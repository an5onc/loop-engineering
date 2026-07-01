"""Stage 11.0 — Cross-Project Orchestration Plan Registry.

Builds metadata-only multi-step orchestration plans from a prepared Stage 10
session and already-resolved Stage 10 scope checks. It does not create
confirmations, snapshots, attempts, jobs, or project-root mutations.
"""

import datetime
import json
from dataclasses import dataclass, field
from typing import Optional

import database
import cross_project_execution_sessions as sessions_mod


@dataclass
class CrossProjectOrchestrationStep:
    id: int
    orchestration_plan_id: int
    session_id: int
    stage10_scope_check_id: int
    stage10_step_id: int
    command_proposal_id: int
    project_key: str
    sequence_number: int
    status: str
    action_summary: str
    blocked_reason: str = ""
    required_controls: list = field(default_factory=list)


@dataclass
class CrossProjectOrchestrationPlan:
    id: int
    session_id: int
    source_execution_plan_id: int
    generated_at: str
    status: str
    summary: str
    total_steps: int
    ready_steps: int
    blocked_steps: int
    safety_notes: list = field(default_factory=list)
    steps: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def step_from_row(row):
    return CrossProjectOrchestrationStep(
        id=row["id"], orchestration_plan_id=row["orchestration_plan_id"],
        session_id=row["session_id"],
        stage10_scope_check_id=row["stage10_scope_check_id"],
        stage10_step_id=row["stage10_step_id"],
        command_proposal_id=row["command_proposal_id"],
        project_key=row["project_key"] or "",
        sequence_number=row["sequence_number"] or 0,
        status=row["status"] or "",
        action_summary=row["action_summary"] or "",
        blocked_reason=row["blocked_reason"] or "",
        required_controls=_safe_json_loads(row["required_controls_json"], []))


def plan_from_row(conn, row):
    steps = [
        step_from_row(r)
        for r in database.list_cross_project_orchestration_steps(conn, row["id"])
    ]
    return CrossProjectOrchestrationPlan(
        id=row["id"], session_id=row["session_id"],
        source_execution_plan_id=row["source_execution_plan_id"],
        generated_at=row["generated_at"] or "", status=row["status"] or "",
        summary=row["summary"] or "", total_steps=row["total_steps"] or 0,
        ready_steps=row["ready_steps"] or 0, blocked_steps=row["blocked_steps"] or 0,
        safety_notes=_safe_json_loads(row["safety_notes_json"], []), steps=steps)


class CrossProjectOrchestrationPlanBuilder:
    def __init__(self, conn):
        self.conn = conn
        self.sessions = sessions_mod.CrossProjectExecutionSessionManager(conn)

    def build_plan(self, session_id):
        session = self.sessions.get_session(int(session_id))
        if session is None:
            raise ValueError(f"no cross-project execution session {session_id}")
        if session.status != "prepared":
            raise ValueError(f"session {session.id} is not prepared")
        checks = database.list_cross_project_execution_scope_checks(
            self.conn, session_id=session.id)
        if not checks:
            raise ValueError("orchestration plan requires resolved Stage 10 scope")
        ready = [c for c in checks if c["status"] == "ready"]
        blocked = [c for c in checks if c["status"] != "ready"]
        plan_id = database.save_cross_project_orchestration_plan(
            self.conn, session.id, session.plan_id, _now_iso(),
            "planned" if ready else "blocked",
            f"Stage 11 orchestration plan for execution session {session.id}.",
            len(checks), len(ready), len(blocked),
            json.dumps(_safety_notes(), sort_keys=True))
        for idx, check in enumerate(checks, start=1):
            blocked_reason = "; ".join(
                _safe_json_loads(check["blocked_reasons_json"], []))
            status = "ready" if check["status"] == "ready" else "blocked"
            database.save_cross_project_orchestration_step(
                self.conn, plan_id, session.id, check["id"], check["step_id"],
                check["command_proposal_id"], check["project_key"], idx, status,
                f"Run Stage 10 step {check['step_id']} for {check['project_key']}.",
                blocked_reason, json.dumps(_required_controls(), sort_keys=True))
        database.save_cross_project_orchestration_event(
            self.conn, plan_id, "planned",
            f"session={session.id} ready={len(ready)} blocked={len(blocked)}")
        return self.get_plan(plan_id)

    def get_plan(self, plan_id) -> Optional[CrossProjectOrchestrationPlan]:
        row = database.get_cross_project_orchestration_plan(self.conn, int(plan_id))
        return plan_from_row(self.conn, row) if row else None

    def list_plans(self, limit=50):
        return database.list_cross_project_orchestration_plans(self.conn, limit=limit)


def _required_controls():
    return [
        "Stage 10 confirmation must be approved for the exact step and command",
        "Stage 10 rollback snapshot must exist before execution",
        "Stage 11 advancement requires explicit --confirm-execution",
        "Stage 10 verification and outcome must succeed before later steps",
    ]


def _safety_notes():
    return [
        "Stage 11 plans are metadata-only.",
        "Stage 11 does not introduce a new command execution path.",
        "Stage 10 remains the only runtime execution layer.",
    ]
