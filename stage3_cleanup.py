"""Stage 3 final cleanup maintenance helpers.

These helpers are intentionally deterministic and metadata-only. They do not
call models, execute commands, delete files, or write outside the project root.
"""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONTROLLED_FIXTURE_LABEL = "stage39-health"
QUARANTINE_LABEL = "health-fixture-quarantined"
CONTROLLED_TASK_PREFIX = "stage39 health scenario:"
ACTIVE_IMPORT_STATUSES = {
    "CREATED",
    "HANDOFF_READY",
    "WAITING_FOR_EXTERNAL_AGENT",
    "COMPLETION_IMPORTED",
    "REVIEWED",
    "BLOCKED",
    "FAILED",
}
FINAL_JOB_STATUS = {
    "APPROVED": "APPROVED",
    "BLOCKED": "BLOCKED",
    "REJECTED": "REVIEWED",
    "REVIEW_INCONSISTENT": "REVIEWED",
    "FAILED": "FAILED",
}


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _columns(conn, table):
    try:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    except Exception:
        return set()


def _has_table(conn, table):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _truthy(value):
    return str(value).lower() in ("1", "true", "yes", "y")


def _labels(row):
    raw = row["labels_json"] if "labels_json" in row.keys() else ""
    try:
        data = json.loads(raw or "[]")
        return [str(x) for x in data] if isinstance(data, list) else []
    except (TypeError, ValueError):
        return []


def _loop_task(conn, loop_id):
    if loop_id is None or not _has_table(conn, "loops"):
        return ""
    row = conn.execute("SELECT task FROM loops WHERE id=?", (loop_id,)).fetchone()
    return (row["task"] if row and "task" in row.keys() else "") or ""


def is_controlled_health_fixture(conn, job_row) -> bool:
    labels = set(_labels(job_row))
    if CONTROLLED_FIXTURE_LABEL in labels or QUARANTINE_LABEL in labels:
        return True
    if _loop_task(conn, job_row["loop_id"]).startswith(CONTROLLED_TASK_PREFIX):
        return True
    # One controlled Stage 3.9 fixture intentionally references a missing loop,
    # has no packet/handoff paths, and therefore cannot carry the loop task
    # marker. Treat it as controlled only when it shares an exact created_at with
    # labelled Stage 3.9 fixtures from the same generated batch.
    if (job_row["loop_id"] if "loop_id" in job_row.keys() else None) is not None:
        if _loop_task(conn, job_row["loop_id"]):
            return False
    if (job_row["handoff_path"] if "handoff_path" in job_row.keys() else None):
        return False
    if (job_row["packet_path"] if "packet_path" in job_row.keys() else None):
        return False
    created_at = job_row["created_at"] if "created_at" in job_row.keys() else None
    if not created_at or not _has_table(conn, "external_agent_jobs"):
        return False
    rows = conn.execute(
        "SELECT labels_json FROM external_agent_jobs WHERE created_at=?", (created_at,)
    ).fetchall()
    for row in rows:
        if CONTROLLED_FIXTURE_LABEL in set(_labels(row)):
            return True
    return False


@dataclass
class QuarantineItem:
    job_id: int
    loop_id: Optional[int]
    status: str
    already_quarantined: bool
    reason: str


@dataclass
class QuarantineReport:
    dry_run: bool
    items: List[QuarantineItem] = field(default_factory=list)
    changed_count: int = 0


def _append_note(existing):
    marker = "[quarantined Stage 3.9 controlled health fixture]"
    existing = existing or ""
    if marker in existing:
        return existing
    return (existing + "\n" + marker).strip()


def _save_job_event(conn, job_id, loop_id, event_type, before, after, details):
    if not _has_table(conn, "external_agent_job_events"):
        return
    cols = _columns(conn, "external_agent_job_events")
    if {"job_id", "loop_id", "event_type", "status_before", "status_after", "details_json"} <= cols:
        conn.execute(
            "INSERT INTO external_agent_job_events "
            "(job_id, loop_id, event_type, status_before, status_after, details_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, loop_id, event_type, before, after, json.dumps(details or {})),
        )


def quarantine_health_fixtures(conn, dry_run=False) -> QuarantineReport:
    report = QuarantineReport(dry_run=dry_run)
    if not _has_table(conn, "external_agent_jobs"):
        return report
    rows = conn.execute("SELECT * FROM external_agent_jobs ORDER BY id").fetchall()
    job_cols = _columns(conn, "external_agent_jobs")
    for row in rows:
        if not is_controlled_health_fixture(conn, row):
            continue
        labels = _labels(row)
        already = _truthy(row["archived"] if "archived" in row.keys() else 0) and (
            QUARANTINE_LABEL in labels
        )
        report.items.append(
            QuarantineItem(
                job_id=row["id"],
                loop_id=row["loop_id"] if "loop_id" in row.keys() else None,
                status=row["status"] if "status" in row.keys() else "",
                already_quarantined=already,
                reason="controlled Stage 3.9 health fixture",
            )
        )
        if dry_run or already:
            continue

        fields = {}
        if "archived" in job_cols:
            fields["archived"] = "1"
        if "archived_at" in job_cols:
            fields["archived_at"] = _now()
        if "notes" in job_cols:
            fields["notes"] = _append_note(row["notes"] if "notes" in row.keys() else "")
        if "labels_json" in job_cols:
            new_labels = labels[:]
            if QUARANTINE_LABEL not in new_labels:
                new_labels.append(QUARANTINE_LABEL)
            fields["labels_json"] = json.dumps(new_labels)
        if "updated_at" in job_cols:
            fields["updated_at"] = _now()
        if fields:
            assignments = ", ".join(f"{k}=?" for k in fields)
            conn.execute(
                f"UPDATE external_agent_jobs SET {assignments} WHERE id=?",
                tuple(fields.values()) + (row["id"],),
            )
        _save_job_event(
            conn,
            row["id"],
            row["loop_id"] if "loop_id" in row.keys() else None,
            "health_fixture_quarantined",
            row["status"] if "status" in row.keys() else None,
            row["status"] if "status" in row.keys() else None,
            {"reason": "controlled Stage 3.9 health fixture", "dry_run": False},
        )
        report.changed_count += 1
    if not dry_run:
        conn.commit()
    return report


@dataclass
class PortablePathItem:
    table: str
    row_id: int
    column: str
    old_path: str
    new_path: Optional[str]
    repairable: bool
    repaired: bool = False
    warning: str = ""
    quarantined: bool = False


@dataclass
class PortablePathReport:
    dry_run: bool
    project_root: str
    items: List[PortablePathItem] = field(default_factory=list)

    @property
    def stale_count(self):
        return len(self.items)

    @property
    def repairable_count(self):
        return sum(1 for i in self.items if i.repairable and not i.quarantined)

    @property
    def repaired_count(self):
        return sum(1 for i in self.items if i.repaired)

    @property
    def warning_count(self):
        return sum(1 for i in self.items if i.warning and not i.quarantined)

    @property
    def quarantined_count(self):
        return sum(1 for i in self.items if i.quarantined)


def _within(path, root):
    real = os.path.realpath(path)
    base = os.path.realpath(root)
    return real == base or real.startswith(base + os.sep)


def _candidate_for(path, project_root):
    parts = os.path.realpath(path).split(os.sep)
    for anchor in (
        "external_agent_jobs",
        "external_agent_handoffs",
        "external_batch_reports",
        "reports",
    ):
        if anchor in parts:
            rel = os.path.join(*parts[parts.index(anchor):])
            candidate = os.path.realpath(os.path.join(project_root, rel))
            if _within(candidate, project_root) and os.path.exists(candidate):
                return candidate
            return None
    return None


def _hashed_run_report_candidate(row, project_root):
    if "loop_id" not in row.keys() or row["loop_id"] is None:
        return None
    if "content_hash" not in row.keys() or not row["content_hash"]:
        return None
    reports_dir = os.path.join(project_root, "reports")
    if not os.path.isdir(reports_dir):
        return None
    prefix = f"loop_{row['loop_id']}_"
    matches = []
    for name in os.listdir(reports_dir):
        if not (name.startswith(prefix) and name.endswith(".md")):
            continue
        candidate = os.path.realpath(os.path.join(reports_dir, name))
        if not _within(candidate, project_root) or not os.path.isfile(candidate):
            continue
        try:
            with open(candidate, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        if "bytes_written" in row.keys() and row["bytes_written"] is not None:
            try:
                if len(data) != int(row["bytes_written"]):
                    continue
            except (TypeError, ValueError):
                pass
        if hashlib.sha256(data).hexdigest() == row["content_hash"]:
            matches.append(candidate)
    return sorted(matches)[-1] if matches else None


def _candidate_for_row(table, row, column, project_root):
    candidate = _candidate_for(row[column], project_root)
    if candidate:
        return candidate
    if table == "run_reports" and column == "report_path":
        return _hashed_run_report_candidate(row, project_root)
    return None


def _path_sources(conn):
    sources = []
    if _has_table(conn, "external_agent_jobs"):
        cols = _columns(conn, "external_agent_jobs")
        for col in ("handoff_path", "packet_path", "completion_path"):
            if col in cols:
                sources.append(("external_agent_jobs", "id", col))
    if _has_table(conn, "external_agent_events") and "handoff_path" in _columns(conn, "external_agent_events"):
        sources.append(("external_agent_events", "id", "handoff_path"))
    if _has_table(conn, "run_reports") and "report_path" in _columns(conn, "run_reports"):
        sources.append(("run_reports", "id", "report_path"))
    if _has_table(conn, "external_batch_reports") and "report_path" in _columns(conn, "external_batch_reports"):
        sources.append(("external_batch_reports", "id", "report_path"))
    if _has_table(conn, "external_completion_inbox_events") and "completion_path" in _columns(conn, "external_completion_inbox_events"):
        sources.append(("external_completion_inbox_events", "id", "completion_path"))
    return sources


def _quarantined_for_path_row(conn, table, row):
    if table == "external_agent_jobs":
        return is_controlled_health_fixture(conn, row) and _truthy(row["archived"] if "archived" in row.keys() else 0)
    job_id = row["job_id"] if "job_id" in row.keys() else None
    if job_id and _has_table(conn, "external_agent_jobs"):
        j = conn.execute("SELECT * FROM external_agent_jobs WHERE id=?", (job_id,)).fetchone()
        if j:
            return is_controlled_health_fixture(conn, j) and _truthy(j["archived"] if "archived" in j.keys() else 0)
    loop_id = row["loop_id"] if "loop_id" in row.keys() else None
    if loop_id and _loop_task(conn, loop_id).startswith(CONTROLLED_TASK_PREFIX):
        return True
    return False


def repair_portable_paths(conn, project_root=PROJECT_ROOT, dry_run=True) -> PortablePathReport:
    root = os.path.realpath(project_root)
    report = PortablePathReport(dry_run=dry_run, project_root=root)
    for table, pk, col in _path_sources(conn):
        rows = conn.execute(f"SELECT * FROM {table} WHERE {col} IS NOT NULL AND {col} != ''").fetchall()
        for row in rows:
            old = row[col]
            if not os.path.isabs(old) or _within(old, root):
                continue
            new = _candidate_for_row(table, row, col, root)
            quarantined = _quarantined_for_path_row(conn, table, row)
            warning = "" if new or quarantined else "absolute path outside project root; no matching local file"
            item = PortablePathItem(
                table=table,
                row_id=row[pk],
                column=col,
                old_path=old,
                new_path=new,
                repairable=bool(new),
                warning=warning,
                quarantined=quarantined,
            )
            if new and not dry_run:
                conn.execute(f"UPDATE {table} SET {col}=? WHERE {pk}=?", (new, row[pk]))
                item.repaired = True
            report.items.append(item)
    if not dry_run:
        conn.commit()
    return report


def check_portable_paths(conn, project_root=PROJECT_ROOT) -> PortablePathReport:
    return repair_portable_paths(conn, project_root=project_root, dry_run=True)


def select_job_for_loop_import(conn, loop_id) -> Tuple[Optional[object], Optional[str]]:
    if not _has_table(conn, "external_agent_jobs"):
        return None, None
    rows = conn.execute(
        "SELECT * FROM external_agent_jobs WHERE loop_id=? ORDER BY id DESC", (loop_id,)
    ).fetchall()
    if not rows:
        return None, None
    active = [
        r for r in rows
        if (r["status"] in ACTIVE_IMPORT_STATUSES)
        and not _truthy(r["archived"] if "archived" in r.keys() else 0)
    ]
    if len(active) == 1:
        return active[0], None
    if len(active) > 1:
        ids = ", ".join(str(r["id"]) for r in active)
        return None, f"multiple active linked external jobs for loop {loop_id}: {ids}"
    if len(rows) == 1:
        return rows[0], None
    ids = ", ".join(str(r["id"]) for r in rows)
    return None, f"multiple linked external jobs for loop {loop_id}: {ids}"


def update_linked_job_after_loop_import(conn, job_row, completion_path, resume_status, stop_reason):
    if job_row is None:
        return None
    status_after = FINAL_JOB_STATUS.get(resume_status, "REVIEWED")
    before = job_row["status"] if "status" in job_row.keys() else None
    cols = _columns(conn, "external_agent_jobs")
    fields = {}
    if "status" in cols:
        fields["status"] = status_after
    if completion_path and "completion_path" in cols:
        fields["completion_path"] = completion_path
    if resume_status == "APPROVED" and "completed_at" in cols:
        fields["completed_at"] = _now()
    if resume_status == "FAILED" and "last_error" in cols:
        fields["last_error"] = f"import ended {resume_status}: {stop_reason}"
    if "updated_at" in cols:
        fields["updated_at"] = _now()
    if fields:
        assignments = ", ".join(f"{k}=?" for k in fields)
        conn.execute(
            f"UPDATE external_agent_jobs SET {assignments} WHERE id=?",
            tuple(fields.values()) + (job_row["id"],),
        )
    _save_job_event(
        conn,
        job_row["id"],
        job_row["loop_id"] if "loop_id" in job_row.keys() else None,
        "loop_import_external_completion",
        before,
        status_after,
        {
            "completion_path": completion_path,
            "resume_status": resume_status,
            "stop_reason": stop_reason,
        },
    )
    conn.commit()
    return status_after
