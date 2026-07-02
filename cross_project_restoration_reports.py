"""Stage 13.6 — Restoration Reports."""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field

import database
import cross_project_orchestration_runs as runs_mod


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "cross_project_restoration_reports")


@dataclass
class CrossProjectRestorationReport:
    run_id: int
    generated_at: str
    overall_status: str
    summary: str
    next_action: str
    targets: list = field(default_factory=list)
    rollbacks: list = field(default_factory=list)
    integrity: list = field(default_factory=list)
    safety_notes: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class CrossProjectRestorationReportBuilder:
    def __init__(self, conn):
        self.conn = conn
        self.runs = runs_mod.CrossProjectOrchestrationRunManager(conn)

    def build_report(self, run_id):
        run = self.runs.get_run(int(run_id))
        if run is None:
            raise ValueError(f"no cross-project orchestration run {run_id}")
        targets = [dict(row) for row in
                   database.list_cross_project_restoration_targets(
                       self.conn, run_id=run.id)]
        rollbacks = [dict(row) for row in
                     database.list_cross_project_orchestration_step_rollbacks(
                         self.conn, run_id=run.id)]
        integrity = [dict(row) for row in
                     database.list_cross_project_restoration_integrity_checks(
                         self.conn, run_id=run.id)]
        restored = sum(1 for r in rollbacks if r["status"] == "restored")
        previewed = sum(1 for r in rollbacks if r["status"] == "previewed")
        summary = (
            f"Run {run.id}: {len(targets)} target resolution(s), "
            f"{previewed} preview(s), {restored} restoration(s), "
            f"{len(integrity)} integrity check(s).")
        next_action = _next_action(run, rollbacks, integrity)
        return CrossProjectRestorationReport(
            run_id=run.id, generated_at=_now_iso(), overall_status=run.status,
            summary=summary, next_action=next_action, targets=targets,
            rollbacks=rollbacks, integrity=integrity,
            safety_notes=[
                "Restoration reports are metadata-only.",
                "File writes happen only via the Stage 10 restore engine "
                "under --confirm-restore.",
                "Restored steps re-open only via a Stage 12 retry "
                "authorization.",
            ])

    def save_report(self, report):
        return database.save_cross_project_restoration_report(
            self.conn, report.run_id, report.generated_at,
            report.overall_status, report.summary, report.next_action,
            json.dumps(report.targets, sort_keys=True),
            json.dumps(report.rollbacks, sort_keys=True),
            json.dumps(report.integrity, sort_keys=True),
            json.dumps(report.safety_notes, sort_keys=True))

    def save_markdown_report(self, report_id, report):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            REPORTS_DIR,
            f"cross_project_restoration_report_{int(report_id)}_{_now_stamp()}.md"))
        base = os.path.realpath(REPORTS_DIR)
        if not path.startswith(base + os.sep):
            raise ValueError("restoration report path escaped directory")
        content = self.render_markdown(report, report_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_cross_project_restoration_markdown_report(
            self.conn, report_id, path, "markdown",
            hashlib.sha256(encoded).hexdigest(), len(encoded))
        return path

    def render_markdown(self, report, report_id=None):
        lines = ["# Cross-Project Restoration Report", ""]
        if report_id is not None:
            lines.append(f"- Report ID: {report_id}")
        lines.extend([
            f"- Run ID: {report.run_id}",
            f"- Status: {report.overall_status}",
            f"- Next action: {report.next_action}",
            f"- Summary: {report.summary}",
            "",
            "## Rollback Records",
        ])
        if not report.rollbacks:
            lines.append("- (none)")
        for row in report.rollbacks:
            lines.append(
                f"- Rollback {row['id']}: {row['status']} "
                f"step={row['run_step_id']} snapshot={row['snapshot_id']} "
                f"restore={row['restore_id']}")
        lines.extend(["", "## Integrity Checks"])
        if not report.integrity:
            lines.append("- (none)")
        for row in report.integrity:
            lines.append(
                f"- Check {row['id']}: {row['status']} "
                f"matched={row['matched_files']} "
                f"mismatched={row['mismatched_files']} "
                f"missing={row['missing_files']}")
        return "\n".join(lines)


def _next_action(run, rollbacks, integrity):
    blocked = [s for s in run.steps if s.status == "blocked"]
    if not blocked:
        return "no blocked steps; review the restoration audit"
    restored_steps = {r["run_step_id"] for r in rollbacks
                      if r["status"] == "restored"}
    if any(s.id not in restored_steps for s in blocked):
        return "inspect restoration status for blocked steps (--restoration-status)"
    if any(row["status"] == "mismatch" for row in integrity):
        return "resolve integrity mismatches before retrying"
    return "request an authorized retry (--request-orchestration-retry)"
