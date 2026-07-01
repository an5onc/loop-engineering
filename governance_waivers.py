"""Stage 8.4 — Exception / Waiver Registry.

Explicit, auditable human waivers for known governance findings. A waiver is
created FROM a finding: it captures that finding's stable signature
(policy_key :: rule_key :: subject) plus a reason, owner, and optional expiry.
During evaluation (Stage 8.1) an active, unexpired waiver suppresses any future
finding with the same signature.

Fail closed: only ``active`` and unexpired waivers suppress. Revoked or expired
waivers never suppress. Metadata-only — no commands, models, or project writes.
"""

import datetime
from dataclasses import dataclass
from typing import Optional

import database
import multi_project_governance_evaluation as eval_mod


VALID_STATUSES = ("active", "revoked", "expired")
DECISION_STATUSES = ("active", "revoked", "expired")


@dataclass
class GovernanceWaiver:
    id: int
    signature: str
    policy_key: str
    rule_key: str
    subject: str
    reason: Optional[str]
    owner: Optional[str]
    expiry: Optional[str]
    status: str
    source_finding_id: Optional[int]
    source_evaluation_id: Optional[int]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def waiver_from_row(row) -> GovernanceWaiver:
    return GovernanceWaiver(
        id=row["id"], signature=row["signature"], policy_key=row["policy_key"],
        rule_key=row["rule_key"], subject=row["subject"], reason=row["reason"],
        owner=row["owner"], expiry=row["expiry"], status=row["status"] or "active",
        source_finding_id=row["source_finding_id"],
        source_evaluation_id=row["source_evaluation_id"],
        created_at=row["created_at"], updated_at=row["updated_at"])


def is_active(waiver) -> bool:
    """True only when status='active' and the expiry has not passed."""
    row = {"status": getattr(waiver, "status", None),
           "expiry": getattr(waiver, "expiry", None)}
    return eval_mod.waiver_is_active(row)


class GovernanceWaiverRegistry:
    def __init__(self, conn):
        self.conn = conn

    def create_from_finding(self, finding_id, reason, owner,
                            expiry_days=None) -> GovernanceWaiver:
        finding = database.get_governance_policy_finding(self.conn, finding_id)
        if finding is None:
            raise ValueError(f"no governance finding {finding_id}")
        if not owner or not str(owner).strip():
            raise ValueError("a waiver owner is required")
        expiry = None
        if expiry_days is not None:
            expiry = (datetime.datetime.now()
                      + datetime.timedelta(days=int(expiry_days))
                      ).isoformat(timespec="seconds")
        waiver_id = database.save_governance_waiver(
            self.conn, finding["signature"], finding["policy_key"],
            finding["rule_key"], finding["subject"], reason, str(owner).strip(),
            expiry, "active", finding_id, finding["evaluation_id"])
        return self.get_waiver(waiver_id)

    def get_waiver(self, waiver_id) -> Optional[GovernanceWaiver]:
        row = database.get_governance_waiver(self.conn, waiver_id)
        return waiver_from_row(row) if row else None

    def list_waivers(self, limit=200):
        return database.list_governance_waivers(self.conn, limit=limit)

    def set_status(self, waiver_id, status) -> GovernanceWaiver:
        if status not in DECISION_STATUSES:
            raise ValueError(
                f"invalid waiver status {status!r}; one of {DECISION_STATUSES}")
        waiver = self.get_waiver(waiver_id)
        if waiver is None:
            raise ValueError(f"no governance waiver {waiver_id}")
        database.update_governance_waiver_status(self.conn, waiver_id, status)
        return self.get_waiver(waiver_id)

    def is_active(self, waiver) -> bool:
        return is_active(waiver)
