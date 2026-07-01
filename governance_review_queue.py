"""Stage 8.3 — Governance Review Queue.

Converts non-passing policy findings into manual review items. Review items are
purely for human triage — creating or updating one performs no remediation, runs
no command, calls no model, and never mutates a registered project. Statuses:
open, acknowledged, waived, resolved, dismissed, blocked.
"""

from dataclasses import dataclass
from typing import List, Optional

import database


VALID_STATUSES = ("open", "acknowledged", "waived", "resolved", "dismissed",
                  "blocked")
# Findings with these statuses become review items.
ACTIONABLE_FINDING_STATUSES = ("WARN", "FAIL")


@dataclass
class ReviewItem:
    id: int
    evaluation_id: Optional[int]
    finding_id: Optional[int]
    policy_key: str
    rule_key: str
    subject: str
    signature: str
    severity: str
    status: str
    notes: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def item_from_row(row) -> ReviewItem:
    return ReviewItem(
        id=row["id"], evaluation_id=row["evaluation_id"],
        finding_id=row["finding_id"], policy_key=row["policy_key"],
        rule_key=row["rule_key"], subject=row["subject"],
        signature=row["signature"], severity=row["severity"],
        status=row["status"] or "open", notes=row["notes"],
        created_at=row["created_at"], updated_at=row["updated_at"])


class GovernanceReviewQueue:
    def __init__(self, conn):
        self.conn = conn

    def create_items(self, evaluation_id) -> List[ReviewItem]:
        evaluation = database.get_governance_policy_evaluation(
            self.conn, evaluation_id)
        if evaluation is None:
            raise ValueError(f"no governance evaluation {evaluation_id}")
        created = []
        for finding in database.list_governance_policy_findings(
                self.conn, evaluation_id):
            if finding["status"] not in ACTIONABLE_FINDING_STATUSES:
                continue
            if database.get_governance_review_item_for_finding(
                    self.conn, evaluation_id, finding["id"]):
                continue
            item_id = database.save_governance_review_item(
                self.conn, evaluation_id, finding["id"], finding["policy_key"],
                finding["rule_key"], finding["subject"], finding["signature"],
                finding["severity"], "open")
            database.save_governance_review_item_event(
                self.conn, item_id, "created",
                f"from finding {finding['id']} ({finding['status']})")
            created.append(self.get_item(item_id))
        return created

    def get_item(self, item_id) -> Optional[ReviewItem]:
        row = database.get_governance_review_item(self.conn, item_id)
        return item_from_row(row) if row else None

    def list_items(self, status=None) -> List[ReviewItem]:
        if status is not None and status not in VALID_STATUSES:
            raise ValueError(f"invalid status filter {status!r}")
        return [item_from_row(r)
                for r in database.list_governance_review_items(
                    self.conn, status=status)]

    def set_status(self, item_id, status, notes=None) -> ReviewItem:
        if status not in VALID_STATUSES:
            raise ValueError(
                f"invalid review status {status!r}; one of {VALID_STATUSES}")
        item = self.get_item(item_id)
        if item is None:
            raise ValueError(f"no governance review item {item_id}")
        database.update_governance_review_item_status(
            self.conn, item_id, status, notes=notes)
        database.save_governance_review_item_event(
            self.conn, item_id, "status_changed", f"{item.status}->{status}")
        return self.get_item(item_id)
