"""Stage 14.2 — Shared Session Operator Gates (advisory metadata)."""

import json
from dataclasses import dataclass, field

import database
import multi_run_sessions as sessions_mod


GATE_STATUSES = ("defined", "approved", "revoked", "expired")


@dataclass
class MultiRunSessionGate:
    id: int
    session_id: int
    label: str
    status: str
    window_ids: list = field(default_factory=list)
    retry_policy_ids: list = field(default_factory=list)
    notes: str = ""


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def gate_from_row(row):
    return MultiRunSessionGate(
        id=row["id"], session_id=row["session_id"], label=row["label"] or "",
        status=row["status"] or "",
        window_ids=_safe_json_loads(row["window_ids_json"], []),
        retry_policy_ids=_safe_json_loads(row["retry_policy_ids_json"], []),
        notes=row["notes"] or "")


class MultiRunSessionGateManager:
    """Session gates record shared operator intent. They are advisory and
    coordinating only: a gate can never authorize execution, retry, or
    restoration by itself. Stage 10/12/13 per-step gates stay authoritative.
    """

    def __init__(self, conn):
        self.conn = conn
        self.sessions = sessions_mod.MultiRunSessionManager(conn)

    def define_gate(self, session_id, label, window_ids=None,
                    retry_policy_ids=None, notes=None):
        session = self.sessions.get_session(int(session_id))
        if session is None:
            raise ValueError(f"no multi-run session {session_id}")
        if session.status == "closed":
            raise ValueError(
                f"multi-run session {session.id} is closed and immutable")
        if not label or not str(label).strip():
            raise ValueError("session gate requires a non-empty --label")
        windows = [int(w) for w in (window_ids or [])]
        for window_id in windows:
            if database.get_cross_project_execution_window(
                    self.conn, window_id) is None:
                raise ValueError(f"no execution window {window_id}")
        policies = [int(p) for p in (retry_policy_ids or [])]
        for policy_id in policies:
            if database.get_cross_project_orchestration_retry_policy(
                    self.conn, policy_id) is None:
                raise ValueError(f"no retry policy {policy_id}")
        gate_id = database.save_multi_run_session_gate(
            self.conn, session.id, str(label).strip(), "defined",
            json.dumps(windows, sort_keys=True),
            json.dumps(policies, sort_keys=True), notes)
        database.save_multi_run_session_event(
            self.conn, session.id, "gate_defined",
            f"gate={gate_id} label={str(label).strip()}")
        return self.get_gate(gate_id)

    def approve_gate(self, gate_id):
        gate = self._require_gate(gate_id)
        if gate.status != "defined":
            raise ValueError(
                f"session gate {gate.id} is '{gate.status}'; only a defined "
                "gate can be approved")
        database.update_multi_run_session_gate_status(
            self.conn, gate.id, "approved")
        database.save_multi_run_session_event(
            self.conn, gate.session_id, "gate_approved", f"gate={gate.id}")
        return self.get_gate(gate.id)

    def revoke_gate(self, gate_id):
        gate = self._require_gate(gate_id)
        if gate.status not in ("defined", "approved"):
            raise ValueError(
                f"session gate {gate.id} is '{gate.status}'; only a defined "
                "or approved gate can be revoked")
        database.update_multi_run_session_gate_status(
            self.conn, gate.id, "revoked")
        database.save_multi_run_session_event(
            self.conn, gate.session_id, "gate_revoked", f"gate={gate.id}")
        return self.get_gate(gate.id)

    def get_gate(self, gate_id):
        row = database.get_multi_run_session_gate(self.conn, int(gate_id))
        return gate_from_row(row) if row else None

    def list_gates(self, session_id=None, limit=100):
        return [gate_from_row(row) for row in
                database.list_multi_run_session_gates(
                    self.conn, session_id=session_id, limit=limit)]

    def approved_gate_for_session(self, session_id):
        for gate in self.list_gates(session_id=int(session_id)):
            if gate.status == "approved":
                return gate
        return None

    def _require_gate(self, gate_id):
        gate = self.get_gate(gate_id)
        if gate is None:
            raise ValueError(f"no multi-run session gate {gate_id}")
        return gate
