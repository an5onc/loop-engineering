"""Stage 10.0 — Cross-Project Execution Session Preflight.

Turns a Stage 9 execution plan and approved handoff into a Stage 10 execution
session candidate. This module is metadata-only: no commands, file snapshots,
project-root writes, model calls, loops, or external jobs.
"""

import datetime
import json
from dataclasses import dataclass, field
from typing import Optional

import database
import cross_project_execution_approvals as approvals_mod
import cross_project_execution_plans as plans_mod


@dataclass
class CrossProjectExecutionSession:
    id: int
    plan_id: int
    approval_id: int
    dry_run_id: int
    handoff_id: int
    status: str
    summary: str
    eligible_steps: list = field(default_factory=list)
    blocked_reasons: list = field(default_factory=list)
    required_next_controls: list = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def session_from_row(row) -> CrossProjectExecutionSession:
    return CrossProjectExecutionSession(
        id=row["id"], plan_id=row["plan_id"], approval_id=row["approval_id"],
        dry_run_id=row["dry_run_id"], handoff_id=row["handoff_id"],
        status=row["status"] or "", summary=row["summary"] or "",
        eligible_steps=_safe_json_loads(row["eligible_steps_json"], []),
        blocked_reasons=_safe_json_loads(row["blocked_reasons_json"], []),
        required_next_controls=_safe_json_loads(
            row["required_next_controls_json"], []),
        created_at=row["created_at"] or "", updated_at=row["updated_at"] or "")


class CrossProjectExecutionSessionManager:
    def __init__(self, conn):
        self.conn = conn
        self.plans = plans_mod.CrossProjectExecutionPlanBuilder(conn)
        self.approvals = approvals_mod.CrossProjectExecutionApprovalGate(conn)

    def prepare(self, plan_id, approval_id) -> CrossProjectExecutionSession:
        plan = self.plans.get_plan(int(plan_id))
        if plan is None:
            raise ValueError(f"no cross-project execution plan {plan_id}")
        approval = self.approvals.get_approval(int(approval_id))
        if approval is None:
            raise ValueError(f"no cross-project execution approval {approval_id}")
        if approval.plan_id != plan.id:
            raise ValueError(
                f"approval {approval.id} references plan {approval.plan_id}, "
                f"not plan {plan.id}")
        if not approvals_mod.is_usable(approval):
            raise ValueError(
                f"execution approval {approval.id} is not approved "
                f"(status={approval.status})")
        dry_run = database.get_cross_project_execution_dry_run(
            self.conn, approval.dry_run_id)
        if dry_run is None or dry_run["overall_status"] != "PASS":
            raise ValueError("Stage 10 session requires a passing Stage 9 dry-run")
        latest = database.list_cross_project_execution_dry_runs(
            self.conn, plan_id=plan.id, limit=1)
        if not latest or latest[0]["id"] != approval.dry_run_id:
            raise ValueError("Stage 10 session requires the latest Stage 9 dry-run")
        handoff = self._matching_handoff(plan.id, approval.id, approval.dry_run_id)
        if handoff is None:
            raise ValueError("Stage 10 session requires a matching Stage 9 handoff")
        self._check_latest_stage9_audit()
        eligible = [
            {"step_id": s.id, "project_key": s.project_key, "phase": s.phase}
            for s in plan.steps if s.status != "blocked"
        ]
        blocked = [
            {"step_id": s.id, "project_key": s.project_key,
             "reason": s.blocked_reason or "blocked"}
            for s in plan.steps if s.status == "blocked"
        ]
        if not eligible:
            raise ValueError("Stage 10 session requires at least one eligible step")
        session_id = database.save_cross_project_execution_session(
            self.conn, plan.id, approval.id, approval.dry_run_id, handoff["id"],
            "prepared",
            f"Prepared Stage 10 execution session for plan {plan.id}.",
            json.dumps(eligible, sort_keys=True),
            json.dumps(blocked, sort_keys=True),
            json.dumps(_required_next_controls(), sort_keys=True))
        database.save_cross_project_execution_session_event(
            self.conn, session_id, "prepared",
            f"plan={plan.id} approval={approval.id} dry_run={approval.dry_run_id}")
        return self.get_session(session_id)

    def get_session(self, session_id) -> Optional[CrossProjectExecutionSession]:
        row = database.get_cross_project_execution_session(self.conn, int(session_id))
        return session_from_row(row) if row else None

    def list_sessions(self, limit=50):
        return database.list_cross_project_execution_sessions(self.conn, limit=limit)

    def _matching_handoff(self, plan_id, approval_id, dry_run_id):
        for row in database.list_cross_project_execution_handoffs(self.conn, limit=200):
            if (row["plan_id"] == plan_id and row["approval_id"] == approval_id
                    and row["dry_run_id"] == dry_run_id and row["status"] == "created"):
                return row
        return None

    def _check_latest_stage9_audit(self):
        rows = database.list_cross_project_stage9_audits(self.conn, limit=1)
        if rows and rows[0]["overall_status"] not in ("PASS", "PASS_WITH_WARNINGS"):
            raise ValueError("latest Stage 9 audit is not passing")


def _required_next_controls():
    return [
        "resolve execution scope before confirmation",
        "obtain Stage 10 execution confirmation for one step and command",
        "create rollback snapshot before execution",
        "run exactly one allowlisted command only with --confirm-execution",
    ]
