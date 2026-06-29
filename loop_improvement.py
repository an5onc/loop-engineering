"""Loop Improvement Engine foundation (Stage 5.0).

The improvement engine reads existing Observatory metadata and produces
reviewable improvement proposals. It never executes commands, calls models,
mutates loop definitions, mutates agent definitions, creates external jobs,
imports completions, resumes jobs, commits, or reads protected file contents.
Writes are limited to improvement metadata and optional Markdown reports under
loop_improvement_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List, Optional

import database
import observatory_action_review
import observatory_drilldown
import observatory_remediation


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "loop_improvement_reports")

TARGET_TYPES = {
    "loop_definition",
    "agent_definition",
    "prompt",
    "quality_gate",
    "stop_condition",
    "workspace_profile",
    "external_agent_flow",
    "observatory_flow",
    "documentation",
    "testing",
    "safety_policy",
    "unknown",
}
PRIORITIES = {"urgent", "high", "medium", "low"}
STATUSES = {"proposed", "accepted", "rejected", "deferred", "converted_to_action"}
SOURCE_TYPES = {"action_review", "remediation_plan", "failure_drilldown"}

NEXT_STEPS = [
    "python3 main.py --loop-improvement-plan PLAN_ID",
    "python3 main.py --loop-improvement-proposal PROPOSAL_ID",
    "python3 main.py --observatory-action-review",
    "python3 main.py --observatory-remediation",
    "python3 main.py --observatory-failures",
]


@dataclass
class LoopImprovementProposal:
    id: int
    target_type: str
    target_name: str
    title: str
    problem_summary: str
    evidence: List[str] = field(default_factory=list)
    proposed_change: str = ""
    expected_benefit: str = ""
    risk_level: str = "low"
    effort_level: str = "low"
    priority: str = "low"
    affected_loop_ids: List[int] = field(default_factory=list)
    affected_action_ids: List[int] = field(default_factory=list)
    affected_remediation_plan_ids: List[int] = field(default_factory=list)
    status: str = "proposed"
    created_at: str = ""


@dataclass
class LoopImprovementPlan:
    generated_at: str
    source_type: str
    source_id: Optional[int]
    total_proposals: int
    urgent_count: int
    high_count: int
    medium_count: int
    low_count: int
    proposals: List[LoopImprovementProposal] = field(default_factory=list)
    summary: str = ""
    next_steps: List[str] = field(default_factory=lambda: list(NEXT_STEPS))


@dataclass
class LoopImprovementMarkdownReport:
    improvement_plan_id: int
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


def proposal_to_dict(proposal):
    return asdict(proposal)


def proposal_from_dict(data):
    return LoopImprovementProposal(**data)


def proposal_from_row(row):
    return LoopImprovementProposal(
        id=row["id"],
        target_type=row["target_type"] or "unknown",
        target_name=row["target_name"] or "",
        title=row["title"] or "",
        problem_summary=row["problem_summary"] or "",
        evidence=_safe_json_loads(row["evidence_json"], []),
        proposed_change=row["proposed_change"] or "",
        expected_benefit=row["expected_benefit"] or "",
        risk_level=row["risk_level"] or "low",
        effort_level=row["effort_level"] or "low",
        priority=row["priority"] or "low",
        affected_loop_ids=_int_list(_safe_json_loads(row["affected_loop_ids_json"], [])),
        affected_action_ids=_int_list(_safe_json_loads(row["affected_action_ids_json"], [])),
        affected_remediation_plan_ids=_int_list(
            _safe_json_loads(row["affected_remediation_plan_ids_json"], [])),
        status=row["status"] or "proposed",
        created_at=row["created_at"] or "",
    )


def plan_from_row(row):
    summary = _safe_json_loads(row["summary_json"], {})
    return LoopImprovementPlan(
        generated_at=row["generated_at"],
        source_type=row["source_type"],
        source_id=row["source_id"],
        total_proposals=row["total_proposals"] or 0,
        urgent_count=row["urgent_count"] or 0,
        high_count=row["high_count"] or 0,
        medium_count=row["medium_count"] or 0,
        low_count=row["low_count"] or 0,
        proposals=[proposal_from_dict(p) for p in _safe_json_loads(row["proposals_json"], [])],
        summary=summary.get("summary", ""),
        next_steps=summary.get("next_steps", list(NEXT_STEPS)),
    )


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


class LoopImprovementEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_plan(self, source_type=None, source_id=None, priority=None,
                   target_type=None, limit=25):
        if priority and priority not in PRIORITIES:
            raise ValueError(f"unknown improvement priority '{priority}'")
        if target_type and target_type not in TARGET_TYPES:
            raise ValueError(f"unknown improvement target type '{target_type}'")
        source_type, source_id = self._resolve_source(source_type, source_id)
        proposals = self._proposals_for_source(source_type, source_id)
        proposals = self._dedupe(proposals)
        filtered = []
        for proposal in proposals:
            if priority and proposal.priority != priority:
                continue
            if target_type and proposal.target_type != target_type:
                continue
            filtered.append(proposal)
            if len(filtered) >= int(limit or 25):
                break
        for idx, proposal in enumerate(filtered, start=1):
            proposal.id = idx
        urgent = sum(1 for p in filtered if p.priority == "urgent")
        high = sum(1 for p in filtered if p.priority == "high")
        medium = sum(1 for p in filtered if p.priority == "medium")
        low = sum(1 for p in filtered if p.priority == "low")
        return LoopImprovementPlan(
            generated_at=_now_iso(),
            source_type=source_type,
            source_id=source_id,
            total_proposals=len(filtered),
            urgent_count=urgent,
            high_count=high,
            medium_count=medium,
            low_count=low,
            proposals=filtered,
            summary=f"{len(filtered)} improvement proposal(s) from {source_type}",
            next_steps=list(NEXT_STEPS),
        )

    def save_plan(self, plan, filters):
        plan_id = database.save_loop_improvement_plan(
            self.conn,
            plan.generated_at,
            plan.source_type,
            plan.source_id,
            json.dumps(filters or {}, sort_keys=True),
            json.dumps({"summary": plan.summary, "next_steps": plan.next_steps},
                       sort_keys=True),
            json.dumps([proposal_to_dict(p) for p in plan.proposals], sort_keys=True),
            plan.total_proposals,
            plan.urgent_count,
            plan.high_count,
            plan.medium_count,
            plan.low_count,
        )
        stored = []
        for proposal in plan.proposals:
            proposal.id = database.save_loop_improvement_proposal(
                self.conn,
                plan_id,
                proposal.target_type,
                proposal.target_name,
                proposal.title,
                proposal.problem_summary,
                json.dumps(proposal.evidence, sort_keys=True),
                proposal.proposed_change,
                proposal.expected_benefit,
                proposal.risk_level,
                proposal.effort_level,
                proposal.priority,
                json.dumps(proposal.affected_loop_ids, sort_keys=True),
                json.dumps(proposal.affected_action_ids, sort_keys=True),
                json.dumps(proposal.affected_remediation_plan_ids, sort_keys=True),
                proposal.status,
            )
            stored.append(proposal_to_dict(proposal))
        database.update_loop_improvement_plan_proposals(
            self.conn, plan_id, json.dumps(stored, sort_keys=True))
        return plan_id

    def save_markdown_report(self, plan_id, plan):
        content = self.render_markdown(plan, plan_id)
        path = self._new_markdown_path(plan_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_loop_improvement_markdown_report(
            self.conn, plan_id, path, "markdown", chash, nbytes)
        return LoopImprovementMarkdownReport(
            improvement_plan_id=plan_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def _resolve_source(self, source_type, source_id):
        if source_type is None:
            rows = database.list_observatory_action_reviews(self.conn, 1)
            if rows:
                return "action_review", rows[0]["id"]
            rows = database.list_observatory_remediation_plans(self.conn, 1)
            if rows:
                return "remediation_plan", rows[0]["id"]
            rows = database.list_observatory_failure_drilldowns(self.conn, 1)
            return ("failure_drilldown", rows[0]["id"] if rows else None)
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"unknown improvement source '{source_type}'")
        if source_id is not None:
            return source_type, int(source_id)
        if source_type == "action_review":
            rows = database.list_observatory_action_reviews(self.conn, 1)
        elif source_type == "remediation_plan":
            rows = database.list_observatory_remediation_plans(self.conn, 1)
        else:
            rows = database.list_observatory_failure_drilldowns(self.conn, 1)
        return source_type, (rows[0]["id"] if rows else None)

    def _proposals_for_source(self, source_type, source_id):
        if source_id is None:
            return [self._proposal(
                "observatory_flow",
                "observatory_source_data",
                "Create observatory source metadata",
                "No action review, remediation plan, or failure drilldown exists yet.",
                ["source_id is missing"],
                "Generate Observatory metadata before proposing framework improvements.",
                "Provides a stable evidence source for improvement proposals.",
                "low",
                "low",
                "low",
            )]
        if source_type == "action_review":
            return self._from_action_review(source_id)
        if source_type == "remediation_plan":
            return self._from_remediation_plan(source_id)
        if source_type == "failure_drilldown":
            return self._from_failure_drilldown(source_id)
        raise ValueError(f"unknown improvement source '{source_type}'")

    def _from_action_review(self, review_id):
        row = database.get_observatory_action_review(self.conn, review_id)
        if row is None:
            raise ValueError(f"no observatory action review {review_id}")
        report = observatory_action_review.report_from_row(row)
        proposals = []
        for item in report.top_actions:
            proposals.append(self._proposal_from_signal(
                title=item.title,
                category=item.category,
                priority=item.priority,
                problem=item.problem_summary or item.rationale,
                evidence=[item.rationale, item.suggested_command],
                recommended=item.recommended_action,
                expected="Reduce repeated Observatory action pressure.",
                risk=item.risk_level,
                effort=item.effort_level,
                loops=item.affected_loop_ids,
                actions=[item.action_id],
            ))
        return proposals

    def _from_remediation_plan(self, plan_id):
        row = database.get_observatory_remediation_plan(self.conn, plan_id)
        if row is None:
            raise ValueError(f"no observatory remediation plan {plan_id}")
        plan = observatory_remediation.plan_from_row(row)
        proposals = []
        for item in plan.items:
            proposals.append(self._proposal_from_signal(
                title=item.title,
                category=item.category,
                priority=item.priority,
                problem=item.problem_summary,
                evidence=[item.evidence, item.suggested_command],
                recommended=item.recommended_action,
                expected=item.expected_impact,
                risk=item.risk_level,
                effort=item.effort_level,
                loops=item.affected_loop_ids,
                remediation_plans=[plan_id],
            ))
        return proposals

    def _from_failure_drilldown(self, drilldown_id):
        row = database.get_observatory_failure_drilldown(self.conn, drilldown_id)
        if row is None:
            raise ValueError(f"no observatory failure drilldown {drilldown_id}")
        report = observatory_drilldown.report_from_row(row)
        proposals = []
        for cluster in report.clusters:
            proposals.append(self._proposal_from_signal(
                title=f"Improve handling for {cluster.cluster_key}",
                category=cluster.cluster_key,
                priority=self._priority_for_text(cluster.cluster_key, cluster.representative_reason),
                problem=cluster.representative_reason or cluster.cluster_key,
                evidence=[
                    f"count={cluster.count}",
                    f"loop_ids={cluster.loop_ids}",
                    cluster.recommended_action,
                ],
                recommended="Create a reusable framework improvement for this failure cluster.",
                expected="Reduce repeated failures in future loops.",
                risk="medium",
                effort="medium",
                loops=cluster.loop_ids,
            ))
        if not proposals:
            for item in report.items:
                proposals.append(self._proposal_from_signal(
                    title=f"Improve handling for loop {item.loop_id}",
                    category=item.failure_category,
                    priority=self._priority_for_text(item.failure_category, item.root_cause_hint),
                    problem=item.root_cause_hint,
                    evidence=[item.stop_reason, item.recommended_action],
                    recommended="Create a reusable framework improvement for this failure.",
                    expected="Reduce repeated failures in future loops.",
                    risk="medium",
                    effort="medium",
                    loops=[item.loop_id],
                ))
        return proposals

    def _proposal_from_signal(self, title, category, priority, problem, evidence,
                              recommended, expected, risk, effort, loops=None,
                              actions=None, remediation_plans=None):
        text = " ".join([title or "", category or "", problem or "", " ".join(evidence or [])])
        lower = text.lower()
        target_type, target_name, proposed_change = self._target_for_text(
            lower, category, recommended)
        return self._proposal(
            target_type,
            target_name,
            self._title_for_target(target_type, title),
            problem or title,
            [e for e in (evidence or []) if e],
            proposed_change,
            expected or "Improve Loop Engineering reliability.",
            risk or self._risk_for_priority(priority, lower),
            effort or "medium",
            self._priority_for_text(priority, lower),
            loops=loops,
            actions=actions,
            remediation_plans=remediation_plans,
        )

    def _target_for_text(self, lower, category, recommended):
        if _has_any(lower, ["protected content", "command execution", "safety bypass",
                           "reviewer bypass", "workspace validation bypass",
                           "workspace_violation", "workspace safety"]):
            return ("safety_policy", "workspace_and_command_safety",
                    "Strengthen the documented safety policy and validation checks.")
        if _has_any(lower, ["quality gate", "quality_gate", "files_written", "gate failures"]):
            return ("quality_gate", "quality_gate_review",
                    "Refine quality gate criteria, evidence, and loop-specific expectations.")
        if _has_any(lower, ["reviewer inconsistency", "reviewer_inconsistent",
                           "review inconsistent", "reviewer output"]):
            return ("prompt", "reviewer_prompt",
                    "Clarify reviewer prompt expectations and contradiction handling.")
        if _has_any(lower, ["external job", "external_agent", "handoff", "external queue"]):
            return ("external_agent_flow", "external_agent_handoff_flow",
                    "Improve external-agent queue, handoff, and stale-job handling.")
        if _has_any(lower, ["documentation", "readme", "docs"]):
            return ("documentation", "operator_documentation",
                    "Update documentation and examples for the affected workflow.")
        if _has_any(lower, ["test failure", "testing", "unittest", "pytest"]):
            return ("testing", "test_coverage",
                    "Add or adjust regression coverage for the recurring behavior.")
        if _has_any(lower, ["stop condition", "stop_condition"]):
            return ("stop_condition", "stop_condition_review",
                    "Review stop condition classification and operator guidance.")
        if category in ("observability", "reporting"):
            return ("observatory_flow", "observatory_reporting",
                    "Improve Observatory metadata and report clarity.")
        return ("unknown", "manual_triage", recommended or
                "Review the evidence and design a safe manual improvement.")

    def _priority_for_text(self, priority, text):
        lower = f"{priority or ''} {text or ''}".lower()
        if _has_any(lower, ["safety bypass", "protected content", "command execution",
                           "reviewer bypass", "workspace validation bypass"]):
            return "urgent"
        if (priority or "").lower() == "urgent":
            return "urgent"
        if _has_any(lower, ["blocked loops", "quality gate", "reviewer inconsistency",
                           "external-agent failure", "external_agent_failed",
                           "external job"]) or (priority or "").lower() == "high":
            return "high"
        if _has_any(lower, ["model invalid", "invalid output", "missing project intelligence",
                           "context", "approval friction"]):
            return "medium"
        if (priority or "").lower() in PRIORITIES:
            return (priority or "").lower()
        return "low"

    def _risk_for_priority(self, priority, text):
        if self._priority_for_text(priority, text) == "urgent":
            return "high"
        if self._priority_for_text(priority, text) == "high":
            return "medium"
        return "low"

    def _title_for_target(self, target_type, title):
        label = target_type.replace("_", " ")
        return f"Improve {label}: {title}"

    def _proposal(self, target_type, target_name, title, problem, evidence,
                  change, benefit, risk, effort, priority, loops=None,
                  actions=None, remediation_plans=None):
        return LoopImprovementProposal(
            id=0,
            target_type=target_type if target_type in TARGET_TYPES else "unknown",
            target_name=target_name or "manual_triage",
            title=title,
            problem_summary=problem,
            evidence=list(evidence or []),
            proposed_change=change,
            expected_benefit=benefit,
            risk_level=risk if risk in ("high", "medium", "low") else "low",
            effort_level=effort if effort in ("high", "medium", "low") else "medium",
            priority=priority if priority in PRIORITIES else "low",
            affected_loop_ids=_int_list(loops or []),
            affected_action_ids=_int_list(actions or []),
            affected_remediation_plan_ids=_int_list(remediation_plans or []),
            status="proposed",
            created_at=_now_iso(),
        )

    def _dedupe(self, proposals):
        seen = set()
        unique = []
        for proposal in proposals:
            key = (proposal.target_type, proposal.target_name, proposal.title)
            if key in seen:
                continue
            seen.add(key)
            unique.append(proposal)
        priority_rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
        unique.sort(key=lambda p: (priority_rank.get(p.priority, 4), p.target_type, p.title))
        return unique

    def _new_markdown_path(self, plan_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"loop_improvements_{int(plan_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("improvement report path escaped loop_improvement_reports/")
        return target

    def render_markdown(self, plan, plan_id=None):
        lines = []
        a = lines.append
        a("# Loop Improvement Plan")
        a("")
        a("## Summary")
        if plan_id is not None:
            a(f"- Plan ID: {plan_id}")
        a(f"- Generated at: {plan.generated_at}")
        a(f"- Source type: {plan.source_type}")
        a(f"- Source ID: {plan.source_id}")
        a(f"- Total proposals: {plan.total_proposals}")
        a(f"- Urgent: {plan.urgent_count}")
        a(f"- High: {plan.high_count}")
        a(f"- Medium: {plan.medium_count}")
        a(f"- Low: {plan.low_count}")
        a("")
        a("## Proposals")
        if not plan.proposals:
            a("- (none)")
        for proposal in plan.proposals:
            a(f"- ID: {proposal.id}")
            a(f"  Priority: {proposal.priority}")
            a(f"  Target type: {proposal.target_type}")
            a(f"  Target name: {proposal.target_name}")
            a(f"  Title: {proposal.title}")
            a(f"  Problem: {proposal.problem_summary}")
            a(f"  Proposed change: {proposal.proposed_change}")
            a(f"  Expected benefit: {proposal.expected_benefit}")
            a(f"  Risk: {proposal.risk_level}")
            a(f"  Effort: {proposal.effort_level}")
            a(f"  Loops: {proposal.affected_loop_ids or []}")
            a(f"  Actions: {proposal.affected_action_ids or []}")
            a(f"  Remediation plans: {proposal.affected_remediation_plan_ids or []}")
            a(f"  Status: {proposal.status}")
        a("")
        a("## Evidence")
        if not plan.proposals:
            a("- (none)")
        for proposal in plan.proposals:
            evidence = "; ".join(proposal.evidence) if proposal.evidence else "(none)"
            a(f"- proposal {proposal.id}: {evidence}")
        a("")
        a("## Next Steps")
        for step in plan.next_steps:
            a(f"- {step}")
        a("")
        a("## Safety Notes")
        a("- Improvement planning only reads SQLite Observatory metadata")
        a("- Proposals are not applied automatically")
        a("- No model calls")
        a("- No command execution")
        a("- No loop, agent, prompt, gate, stop-condition, or job mutation")
        a("- Markdown reports are written only under loop_improvement_reports/")
        a("")
        return "\n".join(lines)


def _has_any(text, needles):
    return any(needle in text for needle in needles)


def _int_list(values):
    out = []
    for value in values:
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            continue
    return out
