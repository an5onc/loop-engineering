"""Stage 13.0 — Restoration Eligibility Target Resolver."""

from dataclasses import dataclass

import database
import cross_project_orchestration_runs as runs_mod


@dataclass
class CrossProjectRestorationTarget:
    id: int
    run_id: int
    run_step_id: int
    orchestration_step_id: int
    advancement_id: int
    snapshot_id: int
    attempt_id: int
    status: str
    reason: str = ""


def target_from_row(row):
    return CrossProjectRestorationTarget(
        id=row["id"], run_id=row["run_id"], run_step_id=row["run_step_id"],
        orchestration_step_id=row["orchestration_step_id"],
        advancement_id=row["advancement_id"], snapshot_id=row["snapshot_id"],
        attempt_id=row["attempt_id"], status=row["status"] or "",
        reason=row["reason"] or "")


def _find_step(run, step_id):
    for step in run.steps:
        if step.step_id == step_id or step.stage10_step_id == step_id:
            return step
    raise ValueError(f"run {run.id} has no step {step_id}")


def latest_step_advancement(conn, run_id, run_step_id):
    for row in database.list_cross_project_orchestration_step_advancements(
            conn, run_id=run_id, limit=500):
        if row["run_step_id"] == run_step_id:
            return row
    return None


class CrossProjectRestorationTargetResolver:
    """Fail-closed resolver: which snapshot may restore a blocked step?"""

    def __init__(self, conn):
        self.conn = conn
        self.runs = runs_mod.CrossProjectOrchestrationRunManager(conn)

    def assess(self, run_id, step_id):
        """Non-persisting eligibility assessment (used by the status resolver)."""
        run = self.runs.get_run(int(run_id))
        if run is None:
            raise ValueError(f"no cross-project orchestration run {run_id}")
        step = _find_step(run, int(step_id))
        advancement = latest_step_advancement(self.conn, run.id, step.id)
        if step.status != "blocked":
            return self._refusal(run, step, advancement,
                                 f"step {step.id} is '{step.status}', not blocked; "
                                 "restoration applies to blocked steps only")
        if advancement is None:
            return self._refusal(run, step, advancement,
                                 f"step {step.id} has no prior advancement; "
                                 "nothing to restore")
        if advancement["status"] != "blocked":
            return self._refusal(run, step, advancement,
                                 f"latest advancement {advancement['id']} is "
                                 f"'{advancement['status']}', not blocked")
        if advancement["snapshot_id"] is None:
            return self._refusal(run, step, advancement,
                                 f"advancement {advancement['id']} recorded no "
                                 "rollback snapshot")
        snapshot = database.get_cross_project_execution_snapshot(
            self.conn, advancement["snapshot_id"])
        if snapshot is None:
            return self._refusal(run, step, advancement,
                                 f"snapshot {advancement['snapshot_id']} no "
                                 "longer exists")
        return {
            "eligible": True, "reason": "", "run": run, "step": step,
            "advancement": advancement,
        }

    def resolve(self, run_id, step_id):
        """Persist the assessment; raise on refusal (fail closed)."""
        assessment = self.assess(run_id, step_id)
        run, step = assessment["run"], assessment["step"]
        advancement = assessment["advancement"]
        target_id = database.save_cross_project_restoration_target(
            self.conn, run.id, step.id, step.orchestration_step_id,
            advancement["id"] if advancement else None,
            advancement["snapshot_id"] if advancement else None,
            advancement["attempt_id"] if advancement else None,
            "eligible" if assessment["eligible"] else "refused",
            assessment["reason"])
        if not assessment["eligible"]:
            raise ValueError(assessment["reason"])
        return target_from_row(database.get_cross_project_restoration_target(
            self.conn, target_id))

    def _refusal(self, run, step, advancement, reason):
        return {
            "eligible": False, "reason": reason, "run": run, "step": step,
            "advancement": advancement,
        }
