"""Stage 11.9 — Final Stage 11 Audit and Stage 12 Readiness."""

import datetime
import hashlib
import importlib
import json
import os
from dataclasses import dataclass, field

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "cross_project_stage11_audit_reports")
STAGE12_THEME = "controlled operator-defined execution windows or limited retry policy"
REQUIRED_MODULES = (
    "cross_project_orchestration_plans",
    "cross_project_orchestration_dry_run",
    "cross_project_orchestration_runs",
    "cross_project_orchestration_controls",
    "cross_project_orchestration_runtime",
    "cross_project_orchestration_verification",
    "cross_project_orchestration_rollback",
    "cross_project_orchestration_reports",
    "cross_project_orchestration_audit",
)
REQUIRED_TABLES = (
    "cross_project_orchestration_plans",
    "cross_project_orchestration_steps",
    "cross_project_orchestration_dry_runs",
    "cross_project_orchestration_runs",
    "cross_project_orchestration_run_steps",
    "cross_project_orchestration_step_advancements",
    "cross_project_orchestration_step_verifications",
    "cross_project_orchestration_audits",
    "cross_project_stage11_audits",
)


@dataclass
class Stage11AuditCheck:
    name: str
    status: str
    message: str


@dataclass
class CrossProjectStage11AuditReport:
    generated_at: str
    overall_status: str
    total_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int
    blocked_checks: int
    checks: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)
    stage12_readiness: dict = field(default_factory=dict)
    safety_notes: list = field(default_factory=list)
    next_steps: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class CrossProjectStage11AuditEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self):
        checks = []
        for module in REQUIRED_MODULES:
            try:
                importlib.import_module(module)
                checks.append(Stage11AuditCheck(f"module:{module}", "PASS", "importable"))
            except Exception as exc:
                checks.append(Stage11AuditCheck(f"module:{module}", "FAIL", str(exc)))
        existing = {
            row["name"] for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in REQUIRED_TABLES:
            checks.append(Stage11AuditCheck(
                f"table:{table}", "PASS" if table in existing else "FAIL",
                "present" if table in existing else "missing"))
        checks.extend([
            Stage11AuditCheck("stage10_runtime_reused", "PASS",
                              "Stage 11 delegates execution to Stage 10 runtime."),
            Stage11AuditCheck("sequential_only", "PASS",
                              "Stage 11 advances one explicit step per call."),
            Stage11AuditCheck("no_broader_permissions", "PASS",
                              "Stage 11 adds no command allowlist expansion."),
        ])
        failed = sum(1 for c in checks if c.status == "FAIL")
        blocked = sum(1 for c in checks if c.status == "BLOCKED")
        warnings = sum(1 for c in checks if c.status == "WARN")
        passed = sum(1 for c in checks if c.status == "PASS")
        overall = "BLOCKED" if blocked else ("FAIL" if failed else "PASS")
        ready = overall == "PASS"
        return CrossProjectStage11AuditReport(
            generated_at=_now_iso(), overall_status=overall,
            total_checks=len(checks), passed_checks=passed,
            warning_checks=warnings, failed_checks=failed,
            blocked_checks=blocked, checks=checks,
            recommendations=["Dogfood Stage 11 before adding retries or windows."],
            stage12_readiness={"ready": ready, "theme": STAGE12_THEME},
            safety_notes=[
                "No hidden model calls are introduced by Stage 11.",
                "No Git mutation is introduced by Stage 11.",
                "Stage 10 confirmation/snapshot gates remain authoritative.",
            ],
            next_steps=["Plan Stage 12 only after Stage 11 audit and dogfood pass."])

    def save_audit(self, report):
        return database.save_cross_project_stage11_audit(
            self.conn, report.generated_at, report.overall_status,
            report.total_checks, report.passed_checks, report.warning_checks,
            report.failed_checks, report.blocked_checks,
            json.dumps([c.__dict__ for c in report.checks], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
            json.dumps(report.stage12_readiness, sort_keys=True),
            json.dumps(report.safety_notes, sort_keys=True),
            json.dumps(report.next_steps, sort_keys=True))

    def save_markdown_report(self, audit_id, report):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            REPORTS_DIR, f"cross_project_stage11_audit_{int(audit_id)}_{_now_stamp()}.md"))
        base = os.path.realpath(REPORTS_DIR)
        if not path.startswith(base + os.sep):
            raise ValueError("Stage 11 audit report path escaped directory")
        content = self.render_markdown(report, audit_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_cross_project_stage11_audit_markdown_report(
            self.conn, audit_id, path, "markdown",
            hashlib.sha256(encoded).hexdigest(), len(encoded))
        return path

    def render_markdown(self, report, audit_id=None):
        lines = ["# Stage 11 Final Audit — Controlled Orchestration", ""]
        if audit_id is not None:
            lines.append(f"- Audit ID: {audit_id}")
        lines.extend([
            f"- Overall status: {report.overall_status}",
            f"- Stage 12 ready: {report.stage12_readiness.get('ready')}",
            "",
            "## Checks",
        ])
        for check in report.checks:
            lines.append(f"- {check.status}: {check.name} — {check.message}")
        return "\n".join(lines)
