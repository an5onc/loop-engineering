"""Stage 12.3 — Bounded Orchestration Retry Policies."""

from dataclasses import dataclass

import database


MAX_RETRY_LIMIT = 3


@dataclass
class CrossProjectOrchestrationRetryPolicy:
    id: int
    run_id: int
    max_retries: int
    status: str
    created_by: str = ""
    notes: str = ""


def policy_from_row(row):
    return CrossProjectOrchestrationRetryPolicy(
        id=row["id"], run_id=row["run_id"],
        max_retries=row["max_retries"] or 0, status=row["status"] or "",
        created_by=row["created_by"] or "", notes=row["notes"] or "")


class CrossProjectOrchestrationRetryPolicyManager:
    def __init__(self, conn):
        self.conn = conn

    def set_policy(self, run_id, max_retries, created_by=None, notes=None):
        run = database.get_cross_project_orchestration_run(self.conn, int(run_id))
        if run is None:
            raise ValueError(f"no cross-project orchestration run {run_id}")
        try:
            retries = int(max_retries)
        except (TypeError, ValueError):
            raise ValueError("retry policy requires an integer --max-retries")
        if retries < 1 or retries > MAX_RETRY_LIMIT:
            raise ValueError(
                f"retry policy --max-retries must be between 1 and {MAX_RETRY_LIMIT}")
        existing = database.get_cross_project_orchestration_retry_policy_for_run(
            self.conn, run["id"])
        if existing is not None:
            raise ValueError(
                f"run {run['id']} already has retry policy {existing['id']}; "
                "retry budgets cannot be widened mid-run")
        policy_id = database.save_cross_project_orchestration_retry_policy(
            self.conn, run["id"], retries, "active", created_by or "operator",
            notes)
        return self.get_policy(policy_id)

    def get_policy(self, policy_id):
        row = database.get_cross_project_orchestration_retry_policy(
            self.conn, int(policy_id))
        return policy_from_row(row) if row else None

    def get_policy_for_run(self, run_id):
        row = database.get_cross_project_orchestration_retry_policy_for_run(
            self.conn, int(run_id))
        return policy_from_row(row) if row else None

    def list_policies(self, limit=50):
        rows = database.list_cross_project_orchestration_retry_policies(
            self.conn, limit=limit)
        return [policy_from_row(row) for row in rows]
