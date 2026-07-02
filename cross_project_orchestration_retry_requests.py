"""Stage 12.4 — Explicit Operator Retry Authorization."""

from dataclasses import dataclass

import database
import cross_project_orchestration_retry_policies as policies_mod
import cross_project_orchestration_runs as runs_mod


@dataclass
class CrossProjectOrchestrationRetryRequest:
    id: int
    run_id: int
    run_step_id: int
    orchestration_step_id: int
    policy_id: int
    attempt_number: int
    status: str
    requested_by: str = ""
    reason: str = ""
    advancement_id: int = None


def request_from_row(row):
    return CrossProjectOrchestrationRetryRequest(
        id=row["id"], run_id=row["run_id"], run_step_id=row["run_step_id"],
        orchestration_step_id=row["orchestration_step_id"],
        policy_id=row["policy_id"], attempt_number=row["attempt_number"] or 0,
        status=row["status"] or "", requested_by=row["requested_by"] or "",
        reason=row["reason"] or "", advancement_id=row["advancement_id"])


def _find_step(run, step_id):
    for step in run.steps:
        if step.step_id == step_id or step.stage10_step_id == step_id:
            return step
    raise ValueError(f"run {run.id} has no step {step_id}")


class CrossProjectOrchestrationRetryGate:
    """Authorizes exactly one bounded retry as metadata; nothing executes here.

    Every retry attempt still requires its own approved Stage 10 confirmation
    and a literal --confirm-execution at advancement time.
    """

    def __init__(self, conn):
        self.conn = conn
        self.runs = runs_mod.CrossProjectOrchestrationRunManager(conn)
        self.policies = policies_mod.CrossProjectOrchestrationRetryPolicyManager(conn)

    def request_retry(self, run_id, step_id, requested_by=None, reason=None):
        run = self.runs.get_run(int(run_id))
        if run is None:
            raise ValueError(f"no cross-project orchestration run {run_id}")
        step = _find_step(run, int(step_id))
        if step.status != "blocked":
            raise ValueError(
                f"orchestration step {step.id} is '{step.status}'; "
                "only a blocked step can be retried")
        policy = self.policies.get_policy_for_run(run.id)
        if policy is None:
            raise ValueError(
                f"run {run.id} has no active retry policy; "
                "set one with --set-orchestration-retry-policy")
        for row in database.list_cross_project_orchestration_retry_requests(
                self.conn, run_step_id=step.id):
            if row["status"] == "authorized":
                raise ValueError(
                    f"run step {step.id} already has authorized retry request "
                    f"{row['id']}")
        prior_step_attempts = [
            row for row in database.list_cross_project_orchestration_step_advancements(
                self.conn, run_id=run.id, limit=500)
            if row["run_step_id"] == step.id
        ]
        if not prior_step_attempts:
            raise ValueError(
                f"run step {step.id} has no prior advancement; nothing to retry")
        retries_used = len(prior_step_attempts) - 1
        if retries_used >= policy.max_retries:
            raise ValueError(
                f"retry budget exhausted for run step {step.id}: "
                f"{retries_used} of {policy.max_retries} retries used")
        attempt_number = len(prior_step_attempts) + 1
        request_id = database.save_cross_project_orchestration_retry_request(
            self.conn, run.id, step.id, step.orchestration_step_id, policy.id,
            attempt_number, "authorized", requested_by or "operator", reason)
        database.update_cross_project_orchestration_run_step(
            self.conn, step.id, "pending")
        database.update_cross_project_orchestration_run_status(
            self.conn, run.id, "running", blocked_steps=0,
            summary=f"Retry {attempt_number - 1} authorized for step {step.id}.")
        database.save_cross_project_orchestration_run_event(
            self.conn, run.id, "retry_authorized",
            f"step={step.id} request={request_id} attempt={attempt_number}")
        return self.get_request(request_id)

    def get_request(self, request_id):
        row = database.get_cross_project_orchestration_retry_request(
            self.conn, int(request_id))
        return request_from_row(row) if row else None

    def list_requests(self, run_id=None, limit=100):
        rows = database.list_cross_project_orchestration_retry_requests(
            self.conn, run_id=run_id, limit=limit)
        return [request_from_row(row) for row in rows]
