"""Stage 8.2 — Fleet Governance Report.

Produces a fleet-level, read-only governance summary: project health, stale
roots, blocked projects, missing validations, open plans, approval state,
handoff/schedule coverage, and policy pass/fail counts. Metadata-only: no
commands, no model calls, no project file-content reads, no cross-project
writes. Writes only report rows and Markdown under ``fleet_governance_reports/``.
"""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Optional

import database
import multi_project_registry as registry_mod


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "fleet_governance_reports")


@dataclass
class FleetGovernanceReport:
    id: int
    generated_at: str
    summary: dict = field(default_factory=dict)
    sections: dict = field(default_factory=dict)


@dataclass
class FleetGovernanceMarkdownReport:
    report_id: int
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


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def is_report_path(path) -> bool:
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


class FleetGovernanceReporter:
    def __init__(self, conn):
        self.conn = conn
        self.registry = registry_mod.ProjectRegistry(conn)

    def build_report(self) -> FleetGovernanceReport:
        projects = self.registry.list_projects()
        active = [p for p in projects if p.status == "active"]

        project_health = []
        stale = []
        blocked = []
        missing_validation = []
        for p in projects:
            root_exists = bool(p.root_path) and os.path.isdir(p.root_path)
            latest = database.latest_project_validation_report(
                self.conn, p.project_key)
            vstatus = latest["overall_status"] if latest else "(none)"
            project_health.append({
                "project_key": p.project_key, "status": p.status,
                "root_exists": root_exists, "latest_validation": vstatus})
            if not root_exists:
                stale.append(p.project_key)
            if p.status == "blocked":
                blocked.append(p.project_key)
            if latest is None and p.status == "active":
                missing_validation.append(p.project_key)

        planning = {
            "plans": _count(self.conn, "cross_project_work_plans"),
            "approvals": _count(self.conn, "cross_project_approvals"),
            "pending_approvals": self.conn.execute(
                "SELECT COUNT(*) AS n FROM cross_project_approvals "
                "WHERE status='pending'").fetchone()["n"],
            "handoffs": _count(self.conn, "cross_project_handoffs"),
            "schedules": _count(self.conn, "multi_project_schedules"),
        }

        latest_eval = database.list_governance_policy_evaluations(self.conn, limit=1)
        if latest_eval:
            e = latest_eval[0]
            policy_summary = {
                "latest_evaluation_id": e["id"],
                "overall_status": e["overall_status"],
                "passed": e["passed_findings"], "warning": e["warning_findings"],
                "failed": e["failed_findings"], "waived": e["waived_findings"],
            }
        else:
            policy_summary = {"latest_evaluation_id": None,
                              "overall_status": "(none)"}

        active_policies = sum(
            1 for p in database.list_governance_policies(self.conn)
            if (p["status"] or "") == "active")
        open_waivers = self.conn.execute(
            "SELECT COUNT(*) AS n FROM governance_waivers "
            "WHERE status='active'").fetchone()["n"]

        summary = {
            "generated_at": _now_iso(),
            "total_projects": len(projects),
            "active_projects": len(active),
            "stale_projects": len(stale),
            "blocked_projects": len(blocked),
            "missing_validations": len(missing_validation),
            "active_policies": active_policies,
            "active_waivers": open_waivers,
            "latest_evaluation_status": policy_summary.get("overall_status"),
            "open_plans": planning["plans"],
            "pending_approvals": planning["pending_approvals"],
        }
        sections = {
            "project_health": project_health,
            "stale_projects": stale,
            "blocked_projects": blocked,
            "missing_validations": missing_validation,
            "planning": planning,
            "policy_summary": policy_summary,
        }
        return FleetGovernanceReport(
            id=0, generated_at=summary["generated_at"], summary=summary,
            sections=sections)

    # -- persistence ----------------------------------------------------- #
    def save_report(self, report) -> int:
        report_id = database.save_fleet_governance_report(
            self.conn, report.generated_at,
            json.dumps(report.summary, sort_keys=True),
            json.dumps(report.sections, sort_keys=True))
        report.id = report_id
        return report_id

    def get_report(self, report_id) -> Optional[FleetGovernanceReport]:
        row = database.get_fleet_governance_report(self.conn, report_id)
        if row is None:
            return None
        return FleetGovernanceReport(
            id=row["id"], generated_at=row["generated_at"] or "",
            summary=_safe_json_loads(row["summary_json"], {}),
            sections=_safe_json_loads(row["sections_json"], {}))

    def list_reports(self, limit=20):
        return database.list_fleet_governance_reports(self.conn, limit=limit)

    def save_markdown_report(self, report_id) -> FleetGovernanceMarkdownReport:
        report = self.get_report(report_id)
        if report is None:
            raise ValueError(f"no fleet governance report {report_id}")
        content = self.render_markdown(report)
        path = self._new_report_path(report_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_fleet_governance_markdown_report(
            self.conn, report_id, path, "markdown", chash, nbytes)
        return FleetGovernanceMarkdownReport(
            report_id=report_id, report_path=path, report_format="markdown",
            content_hash=chash, bytes_written=nbytes, created_at=_now_iso())

    def _new_report_path(self, report_id) -> str:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"fleet_governance_{int(report_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("fleet governance report path escaped directory")
        return target

    def render_markdown(self, report) -> str:
        s = report.summary
        sec = report.sections
        lines = []
        a = lines.append
        a("# Fleet Governance Report")
        a("")
        a("## Summary")
        a(f"- Generated at: {s.get('generated_at', report.generated_at)}")
        a(f"- Total projects: {s.get('total_projects', 0)} "
          f"(active {s.get('active_projects', 0)})")
        a(f"- Stale projects: {s.get('stale_projects', 0)}")
        a(f"- Blocked projects: {s.get('blocked_projects', 0)}")
        a(f"- Missing validations: {s.get('missing_validations', 0)}")
        a(f"- Active policies: {s.get('active_policies', 0)}")
        a(f"- Active waivers: {s.get('active_waivers', 0)}")
        a(f"- Latest evaluation status: {s.get('latest_evaluation_status')}")
        a(f"- Open plans: {s.get('open_plans', 0)}")
        a(f"- Pending approvals: {s.get('pending_approvals', 0)}")
        a("")
        a("## Project Health")
        health = sec.get("project_health", [])
        if not health:
            a("- (none registered)")
        for p in health:
            a(f"- {p.get('project_key')} [{p.get('status')}] "
              f"root_exists={p.get('root_exists')} "
              f"validation={p.get('latest_validation')}")
        a("")
        a("## Attention")
        a(f"- Stale roots: {sec.get('stale_projects') or '(none)'}")
        a(f"- Blocked: {sec.get('blocked_projects') or '(none)'}")
        a(f"- Missing validations: {sec.get('missing_validations') or '(none)'}")
        a("")
        a("## Planning")
        plan = sec.get("planning", {})
        a(f"- Plans: {plan.get('plans', 0)}")
        a(f"- Approvals: {plan.get('approvals', 0)} "
          f"(pending {plan.get('pending_approvals', 0)})")
        a(f"- Handoffs: {plan.get('handoffs', 0)}")
        a(f"- Schedules: {plan.get('schedules', 0)}")
        a("")
        a("## Policy Summary")
        ps = sec.get("policy_summary", {})
        a(f"- Latest evaluation: {ps.get('latest_evaluation_id')}")
        a(f"- Overall status: {ps.get('overall_status')}")
        if ps.get("latest_evaluation_id"):
            a(f"- pass/warn/fail/waived: {ps.get('passed')}/{ps.get('warning')}/"
              f"{ps.get('failed')}/{ps.get('waived')}")
        a("")
        a("## Safety Notes")
        for note in (
            "Read-only, metadata-only fleet aggregation.",
            "No project file contents read; no commands; no model calls.",
            "No cross-project mutation.",
        ):
            a(f"- {note}")
        a("")
        return "\n".join(lines)
