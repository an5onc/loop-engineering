"""Context Packs (Stage 2.8): bounded, safe file-level context for agents.

Selects relevant workspace files (from explicit paths, project intelligence,
memory search, task keywords, and common entrypoints), reads bounded excerpts,
and produces a ContextPack for agent prompts. Read-only and bounded: honors
allowed_read_paths, skips protected/.git/.env/secrets/node_modules/venvs, binary
files, files > 250 KB, and symlink escapes; never executes, writes, or calls
Ollama; never reads paths chosen directly by model output.
"""

import datetime
import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

import project_workspace
from project_intelligence import LANG_BY_EXT, MAX_FILE_BYTES

DEFAULT_MAX_FILES = 8
DEFAULT_MAX_TOTAL_CHARS = 24000
DEFAULT_MAX_CHARS_PER_FILE = 6000


@dataclass
class ContextPackRequest:
    workspace_name: str
    task: str
    explicit_paths: List[str] = field(default_factory=list)
    max_files: int = DEFAULT_MAX_FILES
    max_total_chars: int = DEFAULT_MAX_TOTAL_CHARS
    max_chars_per_file: int = DEFAULT_MAX_CHARS_PER_FILE
    include_tests: bool = True
    include_docs: bool = True
    include_configs: bool = True
    include_source: bool = True
    use_project_intelligence: bool = True
    use_memory_search: bool = True
    created_at: str = ""


@dataclass
class ContextPackFile:
    path: str
    file_type: str
    detected_language: str
    size_bytes: int
    line_count: int
    content_hash: str
    included_chars: int
    truncated: bool
    relevance_score: float
    reason: str
    content: str = ""  # transient — for prompts only, never persisted


@dataclass
class ContextPack:
    workspace_name: str
    generated_at: str
    task: str
    files: List[ContextPackFile]
    total_files_considered: int
    total_files_included: int
    total_chars: int
    truncated: bool
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    safe: bool = True


def _lang(path):
    return LANG_BY_EXT.get(os.path.splitext(path)[1].lower(), "unknown")


def _terms(task):
    return [t for t in re.split(r"\W+", (task or "").lower()) if len(t) > 2]


def _excerpt(content, max_chars):
    if len(content) <= max_chars:
        return content, False
    half = max_chars // 2
    head = content[:half]
    tail = content[-half:]
    # trim to line boundaries where practical
    if "\n" in head:
        head = head[:head.rfind("\n")]
    if "\n" in tail:
        tail = tail[tail.find("\n") + 1:]
    return head + "\n…(truncated)…\n" + tail, True


class ContextPackBuilder:
    def __init__(self, conn):
        self.conn = conn
        self._mgr = project_workspace.WorkspaceManager()

    def _safe_read(self, ws, rel):
        """(ok, content_or_reason). Read-only, bounded, protected-aware."""
        if not rel or "\x00" in str(rel):
            return False, "empty/null path"
        rel = str(rel).strip()
        if os.path.isabs(rel) or rel.startswith("~") or ".." in rel.split("/"):
            return False, "unsafe path (absolute/home/traversal)"
        target = os.path.realpath(os.path.join(ws.root_path, rel))
        root = os.path.realpath(ws.root_path)
        if target != root and not target.startswith(root + os.sep):
            return False, "outside workspace root"
        if not self._mgr.is_path_allowed_for_read(ws, target):
            return False, "outside allowed read paths"
        rel_to_root = os.path.relpath(target, root)
        if project_workspace.is_protected_path(rel_to_root):
            return False, "protected path"
        if not os.path.isfile(target):
            return False, "not a file"
        try:
            if os.path.getsize(target) > MAX_FILE_BYTES:
                return False, "file too large (>250 KB)"
            with open(target, "rb") as fh:
                chunk = fh.read(MAX_FILE_BYTES + 1)
        except OSError as exc:
            return False, f"read error: {exc}"
        if b"\x00" in chunk:
            return False, "binary file"
        try:
            return True, chunk.decode("utf-8")
        except UnicodeDecodeError:
            return False, "non-text file"

    def build(self, req: ContextPackRequest, ws, loop_type=None) -> ContextPack:
        import database
        terms = _terms(req.task)
        task_l = (req.task or "").lower()
        candidates = {}   # path -> dict(file_type, language, score, reason, explicit)
        warnings, recs = [], []

        def add(path, ft, lang, score, reason, explicit=False):
            c = candidates.get(path)
            if c is None:
                candidates[path] = dict(file_type=ft, language=lang, score=score,
                                        reason=reason, explicit=explicit)
            else:
                if score > c["score"]:
                    c["score"] = score
                c["explicit"] = c["explicit"] or explicit

        # 1) explicit user paths (validated at read time).
        for p in (req.explicit_paths or []):
            add(p, "explicit", _lang(p), 2.0, "explicitly requested", explicit=True)

        # 2) project intelligence files.
        if req.use_project_intelligence:
            pi = database.get_latest_project_intelligence_report(self.conn, ws.name)
            if pi is not None:
                import json
                rj = json.loads(pi["report_json"] or "{}")
                important = set(rj.get("structure", {}).get("important_files", []))
                for f in rj.get("files", []):
                    ft = f.get("file_type", "other")
                    if ft == "test" and not req.include_tests:
                        continue
                    if ft == "doc" and not req.include_docs:
                        continue
                    if ft == "config" and not req.include_configs:
                        continue
                    if ft == "source" and not req.include_source:
                        continue
                    path = f["path"]
                    score = 0.4 if path in important else 0.2
                    if any(t in path.lower() for t in terms):
                        score += 0.3
                    if any(t in (f.get("content_preview") or "").lower() for t in terms):
                        score += 0.2
                    if loop_type == "test_fix" and ft == "test":
                        score += 0.2
                    if loop_type in ("prompt_design", "loop_design", "code_review") and ft == "doc":
                        score += 0.2
                    if ft == "config" and any(w in task_l for w in
                                              ("setup", "build", "dependenc", "install")):
                        score += 0.2
                    add(path, ft, f.get("detected_language", "unknown"),
                        round(score, 3), f"project intelligence ({ft})")

        # 3) memory-search relevant file paths.
        if req.use_memory_search:
            try:
                import memory_search
                eng = memory_search.MemorySearchEngine(self.conn)
                mr = eng.search(memory_search.MemorySearchQuery(
                    query=req.task, workspace_name=ws.name, limit=10,
                    source_types=["files"]))
                for r in mr:
                    if r.title.startswith("file: "):
                        add(r.title[len("file: "):], "memory", _lang(r.title),
                            0.3, "relevant in project memory")
            except Exception:
                pass

        # 4) common entrypoints.
        for ep in ("README.md", "main.py", "app.py"):
            add(ep, "entry", _lang(ep), 0.25, "common entrypoint")

        considered = len(candidates)
        ranked = sorted(candidates.items(), key=lambda kv: kv[1]["score"], reverse=True)

        files: List[ContextPackFile] = []
        total = 0
        skipped = 0
        explicit_total = sum(1 for c in candidates.values() if c["explicit"])
        explicit_blocked = 0

        for path, info in ranked:
            if len(files) >= req.max_files:
                skipped += 1
                continue
            ok, content = self._safe_read(ws, path)
            if not ok:
                if info["explicit"]:
                    explicit_blocked += 1
                    warnings.append(f"blocked explicit file '{path}': {content}")
                # non-explicit unreadable files are silently skipped (entrypoints
                # that don't exist are common); only note protected ones.
                elif "protected" in content:
                    warnings.append(f"skipped protected '{path}'")
                continue
            excerpt, truncated = _excerpt(content, req.max_chars_per_file)
            inc = len(excerpt)
            if total + inc > req.max_total_chars:
                skipped += 1
                warnings.append(f"skipped '{path}' (total-char budget)")
                continue
            total += inc
            files.append(ContextPackFile(
                path=path, file_type=info["file_type"],
                detected_language=info["language"],
                size_bytes=len(content.encode("utf-8")),
                line_count=content.count("\n") + 1,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
                included_chars=inc, truncated=truncated,
                relevance_score=info["score"], reason=info["reason"],
                content=excerpt))

        if skipped:
            warnings.append(f"{skipped} lower-relevance file(s) skipped due to limits")
        safe = not (explicit_total > 0 and explicit_blocked == explicit_total)
        if not safe:
            warnings.append("all explicitly requested files were unsafe/blocked")
        if not files:
            recs.append("No safe context files selected; run --scan-project for richer context.")

        return ContextPack(
            workspace_name=ws.name,
            generated_at=datetime.datetime.now().isoformat(timespec="seconds"),
            task=req.task, files=files, total_files_considered=considered,
            total_files_included=len(files), total_chars=total,
            truncated=any(f.truncated for f in files), warnings=warnings,
            recommendations=recs, safe=safe)


def format_context_summary(pack: ContextPack) -> str:
    if pack is None or not pack.files:
        return "CONTEXT PACK SUMMARY:\n- (no context files included)"
    lines = ["CONTEXT PACK SUMMARY:", f"- Files included: {pack.total_files_included}"]
    for f in pack.files:
        lines.append(f"  - {f.path} ({f.detected_language}) — {f.reason}")
    lines.append(f"- Warnings: {'; '.join(pack.warnings) if pack.warnings else '(none)'}")
    lines.append(f"- Total chars: {pack.total_chars}")
    lines.append(f"- Truncated: {'yes' if pack.truncated else 'no'}")
    return "\n".join(lines)


def format_file_context(pack: ContextPack) -> str:
    if pack is None or not pack.files:
        return ""
    blocks = ["RELEVANT FILE CONTEXT:"]
    for f in pack.files:
        blocks.append(
            f"### {f.path} ({f.detected_language}) — {f.reason}"
            f"{' [truncated]' if f.truncated else ''}\n```\n{f.content}\n```")
    return "\n\n".join(blocks)
