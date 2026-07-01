"""Stage 11.5 — Orchestration Verification and Stop Policy."""

from dataclasses import dataclass

import database
import cross_project_execution_outcomes as outcomes_mod
import cross_project_execution_verification as verification_mod
import cross_project_orchestration_runs as runs_mod


@dataclass
class CrossProjectOrchestrationStepVerification:
    id: int
    run_id: int
    run_step_id: int
    orchestration_step_id: int
    attempt_id: int
    verification_run_id: int
    outcome_id: int
    status: str
    summary: str


class CrossProjectOrchestrationVerificationBinder:
    def __init__(self, conn):
        self.conn = conn
        self.runs = runs_mod.CrossProjectOrchestrationRunManager(conn)
        self.verifier = verification_mod.CrossProjectExecutionVerificationRunner(conn)
        self.outcomes = outcomes_mod.CrossProjectExecutionOutcomeTracker(conn)

    def verify_step(self, run_id, step_id):
        run = self.runs.get_run(int(run_id))
        if run is None:
            raise ValueError(f"no cross-project orchestration run {run_id}")
        step = _find_step(run, int(step_id))
        if not step.attempt_id:
            raise ValueError("orchestration step has no execution attempt")
        verification = self.verifier.verify(step.attempt_id)
        outcome = self.outcomes.record(step.attempt_id)
        status = "succeeded" if outcome.status == "succeeded" else "blocked"
        vid = database.save_cross_project_orchestration_step_verification(
            self.conn, run.id, step.id, step.orchestration_step_id, step.attempt_id,
            verification.id, outcome.id, status,
            f"orchestration step {step.id} verification: {status}")
        database.update_cross_project_orchestration_run_step(
            self.conn, step.id, status, verification_run_id=verification.id,
            outcome_id=outcome.id)
        completed = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_orchestration_run_steps "
            "WHERE run_id=? AND status='succeeded'", (run.id,)).fetchone()["n"]
        total = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_orchestration_run_steps "
            "WHERE run_id=?", (run.id,)).fetchone()["n"]
        if status != "succeeded":
            database.update_cross_project_orchestration_run_status(
                self.conn, run.id, "blocked", completed_steps=completed,
                blocked_steps=1)
        elif completed == total:
            database.update_cross_project_orchestration_run_status(
                self.conn, run.id, "succeeded", completed_steps=completed)
        return CrossProjectOrchestrationStepVerification(
            id=vid, run_id=run.id, run_step_id=step.id,
            orchestration_step_id=step.orchestration_step_id,
            attempt_id=step.attempt_id, verification_run_id=verification.id,
            outcome_id=outcome.id, status=status,
            summary=f"orchestration step {step.id} verification: {status}")


def _find_step(run, step_id):
    for step in run.steps:
        if step.step_id == step_id or step.stage10_step_id == step_id:
            return step
    raise ValueError(f"run {run.id} has no step {step_id}")
