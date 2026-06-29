"""Loop Improvement Patch Proposal Generator (Stage 6.1).

This stage converts approved application-plan metadata into a metadata-only
patch proposal. It does not generate unified diffs, write patch files, edit
source files, read source file contents, execute commands, call Ollama, create
loops/jobs, or commit. Writes are limited to patch-proposal metadata and
optional Markdown reports under loop_improvement_patch_proposal_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database
import loop_improvement_application_planner


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "loop_improvement_patch_proposal_reports")


@dataclass
class LoopImprovementPatchProposalItem:
    application_plan_id: int
    source_action_id: int
    source_handoff_id: int
    source_proposal_id: int
    source_plan_id: int
    target_type: str
    target_name: str
    target_file: str
    proposed_edit_kind: str
    metadata_intent_summary: str
    safety_constraints: List[str] = field(default_factory=list)
    validation_requirements: List[str] = field(default_factory=list)
    rollback_requirements: List[str] = field(default_factory=list)


@dataclass
class LoopImprovementPatchProposal:
    generated_at: str
    application_plan_id: int
    status: str
    total_plan_items: int
    total_target_files: int
    target_files: List[str] = field(default_factory=list)
    patch_strategy: str = ""
    metadata_only_intent: str = ""
    required_approvals: List[str] = field(default_factory=list)
    rollback_requirements: List[str] = field(default_factory=list)
    validation_requirements: List[str] = field(default_factory=list)
    safety_notes: List[str] = field(default_factory=list)
    recommended_next_commands: List[str] = field(default_factory=list)
    items: List[LoopImprovementPatchProposalItem] = field(default_factory=list)
    generates_unified_diff: bool = False
    writes_patch_file: bool = False
    applies_changes: bool = False
    reads_file_contents: bool = False


@dataclass
class LoopImprovementPatchProposalMarkdownReport:
    patch_proposal_id: int
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


def proposal_to_dict(proposal):
    data = asdict(proposal)
    data["items"] = [item_to_dict(i) for i in proposal.items]
    return data


def item_from_dict(data):
    return LoopImprovementPatchProposalItem(**data)


def proposal_from_row(row):
    return LoopImprovementPatchProposal(
        generated_at=row["generated_at"] or "",
        application_plan_id=row["application_plan_id"],
        status=row["status"] or "",
        total_plan_items=row["total_plan_items"] or 0,
        total_target_files=row["total_target_files"] or 0,
        target_files=_safe_json_loads(row["target_files_json"], []),
        patch_strategy=row["patch_strategy"] or "",
        metadata_only_intent=row["metadata_only_intent"] or "",
        required_approvals=_safe_json_loads(row["required_approvals_json"], []),
        rollback_requirements=_safe_json_loads(row["rollback_requirements_json"], []),
        validation_requirements=_safe_json_loads(row["validation_requirements_json"], []),
        safety_notes=_safe_json_loads(row["safety_notes_json"], []),
        recommended_next_commands=_safe_json_loads(
            row["recommended_next_commands_json"], []),
        items=[item_from_dict(i) for i in _safe_json_loads(row["items_json"], [])],
        generates_unified_diff=bool(row["generates_unified_diff"]),
        writes_patch_file=bool(row["writes_patch_file"]),
        applies_changes=bool(row["applies_changes"]),
        reads_file_contents=bool(row["reads_file_contents"]),
    )


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


class LoopImprovementPatchProposalGenerator:
    def __init__(self, conn):
        self.conn = conn

    def build_proposal(self, application_plan_id):
        row = database.get_loop_improvement_application_plan(
            self.conn, int(application_plan_id))
        if row is None:
            raise ValueError(f"no loop improvement application plan {application_plan_id}")
        plan = loop_improvement_application_planner.plan_from_row(row)
        items = self._proposal_items(plan, int(application_plan_id))
        target_files = _dedupe([item.target_file for item in items])
        return LoopImprovementPatchProposal(
            generated_at=_now_iso(),
            application_plan_id=int(application_plan_id),
            status="proposed",
            total_plan_items=plan.total_items,
            total_target_files=len(target_files),
            target_files=target_files,
            patch_strategy=(
                "Create a future human-reviewed patch from metadata intent only; "
                "do not generate unified diffs until Stage 6.2+ dry-run validation."
            ),
            metadata_only_intent=self._metadata_only_intent(plan, items),
            required_approvals=_required_approvals(),
            rollback_requirements=_rollback_requirements(),
            validation_requirements=_validation_requirements(),
            safety_notes=_safety_notes(),
            recommended_next_commands=self._recommended_next_commands(
                int(application_plan_id)),
            items=items,
            generates_unified_diff=False,
            writes_patch_file=False,
            applies_changes=False,
            reads_file_contents=False,
        )

    def save_proposal(self, proposal):
        proposal_id = database.save_loop_improvement_patch_proposal(
            self.conn,
            proposal.generated_at,
            proposal.application_plan_id,
            proposal.status,
            proposal.total_plan_items,
            proposal.total_target_files,
            json.dumps(proposal.target_files, sort_keys=True),
            proposal.patch_strategy,
            proposal.metadata_only_intent,
            json.dumps(proposal.required_approvals, sort_keys=True),
            json.dumps(proposal.rollback_requirements, sort_keys=True),
            json.dumps(proposal.validation_requirements, sort_keys=True),
            json.dumps(proposal.safety_notes, sort_keys=True),
            json.dumps(proposal.recommended_next_commands, sort_keys=True),
            json.dumps([item_to_dict(i) for i in proposal.items], sort_keys=True),
            proposal.generates_unified_diff,
            proposal.writes_patch_file,
            proposal.applies_changes,
            proposal.reads_file_contents,
        )
        for item in proposal.items:
            database.save_loop_improvement_patch_proposal_item(
                self.conn,
                proposal_id,
                item.application_plan_id,
                item.source_action_id,
                item.source_handoff_id,
                item.source_proposal_id,
                item.source_plan_id,
                item.target_type,
                item.target_name,
                item.target_file,
                item.proposed_edit_kind,
                item.metadata_intent_summary,
                json.dumps(item.safety_constraints, sort_keys=True),
                json.dumps(item.validation_requirements, sort_keys=True),
                json.dumps(item.rollback_requirements, sort_keys=True),
            )
        database.save_loop_improvement_patch_proposal_event(
            self.conn,
            proposal_id,
            "created",
            json.dumps({
                "application_plan_id": proposal.application_plan_id,
                "total_plan_items": proposal.total_plan_items,
                "total_target_files": proposal.total_target_files,
            }, sort_keys=True),
        )
        return proposal_id

    def save_markdown_report(self, proposal_id, proposal):
        content = self.render_markdown(proposal, proposal_id)
        path = self._new_report_path(proposal_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_loop_improvement_patch_proposal_markdown_report(
            self.conn, proposal_id, path, "markdown", chash, nbytes)
        return LoopImprovementPatchProposalMarkdownReport(
            patch_proposal_id=proposal_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def _proposal_items(self, plan, application_plan_id):
        items = []
        for plan_item in plan.items:
            for target_file in plan_item.target_files:
                items.append(LoopImprovementPatchProposalItem(
                    application_plan_id=application_plan_id,
                    source_action_id=plan_item.source_action_id,
                    source_handoff_id=plan_item.source_handoff_id,
                    source_proposal_id=plan_item.source_proposal_id,
                    source_plan_id=plan_item.source_plan_id,
                    target_type=plan_item.target_type,
                    target_name=plan_item.target_name,
                    target_file=target_file,
                    proposed_edit_kind="metadata_intent",
                    metadata_intent_summary=(
                        f"Metadata-only patch intent for {target_file}: "
                        f"{plan_item.patch_intent_summary}"
                    ),
                    safety_constraints=_safety_notes(),
                    validation_requirements=_validation_requirements(),
                    rollback_requirements=_rollback_requirements(),
                ))
        return items

    def _metadata_only_intent(self, plan, items):
        if not items:
            return "No eligible target files were found for patch proposal planning."
        return (
            "Metadata-only patch intent derived from application plan "
            f"#{plan.source_id}: {plan.patch_intent_summary}"
        )

    def _recommended_next_commands(self, application_plan_id):
        return [
            f"python3 main.py --loop-improvement-application-plan {application_plan_id}",
            "python3 main.py --loop-improvement-patch-proposal PROPOSAL_ID",
            "Stage 6.2 dry-run validator must inspect this proposal before any patch is generated.",
        ]

    def _new_report_path(self, proposal_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = (
            f"loop_improvement_patch_proposal_{int(proposal_id)}_{_now_stamp()}.md"
        )
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError(
                "patch proposal report path escaped loop_improvement_patch_proposal_reports/")
        return target

    def render_markdown(self, proposal, proposal_id=None):
        lines = []
        a = lines.append
        a("# Loop Improvement Patch Proposal")
        a("")
        a("## Summary")
        if proposal_id is not None:
            a(f"- Patch Proposal ID: {proposal_id}")
        a(f"- Generated at: {proposal.generated_at}")
        a(f"- Application plan ID: {proposal.application_plan_id}")
        a(f"- Status: {proposal.status}")
        a(f"- Total plan items: {proposal.total_plan_items}")
        a(f"- Total target files: {proposal.total_target_files}")
        a(f"- Generates unified diff: {proposal.generates_unified_diff}")
        a(f"- Writes patch file: {proposal.writes_patch_file}")
        a(f"- Applies changes: {proposal.applies_changes}")
        a(f"- Reads file contents: {proposal.reads_file_contents}")
        a("")
        a("## Metadata-Only Patch Intent")
        a(proposal.metadata_only_intent or "(none)")
        a("")
        a("## Target Files")
        _append_list(lines, proposal.target_files)
        a("## Patch Strategy")
        a(proposal.patch_strategy or "(none)")
        a("")
        a("## Items")
        if not proposal.items:
            a("- (none)")
        for item in proposal.items:
            a(f"- {item.target_file}")
            a(f"  target: {item.target_type}/{item.target_name}")
            a(f"  edit kind: {item.proposed_edit_kind}")
            a(f"  intent: {item.metadata_intent_summary}")
        a("")
        a("## Required Approvals")
        _append_list(lines, proposal.required_approvals)
        a("## Rollback Requirements")
        _append_list(lines, proposal.rollback_requirements)
        a("## Validation Requirements")
        _append_list(lines, proposal.validation_requirements)
        a("## Safety Notes")
        _append_list(lines, proposal.safety_notes)
        a("## Recommended Next Commands")
        _append_list(lines, proposal.recommended_next_commands)
        return "\n".join(lines)


def _required_approvals():
    return [
        "human approval before any unified diff is generated",
        "human approval before any patch file is written",
        "human approval before any source file write",
        "human approval before command execution",
    ]


def _rollback_requirements():
    return [
        "rollback snapshot required before any future source file write",
        "original file hashes and contents must be captured by a later stage",
        "failure must stop and preserve rollback path",
    ]


def _validation_requirements():
    return [
        "Stage 6.2 dry-run validator must run before patch generation",
        "target files must pass file allowlist and workspace profile checks",
        "post-apply tests are required in a later application stage",
    ]


def _safety_notes():
    return [
        "Stage 6.1 is metadata-only patch proposal planning.",
        "No unified diffs are generated.",
        "No patch files are written.",
        "No source files are edited.",
        "No source file contents are read.",
        "No commands are executed.",
        "No Ollama or external-agent calls are made.",
        "No loops, jobs, commits, or framework definitions are mutated.",
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
