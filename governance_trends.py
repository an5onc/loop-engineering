"""Stage 8.5 — Governance Trend Snapshot.

Tracks governance health over time from saved policy evaluations and fleet
governance reports. Trend snapshots record counts only (per-evaluation
pass/warn/fail/waived plus a simple direction) — never file contents or command
output. Metadata-only; writes only snapshot rows and Markdown under
``governance_trend_reports/``.
"""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "governance_trend_reports")


@dataclass
class GovernanceTrendSnapshot:
    id: int
    generated_at: str
    summary: dict = field(default_factory=dict)
    points: List[dict] = field(default_factory=list)


@dataclass
class TrendMarkdownReport:
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


def _direction(points):
    """Compare oldest vs newest failed counts to describe the trend."""
    if len(points) < 2:
        return "insufficient_data"
    oldest = points[0]["failed"]
    newest = points[-1]["failed"]
    if newest < oldest:
        return "improving"
    if newest > oldest:
        return "regressing"
    return "stable"


class GovernanceTrendTracker:
    def __init__(self, conn):
        self.conn = conn

    def build_snapshot(self, limit=50) -> GovernanceTrendSnapshot:
        # Evaluations are returned newest-first; reverse to chronological order.
        rows = list(reversed(
            database.list_governance_policy_evaluations(self.conn, limit=limit)))
        points = [
            {"evaluation_id": r["id"], "generated_at": r["generated_at"],
             "overall_status": r["overall_status"],
             "passed": r["passed_findings"] or 0,
             "warning": r["warning_findings"] or 0,
             "failed": r["failed_findings"] or 0,
             "waived": r["waived_findings"] or 0}
            for r in rows
        ]
        fleet_reports = len(database.list_fleet_governance_reports(self.conn, limit=1000))
        latest = points[-1] if points else {}
        summary = {
            "generated_at": _now_iso(),
            "evaluations": len(points),
            "fleet_reports": fleet_reports,
            "latest_overall_status": latest.get("overall_status", "(none)"),
            "latest_failed": latest.get("failed", 0),
            "direction": _direction(points),
        }
        return GovernanceTrendSnapshot(
            id=0, generated_at=summary["generated_at"], summary=summary,
            points=points)

    def save_snapshot(self, snapshot) -> int:
        snapshot_id = database.save_governance_trend_snapshot(
            self.conn, snapshot.generated_at,
            json.dumps(snapshot.summary, sort_keys=True),
            json.dumps(snapshot.points, sort_keys=True))
        snapshot.id = snapshot_id
        return snapshot_id

    def get_snapshot(self, snapshot_id) -> Optional[GovernanceTrendSnapshot]:
        row = database.get_governance_trend_snapshot(self.conn, snapshot_id)
        if row is None:
            return None
        return GovernanceTrendSnapshot(
            id=row["id"], generated_at=row["generated_at"] or "",
            summary=_safe_json_loads(row["summary_json"], {}),
            points=_safe_json_loads(row["points_json"], []))

    def list_snapshots(self, limit=20):
        return database.list_governance_trend_snapshots(self.conn, limit=limit)

    def save_markdown_report(self, snapshot_id) -> TrendMarkdownReport:
        snapshot = self.get_snapshot(snapshot_id)
        if snapshot is None:
            raise ValueError(f"no governance trend snapshot {snapshot_id}")
        content = self.render_markdown(snapshot)
        path = self._new_report_path(snapshot_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_governance_trend_markdown_report(
            self.conn, snapshot_id, path, "markdown", chash, nbytes)
        return TrendMarkdownReport(
            snapshot_id=snapshot_id, report_path=path, report_format="markdown",
            content_hash=chash, bytes_written=nbytes, created_at=_now_iso())

    def _new_report_path(self, snapshot_id) -> str:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"governance_trend_{int(snapshot_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("governance trend report path escaped directory")
        return target

    def render_markdown(self, snapshot) -> str:
        s = snapshot.summary
        lines = []
        a = lines.append
        a("# Governance Trend Snapshot")
        a("")
        a("## Summary")
        a(f"- Generated at: {s.get('generated_at', snapshot.generated_at)}")
        a(f"- Evaluations tracked: {s.get('evaluations', 0)}")
        a(f"- Fleet reports: {s.get('fleet_reports', 0)}")
        a(f"- Latest overall status: {s.get('latest_overall_status')}")
        a(f"- Latest failed findings: {s.get('latest_failed', 0)}")
        a(f"- Direction: {s.get('direction')}")
        a("")
        a("## Points")
        if not snapshot.points:
            a("- (no evaluations yet)")
        for pt in snapshot.points:
            a(f"- eval #{pt.get('evaluation_id')} {pt.get('generated_at')} "
              f"{pt.get('overall_status')} "
              f"(pass={pt.get('passed')} warn={pt.get('warning')} "
              f"fail={pt.get('failed')} waived={pt.get('waived')})")
        a("")
        a("## Safety Notes")
        for note in (
            "Trend counts only; no file contents or command output.",
            "No commands, no model calls, no cross-project writes.",
        ):
            a(f"- {note}")
        a("")
        return "\n".join(lines)
