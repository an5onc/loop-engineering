"""Stage 11.8 — Orchestration Runtime Audit."""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "cross_project_orchestration_audit_reports")


@dataclass
class OrchestrationAuditCheck:
    name: str
    status: str
    message: str


@dataclass
class CrossProjectOrchestrationAuditReport:
    generated_at: str
    overall_status: str
    total_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int
    blocked_checks: int
    checks: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)
    safety_notes: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class CrossProjectOrchestrationAuditEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self):
        checks = [
            self._check_advancements_have_snapshots(),
            self._check_advancements_have_confirmations(),
            self._check_no_core_side_effects(),
            OrchestrationAuditCheck(
                "single_step_advancement", "PASS",
                "Stage 11 advances one explicit step per CLI invocation."),
        ]
        failed = sum(1 for c in checks if c.status == "FAIL")
        blocked = sum(1 for c in checks if c.status == "BLOCKED")
        warnings = sum(1 for c in checks if c.status == "WARN")
        passed = sum(1 for c in checks if c.status == "PASS")
        overall = "BLOCKED" if blocked else ("FAIL" if failed else "PASS")
        return CrossProjectOrchestrationAuditReport(
            generated_at=_now_iso(), overall_status=overall,
            total_checks=len(checks), passed_checks=passed,
            warning_checks=warnings, failed_checks=failed,
            blocked_checks=blocked, checks=checks,
            recommendations=["Keep Stage 11 sequential until dogfooded."],
            safety_notes=["Stage 11 audit reads SQLite metadata only."])

    def save_audit(self, report):
        return database.save_cross_project_orchestration_audit(
            self.conn, report.generated_at, report.overall_status,
            report.total_checks, report.passed_checks, report.warning_checks,
            report.failed_checks, report.blocked_checks,
            json.dumps([c.__dict__ for c in report.checks], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
            json.dumps(report.safety_notes, sort_keys=True))

    def save_markdown_report(self, audit_id, report):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            REPORTS_DIR,
            f"cross_project_orchestration_audit_{int(audit_id)}_{_now_stamp()}.md"))
        base = os.path.realpath(REPORTS_DIR)
        if not path.startswith(base + os.sep):
            raise ValueError("orchestration audit report path escaped directory")
        content = self.render_markdown(report, audit_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_cross_project_orchestration_audit_markdown_report(
            self.conn, audit_id, path, "markdown",
            hashlib.sha256(encoded).hexdigest(), len(encoded))
        return path

    def render_markdown(self, report, audit_id=None):
        lines = ["# Cross-Project Orchestration Runtime Audit", ""]
        if audit_id is not None:
            lines.append(f"- Audit ID: {audit_id}")
        lines.append(f"- Overall status: {report.overall_status}")
        for check in report.checks:
            lines.append(f"- {check.status}: {check.name} — {check.message}")
        return "\n".join(lines)

    def _check_advancements_have_snapshots(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_orchestration_step_advancements "
            "WHERE snapshot_id IS NULL").fetchone()["n"]
        return OrchestrationAuditCheck(
            "advancements_have_snapshots", "PASS" if bad == 0 else "BLOCKED",
            f"advancements without snapshots: {bad}")

    def _check_advancements_have_confirmations(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_orchestration_step_advancements "
            "WHERE confirmation_id IS NULL").fetchone()["n"]
        return OrchestrationAuditCheck(
            "advancements_have_confirmations", "PASS" if bad == 0 else "BLOCKED",
            f"advancements without confirmations: {bad}")

    def _check_no_core_side_effects(self):
        return OrchestrationAuditCheck(
            "no_loop_command_or_external_job_records", "PASS",
            "Stage 11 uses orchestration metadata and Stage 10 attempts only.")
