"""Stage 14.5 — Single-Step Session Advancement (delegates to Stage 12).

Stage 14 has no executor: this wrapper's only execution route is the Stage 12
gated advancement engine, which delegates to Stage 11 and then Stage 10. It
has no subprocess import and no direct terminal-runner or model-client call;
the Stage 14 runtime audit verifies this against module source.
"""

import json
from dataclasses import dataclass, field

import database
import cross_project_gated_advancement as gated_mod
import cross_project_orchestration_runs as runs_mod
import multi_run_readiness as readiness_mod
import multi_run_session_gates as gates_mod
import multi_run_sessions as sessions_mod


@dataclass
class MultiRunSessionAdvancement:
    id: int
    session_id: int
    run_id: int
    run_step_id: int
    gate_id: int
    gated_advancement_id: int
    attempt_id: int
    status: str
    detail: str = ""
    safety_notes: list = field(default_factory=list)


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def advancement_from_row(row):
    return MultiRunSessionAdvancement(
        id=row["id"], session_id=row["session_id"], run_id=row["run_id"],
        run_step_id=row["run_step_id"], gate_id=row["gate_id"],
        gated_advancement_id=row["gated_advancement_id"],
        attempt_id=row["attempt_id"], status=row["status"] or "",
        detail=row["detail"] or "",
        safety_notes=_safe_json_loads(row["safety_notes_json"], []))


class MultiRunSessionAdvancementEngine:
    def __init__(self, conn):
        self.conn = conn
        self.sessions = sessions_mod.MultiRunSessionManager(conn)
        self.gates = gates_mod.MultiRunSessionGateManager(conn)
        self.engine = gated_mod.CrossProjectGatedAdvancementEngine(conn)

    def advance(self, session_id, run_id, step_id, confirmation_id,
                snapshot_id, confirm_execution=False):
        if not confirm_execution:
            raise ValueError(
                "session advancement requires explicit --confirm-execution")
        session = self.sessions.get_session(int(session_id))
        if session is None:
            raise ValueError(f"no multi-run session {session_id}")
        if session.status == "closed":
            raise ValueError(
                f"multi-run session {session.id} is closed and immutable")
        if session.status == "defined":
            raise ValueError(
                f"multi-run session {session.id} has no member runs yet")
        members = {m.run_id for m in self.sessions.active_members(session.id)}
        if int(run_id) not in members:
            raise ValueError(
                f"run {run_id} is not an active member of session {session.id}")
        gate = self.gates.approved_gate_for_session(session.id)
        if gate is None:
            raise ValueError(
                f"session {session.id} advancement requires an approved "
                "session gate (--approve-multi-run-gate)")
        readiness = self._readiness_guard(session, int(run_id))
        try:
            gated = self.engine.advance(
                int(run_id), int(step_id), confirmation_id, snapshot_id,
                confirm_execution=True)
        except ValueError as exc:
            record_id = database.save_multi_run_session_advancement(
                self.conn, session.id, int(run_id), None, gate.id, None, None,
                "refused", str(exc),
                json.dumps(_safety_notes(readiness), sort_keys=True))
            database.save_multi_run_session_event(
                self.conn, session.id, "advancement_refused",
                f"run={run_id} step={step_id} record={record_id}")
            raise
        record_id = database.save_multi_run_session_advancement(
            self.conn, session.id, gated.run_id, gated.run_step_id, gate.id,
            gated.id, gated.attempt_id, gated.status,
            f"attempt_number={gated.attempt_number}",
            json.dumps(_safety_notes(readiness), sort_keys=True))
        database.save_multi_run_session_event(
            self.conn, session.id, "advanced",
            f"run={gated.run_id} step={gated.run_step_id} "
            f"gated={gated.id} status={gated.status}")
        self.sessions.refresh_status(session.id)
        return advancement_from_row(database.get_multi_run_session_advancement(
            self.conn, record_id))

    def _readiness_guard(self, session, run_id):
        """Refuse execution while the run still needs recovery; the exact
        Stage 12/13 gates remain authoritative for everything else."""
        run = runs_mod.CrossProjectOrchestrationRunManager(self.conn).get_run(
            run_id)
        if run is None:
            raise ValueError(f"no cross-project orchestration run {run_id}")
        entry = readiness_mod.assess_run(self.conn, run)
        if entry["status"] in ("needs_restoration",
                               "needs_retry_authorization"):
            raise ValueError(
                f"run {run_id} needs recovery before execution "
                f"({entry['status']}): {entry['next_action']}")
        return entry["status"]

    def list_advancements(self, session_id=None, limit=100):
        return [advancement_from_row(row) for row in
                database.list_multi_run_session_advancements(
                    self.conn, session_id=session_id, limit=limit)]


def _safety_notes(readiness_status):
    return [
        "Stage 14 executed at most one step and delegated to the Stage 12 "
        "gated advancement engine (Stage 12 -> Stage 11 -> Stage 10).",
        "The approved session gate is advisory; Stage 10 confirmation, "
        "snapshot, allowlist, cwd, execution window, and --confirm-execution "
        "were all still required.",
        f"Run readiness at advancement time: {readiness_status}.",
    ]
