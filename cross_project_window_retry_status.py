"""Stage 12.6 — Combined Window & Retry Status Resolver."""

import datetime
import json
from dataclasses import dataclass, field

import database
import cross_project_execution_window_checks as checks_mod
import cross_project_execution_windows as windows_mod
import cross_project_orchestration_retry_policies as policies_mod
import cross_project_orchestration_runs as runs_mod


@dataclass
class CrossProjectWindowRetryStatus:
    id: int
    run_id: int
    run_step_id: int
    window_status: str
    retry_policy_id: int
    retries_allowed: int
    retries_used: int
    next_action: str
    detail: dict = field(default_factory=dict)


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def status_from_row(row):
    return CrossProjectWindowRetryStatus(
        id=row["id"], run_id=row["run_id"], run_step_id=row["run_step_id"],
        window_status=row["window_status"] or "",
        retry_policy_id=row["retry_policy_id"],
        retries_allowed=row["retries_allowed"] or 0,
        retries_used=row["retries_used"] or 0,
        next_action=row["next_action"] or "",
        detail=_safe_json_loads(row["detail_json"], {}))


def _now():
    return datetime.datetime.now()


class CrossProjectWindowRetryStatusResolver:
    def __init__(self, conn):
        self.conn = conn
        self.runs = runs_mod.CrossProjectOrchestrationRunManager(conn)
        self.windows = windows_mod.CrossProjectExecutionWindowManager(conn)
        self.policies = policies_mod.CrossProjectOrchestrationRetryPolicyManager(conn)

    def resolve(self, run_id, step_id=None, now=None):
        run = self.runs.get_run(int(run_id))
        if run is None:
            raise ValueError(f"no cross-project orchestration run {run_id}")
        moment = now or _now()
        windows = self.windows.list_windows(run_id=run.id, limit=200)
        window, window_status, window_reason = checks_mod.select_window(
            windows, moment)
        policy = self.policies.get_policy_for_run(run.id)
        step = None
        if step_id is not None:
            step = _find_step(run, int(step_id))
        retries_used = self._retries_used(run, step)
        authorized_request = self._authorized_request(run, step)
        next_action = _next_action(window_status, run, step, policy,
                                   retries_used, authorized_request)
        detail = {
            "window_id": window.id if window else None,
            "window_reason": window_reason,
            "run_status": run.status,
            "step_status": step.status if step else None,
            "authorized_retry_request_id": (
                authorized_request["id"] if authorized_request else None),
        }
        status_id = database.save_cross_project_window_retry_status(
            self.conn, run.id, step.id if step else None, window_status,
            policy.id if policy else None,
            policy.max_retries if policy else 0, retries_used, next_action,
            json.dumps(detail, sort_keys=True))
        return status_from_row(database.get_cross_project_window_retry_status(
            self.conn, status_id))

    def _retries_used(self, run, step):
        rows = database.list_cross_project_orchestration_step_advancements(
            self.conn, run_id=run.id, limit=500)
        if step is not None:
            attempts = [row for row in rows if row["run_step_id"] == step.id]
            return max(0, len(attempts) - 1)
        by_step = {}
        for row in rows:
            by_step[row["run_step_id"]] = by_step.get(row["run_step_id"], 0) + 1
        return sum(max(0, count - 1) for count in by_step.values())

    def _authorized_request(self, run, step):
        rows = database.list_cross_project_orchestration_retry_requests(
            self.conn, run_id=run.id,
            run_step_id=step.id if step else None)
        for row in rows:
            if row["status"] == "authorized":
                return row
        return None


def _find_step(run, step_id):
    for step in run.steps:
        if step.step_id == step_id or step.stage10_step_id == step_id:
            return step
    raise ValueError(f"run {run.id} has no step {step_id}")


def _next_action(window_status, run, step, policy, retries_used,
                 authorized_request):
    if window_status == "missing":
        return "define an execution window (--define-execution-window)"
    if window_status != "open":
        return "open an execution window (--open-execution-window)"
    blocked = step is not None and step.status == "blocked"
    if step is None:
        blocked = any(s.status == "blocked" for s in run.steps)
    if blocked:
        if policy is None:
            return "set a retry policy (--set-orchestration-retry-policy)"
        if authorized_request is not None:
            return ("advance with --confirm-execution using a fresh "
                    "Stage 10 confirmation")
        if retries_used < policy.max_retries:
            return "request an authorized retry (--request-orchestration-retry)"
        return "retry budget exhausted — review orchestration rollback status"
    if any(s.status == "pending" for s in run.steps):
        return "advance the pending step with --confirm-execution"
    return "review the window/retry report (--cross-project-window-retry-report)"
