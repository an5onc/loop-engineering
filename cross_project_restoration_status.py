"""Stage 13.5 — Restoration Status Resolver."""

import json
from dataclasses import dataclass, field

import database
import cross_project_orchestration_runs as runs_mod
import cross_project_restoration_integrity as integrity_mod
import cross_project_restoration_targets as targets_mod


@dataclass
class CrossProjectRestorationStatus:
    id: int
    run_id: int
    run_step_id: int
    eligibility: str
    previewed: bool
    restored: bool
    integrity_status: str
    next_action: str
    detail: dict = field(default_factory=dict)


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def status_from_row(row):
    return CrossProjectRestorationStatus(
        id=row["id"], run_id=row["run_id"], run_step_id=row["run_step_id"],
        eligibility=row["eligibility"] or "",
        previewed=bool(row["previewed"]), restored=bool(row["restored"]),
        integrity_status=row["integrity_status"] or "",
        next_action=row["next_action"] or "",
        detail=_safe_json_loads(row["detail_json"], {}))


class CrossProjectRestorationStatusResolver:
    """Read-only inspection of the restoration lifecycle; never mutates
    run or step state."""

    def __init__(self, conn):
        self.conn = conn
        self.runs = runs_mod.CrossProjectOrchestrationRunManager(conn)
        self.targets = targets_mod.CrossProjectRestorationTargetResolver(conn)

    def resolve(self, run_id, step_id=None):
        run = self.runs.get_run(int(run_id))
        if run is None:
            raise ValueError(f"no cross-project orchestration run {run_id}")
        step = self._pick_step(run, step_id)
        if step is None:
            next_action = "no restoration needed; run has no blocked steps"
            status_id = database.save_cross_project_restoration_status(
                self.conn, run.id, None, "no_blocked_steps", False, False, "",
                next_action, json.dumps({"run_status": run.status},
                                        sort_keys=True))
            return status_from_row(database.get_cross_project_restoration_status(
                self.conn, status_id))
        assessment = self.targets.assess(run.id, step.step_id)
        eligibility = ("eligible" if assessment["eligible"]
                       else f"refused: {assessment['reason']}")
        snapshot_id = (assessment["advancement"]["snapshot_id"]
                       if assessment["advancement"] else None)
        previewed = self._has_rollback(run, step, "previewed", snapshot_id)
        restored = self._has_rollback(run, step, "restored", snapshot_id)
        integrity_status = self._latest_integrity_status(step)
        outcome_recorded = self._has_outcome(run, step)
        policy = database.get_cross_project_orchestration_retry_policy_for_run(
            self.conn, run.id)
        retries_used = self._retries_used(run, step)
        next_action = _next_action(
            step, assessment, previewed, restored, integrity_status,
            outcome_recorded, policy, retries_used)
        detail = {
            "step_status": step.status,
            "snapshot_id": snapshot_id,
            "outcome_recorded": outcome_recorded,
            "retry_policy_id": policy["id"] if policy else None,
            "retries_used": retries_used,
        }
        status_id = database.save_cross_project_restoration_status(
            self.conn, run.id, step.id, eligibility, previewed, restored,
            integrity_status, next_action, json.dumps(detail, sort_keys=True))
        return status_from_row(database.get_cross_project_restoration_status(
            self.conn, status_id))

    def _pick_step(self, run, step_id):
        if step_id is not None:
            return targets_mod._find_step(run, int(step_id))
        for step in run.steps:
            if step.status == "blocked":
                return step
        return None

    def _has_rollback(self, run, step, status, snapshot_id):
        for row in database.list_cross_project_orchestration_step_rollbacks(
                self.conn, run_id=run.id):
            if row["run_step_id"] != step.id or row["status"] != status:
                continue
            if snapshot_id is None or row["snapshot_id"] == snapshot_id:
                return True
        return False

    def _latest_integrity_status(self, step):
        rows = database.list_cross_project_restoration_integrity_checks(
            self.conn, run_step_id=step.id, limit=1)
        return rows[0]["status"] if rows else ""

    def _has_outcome(self, run, step):
        for row in database.list_cross_project_restoration_outcomes(
                self.conn, run_id=run.id):
            if row["run_step_id"] == step.id:
                return True
        return False

    def _retries_used(self, run, step):
        rows = database.list_cross_project_orchestration_step_advancements(
            self.conn, run_id=run.id, limit=500)
        attempts = [row for row in rows if row["run_step_id"] == step.id]
        return max(0, len(attempts) - 1)


def _next_action(step, assessment, previewed, restored, integrity_status,
                 outcome_recorded, policy, retries_used):
    if step.status != "blocked":
        return f"no restoration needed; step is '{step.status}'"
    if not assessment["eligible"]:
        return assessment["reason"]
    if not previewed:
        return "preview the restoration (--preview-orchestration-restoration)"
    if not restored:
        return ("restore the snapshot (--restore-orchestration-step ... "
                "--confirm-restore)")
    if not integrity_status:
        return "verify restoration integrity (--check-restoration-integrity)"
    if integrity_status == "mismatch":
        return ("integrity mismatch — re-preview and re-restore before "
                "retrying")
    if not outcome_recorded:
        return "record the rollback outcome (--record-restoration-outcome)"
    if policy is None:
        return "set a retry policy (--set-orchestration-retry-policy)"
    if retries_used < (policy["max_retries"] or 0):
        return "request an authorized retry (--request-orchestration-retry)"
    return ("restoration complete; retry budget exhausted — review the "
            "restoration report")
