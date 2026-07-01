"""Stage 9.0 — Cross-Project Execution Intent Registry.

Stores explicit human-authored execution intent for later cross-project
execution planning. Metadata only: no commands, model calls, loops, external
jobs, project file reads, or project-root writes.
"""

import json
from dataclasses import dataclass, field
from typing import Optional

import database


VALID_SOURCE_TYPES = ("cross_project_plan", "governance_action_plan", "manual")
VALID_STATUSES = ("draft", "ready", "archived")


@dataclass
class CrossProjectExecutionIntent:
    id: int
    source_type: str
    source_id: int
    title: str
    owner: str
    status: str = "draft"
    summary: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def intent_from_row(row) -> CrossProjectExecutionIntent:
    return CrossProjectExecutionIntent(
        id=row["id"], source_type=row["source_type"],
        source_id=row["source_id"] or 0, title=row["title"] or "",
        owner=row["owner"] or "", status=row["status"] or "draft",
        summary=_safe_json_loads(row["summary_json"], {}),
        details=_safe_json_loads(row["details_json"], {}),
        created_at=row["created_at"], updated_at=row["updated_at"])


class CrossProjectExecutionIntentRegistry:
    def __init__(self, conn):
        self.conn = conn

    def create_intent(self, source_type, source_id, title, owner, summary=None,
                      details=None, status="draft") -> CrossProjectExecutionIntent:
        source_type = (source_type or "").strip()
        title = (title or "").strip()
        owner = (owner or "").strip()
        if source_type not in VALID_SOURCE_TYPES:
            raise ValueError(
                f"invalid source_type {source_type!r}; one of {VALID_SOURCE_TYPES}")
        try:
            source_id = int(source_id or 0)
        except (TypeError, ValueError):
            raise ValueError("source_id must be an integer")
        if source_type != "manual" and source_id <= 0:
            raise ValueError("non-manual execution intents require source_id > 0")
        if not title:
            raise ValueError("execution intent title is required")
        if not owner:
            raise ValueError("execution intent owner is required")
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid intent status {status!r}")
        intent_id = database.save_cross_project_execution_intent(
            self.conn, source_type, source_id, title, owner, status,
            json.dumps(summary or {}, sort_keys=True),
            json.dumps(details or {}, sort_keys=True))
        database.save_cross_project_execution_intent_event(
            self.conn, intent_id, "created",
            f"source={source_type}:{source_id} owner={owner}")
        return self.get_intent(intent_id)

    def get_intent(self, intent_id) -> Optional[CrossProjectExecutionIntent]:
        row = database.get_cross_project_execution_intent(self.conn, intent_id)
        return intent_from_row(row) if row else None

    def list_intents(self, limit=50):
        return database.list_cross_project_execution_intents(self.conn, limit=limit)

    def set_status(self, intent_id, status) -> CrossProjectExecutionIntent:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid intent status {status!r}")
        intent = self.get_intent(intent_id)
        if intent is None:
            raise ValueError(f"no cross-project execution intent {intent_id}")
        database.update_cross_project_execution_intent_status(
            self.conn, intent_id, status)
        database.save_cross_project_execution_intent_event(
            self.conn, intent_id, "status_changed", f"{intent.status}->{status}")
        return self.get_intent(intent_id)
