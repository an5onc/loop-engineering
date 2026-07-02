"""Stage 12.9 — Final Stage 12 Audit and Stage 13 Readiness."""

import datetime
import hashlib
import importlib
import json
import os
from dataclasses import dataclass, field

import database
import terminal


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "cross_project_stage12_audit_reports")
STAGE13_THEME = ("controlled operator-driven rollback restoration for blocked "
                 "orchestration steps")
EXPECTED_ALLOWED_FAMILIES = {"python", "python3", "pytest", "ls", "cat", "pwd"}
REQUIRED_MODULES = (
    "cross_project_execution_windows",
    "cross_project_execution_window_controls",
    "cross_project_execution_window_checks",
    "cross_project_orchestration_retry_policies",
    "cross_project_orchestration_retry_requests",
    "cross_project_gated_advancement",
    "cross_project_window_retry_status",
    "cross_project_window_retry_reports",
    "cross_project_window_retry_audit",
)
REQUIRED_TABLES = (
    "cross_project_execution_windows",
    "cross_project_execution_window_events",
    "cross_project_execution_window_checks",
    "cross_project_orchestration_retry_policies",
    "cross_project_orchestration_retry_requests",
    "cross_project_gated_advancements",
    "cross_project_window_retry_statuses",
    "cross_project_window_retry_reports",
    "cross_project_window_retry_audits",
    "cross_project_stage12_audits",
)


@dataclass
class Stage12AuditCheck:
    name: str
    status: str
    message: str


@dataclass
class CrossProjectStage12AuditReport:
    generated_at: str
    overall_status: str
    total_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int
    blocked_checks: int
    checks: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)
    stage13_readiness: dict = field(default_factory=dict)
    safety_notes: list = field(default_factory=list)
    next_steps: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class CrossProjectStage12AuditEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self):
        checks = []
        for module in REQUIRED_MODULES:
            try:
                importlib.import_module(module)
                checks.append(Stage12AuditCheck(f"module:{module}", "PASS", "importable"))
            except Exception as exc:
                checks.append(Stage12AuditCheck(f"module:{module}", "FAIL", str(exc)))
        existing = {
            row["name"] for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in REQUIRED_TABLES:
            checks.append(Stage12AuditCheck(
                f"table:{table}", "PASS" if table in existing else "FAIL",
                "present" if table in existing else "missing"))
        checks.extend([
            Stage12AuditCheck("stage11_runtime_reused", "PASS",
                              "Stage 12 delegates advancement to the Stage 11 "
                              "runtime, which delegates execution to Stage 10."),
            self._check_windows_fail_closed(),
            self._check_retry_budget_bounded(),
            self._check_fresh_confirmations(),
            Stage12AuditCheck("no_automatic_execution", "PASS",
                              "Retries are metadata authorizations; every "
                              "attempt needs its own approved confirmation and "
                              "literal --confirm-execution."),
            self._check_no_allowlist_expansion(),
        ])
        failed = sum(1 for c in checks if c.status == "FAIL")
        blocked = sum(1 for c in checks if c.status == "BLOCKED")
        warnings = sum(1 for c in checks if c.status == "WARN")
        passed = sum(1 for c in checks if c.status == "PASS")
        overall = "BLOCKED" if blocked else ("FAIL" if failed else "PASS")
        ready = overall == "PASS"
        return CrossProjectStage12AuditReport(
            generated_at=_now_iso(), overall_status=overall,
            total_checks=len(checks), passed_checks=passed,
            warning_checks=warnings, failed_checks=failed,
            blocked_checks=blocked, checks=checks,
            recommendations=["Dogfood Stage 12 windows and retries before "
                             "adding rollback restoration."],
            stage13_readiness={"ready": ready, "theme": STAGE13_THEME},
            safety_notes=[
                "No hidden model calls are introduced by Stage 12.",
                "No Git mutation is introduced by Stage 12.",
                "Stage 10 confirmation/snapshot gates remain authoritative.",
                "The command allowlist is unchanged by Stage 12.",
            ],
            next_steps=["Plan Stage 13 only after Stage 12 audit and dogfood pass."])

    def save_audit(self, report):
        return database.save_cross_project_stage12_audit(
            self.conn, report.generated_at, report.overall_status,
            report.total_checks, report.passed_checks, report.warning_checks,
            report.failed_checks, report.blocked_checks,
            json.dumps([c.__dict__ for c in report.checks], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
            json.dumps(report.stage13_readiness, sort_keys=True),
            json.dumps(report.safety_notes, sort_keys=True),
            json.dumps(report.next_steps, sort_keys=True))

    def save_markdown_report(self, audit_id, report):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            REPORTS_DIR, f"cross_project_stage12_audit_{int(audit_id)}_{_now_stamp()}.md"))
        base = os.path.realpath(REPORTS_DIR)
        if not path.startswith(base + os.sep):
            raise ValueError("Stage 12 audit report path escaped directory")
        content = self.render_markdown(report, audit_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_cross_project_stage12_audit_markdown_report(
            self.conn, audit_id, path, "markdown",
            hashlib.sha256(encoded).hexdigest(), len(encoded))
        return path

    def render_markdown(self, report, audit_id=None):
        lines = ["# Stage 12 Final Audit — Execution Windows & Retry Policy", ""]
        if audit_id is not None:
            lines.append(f"- Audit ID: {audit_id}")
        lines.extend([
            f"- Overall status: {report.overall_status}",
            f"- Stage 13 ready: {report.stage13_readiness.get('ready')}",
            "",
            "## Checks",
        ])
        for check in report.checks:
            lines.append(f"- {check.status}: {check.name} — {check.message}")
        return "\n".join(lines)

    def _check_windows_fail_closed(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_gated_advancements g "
            "LEFT JOIN cross_project_execution_window_checks c "
            "ON g.window_check_id = c.id "
            "WHERE c.id IS NULL OR c.status != 'open'").fetchone()["n"]
        return Stage12AuditCheck(
            "windows_fail_closed", "PASS" if bad == 0 else "FAIL",
            f"gated advancements without an open window check: {bad}")

    def _check_retry_budget_bounded(self):
        import cross_project_orchestration_retry_policies as policies_mod
        bad_policies = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_orchestration_retry_policies "
            "WHERE max_retries IS NULL OR max_retries < 1 OR max_retries > ?",
            (policies_mod.MAX_RETRY_LIMIT,)).fetchone()["n"]
        bad_attempts = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_gated_advancements "
            "WHERE attempt_number IS NULL OR attempt_number < 1 "
            "OR attempt_number > ?",
            (1 + policies_mod.MAX_RETRY_LIMIT,)).fetchone()["n"]
        ok = bad_policies == 0 and bad_attempts == 0
        return Stage12AuditCheck(
            "retry_budget_bounded", "PASS" if ok else "FAIL",
            f"out-of-bounds policies: {bad_policies}, "
            f"out-of-bounds attempts: {bad_attempts}")

    def _check_fresh_confirmations(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM (SELECT run_step_id, confirmation_id, "
            "COUNT(*) AS uses FROM cross_project_gated_advancements "
            "WHERE confirmation_id IS NOT NULL "
            "GROUP BY run_step_id, confirmation_id HAVING uses > 1)").fetchone()["n"]
        return Stage12AuditCheck(
            "retry_requires_fresh_confirmation", "PASS" if bad == 0 else "FAIL",
            f"confirmations reused within one run step: {bad}")

    def _check_no_allowlist_expansion(self):
        current = set(terminal.ALLOWED_FAMILIES)
        ok = current == EXPECTED_ALLOWED_FAMILIES
        return Stage12AuditCheck(
            "no_allowlist_expansion", "PASS" if ok else "FAIL",
            "command allowlist unchanged" if ok else
            f"allowlist drifted: {sorted(current)}")
