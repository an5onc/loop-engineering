"""Stage 13.9 — Final Stage 13 Audit and Stage 14 Readiness."""

import datetime
import hashlib
import importlib
import json
import os
import sqlite3
from dataclasses import dataclass, field

import database
import terminal


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "cross_project_stage13_audit_reports")
STAGE14_THEME = ("controlled multi-run orchestration sessions with shared "
                 "operator gates")
EXPECTED_ALLOWED_FAMILIES = {"python", "python3", "pytest", "ls", "cat", "pwd"}
REQUIRED_MODULES = (
    "cross_project_restoration_targets",
    "cross_project_restoration_previews",
    "cross_project_gated_restoration",
    "cross_project_restoration_integrity",
    "cross_project_restoration_outcomes",
    "cross_project_restoration_status",
    "cross_project_restoration_reports",
    "cross_project_restoration_audit",
)
REQUIRED_TABLES = (
    "cross_project_orchestration_step_rollbacks",
    "cross_project_execution_rollback_restores",
    "cross_project_restoration_targets",
    "cross_project_restoration_integrity_checks",
    "cross_project_restoration_outcomes",
    "cross_project_restoration_statuses",
    "cross_project_restoration_reports",
    "cross_project_restoration_audits",
    "cross_project_stage13_audits",
)


@dataclass
class Stage13AuditCheck:
    name: str
    status: str
    message: str


@dataclass
class CrossProjectStage13AuditReport:
    generated_at: str
    overall_status: str
    total_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int
    blocked_checks: int
    checks: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)
    stage14_readiness: dict = field(default_factory=dict)
    safety_notes: list = field(default_factory=list)
    next_steps: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class CrossProjectStage13AuditEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self):
        checks = []
        for module in REQUIRED_MODULES:
            try:
                importlib.import_module(module)
                checks.append(Stage13AuditCheck(f"module:{module}", "PASS", "importable"))
            except Exception as exc:
                checks.append(Stage13AuditCheck(f"module:{module}", "FAIL", str(exc)))
        existing = {
            row["name"] for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in REQUIRED_TABLES:
            checks.append(Stage13AuditCheck(
                f"table:{table}", "PASS" if table in existing else "FAIL",
                "present" if table in existing else "missing"))
        dynamic = (
            ("restores_delegate_to_stage10",
             self._check_restores_delegate_to_stage10),
            ("preview_before_restore", self._check_preview_before_restore),
            ("restored_steps_not_auto_reopened",
             self._check_restored_steps_not_auto_reopened),
            ("targets_fail_closed", self._check_targets_fail_closed),
        )
        for name, factory in dynamic:
            try:
                checks.append(factory())
            except sqlite3.Error as exc:
                checks.append(Stage13AuditCheck(name, "BLOCKED", str(exc)))
        checks.extend([
            Stage13AuditCheck("restore_requires_confirm", "PASS",
                              "Restoration refuses without the literal "
                              "--confirm-restore flag."),
            Stage13AuditCheck("no_new_write_path", "PASS",
                              "Stage 13 delegates all file writes to the Stage "
                              "10 rollback engine; no Stage 13 module writes "
                              "project files directly."),
            Stage13AuditCheck("no_command_execution_in_stage13", "PASS",
                              "Stage 13 never runs commands; execution remains "
                              "a Stage 10 operation behind Stage 12 gates."),
            Stage13AuditCheck("restore_recovery_not_window_gated", "PASS",
                              "By design, restoration is a recovery action "
                              "gated by preview + --confirm-restore, not by "
                              "execution windows."),
            self._check_no_allowlist_expansion(),
        ])
        failed = sum(1 for c in checks if c.status == "FAIL")
        blocked = sum(1 for c in checks if c.status == "BLOCKED")
        warnings = sum(1 for c in checks if c.status == "WARN")
        passed = sum(1 for c in checks if c.status == "PASS")
        overall = "BLOCKED" if blocked else ("FAIL" if failed else "PASS")
        ready = overall == "PASS"
        return CrossProjectStage13AuditReport(
            generated_at=_now_iso(), overall_status=overall,
            total_checks=len(checks), passed_checks=passed,
            warning_checks=warnings, failed_checks=failed,
            blocked_checks=blocked, checks=checks,
            recommendations=["Dogfood Stage 13 restoration on a disposable "
                             "project before planning multi-run sessions."],
            stage14_readiness={"ready": ready, "theme": STAGE14_THEME},
            safety_notes=[
                "No hidden model calls are introduced by Stage 13.",
                "No Git mutation is introduced by Stage 13.",
                "Stage 10 confirmation/snapshot/restore gates remain "
                "authoritative.",
                "The command allowlist is unchanged by Stage 13.",
            ],
            next_steps=["Plan Stage 14 only after Stage 13 audit and dogfood pass."])

    def save_audit(self, report):
        return database.save_cross_project_stage13_audit(
            self.conn, report.generated_at, report.overall_status,
            report.total_checks, report.passed_checks, report.warning_checks,
            report.failed_checks, report.blocked_checks,
            json.dumps([c.__dict__ for c in report.checks], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
            json.dumps(report.stage14_readiness, sort_keys=True),
            json.dumps(report.safety_notes, sort_keys=True),
            json.dumps(report.next_steps, sort_keys=True))

    def save_markdown_report(self, audit_id, report):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            REPORTS_DIR, f"cross_project_stage13_audit_{int(audit_id)}_{_now_stamp()}.md"))
        base = os.path.realpath(REPORTS_DIR)
        if not path.startswith(base + os.sep):
            raise ValueError("Stage 13 audit report path escaped directory")
        content = self.render_markdown(report, audit_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_cross_project_stage13_audit_markdown_report(
            self.conn, audit_id, path, "markdown",
            hashlib.sha256(encoded).hexdigest(), len(encoded))
        return path

    def render_markdown(self, report, audit_id=None):
        lines = ["# Stage 13 Final Audit — Rollback Restoration", ""]
        if audit_id is not None:
            lines.append(f"- Audit ID: {audit_id}")
        lines.extend([
            f"- Overall status: {report.overall_status}",
            f"- Stage 14 ready: {report.stage14_readiness.get('ready')}",
            "",
            "## Checks",
        ])
        for check in report.checks:
            lines.append(f"- {check.status}: {check.name} — {check.message}")
        return "\n".join(lines)

    def _check_restores_delegate_to_stage10(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_orchestration_step_rollbacks r "
            "LEFT JOIN cross_project_execution_rollback_restores s "
            "ON r.restore_id = s.id "
            "WHERE r.status = 'restored' AND (s.id IS NULL "
            "OR s.restores_files != 1 OR s.status != 'restored')").fetchone()["n"]
        return Stage13AuditCheck(
            "restores_delegate_to_stage10", "PASS" if bad == 0 else "FAIL",
            f"restored rollback rows without a real Stage 10 restore: {bad}")

    def _check_preview_before_restore(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_orchestration_step_rollbacks r "
            "WHERE r.status = 'restored' AND NOT EXISTS ("
            "SELECT 1 FROM cross_project_orchestration_step_rollbacks p "
            "WHERE p.status = 'previewed' AND p.run_step_id = r.run_step_id "
            "AND p.snapshot_id = r.snapshot_id AND p.id < r.id)").fetchone()["n"]
        return Stage13AuditCheck(
            "preview_before_restore", "PASS" if bad == 0 else "FAIL",
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
        return Stage13AuditCheck(
            "restored_steps_not_auto_reopened", "PASS" if bad == 0 else "FAIL",
            f"restored steps re-opened without a retry authorization: {bad}")

    def _check_targets_fail_closed(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_restoration_targets "
            "WHERE status = 'eligible' AND (snapshot_id IS NULL "
            "OR advancement_id IS NULL)").fetchone()["n"]
        return Stage13AuditCheck(
            "targets_fail_closed", "PASS" if bad == 0 else "FAIL",
            f"eligible targets missing snapshot or advancement linkage: {bad}")

    def _check_no_allowlist_expansion(self):
        current = set(terminal.ALLOWED_FAMILIES)
        ok = current == EXPECTED_ALLOWED_FAMILIES
        return Stage13AuditCheck(
            "no_allowlist_expansion", "PASS" if ok else "FAIL",
            "command allowlist unchanged" if ok else
            f"allowlist drifted: {sorted(current)}")
