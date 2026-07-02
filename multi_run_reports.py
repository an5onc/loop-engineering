"""Stage 14.7 — Multi-Run Session Reports (metadata-only)."""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field

import database
import cross_project_orchestration_runs as runs_mod
import multi_run_readiness as readiness_mod
import multi_run_recovery as recovery_mod
import multi_run_session_gates as gates_mod
import multi_run_sessions as sessions_mod


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "multi_run_session_reports")


@dataclass
class MultiRunSessionReport:
    id: int
    session_id: int
    generated_at: str
    overall_status: str
    summary: str
    next_action: str
    members: list = field(default_factory=list)
    gates: list = field(default_factory=list)
    advancements: list = field(default_factory=list)
    recovery: list = field(default_factory=list)
    safety_notes: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class MultiRunSessionReportBuilder:
    def __init__(self, conn):
        self.conn = conn
        self.sessions = sessions_mod.MultiRunSessionManager(conn)
        self.gates = gates_mod.MultiRunSessionGateManager(conn)
        self.runs = runs_mod.CrossProjectOrchestrationRunManager(conn)

    def build_report(self, session_id):
        session = self.sessions.get_session(int(session_id))
        if session is None:
            raise ValueError(f"no multi-run session {session_id}")
        members = []
        for member in self.sessions.active_members(session.id):
            run = self.runs.get_run(member.run_id)
            if run is None:
                members.append({"run_id": member.run_id,
                                "status": "missing"})
                continue
            members.append(readiness_mod.assess_run(self.conn, run))
        gates = [gate.__dict__ for gate in
                 self.gates.list_gates(session_id=session.id)]
        advancements = [
            dict(row) for row in database.list_multi_run_session_advancements(
                self.conn, session_id=session.id)
        ]
        recovery = recovery_mod.build_entries(self.conn, session.id)
        overall, next_action = readiness_mod._overall(members)
        summary = (
            f"Session {session.id} ('{session.title}'): status "
            f"{session.status}, {len(members)} member run(s), "
            f"{len(gates)} gate(s), {len(advancements)} session "
            f"advancement(s), {len(recovery)} blocked step(s).")
        return MultiRunSessionReport(
            id=0, session_id=session.id, generated_at=_now_iso(),
            overall_status=overall, summary=summary, next_action=next_action,
            members=members, gates=gates, advancements=advancements,
            recovery=recovery, safety_notes=_safety_notes())

    def save_report(self, report):
        report_id = database.save_multi_run_session_report(
            self.conn, report.session_id, report.generated_at,
            report.overall_status, report.summary, report.next_action,
            json.dumps(report.members, sort_keys=True),
            json.dumps(report.gates, sort_keys=True),
            json.dumps(report.advancements, sort_keys=True),
            json.dumps(report.recovery, sort_keys=True),
            json.dumps(report.safety_notes, sort_keys=True))
        report.id = report_id
        return report_id

    def save_markdown_report(self, report_id, report):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            REPORTS_DIR,
            f"multi_run_session_report_{int(report_id)}_{_now_stamp()}.md"))
        base = os.path.realpath(REPORTS_DIR)
        if not path.startswith(base + os.sep):
            raise ValueError("session report path escaped directory")
        content = self.render_markdown(report, report_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_multi_run_session_markdown_report(
            self.conn, report_id, path, "markdown",
            hashlib.sha256(encoded).hexdigest(), len(encoded))
        return path

    def render_markdown(self, report, report_id=None):
        lines = ["# Multi-Run Session Report", ""]
        if report_id is not None:
            lines.append(f"- Report ID: {report_id}")
        lines.extend([
            f"- Session ID: {report.session_id}",
            f"- Overall: {report.overall_status}",
            f"- Next action: {report.next_action}",
            f"- Summary: {report.summary}",
            "",
            "## Member Runs",
        ])
        if not report.members:
            lines.append("- (none)")
        for member in report.members:
            lines.append(
                f"- Run {member['run_id']}: {member.get('status', '')} — "
                f"{member.get('next_action', '')}")
        lines.extend(["", "## Session Advancements"])
        if not report.advancements:
            lines.append("- (none)")
        for row in report.advancements:
            lines.append(
                f"- Advancement {row['id']}: run={row['run_id']} "
                f"status={row['status']}")
        return "\n".join(lines)


def _safety_notes():
    return [
        "Session reports are metadata-only and contain no protected file "
        "contents, database snapshots, or handoff packet contents.",
        "Execution flows only through Stage 12 gated advancement.",
    ]
