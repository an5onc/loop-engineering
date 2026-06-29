"""Loop Improvement Action Conversion (Stage 5.2).

Reviewed improvement proposals can be converted into durable manual action
items. This module never executes suggested commands, calls models, applies
proposals, mutates framework definitions, creates loops/jobs, commits, or reads
protected file contents. Writes are limited to action metadata/events/batches
and optional Markdown reports under loop_improvement_action_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import List

import database
import loop_improvement_review


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "loop_improvement_action_reports")
STATUSES = {"open", "in_progress", "completed", "dismissed", "blocked"}


@dataclass
class LoopImprovementActionItem:
    id: int
    source_review_id: int
    source_proposal_id: int
    source_plan_id: int
    target_type: str
    target_name: str
    title: str
    priority: str
    status: str
    risk_level: str
    effort_level: str
    problem_summary: str
    proposed_change: str
    expected_benefit: str
    recommended_decision: str
    suggested_next_command: str
    affected_loop_ids: List[int] = field(default_factory=list)
    affected_action_ids: List[int] = field(default_factory=list)
    affected_remediation_plan_ids: List[int] = field(default_factory=list)
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""
    dismissed_at: str = ""


@dataclass
class LoopImprovementActionBatch:
    id: int
    source_review_id: int
    generated_at: str
    total_actions: int
    created_count: int
    skipped_duplicates: int
    actions: List[LoopImprovementActionItem] = field(default_factory=list)


@dataclass
class LoopImprovementActionMarkdownReport:
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
    return LoopImprovementActionItem(
        id=row["id"],
        source_review_id=row["source_review_id"],
        source_proposal_id=row["source_proposal_id"],
        source_plan_id=row["source_plan_id"],
        target_type=row["target_type"] or "",
        target_name=row["target_name"] or "",
        title=row["title"] or "",
        priority=row["priority"] or "low",
        status=row["status"] or "open",
        risk_level=row["risk_level"] or "",
        effort_level=row["effort_level"] or "",
        problem_summary=row["problem_summary"] or "",
        proposed_change=row["proposed_change"] or "",
        expected_benefit=row["expected_benefit"] or "",
        recommended_decision=row["recommended_decision"] or "",
        suggested_next_command=row["suggested_next_command"] or "",
        affected_loop_ids=_safe_json_loads(row["affected_loop_ids_json"], []),
        affected_action_ids=_safe_json_loads(row["affected_action_ids_json"], []),
        affected_remediation_plan_ids=_safe_json_loads(
            row["affected_remediation_plan_ids_json"], []),
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


class LoopImprovementActionEngine:
    def __init__(self, conn):
        self.conn = conn

    def create_actions_from_review(self, review_id, priority=None, target_type=None,
                                   include_deferred=False, include_rejected=False):
        review_id = int(review_id)
        row = database.get_loop_improvement_review(self.conn, review_id)
        if row is None:
            raise ValueError(f"no loop improvement review {review_id}")
        report = loop_improvement_review.report_from_row(row)
        created = []
        skipped = 0
        filters = {
            "priority": priority,
            "target_type": target_type,
            "include_deferred": bool(include_deferred),
            "include_rejected": bool(include_rejected),
        }
        for item in report.top_proposals:
            if priority and item.priority != priority:
                continue
            if target_type and item.target_type != target_type:
                continue
            if not self._included(item, include_deferred, include_rejected):
                continue
            existing = database.get_loop_improvement_action_item_for_source(
                self.conn, review_id, item.proposal_id)
            if existing is not None:
                skipped += 1
                database.save_loop_improvement_action_event(
                    self.conn,
                    existing["id"],
                    "duplicate_skipped",
                    existing["status"],
                    existing["status"],
                    json.dumps({"source_review_id": review_id,
                                "source_proposal_id": item.proposal_id},
                               sort_keys=True),
                )
                continue
            action_id = database.save_loop_improvement_action_item(
                self.conn,
                review_id,
                item.proposal_id,
                item.plan_id,
                item.target_type,
                item.target_name,
                item.title,
                item.priority,
                "open",
                item.risk_level,
                item.effort_level,
                item.problem_summary,
                item.proposed_change,
                item.expected_benefit,
                item.recommended_decision,
                item.suggested_next_command,
                json.dumps(item.affected_loop_ids or [], sort_keys=True),
                json.dumps(item.affected_action_ids or [], sort_keys=True),
                json.dumps(item.affected_remediation_plan_ids or [], sort_keys=True),
                "",
            )
            database.save_loop_improvement_action_event(
                self.conn,
                action_id,
                "created",
                None,
                "open",
                json.dumps({"source_review_id": review_id,
                            "source_proposal_id": item.proposal_id},
                           sort_keys=True),
            )
            created.append(self.get_action(action_id, record_view=False))
        generated_at = _now_iso()
        total_actions = len(created) + skipped
        batch_id = database.save_loop_improvement_action_batch(
            self.conn,
            review_id,
            generated_at,
            json.dumps(filters, sort_keys=True),
            total_actions,
            len(created),
            skipped,
            json.dumps([a.id for a in created], sort_keys=True),
        )
        return LoopImprovementActionBatch(
            id=batch_id,
            source_review_id=review_id,
            generated_at=generated_at,
            total_actions=total_actions,
            created_count=len(created),
            skipped_duplicates=skipped,
            actions=created,
        )

    def list_actions(self, status="open", priority=None, target_type=None, limit=25):
        rows = database.list_loop_improvement_action_items(
            self.conn, status=status, priority=priority, target_type=target_type,
            limit=int(limit or 25))
        return [_row_to_action(row) for row in rows]

    def get_action(self, action_id, record_view=True):
        row = database.get_loop_improvement_action_item(self.conn, int(action_id))
        if row is None:
            raise ValueError(f"no loop improvement action {action_id}")
        if record_view:
            database.save_loop_improvement_action_event(
                self.conn, int(action_id), "viewed", row["status"], row["status"], "{}")
        return _row_to_action(row)

    def update_status(self, action_id, status):
        if status not in STATUSES:
            raise ValueError(f"invalid loop improvement action status '{status}'")
        row = database.get_loop_improvement_action_item(self.conn, int(action_id))
        if row is None:
            raise ValueError(f"no loop improvement action {action_id}")
        before = row["status"]
        database.update_loop_improvement_action_status(self.conn, int(action_id), status)
        database.save_loop_improvement_action_event(
            self.conn, int(action_id), "status_changed", before, status, "{}")
        return self.get_action(action_id, record_view=False)

    def update_notes(self, action_id, notes):
        row = database.get_loop_improvement_action_item(self.conn, int(action_id))
        if row is None:
            raise ValueError(f"no loop improvement action {action_id}")
        database.update_loop_improvement_action_notes(self.conn, int(action_id), notes or "")
        database.save_loop_improvement_action_event(
            self.conn,
            int(action_id),
            "notes_updated",
            row["status"],
            row["status"],
            json.dumps({"notes_length": len(notes or "")}, sort_keys=True),
        )
        return self.get_action(action_id, record_view=False)

    def save_markdown_report(self):
        actions = self.list_actions(status=None, limit=1000)
        content = self.render_markdown(actions)
        path = self._new_report_path()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_loop_improvement_action_markdown_report(
            self.conn, path, "markdown", chash, nbytes)
        return LoopImprovementActionMarkdownReport(
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def _included(self, item, include_deferred, include_rejected):
        rejected = item.status == "rejected" or item.recommended_decision == "reject"
        deferred = item.status == "deferred"
        if rejected:
            return bool(include_rejected)
        if deferred:
            return bool(include_deferred)
        if item.recommended_decision in ("accept", "convert_to_action"):
            return True
        if item.priority in ("urgent", "high"):
            return True
        if include_deferred and item.recommended_decision == "defer":
            return True
        return False

    def _new_report_path(self):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"loop_improvement_actions_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("action report path escaped loop_improvement_action_reports/")
        return target

    def render_markdown(self, actions):
        lines = []
        a = lines.append
        a("# Loop Improvement Actions")
        a("")
        a("## Summary")
        a(f"- Generated at: {_now_iso()}")
        a(f"- Total actions: {len(actions)}")
        a(f"- Open actions: {sum(1 for x in actions if x.status in ('open', 'in_progress', 'blocked'))}")
        a(f"- Completed actions: {sum(1 for x in actions if x.status == 'completed')}")
        a(f"- Dismissed actions: {sum(1 for x in actions if x.status == 'dismissed')}")
        a("")
        self._append_section(lines, "Open Actions",
                             [x for x in actions if x.status in ("open", "in_progress", "blocked")])
        self._append_section(lines, "High Priority Actions",
                             [x for x in actions if x.priority in ("urgent", "high")])
        self._append_section(lines, "Safety/Quality Gate Actions",
                             [x for x in actions if x.target_type in ("safety_policy", "quality_gate")])
        self._append_section(lines, "Completed Actions",
                             [x for x in actions if x.status == "completed"])
        self._append_section(lines, "Dismissed Actions",
                             [x for x in actions if x.status == "dismissed"])
        a("## Next Steps")
        a("- python3 main.py --loop-improvement-actions")
        a("- python3 main.py --loop-improvement-review")
        a("- python3 main.py --loop-improvement-proposals")
        a("")
        a("## Safety Notes")
        a("- Improvement actions are manual tracking records only")
        a("- Suggested commands are not executed")
        a("- Proposals are not applied automatically")
        a("- No model calls")
        a("- No loop, job, prompt, gate, or stop-condition mutation")
        a("")
        return "\n".join(lines)

    def _append_section(self, lines, title, actions):
        lines.append(f"## {title}")
        if not actions:
            lines.append("- (none)")
            lines.append("")
            return
        for action in actions:
            lines.append(
                f"- #{action.id} [{action.priority}] {action.target_type}/"
                f"{action.target_name}: {action.title}")
            lines.append(f"  status: {action.status}")
            lines.append(f"  command: {action.suggested_next_command}")
        lines.append("")
