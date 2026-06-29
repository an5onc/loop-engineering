"""Loop Improvement Patch Approval Gate (Stage 6.3).

This stage records explicit human approval decisions for validated patch
proposals. It does not generate patches, apply changes, execute commands, call
Ollama, create loops/jobs, or commit. Writes are limited to approval metadata
and optional Markdown reports under loop_improvement_patch_approval_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database
import loop_improvement_patch_dry_run


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "loop_improvement_patch_approval_reports")
STATUSES = {"pending", "approved", "rejected", "cancelled"}


@dataclass
class LoopImprovementPatchApproval:
    generated_at: str
    validation_id: int
    patch_proposal_id: int
    application_plan_id: int
    status: str
    approval_required: bool
    approved: bool
    auto_approved: bool
    requested_by: str = "operator"
    decided_by: str = ""
    decision_notes: str = ""
    approval_summary: str = ""
    required_controls: List[str] = field(default_factory=list)
    safety_notes: List[str] = field(default_factory=list)
    generates_patch: bool = False
    applies_changes: bool = False
    executes_commands: bool = False
    updated_at: str = ""
    decided_at: str = ""


@dataclass
class LoopImprovementPatchApprovalMarkdownReport:
    approval_id: int
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


def approval_to_dict(approval):
    return asdict(approval)


def approval_from_row(row):
    return LoopImprovementPatchApproval(
        generated_at=row["generated_at"] or "",
        validation_id=row["validation_id"],
        patch_proposal_id=row["patch_proposal_id"],
        application_plan_id=row["application_plan_id"],
        status=row["status"] or "",
        approval_required=bool(row["approval_required"]),
        approved=bool(row["approved"]),
        auto_approved=bool(row["auto_approved"]),
        requested_by=row["requested_by"] or "",
        decided_by=row["decided_by"] or "",
        decision_notes=row["decision_notes"] or "",
        approval_summary=row["approval_summary"] or "",
        required_controls=_safe_json_loads(row["required_controls_json"], []),
        safety_notes=_safe_json_loads(row["safety_notes_json"], []),
        generates_patch=bool(row["generates_patch"]),
        applies_changes=bool(row["applies_changes"]),
        executes_commands=bool(row["executes_commands"]),
        updated_at=row["updated_at"] or "",
        decided_at=row["decided_at"] or "",
    )


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


class LoopImprovementPatchApprovalEngine:
    def __init__(self, conn):
        self.conn = conn

    def create_approval_request(self, validation_id, requested_by="operator"):
        row = database.get_loop_improvement_patch_dry_run_validation(
            self.conn, int(validation_id))
        if row is None:
            raise ValueError(f"no loop improvement patch dry-run validation {validation_id}")
        validation = loop_improvement_patch_dry_run.validation_from_row(row)
        if not validation.ready_for_human_approval or validation.failed_checks:
            raise ValueError(
                f"dry-run validation {validation_id} is not ready for human approval"
            )
        return LoopImprovementPatchApproval(
            generated_at=_now_iso(),
            validation_id=int(validation_id),
            patch_proposal_id=validation.patch_proposal_id,
            application_plan_id=validation.application_plan_id,
            status="pending",
            approval_required=True,
            approved=False,
            auto_approved=False,
            requested_by=requested_by,
            approval_summary=(
                "Pending explicit human approval for a later patch application stage."
            ),
            required_controls=_required_controls(),
            safety_notes=_safety_notes(),
            generates_patch=False,
            applies_changes=False,
            executes_commands=False,
            updated_at=_now_iso(),
        )

    def save_approval_request(self, approval):
        approval_id = database.save_loop_improvement_patch_approval(
            self.conn,
            approval.generated_at,
            approval.validation_id,
            approval.patch_proposal_id,
            approval.application_plan_id,
            approval.status,
            approval.approval_required,
            approval.approved,
            approval.auto_approved,
            approval.requested_by,
            approval.decided_by,
            approval.decision_notes,
            approval.approval_summary,
            json.dumps(approval.required_controls, sort_keys=True),
            json.dumps(approval.safety_notes, sort_keys=True),
            approval.generates_patch,
            approval.applies_changes,
            approval.executes_commands,
            approval.updated_at,
            approval.decided_at,
        )
        database.save_loop_improvement_patch_approval_event(
            self.conn,
            approval_id,
            "created",
            json.dumps({
                "validation_id": approval.validation_id,
                "patch_proposal_id": approval.patch_proposal_id,
                "status": approval.status,
            }, sort_keys=True),
        )
        return approval_id

    def update_approval_status(self, approval_id, status, operator="operator", notes=""):
        if status not in STATUSES:
            raise ValueError("approval status must be pending, approved, rejected, or cancelled")
        row = database.get_loop_improvement_patch_approval(self.conn, int(approval_id))
        if row is None:
            raise ValueError(f"no loop improvement patch approval {approval_id}")
        decided_at = _now_iso() if status in ("approved", "rejected", "cancelled") else ""
        updated = database.update_loop_improvement_patch_approval_status(
            self.conn,
            int(approval_id),
            status,
            status == "approved",
            operator if status != "pending" else "",
            notes,
            _now_iso(),
            decided_at,
        )
        database.save_loop_improvement_patch_approval_event(
            self.conn,
            int(approval_id),
            "status_updated",
            json.dumps({
                "status": status,
                "operator": operator,
                "notes": notes,
                "applies_changes": False,
            }, sort_keys=True),
        )
        return approval_from_row(updated)

    def save_markdown_report(self, approval_id, approval):
        content = self.render_markdown(approval, approval_id)
        path = self._new_report_path(approval_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_loop_improvement_patch_approval_markdown_report(
            self.conn, approval_id, path, "markdown", chash, nbytes)
        return LoopImprovementPatchApprovalMarkdownReport(
            approval_id=approval_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def _new_report_path(self, approval_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = (
            f"loop_improvement_patch_approval_{int(approval_id)}_{_now_stamp()}.md"
        )
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError(
                "patch approval report path escaped loop_improvement_patch_approval_reports/")
        return target

    def render_markdown(self, approval, approval_id=None):
        lines = []
        a = lines.append
        a("# Loop Improvement Patch Approval")
        a("")
        a("## Summary")
        if approval_id is not None:
            a(f"- Approval ID: {approval_id}")
        a(f"- Generated at: {approval.generated_at}")
        a(f"- Validation ID: {approval.validation_id}")
        a(f"- Patch proposal ID: {approval.patch_proposal_id}")
        a(f"- Application plan ID: {approval.application_plan_id}")
        a(f"- Status: {approval.status}")
        a(f"- Approved: {approval.approved}")
        a(f"- Auto-approved: {approval.auto_approved}")
        a(f"- Applies changes: {approval.applies_changes}")
        a(f"- Generates patch: {approval.generates_patch}")
        a(f"- Executes commands: {approval.executes_commands}")
        a("")
        a("## Decision")
        a(f"- Requested by: {approval.requested_by or '(none)'}")
        a(f"- Decided by: {approval.decided_by or '(none)'}")
        a(f"- Decided at: {approval.decided_at or '(none)'}")
        a(f"- Notes: {approval.decision_notes or '(none)'}")
        a("")
        a("## Required Controls")
        _append_list(lines, approval.required_controls)
        a("## Safety Notes")
        _append_list(lines, approval.safety_notes)
        return "\n".join(lines)


def _required_controls():
    return [
        "explicit human approval required before patch application",
        "approved status only unlocks later stages; it does not apply changes",
        "patch preview and rollback snapshot are still required before file writes",
        "workspace profile and command allowlist protections must remain enforced",
    ]


def _safety_notes():
    return [
        "Stage 6.3 records human approval metadata only.",
        "No patches are generated.",
        "No changes are applied by approval recording.",
        "No commands are executed.",
        "No Ollama or external-agent calls are made.",
        "No loops, jobs, commits, or framework definitions are mutated.",
        "No approval is created automatically from a failed dry-run validation.",
    ]


def _append_list(lines, items):
    if not items:
        lines.append("- (none)")
    for item in items:
        lines.append(f"- {item}")
    lines.append("")
