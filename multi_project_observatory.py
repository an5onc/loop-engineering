"""Stage 7.2 — Multi-Project Observatory (read-only dashboard).

Aggregates registry, validation, and local DB metadata across all registered
projects into a snapshot. This module is metadata-only: it reads no project file
contents, runs no commands, calls no model, and mutates nothing except its own
observatory snapshot/report rows and Markdown reports under
``multi_project_observatory_reports/``.
"""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

import database
import multi_project_registry as registry_mod


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "multi_project_observatory_reports")


@dataclass
class MultiProjectObservatorySnapshot:
    id: int
    generated_at: str
    summary: dict = field(default_factory=dict)
    projects: List[dict] = field(default_factory=list)
    filters: dict = field(default_factory=dict)


@dataclass
class MultiProjectObservatoryReport:
    snapshot_id: int
    report_path: str
    report_format: str
    content_hash: str
    bytes_written: int
    created_at: str


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def is_report_path(path) -> bool:
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


def _within(child, parent) -> bool:
    if not child or not parent:
        return False
    child = os.path.realpath(child)
    parent = os.path.realpath(parent)
    return child == parent or child.startswith(parent + os.sep)


class MultiProjectObservatory:
    def __init__(self, conn):
        self.conn = conn
        self.registry = registry_mod.ProjectRegistry(conn)

    def build_snapshot(self) -> MultiProjectObservatorySnapshot:
        projects = self.registry.list_projects()
        observations = [self._observe(p) for p in projects]
        by_status = {s: 0 for s in registry_mod.VALID_STATUSES}
        for p in projects:
            by_status[p.status] = by_status.get(p.status, 0) + 1
        stale = sum(1 for o in observations if o["stale"])
        attention = sum(1 for o in observations if o["needs_attention"])
        with_validation = sum(
            1 for o in observations if o["latest_validation_status"] != "(none)")
        summary = {
            "generated_at": _now_iso(),
            "total_projects": len(projects),
            "active": by_status.get("active", 0),
            "paused": by_status.get("paused", 0),
            "archived": by_status.get("archived", 0),
            "blocked": by_status.get("blocked", 0),
            "stale_count": stale,
            "needs_attention_count": attention,
            "projects_with_validation": with_validation,
        }
        return MultiProjectObservatorySnapshot(
            id=0, generated_at=summary["generated_at"], summary=summary,
            projects=observations, filters={})

    def _observe(self, project) -> dict:
        root = project.root_path
        root_exists = bool(root) and os.path.isdir(root)
        stale = not root_exists
        latest = database.latest_project_validation_report(
            self.conn, project.project_key)
        validation_status = latest["overall_status"] if latest else "(none)"
        loop_count = self._loop_count(root)
        job_count = self._external_job_count(root)

        reasons = []
        if stale:
            reasons.append("root missing or stale")
        if project.status == "blocked":
            reasons.append("project status is blocked")
        if validation_status in ("FAIL", "BLOCKED"):
            reasons.append(f"latest validation {validation_status}")
        needs_attention = bool(reasons)
        return {
            "project_key": project.project_key,
            "name": project.name,
            "status": project.status,
            "root_path": root,
            "root_exists": root_exists,
            "stale": stale,
            "latest_validation_status": validation_status,
            "loop_count": loop_count,
            "external_job_count": job_count,
            "needs_attention": needs_attention,
            "attention_reasons": reasons,
        }

    def _loop_count(self, root) -> int:
        if not root:
            return 0
        count = 0
        for row in self.conn.execute(
                "SELECT workspace_root FROM loops WHERE workspace_root IS NOT NULL"):
            if _within(row["workspace_root"], root):
                count += 1
        return count

    def _external_job_count(self, root) -> int:
        if not root:
            return 0
        if not self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='external_agent_jobs'").fetchone():
            return 0
        count = 0
        for row in self.conn.execute(
                "SELECT workspace_root FROM external_agent_jobs "
                "WHERE workspace_root IS NOT NULL"):
            if _within(row["workspace_root"], root):
                count += 1
        return count

    # -- persistence ----------------------------------------------------- #
    def save_snapshot(self, snapshot) -> int:
        snapshot_id = database.save_multi_project_observatory_snapshot(
            self.conn, snapshot.generated_at,
            json.dumps(snapshot.summary, sort_keys=True),
            json.dumps(snapshot.projects, sort_keys=True),
            json.dumps(snapshot.filters, sort_keys=True))
        snapshot.id = snapshot_id
        return snapshot_id

    def get_snapshot(self, snapshot_id) -> Optional[MultiProjectObservatorySnapshot]:
        row = database.get_multi_project_observatory_snapshot(self.conn, snapshot_id)
        if row is None:
            return None
        return MultiProjectObservatorySnapshot(
            id=row["id"], generated_at=row["generated_at"] or "",
            summary=_safe_json_loads(row["summary_json"], {}),
            projects=_safe_json_loads(row["projects_json"], []),
            filters=_safe_json_loads(row["filters_json"], {}))

    def save_report(self, snapshot_id) -> MultiProjectObservatoryReport:
        snapshot = self.get_snapshot(snapshot_id)
        if snapshot is None:
            raise ValueError(f"no observatory snapshot {snapshot_id}")
        content = self.render_markdown(snapshot)
        path = self._new_report_path(snapshot_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_multi_project_observatory_report(
            self.conn, snapshot_id, path, "markdown", chash, nbytes)
        return MultiProjectObservatoryReport(
            snapshot_id=snapshot_id, report_path=path, report_format="markdown",
            content_hash=chash, bytes_written=nbytes, created_at=_now_iso())

    def _new_report_path(self, snapshot_id) -> str:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"multi_project_observatory_{int(snapshot_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("observatory report path escaped reports directory")
        return target

    def render_markdown(self, snapshot) -> str:
        summary = snapshot.summary
        lines = []
        a = lines.append
        a("# Multi-Project Observatory Report")
        a("")
        a("## Summary")
        a(f"- Generated at: {summary.get('generated_at', snapshot.generated_at)}")
        a(f"- Total projects: {summary.get('total_projects', 0)}")
        a(f"- Active: {summary.get('active', 0)}")
        a(f"- Paused: {summary.get('paused', 0)}")
        a(f"- Archived: {summary.get('archived', 0)}")
        a(f"- Blocked: {summary.get('blocked', 0)}")
        a(f"- Stale: {summary.get('stale_count', 0)}")
        a(f"- Needs attention: {summary.get('needs_attention_count', 0)}")
        a(f"- Projects with validation: {summary.get('projects_with_validation', 0)}")
        a("")
        a("## Projects")
        if not snapshot.projects:
            a("- (none registered)")
        for project in snapshot.projects:
            a(f"- {project.get('project_key')} [{project.get('status')}]")
            a(f"  - root: {project.get('root_path')}")
            a(f"  - root exists: {project.get('root_exists')}")
            a(f"  - latest validation: {project.get('latest_validation_status')}")
            a(f"  - loop count: {project.get('loop_count')}")
            a(f"  - external job count: {project.get('external_job_count')}")
            a(f"  - needs attention: {project.get('needs_attention')}")
            if project.get("attention_reasons"):
                a(f"  - reasons: {', '.join(project['attention_reasons'])}")
        a("")
        a("## Safety Notes")
        for note in (
            "Metadata-only read-only dashboard.",
            "No project file contents are read.",
            "No commands executed.",
            "No model calls.",
            "No cross-project mutation.",
        ):
            a(f"- {note}")
        a("")
        return "\n".join(lines)
