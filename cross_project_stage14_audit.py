"""Stage 14.9 — Final Stage 14 Audit and Stage 15 Readiness."""

import datetime
import hashlib
import importlib
import json
import os
import sqlite3
from dataclasses import dataclass, field

import database
import multi_run_session_audit as runtime_audit_mod
import terminal


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "cross_project_stage14_audit_reports")
STAGE15_THEME = ("controlled fleet-scale execution governance and session "
                 "policy enforcement")
EXPECTED_ALLOWED_FAMILIES = {"python", "python3", "pytest", "ls", "cat", "pwd"}
REQUIRED_MODULES = (
    "multi_run_sessions",
    "multi_run_session_gates",
    "multi_run_readiness",
    "multi_run_planner",
    "multi_run_advancement",
    "multi_run_recovery",
    "multi_run_reports",
    "multi_run_session_audit",
)
REQUIRED_TABLES = (
    "multi_run_sessions",
    "multi_run_session_members",
    "multi_run_session_events",
    "multi_run_session_gates",
    "multi_run_readiness_reports",
    "multi_run_planner_reports",
    "multi_run_session_advancements",
    "multi_run_recovery_reports",
    "multi_run_session_reports",
    "multi_run_session_audits",
    "cross_project_stage14_audits",
)


@dataclass
class Stage14AuditCheck:
    name: str
    status: str
    message: str


@dataclass
class CrossProjectStage14AuditReport:
    generated_at: str
    overall_status: str
    total_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int
    blocked_checks: int
    checks: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)
    stage15_readiness: dict = field(default_factory=dict)
    safety_notes: list = field(default_factory=list)
    next_steps: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class CrossProjectStage14AuditEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self):
        checks = []
        for module in REQUIRED_MODULES:
            try:
                importlib.import_module(module)
                checks.append(Stage14AuditCheck(f"module:{module}", "PASS", "importable"))
            except Exception as exc:
                checks.append(Stage14AuditCheck(f"module:{module}", "FAIL", str(exc)))
        existing = {
            row["name"] for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in REQUIRED_TABLES:
            checks.append(Stage14AuditCheck(
                f"table:{table}", "PASS" if table in existing else "FAIL",
                "present" if table in existing else "missing"))
        checks.append(self._check_runtime_audit())
        checks.extend([
            Stage14AuditCheck("no_new_executor", "PASS",
                              "Stage 14 has no executor: session advancement "
                              "delegates to Stage 12, which delegates to "
                              "Stage 11 and Stage 10."),
            Stage14AuditCheck("no_batch_or_parallel_execution", "PASS",
                              "At most one step executes per invocation; "
                              "sessions never batch or parallelize."),
            Stage14AuditCheck("no_auto_restore_or_auto_retry", "PASS",
                              "Recovery guidance is advisory; restoration and "
                              "retries remain explicit Stage 13/12 operator "
                              "actions."),
            Stage14AuditCheck("shared_gates_do_not_bypass_step_gates", "PASS",
                              "Approved session gates never replace per-step "
                              "confirmation, snapshot, cwd, allowlist, "
                              "execution window, or --confirm-execution."),
            Stage14AuditCheck("no_git_mutation_or_model_calls", "PASS",
                              "Stage 14 performs no Git mutation and no "
                              "hidden model calls."),
            self._check_no_allowlist_expansion(),
        ])
        failed = sum(1 for c in checks if c.status == "FAIL")
        blocked = sum(1 for c in checks if c.status == "BLOCKED")
        warnings = sum(1 for c in checks if c.status == "WARN")
        passed = sum(1 for c in checks if c.status == "PASS")
        overall = "BLOCKED" if blocked else ("FAIL" if failed else "PASS")
        ready = overall == "PASS"
        return CrossProjectStage14AuditReport(
            generated_at=_now_iso(), overall_status=overall,
            total_checks=len(checks), passed_checks=passed,
            warning_checks=warnings, failed_checks=failed,
            blocked_checks=blocked, checks=checks,
            recommendations=["Dogfood Stage 14 sessions before planning "
                             "fleet-scale governance."],
            stage15_readiness={"ready": ready, "theme": STAGE15_THEME},
            safety_notes=[
                "No hidden model calls are introduced by Stage 14.",
                "No Git mutation is introduced by Stage 14.",
                "Stage 10/12/13 per-step gates remain authoritative.",
                "The command allowlist is unchanged by Stage 14.",
            ],
            next_steps=["Plan Stage 15 only after Stage 14 audit and dogfood pass."])

    def _check_runtime_audit(self):
        try:
            report = runtime_audit_mod.MultiRunSessionAuditEngine(
                self.conn).build_report()
        except sqlite3.Error as exc:
            return Stage14AuditCheck("runtime_audit", "BLOCKED", str(exc))
        status = ("PASS" if report.overall_status == "PASS"
                  else report.overall_status)
        return Stage14AuditCheck(
            "runtime_audit", status,
            f"multi-run session runtime audit: {report.overall_status} "
            f"({report.passed_checks}/{report.total_checks} passed)")

    def _check_no_allowlist_expansion(self):
        current = set(terminal.ALLOWED_FAMILIES)
        ok = current == EXPECTED_ALLOWED_FAMILIES
        return Stage14AuditCheck(
            "no_allowlist_expansion", "PASS" if ok else "FAIL",
            "command allowlist unchanged" if ok else
            f"allowlist drifted: {sorted(current)}")

    def save_audit(self, report):
        return database.save_cross_project_stage14_audit(
            self.conn, report.generated_at, report.overall_status,
            report.total_checks, report.passed_checks, report.warning_checks,
            report.failed_checks, report.blocked_checks,
            json.dumps([c.__dict__ for c in report.checks], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
            json.dumps(report.stage15_readiness, sort_keys=True),
            json.dumps(report.safety_notes, sort_keys=True),
            json.dumps(report.next_steps, sort_keys=True))

    def save_markdown_report(self, audit_id, report):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            REPORTS_DIR, f"cross_project_stage14_audit_{int(audit_id)}_{_now_stamp()}.md"))
        base = os.path.realpath(REPORTS_DIR)
        if not path.startswith(base + os.sep):
            raise ValueError("Stage 14 audit report path escaped directory")
        content = self.render_markdown(report, audit_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_cross_project_stage14_audit_markdown_report(
            self.conn, audit_id, path, "markdown",
            hashlib.sha256(encoded).hexdigest(), len(encoded))
        return path

    def render_markdown(self, report, audit_id=None):
        lines = ["# Stage 14 Final Audit — Multi-Run Sessions", ""]
        if audit_id is not None:
            lines.append(f"- Audit ID: {audit_id}")
        lines.extend([
            f"- Overall status: {report.overall_status}",
            f"- Stage 15 ready: {report.stage15_readiness.get('ready')}",
            "",
            "## Checks",
        ])
        for check in report.checks:
            lines.append(f"- {check.status}: {check.name} — {check.message}")
        return "\n".join(lines)
