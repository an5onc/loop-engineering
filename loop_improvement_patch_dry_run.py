"""Loop Improvement Patch Dry-Run Validator (Stage 6.2).

This stage validates Stage 6.1 patch proposal metadata before any future patch
generation. It does not generate patches, apply changes, execute commands, read
source file contents, call Ollama, create loops/jobs, or commit. Writes are
limited to dry-run validation metadata and optional Markdown reports under
loop_improvement_patch_dry_run_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database
import loop_improvement_patch_proposals


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "loop_improvement_patch_dry_run_reports")
PROTECTED_PATH_FRAGMENTS = (
    ".env",
    "secret",
    "secrets",
    "private_key",
    "id_rsa",
    ".ssh",
)


@dataclass
class LoopImprovementPatchDryRunCheck:
    name: str
    status: str
    message: str
    evidence: dict = field(default_factory=dict)


@dataclass
class LoopImprovementPatchDryRunValidation:
    generated_at: str
    patch_proposal_id: int
    application_plan_id: int
    overall_status: str
    total_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int
    ready_for_human_approval: bool
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    safety_notes: List[str] = field(default_factory=list)
    required_next_controls: List[str] = field(default_factory=list)
    checks: List[LoopImprovementPatchDryRunCheck] = field(default_factory=list)
    generates_patch: bool = False
    applies_changes: bool = False
    executes_commands: bool = False
    reads_file_contents: bool = False


@dataclass
class LoopImprovementPatchDryRunMarkdownReport:
    validation_id: int
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


def check_to_dict(check):
    return asdict(check)


def check_from_dict(data):
    return LoopImprovementPatchDryRunCheck(**data)


def validation_from_row(row):
    return LoopImprovementPatchDryRunValidation(
        generated_at=row["generated_at"] or "",
        patch_proposal_id=row["patch_proposal_id"],
        application_plan_id=row["application_plan_id"],
        overall_status=row["overall_status"] or "",
        total_checks=row["total_checks"] or 0,
        passed_checks=row["passed_checks"] or 0,
        warning_checks=row["warning_checks"] or 0,
        failed_checks=row["failed_checks"] or 0,
        ready_for_human_approval=bool(row["ready_for_human_approval"]),
        blockers=_safe_json_loads(row["blockers_json"], []),
        warnings=_safe_json_loads(row["warnings_json"], []),
        safety_notes=_safe_json_loads(row["safety_notes_json"], []),
        required_next_controls=_safe_json_loads(
            row["required_next_controls_json"], []),
        checks=[
            check_from_dict(c)
            for c in _safe_json_loads(row["checks_json"], [])
        ],
        generates_patch=bool(row["generates_patch"]),
        applies_changes=bool(row["applies_changes"]),
        executes_commands=bool(row["executes_commands"]),
        reads_file_contents=bool(row["reads_file_contents"]),
    )


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


class LoopImprovementPatchDryRunValidator:
    def __init__(self, conn):
        self.conn = conn

    def validate_patch_proposal(self, patch_proposal_id):
        row = database.get_loop_improvement_patch_proposal(
            self.conn, int(patch_proposal_id))
        if row is None:
            raise ValueError(f"no loop improvement patch proposal {patch_proposal_id}")
        proposal = loop_improvement_patch_proposals.proposal_from_row(row)
        checks = self._checks(proposal)
        blockers = [
            check.message for check in checks
            if check.status == "FAIL"
        ]
        warnings = [
            check.message for check in checks
            if check.status == "WARN"
        ]
        failed = sum(1 for check in checks if check.status == "FAIL")
        warned = sum(1 for check in checks if check.status == "WARN")
        passed = sum(1 for check in checks if check.status == "PASS")
        status = "FAIL" if failed else ("PASS WITH WARNINGS" if warned else "PASS")
        return LoopImprovementPatchDryRunValidation(
            generated_at=_now_iso(),
            patch_proposal_id=int(patch_proposal_id),
            application_plan_id=proposal.application_plan_id,
            overall_status=status,
            total_checks=len(checks),
            passed_checks=passed,
            warning_checks=warned,
            failed_checks=failed,
            ready_for_human_approval=failed == 0,
            blockers=blockers,
            warnings=warnings,
            safety_notes=_safety_notes(),
            required_next_controls=_required_next_controls(),
            checks=checks,
            generates_patch=False,
            applies_changes=False,
            executes_commands=False,
            reads_file_contents=False,
        )

    def save_validation(self, validation):
        validation_id = database.save_loop_improvement_patch_dry_run_validation(
            self.conn,
            validation.generated_at,
            validation.patch_proposal_id,
            validation.application_plan_id,
            validation.overall_status,
            validation.total_checks,
            validation.passed_checks,
            validation.warning_checks,
            validation.failed_checks,
            validation.ready_for_human_approval,
            json.dumps(validation.blockers, sort_keys=True),
            json.dumps(validation.warnings, sort_keys=True),
            json.dumps(validation.safety_notes, sort_keys=True),
            json.dumps(validation.required_next_controls, sort_keys=True),
            json.dumps([check_to_dict(c) for c in validation.checks], sort_keys=True),
            validation.generates_patch,
            validation.applies_changes,
            validation.executes_commands,
            validation.reads_file_contents,
        )
        for check in validation.checks:
            database.save_loop_improvement_patch_dry_run_check(
                self.conn,
                validation_id,
                check.name,
                check.status,
                check.message,
                json.dumps(check.evidence, sort_keys=True),
            )
        database.save_loop_improvement_patch_dry_run_validation_event(
            self.conn,
            validation_id,
            "created",
            json.dumps({
                "patch_proposal_id": validation.patch_proposal_id,
                "overall_status": validation.overall_status,
                "failed_checks": validation.failed_checks,
            }, sort_keys=True),
        )
        return validation_id

    def save_markdown_report(self, validation_id, validation):
        content = self.render_markdown(validation, validation_id)
        path = self._new_report_path(validation_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_loop_improvement_patch_dry_run_markdown_report(
            self.conn, validation_id, path, "markdown", chash, nbytes)
        return LoopImprovementPatchDryRunMarkdownReport(
            validation_id=validation_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def _checks(self, proposal):
        return [
            _proposal_status_check(proposal),
            _metadata_only_flags_check(proposal),
            _target_files_present_check(proposal),
            _target_file_allowlist_check(proposal),
            _no_file_content_reads_check(proposal),
            _no_command_execution_check(),
            _human_approval_required_check(proposal),
            _rollback_required_check(proposal),
        ]

    def _new_report_path(self, validation_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = (
            f"loop_improvement_patch_dry_run_{int(validation_id)}_{_now_stamp()}.md"
        )
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError(
                "patch dry-run report path escaped loop_improvement_patch_dry_run_reports/")
        return target

    def render_markdown(self, validation, validation_id=None):
        lines = []
        a = lines.append
        a("# Loop Improvement Patch Dry-Run Validation")
        a("")
        a("## Summary")
        if validation_id is not None:
            a(f"- Validation ID: {validation_id}")
        a(f"- Generated at: {validation.generated_at}")
        a(f"- Patch proposal ID: {validation.patch_proposal_id}")
        a(f"- Application plan ID: {validation.application_plan_id}")
        a(f"- Overall status: {validation.overall_status}")
        a(f"- Ready for human approval: {validation.ready_for_human_approval}")
        a(f"- Total checks: {validation.total_checks}")
        a(f"- Passed: {validation.passed_checks}")
        a(f"- Warnings: {validation.warning_checks}")
        a(f"- Failed: {validation.failed_checks}")
        a(f"- Generates patch: {validation.generates_patch}")
        a(f"- Applies changes: {validation.applies_changes}")
        a(f"- Executes commands: {validation.executes_commands}")
        a(f"- Reads file contents: {validation.reads_file_contents}")
        a("")
        a("## Checks")
        if not validation.checks:
            a("- (none)")
        for check in validation.checks:
            a(f"- [{check.status}] {check.name}")
            a(f"  message: {check.message}")
            a(f"  evidence: {json.dumps(check.evidence, sort_keys=True)}")
        a("")
        a("## Blockers")
        _append_list(lines, validation.blockers)
        a("## Warnings")
        _append_list(lines, validation.warnings)
        a("## Required Next Controls")
        _append_list(lines, validation.required_next_controls)
        a("## Safety Notes")
        _append_list(lines, validation.safety_notes)
        return "\n".join(lines)


def _proposal_status_check(proposal):
    ok = proposal.status in ("proposed", "validated", "planned")
    return LoopImprovementPatchDryRunCheck(
        name="proposal_status",
        status="PASS" if ok else "FAIL",
        message=(
            "patch proposal status is eligible for dry-run validation"
            if ok else f"patch proposal status is not eligible: {proposal.status}"
        ),
        evidence={"status": proposal.status},
    )


def _metadata_only_flags_check(proposal):
    unsafe = {
        "generates_unified_diff": proposal.generates_unified_diff,
        "writes_patch_file": proposal.writes_patch_file,
        "applies_changes": proposal.applies_changes,
        "reads_file_contents": proposal.reads_file_contents,
    }
    ok = not any(unsafe.values())
    return LoopImprovementPatchDryRunCheck(
        name="metadata_only_flags",
        status="PASS" if ok else "FAIL",
        message=(
            "patch proposal is metadata-only"
            if ok else "patch proposal contains unsafe generation or mutation flags"
        ),
        evidence=unsafe,
    )


def _target_files_present_check(proposal):
    target_files = list(proposal.target_files or [])
    ok = bool(target_files) and len(proposal.items or []) >= len(target_files)
    return LoopImprovementPatchDryRunCheck(
        name="target_files_present",
        status="PASS" if ok else "FAIL",
        message=(
            "patch proposal includes target file metadata"
            if ok else "patch proposal has no target file metadata"
        ),
        evidence={
            "target_files": target_files,
            "item_count": len(proposal.items or []),
        },
    )


def _target_file_allowlist_check(proposal):
    problems = []
    for target_file in proposal.target_files or []:
        problem = _target_file_problem(target_file)
        if problem:
            problems.append(problem)
    ok = not problems
    return LoopImprovementPatchDryRunCheck(
        name="target_file_allowlist",
        status="PASS" if ok else "FAIL",
        message=(
            "target files are relative, allowlisted metadata paths"
            if ok else "; ".join(problems)
        ),
        evidence={"target_files": proposal.target_files or []},
    )


def _target_file_problem(path):
    if not path:
        return "target file is empty"
    if os.path.isabs(path):
        return f"target file is outside the allowed relative workspace: {path}"
    normalized = os.path.normpath(path)
    if normalized == "." or normalized.startswith("..") or ".." in normalized.split(os.sep):
        return f"target file is outside the allowed relative workspace: {path}"
    lowered = normalized.lower()
    for fragment in PROTECTED_PATH_FRAGMENTS:
        if fragment in lowered:
            return f"target file references protected content: {path}"
    return None


def _no_file_content_reads_check(proposal):
    ok = not proposal.reads_file_contents
    return LoopImprovementPatchDryRunCheck(
        name="no_file_content_reads",
        status="PASS" if ok else "FAIL",
        message=(
            "No source file contents are read."
            if ok else "patch proposal requires source file content reads"
        ),
        evidence={"reads_file_contents": proposal.reads_file_contents},
    )


def _no_command_execution_check():
    return LoopImprovementPatchDryRunCheck(
        name="no_command_execution",
        status="PASS",
        message="No commands are executed during dry-run validation.",
        evidence={"executes_commands": False},
    )


def _human_approval_required_check(proposal):
    approvals = " ".join(proposal.required_approvals or []).lower()
    ok = "human approval" in approvals
    return LoopImprovementPatchDryRunCheck(
        name="human_approval_required",
        status="PASS" if ok else "FAIL",
        message=(
            "human approval controls are present"
            if ok else "human approval controls are missing"
        ),
        evidence={"required_approvals": proposal.required_approvals or []},
    )


def _rollback_required_check(proposal):
    rollback = " ".join(proposal.rollback_requirements or []).lower()
    ok = "rollback" in rollback
    return LoopImprovementPatchDryRunCheck(
        name="rollback_required",
        status="PASS" if ok else "FAIL",
        message=(
            "rollback requirements are present"
            if ok else "rollback requirements are missing"
        ),
        evidence={"rollback_requirements": proposal.rollback_requirements or []},
    )


def _required_next_controls():
    return [
        "human approval required before patch generation",
        "patch preview required before any apply stage",
        "rollback snapshot required before any file write",
        "workspace profile and file allowlist must remain enforced",
    ]


def _safety_notes():
    return [
        "Stage 6.2 is dry-run validation only.",
        "No patches are generated.",
        "No changes are applied.",
        "No commands are executed.",
        "No source file contents are read.",
        "No Ollama or external-agent calls are made.",
        "No loops, jobs, commits, or framework definitions are mutated.",
    ]


def _append_list(lines, items):
    if not items:
        lines.append("- (none)")
    for item in items:
        lines.append(f"- {item}")
    lines.append("")
