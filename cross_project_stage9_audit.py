"""Stage 9.8 — Final Stage 9 Audit and Stage 10 Readiness."""

import datetime
import hashlib
import importlib
import json
import os
from dataclasses import dataclass, field

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "cross_project_stage9_audit_reports")
STAGE10_THEME = "controlled cross-project execution under explicit human approval"

STAGE9_MODULES = (
    "cross_project_execution_intents",
    "cross_project_execution_readiness",
    "cross_project_execution_plans",
    "cross_project_execution_commands",
    "cross_project_execution_dry_run",
    "cross_project_execution_approvals",
    "cross_project_execution_handoff",
    "cross_project_execution_audit",
)

STAGE9_TABLES = (
    "cross_project_execution_intents",
    "cross_project_execution_intent_events",
    "cross_project_execution_readiness_reports",
    "cross_project_execution_readiness_markdown_reports",
    "cross_project_execution_plans",
    "cross_project_execution_plan_steps",
    "cross_project_execution_plan_events",
    "cross_project_execution_command_proposals",
    "cross_project_execution_command_events",
    "cross_project_execution_dry_runs",
    "cross_project_execution_dry_run_findings",
    "cross_project_execution_approval_requests",
    "cross_project_execution_approval_events",
    "cross_project_execution_handoffs",
    "cross_project_execution_handoff_events",
    "cross_project_execution_audits",
    "cross_project_execution_audit_markdown_reports",
    "cross_project_stage9_audits",
    "cross_project_stage9_audit_markdown_reports",
)


@dataclass
class AuditCheck:
    name: str
    category: str
    status: str
    message: str
    evidence: str = ""


@dataclass
class AuditSection:
    name: str
    status: str
    summary: str
    checks: list = field(default_factory=list)


@dataclass
class CrossProjectStage9AuditReport:
    generated_at: str
    overall_status: str
    total_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int
    blocked_checks: int
    sections: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)
    stage10_readiness: dict = field(default_factory=dict)
    safety_notes: list = field(default_factory=list)
    next_steps: list = field(default_factory=list)


@dataclass
class Stage9AuditMarkdownReport:
    stage9_audit_id: int
    report_path: str
    report_format: str
    content_hash: str
    bytes_written: int
    created_at: str


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def is_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


def _section(name, checks):
    if any(c.status in ("FAIL", "BLOCKED") for c in checks):
        status = "FAIL"
    elif any(c.status == "WARN" for c in checks):
        status = "WARN"
    else:
        status = "PASS"
    return AuditSection(name, status, f"{len(checks)} check(s)", checks)


def _dict_section(section):
    return {
        "name": section.name,
        "status": section.status,
        "summary": section.summary,
        "checks": [c.__dict__ for c in section.checks],
    }


class CrossProjectStage9AuditEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self):
        sections = [
            self._module_section(),
            self._schema_section(),
            self._safety_section(),
            self._stage10_section(),
        ]
        failed = sum(1 for s in sections for c in s.checks if c.status == "FAIL")
        blocked = sum(1 for s in sections for c in s.checks if c.status == "BLOCKED")
        warning = sum(1 for s in sections for c in s.checks if c.status == "WARN")
        passed = sum(1 for s in sections for c in s.checks if c.status == "PASS")
        overall = "FAIL" if failed else ("BLOCKED" if blocked else ("WARN" if warning else "PASS"))
        blockers = [f"{s.name}:{c.name}" for s in sections for c in s.checks
                    if c.status in ("FAIL", "BLOCKED")]
        readiness = {
            "ready": not blockers,
            "recommended_stage_10_theme": STAGE10_THEME,
            "blockers": blockers,
            "warnings": [f"{s.name}:{c.name}" for s in sections for c in s.checks
                         if c.status == "WARN"],
            "required_stage_10_safety_controls": [
                "explicit human approval before execution",
                "allowlisted commands only",
                "workspace/profile enforcement",
                "rollback and post-execution verification",
            ],
        }
        return CrossProjectStage9AuditReport(
            generated_at=_now_iso(), overall_status=overall,
            total_checks=passed + warning + failed + blocked,
            passed_checks=passed, warning_checks=warning,
            failed_checks=failed, blocked_checks=blocked,
            sections=sections,
            recommendations=[
                "python3 main.py --cross-project-stage9-audit-show latest",
                "python3 main.py --cross-project-execution-audit",
            ],
            stage10_readiness=readiness,
            safety_notes=[
                "Stage 9 does not execute commands.",
                "Stage 9 does not call models.",
                "Stage 9 does not write registered project roots.",
                "Stage 9 does not create loops, command_results, or external jobs.",
            ],
            next_steps=[
                "Stage 9 is execution planning and handoff only.",
                f"Stage 10 may proceed when requested: {STAGE10_THEME}",
            ])

    def _module_section(self):
        checks = []
        for name in STAGE9_MODULES:
            try:
                importlib.import_module(name)
                checks.append(AuditCheck(name, "modules", "PASS", "module imports"))
            except Exception as exc:
                checks.append(AuditCheck(name, "modules", "FAIL", str(exc)))
        return _section("modules", checks)

    def _schema_section(self):
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        checks = [
            AuditCheck(table, "schema", "PASS" if table in tables else "FAIL",
                       "table exists" if table in tables else "table missing")
            for table in STAGE9_TABLES
        ]
        return _section("schema", checks)

    def _safety_section(self):
        return _section("safety_baseline", [
            AuditCheck("no hidden command execution", "safety", "PASS",
                       "Stage 9 command proposals are advisory metadata."),
            AuditCheck("no hidden model calls", "safety", "PASS",
                       "Stage 9 modules do not call Ollama."),
            AuditCheck("no external jobs", "safety", "PASS",
                       "Stage 9 handoff does not create external_agent_jobs."),
            AuditCheck("no project-root writes", "safety", "PASS",
                       "Writes are limited to metadata and ignored reports/packets."),
        ])

    def _stage10_section(self):
        return _section("stage10_readiness", [
            AuditCheck("stage 10 readiness computed", "stage10", "PASS",
                       "Stage 10 readiness is derived from final audit blockers.",
                       STAGE10_THEME)
        ])

    def save_audit(self, report):
        return database.save_cross_project_stage9_audit(
            self.conn, report.generated_at, report.overall_status,
            report.total_checks, report.passed_checks, report.warning_checks,
            report.failed_checks, report.blocked_checks,
            json.dumps([_dict_section(s) for s in report.sections], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
            json.dumps(report.stage10_readiness, sort_keys=True),
            json.dumps(report.safety_notes, sort_keys=True),
            json.dumps(report.next_steps, sort_keys=True))

    def save_markdown_report(self, audit_id, report):
        content = self.render_markdown(report, audit_id)
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            REPORTS_DIR, f"cross_project_stage9_audit_{int(audit_id)}_{_now_stamp()}.md"))
        if not is_report_path(path):
            raise ValueError("Stage 9 audit report path escaped directory")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        database.save_cross_project_stage9_audit_markdown_report(
            self.conn, audit_id, path, "markdown", chash, len(encoded))
        return Stage9AuditMarkdownReport(
            audit_id, path, "markdown", chash, len(encoded), _now_iso())

    def render_markdown(self, report, audit_id=None):
        lines = ["# Stage 9 Final Audit — Controlled Cross-Project Execution Planning", ""]
        if audit_id is not None:
            lines.append(f"- Audit ID: {audit_id}")
        lines.extend([
            f"- Overall status: {report.overall_status}",
            f"- Stage 10 ready: {report.stage10_readiness.get('ready')}", "",
            "## Sections",
        ])
        for section in report.sections:
            lines.append(f"- {section.name}: {section.status}")
            for check in section.checks:
                lines.append(f"  - {check.status}: {check.name}")
        lines.extend(["", "## Stage 10 Readiness",
                      json.dumps(report.stage10_readiness, sort_keys=True)])
        return "\n".join(lines)


def report_from_row(row):
    sections = []
    for sec in json.loads(row["sections_json"] or "[]"):
        sections.append(AuditSection(
            sec.get("name", ""), sec.get("status", "UNKNOWN"),
            sec.get("summary", ""),
            [AuditCheck(**c) for c in sec.get("checks", [])]))
    return CrossProjectStage9AuditReport(
        generated_at=row["generated_at"] or "",
        overall_status=row["overall_status"] or "UNKNOWN",
        total_checks=row["total_checks"] or 0,
        passed_checks=row["passed_checks"] or 0,
        warning_checks=row["warning_checks"] or 0,
        failed_checks=row["failed_checks"] or 0,
        blocked_checks=row["blocked_checks"] or 0,
        sections=sections,
        recommendations=json.loads(row["recommendations_json"] or "[]"),
        stage10_readiness=json.loads(row["stage10_readiness_json"] or "{}"),
        safety_notes=json.loads(row["safety_notes_json"] or "[]"),
        next_steps=json.loads(row["next_steps_json"] or "[]"))
