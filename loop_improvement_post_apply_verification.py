"""Post-Apply Verification Runner (Stage 6.6).

This stage builds metadata-only verification plans and reports for existing
patch application attempts. It recommends manual commands and checks but never
executes commands, writes source files, applies patches, restores files, calls
Ollama, creates loops/jobs, commits, or mutates framework definitions.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database
import loop_improvement_patch_application
import loop_improvement_patch_proposals


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "post_apply_verification_reports")
PLAN_STATUSES = {"planned", "manually_verified", "failed", "blocked", "deferred"}
CHECK_STATUSES = {"pending", "passed", "failed", "blocked", "skipped"}
REPORT_STATUSES = {"PASS", "PASS_WITH_WARNINGS", "FAIL", "BLOCKED", "PENDING"}


@dataclass
class PostApplyVerificationCheck:
    name: str
    category: str
    command: str
    required: bool
    expected_result: str
    status: str = "pending"
    manual_result: str = ""
    evidence: str = ""
    notes: str = ""


@dataclass
class PostApplyVerificationPlan:
    id: int
    application_attempt_id: int
    patch_proposal_id: int
    approval_id: int
    generated_at: str
    status: str
    summary: str
    verification_commands: List[dict] = field(default_factory=list)
    checks: List[PostApplyVerificationCheck] = field(default_factory=list)
    required_checks: int = 0
    optional_checks: int = 0
    risk_level: str = "medium"
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)


@dataclass
class PostApplyVerificationReport:
    id: int
    verification_plan_id: int
    generated_at: str
    overall_status: str
    total_checks: int
    required_checks: int
    optional_checks: int
    passed_checks: int
    failed_checks: int
    blocked_checks: int
    pending_checks: int
    checks: List[PostApplyVerificationCheck] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)


@dataclass
class PostApplyVerificationMarkdownReport:
    verification_report_id: int
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
    return PostApplyVerificationCheck(**data)


def plan_from_row(row):
    return PostApplyVerificationPlan(
        id=row["id"],
        application_attempt_id=row["application_attempt_id"],
        patch_proposal_id=row["patch_proposal_id"],
        approval_id=row["approval_id"],
        generated_at=row["generated_at"] or "",
        status=row["status"] or "",
        summary=row["summary"] or "",
        verification_commands=_safe_json_loads(
            row["verification_commands_json"], []),
        checks=[
            check_from_dict(item)
            for item in _safe_json_loads(row["checks_json"], [])
        ],
        required_checks=row["required_checks"] or 0,
        optional_checks=row["optional_checks"] or 0,
        risk_level=row["risk_level"] or "medium",
        blockers=_safe_json_loads(row["blockers_json"], []),
        warnings=_safe_json_loads(row["warnings_json"], []),
        next_steps=_safe_json_loads(row["next_steps_json"], []),
    )


def report_from_row(row):
    return PostApplyVerificationReport(
        id=row["id"],
        verification_plan_id=row["verification_plan_id"],
        generated_at=row["generated_at"] or "",
        overall_status=row["overall_status"] or "",
        total_checks=row["total_checks"] or 0,
        required_checks=row["required_checks"] or 0,
        optional_checks=row["optional_checks"] or 0,
        passed_checks=row["passed_checks"] or 0,
        failed_checks=row["failed_checks"] or 0,
        blocked_checks=row["blocked_checks"] or 0,
        pending_checks=row["pending_checks"] or 0,
        checks=[
            check_from_dict(item)
            for item in _safe_json_loads(row["checks_json"], [])
        ],
        blockers=_safe_json_loads(row["blockers_json"], []),
        warnings=_safe_json_loads(row["warnings_json"], []),
        next_steps=_safe_json_loads(row["next_steps_json"], []),
    )


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


class PostApplyVerificationEngine:
    def __init__(self, conn):
        self.conn = conn

    def create_plan(self, application_attempt_id):
        row = database.get_loop_improvement_patch_application_attempt(
            self.conn, int(application_attempt_id))
        if row is None:
            raise ValueError(
                f"no loop improvement patch application attempt {application_attempt_id}"
            )
        attempt = loop_improvement_patch_application.application_attempt_from_row(row)
        target_files = self._target_files(attempt)
        risk_level = _risk_level(target_files)
        commands = _verification_commands(target_files, risk_level)
        checks = _checks_from_commands(commands)
        checks.extend(_metadata_checks(target_files))
        required_checks = sum(1 for check in checks if check.required)
        optional_checks = len(checks) - required_checks
        blockers = []
        if not target_files:
            blockers.append("No target files were recorded on the application attempt.")
        return PostApplyVerificationPlan(
            id=0,
            application_attempt_id=int(application_attempt_id),
            patch_proposal_id=attempt.patch_proposal_id,
            approval_id=attempt.approval_id,
            generated_at=_now_iso(),
            status="planned",
            summary=(
                "Manual post-apply verification plan for application attempt "
                f"{application_attempt_id}; commands are recommendations only."
            ),
            verification_commands=commands,
            checks=checks,
            required_checks=required_checks,
            optional_checks=optional_checks,
            risk_level=risk_level,
            blockers=blockers,
            warnings=_warnings(risk_level),
            next_steps=_next_steps(),
        )

    def save_plan(self, plan):
        return database.save_post_apply_verification_plan(
            self.conn,
            plan.application_attempt_id,
            plan.patch_proposal_id,
            plan.approval_id,
            plan.generated_at,
            plan.status,
            plan.summary,
            json.dumps(plan.verification_commands, sort_keys=True),
            json.dumps([check_to_dict(c) for c in plan.checks], sort_keys=True),
            plan.required_checks,
            plan.optional_checks,
            plan.risk_level,
            json.dumps(plan.blockers, sort_keys=True),
            json.dumps(plan.warnings, sort_keys=True),
            json.dumps(plan.next_steps, sort_keys=True),
        )

    def create_report(self, plan_id):
        row = database.get_post_apply_verification_plan(self.conn, int(plan_id))
        if row is None:
            raise ValueError(f"no post-apply verification plan {plan_id}")
        plan = plan_from_row(row)
        checks = _checks_for_plan_status(plan)
        passed = sum(1 for check in checks if check.status == "passed")
        failed = sum(1 for check in checks if check.status == "failed")
        blocked = sum(1 for check in checks if check.status == "blocked")
        pending = sum(1 for check in checks if check.status == "pending")
        return PostApplyVerificationReport(
            id=0,
            verification_plan_id=int(plan_id),
            generated_at=_now_iso(),
            overall_status=_overall_status(plan, failed, blocked, pending),
            total_checks=len(checks),
            required_checks=plan.required_checks,
            optional_checks=plan.optional_checks,
            passed_checks=passed,
            failed_checks=failed,
            blocked_checks=blocked,
            pending_checks=pending,
            checks=checks,
            blockers=list(plan.blockers),
            warnings=list(plan.warnings),
            next_steps=_report_next_steps(plan),
        )

    def save_report(self, report):
        return database.save_post_apply_verification_report(
            self.conn,
            report.verification_plan_id,
            report.generated_at,
            report.overall_status,
            report.total_checks,
            report.required_checks,
            report.optional_checks,
            report.passed_checks,
            report.failed_checks,
            report.blocked_checks,
            report.pending_checks,
            json.dumps([check_to_dict(c) for c in report.checks], sort_keys=True),
            json.dumps(report.blockers, sort_keys=True),
            json.dumps(report.warnings, sort_keys=True),
            json.dumps(report.next_steps, sort_keys=True),
        )

    def save_markdown_report(self, report_id, report):
        content = self.render_markdown(report, report_id)
        path = self._new_report_path(report_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_post_apply_verification_markdown_report(
            self.conn, report_id, path, "markdown", chash, nbytes)
        return PostApplyVerificationMarkdownReport(
            verification_report_id=report_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def render_markdown(self, report, report_id=None):
        lines = []
        a = lines.append
        a("# Post-Apply Verification Report")
        a("")
        a("## Summary")
        if report_id is not None:
            a(f"- Report ID: {report_id}")
        a(f"- Verification plan ID: {report.verification_plan_id}")
        a(f"- Generated at: {report.generated_at}")
        a(f"- Overall status: {report.overall_status}")
        a(f"- Total checks: {report.total_checks}")
        a(f"- Required checks: {report.required_checks}")
        a(f"- Optional checks: {report.optional_checks}")
        a("")
        a("## Verification Commands")
        command_checks = [check for check in report.checks if check.command]
        if not command_checks:
            a("(none)")
        for check in command_checks:
            a(f"- `{check.command}`")
            a(f"  - Required: {check.required}")
            a(f"  - Status: {check.status}")
            a(f"  - Expected: {check.expected_result}")
        a("")
        a("## Checks")
        if not report.checks:
            a("(none)")
        for check in report.checks:
            a(f"- {check.name} [{check.status}]")
            a(f"  - Category: {check.category}")
            a(f"  - Required: {check.required}")
            if check.notes:
                a(f"  - Notes: {check.notes}")
        a("")
        a("## Blockers")
        _markdown_list(a, report.blockers)
        a("")
        a("## Warnings")
        _markdown_list(a, report.warnings)
        a("")
        a("## Next Steps")
        _markdown_list(a, report.next_steps)
        a("")
        a("## Safety Notes")
        for note in _safety_notes():
            a(f"- {note}")
        a("")
        return "\n".join(lines)

    def _target_files(self, attempt):
        target_files = list(attempt.target_files or [])
        row = database.get_loop_improvement_patch_proposal(
            self.conn, attempt.patch_proposal_id)
        if row is not None:
            proposal = loop_improvement_patch_proposals.proposal_from_row(row)
            target_files.extend(proposal.target_files or [])
        return _dedupe(target_files)

    def _new_report_path(self, report_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"post_apply_verification_{int(report_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("post-apply verification report path escaped directory")
        return target


def _verification_commands(target_files, risk_level):
    commands = [
        _command("python3 -m py_compile *.py", True, "syntax"),
        _command("python3 audit_hotfix.py", True, "security"),
        _command("python3 agent_handoff.py --check", True, "handoff"),
    ]
    for command in _focused_test_commands(target_files):
        commands.append(_command(command, True, "focused_tests"))
    broad_required = risk_level == "high"
    commands.append(_command(
        "python3 -m unittest discover",
        broad_required,
        "broad_regression",
        "Manual broad regression; required for high-risk changes.",
    ))
    return _dedupe_commands(commands)


def _focused_test_commands(target_files):
    commands = []
    for path in target_files:
        base = os.path.basename(path)
        if base.startswith("loop_improvement_") and base.endswith(".py"):
            test_name = "test_" + base
            if os.path.exists(os.path.join(PROJECT_ROOT, test_name)):
                commands.append(f"python3 -m unittest {test_name}")
    if any(os.path.basename(p) in ("database.py", "main.py") for p in target_files):
        stage6_tests = [
            "test_loop_improvement_application_planner.py",
            "test_loop_improvement_patch_proposals.py",
            "test_loop_improvement_patch_dry_run.py",
            "test_loop_improvement_patch_approval.py",
            "test_loop_improvement_patch_application.py",
            "test_loop_improvement_rollback_snapshot.py",
        ]
        existing = [
            name for name in stage6_tests
            if os.path.exists(os.path.join(PROJECT_ROOT, name))
        ]
        if existing:
            commands.append("python3 -m unittest " + " ".join(existing))
    return _dedupe(commands)


def _metadata_checks(target_files):
    checks = [
        PostApplyVerificationCheck(
            name="Review patch application outcome metadata",
            category="manual_review",
            command="",
            required=True,
            expected_result=(
                "Operator confirms the application attempt status, target files, "
                "rollback snapshot path, and approval linkage are correct."
            ),
            notes="Manual review only; no command execution is performed.",
        ),
        PostApplyVerificationCheck(
            name="Confirm rollback path remains available",
            category="rollback",
            command="",
            required=True,
            expected_result="Rollback snapshot metadata is present before closure.",
            notes="Failure must stop and preserve rollback path.",
        ),
    ]
    docs = [path for path in target_files if os.path.basename(path) in (
        "README.md", "HANDOFF.md")]
    if docs:
        checks.append(PostApplyVerificationCheck(
            name="Review documentation-only changes",
            category="documentation",
            command="",
            required=False,
            expected_result="Documentation accurately describes the current behavior.",
            notes="Manual docs review for " + ", ".join(docs),
        ))
    return checks


def _checks_from_commands(commands):
    checks = []
    for item in commands:
        checks.append(PostApplyVerificationCheck(
            name=item["name"],
            category=item["category"],
            command=item["command"],
            required=item["required"],
            expected_result=item["expected_result"],
            notes=item["notes"],
        ))
    return checks


def _checks_for_plan_status(plan):
    checks = [
        PostApplyVerificationCheck(**check_to_dict(check))
        for check in plan.checks
    ]
    if plan.status == "manually_verified":
        for check in checks:
            check.status = "passed"
            check.manual_result = "Marked manually verified by operator."
    elif plan.status == "failed":
        for check in checks:
            if check.required:
                check.status = "failed"
                check.manual_result = "Marked failed by operator."
    elif plan.status == "blocked":
        for check in checks:
            if check.required:
                check.status = "blocked"
                check.manual_result = "Marked blocked by operator."
    return checks


def _overall_status(plan, failed, blocked, pending):
    if failed or plan.status == "failed":
        return "FAIL"
    if blocked or plan.status == "blocked":
        return "BLOCKED"
    if pending or plan.status in ("planned", "deferred"):
        return "PENDING"
    if plan.warnings:
        return "PASS_WITH_WARNINGS"
    return "PASS"


def _report_next_steps(plan):
    if plan.status == "manually_verified":
        return ["Record outcome and proceed only with explicit human direction."]
    if plan.status == "failed":
        return ["Stop; preserve rollback path and investigate failed checks."]
    if plan.status == "blocked":
        return ["Stop; resolve blockers before any further application work."]
    if plan.status == "deferred":
        return ["Verification deferred; do not treat the application as complete."]
    return list(plan.next_steps)


def _risk_level(target_files):
    names = {os.path.basename(path) for path in target_files}
    if {"database.py", "main.py"} & names:
        return "high"
    if any(name.startswith("loop_improvement_") for name in names):
        return "high"
    if names and names <= {"README.md", "HANDOFF.md", "AGENTS.md"}:
        return "low"
    return "medium"


def _command(command, required, category, notes="Manual command only."):
    return {
        "name": _command_name(category),
        "category": category,
        "command": command,
        "required": bool(required),
        "execution": "manual",
        "expected_result": "Command exits 0 when manually run by an operator.",
        "notes": notes,
    }


def _command_name(category):
    names = {
        "syntax": "Compile Python files",
        "security": "Run safety audit",
        "handoff": "Validate agent handoff",
        "focused_tests": "Run focused regression tests",
        "broad_regression": "Run broad regression suite",
    }
    return names.get(category, category.replace("_", " ").title())


def _warnings(risk_level):
    warnings = [
        "Stage 6.6 does not execute commands; every verification command is manual.",
        "No command_results rows are created by post-apply verification planning.",
        "Invalid or unavailable Ollama hosts have no effect on this subsystem.",
    ]
    if risk_level == "high":
        warnings.append("High-risk target files require manual broad regression.")
    return warnings


def _next_steps():
    return [
        "Manually review the patch application attempt and rollback snapshot.",
        "Manually run required verification commands in an approved environment.",
        "Update post-apply verification status only after reviewing evidence.",
        "Stop and preserve rollback path if any required check fails or blocks.",
    ]


def _safety_notes():
    return [
        "Dry-run and human approval remain prerequisites from earlier Stage 6 gates.",
        "Patch preview and rollback snapshot must remain available before closure.",
        "No command is executed by Stage 6.6.",
        "No source file, loop definition, agent definition, workspace profile, or job is mutated.",
        "No autonomous recursive self-modification, hidden model call, or external-agent execution occurs.",
    ]


def _markdown_list(append, items):
    if not items:
        append("(none)")
        return
    for item in items:
        append(f"- {item}")


def _dedupe(items):
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _dedupe_commands(commands):
    seen = set()
    out = []
    for item in commands:
        command = item.get("command")
        if command not in seen:
            seen.add(command)
            out.append(item)
    return out
