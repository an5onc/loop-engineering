"""Stage 10.1 — Cross-Project Execution Scope Resolver."""

import json
import os
from dataclasses import dataclass, field

import database
import cross_project_execution_commands as commands_mod
import cross_project_execution_sessions as sessions_mod
import multi_project_registry
import terminal


@dataclass
class CrossProjectExecutionScopeCheck:
    id: int
    session_id: int
    plan_id: int
    step_id: int
    command_proposal_id: int
    project_key: str
    status: str
    command_text: str
    command_cwd: str
    command_allowed: bool
    blocked_reasons: list = field(default_factory=list)
    safety_notes: list = field(default_factory=list)


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def scope_check_from_row(row):
    return CrossProjectExecutionScopeCheck(
        id=row["id"], session_id=row["session_id"], plan_id=row["plan_id"],
        step_id=row["step_id"], command_proposal_id=row["command_proposal_id"],
        project_key=row["project_key"] or "", status=row["status"] or "",
        command_text=row["command_text"] or "", command_cwd=row["command_cwd"] or "",
        command_allowed=bool(row["command_allowed"]),
        blocked_reasons=_safe_json_loads(row["blocked_reasons_json"], []),
        safety_notes=_safe_json_loads(row["safety_notes_json"], []))


class CrossProjectExecutionScopeResolver:
    def __init__(self, conn):
        self.conn = conn
        self.sessions = sessions_mod.CrossProjectExecutionSessionManager(conn)
        self.commands = commands_mod.CrossProjectExecutionCommandProposer(conn)
        self.registry = multi_project_registry.ProjectRegistry(conn)

    def resolve(self, session_id):
        session = self.sessions.get_session(int(session_id))
        if session is None:
            raise ValueError(f"no cross-project execution session {session_id}")
        if session.status != "prepared":
            raise ValueError(f"session {session.id} is not prepared")
        existing = database.list_cross_project_execution_scope_checks(
            self.conn, session_id=session.id)
        if existing:
            return [scope_check_from_row(r) for r in existing]
        checks = []
        for step in session.eligible_steps:
            step_id = int(step["step_id"])
            project_key = step["project_key"]
            proposal = self._proposal_for_step(session.plan_id, step_id, project_key)
            command_text = proposal.command_text if proposal else ""
            blocked = []
            project = self.registry.get_project(project_key)
            cwd = ""
            if project is None:
                blocked.append("missing registered project")
            else:
                cwd = os.path.realpath(project.root_path)
                if project.status != "active":
                    blocked.append(f"project status is {project.status}")
                if not os.path.isdir(cwd):
                    blocked.append("missing project root")
            if proposal is None:
                blocked.append("missing command proposal")
            elif proposal.status != "proposed":
                blocked.append(f"command proposal status is {proposal.status}")
            command_allowed = terminal.is_safe_command(command_text)
            if command_text and not command_allowed:
                blocked.append("command is not allowlisted")
            status = "blocked" if blocked else "ready"
            cid = database.save_cross_project_execution_scope_check(
                self.conn, session.id, session.plan_id, step_id,
                proposal.id if proposal else None, project_key, status,
                command_text, cwd, command_allowed,
                json.dumps(blocked, sort_keys=True),
                json.dumps(_safety_notes(), sort_keys=True))
            checks.append(scope_check_from_row(
                database.get_cross_project_execution_scope_check(self.conn, cid)))
        return checks

    def get_scope_check(self, scope_check_id):
        row = database.get_cross_project_execution_scope_check(
            self.conn, int(scope_check_id))
        return scope_check_from_row(row) if row else None

    def _proposal_for_step(self, plan_id, step_id, project_key):
        for row in database.list_cross_project_execution_command_proposals(
                self.conn, plan_id=plan_id):
            proposal = commands_mod.proposal_from_row(row)
            if proposal.step_id == step_id and proposal.project_key == project_key:
                return proposal
        return None


def _safety_notes():
    return [
        "scope resolution does not execute commands",
        "actual execution must use terminal.run_command",
        "project cwd must stay inside registered project root",
    ]
