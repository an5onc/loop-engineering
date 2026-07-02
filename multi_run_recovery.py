"""Stage 14.6 — Session Recovery Guidance (advisory, Stage 13 integration)."""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field

import database
import cross_project_orchestration_runs as runs_mod
import cross_project_restoration_integrity as integrity_mod
import cross_project_restoration_targets as targets_mod
import multi_run_sessions as sessions_mod


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "multi_run_recovery_reports")


@dataclass
class MultiRunRecoveryStatus:
    id: int
    session_id: int
    generated_at: str
    overall_status: str
    summary: str
    next_action: str
    entries: list = field(default_factory=list)
    safety_notes: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def build_entries(conn, session_id):
    """Pure computation of per-blocked-step recovery state. No writes."""
    sessions = sessions_mod.MultiRunSessionManager(conn)
    runs = runs_mod.CrossProjectOrchestrationRunManager(conn)
    resolver = targets_mod.CrossProjectRestorationTargetResolver(conn)
    entries = []
    for member in sessions.active_members(session_id):
        run = runs.get_run(member.run_id)
        if run is None:
            continue
        for step in run.steps:
            if step.status != "blocked":
                continue
            assessment = resolver.assess(run.id, step.step_id)
            rollbacks = [
                row for row in
                database.list_cross_project_orchestration_step_rollbacks(
                    conn, run_id=run.id)
                if row["run_step_id"] == step.id
            ]
            previewed = any(r["status"] == "previewed" for r in rollbacks)
            restored = any(r["status"] == "restored" for r in rollbacks)
            integrity_rows = database.list_cross_project_restoration_integrity_checks(
                conn, run_step_id=step.id, limit=1)
            integrity_status = integrity_rows[0]["status"] if integrity_rows else ""
            outcome_recorded = any(
                row["run_step_id"] == step.id
                for row in database.list_cross_project_restoration_outcomes(
                    conn, run_id=run.id))
            policy = database.get_cross_project_orchestration_retry_policy_for_run(
                conn, run.id)
            attempts = [
                row for row in
                database.list_cross_project_orchestration_step_advancements(
                    conn, run_id=run.id, limit=500)
                if row["run_step_id"] == step.id
            ]
            retries_used = max(0, len(attempts) - 1)
            entries.append({
                "run_id": run.id, "run_step_id": step.id,
                "step_id": step.step_id,
                "eligible": assessment["eligible"],
                "reason": assessment["reason"],
                "previewed": previewed, "restored": restored,
                "integrity_status": integrity_status,
                "outcome_recorded": outcome_recorded,
                "retry_policy_id": policy["id"] if policy else None,
                "retries_allowed": policy["max_retries"] if policy else 0,
                "retries_used": retries_used,
                "next_command": _next_command(
                    run, step, assessment, previewed, restored,
                    integrity_status, outcome_recorded, policy, retries_used),
            })
    return entries


def _next_command(run, step, assessment, previewed, restored,
                  integrity_status, outcome_recorded, policy, retries_used):
    if not assessment["eligible"] and not restored:
        return (f"python3 main.py --restoration-status {run.id} "
                f"--step {step.step_id}")
    if not previewed:
        return (f"python3 main.py --preview-orchestration-restoration "
                f"{run.id} --step {step.step_id}")
    if not restored:
        return (f"python3 main.py --restore-orchestration-step {run.id} "
                f"--step {step.step_id} --confirm-restore")
    if not integrity_status:
        return (f"python3 main.py --check-restoration-integrity {run.id} "
                f"--step {step.step_id}")
    if integrity_status == "mismatch":
        return (f"python3 main.py --preview-orchestration-restoration "
                f"{run.id} --step {step.step_id}")
    if not outcome_recorded:
        return (f"python3 main.py --record-restoration-outcome {run.id} "
                f"--step {step.step_id}")
    if policy is None:
        return (f"python3 main.py --set-orchestration-retry-policy {run.id} "
                "--max-retries N")
    if retries_used < (policy["max_retries"] or 0):
        return (f"python3 main.py --request-orchestration-retry {run.id} "
                f"--step {step.step_id}")
    return "retry budget exhausted — review the restoration report"


class MultiRunRecoveryEngine:
    def __init__(self, conn):
        self.conn = conn
        self.sessions = sessions_mod.MultiRunSessionManager(conn)

    def status(self, session_id):
        session = self.sessions.get_session(int(session_id))
        if session is None:
            raise ValueError(f"no multi-run session {session_id}")
        entries = build_entries(self.conn, session.id)
        if not entries:
            overall = "no_blocked_steps"
            next_action = "no recovery needed"
        elif all("exhausted" in e["next_command"] for e in entries):
            overall = "blocked"
            next_action = entries[0]["next_command"]
        else:
            overall = "recovery_available"
            next_action = entries[0]["next_command"]
        summary = (f"Session {session.id}: {len(entries)} blocked step(s) "
                   "with recovery guidance.")
        status_id = database.save_multi_run_recovery_report(
            self.conn, session.id, _now_iso(), overall, summary, next_action,
            json.dumps(entries, sort_keys=True),
            json.dumps(_safety_notes(), sort_keys=True))
        return MultiRunRecoveryStatus(
            id=status_id, session_id=session.id, generated_at=_now_iso(),
            overall_status=overall, summary=summary, next_action=next_action,
            entries=entries, safety_notes=_safety_notes())

    def save_markdown_report(self, status):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            REPORTS_DIR, f"multi_run_recovery_{int(status.id)}_{_now_stamp()}.md"))
        base = os.path.realpath(REPORTS_DIR)
        if not path.startswith(base + os.sep):
            raise ValueError("recovery report path escaped directory")
        content = self.render_markdown(status)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_multi_run_recovery_markdown_report(
            self.conn, status.id, path, "markdown",
            hashlib.sha256(encoded).hexdigest(), len(encoded))
        return path

    def render_markdown(self, status):
        lines = [
            "# Multi-Run Session Recovery", "",
            f"- Report ID: {status.id}",
            f"- Session ID: {status.session_id}",
            f"- Overall: {status.overall_status}",
            f"- Next action: {status.next_action}",
            "",
            "## Blocked Steps",
        ]
        if not status.entries:
            lines.append("- (none)")
        for entry in status.entries:
            lines.append(
                f"- Run {entry['run_id']} step {entry['step_id']}: "
                f"restored={entry['restored']} "
                f"integrity={entry['integrity_status'] or '-'} — "
                f"{entry['next_command']}")
        return "\n".join(lines)


def _safety_notes():
    return [
        "Recovery guidance is advisory: nothing was previewed, restored, "
        "verified, recorded, retried, or re-opened.",
        "Restoration still requires preview-first plus --confirm-restore; "
        "retries still require Stage 12 authorization and fresh "
        "confirmation.",
    ]
