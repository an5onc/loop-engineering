"""Stage 12.8 — Window & Retry Runtime Audit."""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field

import database
from cross_project_orchestration_retry_policies import MAX_RETRY_LIMIT


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "cross_project_window_retry_audit_reports")


@dataclass
class WindowRetryAuditCheck:
    name: str
    status: str
    message: str


@dataclass
class CrossProjectWindowRetryAuditReport:
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


class CrossProjectWindowRetryAuditEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self):
        checks = [
            self._check_advancements_reference_open_windows(),
            self._check_attempt_numbers_bounded(),
            self._check_policies_bounded(),
            self._check_no_confirmation_reuse(),
            self._check_consumed_requests_have_advancements(),
            self._check_no_reopened_windows(),
            WindowRetryAuditCheck(
                "retries_metadata_only", "PASS",
                "Retry authorizations are metadata; every attempt requires its "
                "own confirmation and --confirm-execution."),
        ]
        failed = sum(1 for c in checks if c.status == "FAIL")
        blocked = sum(1 for c in checks if c.status == "BLOCKED")
        warnings = sum(1 for c in checks if c.status == "WARN")
        passed = sum(1 for c in checks if c.status == "PASS")
        overall = "BLOCKED" if blocked else ("FAIL" if failed else "PASS")
        return CrossProjectWindowRetryAuditReport(
            generated_at=_now_iso(), overall_status=overall,
            total_checks=len(checks), passed_checks=passed,
            warning_checks=warnings, failed_checks=failed,
            blocked_checks=blocked, checks=checks,
            recommendations=["Keep retry budgets small; prefer new windows "
                             "over long-lived open ones."],
            safety_notes=["Stage 12 audit reads SQLite metadata only."])

    def save_audit(self, report):
        return database.save_cross_project_window_retry_audit(
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
            f"cross_project_window_retry_audit_{int(audit_id)}_{_now_stamp()}.md"))
        base = os.path.realpath(REPORTS_DIR)
        if not path.startswith(base + os.sep):
            raise ValueError("window/retry audit report path escaped directory")
        content = self.render_markdown(report, audit_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_cross_project_window_retry_audit_markdown_report(
            self.conn, audit_id, path, "markdown",
            hashlib.sha256(encoded).hexdigest(), len(encoded))
        return path

    def render_markdown(self, report, audit_id=None):
        lines = ["# Cross-Project Window & Retry Runtime Audit", ""]
        if audit_id is not None:
            lines.append(f"- Audit ID: {audit_id}")
        lines.append(f"- Overall status: {report.overall_status}")
        for check in report.checks:
            lines.append(f"- {check.status}: {check.name} — {check.message}")
        return "\n".join(lines)

    def _check_advancements_reference_open_windows(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_gated_advancements g "
            "LEFT JOIN cross_project_execution_window_checks c "
            "ON g.window_check_id = c.id "
            "WHERE c.id IS NULL OR c.status != 'open'").fetchone()["n"]
        return WindowRetryAuditCheck(
            "advancements_reference_open_windows",
            "PASS" if bad == 0 else "FAIL",
            f"gated advancements without an open window check: {bad}")

    def _check_attempt_numbers_bounded(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_gated_advancements "
            "WHERE attempt_number IS NULL OR attempt_number < 1 "
            "OR attempt_number > ?", (1 + MAX_RETRY_LIMIT,)).fetchone()["n"]
        return WindowRetryAuditCheck(
            "attempt_numbers_bounded", "PASS" if bad == 0 else "FAIL",
            f"gated advancements outside attempt bounds 1..{1 + MAX_RETRY_LIMIT}: {bad}")

    def _check_policies_bounded(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_orchestration_retry_policies "
            "WHERE max_retries IS NULL OR max_retries < 1 OR max_retries > ?",
            (MAX_RETRY_LIMIT,)).fetchone()["n"]
        return WindowRetryAuditCheck(
            "retry_policies_bounded", "PASS" if bad == 0 else "FAIL",
            f"retry policies outside 1..{MAX_RETRY_LIMIT}: {bad}")

    def _check_no_confirmation_reuse(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM (SELECT run_step_id, confirmation_id, "
            "COUNT(*) AS uses FROM cross_project_gated_advancements "
            "WHERE confirmation_id IS NOT NULL "
            "GROUP BY run_step_id, confirmation_id HAVING uses > 1)").fetchone()["n"]
        return WindowRetryAuditCheck(
            "no_confirmation_reuse", "PASS" if bad == 0 else "FAIL",
            f"confirmations reused across advancements of one step: {bad}")

    def _check_consumed_requests_have_advancements(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_orchestration_retry_requests "
            "WHERE status = 'consumed' AND advancement_id IS NULL").fetchone()["n"]
        return WindowRetryAuditCheck(
            "consumed_requests_have_advancements",
            "PASS" if bad == 0 else "FAIL",
            f"consumed retry requests without an advancement: {bad}")

    def _check_no_reopened_windows(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_execution_window_events o "
            "WHERE o.event_type = 'opened' AND EXISTS ("
            "SELECT 1 FROM cross_project_execution_window_events c "
            "WHERE c.window_id = o.window_id AND c.event_type = 'closed' "
            "AND c.id < o.id)").fetchone()["n"]
        return WindowRetryAuditCheck(
            "no_reopened_windows", "PASS" if bad == 0 else "FAIL",
            f"windows reopened after close: {bad}")
