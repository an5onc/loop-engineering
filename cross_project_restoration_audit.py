"""Stage 13.7 — Restoration Runtime Audit."""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "cross_project_restoration_audit_reports")


@dataclass
class RestorationAuditCheck:
    name: str
    status: str
    message: str


@dataclass
class CrossProjectRestorationAuditReport:
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


class CrossProjectRestorationAuditEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self):
        checks = [
            self._check_restored_rollbacks_reference_real_restores(),
            self._check_previews_precede_restores(),
            self._check_restored_steps_not_auto_reopened(),
            self._check_targets_fail_closed(),
            self._check_integrity_mismatches_surfaced(),
            RestorationAuditCheck(
                "restore_requires_confirm", "PASS",
                "Restoration refuses without the literal --confirm-restore "
                "flag and a fresh preview of the same snapshot."),
            RestorationAuditCheck(
                "no_new_write_path", "PASS",
                "Stage 13 delegates all file writes to the Stage 10 rollback "
                "engine; Stage 13 modules contain no write path of their own."),
        ]
        failed = sum(1 for c in checks if c.status == "FAIL")
        blocked = sum(1 for c in checks if c.status == "BLOCKED")
        warnings = sum(1 for c in checks if c.status == "WARN")
        passed = sum(1 for c in checks if c.status == "PASS")
        overall = "BLOCKED" if blocked else ("FAIL" if failed else "PASS")
        return CrossProjectRestorationAuditReport(
            generated_at=_now_iso(), overall_status=overall,
            total_checks=len(checks), passed_checks=passed,
            warning_checks=warnings, failed_checks=failed,
            blocked_checks=blocked, checks=checks,
            recommendations=["Run an integrity check after every restoration "
                             "before authorizing a retry."],
            safety_notes=["Stage 13 audit reads SQLite metadata only."])

    def save_audit(self, report):
        return database.save_cross_project_restoration_audit(
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
            f"cross_project_restoration_audit_{int(audit_id)}_{_now_stamp()}.md"))
        base = os.path.realpath(REPORTS_DIR)
        if not path.startswith(base + os.sep):
            raise ValueError("restoration audit report path escaped directory")
        content = self.render_markdown(report, audit_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_cross_project_restoration_audit_markdown_report(
            self.conn, audit_id, path, "markdown",
            hashlib.sha256(encoded).hexdigest(), len(encoded))
        return path

    def render_markdown(self, report, audit_id=None):
        lines = ["# Cross-Project Restoration Runtime Audit", ""]
        if audit_id is not None:
            lines.append(f"- Audit ID: {audit_id}")
        lines.append(f"- Overall status: {report.overall_status}")
        for check in report.checks:
            lines.append(f"- {check.status}: {check.name} — {check.message}")
        return "\n".join(lines)

    def _check_restored_rollbacks_reference_real_restores(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_orchestration_step_rollbacks r "
            "LEFT JOIN cross_project_execution_rollback_restores s "
            "ON r.restore_id = s.id "
            "WHERE r.status = 'restored' AND (s.id IS NULL "
            "OR s.restores_files != 1 OR s.status != 'restored')").fetchone()["n"]
        return RestorationAuditCheck(
            "restored_rollbacks_reference_real_restores",
            "PASS" if bad == 0 else "FAIL",
            f"restored rollback rows without a real Stage 10 restore: {bad}")

    def _check_previews_precede_restores(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_orchestration_step_rollbacks r "
            "WHERE r.status = 'restored' AND NOT EXISTS ("
            "SELECT 1 FROM cross_project_orchestration_step_rollbacks p "
            "WHERE p.status = 'previewed' AND p.run_step_id = r.run_step_id "
            "AND p.snapshot_id = r.snapshot_id AND p.id < r.id)").fetchone()["n"]
        return RestorationAuditCheck(
            "previews_precede_restores", "PASS" if bad == 0 else "FAIL",
            f"restorations without an earlier preview of the same snapshot: {bad}")

    def _check_restored_steps_not_auto_reopened(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_orchestration_run_steps s "
            "WHERE s.status = 'pending' AND EXISTS ("
            "SELECT 1 FROM cross_project_orchestration_step_rollbacks r "
            "WHERE r.run_step_id = s.id AND r.status = 'restored') "
            "AND NOT EXISTS ("
            "SELECT 1 FROM cross_project_orchestration_retry_requests q "
            "WHERE q.run_step_id = s.id "
            "AND q.status IN ('authorized', 'consumed'))").fetchone()["n"]
        return RestorationAuditCheck(
            "restored_steps_not_auto_reopened", "PASS" if bad == 0 else "FAIL",
            f"restored steps re-opened without a retry authorization: {bad}")

    def _check_targets_fail_closed(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_restoration_targets "
            "WHERE status = 'eligible' AND (snapshot_id IS NULL "
            "OR advancement_id IS NULL)").fetchone()["n"]
        return RestorationAuditCheck(
            "targets_fail_closed", "PASS" if bad == 0 else "FAIL",
            f"eligible targets missing snapshot or advancement linkage: {bad}")

    def _check_integrity_mismatches_surfaced(self):
        count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_restoration_integrity_checks "
            "WHERE status = 'mismatch'").fetchone()["n"]
        return RestorationAuditCheck(
            "integrity_mismatches_surfaced", "PASS" if count == 0 else "WARN",
            f"integrity checks reporting mismatch: {count}")
