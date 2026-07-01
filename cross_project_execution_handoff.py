"""Stage 9.6 — Cross-Project Execution Handoff Packet Generator."""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Optional

import database
import cross_project_execution_approvals as approvals_mod
import cross_project_execution_plans as plans_mod


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PACKETS_DIR = os.path.join(PROJECT_ROOT, "cross_project_execution_handoff_packets")


@dataclass
class CrossProjectExecutionHandoff:
    id: int
    plan_id: int
    approval_id: int
    dry_run_id: Optional[int]
    generated_at: str
    packet_path: str
    packet_format: str
    content_hash: str
    bytes_written: int
    status: str
    projects: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def is_packet_path(path) -> bool:
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(PACKETS_DIR)
    return target != base and target.startswith(base + os.sep)


def handoff_from_row(row):
    return CrossProjectExecutionHandoff(
        id=row["id"], plan_id=row["plan_id"], approval_id=row["approval_id"],
        dry_run_id=row["dry_run_id"], generated_at=row["generated_at"] or "",
        packet_path=row["packet_path"] or "",
        packet_format=row["packet_format"] or "markdown",
        content_hash=row["content_hash"] or "",
        bytes_written=row["bytes_written"] or 0,
        status=row["status"] or "created",
        projects=_safe_json_loads(row["projects_json"], []))


class CrossProjectExecutionHandoffBuilder:
    def __init__(self, conn):
        self.conn = conn
        self.plans = plans_mod.CrossProjectExecutionPlanBuilder(conn)
        self.gate = approvals_mod.CrossProjectExecutionApprovalGate(conn)

    def create_handoff(self, plan_id, approval_id) -> CrossProjectExecutionHandoff:
        plan = self.plans.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"no cross-project execution plan {plan_id}")
        approval = self.gate.get_approval(approval_id)
        if approval is None:
            raise ValueError(f"no cross-project execution approval {approval_id}")
        if approval.plan_id != plan.id:
            raise ValueError(
                f"approval {approval_id} references plan {approval.plan_id}, "
                f"not plan {plan.id}")
        if not approvals_mod.is_usable(approval):
            raise ValueError(
                f"approval {approval_id} is not usable (status={approval.status})")
        dry_run = database.get_cross_project_execution_dry_run(
            self.conn, approval.dry_run_id)
        if dry_run is None or dry_run["overall_status"] != "PASS":
            raise ValueError("approved execution handoff requires a passing dry-run")
        latest = database.list_cross_project_execution_dry_runs(
            self.conn, plan_id=plan.id, limit=1)
        if not latest or latest[0]["id"] != approval.dry_run_id:
            raise ValueError("approved execution handoff requires the latest dry-run")
        content = self.render_packet(plan, approval)
        path = self._new_packet_path(plan.id, approval.id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        projects = [s.project_key for s in plan.steps if s.status != "blocked"]
        handoff_id = database.save_cross_project_execution_handoff(
            self.conn, plan.id, approval.id, approval.dry_run_id, _now_iso(),
            path, "markdown", chash, len(encoded), "created",
            json.dumps(projects, sort_keys=True))
        database.save_cross_project_execution_handoff_event(
            self.conn, handoff_id, "created",
            f"plan={plan.id} approval={approval.id}")
        return self.get_handoff(handoff_id)

    def get_handoff(self, handoff_id) -> Optional[CrossProjectExecutionHandoff]:
        row = database.get_cross_project_execution_handoff(self.conn, handoff_id)
        return handoff_from_row(row) if row else None

    def list_handoffs(self, limit=50):
        return database.list_cross_project_execution_handoffs(self.conn, limit=limit)

    def _new_packet_path(self, plan_id, approval_id):
        os.makedirs(PACKETS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            PACKETS_DIR,
            f"cross_project_execution_plan_{int(plan_id)}_approval_{int(approval_id)}_{_now_stamp()}.md"))
        if not is_packet_path(path):
            raise ValueError("execution handoff packet path escaped directory")
        return path

    def render_packet(self, plan, approval):
        lines = []
        a = lines.append
        a("# Cross-Project Execution Planning Handoff")
        a("")
        a("## Summary")
        a(f"- Plan ID: {plan.id}")
        a(f"- Approval ID: {approval.id} (status: {approval.status})")
        a(f"- Dry-run ID: {approval.dry_run_id}")
        a(f"- Generated at: {_now_iso()}")
        a("")
        a("## Safety Rules")
        for note in (
            "Do not execute automatically.",
            "Do not create loops, command results, external jobs, commits, or pushes.",
            "Do not read protected file contents.",
            "Do not write project roots from this packet.",
        ):
            a(f"- {note}")
        a("")
        a("## Advisory Commands")
        for step in plan.steps:
            a(f"- Project `{step.project_key}` ({step.status})")
            if step.blocked_reason:
                a(f"  - blocked: {step.blocked_reason}")
            for cmd in step.advisory_commands:
                a(f"  - `{cmd}`")
        a("")
        a("## Required Approvals")
        for item in plan.required_approvals:
            a(f"- {item}")
        a("")
        a("## Rollback Requirements")
        for item in plan.rollback_requirements:
            a(f"- {item}")
        a("")
        a("## Completion Response JSON")
        a("```json")
        a(json.dumps({
            "execution_plan_id": plan.id,
            "approval_id": approval.id,
            "dry_run_id": approval.dry_run_id,
            "status": "not_executed",
            "commands_run": [],
            "notes": "",
        }, indent=2))
        a("```")
        a("")
        return "\n".join(lines)
