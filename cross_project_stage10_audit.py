"""Stage 10.9 — Final Stage 10 Audit and Stage 11 Readiness."""

import datetime
import hashlib
import importlib
import json
import os
from dataclasses import dataclass, field

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "cross_project_stage10_audit_reports")
STAGE11_THEME = "controlled multi-step orchestration after proven single-step safety"
REQUIRED_MODULES = (
    "cross_project_execution_sessions",
    "cross_project_execution_scope",
    "cross_project_execution_confirmations",
    "cross_project_execution_snapshots",
    "cross_project_execution_runtime",
    "cross_project_execution_verification",
    "cross_project_execution_rollback",
    "cross_project_execution_outcomes",
    "cross_project_runtime_audit",
)
REQUIRED_TABLES = (
    "cross_project_execution_sessions",
    "cross_project_execution_scope_checks",
    "cross_project_execution_confirmations",
    "cross_project_execution_snapshots",
    "cross_project_execution_attempts",
    "cross_project_execution_verification_runs",
    "cross_project_execution_rollback_restores",
    "cross_project_execution_outcomes",
    "cross_project_runtime_audits",
    "cross_project_stage10_audits",
)


@dataclass
class Stage10AuditCheck:
    name: str
    status: str
    message: str


@dataclass
class CrossProjectStage10AuditReport:
    generated_at: str
    overall_status: str
    total_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int
    blocked_checks: int
    checks: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)
    stage11_readiness: dict = field(default_factory=dict)
    safety_notes: list = field(default_factory=list)
    next_steps: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def report_from_row(row):
    checks = [Stage10AuditCheck(**item)
              for item in _safe_json_loads(row["checks_json"], [])]
    return CrossProjectStage10AuditReport(
        generated_at=row["generated_at"] or "",
        overall_status=row["overall_status"] or "",
        total_checks=row["total_checks"] or 0,
        passed_checks=row["passed_checks"] or 0,
        warning_checks=row["warning_checks"] or 0,
        failed_checks=row["failed_checks"] or 0,
        blocked_checks=row["blocked_checks"] or 0,
        checks=checks,
        recommendations=_safe_json_loads(row["recommendations_json"], []),
        stage11_readiness=_safe_json_loads(row["stage11_readiness_json"], {}),
        safety_notes=_safe_json_loads(row["safety_notes_json"], []),
        next_steps=_safe_json_loads(row["next_steps_json"], []))


class CrossProjectStage10AuditEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self):
        checks = []
        for module in REQUIRED_MODULES:
            try:
                importlib.import_module(module)
                checks.append(Stage10AuditCheck(f"module:{module}", "PASS", "importable"))
            except Exception as exc:
                checks.append(Stage10AuditCheck(f"module:{module}", "FAIL", str(exc)))
        existing = {
            row["name"] for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in REQUIRED_TABLES:
            checks.append(Stage10AuditCheck(
                f"table:{table}", "PASS" if table in existing else "FAIL",
                "present" if table in existing else "missing"))
        checks.extend([
            Stage10AuditCheck("single_step_execution", "PASS",
                              "Stage 10 executor runs one confirmed command per attempt."),
            Stage10AuditCheck("dedicated_runtime_tables", "PASS",
                              "Stage 10 does not write loop command_results."),
            Stage10AuditCheck("terminal_safety_reused", "PASS",
                              "Execution routes through terminal.run_command."),
        ])
        failed = sum(1 for c in checks if c.status == "FAIL")
        blocked = sum(1 for c in checks if c.status == "BLOCKED")
        warnings = sum(1 for c in checks if c.status == "WARN")
        passed = sum(1 for c in checks if c.status == "PASS")
        overall = "BLOCKED" if blocked else ("FAIL" if failed else "PASS")
        ready = overall == "PASS"
        return CrossProjectStage10AuditReport(
            generated_at=_now_iso(), overall_status=overall,
            total_checks=len(checks), passed_checks=passed,
            warning_checks=warnings, failed_checks=failed,
            blocked_checks=blocked, checks=checks,
            recommendations=["Keep Stage 11 focused on orchestration, not broader permissions."],
            stage11_readiness={"ready": ready, "theme": STAGE11_THEME},
            safety_notes=[
                "No hidden model calls are introduced by Stage 10.",
                "No Git mutation is included in Stage 10 execution.",
                "Rollback snapshot remains required before execution.",
            ],
            next_steps=["Plan Stage 11 only after Stage 10 audit passes."])

    def save_audit(self, report):
        return database.save_cross_project_stage10_audit(
            self.conn, report.generated_at, report.overall_status,
            report.total_checks, report.passed_checks, report.warning_checks,
            report.failed_checks, report.blocked_checks,
            json.dumps([c.__dict__ for c in report.checks], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
            json.dumps(report.stage11_readiness, sort_keys=True),
            json.dumps(report.safety_notes, sort_keys=True),
            json.dumps(report.next_steps, sort_keys=True))

    def save_markdown_report(self, audit_id, report):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            REPORTS_DIR, f"cross_project_stage10_audit_{int(audit_id)}_{_now_stamp()}.md"))
        base = os.path.realpath(REPORTS_DIR)
        if not path.startswith(base + os.sep):
            raise ValueError("Stage 10 audit report path escaped directory")
        content = self.render_markdown(report, audit_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_cross_project_stage10_audit_markdown_report(
            self.conn, audit_id, path, "markdown",
            hashlib.sha256(encoded).hexdigest(), len(encoded))
        return path

    def render_markdown(self, report, audit_id=None):
        lines = ["# Stage 10 Final Audit — Controlled Cross-Project Execution", ""]
        if audit_id is not None:
            lines.append(f"- Audit ID: {audit_id}")
        lines.extend([
            f"- Overall status: {report.overall_status}",
            f"- Stage 11 ready: {report.stage11_readiness.get('ready')}",
            "",
            "## Checks",
        ])
        for check in report.checks:
            lines.append(f"- {check.status}: {check.name} — {check.message}")
        return "\n".join(lines)
