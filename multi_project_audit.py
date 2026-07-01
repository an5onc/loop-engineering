"""Stage 7.7 — Multi-Project Audit Trail.

Summarizes the Stage 7 subsystem (registry, validation, observatory, planning,
approvals, handoffs, schedules) plus a safety baseline and Stage 8 readiness.
The audit is read-only over Stage 7 metadata: it runs no commands, calls no
model, creates no loops or external jobs, and reads no project file contents. It
writes only its own audit rows and optional Markdown reports under
``multi_project_audit_reports/``.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "multi_project_audit_reports")

STAGE8_THEME = "Multi-Project Governance and Fleet Reporting"
SAFETY_TABLES = ("loops", "command_results", "external_agent_jobs")


@dataclass
class AuditCheck:
    name: str
    category: str
    status: str
    message: str
    evidence: str = ""
    recommended_action: str = ""


@dataclass
class AuditSection:
    name: str
    status: str
    checks: List[AuditCheck] = field(default_factory=list)
    summary: str = ""


@dataclass
class MultiProjectAuditReport:
    id: int
    generated_at: str
    overall_status: str
    total_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int
    blocked_checks: int
    sections: List[AuditSection] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    stage8_readiness: dict = field(default_factory=dict)
    safety_notes: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)


@dataclass
class AuditMarkdownReport:
    audit_id: int
    report_path: str
    report_format: str
    content_hash: str
    bytes_written: int
    created_at: str


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def section_to_dict(section):
    data = asdict(section)
    data["checks"] = [asdict(c) for c in section.checks]
    return data


def section_from_dict(data):
    return AuditSection(
        name=data["name"], status=data["status"],
        checks=[AuditCheck(**c) for c in data.get("checks", [])],
        summary=data.get("summary", ""))


def report_from_row(row):
    return MultiProjectAuditReport(
        id=row["id"], generated_at=row["generated_at"] or "",
        overall_status=row["overall_status"] or "",
        total_checks=row["total_checks"] or 0,
        passed_checks=row["passed_checks"] or 0,
        warning_checks=row["warning_checks"] or 0,
        failed_checks=row["failed_checks"] or 0,
        blocked_checks=row["blocked_checks"] or 0,
        sections=[section_from_dict(s)
                  for s in _safe_json_loads(row["sections_json"], [])],
        recommendations=_safe_json_loads(row["recommendations_json"], []),
        stage8_readiness=_safe_json_loads(row["stage8_readiness_json"], {}),
        safety_notes=_safe_json_loads(row["safety_notes_json"], []),
        next_steps=_safe_json_loads(row["next_steps_json"], []))


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


def aggregate_overall_status(sections):
    statuses = [s.status for s in sections]
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "PASS_WITH_WARNINGS"
    return "PASS"


def _section_status(checks):
    statuses = [c.status for c in checks]
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"


def _make_section(name, checks):
    passed = sum(1 for c in checks if c.status == "PASS")
    warnings = sum(1 for c in checks if c.status == "WARN")
    failed = sum(1 for c in checks if c.status == "FAIL")
    blocked = sum(1 for c in checks if c.status == "BLOCKED")
    return AuditSection(
        name=name, status=_section_status(checks), checks=checks,
        summary=f"{passed} pass, {warnings} warning, {failed} fail, {blocked} blocked")


class MultiProjectAuditEngine:
    def __init__(self, conn):
        self.conn = conn
        self._baseline = {t: _count(conn, t) for t in SAFETY_TABLES}

    # -- building -------------------------------------------------------- #
    def build_report(self):
        sections = [
            self._registry_section(),
            self._validation_section(),
            self._observatory_section(),
            self._planning_section(),
            self._approvals_section(),
            self._handoffs_section(),
            self._schedules_section(),
            self._safety_baseline_section(),
        ]
        readiness = self._stage8_readiness(sections)
        sections.append(self._stage8_section(readiness))
        overall = aggregate_overall_status(sections)
        if overall in ("FAIL", "BLOCKED"):
            readiness["ready"] = False
        readiness["overall_status"] = overall
        total = sum(len(s.checks) for s in sections)
        passed = sum(1 for s in sections for c in s.checks if c.status == "PASS")
        warnings = sum(1 for s in sections for c in s.checks if c.status == "WARN")
        failed = sum(1 for s in sections for c in s.checks if c.status == "FAIL")
        blocked = sum(1 for s in sections for c in s.checks if c.status == "BLOCKED")
        return MultiProjectAuditReport(
            id=0, generated_at=_now_iso(), overall_status=overall,
            total_checks=total, passed_checks=passed, warning_checks=warnings,
            failed_checks=failed, blocked_checks=blocked, sections=sections,
            recommendations=_recommendations(), stage8_readiness=readiness,
            safety_notes=_safety_notes(), next_steps=_next_steps(readiness))

    def _ok(self, name, category, ok, ok_msg, bad_msg, evidence="",
            bad_status="FAIL", action=""):
        return AuditCheck(
            name=name, category=category, status="PASS" if ok else bad_status,
            message=ok_msg if ok else bad_msg, evidence=evidence,
            recommended_action="No action required." if ok else action)

    def _registry_section(self):
        n = _count(self.conn, "registered_projects")
        statuses = {r["status"] for r in
                    database.list_registered_projects(self.conn)}
        invalid = sorted(s for s in statuses
                         if s and s not in ("active", "paused", "archived", "blocked"))
        checks = [
            self._ok("registered_projects listable", "registry", True,
                     f"{n} project(s) registered.", "", f"count={n}"),
            self._ok("project statuses valid", "registry", not invalid,
                     "All project statuses valid.",
                     "Invalid statuses: " + ", ".join(invalid),
                     f"observed={sorted(statuses)}",
                     action="Correct invalid project statuses."),
        ]
        return _make_section("registry", checks)

    def _validation_section(self):
        n = _count(self.conn, "project_validation_reports")
        checks = [
            self._ok("validation reports listable", "validation", True,
                     f"{n} validation report(s).", "", f"count={n}",
                     bad_status="WARN"),
        ]
        return _make_section("validation", checks)

    def _observatory_section(self):
        n = _count(self.conn, "multi_project_observatory_snapshots")
        checks = [
            self._ok("observatory snapshots listable", "observatory", True,
                     f"{n} snapshot(s).", "", f"count={n}", bad_status="WARN"),
        ]
        return _make_section("observatory", checks)

    def _planning_section(self):
        n = _count(self.conn, "cross_project_work_plans")
        checks = [
            self._ok("plans listable", "planning", True,
                     f"{n} plan(s).", "", f"count={n}", bad_status="WARN"),
        ]
        return _make_section("planning", checks)

    def _approvals_section(self):
        n = _count(self.conn, "cross_project_approvals")
        orphan = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_approvals a "
            "LEFT JOIN cross_project_work_plans p ON a.plan_id=p.id "
            "WHERE p.id IS NULL").fetchone()["n"]
        checks = [
            self._ok("approvals listable", "approvals", True,
                     f"{n} approval(s).", "", f"count={n}", bad_status="WARN"),
            self._ok("approvals reference a valid plan", "approvals", orphan == 0,
                     "All approvals reference a valid plan.",
                     f"{orphan} approval(s) reference a missing plan.",
                     f"orphans={orphan}",
                     action="Investigate orphaned approvals."),
        ]
        return _make_section("approvals", checks)

    def _handoffs_section(self):
        n = _count(self.conn, "cross_project_handoffs")
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_handoffs h "
            "LEFT JOIN cross_project_approvals a ON h.approval_id=a.id "
            "WHERE a.id IS NULL OR a.status != 'approved'").fetchone()["n"]
        checks = [
            self._ok("handoffs listable", "handoffs", True,
                     f"{n} handoff(s).", "", f"count={n}", bad_status="WARN"),
            self._ok("every handoff has an approved approval", "handoffs", bad == 0,
                     "All handoffs reference an approved approval.",
                     f"{bad} handoff(s) lack an approved approval.",
                     f"unapproved={bad}",
                     action="Review handoffs whose approval is missing or not approved."),
        ]
        return _make_section("handoffs", checks)

    def _schedules_section(self):
        n = _count(self.conn, "multi_project_schedules")
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM multi_project_schedules s "
            "LEFT JOIN cross_project_approvals a ON s.approval_id=a.id "
            "WHERE a.id IS NULL OR a.status != 'approved'").fetchone()["n"]
        checks = [
            self._ok("schedules listable", "schedules", True,
                     f"{n} schedule(s).", "", f"count={n}", bad_status="WARN"),
            self._ok("every schedule has an approved approval", "schedules", bad == 0,
                     "All schedules reference an approved approval.",
                     f"{bad} schedule(s) lack an approved approval.",
                     f"unapproved={bad}",
                     action="Review schedules whose approval is missing or not approved."),
        ]
        return _make_section("schedules", checks)

    def _safety_baseline_section(self):
        checks = []
        for table in SAFETY_TABLES:
            before = self._baseline.get(table, 0)
            after = _count(self.conn, table)
            checks.append(self._ok(
                f"{table} count unchanged during audit", "safety_baseline",
                before == after, f"{table} count stable at {after}.",
                f"{table} changed {before}->{after}.",
                f"before={before} after={after}",
                action=f"Investigate writes to {table}."))
        checks.append(AuditCheck(
            name="no hidden command execution", category="safety_baseline",
            status="PASS",
            message="Stage 7 audit executes no commands.",
            evidence="metadata-only", recommended_action="No action required."))
        checks.append(AuditCheck(
            name="no Ollama dependency", category="safety_baseline", status="PASS",
            message="Stage 7 audit makes no model calls.",
            evidence="db-only", recommended_action="No action required."))
        checks.append(AuditCheck(
            name="no cross-project writes", category="safety_baseline", status="PASS",
            message="Stage 7 audit never writes to external project roots.",
            evidence="local-db-only", recommended_action="No action required."))
        return _make_section("safety_baseline", checks)

    def _stage8_readiness(self, sections):
        blockers = []
        warnings = []
        for section in sections:
            for check in section.checks:
                if check.status in ("FAIL", "BLOCKED"):
                    blockers.append(f"{section.name}: {check.name}")
                elif check.status == "WARN":
                    warnings.append(f"{section.name}: {check.name}")
        return {
            "ready": not blockers,
            "recommended_stage_8_theme": STAGE8_THEME,
            "blockers": blockers,
            "warnings": warnings,
            "required_stage_8_safety_controls": [
                "explicit approval before any cross-project action",
                "no hidden model or command execution",
                "no cross-project writes without approval",
                "metadata-only observability",
            ],
        }

    def _stage8_section(self, readiness):
        checks = [
            AuditCheck(
                name="stage 8 readiness computed", category="stage8_readiness",
                status="PASS" if readiness.get("ready") else "WARN",
                message=("Stage 8 readiness: ready" if readiness.get("ready")
                         else "Stage 8 readiness: not ready (see blockers)"),
                evidence=f"blockers={len(readiness.get('blockers', []))}",
                recommended_action=("No action required." if readiness.get("ready")
                                    else "Resolve blockers before Stage 8.")),
        ]
        return _make_section("stage8_readiness", checks)

    # -- persistence ----------------------------------------------------- #
    def save_audit(self, report):
        return database.save_multi_project_audit(
            self.conn, report.generated_at, report.overall_status,
            report.total_checks, report.passed_checks, report.warning_checks,
            report.failed_checks, report.blocked_checks,
            json.dumps([section_to_dict(s) for s in report.sections], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
            json.dumps(report.stage8_readiness, sort_keys=True),
            json.dumps(report.safety_notes, sort_keys=True),
            json.dumps(report.next_steps, sort_keys=True))

    def save_markdown_report(self, audit_id, report):
        content = self.render_markdown(report, audit_id)
        path = self._new_report_path(audit_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_multi_project_audit_markdown_report(
            self.conn, audit_id, path, "markdown", chash, nbytes)
        return AuditMarkdownReport(
            audit_id=audit_id, report_path=path, report_format="markdown",
            content_hash=chash, bytes_written=nbytes, created_at=_now_iso())

    def _new_report_path(self, audit_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"multi_project_audit_{int(audit_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("multi-project audit report path escaped directory")
        return target

    def render_markdown(self, report, audit_id=None):
        lines = []
        a = lines.append
        a("# Multi-Project Audit Trail")
        a("")
        a("## Summary")
        if audit_id is not None:
            a(f"- Audit ID: {audit_id}")
        a(f"- Generated at: {report.generated_at}")
        a(f"- Overall status: {report.overall_status}")
        a(f"- Total checks: {report.total_checks}")
        a(f"- Passed: {report.passed_checks}")
        a(f"- Warnings: {report.warning_checks}")
        a(f"- Failed: {report.failed_checks}")
        a(f"- Blocked: {report.blocked_checks}")
        a(f"- Stage 8 ready: {report.stage8_readiness.get('ready')}")
        a("")
        a("## Sections")
        for section in report.sections:
            a(f"- {section.name}: {section.status}")
            a(f"  - {section.summary}")
            for check in section.checks:
                a(f"  - {check.status}: {check.name} — {check.message}")
        a("")
        a("## Stage 8 Readiness")
        for key, value in report.stage8_readiness.items():
            a(f"- {key}: {value}")
        a("")
        a("## Safety Notes")
        for note in report.safety_notes:
            a(f"- {note}")
        a("")
        a("## Next Steps")
        for step in report.next_steps:
            a(f"- {step}")
        a("")
        return "\n".join(lines)


def _recommendations():
    return [
        "python3 main.py --projects",
        "python3 main.py --validate-projects",
        "python3 main.py --multi-project-observatory",
        "python3 main.py --cross-project-plans",
        "python3 main.py --cross-project-approvals",
        "python3 main.py --cross-project-handoffs",
        "python3 main.py --multi-project-schedules",
    ]


def _safety_notes():
    return [
        "No commands executed by the multi-project audit.",
        "No model / Ollama calls.",
        "No loops or external jobs created.",
        "No cross-project writes.",
        "No protected file contents read.",
        "Only Stage 7 metadata is read; only audit rows/reports are written.",
    ]


def _next_steps(readiness):
    if readiness.get("ready"):
        return [
            "Proceed to the Stage 7 final audit: python3 main.py --multi-project-stage7-audit",
            f"Stage 8 theme when ready: {readiness.get('recommended_stage_8_theme')}",
        ]
    return [
        "Resolve the listed blockers.",
        "Re-run the multi-project audit before proceeding.",
    ]
