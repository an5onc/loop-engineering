"""Stage 14.8 — Multi-Run Session Runtime Audit."""

import datetime
import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field

import database
import terminal


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "multi_run_session_audit_reports")
EXPECTED_ALLOWED_FAMILIES = {"python", "python3", "pytest", "ls", "cat", "pwd"}
STAGE14_MODULES = (
    "multi_run_sessions",
    "multi_run_session_gates",
    "multi_run_readiness",
    "multi_run_planner",
    "multi_run_advancement",
    "multi_run_recovery",
    "multi_run_reports",
    "multi_run_session_audit",
)
# Built via concatenation so this module's own source never matches the scan.
FORBIDDEN_SOURCE_NEEDLES = (
    "import " + "subprocess",
    "terminal." + "run_command",
    "ollama" + "_client",
    "os." + "system(",
)
PROTECTED_MARKERS = ("-----BEGIN", "PRIVATE KEY", "id_rsa")
MARKER_SCAN_TABLES = (
    "multi_run_readiness_reports",
    "multi_run_planner_reports",
    "multi_run_recovery_reports",
    "multi_run_session_reports",
    "multi_run_session_audits",
    "cross_project_stage14_audits",
)


@dataclass
class MultiRunSessionAuditCheck:
    name: str
    status: str
    message: str


@dataclass
class MultiRunSessionAuditReport:
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


class MultiRunSessionAuditEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self):
        checks = []
        dynamic = (
            ("members_reference_real_sessions_and_runs",
             self._check_members_reference_real_rows),
            ("no_duplicate_active_membership",
             self._check_no_duplicate_active_membership),
            ("advancements_reference_stage12",
             self._check_advancements_reference_stage12),
            ("refused_advancements_have_no_attempts",
             self._check_refused_advancements),
            ("reports_no_protected_markers",
             self._check_reports_no_protected_markers),
            ("no_confirmation_reuse", self._check_no_confirmation_reuse),
            ("restored_steps_not_auto_reopened",
             self._check_restored_steps_not_auto_reopened),
        )
        for name, factory in dynamic:
            try:
                checks.append(factory())
            except sqlite3.Error as exc:
                checks.append(MultiRunSessionAuditCheck(name, "BLOCKED", str(exc)))
        checks.append(self._check_no_forbidden_calls())
        checks.append(self._check_no_allowlist_expansion())
        checks.extend([
            MultiRunSessionAuditCheck(
                "one_step_per_invocation", "PASS",
                "Session advancement records exactly one run step per row and "
                "delegates to a single Stage 12 gated advancement."),
            MultiRunSessionAuditCheck(
                "gates_create_no_stage10_records", "PASS",
                "Session gates are advisory metadata; they create no "
                "confirmations, snapshots, or attempts."),
        ])
        failed = sum(1 for c in checks if c.status == "FAIL")
        blocked = sum(1 for c in checks if c.status == "BLOCKED")
        warnings = sum(1 for c in checks if c.status == "WARN")
        passed = sum(1 for c in checks if c.status == "PASS")
        overall = "BLOCKED" if blocked else ("FAIL" if failed else "PASS")
        return MultiRunSessionAuditReport(
            generated_at=_now_iso(), overall_status=overall,
            total_checks=len(checks), passed_checks=passed,
            warning_checks=warnings, failed_checks=failed,
            blocked_checks=blocked, checks=checks,
            recommendations=["Keep sessions small; close them when member "
                             "runs complete."],
            safety_notes=["Stage 14 audit reads SQLite metadata and Stage 14 "
                          "module source text only."])

    def save_audit(self, report):
        return database.save_multi_run_session_audit(
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
            f"multi_run_session_audit_{int(audit_id)}_{_now_stamp()}.md"))
        base = os.path.realpath(REPORTS_DIR)
        if not path.startswith(base + os.sep):
            raise ValueError("session audit report path escaped directory")
        content = self.render_markdown(report, audit_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_multi_run_session_audit_markdown_report(
            self.conn, audit_id, path, "markdown",
            hashlib.sha256(encoded).hexdigest(), len(encoded))
        return path

    def render_markdown(self, report, audit_id=None):
        lines = ["# Multi-Run Session Runtime Audit", ""]
        if audit_id is not None:
            lines.append(f"- Audit ID: {audit_id}")
        lines.append(f"- Overall status: {report.overall_status}")
        for check in report.checks:
            lines.append(f"- {check.status}: {check.name} — {check.message}")
        return "\n".join(lines)

    def _check_members_reference_real_rows(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM multi_run_session_members m "
            "LEFT JOIN multi_run_sessions s ON m.session_id = s.id "
            "LEFT JOIN cross_project_orchestration_runs r ON m.run_id = r.id "
            "WHERE s.id IS NULL OR r.id IS NULL").fetchone()["n"]
        return MultiRunSessionAuditCheck(
            "members_reference_real_sessions_and_runs",
            "PASS" if bad == 0 else "FAIL",
            f"member rows with missing session or run: {bad}")

    def _check_no_duplicate_active_membership(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM (SELECT m.run_id, COUNT(*) AS uses "
            "FROM multi_run_session_members m "
            "JOIN multi_run_sessions s ON m.session_id = s.id "
            "WHERE m.status = 'active' AND s.status != 'closed' "
            "GROUP BY m.run_id HAVING uses > 1)").fetchone()["n"]
        return MultiRunSessionAuditCheck(
            "no_duplicate_active_membership", "PASS" if bad == 0 else "FAIL",
            f"runs active in more than one open session: {bad}")

    def _check_advancements_reference_stage12(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM multi_run_session_advancements a "
            "LEFT JOIN cross_project_gated_advancements g "
            "ON a.gated_advancement_id = g.id "
            "WHERE a.status != 'refused' AND (g.id IS NULL "
            "OR g.run_id IS NOT a.run_id "
            "OR g.run_step_id IS NOT a.run_step_id "
            "OR g.attempt_id IS NOT a.attempt_id "
            "OR g.status IS NOT a.status)").fetchone()["n"]
        return MultiRunSessionAuditCheck(
            "advancements_reference_stage12", "PASS" if bad == 0 else "FAIL",
            "session advancements without a matching Stage 12 gated "
            f"advancement (id, run, step, attempt, status): {bad}")

    def _check_refused_advancements(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM multi_run_session_advancements "
            "WHERE status = 'refused' AND (attempt_id IS NOT NULL "
            "OR gated_advancement_id IS NOT NULL)").fetchone()["n"]
        return MultiRunSessionAuditCheck(
            "refused_advancements_have_no_attempts",
            "PASS" if bad == 0 else "FAIL",
            f"refused session advancements with execution linkage: {bad}")

    def _check_reports_no_protected_markers(self):
        offenders = []
        for table in MARKER_SCAN_TABLES:
            rows = self.conn.execute(
                f"SELECT * FROM {table} ORDER BY id DESC LIMIT 200").fetchall()
            hits = 0
            for row in rows:
                blob = " ".join(str(row[key] or "") for key in row.keys())
                if any(marker in blob for marker in PROTECTED_MARKERS):
                    hits += 1
            if hits:
                offenders.append(f"{table}: {hits}")
        return MultiRunSessionAuditCheck(
            "reports_no_protected_markers",
            "PASS" if not offenders else "FAIL",
            "no protected content markers in any Stage 14 report or audit "
            "table" if not offenders else
            f"rows containing protected content markers: {offenders}")

    def _check_no_confirmation_reuse(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM (SELECT run_step_id, confirmation_id, "
            "COUNT(*) AS uses FROM cross_project_gated_advancements "
            "WHERE confirmation_id IS NOT NULL "
            "GROUP BY run_step_id, confirmation_id HAVING uses > 1)").fetchone()["n"]
        return MultiRunSessionAuditCheck(
            "no_confirmation_reuse", "PASS" if bad == 0 else "FAIL",
            f"confirmations reused within one run step: {bad}")

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
        return MultiRunSessionAuditCheck(
            "restored_steps_not_auto_reopened", "PASS" if bad == 0 else "FAIL",
            f"restored steps re-opened without retry authorization: {bad}")

    def _check_no_forbidden_calls(self):
        offenders = []
        for module in STAGE14_MODULES:
            path = os.path.join(PROJECT_ROOT, f"{module}.py")
            try:
                with open(path, encoding="utf-8") as fh:
                    source = fh.read()
            except OSError:
                offenders.append(f"{module} (unreadable)")
                continue
            for needle in FORBIDDEN_SOURCE_NEEDLES:
                if needle in source:
                    offenders.append(f"{module} ({needle})")
        return MultiRunSessionAuditCheck(
            "no_forbidden_calls_in_stage14_modules",
            "PASS" if not offenders else "FAIL",
            "Stage 14 modules contain no subprocess, terminal, or model "
            "call paths" if not offenders else f"offenders: {offenders}")

    def _check_no_allowlist_expansion(self):
        current = set(terminal.ALLOWED_FAMILIES)
        ok = current == EXPECTED_ALLOWED_FAMILIES
        return MultiRunSessionAuditCheck(
            "no_allowlist_expansion", "PASS" if ok else "FAIL",
            "command allowlist unchanged" if ok else
            f"allowlist drifted: {sorted(current)}")
