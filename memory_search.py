"""Project Memory Search (Stage 2.7): search prior runs using SQLite only.

Read-only search across loops, steps, reviews, command results, file operations,
run reports, project-intelligence reports, and file summaries. No embeddings, no
Ollama, no external packages, no writes, no command execution. Report file bodies
are only read from internally-generated reports/ paths.
"""

import datetime
import json
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

# Internal reports dir (only place report file bodies may be read from).
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_REPORTS_DIR = os.path.realpath(os.path.join(_PROJECT_ROOT, "reports"))

CANDIDATE_LIMIT = 600  # rows scanned per source before Python-side ranking

ALL_SOURCES = {"loops", "steps", "reviews", "command_results", "file_operations",
               "run_reports", "project_intelligence_reports", "project_file_summaries"}

# CLI --source value -> internal source keys
SOURCE_ALIASES = {
    "all": set(ALL_SOURCES),
    "loops": {"loops"},
    "steps": {"steps"},
    "reviews": {"reviews"},
    "commands": {"command_results"},
    "files": {"file_operations", "project_file_summaries"},
    "reports": {"run_reports"},
    "project_intel": {"project_intelligence_reports"},
}


@dataclass
class MemorySearchQuery:
    query: str
    workspace_name: Optional[str] = None
    loop_type: Optional[str] = None
    source_types: List[str] = field(default_factory=lambda: ["all"])
    limit: int = 10
    include_reports: bool = True
    include_steps: bool = True
    include_reviews: bool = True
    include_commands: bool = True
    include_files: bool = True
    include_project_intel: bool = True
    created_at: str = ""


@dataclass
class MemorySearchResult:
    source_type: str
    source_id: int
    loop_id: Optional[int]
    workspace_name: Optional[str]
    title: str
    snippet: str
    score: float
    created_at: str
    metadata_json: str = "{}"


def _terms(q: str):
    return [t for t in re.split(r"\s+", (q or "").strip().lower()) if t]


def _snippet(text: str, terms, width=160) -> str:
    t = text or ""
    low = t.lower()
    pos = -1
    for term in terms:
        i = low.find(term)
        if i != -1 and (pos == -1 or i < pos):
            pos = i
    if pos == -1:
        return t[:width].replace("\n", " ").strip()
    start = max(0, pos - 40)
    return ("…" if start > 0 else "") + t[start:start + width].replace("\n", " ").strip()


def _score(terms, phrase, text, title, ws_match, recency_id):
    t = (text or "").lower()
    ti = (title or "").lower()
    score = 0.0
    if phrase and phrase in t:
        score += 5.0
    if phrase and phrase in ti:
        score += 3.0
    matched = sum(1 for term in terms if term in t)
    if terms:
        if matched == len(terms):
            score += 3.0
        elif matched > 0:
            score += 2.0 * matched / len(terms)
    score += 0.5 * sum(1 for term in terms if term in ti)
    if ws_match:
        score += 1.0
    score += min(1.0, (recency_id or 0) * 0.0005)  # small recency tiebreak
    return score, matched


def _sources_for(source_types):
    out = set()
    for s in (source_types or ["all"]):
        out |= SOURCE_ALIASES.get(s, set())
    return out or set(ALL_SOURCES)


class MemorySearchEngine:
    def __init__(self, conn):
        self.conn = conn

    def search(self, q: MemorySearchQuery) -> List[MemorySearchResult]:
        terms = _terms(q.query)
        if not terms:
            return []
        phrase = q.query.strip().lower()
        sources = _sources_for(q.source_types)
        results: List[MemorySearchResult] = []

        def consider(source_type, sid, loop_id, ws, title, text, created, meta):
            ws_match = bool(q.workspace_name) and ws == q.workspace_name
            sc, matched = _score(terms, phrase, text, title, ws_match, sid)
            if matched == 0 and not (phrase and phrase in (text or "").lower()):
                return
            results.append(MemorySearchResult(
                source_type=source_type, source_id=sid, loop_id=loop_id,
                workspace_name=ws, title=title, snippet=_snippet(text, terms),
                score=round(sc, 3), created_at=created or "",
                metadata_json=json.dumps(meta)))

        wfilter = q.workspace_name
        ltfilter = q.loop_type

        if "loops" in sources:
            self._search_loops(wfilter, ltfilter, consider)
        if "steps" in sources and q.include_steps:
            self._search_child("steps", wfilter, ltfilter, consider)
        if "reviews" in sources and q.include_reviews:
            self._search_child("reviews", wfilter, ltfilter, consider)
        if "command_results" in sources and q.include_commands:
            self._search_child("command_results", wfilter, ltfilter, consider)
        if "file_operations" in sources and q.include_files:
            self._search_child("file_operations", wfilter, ltfilter, consider)
        if "run_reports" in sources and q.include_reports:
            self._search_reports(wfilter, ltfilter, consider)
        if "project_intelligence_reports" in sources and q.include_project_intel:
            self._search_intel(wfilter, consider)
        if "project_file_summaries" in sources and q.include_files:
            self._search_file_summaries(wfilter, consider)

        results.sort(key=lambda r: r.score, reverse=True)
        return results[: q.limit]

    # --- per-source ------------------------------------------------------ #
    def _rows(self, sql, params):
        return self.conn.execute(sql, params).fetchall()

    def _search_loops(self, ws, lt, consider):
        sql = "SELECT * FROM loops WHERE 1=1"
        p = []
        if ws:
            sql += " AND workspace_name=?"; p.append(ws)
        if lt:
            sql += " AND loop_type=?"; p.append(lt)
        sql += " ORDER BY id DESC LIMIT ?"; p.append(CANDIDATE_LIMIT)
        for r in self._rows(sql, p):
            text = " ".join(str(r[k] or "") for k in (
                "task", "status", "stop_reason", "loop_type", "template_name",
                "rendered_task"))
            title = f"loop #{r['id']}: {(r['task'] or '')[:60]}"
            consider("loops", r["id"], r["id"], r["workspace_name"], title, text,
                     r["created_at"], {"status": r["status"], "loop_type": r["loop_type"]})

    def _search_child(self, table, ws, lt, consider):
        text_cols = {
            "steps": ("prompt", "response", "step_name", "agent_role", "model"),
            "reviews": ("summary", "issues_json", "required_changes_json", "stop_reason"),
            "command_results": ("command", "stdout", "stderr", "reason_if_blocked"),
            "file_operations": ("path", "operation", "reason_if_blocked", "content_hash"),
        }[table]
        sql = (f"SELECT c.*, l.workspace_name AS ws, l.loop_type AS lt "
               f"FROM {table} c JOIN loops l ON l.id=c.loop_id WHERE 1=1")
        p = []
        if ws:
            sql += " AND l.workspace_name=?"; p.append(ws)
        if lt:
            sql += " AND l.loop_type=?"; p.append(lt)
        sql += " ORDER BY c.id DESC LIMIT ?"; p.append(CANDIDATE_LIMIT)
        for r in self._rows(sql, p):
            text = " ".join(str(r[k] or "") for k in text_cols)
            title = f"{table} #{r['id']} (loop #{r['loop_id']})"
            consider(table, r["id"], r["loop_id"], r["ws"], title, text,
                     r["created_at"], {"loop_type": r["lt"]})

    def _search_reports(self, ws, lt, consider):
        sql = ("SELECT r.*, l.workspace_name AS ws, l.loop_type AS lt "
               "FROM run_reports r JOIN loops l ON l.id=r.loop_id WHERE 1=1")
        p = []
        if ws:
            sql += " AND l.workspace_name=?"; p.append(ws)
        if lt:
            sql += " AND l.loop_type=?"; p.append(lt)
        sql += " ORDER BY r.id DESC LIMIT ?"; p.append(CANDIDATE_LIMIT)
        for r in self._rows(sql, p):
            body = self._safe_read_report(r["report_path"])
            text = " ".join([str(r["report_path"] or ""), str(r["report_format"] or ""), body])
            title = f"report (loop #{r['loop_id']})"
            consider("run_reports", r["id"], r["loop_id"], r["ws"], title, text,
                     r["created_at"], {"path": r["report_path"]})

    def _search_intel(self, ws, consider):
        sql = "SELECT * FROM project_intelligence_reports WHERE 1=1"
        p = []
        if ws:
            sql += " AND workspace_name=?"; p.append(ws)
        sql += " ORDER BY id DESC LIMIT ?"; p.append(CANDIDATE_LIMIT)
        for r in self._rows(sql, p):
            text = " ".join(str(r[k] or "") for k in (
                "languages_json", "important_files_json", "recommendations_json",
                "warnings_json", "report_json"))
            title = f"project intel #{r['id']} ({r['workspace_name']})"
            consider("project_intelligence_reports", r["id"], None,
                     r["workspace_name"], title, text, r["created_at"],
                     {"generated_at": r["generated_at"]})

    def _search_file_summaries(self, ws, consider):
        sql = "SELECT * FROM project_file_summaries WHERE 1=1"
        p = []
        if ws:
            sql += " AND workspace_name=?"; p.append(ws)
        sql += " ORDER BY id DESC LIMIT ?"; p.append(CANDIDATE_LIMIT)
        for r in self._rows(sql, p):
            text = " ".join(str(r[k] or "") for k in (
                "path", "file_type", "detected_language", "reason", "content_preview"))
            title = f"file: {r['path']}"
            consider("project_file_summaries", r["id"], None, r["workspace_name"],
                     title, text, r["created_at"], {"importance": r["importance_score"]})

    @staticmethod
    def _safe_read_report(path):
        """Only read report bodies from inside the internal reports/ dir."""
        if not path:
            return ""
        real = os.path.realpath(path)
        if real != _REPORTS_DIR and not real.startswith(_REPORTS_DIR + os.sep):
            return ""
        if not os.path.isfile(real):
            return ""
        try:
            with open(real, "r", encoding="utf-8") as fh:
                return fh.read(20000)
        except OSError:
            return ""


def format_memory_context(results: List[MemorySearchResult]) -> str:
    """Concise MEMORY CONTEXT block for the Supervisor prompt (no full bodies)."""
    if not results:
        return ("MEMORY CONTEXT:\n- (no relevant memory found; proceed normally)")

    def bucket(types, n=2):
        out = [r for r in results if r.source_type in types][:n]
        return out

    def fmt(rs):
        if not rs:
            return "  (none)"
        return "\n".join(f"  - {r.title} :: {r.snippet[:120]}" for r in rs)

    lines = [
        "MEMORY CONTEXT:",
        "- Similar past loops:",
        fmt(bucket({"loops"})),
        "- Relevant past failures:",
        fmt(bucket({"command_results"})),
        "- Relevant reviews:",
        fmt(bucket({"reviews"})),
        "- Relevant reports:",
        fmt(bucket({"run_reports"})),
        "- Relevant project intelligence:",
        fmt(bucket({"project_intelligence_reports", "project_file_summaries"})),
        "- Notes: based on prior runs in this project's memory.",
    ]
    return "\n".join(lines)
