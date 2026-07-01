"""Stage 11.4 — Single-Step Orchestration Advancement Engine."""

import json
from dataclasses import dataclass, field

import database
import cross_project_execution_runtime as runtime_mod
import cross_project_orchestration_runs as runs_mod


@dataclass
class CrossProjectOrchestrationStepAdvancement:
    id: int
    run_id: int
    run_step_id: int
    orchestration_step_id: int
    confirmation_id: int
    snapshot_id: int
    attempt_id: int
    status: str
    safety_notes: list = field(default_factory=list)


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def advancement_from_row(row):
    return CrossProjectOrchestrationStepAdvancement(
        id=row["id"], run_id=row["run_id"], run_step_id=row["run_step_id"],
        orchestration_step_id=row["orchestration_step_id"],
        confirmation_id=row["confirmation_id"], snapshot_id=row["snapshot_id"],
        attempt_id=row["attempt_id"], status=row["status"] or "",
        safety_notes=_safe_json_loads(row["safety_notes_json"], []))


class CrossProjectOrchestrationRuntime:
    def __init__(self, conn):
        self.conn = conn
        self.runs = runs_mod.CrossProjectOrchestrationRunManager(conn)
        self.runtime = runtime_mod.CrossProjectExecutionRuntime(conn)

    def advance(self, run_id, step_id, confirmation_id, snapshot_id,
                confirm_execution=False):
        if not confirm_execution:
            raise ValueError("orchestration advancement requires explicit --confirm-execution")
        run = self.runs.get_run(int(run_id))
        if run is None:
            raise ValueError(f"no cross-project orchestration run {run_id}")
        if run.status != "running":
            raise ValueError(f"orchestration run {run.id} is not running")
        step = _find_step(run, int(step_id))
        if step.status != "pending":
            raise ValueError(f"orchestration step {step.id} is not pending")
        _ensure_prior_steps_succeeded(run, step)
        confirmation = database.get_cross_project_execution_confirmation(
            self.conn, int(confirmation_id))
        if confirmation is None:
            raise ValueError(f"no Stage 10 confirmation {confirmation_id}")
        orchestration_step = database.get_cross_project_orchestration_step(
            self.conn, step.orchestration_step_id)
        if confirmation["session_id"] != orchestration_step["session_id"]:
            raise ValueError("confirmation does not match orchestration session")
        if (confirmation["step_id"] != step.stage10_step_id
                or confirmation["command_proposal_id"] != step.command_proposal_id):
            raise ValueError("confirmation does not match orchestration step")
        snapshot = database.get_cross_project_execution_snapshot(
            self.conn, int(snapshot_id))
        if snapshot is None:
            raise ValueError(f"no Stage 10 snapshot {snapshot_id}")
        if snapshot["session_id"] != orchestration_step["session_id"]:
            raise ValueError("snapshot does not match orchestration session")
        attempt = self.runtime.execute(
            confirmation["session_id"], confirmation["id"], snapshot["id"],
            confirm_execution=True)
        status = "executed" if attempt.status == "succeeded" else "blocked"
        adv_id = database.save_cross_project_orchestration_step_advancement(
            self.conn, run.id, step.id, step.orchestration_step_id,
            confirmation["id"], snapshot["id"], attempt.id, status,
            json.dumps(_safety_notes(), sort_keys=True))
        database.update_cross_project_orchestration_run_step(
            self.conn, step.id, "executed" if status == "executed" else "blocked",
            attempt_id=attempt.id)
        if status != "executed":
            database.update_cross_project_orchestration_run_status(
                self.conn, run.id, "blocked", blocked_steps=1,
                summary=f"Stage {step.id} blocked during execution.")
        database.save_cross_project_orchestration_run_event(
            self.conn, run.id, "advanced",
            f"step={step.id} attempt={attempt.id} status={status}")
        return advancement_from_row(
            database.get_cross_project_orchestration_step_advancement(
                self.conn, adv_id))


def _find_step(run, step_id):
    for step in run.steps:
        if step.step_id == step_id or step.stage10_step_id == step_id:
            return step
    raise ValueError(f"run {run.id} has no step {step_id}")


def _ensure_prior_steps_succeeded(run, step):
    for prior in run.steps:
        if prior.sequence_number >= step.sequence_number:
            continue
        if prior.status != "succeeded":
            raise ValueError("prior orchestration step is not verified as succeeded")


def _safety_notes():
    return [
        "Stage 11 advanced exactly one step.",
        "Execution delegated to Stage 10 runtime.",
        "No parallel or batch execution was performed.",
    ]
