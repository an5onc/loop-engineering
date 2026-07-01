"""Stage 8.6 — Governance Action Planner.

Generates manual follow-up plans from unresolved governance findings (WARN/FAIL,
not waived). Every suggested command is emitted as TEXT ONLY — the planner never
executes anything, mutates a project, creates loops/jobs, or calls a model.
"""

import datetime
import json
from dataclasses import dataclass, field
from typing import List, Optional

import database


# Per-rule advisory follow-up commands (text only, never executed).
RULE_ADVICE = {
    "not_stale": [
        "python3 main.py --validate-project {subject}",
        "# Restore or re-register the project root, then re-validate.",
    ],
    "validation_not_failing": [
        "python3 main.py --validate-project {subject}",
        "python3 main.py --project-validation-reports --project {subject}",
    ],
    "require_validation": [
        "python3 main.py --validate-project {subject}",
    ],
    "blocked_project_handling": [
        "python3 main.py --project {subject}",
        "python3 main.py --set-project-status {subject} active  # after review",
    ],
    "require_safety_profile": [
        "python3 main.py --project {subject}  # assign a safety profile",
    ],
    "approval_freshness": [
        "python3 main.py --cross-project-approvals",
    ],
    "handoff_schedule_integrity": [
        "python3 main.py --cross-project-handoffs",
        "python3 main.py --multi-project-schedules",
    ],
    "audit_recency": [
        "python3 main.py --multi-project-audit --save-report",
    ],
}


@dataclass
class ActionItem:
    id: int
    plan_id: int
    policy_key: str
    rule_key: str
    subject: str
    description: str
    suggested_commands: List[str] = field(default_factory=list)


@dataclass
class GovernanceActionPlan:
    id: int
    generated_at: str
    source_evaluation_id: Optional[int]
    total_items: int
    suggested_commands: List[str] = field(default_factory=list)
    safety_notes: List[str] = field(default_factory=list)
    status: str = "proposed"
    summary: str = ""
    items: List[ActionItem] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def _advice(rule_key, subject):
    return [c.format(subject=subject) for c in RULE_ADVICE.get(rule_key, [
        "# Review this finding manually; no automated remediation is provided.",
    ])]


class GovernanceActionPlanner:
    def __init__(self, conn):
        self.conn = conn

    def plan(self, evaluation_id=None, persist=True) -> GovernanceActionPlan:
        if evaluation_id is None:
            rows = database.list_governance_policy_evaluations(self.conn, limit=1)
            if not rows:
                raise ValueError("no governance evaluations exist to plan from")
            evaluation_id = rows[0]["id"]
        evaluation = database.get_governance_policy_evaluation(
            self.conn, evaluation_id)
        if evaluation is None:
            raise ValueError(f"no governance evaluation {evaluation_id}")

        items = []
        for finding in database.list_governance_policy_findings(
                self.conn, evaluation_id):
            if finding["status"] not in ("WARN", "FAIL"):
                continue
            items.append(ActionItem(
                id=0, plan_id=0, policy_key=finding["policy_key"],
                rule_key=finding["rule_key"], subject=finding["subject"],
                description=(f"Resolve {finding['rule_key']} for "
                             f"{finding['subject']} ({finding['status']})"),
                suggested_commands=_advice(finding["rule_key"],
                                           finding["subject"])))

        plan_commands = [
            f"python3 main.py --governance-evaluation {evaluation_id}",
            "python3 main.py --governance-review-items",
            "# Address each item below, then re-run --evaluate-governance-policies.",
        ]
        safety_notes = [
            "All suggested commands are advisory text only; none are executed.",
            "No project roots are modified by this plan.",
            "No loops, jobs, model calls, or commands are created/run.",
        ]
        summary = (f"{len(items)} action item(s) from evaluation {evaluation_id}")
        plan = GovernanceActionPlan(
            id=0, generated_at=_now_iso(), source_evaluation_id=evaluation_id,
            total_items=len(items), suggested_commands=plan_commands,
            safety_notes=safety_notes, status="proposed", summary=summary,
            items=items)
        if persist:
            self._persist(plan)
        return plan

    def _persist(self, plan) -> None:
        plan.id = database.save_governance_action_plan(
            self.conn, plan.generated_at, plan.source_evaluation_id,
            plan.total_items, json.dumps(plan.suggested_commands),
            json.dumps(plan.safety_notes), plan.status, plan.summary)
        for item in plan.items:
            item.plan_id = plan.id
            item.id = database.save_governance_action_plan_item(
                self.conn, plan.id, item.policy_key, item.rule_key, item.subject,
                item.description, json.dumps(item.suggested_commands))
        database.save_governance_action_plan_event(
            self.conn, plan.id, "created",
            f"source_evaluation={plan.source_evaluation_id} items={plan.total_items}")

    def get_plan(self, plan_id) -> Optional[GovernanceActionPlan]:
        row = database.get_governance_action_plan(self.conn, plan_id)
        if row is None:
            return None
        items = [
            ActionItem(
                id=r["id"], plan_id=r["plan_id"], policy_key=r["policy_key"],
                rule_key=r["rule_key"], subject=r["subject"],
                description=r["description"],
                suggested_commands=_safe_json_loads(r["suggested_commands_json"], []))
            for r in database.list_governance_action_plan_items(self.conn, plan_id)
        ]
        return GovernanceActionPlan(
            id=row["id"], generated_at=row["generated_at"] or "",
            source_evaluation_id=row["source_evaluation_id"],
            total_items=row["total_items"] or 0,
            suggested_commands=_safe_json_loads(row["suggested_commands_json"], []),
            safety_notes=_safe_json_loads(row["safety_notes_json"], []),
            status=row["status"] or "proposed", summary=row["summary"] or "",
            items=items)

    def list_plans(self, limit=50):
        return database.list_governance_action_plans(self.conn, limit=limit)
