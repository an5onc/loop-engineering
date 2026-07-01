"""Stage 7.4 — Cross-Project Approval Gates.

Explicit approval metadata that must exist (and be ``approved``) before any
cross-project handoff or schedule may reference a plan. Approvals only update
metadata: requesting or deciding an approval executes nothing, modifies no
repository, and never runs the plan. Rejected / cancelled / expired / pending
approvals are not usable.
"""

import datetime
from dataclasses import dataclass
from typing import Optional

import database


VALID_STATUSES = ("pending", "approved", "rejected", "expired", "cancelled")
DECISION_STATUSES = ("approved", "rejected", "expired", "cancelled")


@dataclass
class CrossProjectApproval:
    id: int
    plan_id: int
    status: str
    requested_at: Optional[str]
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    notes: Optional[str] = None


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def approval_from_row(row) -> CrossProjectApproval:
    return CrossProjectApproval(
        id=row["id"], plan_id=row["plan_id"], status=row["status"] or "pending",
        requested_at=row["requested_at"], decided_at=row["decided_at"],
        decided_by=row["decided_by"], notes=row["notes"])


def is_usable(approval) -> bool:
    """An approval may be used for handoff/scheduling only when approved."""
    return getattr(approval, "status", None) == "approved"


class CrossProjectApprovalGate:
    def __init__(self, conn):
        self.conn = conn

    def request_approval(self, plan_id) -> CrossProjectApproval:
        plan = database.get_cross_project_work_plan(self.conn, plan_id)
        if plan is None:
            raise ValueError(f"approval must reference a valid plan; no plan {plan_id}")
        approval_id = database.save_cross_project_approval(
            self.conn, plan_id, "pending", _now_iso())
        return self.get_approval(approval_id)

    def get_approval(self, approval_id) -> Optional[CrossProjectApproval]:
        row = database.get_cross_project_approval(self.conn, approval_id)
        return approval_from_row(row) if row else None

    def list_approvals(self, limit=50):
        return database.list_cross_project_approvals(self.conn, limit=limit)

    def set_status(self, approval_id, status, decided_by=None,
                   notes=None) -> CrossProjectApproval:
        if status not in DECISION_STATUSES:
            raise ValueError(
                f"invalid approval decision {status!r}; one of {DECISION_STATUSES}")
        approval = self.get_approval(approval_id)
        if approval is None:
            raise ValueError(f"no cross-project approval {approval_id}")
        database.update_cross_project_approval(
            self.conn, approval_id, status, decided_at=_now_iso(),
            decided_by=decided_by, notes=notes)
        return self.get_approval(approval_id)

    def is_usable(self, approval) -> bool:
        return is_usable(approval)
