"""Stage 9.5 — Human Approval Metadata for Cross-Project Execution."""

import datetime
from dataclasses import dataclass
from typing import Optional

import database


VALID_STATUSES = ("pending", "approved", "rejected", "cancelled")
DECISION_STATUSES = ("approved", "rejected", "cancelled")


@dataclass
class CrossProjectExecutionApproval:
    id: int
    plan_id: int
    dry_run_id: int
    status: str
    requested_at: Optional[str]
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    notes: Optional[str] = None


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def approval_from_row(row) -> CrossProjectExecutionApproval:
    return CrossProjectExecutionApproval(
        id=row["id"], plan_id=row["plan_id"], dry_run_id=row["dry_run_id"],
        status=row["status"] or "pending", requested_at=row["requested_at"],
        decided_at=row["decided_at"], decided_by=row["decided_by"],
        notes=row["notes"])


def is_usable(approval) -> bool:
    return getattr(approval, "status", None) == "approved"


class CrossProjectExecutionApprovalGate:
    def __init__(self, conn):
        self.conn = conn

    def request_approval(self, plan_id, dry_run_id) -> CrossProjectExecutionApproval:
        plan = database.get_cross_project_execution_plan(self.conn, plan_id)
        if plan is None:
            raise ValueError(f"no cross-project execution plan {plan_id}")
        dry_run = database.get_cross_project_execution_dry_run(self.conn, dry_run_id)
        if dry_run is None:
            raise ValueError(f"no cross-project execution dry-run {dry_run_id}")
        if dry_run["plan_id"] != plan["id"]:
            raise ValueError(
                f"dry-run {dry_run_id} references plan {dry_run['plan_id']}, "
                f"not plan {plan['id']}")
        latest = database.list_cross_project_execution_dry_runs(
            self.conn, plan_id=plan["id"], limit=1)
        if not latest or latest[0]["id"] != dry_run["id"]:
            raise ValueError(
                f"dry-run {dry_run_id} is not the latest dry-run for plan {plan['id']}")
        if dry_run["overall_status"] != "PASS":
            raise ValueError(
                f"dry-run {dry_run_id} is not passable "
                f"(status={dry_run['overall_status']})")
        approval_id = database.save_cross_project_execution_approval_request(
            self.conn, plan["id"], dry_run["id"], "pending", _now_iso())
        database.save_cross_project_execution_approval_event(
            self.conn, approval_id, "created",
            f"plan={plan['id']} dry_run={dry_run['id']}")
        return self.get_approval(approval_id)

    def get_approval(self, approval_id) -> Optional[CrossProjectExecutionApproval]:
        row = database.get_cross_project_execution_approval_request(
            self.conn, approval_id)
        return approval_from_row(row) if row else None

    def list_approvals(self, limit=50):
        return database.list_cross_project_execution_approval_requests(
            self.conn, limit=limit)

    def set_status(self, approval_id, status, decided_by=None,
                   notes=None) -> CrossProjectExecutionApproval:
        if status not in DECISION_STATUSES:
            raise ValueError(
                f"invalid execution approval decision {status!r}; "
                f"one of {DECISION_STATUSES}")
        approval = self.get_approval(approval_id)
        if approval is None:
            raise ValueError(f"no cross-project execution approval {approval_id}")
        database.update_cross_project_execution_approval_request(
            self.conn, approval_id, status, decided_at=_now_iso(),
            decided_by=decided_by, notes=notes)
        database.save_cross_project_execution_approval_event(
            self.conn, approval_id, "status_changed",
            f"{approval.status}->{status}")
        return self.get_approval(approval_id)

    def is_usable(self, approval) -> bool:
        return is_usable(approval)
