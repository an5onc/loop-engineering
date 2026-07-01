"""Stage 10.2 — Human Confirmation Gate for Cross-Project Execution."""

import datetime
import json
from dataclasses import dataclass
from typing import Optional

import database
import cross_project_execution_scope as scope_mod
import cross_project_execution_sessions as sessions_mod


VALID_STATUSES = ("requested", "approved", "rejected", "expired")


@dataclass
class CrossProjectExecutionConfirmation:
    id: int
    session_id: int
    plan_id: int
    step_id: int
    command_proposal_id: int
    project_key: str
    status: str
    requested_at: str
    decided_at: str = ""
    decided_by: str = ""
    notes: str = ""


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def confirmation_from_row(row):
    return CrossProjectExecutionConfirmation(
        id=row["id"], session_id=row["session_id"], plan_id=row["plan_id"],
        step_id=row["step_id"], command_proposal_id=row["command_proposal_id"],
        project_key=row["project_key"] or "", status=row["status"] or "",
        requested_at=row["requested_at"] or "", decided_at=row["decided_at"] or "",
        decided_by=row["decided_by"] or "", notes=row["notes"] or "")


def is_usable(confirmation) -> bool:
    return getattr(confirmation, "status", None) == "approved"


class CrossProjectExecutionConfirmationGate:
    def __init__(self, conn):
        self.conn = conn
        self.sessions = sessions_mod.CrossProjectExecutionSessionManager(conn)
        self.scope = scope_mod.CrossProjectExecutionScopeResolver(conn)

    def request(self, session_id, step_id, command_proposal_id):
        session = self.sessions.get_session(int(session_id))
        if session is None:
            raise ValueError(f"no cross-project execution session {session_id}")
        if session.status != "prepared":
            raise ValueError(f"session {session.id} is not prepared")
        checks = self.scope.resolve(session.id)
        match = None
        for check in checks:
            if (check.step_id == int(step_id)
                    and check.command_proposal_id == int(command_proposal_id)):
                match = check
                break
        if match is None:
            raise ValueError("confirmation must reference a scoped step and command")
        if match.status != "ready":
            raise ValueError(
                f"scope check for step {step_id} is not ready: {match.blocked_reasons}")
        cid = database.save_cross_project_execution_confirmation(
            self.conn, session.id, session.plan_id, int(step_id),
            int(command_proposal_id), match.project_key, "requested", _now_iso())
        database.save_cross_project_execution_confirmation_event(
            self.conn, cid, "requested",
            json.dumps({"session_id": session.id, "step_id": int(step_id),
                        "command_proposal_id": int(command_proposal_id)},
                       sort_keys=True))
        return self.get_confirmation(cid)

    def set_status(self, confirmation_id, status, decided_by=None, notes=None):
        if status not in ("approved", "rejected", "expired"):
            raise ValueError(f"invalid execution confirmation status {status!r}")
        confirmation = self.get_confirmation(int(confirmation_id))
        if confirmation is None:
            raise ValueError(f"no cross-project execution confirmation {confirmation_id}")
        database.update_cross_project_execution_confirmation(
            self.conn, confirmation.id, status, decided_at=_now_iso(),
            decided_by=decided_by, notes=notes)
        database.save_cross_project_execution_confirmation_event(
            self.conn, confirmation.id, "status_changed",
            f"{confirmation.status}->{status}")
        return self.get_confirmation(confirmation.id)

    def get_confirmation(self, confirmation_id) -> Optional[CrossProjectExecutionConfirmation]:
        row = database.get_cross_project_execution_confirmation(
            self.conn, int(confirmation_id))
        return confirmation_from_row(row) if row else None

    def list_confirmations(self, limit=50):
        return database.list_cross_project_execution_confirmations(
            self.conn, limit=limit)
