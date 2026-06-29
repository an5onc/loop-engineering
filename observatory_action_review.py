"""Review and prioritization for Observatory action items (Stage 4.6).

Action review reads action metadata and produces deterministic priority and
grouping recommendations. It never executes suggested commands, calls models,
mutates loops/jobs, imports completions, resumes work, commits, or reads
protected file contents. Writes are limited to review metadata and optional
Markdown reports under observatory_action_review_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database
import observatory_actions


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "observatory_action_review_reports")
GROUP_BY = {"category", "priority", "status", "risk"}


@dataclass
class ObservatoryActionReviewItem:
    action_id: int
    source_plan_id: int
    title: str
    category: str
    priority: str
    status: str
    risk_level: str
    effort_level: str
    affected_loop_ids: List[int] = field(default_factory=list)
    affected_job_ids: List[int] = field(default_factory=list)
    suggested_command: str = ""
    problem_summary: str = ""
    recommended_action: str = ""
    review_score: int = 0
    urgency_score: int = 0
    impact_score: int = 0
    effort_score: int = 0
    risk_score: int = 0
    rationale: str = ""
    next_step: str = ""


@dataclass
class ObservatoryActionReviewGroup:
    group_key: str
    group_type: str
    count: int
    action_ids: List[int] = field(default_factory=list)
    highest_priority: str = "low"
    common_category: str = ""
    summary: str = ""
    recommended_next_step: str = ""


@dataclass
class ObservatoryActionReviewReport:
    generated_at: str
    total_actions_reviewed: int
    filters_json: str
    top_actions: List[ObservatoryActionReviewItem] = field(default_factory=list)
    groups: List[ObservatoryActionReviewGroup] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)


@dataclass
class ObservatoryActionReviewMarkdownReport:
    action_review_id: int
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


def item_to_dict(item):
    return asdict(item)


def group_to_dict(group):
    return asdict(group)


def item_from_dict(data):
    return ObservatoryActionReviewItem(**data)


def group_from_dict(data):
    return ObservatoryActionReviewGroup(**data)


def report_from_row(row):
    return ObservatoryActionReviewReport(
        generated_at=row["generated_at"],
        total_actions_reviewed=row["total_actions_reviewed"] or 0,
        filters_json=row["filters_json"] or "{}",
        top_actions=[item_from_dict(i) for i in _safe_json_loads(row["top_actions_json"], [])],
        groups=[group_from_dict(g) for g in _safe_json_loads(row["groups_json"], [])],
        recommendations=_safe_json_loads(row["recommendations_json"], []),
        next_steps=_safe_json_loads(row["next_steps_json"], []),
    )


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


class ObservatoryActionReviewEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self, status="open", priority=None, category=None,
                     group_by="category", limit=25):
        if group_by not in GROUP_BY:
            raise ValueError(f"unknown action review group '{group_by}'")
        rows = database.list_observatory_action_items(
            self.conn,
            status=status,
            priority=priority,
            category=category,
            limit=int(limit or 25),
        )
        actions = [observatory_actions._row_to_action(row) for row in rows]
        reviewed = [self._review_action(action) for action in actions]
        reviewed.sort(key=lambda item: (-item.review_score, item.action_id))
        groups = self._groups(reviewed, group_by)
        recs, next_steps = self._recommendations(reviewed)
        filters = {
            "status": status,
            "priority": priority,
            "category": category,
            "group_by": group_by,
            "limit": int(limit or 25),
        }
        return ObservatoryActionReviewReport(
            generated_at=_now_iso(),
            total_actions_reviewed=len(reviewed),
            filters_json=json.dumps(filters, sort_keys=True),
            top_actions=reviewed,
            groups=groups,
            recommendations=recs,
            next_steps=next_steps,
        )

    def save_review(self, report, group_by="category"):
        return database.save_observatory_action_review(
            self.conn,
            report.generated_at,
            report.filters_json,
            group_by,
            report.total_actions_reviewed,
            json.dumps([item_to_dict(i) for i in report.top_actions], sort_keys=True),
            json.dumps([group_to_dict(g) for g in report.groups], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
            json.dumps(report.next_steps, sort_keys=True),
        )

    def save_markdown_report(self, review_id, report):
        content = self.render_markdown(report, review_id)
        path = self._new_report_path(review_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_observatory_action_review_markdown_report(
            self.conn, review_id, path, "markdown", chash, nbytes)
        return ObservatoryActionReviewMarkdownReport(
            action_review_id=review_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def _review_action(self, action):
        priority_score = {"urgent": 50, "high": 38, "medium": 24, "low": 10}.get(
            action.priority, 8)
        category_score = {
            "safety": 34,
            "reliability": 26,
            "external_agent_health": 26,
            "external_agent_queue": 22,
            "testing": 16,
            "documentation": 6,
        }.get(action.category, 10)
        status_score = {
            "blocked": 28,
            "open": 18,
            "in_progress": 14,
            "completed": -45,
            "dismissed": -55,
        }.get(action.status, 0)
        risk_score = {"high": 18, "medium": 10, "low": 4}.get(action.risk_level, 4)
        effort_score = {"low": 12, "medium": 7, "high": 2}.get(action.effort_level, 5)
        impact_score = min(20, len(action.affected_loop_ids) * 3 + len(action.affected_job_ids) * 4)
        command_score = 6 if action.suggested_command else -8
        review_score = (priority_score + category_score + status_score + risk_score
                        + effort_score + impact_score + command_score)
        rationale_parts = [
            f"priority={action.priority}",
            f"category={action.category}",
            f"status={action.status}",
        ]
        if action.category in ("safety", "reliability", "external_agent_health"):
            rationale_parts.append(f"{action.category} action gets elevated score")
        if action.status == "blocked":
            rationale_parts.append("blocked action needs human review")
        if action.status in ("completed", "dismissed"):
            rationale_parts.append("completed/dismissed actions rank lower")
        next_step = f"python3 main.py --observatory-action {action.id}"
        return ObservatoryActionReviewItem(
            action_id=action.id,
            source_plan_id=action.source_plan_id,
            title=action.title,
            category=action.category,
            priority=action.priority,
            status=action.status,
            risk_level=action.risk_level,
            effort_level=action.effort_level,
            affected_loop_ids=action.affected_loop_ids,
            affected_job_ids=action.affected_job_ids,
            suggested_command=action.suggested_command,
            problem_summary=action.problem_summary,
            recommended_action=action.recommended_action,
            review_score=review_score,
            urgency_score=priority_score + status_score,
            impact_score=impact_score,
            effort_score=effort_score,
            risk_score=risk_score,
            rationale="; ".join(rationale_parts),
            next_step=next_step,
        )

    def _groups(self, items, group_by):
        grouped = {}
        for item in items:
            key = self._group_key(item, group_by)
            grouped.setdefault(key, []).append(item)
        out = []
        for key, vals in grouped.items():
            vals.sort(key=lambda item: (-item.review_score, item.action_id))
            out.append(ObservatoryActionReviewGroup(
                group_key=key,
                group_type=group_by,
                count=len(vals),
                action_ids=[v.action_id for v in vals[:10]],
                highest_priority=self._highest_priority(vals),
                common_category=self._common_category(vals),
                summary=f"{len(vals)} action(s) grouped by {group_by}={key}",
                recommended_next_step=vals[0].next_step,
            ))
        out.sort(key=lambda group: (-group.count, group.group_key))
        return out

    def _group_key(self, item, group_by):
        if group_by == "category":
            return item.category or "(unknown)"
        if group_by == "priority":
            return item.priority or "(unknown)"
        if group_by == "status":
            return item.status or "(unknown)"
        if group_by == "risk":
            return item.risk_level or "(unknown)"
        return "(unknown)"

    def _highest_priority(self, items):
        order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
        return sorted((i.priority for i in items), key=lambda p: order.get(p, 9))[0]

    def _common_category(self, items):
        counts = {}
        for item in items:
            counts[item.category] = counts.get(item.category, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    def _recommendations(self, items):
        recs = []
        next_steps = []
        for item in items[:3]:
            recs.extend([
                f"python3 main.py --observatory-action {item.action_id}",
                f"python3 main.py --set-observatory-action-status {item.action_id} in_progress",
                f"python3 main.py --set-observatory-action-status {item.action_id} completed",
                f"python3 main.py --set-observatory-action-notes {item.action_id} \"notes\"",
            ])
            next_steps.append(f"python3 main.py --observatory-action {item.action_id}")
        seen = []
        for cmd in recs:
            if cmd not in seen:
                seen.append(cmd)
        return seen, next_steps

    def _new_report_path(self, review_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"observatory_action_review_{int(review_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("action review report path escaped observatory_action_review_reports/")
        return target

    def render_markdown(self, report, review_id=None):
        lines = []
        a = lines.append
        a("# Observatory Action Review")
        a("")
        a("## Summary")
        if review_id is not None:
            a(f"- Review ID: {review_id}")
        a(f"- Generated at: {report.generated_at}")
        a(f"- Actions reviewed: {report.total_actions_reviewed}")
        a(f"- Filters: {report.filters_json}")
        a("")
        a("## Top Actions")
        if not report.top_actions:
            a("- (none)")
        for item in report.top_actions:
            a(f"- #{item.action_id} score={item.review_score} "
              f"[{item.priority}] {item.category} status={item.status}")
            a(f"  next: {item.next_step}")
            a(f"  command: {item.suggested_command}")
        a("")
        a("## Groups")
        if not report.groups:
            a("- (none)")
        for group in report.groups:
            a(f"- {group.group_type}={group.group_key} count={group.count} "
              f"actions={group.action_ids}")
            a(f"  next: {group.recommended_next_step}")
        a("")
        a("## Recommendations")
        for rec in report.recommendations:
            a(f"- {rec}")
        a("")
        a("## Next Steps")
        for step in report.next_steps:
            a(f"- {step}")
        a("")
        a("## Safety Notes")
        a("- Action review only reads action metadata")
        a("- Suggested commands are not executed")
        a("- No model calls")
        a("- No command execution")
        a("- No job or loop mutation")
        a("")
        return "\n".join(lines)
