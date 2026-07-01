"""Stage 11.7 — Orchestration Reports."""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field

import database
import cross_project_orchestration_rollback as rollback_mod
import cross_project_orchestration_runs as runs_mod


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "cross_project_orchestration_reports")


@dataclass
class CrossProjectOrchestrationReport:
    run_id: int
    generated_at: str
    overall_status: str
    summary: str
    next_action: str
    steps: list = field(default_factory=list)
    rollback_status: dict = field(default_factory=dict)
    safety_notes: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class CrossProjectOrchestrationReportBuilder:
    def __init__(self, conn):
        self.conn = conn
        self.runs = runs_mod.CrossProjectOrchestrationRunManager(conn)
        self.rollback = rollback_mod.CrossProjectOrchestrationRollbackCoordinator(conn)

    def build_report(self, run_id):
        run = self.runs.get_run(int(run_id))
        if run is None:
            raise ValueError(f"no cross-project orchestration run {run_id}")
        steps = [step.__dict__ for step in run.steps]
        rb = self.rollback.status(run.id)
        next_action = _next_action(run)
        return CrossProjectOrchestrationReport(
            run_id=run.id, generated_at=_now_iso(), overall_status=run.status,
            summary=run.summary, next_action=next_action, steps=steps,
            rollback_status=rb.__dict__,
            safety_notes=[
                "Stage 11 reports are metadata-only.",
                "Rollback restore remains a Stage 10 explicit-confirm operation.",
            ])

    def save_report(self, report):
        return database.save_cross_project_orchestration_report(
            self.conn, report.run_id, report.generated_at, report.overall_status,
            report.summary, report.next_action,
            json.dumps(report.steps, sort_keys=True),
            json.dumps(report.rollback_status, sort_keys=True),
            json.dumps(report.safety_notes, sort_keys=True))

    def save_markdown_report(self, report_id, report):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            REPORTS_DIR,
            f"cross_project_orchestration_report_{int(report_id)}_{_now_stamp()}.md"))
        base = os.path.realpath(REPORTS_DIR)
        if not path.startswith(base + os.sep):
            raise ValueError("orchestration report path escaped directory")
        content = self.render_markdown(report, report_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_cross_project_orchestration_markdown_report(
            self.conn, report_id, path, "markdown",
            hashlib.sha256(encoded).hexdigest(), len(encoded))
        return path

    def render_markdown(self, report, report_id=None):
        lines = ["# Cross-Project Orchestration Report", ""]
        if report_id is not None:
            lines.append(f"- Report ID: {report_id}")
        lines.extend([
            f"- Run ID: {report.run_id}",
            f"- Status: {report.overall_status}",
            f"- Next action: {report.next_action}",
            "",
            "## Steps",
        ])
        for step in report.steps:
            lines.append(
                f"- Step {step['id']}: {step['status']} project={step['project_key']}")
        return "\n".join(lines)


def _next_action(run):
    for step in run.steps:
        if step.status == "pending":
            return f"prepare Stage 10 controls for run step {step.id}"
        if step.status == "executed":
            return f"verify run step {step.id}"
    return "review orchestration audit"
