"""Stage 11.3 — Step Control Resolver."""

import json
from dataclasses import dataclass, field

import database
import cross_project_orchestration_runs as runs_mod


@dataclass
class CrossProjectOrchestrationStepControl:
    id: int
    run_id: int
    run_step_id: int
    orchestration_step_id: int
    status: str
    confirmation_id: int = None
    snapshot_id: int = None
    required_controls: list = field(default_factory=list)
    next_action: str = ""


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def control_from_row(row):
    return CrossProjectOrchestrationStepControl(
        id=row["id"], run_id=row["run_id"], run_step_id=row["run_step_id"],
        orchestration_step_id=row["orchestration_step_id"],
        status=row["status"] or "", confirmation_id=row["confirmation_id"],
        snapshot_id=row["snapshot_id"],
        required_controls=_safe_json_loads(row["required_controls_json"], []),
        next_action=row["next_action"] or "")


class CrossProjectOrchestrationControlResolver:
    def __init__(self, conn):
        self.conn = conn
        self.runs = runs_mod.CrossProjectOrchestrationRunManager(conn)

    def resolve(self, run_id, step_id):
        run = self.runs.get_run(int(run_id))
        if run is None:
            raise ValueError(f"no cross-project orchestration run {run_id}")
        step = _find_step(run, int(step_id))
        orchestration_step = database.get_cross_project_orchestration_step(
            self.conn, step.orchestration_step_id)
        confirmation = _latest_matching_confirmation(
            self.conn, step, orchestration_step["session_id"])
        snapshot = _latest_matching_snapshot(self.conn, run, confirmation)
        if confirmation is None:
            status, action = "needs_confirmation", "request Stage 10 confirmation"
        elif confirmation["status"] != "approved":
            status, action = "needs_approval", "approve Stage 10 confirmation"
        elif snapshot is None:
            status, action = "needs_snapshot", "create Stage 10 rollback snapshot"
        else:
            status, action = "ready", "advance orchestration step with --confirm-execution"
        cid = database.save_cross_project_orchestration_step_control(
            self.conn, run.id, step.id, step.orchestration_step_id, status,
            confirmation["id"] if confirmation else None,
            snapshot["id"] if snapshot else None,
            json.dumps(_required_controls(), sort_keys=True), action)
        return control_from_row(database.get_cross_project_orchestration_step_control(
            self.conn, cid))


def _find_step(run, step_id):
    for step in run.steps:
        if step.step_id == step_id or step.stage10_step_id == step_id:
            return step
    raise ValueError(f"run {run.id} has no step {step_id}")


def _latest_matching_confirmation(conn, step, session_id):
    rows = database.list_cross_project_execution_confirmations(conn, limit=200)
    for row in rows:
        if (row["session_id"] == session_id
                and row["step_id"] == step.stage10_step_id
                and row["command_proposal_id"] == step.command_proposal_id):
            return row
    return None


def _latest_matching_snapshot(conn, run, confirmation):
    if confirmation is None:
        return None
    for row in database.list_cross_project_execution_snapshots(conn, limit=200):
        if row["confirmation_id"] == confirmation["id"]:
            return row
    return None


def _required_controls():
    return [
        "Stage 10 confirmation must be approved",
        "Stage 10 snapshot must exist",
        "Stage 11 advancement requires --confirm-execution",
    ]
