"""Stage 12.5 — Window- and Retry-Gated Orchestration Advancement Engine."""

import json
from dataclasses import dataclass, field

import database
import cross_project_execution_window_checks as checks_mod
import cross_project_orchestration_retry_policies as policies_mod
import cross_project_orchestration_retry_requests as requests_mod
import cross_project_orchestration_runs as runs_mod
import cross_project_orchestration_runtime as orchestration_runtime_mod


@dataclass
class CrossProjectGatedAdvancement:
    id: int
    run_id: int
    run_step_id: int
    orchestration_step_id: int
    window_id: int
    window_check_id: int
    retry_request_id: int
    attempt_number: int
    confirmation_id: int
    snapshot_id: int
    advancement_id: int
    attempt_id: int
    status: str
    safety_notes: list = field(default_factory=list)


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def gated_advancement_from_row(row):
    return CrossProjectGatedAdvancement(
        id=row["id"], run_id=row["run_id"], run_step_id=row["run_step_id"],
        orchestration_step_id=row["orchestration_step_id"],
        window_id=row["window_id"], window_check_id=row["window_check_id"],
        retry_request_id=row["retry_request_id"],
        attempt_number=row["attempt_number"] or 0,
        confirmation_id=row["confirmation_id"], snapshot_id=row["snapshot_id"],
        advancement_id=row["advancement_id"], attempt_id=row["attempt_id"],
        status=row["status"] or "",
        safety_notes=_safe_json_loads(row["safety_notes_json"], []))


def _find_step(run, step_id):
    for step in run.steps:
        if step.step_id == step_id or step.stage10_step_id == step_id:
            return step
    raise ValueError(f"run {run.id} has no step {step_id}")


class CrossProjectGatedAdvancementEngine:
    """Stage 12 advancement path.

    Wraps the Stage 11 orchestration runtime (which delegates execution to
    the Stage 10 runtime) with two fail-closed gates: an operator execution
    window must be open, and any attempt beyond the first requires an
    authorized retry request plus a fresh Stage 10 confirmation.
    """

    def __init__(self, conn):
        self.conn = conn
        self.runs = runs_mod.CrossProjectOrchestrationRunManager(conn)
        self.runtime = orchestration_runtime_mod.CrossProjectOrchestrationRuntime(conn)
        self.checker = checks_mod.CrossProjectExecutionWindowChecker(conn)
        self.policies = policies_mod.CrossProjectOrchestrationRetryPolicyManager(conn)
        self.retries = requests_mod.CrossProjectOrchestrationRetryGate(conn)

    def advance(self, run_id, step_id, confirmation_id, snapshot_id,
                confirm_execution=False):
        if not confirm_execution:
            raise ValueError(
                "orchestration advancement requires explicit --confirm-execution")
        run = self.runs.get_run(int(run_id))
        if run is None:
            raise ValueError(f"no cross-project orchestration run {run_id}")
        step = _find_step(run, int(step_id))
        check = self.checker.check(run.id, run_step_id=step.id)
        if check.status != "open":
            raise ValueError(
                f"no open execution window covers run {run.id} "
                f"({check.status}): {check.reason}")
        prior_attempts = [
            row for row in database.list_cross_project_orchestration_step_advancements(
                self.conn, run_id=run.id, limit=500)
            if row["run_step_id"] == step.id
        ]
        attempt_number = len(prior_attempts) + 1
        retry_request = None
        if attempt_number > 1:
            retry_request = self._resolve_retry_authorization(
                run, step, prior_attempts, attempt_number, confirmation_id)
        advancement = self.runtime.advance(
            run.id, int(step_id), confirmation_id, snapshot_id,
            confirm_execution=True)
        gated_id = database.save_cross_project_gated_advancement(
            self.conn, run.id, step.id, step.orchestration_step_id,
            check.window_id, check.id,
            retry_request.id if retry_request else None, attempt_number,
            advancement.confirmation_id, advancement.snapshot_id,
            advancement.id, advancement.attempt_id, advancement.status,
            json.dumps(_safety_notes(attempt_number), sort_keys=True))
        if retry_request is not None:
            database.update_cross_project_orchestration_retry_request(
                self.conn, retry_request.id, "consumed",
                advancement_id=advancement.id)
        return gated_advancement_from_row(
            database.get_cross_project_gated_advancement(self.conn, gated_id))

    def _resolve_retry_authorization(self, run, step, prior_attempts,
                                     attempt_number, confirmation_id):
        authorized = None
        for row in database.list_cross_project_orchestration_retry_requests(
                self.conn, run_step_id=step.id):
            if row["status"] == "authorized":
                authorized = row
                break
        if authorized is None:
            raise ValueError(
                f"retry advancement for run step {step.id} requires an "
                "authorized retry request (--request-orchestration-retry)")
        policy = self.policies.get_policy_for_run(run.id)
        if policy is None:
            raise ValueError(
                f"run {run.id} has no active retry policy; retry refused")
        if attempt_number > 1 + policy.max_retries:
            raise ValueError(
                f"retry budget exhausted for run step {step.id}: "
                f"attempt {attempt_number} exceeds 1 + {policy.max_retries}")
        used_confirmations = {row["confirmation_id"] for row in prior_attempts}
        if int(confirmation_id) in used_confirmations:
            raise ValueError(
                f"confirmation {confirmation_id} was already used for run step "
                f"{step.id}; every retry requires a fresh Stage 10 confirmation")
        return requests_mod.request_from_row(authorized)


def _safety_notes(attempt_number):
    return [
        "Stage 12 verified an open operator execution window before advancement.",
        "Advancement delegated to the Stage 11 runtime, which delegates "
        "execution to the Stage 10 runtime.",
        f"Attempt {attempt_number} used its own approved Stage 10 confirmation "
        "and explicit --confirm-execution.",
        "Retries are metadata-authorized and bounded; nothing runs automatically.",
    ]
