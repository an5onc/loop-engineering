"""Project Intelligence (Stage 2.6): read-only workspace scanning.

Scans a workspace's allowed read paths, classifies files, scores importance, and
produces a concise structure summary used to give Supervisor better context.

Safety: read-only. Honors workspace.allowed_read_paths, skips protected paths,
.git/.env/secrets/node_modules/venvs/__pycache__, binary files, files > 250 KB,
and symlinks that escape the root. Never executes files; never calls Ollama.
"""

import datetime
import fnmatch
import hashlib
import os
from dataclasses import dataclass, field
from typing import List

import project_workspace

MAX_FILE_BYTES = 250 * 1024
PREVIEW_LINES = 15
MAX_FILE_SUMMARIES = 60

SOURCE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".html", ".css", ".json", ".sql"}
LANG_BY_EXT = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
    ".jsx": "javascript", ".html": "html", ".css": "css", ".json": "json",
    ".sql": "sql", ".md": "markdown", ".toml": "toml", ".yml": "yaml",
    ".yaml": "yaml", ".sh": "shell",
}
CONFIG_BASENAMES = {
    "pyproject.toml", "package.json", "requirements.txt", "tsconfig.json",
    "dockerfile", "docker-compose.yml", ".gitignore",
}
CONFIG_GLOBS = ["vite.config.*", "tsconfig*.json"]


@dataclass
class ProjectFileSummary:
    path: str
    file_type: str
    size_bytes: int
    line_count: int
    detected_language: str
    importance_score: float
    reason: str
    content_preview: str
    hash: str


@dataclass
class ProjectStructureSummary:
    workspace_name: str
    root_path: str
    total_files_scanned: int
    total_dirs_scanned: int
    ignored_files_count: int
    languages_detected: List[str]
    important_files: List[str]
    test_files: List[str]
    config_files: List[str]
    documentation_files: List[str]
    source_files: List[str]


@dataclass
class ProjectIntelligenceReport:
    workspace_name: str
    generated_at: str
    structure_summary: ProjectStructureSummary
    file_summaries: List[ProjectFileSummary]
    recommendations: List[str]
    warnings: List[str]
    scan_safe: bool = True

    def to_dict(self) -> dict:
        s = self.structure_summary
        return {
            "workspace_name": self.workspace_name,
            "generated_at": self.generated_at,
            "scan_safe": self.scan_safe,
            "structure": {
                "total_files_scanned": s.total_files_scanned,
                "total_dirs_scanned": s.total_dirs_scanned,
                "ignored_files_count": s.ignored_files_count,
                "languages_detected": s.languages_detected,
                "important_files": s.important_files,
                "test_files": s.test_files,
                "config_files": s.config_files,
                "documentation_files": s.documentation_files,
                "source_files": s.source_files,
            },
            "recommendations": self.recommendations,
            "warnings": self.warnings,
            "files": [vars(f) for f in self.file_summaries],
        }


def _is_test(rel: str, base: str) -> bool:
    parts = rel.split("/")
    if "tests" in parts or "test" in parts:
        return True
    if fnmatch.fnmatch(base, "test_*.py") or fnmatch.fnmatch(base, "*_test.py"):
        return True
    if base.endswith(".test.ts") or base.endswith(".spec.ts"):
        return True
    return False


def _is_config(base: str) -> bool:
    if base.lower() in CONFIG_BASENAMES:
        return True
    return any(fnmatch.fnmatch(base, g) for g in CONFIG_GLOBS)


def _is_doc(rel: str, base: str) -> bool:
    parts = rel.split("/")
    return base == "README.md" or base.endswith(".md") or "docs" in parts


def _score(rel: str, base: str, is_test, is_config, is_doc, is_source, changed):
    if base == "README.md":
        score, reason = 0.95, "README"
    elif base.lower() in ("requirements.txt", "package.json", "pyproject.toml"):
        score, reason = 0.9, "dependency manifest"
    elif base in ("main.py", "app.py", "__main__.py") or base.startswith("index."):
        score, reason = 0.85, "entrypoint"
    elif is_config:
        score, reason = 0.8, "config file"
    elif is_test:
        score, reason = 0.6, "test file"
    elif is_source:
        top = rel.split("/")[0]
        if top in ("src", "app", "lib"):
            score, reason = 0.7, "source in src/app/lib"
        else:
            score, reason = 0.5, "source file"
    elif is_doc:
        score, reason = 0.4, "documentation"
    else:
        score, reason = 0.3, "other file"
    if changed:
        score = min(1.0, score + 0.1)
        reason += " (recently changed)"
    return round(score, 2), reason


class ProjectIntelligenceScanner:
    def __init__(self):
        self._mgr = project_workspace.WorkspaceManager()

    def _changed_set(self, ws):
        """Best-effort git-changed relative paths (no error if unavailable)."""
        try:
            import git_tools
            if not git_tools.is_git_repo(ws.root_path):
                return set()
            st = git_tools.git_status(ws.root_path)
            changed = set()
            for line in (st.stdout or "").splitlines():
                p = line[3:] if len(line) > 3 else line
                changed.add(p.strip())
            return changed
        except Exception:
            return set()

    def scan(self, ws) -> ProjectIntelligenceReport:
        root = os.path.realpath(ws.root_path)
        read_dirs = [os.path.realpath(os.path.join(root, p))
                     for p in (ws.allowed_read_paths or ["."])]
        changed = self._changed_set(ws)

        files: List[ProjectFileSummary] = []
        languages = set()
        important, tests, configs, docs, sources = [], [], [], [], []
        n_files = n_dirs = ignored = 0

        for base_dir in read_dirs:
            if not os.path.isdir(base_dir):
                continue
            for dirpath, dirnames, filenames in os.walk(base_dir, followlinks=False):
                # Prune protected / hidden dirs in-place.
                dirnames[:] = [d for d in dirnames
                               if not project_workspace.is_protected_path(d)]
                n_dirs += 1
                for fn in filenames:
                    abs_path = os.path.join(dirpath, fn)
                    rel_root = os.path.relpath(abs_path, root).replace(os.sep, "/")
                    # Read permission + protected + symlink-escape checks.
                    if not self._mgr.is_path_allowed_for_read(ws, abs_path):
                        ignored += 1
                        continue
                    if project_workspace.is_protected_path(rel_root):
                        ignored += 1
                        continue
                    real = os.path.realpath(abs_path)
                    if real != root and not real.startswith(root + os.sep):
                        ignored += 1  # symlink escaped the root
                        continue
                    try:
                        size = os.path.getsize(abs_path)
                    except OSError:
                        ignored += 1
                        continue
                    if size > MAX_FILE_BYTES:
                        ignored += 1
                        continue
                    content = self._read_text(abs_path)
                    if content is None:  # binary / unreadable
                        ignored += 1
                        continue

                    n_files += 1
                    base = fn
                    ext = os.path.splitext(base)[1].lower()
                    lang = LANG_BY_EXT.get(ext, "")
                    if lang:
                        languages.add(lang)
                    is_src = ext in SOURCE_EXTS
                    is_tst = _is_test(rel_root, base)
                    is_cfg = _is_config(base)
                    is_doc = _is_doc(rel_root, base)
                    score, reason = _score(rel_root, base, is_tst, is_cfg, is_doc,
                                           is_src, rel_root in changed)
                    preview = "\n".join(content.splitlines()[:PREVIEW_LINES])
                    files.append(ProjectFileSummary(
                        path=rel_root,
                        file_type=("test" if is_tst else "config" if is_cfg
                                   else "doc" if is_doc else "source" if is_src else "other"),
                        size_bytes=size, line_count=content.count("\n") + 1,
                        detected_language=lang or "unknown",
                        importance_score=score, reason=reason,
                        content_preview=preview,
                        hash=hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]))
                    if is_tst:
                        tests.append(rel_root)
                    if is_cfg:
                        configs.append(rel_root)
                    if is_doc:
                        docs.append(rel_root)
                    if is_src:
                        sources.append(rel_root)
                    if score >= 0.7:
                        important.append(rel_root)

        files.sort(key=lambda f: f.importance_score, reverse=True)
        important.sort()
        structure = ProjectStructureSummary(
            workspace_name=ws.name, root_path=root, total_files_scanned=n_files,
            total_dirs_scanned=n_dirs, ignored_files_count=ignored,
            languages_detected=sorted(languages),
            important_files=important[:25], test_files=sorted(set(tests))[:25],
            config_files=sorted(set(configs))[:25],
            documentation_files=sorted(set(docs))[:25],
            source_files=sorted(set(sources))[:40])

        recs, warns = self._advise(structure)
        return ProjectIntelligenceReport(
            workspace_name=ws.name,
            generated_at=datetime.datetime.now().isoformat(timespec="seconds"),
            structure_summary=structure,
            file_summaries=files[:MAX_FILE_SUMMARIES],
            recommendations=recs, warnings=warns, scan_safe=True)

    @staticmethod
    def _read_text(path):
        try:
            with open(path, "rb") as fh:
                chunk = fh.read(MAX_FILE_BYTES + 1)
        except OSError:
            return None
        if b"\x00" in chunk:
            return None  # binary
        try:
            return chunk.decode("utf-8")
        except UnicodeDecodeError:
            return None  # non-text

    @staticmethod
    def _advise(s: ProjectStructureSummary):
        recs, warns = [], []
        if s.source_files and not s.test_files:
            recs.append("No test files detected — consider adding tests.")
        if "README.md" not in [os.path.basename(d) for d in s.documentation_files]:
            recs.append("No README.md detected — consider adding project docs.")
        if s.config_files:
            recs.append(f"Dependency/config files present: {', '.join(s.config_files[:3])}.")
        if not s.source_files:
            warns.append("No recognizable source files were found.")
        if s.ignored_files_count:
            warns.append(f"{s.ignored_files_count} file(s) ignored "
                         "(protected/binary/oversized/out-of-scope).")
        return recs, warns


def format_project_context(report_dict: dict, profile: str = "") -> str:
    """Build the concise PROJECT CONTEXT block for the Supervisor prompt."""
    st = report_dict.get("structure", {})

    def short(lst, n=8):
        lst = lst or []
        return ", ".join(lst[:n]) + (" …" if len(lst) > n else "") if lst else "(none)"

    lines = [
        "PROJECT CONTEXT:",
        f"- Workspace: {report_dict.get('workspace_name', '?')}",
        f"- Profile: {profile or '(unknown)'}",
        f"- Languages: {', '.join(st.get('languages_detected', [])) or '(none)'}",
        f"- Important files: {short(st.get('important_files'))}",
        f"- Test files: {short(st.get('test_files'))}",
        f"- Config files: {short(st.get('config_files'))}",
        f"- Docs: {short(st.get('documentation_files'))}",
        f"- Warnings: {short(report_dict.get('warnings'), 5)}",
        f"- Recommendations: {short(report_dict.get('recommendations'), 5)}",
    ]
    return "\n".join(lines)
