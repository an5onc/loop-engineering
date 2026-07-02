"""Stage 13.4 — Restoration Outcome Binder."""

from dataclasses import dataclass

import database
import cross_project_execution_outcomes as outcomes_mod
import cross_project_restoration_integrity as integrity_mod
import cross_project_restoration_targets as targets_mod


@dataclass
class CrossProjectRestorationOutcome:
    id: int
    run_id: int
    run_step_id: int
    rollback_id: int
    attempt_id: int
    outcome_id: int
    status: str
    summary: str = ""


def outcome_from_row(row):
    return CrossProjectRestorationOutcome(
        id=row["id"], run_id=row["run_id"], run_step_id=row["run_step_id"],
        rollback_id=row["rollback_id"], attempt_id=row["attempt_id"],
        outcome_id=row["outcome_id"], status=row["status"] or "",
        summary=row["summary"] or "")


class CrossProjectRestorationOutcomeBinder:
    """Records the Stage 10 outcome for a restored step (metadata only)."""

    def __init__(self, conn):
        self.conn = conn
        self.tracker = outcomes_mod.CrossProjectExecutionOutcomeTracker(conn)

    def record(self, run_id, run_step_id):
        rollback = integrity_mod.latest_restored_rollback(
            self.conn, int(run_id), int(run_step_id))
        if rollback is None:
            raise ValueError(
                f"run step {run_step_id} has no completed restoration; "
                "nothing to record")
        existing = _existing_outcome_for_rollback(
            self.conn, rollback["run_id"], rollback["id"])
        if existing is not None:
            return outcome_from_row(existing)
        advancement = targets_mod.latest_step_advancement(
            self.conn, rollback["run_id"], rollback["run_step_id"])
        if advancement is None or advancement["attempt_id"] is None:
            raise ValueError(
                f"run step {run_step_id} has no advancement attempt to "
                "record an outcome for")
        outcome = self.tracker.record(advancement["attempt_id"])
        summary = (f"Attempt {advancement['attempt_id']} outcome "
                   f"'{outcome.status}' after restoration {rollback['id']}.")
        record_id = database.save_cross_project_restoration_outcome(
            self.conn, rollback["run_id"], rollback["run_step_id"],
            rollback["id"], advancement["attempt_id"], outcome.id,
            outcome.status, summary)
        database.save_cross_project_orchestration_run_event(
            self.conn, rollback["run_id"], "rollback_outcome_recorded",
            f"step={rollback['run_step_id']} attempt={advancement['attempt_id']} "
            f"status={outcome.status}")
        return outcome_from_row(database.get_cross_project_restoration_outcome(
            self.conn, record_id))


def _existing_outcome_for_rollback(conn, run_id, rollback_id):
    for row in database.list_cross_project_restoration_outcomes(
            conn, run_id=run_id):
        if row["rollback_id"] == rollback_id:
            return row
    return None
