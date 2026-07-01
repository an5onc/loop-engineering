"""Stage 9.2 — Cross-Project Execution Plan Builder."""

import datetime
import json
from dataclasses import dataclass, field
from typing import Optional

import database
import cross_project_execution_intents as intents_mod
import cross_project_execution_readiness as readiness_mod


@dataclass
class CrossProjectExecutionPlanStep:
    id: int
    plan_id: int
    project_key: str
    phase: str
    action_summary: str
    status: str
    gating: dict = field(default_factory=dict)
    advisory_commands: list = field(default_factory=list)
    blocked_reason: Optional[str] = None


@dataclass
class CrossProjectExecutionPlan:
    id: int
    intent_id: int
    readiness_report_id: int
    generated_at: str
    status: str
    summary: str
    required_approvals: list = field(default_factory=list)
    rollback_requirements: list = field(default_factory=list)
    validation_requirements: list = field(default_factory=list)
    safety_notes: list = field(default_factory=list)
    steps: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def step_from_row(row) -> CrossProjectExecutionPlanStep:
    return CrossProjectExecutionPlanStep(
        id=row["id"], plan_id=row["plan_id"], project_key=row["project_key"],
        phase=row["phase"] or "", action_summary=row["action_summary"] or "",
        status=row["status"] or "planned",
        gating=_safe_json_loads(row["gating_json"], {}),
        advisory_commands=_safe_json_loads(row["advisory_commands_json"], []),
        blocked_reason=row["blocked_reason"])


class CrossProjectExecutionPlanBuilder:
    def __init__(self, conn):
        self.conn = conn
        self.intents = intents_mod.CrossProjectExecutionIntentRegistry(conn)
        self.readiness = readiness_mod.CrossProjectExecutionReadinessResolver(conn)

    def build_plan(self, intent_id, readiness_report_id, persist=True):
        intent = self.intents.get_intent(intent_id)
        if intent is None:
            raise ValueError(f"no cross-project execution intent {intent_id}")
        readiness = self.readiness.get_report(readiness_report_id)
        if readiness is None:
            raise ValueError(f"no cross-project execution readiness report {readiness_report_id}")
        if readiness.intent_id != intent.id:
            raise ValueError(
                f"readiness report {readiness_report_id} references intent "
                f"{readiness.intent_id}, not intent {intent.id}")
        steps = []
        for item in readiness.project_results:
            project_key = item["project_key"]
            blocked = item["status"] != "ready"
            commands = [
                f"python3 main.py --validate-project {project_key}",
                f"python3 main.py --project {project_key}",
            ]
            steps.append(CrossProjectExecutionPlanStep(
                id=0, plan_id=0, project_key=project_key,
                phase="project_preflight",
                action_summary=(
                    f"Prepare reviewed execution work for {project_key}; "
                    "commands are advisory text only."),
                status="blocked" if blocked else "planned",
                gating={
                    "requires_dry_run": True,
                    "requires_human_approval": True,
                    "requires_validation": True,
                    "no_auto_execution": True,
                },
                advisory_commands=commands,
                blocked_reason="; ".join(item.get("blockers", [])) or None))
        required = [
            "Dry-run must pass before approval.",
            "Human approval must reference the exact plan and dry-run.",
            "No commands may be executed automatically from this plan.",
        ]
        rollback = [
            "Capture per-project rollback instructions before execution.",
            "Do not proceed if rollback path is unavailable.",
        ]
        validation = [
            "Re-run project validation before any execution.",
            "Run post-change validation manually after future execution.",
        ]
        safety = [
            "Execution plan stores metadata and advisory commands only.",
            "No project file contents are read and no project roots are written.",
            "No loops, command_results, or external_agent_jobs are created.",
        ]
        plan = CrossProjectExecutionPlan(
            id=0, intent_id=intent.id, readiness_report_id=readiness.id,
            generated_at=_now_iso(),
            status="blocked" if readiness.overall_status == "BLOCKED" else "planned",
            summary=f"{len(steps)} project execution step(s) for intent {intent.id}",
            required_approvals=required, rollback_requirements=rollback,
            validation_requirements=validation, safety_notes=safety, steps=steps)
        if persist:
            self._persist(plan)
        return plan

    def _persist(self, plan):
        plan.id = database.save_cross_project_execution_plan(
            self.conn, plan.intent_id, plan.readiness_report_id,
            plan.generated_at, plan.status, plan.summary,
            json.dumps(plan.required_approvals, sort_keys=True),
            json.dumps(plan.rollback_requirements, sort_keys=True),
            json.dumps(plan.validation_requirements, sort_keys=True),
            json.dumps(plan.safety_notes, sort_keys=True))
        for step in plan.steps:
            step.plan_id = plan.id
            step.id = database.save_cross_project_execution_plan_step(
                self.conn, plan.id, step.project_key, step.phase,
                step.action_summary, step.status,
                json.dumps(step.gating, sort_keys=True),
                json.dumps(step.advisory_commands, sort_keys=True),
                step.blocked_reason)
        database.save_cross_project_execution_plan_event(
            self.conn, plan.id, "created",
            f"intent={plan.intent_id} readiness={plan.readiness_report_id}")

    def get_plan(self, plan_id) -> Optional[CrossProjectExecutionPlan]:
        row = database.get_cross_project_execution_plan(self.conn, plan_id)
        if row is None:
            return None
        steps = [step_from_row(r)
                 for r in database.list_cross_project_execution_plan_steps(
                     self.conn, plan_id)]
        return CrossProjectExecutionPlan(
            id=row["id"], intent_id=row["intent_id"],
            readiness_report_id=row["readiness_report_id"],
            generated_at=row["generated_at"] or "",
            status=row["status"] or "planned", summary=row["summary"] or "",
            required_approvals=_safe_json_loads(row["required_approvals_json"], []),
            rollback_requirements=_safe_json_loads(
                row["rollback_requirements_json"], []),
            validation_requirements=_safe_json_loads(
                row["validation_requirements_json"], []),
            safety_notes=_safe_json_loads(row["safety_notes_json"], []),
            steps=steps)

    def list_plans(self, limit=50):
        return database.list_cross_project_execution_plans(self.conn, limit=limit)
