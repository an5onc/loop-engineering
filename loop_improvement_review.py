"""Loop Improvement Proposal Review (Stage 5.1).

This module reviews persisted improvement proposals deterministically. It never
executes commands, calls models, creates loops/jobs, applies proposals, mutates
framework definitions, commits, or reads protected file contents. Writes are
limited to review metadata and optional Markdown reports under
loop_improvement_review_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database
import loop_improvement


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "loop_improvement_review_reports")
GROUP_BY = {"target_type", "priority", "status", "risk"}
DECISIONS = {"accept", "defer", "reject", "convert_to_action", "needs_more_evidence"}


@dataclass
class LoopImprovementReviewItem:
    proposal_id: int
    plan_id: int
    target_type: str
    target_name: str
    title: str
    priority: str
    status: str
    risk_level: str
    effort_level: str
    affected_loop_ids: List[int] = field(default_factory=list)
    affected_action_ids: List[int] = field(default_factory=list)
    affected_remediation_plan_ids: List[int] = field(default_factory=list)
    problem_summary: str = ""
    proposed_change: str = ""
    expected_benefit: str = ""
    review_score: int = 0
    urgency_score: int = 0
    impact_score: int = 0
    effort_score: int = 0
    risk_score: int = 0
    rationale: str = ""
    recommended_decision: str = "needs_more_evidence"
    suggested_next_command: str = ""


@dataclass
class LoopImprovementReviewGroup:
    group_key: str
    group_type: str
    count: int
    proposal_ids: List[int] = field(default_factory=list)
    highest_priority: str = "low"
    common_target_type: str = ""
    summary: str = ""
    recommended_next_step: str = ""


@dataclass
class LoopImprovementReviewReport:
    generated_at: str
    total_proposals_reviewed: int
    filters_json: str
    top_proposals: List[LoopImprovementReviewItem] = field(default_factory=list)
    groups: List[LoopImprovementReviewGroup] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)


@dataclass
class LoopImprovementReviewMarkdownReport:
    improvement_review_id: int
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
    return LoopImprovementReviewItem(**data)


def group_from_dict(data):
    return LoopImprovementReviewGroup(**data)


def report_from_row(row):
    return LoopImprovementReviewReport(
        generated_at=row["generated_at"],
        total_proposals_reviewed=row["total_proposals_reviewed"] or 0,
        filters_json=row["filters_json"] or "{}",
        top_proposals=[
            item_from_dict(i) for i in _safe_json_loads(row["top_proposals_json"], [])
        ],
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


class LoopImprovementReviewEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self, status="proposed", priority=None, target_type=None,
                     group_by="target_type", limit=25):
        if group_by not in GROUP_BY:
            raise ValueError(f"unknown improvement review group '{group_by}'")
        if priority and priority not in loop_improvement.PRIORITIES:
            raise ValueError(f"unknown improvement priority '{priority}'")
        if target_type and target_type not in loop_improvement.TARGET_TYPES:
            raise ValueError(f"unknown improvement target type '{target_type}'")
        rows = database.list_loop_improvement_proposals(
            self.conn,
            status=status,
            priority=priority,
            target_type=target_type,
            limit=int(limit or 25),
        )
        reviewed = [self._review_row(row) for row in rows]
        reviewed.sort(key=lambda item: (-item.review_score, item.proposal_id))
        groups = self._groups(reviewed, group_by)
        recommendations, next_steps = self._recommendations(reviewed)
        filters = {
            "status": status,
            "priority": priority,
            "target_type": target_type,
            "group_by": group_by,
            "limit": int(limit or 25),
        }
        return LoopImprovementReviewReport(
            generated_at=_now_iso(),
            total_proposals_reviewed=len(reviewed),
            filters_json=json.dumps(filters, sort_keys=True),
            top_proposals=reviewed,
            groups=groups,
            recommendations=recommendations,
            next_steps=next_steps,
        )

    def save_review(self, report, group_by="target_type"):
        return database.save_loop_improvement_review(
            self.conn,
            report.generated_at,
            report.filters_json,
            group_by,
            report.total_proposals_reviewed,
            json.dumps([item_to_dict(i) for i in report.top_proposals], sort_keys=True),
            json.dumps([group_to_dict(g) for g in report.groups], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
            json.dumps(report.next_steps, sort_keys=True),
        )

    def save_markdown_report(self, review_id, report):
        content = self.render_markdown(report, review_id)
        path = self._new_markdown_path(review_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_loop_improvement_review_markdown_report(
            self.conn, review_id, path, "markdown", chash, nbytes)
        return LoopImprovementReviewMarkdownReport(
            improvement_review_id=review_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def _review_row(self, row):
        proposal = loop_improvement.proposal_from_row(row)
        priority_score = {"urgent": 58, "high": 42, "medium": 24, "low": 10}.get(
            proposal.priority, 8)
        target_score = {
            "safety_policy": 34,
            "quality_gate": 28,
            "stop_condition": 24,
            "prompt": 23,
            "testing": 20,
            "external_agent_flow": 22,
            "workspace_profile": 18,
            "observatory_flow": 12,
            "agent_definition": 12,
            "loop_definition": 12,
            "documentation": 4,
            "unknown": 2,
        }.get(proposal.target_type, 2)
        risk_score = {"high": 18, "medium": 10, "low": 4}.get(proposal.risk_level, 4)
        effort_score = {"low": 16, "medium": 8, "high": 1}.get(proposal.effort_level, 5)
        status_score = {
            "proposed": 20,
            "accepted": 8,
            "deferred": -8,
            "rejected": -70,
            "converted_to_action": -55,
        }.get(proposal.status, 0)
        impact_score = min(
            28,
            len(proposal.affected_loop_ids) * 3 +
            len(proposal.affected_action_ids) * 4 +
            len(proposal.affected_remediation_plan_ids) * 3,
        )
        text = " ".join([
            proposal.title,
            proposal.problem_summary,
            proposal.proposed_change,
            " ".join(proposal.evidence),
        ]).lower()
        if proposal.target_type == "external_agent_flow" and _has_any(
                text, ["stale", "blocked", "failed", "waiting"]):
            target_score += 8
        if proposal.target_type == "prompt" and _has_any(
                text, ["reviewer", "inconsistent", "contradictory"]):
            target_score += 8
        if proposal.target_type in ("quality_gate", "stop_condition") and _has_any(
                text, ["repeat", "recur", "failed", "failure"]):
            target_score += 6
        review_score = (priority_score + target_score + risk_score +
                        effort_score + status_score + impact_score)
        decision = self._recommended_decision(proposal, impact_score)
        rationale_parts = [
            f"priority={proposal.priority}",
            f"target={proposal.target_type}",
            f"status={proposal.status}",
            f"risk={proposal.risk_level}",
            f"effort={proposal.effort_level}",
        ]
        if proposal.target_type in ("safety_policy", "quality_gate", "stop_condition",
                                    "prompt", "testing", "external_agent_flow"):
            rationale_parts.append(f"{proposal.target_type} target gets elevated score")
        if proposal.status in ("rejected", "converted_to_action"):
            rationale_parts.append("already terminal or rejected status ranks lower")
        if impact_score >= 12:
            rationale_parts.append("many affected loops/actions increase impact")
        return LoopImprovementReviewItem(
            proposal_id=proposal.id,
            plan_id=row["plan_id"],
            target_type=proposal.target_type,
            target_name=proposal.target_name,
            title=proposal.title,
            priority=proposal.priority,
            status=proposal.status,
            risk_level=proposal.risk_level,
            effort_level=proposal.effort_level,
            affected_loop_ids=proposal.affected_loop_ids,
            affected_action_ids=proposal.affected_action_ids,
            affected_remediation_plan_ids=proposal.affected_remediation_plan_ids,
            problem_summary=proposal.problem_summary,
            proposed_change=proposal.proposed_change,
            expected_benefit=proposal.expected_benefit,
            review_score=review_score,
            urgency_score=priority_score + status_score,
            impact_score=impact_score,
            effort_score=effort_score,
            risk_score=risk_score,
            rationale="; ".join(rationale_parts),
            recommended_decision=decision,
            suggested_next_command=(
                f"python3 main.py --loop-improvement-proposal {proposal.id}"),
        )

    def _recommended_decision(self, proposal, impact_score):
        if proposal.status == "rejected":
            return "reject"
        if proposal.status == "converted_to_action":
            return "defer"
        if proposal.status == "deferred":
            return "needs_more_evidence"
        if proposal.target_type == "safety_policy" and proposal.priority in ("urgent", "high"):
            return "convert_to_action" if proposal.risk_level == "high" else "accept"
        if impact_score >= 12 and proposal.effort_level == "low":
            return "accept"
        if proposal.priority in ("urgent", "high") and proposal.effort_level == "low":
            return "accept"
        if proposal.risk_level == "high" and proposal.effort_level == "high":
            return "needs_more_evidence"
        if not proposal.evidence:
            return "defer"
        return "defer" if proposal.priority == "low" else "accept"

    def _groups(self, items, group_by):
        groups = {}
        for item in items:
            key = self._group_key(item, group_by)
            groups.setdefault(key, []).append(item)
        out = []
        for key, vals in groups.items():
            vals.sort(key=lambda item: (-item.review_score, item.proposal_id))
            out.append(LoopImprovementReviewGroup(
                group_key=key,
                group_type=group_by,
                count=len(vals),
                proposal_ids=[v.proposal_id for v in vals[:10]],
                highest_priority=self._highest_priority(vals),
                common_target_type=self._common_target(vals),
                summary=f"{len(vals)} proposal(s) grouped by {group_by}={key}",
                recommended_next_step=(
                    f"python3 main.py --loop-improvement-proposal {vals[0].proposal_id}"),
            ))
        out.sort(key=lambda g: (-g.count, _priority_sort(g.highest_priority), g.group_key))
        return out

    def _group_key(self, item, group_by):
        if group_by == "target_type":
            return item.target_type
        if group_by == "priority":
            return item.priority
        if group_by == "status":
            return item.status
        if group_by == "risk":
            return item.risk_level
        return "unknown"

    def _highest_priority(self, items):
        return sorted([i.priority for i in items], key=_priority_sort)[0] if items else "low"

    def _common_target(self, items):
        counts = {}
        for item in items:
            counts[item.target_type] = counts.get(item.target_type, 0) + 1
        if not counts:
            return ""
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    def _recommendations(self, items):
        recs = []
        next_steps = []
        for item in items[:3]:
            inspect = f"python3 main.py --loop-improvement-proposal {item.proposal_id}"
            accept = f"python3 main.py --set-loop-improvement-status {item.proposal_id} accepted"
            defer = f"python3 main.py --set-loop-improvement-status {item.proposal_id} deferred"
            reject = f"python3 main.py --set-loop-improvement-status {item.proposal_id} rejected"
            for cmd in (inspect, accept, defer, reject):
                if cmd not in recs:
                    recs.append(cmd)
            if inspect not in next_steps:
                next_steps.append(inspect)
        recs.append("python3 main.py --create-loop-improvement-actions REVIEW_ID")
        return recs, next_steps

    def _new_markdown_path(self, review_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"loop_improvement_review_{int(review_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError(
                "improvement review report path escaped loop_improvement_review_reports/")
        return target

    def render_markdown(self, report, review_id=None):
        lines = []
        a = lines.append
        a("# Loop Improvement Proposal Review")
        a("")
        a("## Summary")
        if review_id is not None:
            a(f"- Review ID: {review_id}")
        a(f"- Generated at: {report.generated_at}")
        a(f"- Proposals reviewed: {report.total_proposals_reviewed}")
        a(f"- Filters: {report.filters_json}")
        a("")
        a("## Top Proposals")
        if not report.top_proposals:
            a("- (none)")
        for item in report.top_proposals:
            a(f"- proposal #{item.proposal_id} plan={item.plan_id} "
              f"score={item.review_score} decision={item.recommended_decision}")
            a(f"  priority: {item.priority}")
            a(f"  target: {item.target_type}/{item.target_name}")
            a(f"  status: {item.status}")
            a(f"  title: {item.title}")
            a(f"  problem: {item.problem_summary}")
            a(f"  change: {item.proposed_change}")
            a(f"  benefit: {item.expected_benefit}")
            a(f"  rationale: {item.rationale}")
            a(f"  command: {item.suggested_next_command}")
        a("")
        a("## Groups")
        if not report.groups:
            a("- (none)")
        for group in report.groups:
            a(f"- {group.group_type}: {group.group_key} count={group.count} "
              f"proposals={group.proposal_ids}")
            a(f"  highest priority: {group.highest_priority}")
            a(f"  summary: {group.summary}")
            a(f"  next: {group.recommended_next_step}")
        a("")
        a("## Recommendations")
        for cmd in report.recommendations:
            a(f"- {cmd}")
        a("")
        a("## Next Steps")
        for cmd in report.next_steps:
            a(f"- {cmd}")
        a("")
        a("## Safety Notes")
        a("- Improvement review only reads persisted improvement proposal metadata")
        a("- Suggested commands are not executed")
        a("- Proposals are not applied automatically")
        a("- No model calls")
        a("- No command execution")
        a("- No loop, job, prompt, gate, or stop-condition mutation")
        a("- Markdown reports are written only under loop_improvement_review_reports/")
        a("")
        return "\n".join(lines)


def _has_any(text, needles):
    return any(needle in text for needle in needles)


def _priority_sort(priority):
    return {"urgent": 0, "high": 1, "medium": 2, "low": 3}.get(priority, 4)
