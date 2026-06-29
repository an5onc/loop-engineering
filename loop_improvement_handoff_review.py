"""Loop Improvement Handoff Review (Stage 5.4).

This deterministic review layer inspects saved loop-improvement handoff metadata
before any handoff is used for manual execution. It never executes commands,
calls models, creates loops/jobs, mutates handoffs, or reads protected file
contents. Writes are limited to review metadata and optional Markdown reports
under loop_improvement_handoff_review_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database
import loop_improvement_handoff


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PACKETS_DIR = loop_improvement_handoff.PACKETS_DIR
REPORTS_DIR = os.path.join(PROJECT_ROOT, "loop_improvement_handoff_review_reports")
GROUP_BY = {"status", "type", "implementation_scope", "target_type", "workspace"}


@dataclass
class LoopImprovementHandoffReviewItem:
    handoff_id: int
    action_id: int
    source_review_id: int
    source_proposal_id: int
    source_plan_id: int
    handoff_type: str
    status: str
    implementation_scope: str
    target_type: str
    target_name: str
    target_loop_type: str
    target_workspace: str
    external_coder: str
    created_loop_id: int = None
    created_external_job_id: int = None
    packet_path: str = ""
    generated_task_preview: str = ""
    safety_notes: List[str] = field(default_factory=list)
    review_status: str = "unknown"
    review_score: int = 0
    risk_level: str = "low"
    rationale: str = ""
    recommended_decision: str = "needs_more_evidence"
    recommended_next_command: str = ""
    created_at: str = ""


@dataclass
class LoopImprovementHandoffReviewGroup:
    group_key: str
    group_type: str
    count: int
    handoff_ids: List[int] = field(default_factory=list)
    highest_risk: str = "low"
    summary: str = ""
    recommended_next_step: str = ""


@dataclass
class LoopImprovementHandoffReviewReport:
    generated_at: str
    total_handoffs_reviewed: int
    filters_json: str
    groups: List[LoopImprovementHandoffReviewGroup] = field(default_factory=list)
    items: List[LoopImprovementHandoffReviewItem] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)


@dataclass
class LoopImprovementHandoffReviewMarkdownReport:
    handoff_review_id: int
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
    return LoopImprovementHandoffReviewItem(**data)


def group_from_dict(data):
    return LoopImprovementHandoffReviewGroup(**data)


def report_from_row(row):
    return LoopImprovementHandoffReviewReport(
        generated_at=row["generated_at"],
        total_handoffs_reviewed=row["total_handoffs_reviewed"] or 0,
        filters_json=row["filters_json"] or "{}",
        groups=[
            group_from_dict(g) for g in _safe_json_loads(row["groups_json"], [])
        ],
        items=[item_from_dict(i) for i in _safe_json_loads(row["items_json"], [])],
        recommendations=_safe_json_loads(row["recommendations_json"], []),
        next_steps=_safe_json_loads(row["next_steps_json"], []),
    )


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


def _packet_path_safe(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(PACKETS_DIR)
    return target != base and target.startswith(base + os.sep)


class LoopImprovementHandoffReviewEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self, status=None, handoff_type=None,
                     implementation_scope=None, target_type=None,
                     workspace=None, external_coder=None, group_by="status",
                     limit=25):
        if group_by not in GROUP_BY:
            raise ValueError(f"unknown loop improvement handoff review group '{group_by}'")
        rows = database.list_loop_improvement_handoffs(self.conn, int(limit or 25))
        items = [self._review_row(row) for row in rows]
        filtered = []
        for item in items:
            if status and item.review_status != status:
                continue
            if handoff_type and item.handoff_type != handoff_type:
                continue
            if implementation_scope and item.implementation_scope != implementation_scope:
                continue
            if target_type and item.target_type != target_type:
                continue
            if workspace and item.target_workspace != workspace:
                continue
            if external_coder and item.external_coder != external_coder:
                continue
            filtered.append(item)
        filtered.sort(key=lambda item: (-item.review_score, item.handoff_id))
        groups = self._groups(filtered, group_by)
        recommendations, next_steps = self._recommendations(filtered)
        filters = {
            "status": status,
            "type": handoff_type,
            "implementation_scope": implementation_scope,
            "target_type": target_type,
            "workspace": workspace,
            "external_coder": external_coder,
            "group_by": group_by,
            "limit": int(limit or 25),
        }
        return LoopImprovementHandoffReviewReport(
            generated_at=_now_iso(),
            total_handoffs_reviewed=len(filtered),
            filters_json=json.dumps(filters, sort_keys=True),
            groups=groups,
            items=filtered,
            recommendations=recommendations,
            next_steps=next_steps,
        )

    def save_review(self, report, group_by="status"):
        return database.save_loop_improvement_handoff_review(
            self.conn,
            report.generated_at,
            report.filters_json,
            group_by,
            report.total_handoffs_reviewed,
            json.dumps([group_to_dict(g) for g in report.groups], sort_keys=True),
            json.dumps([item_to_dict(i) for i in report.items], sort_keys=True),
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
        database.save_loop_improvement_handoff_review_markdown_report(
            self.conn, review_id, path, "markdown", chash, nbytes)
        return LoopImprovementHandoffReviewMarkdownReport(
            handoff_review_id=review_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def _review_row(self, row):
        handoff = loop_improvement_handoff.handoff_from_row(row)
        review_status, rationale_parts = self._classify(handoff)
        risk_level = self._risk_for(review_status)
        score = self._score(handoff, review_status, risk_level)
        return LoopImprovementHandoffReviewItem(
            handoff_id=handoff.id,
            action_id=handoff.action_id,
            source_review_id=handoff.source_review_id,
            source_proposal_id=handoff.source_proposal_id,
            source_plan_id=handoff.source_plan_id,
            handoff_type=handoff.handoff_type,
            status=handoff.status,
            implementation_scope=handoff.implementation_scope,
            target_type=handoff.target_type,
            target_name=handoff.target_name,
            target_loop_type=handoff.target_loop_type,
            target_workspace=handoff.target_workspace,
            external_coder=handoff.external_coder,
            created_loop_id=handoff.created_loop_id,
            created_external_job_id=handoff.created_external_job_id,
            packet_path=handoff.packet_path,
            generated_task_preview=(handoff.generated_task or "")[:220],
            safety_notes=handoff.safety_notes,
            review_status=review_status,
            review_score=score,
            risk_level=risk_level,
            rationale="; ".join(rationale_parts),
            recommended_decision=self._decision(review_status),
            recommended_next_command=(
                f"python3 main.py --loop-improvement-handoff {handoff.id}"),
            created_at=handoff.created_at,
        )

    def _classify(self, handoff):
        rationale = []
        if not handoff.generated_task:
            return "suspicious", ["missing generated_task"]
        if self._unsafe_command(handoff.suggested_command):
            return "suspicious", ["unsafe-looking suggested_command"]
        if str(handoff.status).lower() in ("failed", "blocked"):
            return "blocked", [f"handoff status is {handoff.status}"]
        if handoff.handoff_type == "implementation_packet":
            if not _packet_path_safe(handoff.packet_path):
                return "suspicious", ["packet path is missing or outside safe directory"]
            rationale.append("implementation packet path is confined")
            return "safe_packet", rationale
        if handoff.handoff_type == "loop_task" and handoff.created_loop_id:
            return "confirmed_loop_created", ["created_loop_id present"]
        if handoff.handoff_type == "external_agent_job" and handoff.created_external_job_id:
            return "confirmed_external_job_created", ["created_external_job_id present"]
        if handoff.handoff_type == "external_agent_job" and not handoff.external_coder:
            return "needs_review", ["external_agent_job missing external_coder"]
        if self._unknown_workspace(handoff.target_workspace):
            return "needs_review", ["target_workspace is unknown"]
        if handoff.handoff_type == "loop_task" and not handoff.created_loop_id and handoff.dry_run:
            return "ready_for_manual_execution", ["loop_task is dry-run and uncreated"]
        if (handoff.handoff_type == "external_agent_job" and
                not handoff.created_external_job_id and handoff.dry_run):
            return "ready_for_manual_execution", [
                "external_agent_job is dry-run and uncreated"]
        if (handoff.handoff_type == "dry_run_plan" and handoff.generated_task and
                not handoff.created_loop_id and not handoff.created_external_job_id):
            return "safe_dry_run", ["dry_run_plan has task and no created ids"]
        return "unknown", ["no classification rule matched"]

    def _unknown_workspace(self, workspace):
        if not workspace or workspace == "default":
            return False
        row = self.conn.execute(
            "SELECT id FROM project_workspaces WHERE name=? LIMIT 1",
            (workspace,),
        ).fetchone()
        return row is None

    def _unsafe_command(self, command):
        text = (command or "").lower()
        needles = ["rm -rf", "curl ", "| sh", "&&", ";", "`", "$("]
        return any(n in text for n in needles)

    def _risk_for(self, review_status):
        if review_status in ("suspicious", "blocked"):
            return "high"
        if review_status in ("confirmed_loop_created", "confirmed_external_job_created",
                             "needs_review", "ready_for_manual_execution"):
            return "medium"
        return "low"

    def _score(self, handoff, review_status, risk_level):
        score = {
            "suspicious": 110,
            "blocked": 100,
            "confirmed_loop_created": 86,
            "confirmed_external_job_created": 86,
            "needs_review": 76,
            "ready_for_manual_execution": 68,
            "safe_packet": 42,
            "safe_dry_run": 32,
            "unknown": 58,
        }.get(review_status, 50)
        score += {
            "safety_policy_update": 28,
            "quality_gate_update": 24,
            "stop_condition_update": 22,
            "prompt_contract_update": 16,
            "external_agent_flow_update": 14,
            "testing_update": 10,
            "observability_update": 8,
            "documentation_update": 2,
        }.get(handoff.implementation_scope, 4)
        if not handoff.safety_notes:
            score += 18
        if not handoff.generated_task:
            score += 20
        if risk_level == "high":
            score += 10
        return score

    def _decision(self, review_status):
        if review_status == "suspicious":
            return "inspect"
        if review_status == "blocked":
            return "block"
        if review_status == "safe_packet":
            return "approve_for_manual_execution"
        if review_status == "safe_dry_run":
            return "defer"
        if review_status == "ready_for_manual_execution":
            return "inspect"
        if review_status in ("confirmed_loop_created", "confirmed_external_job_created"):
            return "archive"
        if review_status == "needs_review":
            return "needs_more_evidence"
        return "needs_more_evidence"

    def _groups(self, items, group_by):
        buckets = {}
        for item in items:
            key = self._group_key(item, group_by)
            buckets.setdefault(key, []).append(item)
        groups = []
        for key, vals in buckets.items():
            vals.sort(key=lambda item: (-item.review_score, item.handoff_id))
            groups.append(LoopImprovementHandoffReviewGroup(
                group_key=key,
                group_type=group_by,
                count=len(vals),
                handoff_ids=[v.handoff_id for v in vals[:10]],
                highest_risk=self._highest_risk(vals),
                summary=f"{len(vals)} handoff(s) grouped by {group_by}={key}",
                recommended_next_step=(
                    f"python3 main.py --loop-improvement-handoff {vals[0].handoff_id}"),
            ))
        groups.sort(key=lambda g: (-g.count, _risk_sort(g.highest_risk), g.group_key))
        return groups

    def _group_key(self, item, group_by):
        if group_by == "status":
            return item.review_status
        if group_by == "type":
            return item.handoff_type
        if group_by == "implementation_scope":
            return item.implementation_scope
        if group_by == "target_type":
            return item.target_type
        if group_by == "workspace":
            return item.target_workspace
        return "unknown"

    def _highest_risk(self, items):
        return sorted([i.risk_level for i in items], key=_risk_sort)[0] if items else "low"

    def _recommendations(self, items):
        recs = []
        next_steps = ["python3 main.py --loop-improvement-handoffs"]
        for item in items[:3]:
            commands = [
                f"python3 main.py --loop-improvement-handoff {item.handoff_id}",
                f"python3 main.py --loop-improvement-action {item.action_id}",
                f"python3 main.py --loop-improvement-proposal {item.source_proposal_id}",
            ]
            if item.created_loop_id:
                commands.append(f"python3 main.py --show {item.created_loop_id}")
            if item.created_external_job_id:
                commands.append(f"python3 main.py --external-job {item.created_external_job_id}")
            for cmd in commands:
                if cmd not in recs:
                    recs.append(cmd)
                if cmd not in next_steps:
                    next_steps.append(cmd)
        return recs, next_steps

    def _new_markdown_path(self, review_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"loop_improvement_handoff_review_{int(review_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError(
                "handoff review report path escaped loop_improvement_handoff_review_reports/")
        return target

    def render_markdown(self, report, review_id=None):
        lines = []
        a = lines.append
        a("# Loop Improvement Handoff Review")
        a("")
        a("## Summary")
        if review_id is not None:
            a(f"- Review ID: {review_id}")
        a(f"- Generated at: {report.generated_at}")
        a(f"- Handoffs reviewed: {report.total_handoffs_reviewed}")
        a(f"- Filters: {report.filters_json}")
        a("")
        a("## Groups")
        for group in report.groups:
            a(f"- {group.group_type}: {group.group_key} count={group.count} "
              f"risk={group.highest_risk} handoffs={group.handoff_ids}")
        if not report.groups:
            a("- (none)")
        a("")
        a("## Handoffs")
        self._append_items(lines, report.items)
        a("## Suspicious Handoffs")
        self._append_items(lines, [i for i in report.items if i.review_status == "suspicious"])
        a("## Confirmed Created Handoffs")
        self._append_items(lines, [
            i for i in report.items
            if i.review_status in ("confirmed_loop_created",
                                   "confirmed_external_job_created")
        ])
        a("## Recommendations")
        for rec in report.recommendations:
            a(f"- {rec}")
        if not report.recommendations:
            a("- (none)")
        a("")
        a("## Next Steps")
        for step in report.next_steps:
            a(f"- {step}")
        a("")
        a("## Safety Notes")
        a("- Handoff review reads handoff/action/proposal metadata only")
        a("- Suggested commands are not executed")
        a("- No model calls")
        a("- No loop or external job creation")
        a("- No framework definition mutation")
        a("")
        return "\n".join(lines)

    def _append_items(self, lines, items):
        if not items:
            lines.append("- (none)")
            lines.append("")
            return
        for item in items:
            lines.append(
                f"- handoff #{item.handoff_id} action=#{item.action_id} "
                f"type={item.handoff_type} status={item.review_status} "
                f"score={item.review_score}")
            lines.append(f"  target: {item.target_type}/{item.target_name}")
            lines.append(f"  rationale: {item.rationale}")
            lines.append(f"  command: {item.recommended_next_command}")
        lines.append("")


def _risk_sort(risk):
    return {"high": 0, "medium": 1, "low": 2}.get(risk, 3)
