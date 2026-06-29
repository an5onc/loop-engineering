"""Manual action queue for Observatory remediation plans (Stage 4.5).

Action items are durable tracking records derived from saved remediation plans.
This module never executes suggested commands, calls models, mutates loops/jobs,
imports completions, resumes work, commits, or reads protected file contents.
Writes are limited to action metadata/events and optional Markdown reports under
observatory_action_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "observatory_action_reports")
STATUSES = {"open", "in_progress", "completed", "dismissed", "blocked"}


@dataclass
class ObservatoryActionItem:
    id: int
    source_plan_id: int
    source_item_id: int
    title: str
    category: str
    priority: str
    status: str
    suggested_command: str
    problem_summary: str
    recommended_action: str
    affected_loop_ids: List[int] = field(default_factory=list)
    affected_job_ids: List[int] = field(default_factory=list)
    risk_level: str = ""
    effort_level: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""
    dismissed_at: str = ""


@dataclass
class ObservatoryActionQueue:
    generated_at: str
    total_actions: int
    open_actions: int
    completed_actions: int
    dismissed_actions: int
    actions: List[ObservatoryActionItem] = field(default_factory=list)


@dataclass
class ObservatoryActionMarkdownReport:
    report_path: str
    report_format: str
    content_hash: str
    bytes_written: int
    created_at: str


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def _row_to_action(row):
    return ObservatoryActionItem(
        id=row["id"],
        source_plan_id=row["source_plan_id"],
        source_item_id=row["source_item_id"],
        title=row["title"] or "",
        category=row["category"] or "",
        priority=row["priority"] or "",
        status=row["status"] or "",
        suggested_command=row["suggested_command"] or "",
        problem_summary=row["problem_summary"] or "",
        recommended_action=row["recommended_action"] or "",
        affected_loop_ids=_safe_json_loads(row["affected_loop_ids_json"], []),
        affected_job_ids=_safe_json_loads(row["affected_job_ids_json"], []),
        risk_level=row["risk_level"] or "",
        effort_level=row["effort_level"] or "",
        notes=row["notes"] or "",
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
        completed_at=row["completed_at"] or "",
        dismissed_at=row["dismissed_at"] or "",
    )


def is_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


class ObservatoryActionEngine:
    def __init__(self, conn):
        self.conn = conn

    def create_actions_from_plan(self, plan_id):
        plan = database.get_observatory_remediation_plan(self.conn, int(plan_id))
        if plan is None:
            raise ValueError(f"no observatory remediation plan {plan_id}")
        items = _safe_json_loads(plan["items_json"], [])
        created = 0
        skipped = 0
        for item in items:
            source_item_id = int(item.get("id") or 0)
            existing = database.get_observatory_action_item_for_source(
                self.conn, int(plan_id), source_item_id)
            if existing is not None:
                skipped += 1
                database.save_observatory_action_event(
                    self.conn,
                    existing["id"],
                    "duplicate_skipped",
                    existing["status"],
                    existing["status"],
                    json.dumps({"source_plan_id": int(plan_id),
                                "source_item_id": source_item_id},
                               sort_keys=True),
                )
                continue
            action_id = database.save_observatory_action_item(
                self.conn,
                int(plan_id),
                source_item_id,
                item.get("title") or "",
                item.get("category") or "unknown",
                item.get("priority") or "low",
                "open",
                item.get("suggested_command") or "",
                item.get("problem_summary") or "",
                item.get("recommended_action") or "",
                json.dumps(item.get("affected_loop_ids") or [], sort_keys=True),
                json.dumps(item.get("affected_job_ids") or [], sort_keys=True),
                item.get("risk_level") or "",
                item.get("effort_level") or "",
                "",
            )
            created += 1
            database.save_observatory_action_event(
                self.conn, action_id, "created", None, "open",
                json.dumps({"source_plan_id": int(plan_id),
                            "source_item_id": source_item_id},
                           sort_keys=True))
        return {"created": created, "skipped": skipped}

    def list_actions(self, status="open", priority=None, category=None, limit=25):
        rows = database.list_observatory_action_items(
            self.conn, status=status, priority=priority, category=category,
            limit=int(limit or 25))
        actions = [_row_to_action(r) for r in rows]
        return ObservatoryActionQueue(
            generated_at=_now_iso(),
            total_actions=len(actions),
            open_actions=sum(1 for a in actions if a.status in ("open", "in_progress", "blocked")),
            completed_actions=sum(1 for a in actions if a.status == "completed"),
            dismissed_actions=sum(1 for a in actions if a.status == "dismissed"),
            actions=actions,
        )

    def get_action(self, action_id, record_view=True):
        row = database.get_observatory_action_item(self.conn, int(action_id))
        if row is None:
            raise ValueError(f"no observatory action {action_id}")
        if record_view:
            database.save_observatory_action_event(
                self.conn, int(action_id), "viewed", row["status"], row["status"], "{}")
        return _row_to_action(row)

    def update_status(self, action_id, status):
        if status not in STATUSES:
            raise ValueError(f"invalid observatory action status '{status}'")
        row = database.get_observatory_action_item(self.conn, int(action_id))
        if row is None:
            raise ValueError(f"no observatory action {action_id}")
        before = row["status"]
        database.update_observatory_action_status(self.conn, int(action_id), status)
        database.save_observatory_action_event(
            self.conn, int(action_id), "status_changed", before, status, "{}")
        return self.get_action(action_id, record_view=False)

    def update_notes(self, action_id, notes):
        row = database.get_observatory_action_item(self.conn, int(action_id))
        if row is None:
            raise ValueError(f"no observatory action {action_id}")
        database.update_observatory_action_notes(self.conn, int(action_id), notes or "")
        database.save_observatory_action_event(
            self.conn, int(action_id), "notes_updated", row["status"], row["status"],
            json.dumps({"notes_length": len(notes or "")}, sort_keys=True))
        return self.get_action(action_id, record_view=False)

    def save_markdown_report(self):
        queue = self.list_actions(status=None, limit=1000)
        content = self.render_markdown(queue)
        path = self._new_report_path()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_observatory_action_markdown_report(
            self.conn, path, "markdown", chash, nbytes)
        return ObservatoryActionMarkdownReport(
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def _new_report_path(self):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"observatory_actions_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("action report path escaped observatory_action_reports/")
        return target

    def render_markdown(self, queue):
        lines = []
        a = lines.append
        a("# Loop Engineering Observatory Action Queue")
        a("")
        a("## Summary")
        a(f"- Generated at: {queue.generated_at}")
        a(f"- Total actions: {queue.total_actions}")
        a(f"- Open actions: {queue.open_actions}")
        a(f"- Completed actions: {queue.completed_actions}")
        a(f"- Dismissed actions: {queue.dismissed_actions}")
        a("")
        self._append_section(lines, "Open Actions",
                             [x for x in queue.actions if x.status in ("open", "in_progress", "blocked")])
        self._append_section(lines, "High Priority Actions",
                             [x for x in queue.actions if x.priority in ("urgent", "high")])
        self._append_section(lines, "Safety Actions",
                             [x for x in queue.actions if x.category == "safety"])
        self._append_section(lines, "Completed Actions",
                             [x for x in queue.actions if x.status == "completed"])
        self._append_section(lines, "Dismissed Actions",
                             [x for x in queue.actions if x.status == "dismissed"])
        a("## Next Steps")
        a("- python3 main.py --observatory-actions")
        a("- python3 main.py --observatory-remediation")
        a("- python3 main.py --observatory-failures")
        a("")
        a("## Safety Notes")
        a("- Action queue commands never execute suggested commands")
        a("- No model calls")
        a("- No command execution")
        a("- No job mutation")
        a("- No loop mutation")
        a("")
        return "\n".join(lines)

    def _append_section(self, lines, title, actions):
        lines.append(f"## {title}")
        if not actions:
            lines.append("- (none)")
            lines.append("")
            return
        for action in actions:
            lines.append(f"- #{action.id} [{action.priority}] {action.category}: {action.title}")
            lines.append(f"  status: {action.status}")
            lines.append(f"  command: {action.suggested_command}")
        lines.append("")
