"""Stage 7.6 — Controlled Multi-Project Scheduling Metadata.

Records scheduling INTENT only. There is no timer, no daemon, no auto-run, and
no command execution anywhere in this module. Changing a schedule's status only
updates a metadata row — it never starts work. A schedule may only be created
for a plan that has a valid ``approved`` approval (fail closed).
"""

import datetime
from dataclasses import dataclass
from typing import Optional

import database
import cross_project_approvals as approvals_mod


VALID_STATUSES = ("active", "paused", "cancelled", "completed")


@dataclass
class MultiProjectSchedule:
    id: int
    plan_id: int
    approval_id: int
    window: str
    status: str
    notes: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def schedule_from_row(row) -> MultiProjectSchedule:
    return MultiProjectSchedule(
        id=row["id"], plan_id=row["plan_id"], approval_id=row["approval_id"],
        window=row["window"] or "", status=row["status"] or "active",
        notes=row["notes"], created_at=row["created_at"],
        updated_at=row["updated_at"])


class MultiProjectScheduler:
    def __init__(self, conn):
        self.conn = conn
        self.gate = approvals_mod.CrossProjectApprovalGate(conn)

    def schedule_plan(self, plan_id, approval_id, window="manual",
                      notes=None) -> MultiProjectSchedule:
        plan = database.get_cross_project_work_plan(self.conn, plan_id)
        if plan is None:
            raise ValueError(f"no cross-project plan {plan_id}")
        approval = self.gate.get_approval(approval_id)
        if approval is None:
            raise ValueError(f"no cross-project approval {approval_id}")
        if approval.plan_id != plan["id"]:
            raise ValueError(
                f"approval {approval_id} references plan {approval.plan_id}, "
                f"not plan {plan['id']}")
        if not approvals_mod.is_usable(approval):
            raise ValueError(
                f"approval {approval_id} is not usable (status={approval.status}); "
                "an approved approval is required before scheduling")
        schedule_id = database.save_multi_project_schedule(
            self.conn, plan_id, approval_id, window or "manual", "active", notes)
        database.save_multi_project_schedule_event(
            self.conn, schedule_id, "created",
            f"plan={plan_id} approval={approval_id} window={window} status=active")
        return self.get_schedule(schedule_id)

    def get_schedule(self, schedule_id) -> Optional[MultiProjectSchedule]:
        row = database.get_multi_project_schedule(self.conn, schedule_id)
        return schedule_from_row(row) if row else None

    def list_schedules(self, limit=50):
        return database.list_multi_project_schedules(self.conn, limit=limit)

    def set_status(self, schedule_id, status) -> MultiProjectSchedule:
        if status not in VALID_STATUSES:
            raise ValueError(
                f"invalid schedule status {status!r}; one of {VALID_STATUSES}")
        schedule = self.get_schedule(schedule_id)
        if schedule is None:
            raise ValueError(f"no multi-project schedule {schedule_id}")
        database.update_multi_project_schedule_status(self.conn, schedule_id, status)
        database.save_multi_project_schedule_event(
            self.conn, schedule_id, "status_changed",
            f"{schedule.status}->{status} (metadata only; no work started)")
        return self.get_schedule(schedule_id)
