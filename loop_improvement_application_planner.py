"""Loop Improvement Application Planner (Stage 6.0).

The planner converts approved/reviewed Stage 5 improvement metadata into a
structured application plan. It does not generate patches, edit files, execute
commands, call Ollama, create loops/jobs, commit, or mutate framework
definitions. Writes are limited to application-plan metadata and optional
Markdown reports under loop_improvement_application_plan_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "loop_improvement_application_plan_reports")
SOURCE_TYPES = {"action", "handoff", "handoff_review"}
ELIGIBLE_HANDOFF_REVIEW_STATUSES = {
    "safe_packet",
    "safe_dry_run",
    "ready_for_manual_execution",
}


@dataclass
class LoopImprovementApplicationPlanItem:
    source_action_id: int
    source_handoff_id: int
    source_proposal_id: int
    source_plan_id: int
    target_type: str
    target_name: str
    target_files: List[str] = field(default_factory=list)
    patch_intent_summary: str = ""
    risk_level: str = "medium"
    required_approvals: List[str] = field(default_factory=list)
    rollback_requirements: List[str] = field(default_factory=list)
    validation_requirements: List[str] = field(default_factory=list)


@dataclass
class LoopImprovementApplicationPlan:
    generated_at: str
    source_type: str
    source_id: int
    status: str
    total_items: int
    source_action_id: int = None
    source_handoff_id: int = None
    source_handoff_review_id: int = None
    source_proposal_id: int = None
    source_plan_id: int = None
    target_files: List[str] = field(default_factory=list)
    patch_intent_summary: str = ""
    risk_assessment: str = ""
    required_approvals: List[str] = field(default_factory=list)
    rollback_requirements: List[str] = field(default_factory=list)
    validation_requirements: List[str] = field(default_factory=list)
    safety_notes: List[str] = field(default_factory=list)
    recommended_next_commands: List[str] = field(default_factory=list)
    items: List[LoopImprovementApplicationPlanItem] = field(default_factory=list)
    generates_patch: bool = False
    applies_changes: bool = False


@dataclass
class LoopImprovementApplicationPlanMarkdownReport:
    application_plan_id: int
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


def plan_to_dict(plan):
    data = asdict(plan)
    data["items"] = [item_to_dict(i) for i in plan.items]
    return data


def item_from_dict(data):
    return LoopImprovementApplicationPlanItem(**data)


def plan_from_row(row):
    return LoopImprovementApplicationPlan(
        generated_at=row["generated_at"] or "",
        source_type=row["source_type"] or "",
        source_id=row["source_id"],
        status=row["status"] or "",
        total_items=row["total_items"] or 0,
        source_action_id=row["source_action_id"],
        source_handoff_id=row["source_handoff_id"],
        source_handoff_review_id=row["source_handoff_review_id"],
        source_proposal_id=row["source_proposal_id"],
        source_plan_id=row["source_plan_id"],
        target_files=_safe_json_loads(row["target_files_json"], []),
        patch_intent_summary=row["patch_intent_summary"] or "",
        risk_assessment=row["risk_assessment"] or "",
        required_approvals=_safe_json_loads(row["required_approvals_json"], []),
        rollback_requirements=_safe_json_loads(row["rollback_requirements_json"], []),
        validation_requirements=_safe_json_loads(row["validation_requirements_json"], []),
        safety_notes=_safe_json_loads(row["safety_notes_json"], []),
        recommended_next_commands=_safe_json_loads(
            row["recommended_next_commands_json"], []),
        items=[item_from_dict(i) for i in _safe_json_loads(row["items_json"], [])],
        generates_patch=bool(row["generates_patch"]),
        applies_changes=bool(row["applies_changes"]),
    )


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


class LoopImprovementApplicationPlanner:
    def __init__(self, conn):
        self.conn = conn

    def build_plan(self, source_type="action", source_id=None):
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"unknown application plan source type '{source_type}'")
        if source_id is None:
            raise ValueError("source_id is required")
        items = self._items_for_source(source_type, int(source_id))
        all_files = _dedupe([f for item in items for f in item.target_files])
        source_action_id = items[0].source_action_id if items else None
        source_handoff_id = items[0].source_handoff_id if items else None
        source_proposal_id = items[0].source_proposal_id if items else None
        source_plan_id = items[0].source_plan_id if items else None
        return LoopImprovementApplicationPlan(
            generated_at=_now_iso(),
            source_type=source_type,
            source_id=int(source_id),
            status="planned",
            total_items=len(items),
            source_action_id=source_action_id,
            source_handoff_id=source_handoff_id,
            source_handoff_review_id=int(source_id) if source_type == "handoff_review" else None,
            source_proposal_id=source_proposal_id,
            source_plan_id=source_plan_id,
            target_files=all_files,
            patch_intent_summary=self._plan_summary(items),
            risk_assessment=self._risk_assessment(items),
            required_approvals=_required_approvals(),
            rollback_requirements=_rollback_requirements(),
            validation_requirements=_validation_requirements(),
            safety_notes=_safety_notes(),
            recommended_next_commands=self._recommended_next_commands(items),
            items=items,
            generates_patch=False,
            applies_changes=False,
        )

    def save_plan(self, plan):
        plan_id = database.save_loop_improvement_application_plan(
            self.conn,
            plan.generated_at,
            plan.source_type,
            plan.source_id,
            plan.source_action_id,
            plan.source_handoff_id,
            plan.source_handoff_review_id,
            plan.source_proposal_id,
            plan.source_plan_id,
            plan.status,
            plan.total_items,
            json.dumps(plan.target_files, sort_keys=True),
            plan.patch_intent_summary,
            plan.risk_assessment,
            json.dumps(plan.required_approvals, sort_keys=True),
            json.dumps(plan.rollback_requirements, sort_keys=True),
            json.dumps(plan.validation_requirements, sort_keys=True),
            json.dumps(plan.safety_notes, sort_keys=True),
            json.dumps(plan.recommended_next_commands, sort_keys=True),
            json.dumps([item_to_dict(i) for i in plan.items], sort_keys=True),
            plan.generates_patch,
            plan.applies_changes,
        )
        for item in plan.items:
            database.save_loop_improvement_application_plan_item(
                self.conn,
                plan_id,
                item.source_action_id,
                item.source_handoff_id,
                item.source_proposal_id,
                item.source_plan_id,
                item.target_type,
                item.target_name,
                json.dumps(item.target_files, sort_keys=True),
                item.patch_intent_summary,
                item.risk_level,
                json.dumps(item.required_approvals, sort_keys=True),
                json.dumps(item.rollback_requirements, sort_keys=True),
                json.dumps(item.validation_requirements, sort_keys=True),
            )
        database.save_loop_improvement_application_plan_event(
            self.conn,
            plan_id,
            "created",
            json.dumps({
                "source_type": plan.source_type,
                "source_id": plan.source_id,
                "total_items": plan.total_items,
            }, sort_keys=True),
        )
        return plan_id

    def save_markdown_report(self, plan_id, plan):
        content = self.render_markdown(plan, plan_id)
        path = self._new_report_path(plan_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_loop_improvement_application_plan_markdown_report(
            self.conn, plan_id, path, "markdown", chash, nbytes)
        return LoopImprovementApplicationPlanMarkdownReport(
            application_plan_id=plan_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def _items_for_source(self, source_type, source_id):
        if source_type == "action":
            return [self._item_from_action_id(source_id)]
        if source_type == "handoff":
            return [self._item_from_handoff_id(source_id)]
        return self._items_from_handoff_review(source_id)

    def _item_from_action_id(self, action_id):
        row = database.get_loop_improvement_action_item(self.conn, int(action_id))
        if row is None:
            raise ValueError(f"no loop improvement action {action_id}")
        return self._item_from_action_row(row, source_handoff_id=None)

    def _item_from_handoff_id(self, handoff_id):
        row = database.get_loop_improvement_handoff(self.conn, int(handoff_id))
        if row is None:
            raise ValueError(f"no loop improvement handoff {handoff_id}")
        action = database.get_loop_improvement_action_item(self.conn, row["action_id"])
        if action is None:
            raise ValueError(f"handoff {handoff_id} has no source action")
        return self._item_from_action_row(action, source_handoff_id=row["id"])

    def _items_from_handoff_review(self, review_id):
        row = database.get_loop_improvement_handoff_review(self.conn, int(review_id))
        if row is None:
            raise ValueError(f"no loop improvement handoff review {review_id}")
        items = []
        for data in _safe_json_loads(row["items_json"], []):
            if data.get("review_status") not in ELIGIBLE_HANDOFF_REVIEW_STATUSES:
                continue
            action = database.get_loop_improvement_action_item(
                self.conn, data.get("action_id"))
            if action is None:
                continue
            items.append(self._item_from_action_row(
                action, source_handoff_id=data.get("handoff_id")))
        return items

    def _item_from_action_row(self, row, source_handoff_id=None):
        target_type = row["target_type"] or "unknown"
        target_name = row["target_name"] or ""
        target_files = infer_target_files(target_type, target_name)
        risk = row["risk_level"] or "medium"
        return LoopImprovementApplicationPlanItem(
            source_action_id=row["id"],
            source_handoff_id=source_handoff_id,
            source_proposal_id=row["source_proposal_id"],
            source_plan_id=row["source_plan_id"],
            target_type=target_type,
            target_name=target_name,
            target_files=target_files,
            patch_intent_summary=(
                f"Plan a future patch for {target_type}/{target_name}: "
                f"{row['proposed_change'] or row['title'] or ''}"
            ),
            risk_level=risk,
            required_approvals=_required_approvals(),
            rollback_requirements=_rollback_requirements(),
            validation_requirements=_validation_requirements(),
        )

    def _plan_summary(self, items):
        if not items:
            return "No eligible application targets found."
        return " | ".join(item.patch_intent_summary for item in items)

    def _risk_assessment(self, items):
        if not items:
            return "low: no eligible items selected"
        risks = [item.risk_level for item in items]
        if "critical" in risks or "high" in risks:
            return "high: approval, rollback, and validation required before any write"
        if "medium" in risks:
            return "medium: approval, rollback, and validation required before any write"
        return "low: approval, rollback, and validation still required"

    def _recommended_next_commands(self, items):
        commands = []
        for item in items:
            if item.source_handoff_id:
                commands.append(
                    f"python3 main.py --loop-improvement-handoff {item.source_handoff_id}")
            if item.source_action_id:
                commands.append(
                    f"python3 main.py --loop-improvement-action {item.source_action_id}")
            if item.source_proposal_id:
                commands.append(
                    f"python3 main.py --loop-improvement-proposal {item.source_proposal_id}")
        commands.append("python3 main.py --loop-improvement-application-plan PLAN_ID")
        return _dedupe(commands)

    def _new_report_path(self, plan_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"loop_improvement_application_plan_{int(plan_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError(
                "application plan report path escaped loop_improvement_application_plan_reports/")
        return target

    def render_markdown(self, plan, plan_id=None):
        lines = []
        a = lines.append
        a("# Loop Improvement Application Plan")
        a("")
        a("## Summary")
        if plan_id is not None:
            a(f"- Application Plan ID: {plan_id}")
        a(f"- Generated at: {plan.generated_at}")
        a(f"- Source: {plan.source_type} #{plan.source_id}")
        a(f"- Status: {plan.status}")
        a(f"- Total items: {plan.total_items}")
        a(f"- Generates patch: {plan.generates_patch}")
        a(f"- Applies changes: {plan.applies_changes}")
        a(f"- Risk: {plan.risk_assessment}")
        a("")
        a("## Target Files")
        _append_list(lines, plan.target_files)
        a("## Patch Intent")
        a(plan.patch_intent_summary or "(none)")
        a("")
        a("## Required Approvals")
        _append_list(lines, plan.required_approvals)
        a("## Rollback Requirements")
        _append_list(lines, plan.rollback_requirements)
        a("## Validation Requirements")
        _append_list(lines, plan.validation_requirements)
        a("## Items")
        if not plan.items:
            a("- (none)")
        for item in plan.items:
            a(f"- {item.target_type}/{item.target_name}")
            a(f"  source action: {item.source_action_id}")
            a(f"  source handoff: {item.source_handoff_id or '(none)'}")
            a(f"  target files: {', '.join(item.target_files) or '(none)'}")
            a(f"  intent: {item.patch_intent_summary}")
        a("")
        a("## Recommended Next Commands")
        _append_list(lines, plan.recommended_next_commands)
        a("## Safety Notes")
        _append_list(lines, plan.safety_notes)
        return "\n".join(lines)


def infer_target_files(target_type, target_name=""):
    mapping = {
        "quality_gate": ["stop_conditions.py", "loop_engine.py"],
        "stop_condition": ["stop_conditions.py", "loop_registry.py"],
        "prompt": ["prompts.py", "agent_registry.py"],
        "agent_definition": ["agent_registry.py"],
        "loop_definition": ["loop_registry.py", "loop_templates.py"],
        "workspace_profile": ["workspace_profiles.py", "project_workspace.py"],
        "external_agent_flow": [
            "external_agents.py",
            "external_agent_jobs.py",
            "external_job_health.py",
        ],
        "observatory_flow": ["observatory.py", "observatory_stage4_audit.py"],
        "documentation": ["README.md", "HANDOFF.md"],
        "testing": ["test_loop_improvement.py"],
        "safety_policy": [
            "filesystem.py",
            "terminal.py",
            "approval_gates.py",
            "project_workspace.py",
        ],
    }
    return list(mapping.get(target_type, ["README.md"]))


def _required_approvals():
    return [
        "human approval before patch generation",
        "human approval before any file write",
        "human approval before command execution",
        "human approval before any git commit",
    ]


def _rollback_requirements():
    return [
        "rollback snapshot required before any file write",
        "record original file hashes and contents for all target files",
        "failure must stop and preserve rollback path",
    ]


def _validation_requirements():
    return [
        "patch preview required before apply",
        "target files must pass workspace profile and protected path checks",
        "post-apply tests required before completion",
    ]


def _safety_notes():
    return [
        "Stage 6.0 is dry-run planning only.",
        "No patches are generated.",
        "No files are edited.",
        "No commands are executed.",
        "No Ollama or external-agent calls are made.",
        "No loops, jobs, commits, or framework definitions are mutated.",
        "No autonomous recursive self-modification is allowed.",
    ]


def _append_list(lines, items):
    if not items:
        lines.append("- (none)")
    for item in items:
        lines.append(f"- {item}")
    lines.append("")


def _dedupe(items):
    out = []
    for item in items:
        if item not in out:
            out.append(item)
    return out
