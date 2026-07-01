"""Stage 9.3 — Advisory Cross-Project Execution Command Proposals."""

from dataclasses import dataclass
from typing import Optional

import database
import cross_project_execution_plans as plans_mod


@dataclass
class CrossProjectExecutionCommandProposal:
    id: int
    plan_id: int
    step_id: Optional[int]
    project_key: str
    command_type: str
    command_text: str
    allowlist_category: str
    risk: str
    requires_approval: bool
    reason: str
    status: str


def proposal_from_row(row) -> CrossProjectExecutionCommandProposal:
    return CrossProjectExecutionCommandProposal(
        id=row["id"], plan_id=row["plan_id"], step_id=row["step_id"],
        project_key=row["project_key"] or "",
        command_type=row["command_type"] or "",
        command_text=row["command_text"] or "",
        allowlist_category=row["allowlist_category"] or "",
        risk=row["risk"] or "medium",
        requires_approval=bool(row["requires_approval"]),
        reason=row["reason"] or "", status=row["status"] or "proposed")


class CrossProjectExecutionCommandProposer:
    def __init__(self, conn):
        self.conn = conn
        self.plans = plans_mod.CrossProjectExecutionPlanBuilder(conn)

    def propose(self, plan_id):
        plan = self.plans.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"no cross-project execution plan {plan_id}")
        existing = database.list_cross_project_execution_command_proposals(
            self.conn, plan_id=plan.id)
        if existing:
            return [proposal_from_row(r) for r in existing]
        proposals = []
        for step in plan.steps:
            if step.status == "blocked":
                continue
            for command in step.advisory_commands:
                command_type = "validation" if "--validate-project" in command else "inspection"
                allowlist = ("metadata_validation" if command_type == "validation"
                             else "metadata_inspection")
                proposal_id = database.save_cross_project_execution_command_proposal(
                    self.conn, plan.id, step.id, step.project_key, command_type,
                    command, allowlist, "low", True,
                    "Advisory preflight command; must be run manually after approval.",
                    "proposed")
                database.save_cross_project_execution_command_event(
                    self.conn, proposal_id, "created",
                    f"plan={plan.id} project={step.project_key}")
                proposals.append(self.get_proposal(proposal_id))
        return proposals

    def get_proposal(self, proposal_id) -> Optional[CrossProjectExecutionCommandProposal]:
        row = database.get_cross_project_execution_command_proposal(
            self.conn, proposal_id)
        return proposal_from_row(row) if row else None

    def list_proposals(self, limit=200):
        return [
            proposal_from_row(r)
            for r in database.list_cross_project_execution_command_proposals(
                self.conn, limit=limit)
        ]
