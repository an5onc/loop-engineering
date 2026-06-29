"""Markdown reports for Loop Observatory snapshots (Stage 4.1).

Reports are generated only from persisted observatory snapshot JSON. This module
does not call models, execute commands, resume jobs, mutate loops/jobs, or accept
user/model-chosen output paths.
"""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Optional

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "observatory_reports")


@dataclass
class ObservatoryReport:
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


def _fmt_filters(filters) -> str:
    if not filters:
        return "(none)"
    parts = []
    for key in ("window", "workspace", "loop_type", "agent"):
        val = filters.get(key)
        if val:
            parts.append(f"{key}={val}")
    return ", ".join(parts) if parts else "(none)"


def _append_rows(lines, rows, fields, empty="(none)"):
    if not rows:
        lines.append(f"- {empty}")
        return
    for row in rows:
        parts = [f"{label}: {row.get(key, default)}" for label, key, default in fields]
        lines.append("- " + ", ".join(parts))


def is_report_path(path) -> bool:
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


class ObservatoryReportGenerator:
    def __init__(self, conn):
        self.conn = conn

    def generate_report(self, snapshot_id):
        snapshot = database.get_observatory_snapshot(self.conn, int(snapshot_id))
        if snapshot is None:
            raise ValueError(f"no observatory snapshot {snapshot_id}")
        content = self._render_markdown(snapshot)
        return self.save_report(int(snapshot_id), content)

    def save_report(self, snapshot_id, content):
        path = self._new_report_path(int(snapshot_id))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_observatory_report(
            self.conn, int(snapshot_id), path, "markdown", chash, nbytes)
        return ObservatoryReport(
            snapshot_id=int(snapshot_id),
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def get_report_path(self, snapshot_id) -> Optional[str]:
        row = database.get_observatory_report(self.conn, int(snapshot_id))
        return row["report_path"] if row else None

    def list_reports(self, limit=20):
        return database.list_observatory_reports(self.conn, limit)

    def _new_report_path(self, snapshot_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"observatory_snapshot_{int(snapshot_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("observatory report path escaped observatory_reports/")
        return target

    def _render_markdown(self, snapshot):
        summary = _safe_json_loads(snapshot["summary_json"], {})
        filters = _safe_json_loads(snapshot["filters_json"], {})
        time_window = summary.get("time_window") or {}
        health = summary.get("external_job_health") or {}
        lines = []
        a = lines.append

        a("# Loop Engineering Observatory Report")
        a("")
        a("## Summary")
        a(f"- Snapshot ID: {snapshot['id']}")
        a(f"- Generated at: {summary.get('generated_at') or snapshot['generated_at']}")
        a(f"- Time window: {snapshot['time_window'] or time_window.get('name') or '(unknown)'}")
        if time_window.get("start_at"):
            a(f"- Window start: {time_window.get('start_at')}")
        if time_window.get("end_at"):
            a(f"- Window end: {time_window.get('end_at')}")
        a(f"- Filters: {_fmt_filters(filters)}")
        a(f"- Total loops: {summary.get('total_loops', 0)}")
        a(f"- Approved loops: {summary.get('approved_loops', 0)}")
        a(f"- Failed loops: {summary.get('failed_loops', 0)}")
        a(f"- Blocked loops: {summary.get('blocked_loops', 0)}")
        a(f"- Needs human loops: {summary.get('needs_human_loops', 0)}")
        a(f"- Paused external loops: {summary.get('paused_external_loops', 0)}")
        a(f"- External jobs: {summary.get('total_external_jobs', 0)}")
        a(f"- Reports: {summary.get('total_reports', 0)}")
        a(f"- Approvals: {summary.get('total_approvals', 0)}")
        a(f"- Declined approvals: {summary.get('declined_approvals', 0)}")
        a(f"- Quality gate failures: {summary.get('quality_gate_failures', 0)}")
        a(f"- Stop condition triggers: {summary.get('stop_condition_triggers', 0)}")
        a("")

        a("## Top Loop Types")
        _append_rows(
            lines,
            summary.get("top_loop_types") or [],
            (("loop type", "loop_type", "(unknown)"),
             ("count", "count", 0),
             ("approval rate", "approval_rate", 0),
             ("failure rate", "failure_rate", 0)),
        )
        a("")

        a("## Top Agents")
        _append_rows(
            lines,
            summary.get("top_agents") or [],
            (("agent", "agent", "(unknown)"),
             ("count", "count", 0),
             ("success rate", "success_rate", 0)),
        )
        a("")

        a("## Top Workspaces")
        _append_rows(
            lines,
            summary.get("top_workspaces") or [],
            (("workspace", "workspace", "(unknown)"),
             ("loop count", "loop_count", 0),
             ("blocked count", "blocked_count", 0)),
        )
        a("")

        a("## Top Failure Reasons")
        _append_rows(
            lines,
            summary.get("top_failure_reasons") or [],
            (("stop reason", "stop_reason", "(unknown)"),
             ("count", "count", 0)),
        )
        a("")

        a("## External Job Health")
        a(f"- waiting: {health.get('waiting', 0)}")
        a(f"- stale: {health.get('stale', 0)}")
        a(f"- needs attention: {health.get('needs_attention', 0)}")
        a(f"- archived: {health.get('archived', 0)}")
        a(f"- cancelled: {health.get('cancelled', 0)}")
        a("")

        a("## Alerts")
        alerts = summary.get("alerts") or []
        if not alerts:
            a("- (none)")
        for alert in alerts:
            a(f"- severity: {alert.get('severity', '(unknown)')}")
            a(f"  alert type: {alert.get('alert_type', '(unknown)')}")
            a(f"  message: {alert.get('message', '')}")
            a(f"  recommended action: {alert.get('recommended_action', '')}")
            a(f"  details: {alert.get('details_json') or '{}'}")
        a("")

        a("## Next Actions")
        for cmd in (
            "python3 main.py --external-dashboard",
            "python3 main.py --external-health",
            "python3 main.py --external-jobs --needs-attention",
            "python3 main.py --history --limit 10",
            "python3 main.py --reports",
            "python3 main.py --observatory",
        ):
            a(f"- {cmd}")
        a("")

        a("## Safety Notes")
        a("- Observatory reports are read-only summaries")
        a("- No model calls")
        a("- No command execution")
        a("- No job mutation")
        a("- No loop mutation")
        a("")
        return "\n".join(lines)
