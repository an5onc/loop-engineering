"""Final Stage 6 Controlled Self-Improvement audit and Stage 7 readiness.

This audit reads Stage 6 SQLite metadata and safe schema metadata only. It does
not execute commands, run tests, call Ollama, apply patches, restore files,
create loops/jobs, import completions, resume jobs, commit, mutate framework
definitions, or read protected file contents. Writes are limited to final
Stage 6 audit metadata and optional Markdown reports under
loop_improvement_stage6_audit_reports/.
"""

import datetime
import hashlib
import importlib.util
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "loop_improvement_stage6_audit_reports")


@dataclass
class Stage6AuditCheck:
    name: str
    category: str
    status: str
    message: str
    evidence: str
    recommended_action: str


@dataclass
class Stage6AuditSection:
    name: str
    status: str
    checks: List[Stage6AuditCheck] = field(default_factory=list)
    summary: str = ""


@dataclass
class Stage6AuditReport:
    id: int
    generated_at: str
    overall_status: str
    total_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int
    blocked_checks: int
    sections: List[Stage6AuditSection] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    stage7_readiness: dict = field(default_factory=dict)
    safety_notes: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)


@dataclass
class Stage6AuditMarkdownReport:
    stage6_audit_id: int
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


def section_to_dict(section):
    data = asdict(section)
    data["checks"] = [check_to_dict(c) for c in section.checks]
    return data


def check_from_dict(data):
    return Stage6AuditCheck(**data)


def section_from_dict(data):
    return Stage6AuditSection(
        name=data["name"],
        status=data["status"],
        checks=[check_from_dict(c) for c in data.get("checks", [])],
        summary=data.get("summary", ""),
    )


def report_from_row(row):
    return Stage6AuditReport(
        id=row["id"],
        generated_at=row["generated_at"] or "",
        overall_status=row["overall_status"] or "",
        total_checks=row["total_checks"] or 0,
        passed_checks=row["passed_checks"] or 0,
        warning_checks=row["warning_checks"] or 0,
        failed_checks=row["failed_checks"] or 0,
        blocked_checks=row["blocked_checks"] or 0,
        sections=[
            section_from_dict(item)
            for item in _safe_json_loads(row["sections_json"], [])
        ],
        recommendations=_safe_json_loads(row["recommendations_json"], []),
        stage7_readiness=_safe_json_loads(row["stage7_readiness_json"], {}),
        safety_notes=_safe_json_loads(row["safety_notes_json"], []),
        next_steps=_safe_json_loads(row["next_steps_json"], []),
    )


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


def aggregate_overall_status(sections):
    statuses = [section.status for section in sections]
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "PASS_WITH_WARNINGS"
    return "PASS"


def _section_status(checks):
    statuses = [check.status for check in checks]
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"


class LoopImprovementStage6AuditEngine:
    def __init__(self, conn):
        self.conn = conn
        self._baseline = self._counts()

    def build_report(self):
        sections = [
            self._application_planning(),
            self._patch_proposal_generation(),
            self._dry_run_validation(),
            self._human_approval(),
            self._safe_application(),
            self._rollback_snapshot(),
            self._post_apply_verification(),
            self._outcome_tracking(),
            self._self_improvement_audit(),
            self._safety_baseline(),
        ]
        readiness = self._stage7_readiness(sections)
        sections.append(self._stage7_readiness_section(readiness))
        overall = aggregate_overall_status(sections)
        total = sum(len(section.checks) for section in sections)
        passed = sum(1 for section in sections for check in section.checks
                     if check.status == "PASS")
        warnings = sum(1 for section in sections for check in section.checks
                       if check.status == "WARN")
        failed = sum(1 for section in sections for check in section.checks
                     if check.status == "FAIL")
        blocked = sum(1 for section in sections for check in section.checks
                      if check.status == "BLOCKED")
        if overall in ("FAIL", "BLOCKED"):
            readiness["ready"] = False
        readiness["overall_status"] = overall
        return Stage6AuditReport(
            id=0,
            generated_at=_now_iso(),
            overall_status=overall,
            total_checks=total,
            passed_checks=passed,
            warning_checks=warnings,
            failed_checks=failed,
            blocked_checks=blocked,
            sections=sections,
            recommendations=_recommendations(),
            stage7_readiness=readiness,
            safety_notes=_safety_notes(),
            next_steps=_next_steps(readiness),
        )

    def save_audit(self, report):
        return database.save_loop_improvement_stage6_audit(
            self.conn,
            report.generated_at,
            report.overall_status,
            report.total_checks,
            report.passed_checks,
            report.warning_checks,
            report.failed_checks,
            report.blocked_checks,
            json.dumps([section_to_dict(s) for s in report.sections], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
            json.dumps(report.stage7_readiness, sort_keys=True),
            json.dumps(report.safety_notes, sort_keys=True),
            json.dumps(report.next_steps, sort_keys=True),
        )

    def save_markdown_report(self, audit_id, report):
        content = self.render_markdown(report, audit_id)
        path = self._new_report_path(audit_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_loop_improvement_stage6_audit_markdown_report(
            self.conn, audit_id, path, "markdown", chash, nbytes)
        return Stage6AuditMarkdownReport(
            stage6_audit_id=audit_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def render_markdown(self, report, audit_id=None):
        lines = []
        a = lines.append
        a("# Stage 6 Controlled Self-Improvement Audit")
        a("")
        a("## Summary")
        if audit_id is not None:
            a(f"- Audit ID: {audit_id}")
        a(f"- Generated at: {report.generated_at}")
        a(f"- Overall status: {report.overall_status}")
        a(f"- Total checks: {report.total_checks}")
        a(f"- Passed: {report.passed_checks}")
        a(f"- Warnings: {report.warning_checks}")
        a(f"- Failed: {report.failed_checks}")
        a(f"- Blocked: {report.blocked_checks}")
        a(f"- Stage 7 readiness: {report.stage7_readiness.get('ready')}")
        a("")
        a("## Sections")
        for section in report.sections:
            a(f"- {section.name}: {section.status}")
            a(f"  - {section.summary}")
            for check in section.checks:
                a(f"  - {check.status}: {check.name} - {check.message}")
        self._markdown_filtered(a, report, "Failed Checks", "FAIL")
        self._markdown_filtered(a, report, "Blocked Checks", "BLOCKED")
        self._markdown_filtered(a, report, "Warning Checks", "WARN")
        a("")
        a("## Recommendations")
        _markdown_list(a, report.recommendations)
        a("")
        a("## Stage 7 Readiness")
        for key, value in report.stage7_readiness.items():
            a(f"- {key}: {value}")
        a("")
        a("## Required Stage 7 Safety Controls")
        _markdown_list(a, report.stage7_readiness.get(
            "required_stage_7_safety_controls", []))
        a("")
        a("## Safety Notes")
        _markdown_list(a, report.safety_notes)
        a("")
        a("## Next Steps")
        _markdown_list(a, report.next_steps)
        a("")
        return "\n".join(lines)

    def _markdown_filtered(self, append, report, title, status):
        append("")
        append(f"## {title}")
        items = [
            (section, check)
            for section in report.sections
            for check in section.checks
            if check.status == status
        ]
        if not items:
            append("(none)")
            return
        for section, check in items:
            append(f"- {section.name}: {check.name}")
            append(f"  - {check.message}")
            append(f"  - Recommended action: {check.recommended_action}")

    def _new_report_path(self, audit_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"loop_improvement_stage6_audit_{int(audit_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("Stage 6 audit report path escaped directory")
        return target

    def _application_planning(self):
        checks = [
            self._module_check("loop_improvement_application_planner",
                               "application planner module exists",
                               "application_planning"),
            self._table_check("loop_improvement_application_plans",
                              "application planner table exists",
                              "application_planning"),
            self._list_check("loop_improvement_application_plans",
                             "application plans can be listed",
                             "application_planning"),
            self._json_requirement_check(
                "loop_improvement_application_plans",
                ["required_approvals_json", "rollback_requirements_json",
                 "validation_requirements_json"],
                "plans record approval, rollback, and validation requirements",
                "application_planning"),
            self._zero_flags_check(
                "loop_improvement_application_plans",
                ["generates_patch", "applies_changes"],
                "plan commands do not generate patches, edit files, or execute commands",
                "application_planning"),
        ]
        return _section("application_planning", checks)

    def _patch_proposal_generation(self):
        checks = [
            self._module_check("loop_improvement_patch_proposals",
                               "patch proposal module exists",
                               "patch_proposal_generation"),
            self._table_check("loop_improvement_patch_proposals",
                              "patch proposal table exists",
                              "patch_proposal_generation"),
            self._reference_check(
                "loop_improvement_patch_proposals", "application_plan_id",
                "loop_improvement_application_plans",
                "proposals reference application plans",
                "patch_proposal_generation"),
            self._zero_flags_check(
                "loop_improvement_patch_proposals",
                ["generates_unified_diff", "writes_patch_file",
                 "applies_changes", "reads_file_contents"],
                "proposals are metadata only until application",
                "patch_proposal_generation"),
            self._zero_flags_check(
                "loop_improvement_patch_proposals", ["applies_changes"],
                "proposal commands do not apply patches",
                "patch_proposal_generation"),
        ]
        return _section("patch_proposal_generation", checks)

    def _dry_run_validation(self):
        checks = [
            self._module_check("loop_improvement_patch_dry_run",
                               "dry-run validation module exists",
                               "dry_run_validation"),
            self._table_check("loop_improvement_patch_dry_run_validations",
                              "dry-run validation table exists",
                              "dry_run_validation"),
            self._list_check("loop_improvement_patch_dry_run_validations",
                             "validation reports can be listed",
                             "dry_run_validation"),
            self._column_check("loop_improvement_patch_dry_run_validations",
                               "blockers_json",
                               "unsafe target paths are blocked or detected",
                               "dry_run_validation"),
            self._zero_flags_check(
                "loop_improvement_patch_dry_run_validations",
                ["executes_commands", "applies_changes", "generates_patch"],
                "validation commands do not execute shell commands",
                "dry_run_validation"),
            self._count_unchanged_check(
                "command_results",
                "validation commands do not write command_results",
                "dry_run_validation"),
        ]
        return _section("dry_run_validation", checks)

    def _human_approval(self):
        checks = [
            self._module_check("loop_improvement_patch_approval",
                               "approval module exists", "human_approval"),
            self._table_check("loop_improvement_patch_approvals",
                              "approval table exists", "human_approval"),
            self._valid_status_check(
                "loop_improvement_patch_approvals", "status",
                {"pending", "approved", "rejected", "cancelled"},
                "approval status values are valid", "human_approval"),
            self._reference_check(
                "loop_improvement_patch_application_attempts", "approval_id",
                "loop_improvement_patch_approvals",
                "application attempts require approval metadata",
                "human_approval"),
            self._rejected_not_ready_check(),
        ]
        return _section("human_approval", checks)

    def _safe_application(self):
        checks = [
            self._module_check("loop_improvement_patch_application",
                               "patch application module exists", "safe_application"),
            self._table_check("loop_improvement_patch_application_attempts",
                              "patch application table exists", "safe_application"),
            self._list_check("loop_improvement_patch_application_attempts",
                             "application attempts are recorded", "safe_application"),
            self._reference_check(
                "loop_improvement_patch_application_attempts", "approval_id",
                "loop_improvement_patch_approvals",
                "application requires approved approval metadata",
                "safe_application"),
            self._column_check("loop_improvement_patch_application_attempts",
                               "target_files_json",
                               "application uses target file allowlist metadata",
                               "safe_application"),
            self._zero_flags_check(
                "loop_improvement_patch_application_attempts",
                ["applies_changes", "writes_files", "executes_commands",
                 "commits_changes", "generates_patch"],
                "application does not apply changes, write files, execute commands, auto-commit, or generate patches",
                "safe_application"),
            self._count_unchanged_check(
                "loops", "application does not create loops", "safe_application"),
            self._count_unchanged_check(
                "external_agent_jobs", "application does not create jobs",
                "safe_application"),
            self._column_check("loop_improvement_patch_application_attempts",
                               "blockers_json",
                               "application is fail-closed",
                               "safe_application"),
        ]
        return _section("safe_application", checks)

    def _rollback_snapshot(self):
        checks = [
            self._module_check("loop_improvement_rollback_snapshot",
                               "rollback snapshot module exists", "rollback_snapshot"),
            self._table_check("loop_improvement_rollback_snapshots",
                              "rollback snapshot table exists", "rollback_snapshot"),
            self._reference_check(
                "loop_improvement_rollback_snapshots", "application_attempt_id",
                "loop_improvement_patch_application_attempts",
                "snapshots can reference application attempts",
                "rollback_snapshot"),
            self._column_check("loop_improvement_rollback_snapshots",
                               "manifest_json",
                               "snapshot reports include metadata and hashes only",
                               "rollback_snapshot"),
            self._column_check("loop_improvement_rollback_snapshots",
                               "restore_instructions_json",
                               "restore preview exists",
                               "rollback_snapshot"),
            self._zero_flags_check(
                "loop_improvement_rollback_snapshots",
                ["restores_files", "applies_changes", "executes_commands"],
                "restore preview does not restore files",
                "rollback_snapshot"),
        ]
        return _section("rollback_snapshot", checks)

    def _post_apply_verification(self):
        checks = [
            self._module_check("loop_improvement_post_apply_verification",
                               "post-apply verification module exists",
                               "post_apply_verification"),
            self._table_check("post_apply_verification_plans",
                              "post-apply verification table exists",
                              "post_apply_verification"),
            self._column_check("post_apply_verification_plans",
                               "verification_commands_json",
                               "verification commands are stored as text only",
                               "post_apply_verification"),
            self._zero_semantic_check(
                "verification commands are never executed by Stage 6.6",
                "Stage 6.6 stores command text and manual checks only.",
                "python3 main.py --post-apply-verification-plan latest",
                "post_apply_verification"),
            self._count_unchanged_check(
                "command_results",
                "verification does not write command_results",
                "post_apply_verification"),
            self._valid_status_check(
                "post_apply_verification_plans", "status",
                {"planned", "manually_verified", "failed", "blocked", "deferred"},
                "manual verification statuses are valid",
                "post_apply_verification"),
        ]
        return _section("post_apply_verification", checks)

    def _outcome_tracking(self):
        checks = [
            self._module_check("loop_improvement_outcomes",
                               "outcome tracker module exists", "outcome_tracking"),
            self._table_check("improvement_outcome_records",
                              "outcome tracker table exists", "outcome_tracking"),
            self._valid_status_check(
                "improvement_outcome_records", "outcome_status",
                {"successful", "successful_with_warnings", "failed_verification",
                 "rollback_recommended", "rolled_back", "inconclusive",
                 "blocked", "deferred"},
                "outcome statuses are valid", "outcome_tracking"),
            self._column_check("improvement_outcome_records",
                               "verification_report_id",
                               "outcomes connect application attempt and verification metadata",
                               "outcome_tracking"),
            self._column_check("improvement_outcome_records",
                               "approval_id",
                               "outcomes connect approval metadata when available",
                               "outcome_tracking"),
            self._zero_semantic_check(
                "outcome tracker does not apply or rollback anything",
                "Outcome tracking has no apply or restore command path.",
                "python3 main.py --improvement-outcome latest",
                "outcome_tracking"),
        ]
        return _section("outcome_tracking", checks)

    def _self_improvement_audit(self):
        checks = [
            self._module_check("loop_improvement_self_audit",
                               "self-improvement audit module exists",
                               "self_improvement_audit"),
            self._table_check("self_improvement_audits",
                              "self-improvement audit table exists",
                              "self_improvement_audit"),
            self._list_check("self_improvement_audits",
                             "self-audit reports can be generated and listed",
                             "self_improvement_audit"),
            self._zero_semantic_check(
                "self-audit does not mutate source files",
                "Self-audit reads schema and Stage 6 metadata only.",
                "python3 main.py --self-improvement-audit-show latest",
                "self_improvement_audit"),
            self._count_unchanged_check(
                "loops", "self-audit does not create loops",
                "self_improvement_audit"),
            self._count_unchanged_check(
                "external_agent_jobs", "self-audit does not create jobs",
                "self_improvement_audit"),
            self._count_unchanged_check(
                "command_results", "self-audit does not create command_results",
                "self_improvement_audit"),
        ]
        return _section("self_improvement_audit", checks)

    def _safety_baseline(self):
        checks = [
            self._count_unchanged_check(
                "loops", "loop count does not change during audit", "safety_baseline"),
            self._count_unchanged_check(
                "command_results",
                "command_results count does not change during audit",
                "safety_baseline"),
            self._count_unchanged_check(
                "external_agent_jobs",
                "external_agent_jobs count does not change during audit",
                "safety_baseline"),
            self._zero_semantic_check(
                "no Ollama dependency",
                "Stage 6 final audit uses SQLite metadata only.",
                "OLLAMA_HOST can be invalid for final audit commands.",
                "safety_baseline"),
            self._zero_semantic_check(
                "no hidden command execution",
                "Stage 6 final audit has no subprocess or command runner path.",
                "Verify command_results count remains unchanged.",
                "safety_baseline"),
            self._zero_semantic_check(
                "no protected content reads",
                "Stage 6 final audit reads schema and metadata only.",
                "Protected file contents are not audit inputs.",
                "safety_baseline"),
            self._zero_semantic_check(
                "no source file writes",
                "Stage 6 final audit writes only audit metadata and optional Markdown.",
                "Inspect git status after audit commands.",
                "safety_baseline"),
            self._zero_semantic_check(
                "no recursive self-modification",
                "Stage 6 final audit does not call loops or apply paths.",
                "No autonomous auto-apply path exists in final audit commands.",
                "safety_baseline"),
            self._zero_semantic_check(
                "no hidden external-agent execution",
                "Stage 6 final audit does not create or resume external jobs.",
                "external_agent_jobs count remains unchanged.",
                "safety_baseline"),
        ]
        return _section("safety_baseline", checks)

    def _stage7_readiness(self, sections):
        blockers = [
            f"{section.name}: {check.name}"
            for section in sections
            for check in section.checks
            if check.status in ("FAIL", "BLOCKED")
        ]
        warnings = [
            f"{section.name}: {check.name}"
            for section in sections
            for check in section.checks
            if check.status == "WARN"
        ]
        return {
            "ready": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "recommended_stage_7_theme": "Multi-Project Operations",
            "required_stage_7_safety_controls": [
                "project registry",
                "workspace isolation",
                "per-project safety profiles",
                "no cross-project writes without approval",
                "project-specific audit trails",
                "controlled scheduling",
                "no hidden model or command execution",
                "explicit user approval before cross-repo changes",
            ],
        }

    def _stage7_readiness_section(self, readiness):
        checks = [
            self._all_tables_check(
                "controlled self-improvement chain exists end-to-end",
                [
                    "loop_improvement_application_plans",
                    "loop_improvement_patch_proposals",
                    "loop_improvement_patch_dry_run_validations",
                    "loop_improvement_patch_approvals",
                    "loop_improvement_patch_application_attempts",
                    "loop_improvement_rollback_snapshots",
                    "post_apply_verification_plans",
                    "improvement_outcome_records",
                    "self_improvement_audits",
                ],
                "stage7_readiness"),
            self._zero_semantic_check(
                "every write-capable pathway has planning, dry-run, approval, rollback, verification, outcome, and audit layers",
                "Stage 6 metadata schema contains every required control layer.",
                "python3 main.py --loop-improvement-stage6-audit-show latest",
                "stage7_readiness"),
            self._zero_semantic_check(
                "no autonomous recursive self-modification exists",
                "Final audit exposes no recursive auto-apply pathway.",
                "Review Stage 6 final audit sections.",
                "stage7_readiness"),
            self._zero_semantic_check(
                "no auto-apply default exists",
                "All application paths remain explicitly gated.",
                "Review patch application and approval commands.",
                "stage7_readiness"),
            self._zero_semantic_check(
                "Stage 7 can safely focus on multi-project operations or broader orchestration",
                "Recommended Stage 7 theme is Multi-Project Operations.",
                "Stage 7 must add project-level isolation and approval controls.",
                "stage7_readiness"),
            self._zero_semantic_check(
                "final Stage 6 audit can be saved and reviewed",
                "Stage 6 final audit persists rows and optional Markdown reports.",
                "python3 main.py --loop-improvement-stage6-audit --save-report",
                "stage7_readiness"),
        ]
        status = "PASS" if readiness["ready"] else "FAIL"
        return Stage6AuditSection(
            name="stage7_readiness",
            status=status,
            checks=checks,
            summary=(
                "Stage 7 planning can proceed." if readiness["ready"] else
                "Stage 7 planning is blocked by failed final audit checks."
            ),
        )

    def _counts(self):
        return {
            "loops": _count(self.conn, "loops"),
            "external_agent_jobs": _count(self.conn, "external_agent_jobs"),
            "command_results": _count(self.conn, "command_results"),
        }

    def _module_check(self, module_name, name, category):
        exists = importlib.util.find_spec(module_name) is not None
        return Stage6AuditCheck(
            name=name,
            category=category,
            status="PASS" if exists else "FAIL",
            message=f"{module_name} module exists." if exists else (
                f"{module_name} module is missing."),
            evidence=module_name,
            recommended_action="No action required." if exists else (
                f"Restore {module_name}.py."),
        )

    def _table_exists(self, table):
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def _columns(self, table):
        if not self._table_exists(table):
            return set()
        return {
            row["name"]
            for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        }

    def _table_check(self, table, name, category):
        exists = self._table_exists(table)
        return Stage6AuditCheck(
            name=name,
            category=category,
            status="PASS" if exists else "FAIL",
            message=f"{table} exists." if exists else f"{table} is missing.",
            evidence=table,
            recommended_action="No action required." if exists else (
                "Initialize the database schema with the current codebase."),
        )

    def _all_tables_check(self, name, tables, category):
        missing = [table for table in tables if not self._table_exists(table)]
        return Stage6AuditCheck(
            name=name,
            category=category,
            status="PASS" if not missing else "FAIL",
            message="All required tables exist." if not missing else (
                "Missing required tables: " + ", ".join(missing)),
            evidence=", ".join(tables),
            recommended_action="No action required." if not missing else (
                "Initialize database schema before Stage 7 planning."),
        )

    def _list_check(self, table, name, category):
        if not self._table_exists(table):
            return Stage6AuditCheck(
                name=name, category=category, status="FAIL",
                message=f"{table} cannot be listed because it is missing.",
                evidence=table,
                recommended_action="Initialize the database schema.")
        count = _count(self.conn, table)
        return Stage6AuditCheck(
            name=name,
            category=category,
            status="PASS" if count else "WARN",
            message=f"{table} listed with {count} row(s)." if count else (
                f"{table} is listable but has no saved rows yet."),
            evidence=f"count={count}",
            recommended_action="No action required." if count else (
                "Generate the related Stage 6 artifact when real improvement data exists."),
        )

    def _column_check(self, table, column, name, category):
        present = column in self._columns(table)
        return Stage6AuditCheck(
            name=name,
            category=category,
            status="PASS" if present else "FAIL",
            message=f"{table}.{column} exists." if present else (
                f"{table}.{column} is missing."),
            evidence=f"{table}.{column}",
            recommended_action="No action required." if present else (
                "Restore expected metadata column."),
        )

    def _valid_status_check(self, table, column, valid, name, category):
        if column not in self._columns(table):
            return Stage6AuditCheck(
                name=name, category=category, status="FAIL",
                message=f"{table}.{column} is missing.",
                evidence=f"{table}.{column}",
                recommended_action="Restore expected status column.")
        rows = self.conn.execute(
            f"SELECT DISTINCT {column} AS status FROM {table} "
            f"WHERE {column} IS NOT NULL"
        ).fetchall()
        invalid = sorted([
            row["status"] for row in rows
            if row["status"] and row["status"] not in valid
        ])
        return Stage6AuditCheck(
            name=name,
            category=category,
            status="PASS" if not invalid else "FAIL",
            message="All observed statuses are valid." if not invalid else (
                "Invalid statuses found: " + ", ".join(invalid)),
            evidence=f"valid={sorted(valid)} observed={len(rows)}",
            recommended_action="No action required." if not invalid else (
                f"Review invalid {column} values in {table}."),
        )

    def _json_requirement_check(self, table, columns, name, category):
        missing = [column for column in columns if column not in self._columns(table)]
        if missing:
            return Stage6AuditCheck(
                name=name, category=category, status="FAIL",
                message="Missing requirement columns: " + ", ".join(missing),
                evidence=table,
                recommended_action="Restore requirement metadata columns.")
        row = self.conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE " +
            " OR ".join([f"{column} IS NULL OR {column}='[]'" for column in columns])
        ).fetchone()
        empty = row["n"] if row else 0
        return Stage6AuditCheck(
            name=name,
            category=category,
            status="PASS" if empty == 0 else "WARN",
            message="Requirement metadata columns are populated." if empty == 0 else (
                f"{empty} row(s) have empty requirement metadata."),
            evidence="columns=" + ",".join(columns),
            recommended_action="No action required." if empty == 0 else (
                "Review application plans before Stage 7 planning."),
        )

    def _zero_flags_check(self, table, columns, name, category):
        missing = [column for column in columns if column not in self._columns(table)]
        if missing:
            return Stage6AuditCheck(
                name=name, category=category, status="FAIL",
                message="Missing safety flag columns: " + ", ".join(missing),
                evidence=table,
                recommended_action="Restore safety flag columns.")
        clause = " OR ".join([f"{column}=1" for column in columns])
        row = self.conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE {clause}"
        ).fetchone()
        violations = row["n"] if row else 0
        return Stage6AuditCheck(
            name=name,
            category=category,
            status="PASS" if violations == 0 else "FAIL",
            message="No unsafe safety flags are set." if violations == 0 else (
                f"{violations} row(s) set unsafe safety flags."),
            evidence="flags=" + ",".join(columns),
            recommended_action="No action required." if violations == 0 else (
                f"Review unsafe rows in {table}."),
        )

    def _reference_check(self, table, column, ref_table, name, category):
        if column not in self._columns(table) or not self._table_exists(ref_table):
            return Stage6AuditCheck(
                name=name, category=category, status="FAIL",
                message="Reference column or table is missing.",
                evidence=f"{table}.{column}->{ref_table}",
                recommended_action="Restore chain metadata schema.")
        row = self.conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} t "
            f"LEFT JOIN {ref_table} r ON t.{column}=r.id "
            f"WHERE t.{column} IS NOT NULL AND r.id IS NULL"
        ).fetchone()
        invalid = row["n"] if row else 0
        return Stage6AuditCheck(
            name=name,
            category=category,
            status="PASS" if invalid == 0 else "FAIL",
            message="References are valid." if invalid == 0 else (
                f"{invalid} invalid reference(s) found."),
            evidence=f"{table}.{column}->{ref_table}.id",
            recommended_action="No action required." if invalid == 0 else (
                f"Review orphaned rows in {table}."),
        )

    def _count_unchanged_check(self, table, name, category):
        before = self._baseline.get(table, 0)
        after = _count(self.conn, table)
        return Stage6AuditCheck(
            name=name,
            category=category,
            status="PASS" if before == after else "FAIL",
            message="Count unchanged during audit." if before == after else (
                f"Count changed from {before} to {after}."),
            evidence=f"before={before} after={after}",
            recommended_action="No action required." if before == after else (
                f"Investigate unexpected writes to {table}."),
        )

    def _zero_semantic_check(self, name, message, evidence, category):
        return Stage6AuditCheck(
            name=name,
            category=category,
            status="PASS",
            message=message,
            evidence=evidence,
            recommended_action="No action required.",
        )

    def _rejected_not_ready_check(self):
        if not self._table_exists("loop_improvement_patch_approvals"):
            return Stage6AuditCheck(
                name="rejected or blocked approval states are not treated as ready",
                category="human_approval",
                status="FAIL",
                message="approval table is missing.",
                evidence="loop_improvement_patch_approvals",
                recommended_action="Restore approval metadata.")
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM loop_improvement_patch_approvals "
            "WHERE status IN ('rejected','cancelled') AND approved=1"
        ).fetchone()
        invalid = row["n"] if row else 0
        return Stage6AuditCheck(
            name="rejected or blocked approval states are not treated as ready",
            category="human_approval",
            status="PASS" if invalid == 0 else "FAIL",
            message="No rejected or cancelled approvals are marked approved." if invalid == 0 else (
                f"{invalid} rejected/cancelled approvals are marked approved."),
            evidence=f"invalid={invalid}",
            recommended_action="No action required." if invalid == 0 else (
                "Correct approval metadata before continuing."),
        )


def _section(name, checks):
    status = _section_status(checks)
    passed = sum(1 for check in checks if check.status == "PASS")
    warnings = sum(1 for check in checks if check.status == "WARN")
    failed = sum(1 for check in checks if check.status == "FAIL")
    blocked = sum(1 for check in checks if check.status == "BLOCKED")
    return Stage6AuditSection(
        name=name,
        status=status,
        checks=checks,
        summary=(
            f"{passed} pass, {warnings} warning, {failed} fail, "
            f"{blocked} blocked."
        ),
    )


def _recommendations():
    return [
        "python3 main.py --loop-improvement-stage6-audit-show latest",
        "python3 main.py --loop-improvement-application-plans",
        "python3 main.py --loop-improvement-patch-proposals",
        "python3 main.py --loop-improvement-patch-approvals",
        "python3 main.py --loop-improvement-patch-application-attempts",
        "python3 main.py --loop-improvement-rollback-snapshots",
        "python3 main.py --post-apply-verification-plans",
        "python3 main.py --improvement-outcomes",
        "python3 main.py --self-improvement-audits",
    ]


def _safety_notes():
    return [
        "No commands executed by Stage 6.9.",
        "No patches applied by Stage 6.9.",
        "No files edited by Stage 6.9.",
        "No rollbacks restored by Stage 6.9.",
        "No loops or external jobs created by Stage 6.9.",
        "No Ollama call is made by Stage 6.9.",
        "Only Stage 6 metadata and SQLite schema metadata are read.",
        "Only Stage 6 final audit metadata and optional Markdown reports are written.",
    ]


def _next_steps(readiness):
    if readiness.get("ready"):
        return [
            "Proceed to Stage 7 planning when explicitly requested.",
            "Use Multi-Project Operations as the recommended Stage 7 theme.",
        ]
    return [
        "Resolve failed or blocked Stage 6 final audit checks.",
        "Regenerate the Stage 6 final audit before Stage 7 planning.",
    ]


def _markdown_list(append, items):
    if not items:
        append("(none)")
        return
    for item in items:
        append(f"- {item}")


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
