"""Stage 11.2 — Orchestration Run Starter."""

import datetime
from dataclasses import dataclass, field

import database
import cross_project_orchestration_dry_run as dry_mod
import cross_project_orchestration_plans as plans_mod


@dataclass
class CrossProjectOrchestrationRunStep:
    id: int
    run_id: int
    orchestration_step_id: int
    step_id: int
    stage10_step_id: int
    command_proposal_id: int
    project_key: str
    sequence_number: int
    status: str
    attempt_id: int = None
    verification_run_id: int = None
    outcome_id: int = None


@dataclass
class CrossProjectOrchestrationRun:
    id: int
    plan_id: int
    dry_run_id: int
    started_at: str
    status: str
    total_steps: int
    completed_steps: int
    blocked_steps: int
    summary: str
    steps: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def run_step_from_row(row):
    return CrossProjectOrchestrationRunStep(
        id=row["id"], run_id=row["run_id"],
        orchestration_step_id=row["orchestration_step_id"],
        step_id=row["orchestration_step_id"],
        stage10_step_id=row["stage10_step_id"],
        command_proposal_id=row["command_proposal_id"],
        project_key=row["project_key"] or "",
        sequence_number=row["sequence_number"] or 0,
        status=row["status"] or "", attempt_id=row["attempt_id"],
        verification_run_id=row["verification_run_id"], outcome_id=row["outcome_id"])


def run_from_row(conn, row):
    steps = [
        run_step_from_row(r)
        for r in database.list_cross_project_orchestration_run_steps(conn, row["id"])
    ]
    return CrossProjectOrchestrationRun(
        id=row["id"], plan_id=row["orchestration_plan_id"],
        dry_run_id=row["dry_run_id"], started_at=row["started_at"] or "",
        status=row["status"] or "", total_steps=row["total_steps"] or 0,
        completed_steps=row["completed_steps"] or 0,
        blocked_steps=row["blocked_steps"] or 0,
        summary=row["summary"] or "", steps=steps)


class CrossProjectOrchestrationRunManager:
    def __init__(self, conn):
        self.conn = conn
        self.plans = plans_mod.CrossProjectOrchestrationPlanBuilder(conn)
        self.dry_runs = dry_mod.CrossProjectOrchestrationDryRunValidator(conn)

    def start(self, plan_id, dry_run_id):
        plan = self.plans.get_plan(int(plan_id))
        if plan is None:
            raise ValueError(f"no cross-project orchestration plan {plan_id}")
        dry_run = self.dry_runs.get_dry_run(int(dry_run_id))
        if dry_run is None or dry_run.plan_id != plan.id:
            raise ValueError("orchestration run requires matching dry-run")
        latest = database.list_cross_project_orchestration_dry_runs(
            self.conn, plan_id=plan.id, limit=1)
        if not latest or latest[0]["id"] != dry_run.id:
            raise ValueError("orchestration run requires latest dry-run")
        if dry_run.overall_status != "PASS":
            raise ValueError("orchestration run requires passing dry-run")
        ready_steps = [s for s in plan.steps if s.status == "ready"]
        run_id = database.save_cross_project_orchestration_run(
            self.conn, plan.id, dry_run.id, _now_iso(), "running",
            len(ready_steps), 0, 0,
            f"Stage 11 orchestration run for plan {plan.id}.")
        for step in ready_steps:
            database.save_cross_project_orchestration_run_step(
                self.conn, run_id, step.id, step.stage10_step_id,
                step.command_proposal_id, step.project_key,
                step.sequence_number, "pending")
        database.save_cross_project_orchestration_run_event(
            self.conn, run_id, "started", f"plan={plan.id} dry_run={dry_run.id}")
        return self.get_run(run_id)

    def get_run(self, run_id):
        row = database.get_cross_project_orchestration_run(self.conn, int(run_id))
        return run_from_row(self.conn, row) if row else None
