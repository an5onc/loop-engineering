"""Loop Improvement Patch Application Engine (Stage 6.4).

This stage creates guarded application attempts for approved patch approvals.
Because rollback snapshots are introduced in Stage 6.5, every attempt in this
stage fails closed before any file write. It does not generate patches, edit
files, execute commands, commit, call Ollama, or create loops/jobs. Writes are
limited to application-attempt metadata and optional Markdown reports under
loop_improvement_patch_application_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import List

import database
import loop_improvement_patch_approval
import loop_improvement_patch_proposals


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "loop_improvement_patch_application_reports")
BLOCKED_ROLLBACK_REQUIRED = "blocked_rollback_required"


@dataclass
class LoopImprovementPatchApplicationAttempt:
    generated_at: str
    approval_id: int
    validation_id: int
    patch_proposal_id: int
    application_plan_id: int
    status: str
    approval_confirmed: bool
    rollback_snapshot_required: bool
    rollback_snapshot_present: bool
    total_target_files: int
    target_files: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    safety_notes: List[str] = field(default_factory=list)
    required_next_controls: List[str] = field(default_factory=list)
    applies_changes: bool = False
    writes_files: bool = False
    executes_commands: bool = False
    commits_changes: bool = False
    generates_patch: bool = False


@dataclass
class LoopImprovementPatchApplicationMarkdownReport:
    attempt_id: int
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


def application_attempt_from_row(row):
    return LoopImprovementPatchApplicationAttempt(
        generated_at=row["generated_at"] or "",
        approval_id=row["approval_id"],
        validation_id=row["validation_id"],
        patch_proposal_id=row["patch_proposal_id"],
        application_plan_id=row["application_plan_id"],
        status=row["status"] or "",
        approval_confirmed=bool(row["approval_confirmed"]),
        rollback_snapshot_required=bool(row["rollback_snapshot_required"]),
        rollback_snapshot_present=bool(row["rollback_snapshot_present"]),
        total_target_files=row["total_target_files"] or 0,
        target_files=_safe_json_loads(row["target_files_json"], []),
        blockers=_safe_json_loads(row["blockers_json"], []),
        safety_notes=_safe_json_loads(row["safety_notes_json"], []),
        required_next_controls=_safe_json_loads(
            row["required_next_controls_json"], []),
        applies_changes=bool(row["applies_changes"]),
        writes_files=bool(row["writes_files"]),
        executes_commands=bool(row["executes_commands"]),
        commits_changes=bool(row["commits_changes"]),
        generates_patch=bool(row["generates_patch"]),
    )


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


class LoopImprovementPatchApplicationEngine:
    def __init__(self, conn):
        self.conn = conn

    def create_application_attempt(self, approval_id):
        row = database.get_loop_improvement_patch_approval(self.conn, int(approval_id))
        if row is None:
            raise ValueError(f"no loop improvement patch approval {approval_id}")
        approval = loop_improvement_patch_approval.approval_from_row(row)
        if approval.status != "approved" or not approval.approved:
            raise ValueError(f"loop improvement patch approval {approval_id} is not approved")
        proposal_row = database.get_loop_improvement_patch_proposal(
            self.conn, approval.patch_proposal_id)
        if proposal_row is None:
            raise ValueError(
                f"approval {approval_id} references missing patch proposal "
                f"{approval.patch_proposal_id}"
            )
        proposal = loop_improvement_patch_proposals.proposal_from_row(proposal_row)
        target_files = list(proposal.target_files or [])
        return LoopImprovementPatchApplicationAttempt(
            generated_at=_now_iso(),
            approval_id=int(approval_id),
            validation_id=approval.validation_id,
            patch_proposal_id=approval.patch_proposal_id,
            application_plan_id=approval.application_plan_id,
            status=BLOCKED_ROLLBACK_REQUIRED,
            approval_confirmed=True,
            rollback_snapshot_required=True,
            rollback_snapshot_present=False,
            total_target_files=len(target_files),
            target_files=target_files,
            blockers=[
                "Rollback snapshot required before any file write.",
                "Stage 6.5 rollback snapshot support must run before apply.",
            ],
            safety_notes=_safety_notes(),
            required_next_controls=_required_next_controls(),
            applies_changes=False,
            writes_files=False,
            executes_commands=False,
            commits_changes=False,
            generates_patch=False,
        )

    def save_application_attempt(self, attempt):
        attempt_id = database.save_loop_improvement_patch_application_attempt(
            self.conn,
            attempt.generated_at,
            attempt.approval_id,
            attempt.validation_id,
            attempt.patch_proposal_id,
            attempt.application_plan_id,
            attempt.status,
            attempt.approval_confirmed,
            attempt.rollback_snapshot_required,
            attempt.rollback_snapshot_present,
            attempt.total_target_files,
            json.dumps(attempt.target_files, sort_keys=True),
            json.dumps(attempt.blockers, sort_keys=True),
            json.dumps(attempt.safety_notes, sort_keys=True),
            json.dumps(attempt.required_next_controls, sort_keys=True),
            attempt.applies_changes,
            attempt.writes_files,
            attempt.executes_commands,
            attempt.commits_changes,
            attempt.generates_patch,
        )
        database.save_loop_improvement_patch_application_attempt_event(
            self.conn,
            attempt_id,
            "created",
            json.dumps({
                "approval_id": attempt.approval_id,
                "status": attempt.status,
                "applies_changes": attempt.applies_changes,
                "rollback_snapshot_present": attempt.rollback_snapshot_present,
            }, sort_keys=True),
        )
        return attempt_id

    def save_markdown_report(self, attempt_id, attempt):
        content = self.render_markdown(attempt, attempt_id)
        path = self._new_report_path(attempt_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_loop_improvement_patch_application_markdown_report(
            self.conn, attempt_id, path, "markdown", chash, nbytes)
        return LoopImprovementPatchApplicationMarkdownReport(
            attempt_id=attempt_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def _new_report_path(self, attempt_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = (
            f"loop_improvement_patch_application_{int(attempt_id)}_{_now_stamp()}.md"
        )
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError(
                "patch application report path escaped "
                "loop_improvement_patch_application_reports/")
        return target

    def render_markdown(self, attempt, attempt_id=None):
        lines = []
        a = lines.append
        a("# Loop Improvement Patch Application Attempt")
        a("")
        a("## Summary")
        if attempt_id is not None:
            a(f"- Attempt ID: {attempt_id}")
        a(f"- Generated at: {attempt.generated_at}")
        a(f"- Approval ID: {attempt.approval_id}")
        a(f"- Patch proposal ID: {attempt.patch_proposal_id}")
        a(f"- Application plan ID: {attempt.application_plan_id}")
        a(f"- Status: {attempt.status}")
        a(f"- Approval confirmed: {attempt.approval_confirmed}")
        a(f"- Rollback snapshot required: {attempt.rollback_snapshot_required}")
        a(f"- Rollback snapshot present: {attempt.rollback_snapshot_present}")
        a(f"- Applies changes: {attempt.applies_changes}")
        a(f"- Writes files: {attempt.writes_files}")
        a(f"- Executes commands: {attempt.executes_commands}")
        a(f"- Commits changes: {attempt.commits_changes}")
        a(f"- Generates patch: {attempt.generates_patch}")
        a("")
        a("## Target Files")
        _append_list(lines, attempt.target_files)
        a("## Blockers")
        _append_list(lines, attempt.blockers)
        a("## Required Next Controls")
        _append_list(lines, attempt.required_next_controls)
        a("## Safety Notes")
        _append_list(lines, attempt.safety_notes)
        return "\n".join(lines)


def _required_next_controls():
    return [
        "Stage 6.5 rollback snapshot must be created before any file write.",
        "Patch preview must remain required before apply.",
        "Workspace profile and file allowlist protections must remain enforced.",
        "Post-apply verification is still required after any future apply stage.",
    ]


def _safety_notes():
    return [
        "Stage 6.4 fail closed until rollback snapshots exist.",
        "No file writes occur before rollback snapshots.",
        "No patches are generated.",
        "No changes are applied.",
        "No commands are executed.",
        "No git commits are created.",
        "No Ollama or external-agent calls are made.",
        "No loops, jobs, or framework definitions are mutated.",
    ]


def _append_list(lines, items):
    if not items:
        lines.append("- (none)")
    for item in items:
        lines.append(f"- {item}")
    lines.append("")
