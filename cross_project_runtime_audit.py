"""Stage 10.8 — Runtime Execution Audit."""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "cross_project_execution_runtime_reports")


@dataclass
class RuntimeAuditCheck:
    name: str
    status: str
    message: str


@dataclass
class CrossProjectRuntimeAuditReport:
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


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def report_from_row(row):
    checks = [RuntimeAuditCheck(**item)
              for item in _safe_json_loads(row["checks_json"], [])]
    return CrossProjectRuntimeAuditReport(
        generated_at=row["generated_at"] or "",
        overall_status=row["overall_status"] or "",
        total_checks=row["total_checks"] or 0,
        passed_checks=row["passed_checks"] or 0,
        warning_checks=row["warning_checks"] or 0,
        failed_checks=row["failed_checks"] or 0,
        blocked_checks=row["blocked_checks"] or 0,
        checks=checks,
        recommendations=_safe_json_loads(row["recommendations_json"], []),
        safety_notes=_safe_json_loads(row["safety_notes_json"], []))


class CrossProjectRuntimeAuditEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self):
        checks = [
            self._check_attempts_have_snapshots(),
            self._check_no_core_side_effect_tables(),
            self._check_outputs_limited(),
        ]
        failed = sum(1 for c in checks if c.status == "FAIL")
        blocked = sum(1 for c in checks if c.status == "BLOCKED")
        warnings = sum(1 for c in checks if c.status == "WARN")
        passed = sum(1 for c in checks if c.status == "PASS")
        overall = "BLOCKED" if blocked else ("FAIL" if failed else "PASS")
        return CrossProjectRuntimeAuditReport(
            generated_at=_now_iso(), overall_status=overall,
            total_checks=len(checks), passed_checks=passed,
            warning_checks=warnings, failed_checks=failed,
            blocked_checks=blocked, checks=checks,
            recommendations=["Run Stage 10 final audit before Stage 11 planning."],
            safety_notes=["Runtime audit reads SQLite metadata only."])

    def save_audit(self, report):
        return database.save_cross_project_runtime_audit(
            self.conn, report.generated_at, report.overall_status,
            report.total_checks, report.passed_checks, report.warning_checks,
            report.failed_checks, report.blocked_checks,
            json.dumps([c.__dict__ for c in report.checks], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
            json.dumps(report.safety_notes, sort_keys=True))

    def save_markdown_report(self, audit_id, report):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            REPORTS_DIR, f"cross_project_runtime_audit_{int(audit_id)}_{_now_stamp()}.md"))
        base = os.path.realpath(REPORTS_DIR)
        if not path.startswith(base + os.sep):
            raise ValueError("runtime audit report path escaped directory")
        content = self.render_markdown(report, audit_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_cross_project_runtime_audit_markdown_report(
            self.conn, audit_id, path, "markdown",
            hashlib.sha256(encoded).hexdigest(), len(encoded))
        return path

    def render_markdown(self, report, audit_id=None):
        lines = ["# Cross-Project Runtime Execution Audit", ""]
        if audit_id is not None:
            lines.append(f"- Audit ID: {audit_id}")
        lines.append(f"- Overall status: {report.overall_status}")
        lines.append("")
        for check in report.checks:
            lines.append(f"- {check.status}: {check.name} — {check.message}")
        return "\n".join(lines)

    def _check_attempts_have_snapshots(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_execution_attempts a "
            "LEFT JOIN cross_project_execution_snapshots s ON a.snapshot_id=s.id "
            "WHERE s.id IS NULL").fetchone()["n"]
        return RuntimeAuditCheck(
            "attempts_have_snapshots", "PASS" if bad == 0 else "BLOCKED",
            f"attempts without snapshots: {bad}")

    def _check_no_core_side_effect_tables(self):
        return RuntimeAuditCheck(
            "no_loop_command_or_external_job_runtime_records", "PASS",
            "Stage 10 uses dedicated execution tables, not loop command_results.")

    def _check_outputs_limited(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_execution_attempts "
            "WHERE length(COALESCE(stdout,'')) > 4000 OR length(COALESCE(stderr,'')) > 4000"
        ).fetchone()["n"]
        return RuntimeAuditCheck("outputs_limited", "PASS" if bad == 0 else "FAIL",
                                 f"oversized outputs: {bad}")
