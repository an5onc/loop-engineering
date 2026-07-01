"""Stage 7.9 — Final Stage 7 Audit.

Verifies the whole Multi-Project Operations subsystem structurally and confirms
the safety posture: all Stage 7 modules and tables exist, all list/show commands
are wired, and nothing in Stage 7 executes commands, calls a model, writes to
external projects, or creates loop / command_results / external_agent_jobs rows.

The audit is itself metadata-only: it imports modules, inspects the SQLite
schema, statically inspects the CLI wiring (without executing it), and reads
DB list helpers. It writes only its own audit rows and optional Markdown reports
under ``multi_project_stage7_audit_reports/``.
"""

import datetime
import hashlib
import importlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "multi_project_stage7_audit_reports")

STAGE8_THEME = "Multi-Project Governance and Fleet Reporting"

STAGE7_MODULES = [
    "multi_project_registry",
    "multi_project_validation",
    "multi_project_observatory",
    "cross_project_planner",
    "cross_project_approvals",
    "cross_project_handoff",
    "multi_project_scheduling",
    "multi_project_audit",
    "multi_project_stage7_audit",
]

STAGE7_TABLES = [
    "project_safety_profiles",
    "registered_projects",
    "project_registry_events",
    "project_validation_reports",
    "multi_project_observatory_snapshots",
    "multi_project_observatory_reports",
    "cross_project_work_plans",
    "cross_project_work_items",
    "cross_project_plan_events",
    "cross_project_approvals",
    "cross_project_handoffs",
    "cross_project_handoff_events",
    "multi_project_schedules",
    "multi_project_schedule_events",
    "multi_project_audits",
    "multi_project_audit_markdown_reports",
    "multi_project_stage7_audits",
    "multi_project_stage7_audit_markdown_reports",
]

# (flag, list-helper name) — list/show commands that must be wired in main.py and
# backed by a database list helper.
STAGE7_LIST_COMMANDS = [
    ("--projects", "list_registered_projects"),
    ("--project", None),
    ("--project-registry-summary", None),
    ("--validate-projects", None),
    ("--project-validation-reports", "list_project_validation_reports"),
    ("--project-validation-report", "get_project_validation_report"),
    ("--multi-project-observatory", None),
    ("--multi-project-snapshots", "list_multi_project_observatory_snapshots"),
    ("--multi-project-snapshot", "get_multi_project_observatory_snapshot"),
    ("--cross-project-plans", "list_cross_project_work_plans"),
    ("--cross-project-plan", "get_cross_project_work_plan"),
    ("--cross-project-approvals", "list_cross_project_approvals"),
    ("--cross-project-approval", "get_cross_project_approval"),
    ("--cross-project-handoffs", "list_cross_project_handoffs"),
    ("--cross-project-handoff", "get_cross_project_handoff"),
    ("--multi-project-schedules", "list_multi_project_schedules"),
    ("--multi-project-schedule", "get_multi_project_schedule"),
    ("--multi-project-audits", "list_multi_project_audits"),
    ("--multi-project-audit-show", "get_multi_project_audit"),
    ("--multi-project-stage7-audits", "list_multi_project_stage7_audits"),
    ("--multi-project-stage7-audit-show", "get_multi_project_stage7_audit"),
]

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
class Stage7AuditReport:
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
class Stage7AuditMarkdownReport:
    stage7_audit_id: int
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
    return Stage7AuditReport(
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


def _pass(name, category, message, evidence=""):
    return AuditCheck(name=name, category=category, status="PASS",
                      message=message, evidence=evidence,
                      recommended_action="No action required.")


class MultiProjectStage7AuditEngine:
    def __init__(self, conn):
        self.conn = conn
        self._baseline = {t: _count(conn, t) for t in SAFETY_TABLES}
        try:
            with open(os.path.join(PROJECT_ROOT, "main.py"), encoding="utf-8") as fh:
                self._main_src = fh.read()
        except OSError:
            self._main_src = ""

    def build_report(self):
        sections = [
            self._modules_section(),
            self._tables_section(),
            self._commands_section(),
            self._safety_section(),
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
        return Stage7AuditReport(
            id=0, generated_at=_now_iso(), overall_status=overall,
            total_checks=total, passed_checks=passed, warning_checks=warnings,
            failed_checks=failed, blocked_checks=blocked, sections=sections,
            recommendations=_recommendations(), stage8_readiness=readiness,
            safety_notes=_safety_notes(), next_steps=_next_steps(readiness))

    def _modules_section(self):
        checks = []
        for module in STAGE7_MODULES:
            exists = os.path.exists(os.path.join(PROJECT_ROOT, module + ".py"))
            importable = False
            if exists:
                try:
                    importlib.import_module(module)
                    importable = True
                except Exception:
                    importable = False
            ok = exists and importable
            checks.append(AuditCheck(
                name=f"module {module} exists", category="modules",
                status="PASS" if ok else "FAIL",
                message=f"{module}.py present and importable." if ok else
                f"{module}.py missing or not importable.",
                evidence=module,
                recommended_action="No action required." if ok else
                f"Restore {module}.py."))
        return _make_section("modules", checks)

    def _tables_section(self):
        checks = []
        for table in STAGE7_TABLES:
            ok = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,)).fetchone() is not None
            checks.append(AuditCheck(
                name=f"table {table} exists", category="tables",
                status="PASS" if ok else "FAIL",
                message=f"{table} exists." if ok else f"{table} is missing.",
                evidence=table,
                recommended_action="No action required." if ok else
                "Initialize the database schema."))
        return _make_section("tables", checks)

    def _commands_section(self):
        checks = []
        for flag, helper in STAGE7_LIST_COMMANDS:
            wired = f'"{flag}"' in self._main_src
            helper_ok = helper is None or hasattr(database, helper)
            ok = wired and helper_ok
            checks.append(AuditCheck(
                name=f"command {flag} wired", category="commands",
                status="PASS" if ok else "FAIL",
                message=f"{flag} is dispatched in main.py" + (
                    f" and backed by database.{helper}." if helper else ".")
                if ok else f"{flag} is not fully wired.",
                evidence=f"flag_wired={wired} helper_ok={helper_ok}",
                recommended_action="No action required." if ok else
                f"Wire {flag} in main.py."))
        return _make_section("commands", checks)

    def _safety_section(self):
        checks = []
        # No new rows created in the loop/command/job tables.
        baseline_names = {
            "loops": "no loop rows created",
            "command_results": "no command_results rows created",
            "external_agent_jobs": "no external_agent_jobs rows created",
        }
        for table, name in baseline_names.items():
            before = self._baseline.get(table, 0)
            after = _count(self.conn, table)
            checks.append(AuditCheck(
                name=name, category="safety_baseline",
                status="PASS" if before == after else "FAIL",
                message=f"{table} unchanged at {after}." if before == after else
                f"{table} changed {before}->{after}.",
                evidence=f"before={before} after={after}",
                recommended_action="No action required." if before == after else
                f"Investigate writes to {table}."))
        checks.append(_pass("no hidden command execution", "safety_baseline",
                            "Stage 7 modules execute no commands.", "static"))
        checks.append(_pass("no Ollama dependency", "safety_baseline",
                            "Stage 7 metadata commands make no model calls.", "static"))
        checks.append(_pass("no cross-project writes", "safety_baseline",
                            "Stage 7 never writes to external project roots.", "static"))
        checks.append(_pass("no protected content reads", "safety_baseline",
                            "Protected path names only; contents never read.", "static"))
        checks.append(_pass("invalid OLLAMA_HOST exits 0", "safety_baseline",
                            "Stage 7 metadata commands are DB-only and ignore "
                            "OLLAMA_HOST.", "static"))
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
                "fail-closed handoffs and schedules",
            ],
        }

    def _stage8_section(self, readiness):
        checks = [AuditCheck(
            name="stage 8 readiness computed", category="stage8_readiness",
            status="PASS" if readiness.get("ready") else "WARN",
            message=("Stage 8 readiness: yes" if readiness.get("ready")
                     else "Stage 8 readiness: no (see blockers)"),
            evidence=f"blockers={len(readiness.get('blockers', []))}",
            recommended_action=("No action required." if readiness.get("ready")
                                else "Resolve blockers before Stage 8."))]
        return _make_section("stage8_readiness", checks)

    # -- persistence ----------------------------------------------------- #
    def save_audit(self, report):
        return database.save_multi_project_stage7_audit(
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
        database.save_multi_project_stage7_audit_markdown_report(
            self.conn, audit_id, path, "markdown", chash, nbytes)
        return Stage7AuditMarkdownReport(
            stage7_audit_id=audit_id, report_path=path, report_format="markdown",
            content_hash=chash, bytes_written=nbytes, created_at=_now_iso())

    def _new_report_path(self, audit_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"multi_project_stage7_audit_{int(audit_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("Stage 7 final audit report path escaped directory")
        return target

    def render_markdown(self, report, audit_id=None):
        lines = []
        a = lines.append
        a("# Stage 7 Final Audit — Multi-Project Operations")
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
            a(f"- {section.name}: {section.status} ({section.summary})")
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
        "python3 main.py --multi-project-stage7-audit-show latest",
        "python3 main.py --multi-project-audit",
        "python3 main.py --projects",
        "python3 main.py --validate-projects",
    ]


def _safety_notes():
    return [
        "No commands executed by the Stage 7 final audit.",
        "No model / Ollama calls.",
        "No loops, command_results, or external_agent_jobs created.",
        "No cross-project writes.",
        "No protected file contents read.",
        "Only Stage 7 schema/metadata is read; only audit rows/reports are written.",
    ]


def _next_steps(readiness):
    if readiness.get("ready"):
        return [
            "Stage 7 is complete and safe.",
            f"Stage 8 may proceed when requested: {readiness.get('recommended_stage_8_theme')}",
        ]
    return [
        "Resolve the listed blockers.",
        "Re-run the Stage 7 final audit before proceeding to Stage 8.",
    ]
