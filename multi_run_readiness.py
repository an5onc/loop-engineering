"""Stage 14.3 — Multi-Run Session Readiness (read-only)."""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field

import database
import cross_project_execution_window_checks as checks_mod
import cross_project_execution_windows as windows_mod
import cross_project_orchestration_controls as controls_mod
import cross_project_orchestration_runs as runs_mod
import cross_project_restoration_integrity as integrity_mod
import cross_project_restoration_targets as targets_mod
import multi_run_sessions as sessions_mod


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "multi_run_readiness_reports")
STATUS_PRIORITY = (
    "needs_restoration", "needs_retry_authorization", "blocked",
    "needs_open_window", "needs_confirmation", "needs_snapshot", "ready",
    "completed",
)


@dataclass
class MultiRunReadinessReport:
    id: int
    session_id: int
    generated_at: str
    overall_status: str
    summary: str
    next_action: str
    runs: list = field(default_factory=list)
    safety_notes: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def assess_run(conn, run, now=None):
    """Non-persisting readiness assessment of one orchestration run.

    Metadata-only: reads SQLite rows, never project files, never executes.
    """
    moment = now or datetime.datetime.now()
    steps = run.steps
    pending = [s for s in steps if s.status == "pending"]
    executed = [s for s in steps if s.status in ("executed", "succeeded")]
    blocked = [s for s in steps if s.status == "blocked"]
    entry = {
        "run_id": run.id, "run_status": run.status,
        "total_steps": len(steps), "pending_steps": len(pending),
        "executed_steps": len(executed), "blocked_steps": len(blocked),
        "window_status": "", "retry_policy_id": None, "retries_allowed": 0,
        "retries_used": 0, "restoration": {}, "status": "", "next_action": "",
    }
    windows = windows_mod.CrossProjectExecutionWindowManager(conn).list_windows(
        run_id=run.id, limit=200)
    _, window_status, _ = checks_mod.select_window(windows, moment)
    entry["window_status"] = window_status
    policy = database.get_cross_project_orchestration_retry_policy_for_run(
        conn, run.id)
    entry["retry_policy_id"] = policy["id"] if policy else None
    entry["retries_allowed"] = policy["max_retries"] if policy else 0
    if run.status == "succeeded":
        entry["status"] = "completed"
        entry["next_action"] = "run complete; no action needed"
        return entry
    if blocked:
        step = min(blocked, key=lambda s: (s.sequence_number, s.id))
        return _assess_blocked_step(conn, run, step, policy, entry)
    if pending:
        step = min(pending, key=lambda s: (s.sequence_number, s.id))
        return _assess_pending_step(conn, run, step, window_status, entry)
    entry["status"] = "ready"
    entry["next_action"] = (
        "verify the executed step "
        "(--verify-cross-project-orchestration-step)")
    return entry


def _assess_blocked_step(conn, run, step, policy, entry):
    resolver = targets_mod.CrossProjectRestorationTargetResolver(conn)
    assessment = resolver.assess(run.id, step.step_id)
    restored = integrity_mod.latest_restored_rollback(
        conn, run.id, step.id) is not None
    outcome_recorded = any(
        row["run_step_id"] == step.id
        for row in database.list_cross_project_restoration_outcomes(
            conn, run_id=run.id))
    retries_used = _retries_used(conn, run, step)
    entry["retries_used"] = retries_used
    entry["restoration"] = {
        "eligible": assessment["eligible"], "reason": assessment["reason"],
        "restored": restored, "outcome_recorded": outcome_recorded,
        "run_step_id": step.id, "step_id": step.step_id,
    }
    if restored and not outcome_recorded:
        entry["status"] = "needs_restoration"
        entry["next_action"] = (
            f"python3 main.py --record-restoration-outcome {run.id} "
            f"--step {step.step_id}")
    elif not restored and assessment["eligible"]:
        entry["status"] = "needs_restoration"
        entry["next_action"] = (
            f"python3 main.py --restoration-status {run.id} "
            f"--step {step.step_id}")
    elif policy is None:
        entry["status"] = "needs_retry_authorization"
        entry["next_action"] = (
            f"python3 main.py --set-orchestration-retry-policy {run.id} "
            "--max-retries N")
    elif retries_used < (policy["max_retries"] or 0):
        entry["status"] = "needs_retry_authorization"
        entry["next_action"] = (
            f"python3 main.py --request-orchestration-retry {run.id} "
            f"--step {step.step_id}")
    else:
        entry["status"] = "blocked"
        entry["next_action"] = (
            "retry budget exhausted — review the restoration report" if restored
            else assessment["reason"] or "step blocked; operator review required")
    return entry


def _assess_pending_step(conn, run, step, window_status, entry):
    if window_status != "open":
        entry["status"] = "needs_open_window"
        entry["next_action"] = (
            f"python3 main.py --define-execution-window {run.id} --label LABEL "
            "then --open-execution-window WINDOW_ID"
            if window_status == "missing"
            else "python3 main.py --open-execution-window WINDOW_ID")
        return entry
    orchestration_step = database.get_cross_project_orchestration_step(
        conn, step.orchestration_step_id)
    confirmation = controls_mod._latest_matching_confirmation(
        conn, step, orchestration_step["session_id"])
    if confirmation is None or confirmation["status"] != "approved":
        entry["status"] = "needs_confirmation"
        entry["next_action"] = (
            "python3 main.py --request-cross-project-execution-confirmation "
            f"{orchestration_step['session_id']} --step {step.stage10_step_id} "
            f"--command {step.command_proposal_id}")
        return entry
    snapshot = controls_mod._latest_matching_snapshot(conn, run, confirmation)
    if snapshot is None:
        entry["status"] = "needs_snapshot"
        entry["next_action"] = (
            "python3 main.py --snapshot-cross-project-execution "
            f"{orchestration_step['session_id']} --confirmation "
            f"{confirmation['id']}")
        return entry
    entry["status"] = "ready"
    entry["next_action"] = (
        f"python3 main.py --advance-multi-run-session SESSION_ID --run {run.id} "
        f"--step {step.step_id} --confirmation {confirmation['id']} "
        f"--snapshot {snapshot['id']} --confirm-execution")
    return entry


def _retries_used(conn, run, step):
    rows = database.list_cross_project_orchestration_step_advancements(
        conn, run_id=run.id, limit=500)
    attempts = [row for row in rows if row["run_step_id"] == step.id]
    return max(0, len(attempts) - 1)


class MultiRunReadinessEngine:
    def __init__(self, conn):
        self.conn = conn
        self.sessions = sessions_mod.MultiRunSessionManager(conn)
        self.runs = runs_mod.CrossProjectOrchestrationRunManager(conn)

    def build(self, session_id, now=None):
        session = self.sessions.get_session(int(session_id))
        if session is None:
            raise ValueError(f"no multi-run session {session_id}")
        entries = []
        for member in self.sessions.active_members(session.id):
            run = self.runs.get_run(member.run_id)
            if run is None:
                entries.append({
                    "run_id": member.run_id, "run_status": "missing",
                    "status": "blocked",
                    "next_action": f"run {member.run_id} no longer exists",
                })
                continue
            entries.append(assess_run(self.conn, run, now=now))
        overall, next_action = _overall(entries)
        summary = (
            f"Session {session.id}: {len(entries)} member run(s), "
            f"overall {overall}.")
        report_id = database.save_multi_run_readiness_report(
            self.conn, session.id, _now_iso(), overall, summary, next_action,
            json.dumps(entries, sort_keys=True),
            json.dumps(_safety_notes(), sort_keys=True))
        self.sessions.refresh_status(session.id)
        return MultiRunReadinessReport(
            id=report_id, session_id=session.id, generated_at=_now_iso(),
            overall_status=overall, summary=summary, next_action=next_action,
            runs=entries, safety_notes=_safety_notes())

    def save_markdown_report(self, report):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            REPORTS_DIR,
            f"multi_run_readiness_{int(report.id)}_{_now_stamp()}.md"))
        base = os.path.realpath(REPORTS_DIR)
        if not path.startswith(base + os.sep):
            raise ValueError("readiness report path escaped directory")
        content = self.render_markdown(report)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_multi_run_readiness_markdown_report(
            self.conn, report.id, path, "markdown",
            hashlib.sha256(encoded).hexdigest(), len(encoded))
        return path

    def render_markdown(self, report):
        lines = [
            "# Multi-Run Session Readiness", "",
            f"- Report ID: {report.id}",
            f"- Session ID: {report.session_id}",
            f"- Overall: {report.overall_status}",
            f"- Next action: {report.next_action}",
            "",
            "## Member Runs",
        ]
        if not report.runs:
            lines.append("- (none)")
        for entry in report.runs:
            lines.append(
                f"- Run {entry['run_id']}: {entry.get('status', '')} — "
                f"{entry.get('next_action', '')}")
        return "\n".join(lines)


def _overall(entries):
    if not entries:
        return "empty", "add member runs (--add-run-to-multi-run-session)"
    if all(e.get("status") == "completed" for e in entries):
        return "completed", "session complete; close it or review reports"
    for status in STATUS_PRIORITY:
        for entry in entries:
            if entry.get("status") == status:
                return status, entry.get("next_action", "")
    return "blocked", "operator review required"


def _safety_notes():
    return [
        "Readiness is metadata-only: no commands, no model calls, no project "
        "file reads.",
        "Shared session gates never replace Stage 10/12/13 per-step gates.",
    ]
