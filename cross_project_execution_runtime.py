"""Stage 10.4 — Single-Step Cross-Project Command Executor."""

import json
from dataclasses import dataclass

import database
import cross_project_execution_commands as commands_mod
import cross_project_execution_confirmations as confirmations_mod
import cross_project_execution_sessions as sessions_mod
import cross_project_execution_snapshots as snapshots_mod
import multi_project_registry
import project_workspace
import terminal


OUTPUT_LIMIT = 4000


@dataclass
class CrossProjectExecutionAttempt:
    id: int
    session_id: int
    confirmation_id: int
    snapshot_id: int
    plan_id: int
    step_id: int
    command_proposal_id: int
    project_key: str
    command_text: str
    command_cwd: str
    status: str
    allowed: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool
    reason_if_blocked: str


def attempt_from_row(row):
    return CrossProjectExecutionAttempt(
        id=row["id"], session_id=row["session_id"],
        confirmation_id=row["confirmation_id"], snapshot_id=row["snapshot_id"],
        plan_id=row["plan_id"], step_id=row["step_id"],
        command_proposal_id=row["command_proposal_id"],
        project_key=row["project_key"] or "", command_text=row["command_text"] or "",
        command_cwd=row["command_cwd"] or "", status=row["status"] or "",
        allowed=bool(row["allowed"]), exit_code=row["exit_code"],
        stdout=row["stdout"] or "", stderr=row["stderr"] or "",
        duration_seconds=row["duration_seconds"] or 0.0,
        timed_out=bool(row["timed_out"]),
        reason_if_blocked=row["reason_if_blocked"] or "")


class CrossProjectExecutionRuntime:
    def __init__(self, conn):
        self.conn = conn
        self.sessions = sessions_mod.CrossProjectExecutionSessionManager(conn)
        self.confirmations = confirmations_mod.CrossProjectExecutionConfirmationGate(conn)
        self.registry = multi_project_registry.ProjectRegistry(conn)

    def execute(self, session_id, confirmation_id, snapshot_id, confirm_execution=False):
        if not confirm_execution:
            raise ValueError("execution requires explicit --confirm-execution")
        session = self.sessions.get_session(int(session_id))
        if session is None:
            raise ValueError(f"no cross-project execution session {session_id}")
        confirmation = self.confirmations.get_confirmation(int(confirmation_id))
        if confirmation is None:
            raise ValueError(f"no cross-project execution confirmation {confirmation_id}")
        if confirmation.session_id != session.id:
            raise ValueError("confirmation does not match session")
        if not confirmations_mod.is_usable(confirmation):
            raise ValueError("execution confirmation is not approved")
        snapshot = snapshots_mod.CrossProjectExecutionSnapshotBuilder(
            self.conn).get_snapshot(int(snapshot_id))
        if snapshot is None:
            raise ValueError(f"no cross-project execution snapshot {snapshot_id}")
        if snapshot.session_id != session.id or snapshot.confirmation_id != confirmation.id:
            raise ValueError("snapshot does not match session and confirmation")
        proposal_row = database.get_cross_project_execution_command_proposal(
            self.conn, confirmation.command_proposal_id)
        if proposal_row is None:
            raise ValueError("confirmation references missing command proposal")
        proposal = commands_mod.proposal_from_row(proposal_row)
        if proposal.status != "proposed":
            raise ValueError(f"command proposal status is {proposal.status}")
        project = self.registry.get_project(confirmation.project_key)
        if project is None:
            raise ValueError(f"no registered project {confirmation.project_key}")
        if not terminal.is_safe_command(proposal.command_text):
            result = terminal.CommandResult(
                proposal.command_text, False, reason_if_blocked="command is not allowlisted")
        else:
            ws = _workspace_for_project(project)
            result = terminal.run_command(proposal.command_text, project.root_path,
                                          workspace=ws)
        status = _attempt_status(result)
        aid = database.save_cross_project_execution_attempt(
            self.conn, session.id, confirmation.id, snapshot.id, session.plan_id,
            confirmation.step_id, confirmation.command_proposal_id,
            confirmation.project_key, proposal.command_text,
            project.root_path,
            status, result.allowed, result.exit_code,
            _redact(result.stdout), _redact(result.stderr),
            result.duration_seconds, result.timed_out, result.reason_if_blocked)
        database.save_cross_project_execution_attempt_event(
            self.conn, aid, "executed",
            json.dumps({"status": status, "allowed": result.allowed,
                        "exit_code": result.exit_code}, sort_keys=True))
        return self.get_attempt(aid)

    def get_attempt(self, attempt_id):
        row = database.get_cross_project_execution_attempt(self.conn, int(attempt_id))
        return attempt_from_row(row) if row else None


def _workspace_for_project(project):
    return project_workspace.ProjectWorkspace(
        name=project.project_key, root_path=project.root_path,
        allowed_read_paths=["."], allowed_write_paths=list(project.allowed_write_paths or ["."]),
        allowed_command_paths=["."], allow_git=False,
        profile_name=project.safety_profile_name or "cross_project_runtime",
        profile_version="1.0")


def _attempt_status(result):
    if not result.allowed:
        return "blocked"
    if result.timed_out:
        return "failed"
    return "succeeded" if result.exit_code == 0 else "failed"


def _redact(text):
    value = (text or "")[:OUTPUT_LIMIT]
    for marker in ("SECRET", "TOKEN", "PRIVATE_KEY"):
        value = value.replace(marker, "[REDACTED]")
    return value
