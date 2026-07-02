"""Stage 12.7 — Window & Retry Reports."""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field

import database
import cross_project_execution_window_checks as checks_mod
import cross_project_execution_windows as windows_mod
import cross_project_orchestration_retry_policies as policies_mod
import cross_project_orchestration_runs as runs_mod


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "cross_project_window_retry_reports")


@dataclass
class CrossProjectWindowRetryReport:
    run_id: int
    generated_at: str
    overall_status: str
    summary: str
    next_action: str
    windows: list = field(default_factory=list)
    retries: dict = field(default_factory=dict)
    advancements: list = field(default_factory=list)
    safety_notes: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class CrossProjectWindowRetryReportBuilder:
    def __init__(self, conn):
        self.conn = conn
        self.runs = runs_mod.CrossProjectOrchestrationRunManager(conn)
        self.windows = windows_mod.CrossProjectExecutionWindowManager(conn)
        self.policies = policies_mod.CrossProjectOrchestrationRetryPolicyManager(conn)

    def build_report(self, run_id):
        run = self.runs.get_run(int(run_id))
        if run is None:
            raise ValueError(f"no cross-project orchestration run {run_id}")
        windows = self.windows.list_windows(run_id=run.id, limit=200)
        window_dicts = [w.__dict__ for w in windows]
        policy = self.policies.get_policy_for_run(run.id)
        requests = [
            dict(row) for row in
            database.list_cross_project_orchestration_retry_requests(
                self.conn, run_id=run.id)
        ]
        gated = [
            dict(row) for row in database.list_cross_project_gated_advancements(
                self.conn, run_id=run.id)
        ]
        _, window_status, _ = checks_mod.select_window(
            windows, datetime.datetime.now())
        retries = {
            "policy": policy.__dict__ if policy else None,
            "requests": requests,
        }
        summary = (
            f"Run {run.id}: {len(windows)} window(s), window status "
            f"{window_status}, {len(gated)} gated advancement(s), "
            f"retry policy "
            f"{'max_retries=' + str(policy.max_retries) if policy else 'none'}.")
        next_action = _next_action(window_status, run, policy)
        return CrossProjectWindowRetryReport(
            run_id=run.id, generated_at=_now_iso(), overall_status=run.status,
            summary=summary, next_action=next_action, windows=window_dicts,
            retries=retries, advancements=gated,
            safety_notes=[
                "Stage 12 reports are metadata-only.",
                "Windows and retries never execute commands; only a gated "
                "advancement with --confirm-execution reaches the Stage 10 "
                "runtime.",
            ])

    def save_report(self, report):
        return database.save_cross_project_window_retry_report(
            self.conn, report.run_id, report.generated_at,
            report.overall_status, report.summary, report.next_action,
            json.dumps(report.windows, sort_keys=True),
            json.dumps(report.retries, sort_keys=True),
            json.dumps(report.advancements, sort_keys=True),
            json.dumps(report.safety_notes, sort_keys=True))

    def save_markdown_report(self, report_id, report):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            REPORTS_DIR,
            f"cross_project_window_retry_report_{int(report_id)}_{_now_stamp()}.md"))
        base = os.path.realpath(REPORTS_DIR)
        if not path.startswith(base + os.sep):
            raise ValueError("window/retry report path escaped directory")
        content = self.render_markdown(report, report_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_cross_project_window_retry_markdown_report(
            self.conn, report_id, path, "markdown",
            hashlib.sha256(encoded).hexdigest(), len(encoded))
        return path

    def render_markdown(self, report, report_id=None):
        lines = ["# Cross-Project Window & Retry Report", ""]
        if report_id is not None:
            lines.append(f"- Report ID: {report_id}")
        lines.extend([
            f"- Run ID: {report.run_id}",
            f"- Status: {report.overall_status}",
            f"- Next action: {report.next_action}",
            f"- Summary: {report.summary}",
            "",
            "## Windows",
        ])
        if not report.windows:
            lines.append("- (none)")
        for window in report.windows:
            lines.append(
                f"- Window {window['id']}: {window['status']} "
                f"label={window['label']}")
        lines.extend(["", "## Gated Advancements"])
        if not report.advancements:
            lines.append("- (none)")
        for adv in report.advancements:
            lines.append(
                f"- Advancement {adv['id']}: attempt {adv['attempt_number']} "
                f"status={adv['status']}")
        return "\n".join(lines)


def _next_action(window_status, run, policy):
    if window_status != "open":
        return "open an execution window before advancing"
    if any(s.status == "blocked" for s in run.steps):
        if policy is None:
            return "set a retry policy to authorize a bounded retry"
        return "request an authorized retry for the blocked step"
    if any(s.status == "pending" for s in run.steps):
        return "advance the pending step with --confirm-execution"
    return "review the window/retry audit"
