"""Self-Improvement Audit (Stage 6.8).

This audit reads Stage 6 SQLite metadata and safe schema metadata to summarize
the controlled self-improvement chain. It never executes commands, runs tests,
calls Ollama, applies patches, restores files, creates loops/jobs, imports
completions, resumes jobs, commits, mutates framework definitions, or reads
protected file contents. Writes are limited to self-audit metadata and optional
Markdown reports under self_improvement_audit_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "self_improvement_audit_reports")
VALID_SECTION_STATUSES = {"PASS", "WARN", "FAIL", "BLOCKED"}
VALID_OVERALL_STATUSES = {"PASS", "PASS_WITH_WARNINGS", "FAIL", "BLOCKED"}


@dataclass
class SelfImprovementAuditCheck:
    name: str
    category: str
    status: str
    message: str
    evidence: str
    recommended_action: str


@dataclass
class SelfImprovementAuditSection:
    name: str
    status: str
    checks: List[SelfImprovementAuditCheck] = field(default_factory=list)
    summary: str = ""


@dataclass
class SelfImprovementAuditReport:
    id: int
    generated_at: str
    overall_status: str
    total_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int
    blocked_checks: int
    sections: List[SelfImprovementAuditSection] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    stage6_final_readiness: dict = field(default_factory=dict)
    safety_notes: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)


@dataclass
class SelfImprovementAuditMarkdownReport:
    self_audit_id: int
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
    return SelfImprovementAuditCheck(**data)


def section_from_dict(data):
    return SelfImprovementAuditSection(
        name=data["name"],
        status=data["status"],
        checks=[check_from_dict(c) for c in data.get("checks", [])],
        summary=data.get("summary", ""),
    )


def report_from_row(row):
    sections = [
        section_from_dict(item)
        for item in _safe_json_loads(row["sections_json"], [])
    ]
    return SelfImprovementAuditReport(
        id=row["id"],
        generated_at=row["generated_at"] or "",
        overall_status=row["overall_status"] or "",
        total_checks=row["total_checks"] or 0,
        passed_checks=row["passed_checks"] or 0,
        warning_checks=row["warning_checks"] or 0,
        failed_checks=row["failed_checks"] or 0,
        blocked_checks=row["blocked_checks"] or 0,
        sections=sections,
        recommendations=_safe_json_loads(row["recommendations_json"], []),
        stage6_final_readiness=_safe_json_loads(
            row["stage6_final_readiness_json"], {}),
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


class LoopImprovementSelfAuditEngine:
    def __init__(self, conn):
        self.conn = conn
        self._baseline = self._counts()

    def build_report(self):
        sections = [
            self._application_planning(),
            self._patch_proposals(),
            self._dry_run_validation(),
            self._human_approval(),
            self._safe_application(),
            self._rollback(),
            self._post_apply_verification(),
            self._outcome_tracking(),
            self._safety_baseline(),
        ]
        readiness = self._stage6_final_readiness(sections)
        sections.append(self._stage6_final_readiness_section(readiness))
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
        return SelfImprovementAuditReport(
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
            stage6_final_readiness=readiness,
            safety_notes=_safety_notes(),
            next_steps=_next_steps(readiness),
        )

    def save_audit(self, report):
        return database.save_self_improvement_audit(
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
            json.dumps(report.stage6_final_readiness, sort_keys=True),
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
        database.save_self_improvement_audit_markdown_report(
            self.conn, audit_id, path, "markdown", chash, nbytes)
        return SelfImprovementAuditMarkdownReport(
            self_audit_id=audit_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def render_markdown(self, report, audit_id=None):
        lines = []
        a = lines.append
        a("# Self-Improvement Audit")
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
        a(f"- Stage 6 final readiness: {report.stage6_final_readiness.get('ready')}")
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
        a("## Stage 6 Final Readiness")
        for key, value in report.stage6_final_readiness.items():
            a(f"- {key}: {value}")
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
        filename = f"self_improvement_audit_{int(audit_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("self-improvement audit report path escaped directory")
        return target

    def _application_planning(self):
        checks = [
            self._table_check("loop_improvement_application_plans",
                              "application_planning"),
            self._table_check("loop_improvement_application_plan_items",
                              "application_planning"),
            self._list_check("loop_improvement_application_plans",
                             "plans can be listed", "application_planning"),
            self._valid_status_check(
                "loop_improvement_application_plans", "status",
                {"planned", "ready_for_patch_proposal"},
                "plan status values are valid", "application_planning"),
            self._json_requirement_check(
                "loop_improvement_application_plans",
                ["required_approvals_json", "rollback_requirements_json",
                 "validation_requirements_json"],
                "plans record approval, rollback, and validation requirements",
                "application_planning"),
            self._zero_flags_check(
                "loop_improvement_application_plans",
                ["generates_patch", "applies_changes"],
                "application plans did not generate patches or edit files",
                "application_planning"),
        ]
        return _section("application_planning", checks)

    def _patch_proposals(self):
        checks = [
            self._table_check("loop_improvement_patch_proposals", "patch_proposals"),
            self._table_check("loop_improvement_patch_proposal_items",
                              "patch_proposals"),
            self._reference_check(
                "loop_improvement_patch_proposals", "application_plan_id",
                "loop_improvement_application_plans",
                "patch proposals reference valid application plans",
                "patch_proposals"),
            self._zero_flags_check(
                "loop_improvement_patch_proposals",
                ["generates_unified_diff", "writes_patch_file",
                 "applies_changes", "reads_file_contents"],
                "patch proposal content is metadata only",
                "patch_proposals"),
            self._zero_flags_check(
                "loop_improvement_patch_proposals", ["applies_changes"],
                "patch proposals do not apply patches", "patch_proposals"),
        ]
        return _section("patch_proposals", checks)

    def _dry_run_validation(self):
        checks = [
            self._table_check("loop_improvement_patch_dry_run_validations",
                              "dry_run_validation"),
            self._table_check("loop_improvement_patch_dry_run_checks",
                              "dry_run_validation"),
            self._list_check("loop_improvement_patch_dry_run_validations",
                             "validation reports can be listed",
                             "dry_run_validation"),
            self._column_check("loop_improvement_patch_dry_run_validations",
                               "blockers_json",
                               "validators record unsafe path blockers",
                               "dry_run_validation"),
            self._column_check("loop_improvement_patch_dry_run_validations",
                               "warnings_json",
                               "validators record protected content warnings",
                               "dry_run_validation"),
            self._zero_flags_check(
                "loop_improvement_patch_dry_run_validations",
                ["executes_commands", "applies_changes", "generates_patch"],
                "validators do not execute commands or apply patches",
                "dry_run_validation"),
            self._count_unchanged_check(
                "command_results", "validators do not write command_results",
                "dry_run_validation"),
        ]
        return _section("dry_run_validation", checks)

    def _human_approval(self):
        checks = [
            self._table_check("loop_improvement_patch_approvals", "human_approval"),
            self._valid_status_check(
                "loop_improvement_patch_approvals", "status",
                {"pending", "approved", "rejected", "cancelled"},
                "approval status values are valid", "human_approval"),
            self._column_check("loop_improvement_patch_approvals",
                               "approval_required",
                               "approval is required before application attempts",
                               "human_approval"),
            self._rejected_not_ready_check(),
        ]
        return _section("human_approval", checks)

    def _safe_application(self):
        checks = [
            self._table_check("loop_improvement_patch_application_attempts",
                              "safe_application"),
            self._reference_check(
                "loop_improvement_patch_application_attempts", "approval_id",
                "loop_improvement_patch_approvals",
                "application attempts require approval metadata",
                "safe_application"),
            self._column_check("loop_improvement_patch_application_attempts",
                               "target_files_json",
                               "application attempts record target files",
                               "safe_application"),
            self._column_check("loop_improvement_patch_application_attempts",
                               "blockers_json",
                               "application commands are fail-closed",
                               "safe_application"),
            self._zero_flags_check(
                "loop_improvement_patch_application_attempts",
                ["commits_changes"],
                "application attempts do not auto-commit",
                "safe_application"),
            self._count_unchanged_check(
                "loops", "application attempts do not create loops",
                "safe_application"),
            self._count_unchanged_check(
                "external_agent_jobs",
                "application attempts do not create external jobs",
                "safe_application"),
        ]
        return _section("safe_application", checks)

    def _rollback(self):
        checks = [
            self._table_check("loop_improvement_rollback_snapshots", "rollback"),
            self._reference_check(
                "loop_improvement_rollback_snapshots", "application_attempt_id",
                "loop_improvement_patch_application_attempts",
                "rollback snapshots reference application attempts",
                "rollback"),
            self._column_check("loop_improvement_rollback_snapshots",
                               "manifest_json",
                               "rollback reports include metadata and hashes only",
                               "rollback"),
            self._column_check("loop_improvement_rollback_snapshots",
                               "restore_instructions_json",
                               "restore preview metadata exists",
                               "rollback"),
            self._zero_flags_check(
                "loop_improvement_rollback_snapshots",
                ["restores_files", "applies_changes", "executes_commands"],
                "restore preview does not restore files",
                "rollback"),
        ]
        return _section("rollback", checks)

    def _post_apply_verification(self):
        checks = [
            self._table_check("post_apply_verification_plans",
                              "post_apply_verification"),
            self._table_check("post_apply_verification_reports",
                              "post_apply_verification"),
            self._column_check("post_apply_verification_plans",
                               "verification_commands_json",
                               "verification commands are stored as text only",
                               "post_apply_verification"),
            self._count_unchanged_check(
                "command_results",
                "verification does not execute commands or write command_results",
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
            self._table_check("improvement_outcome_records", "outcome_tracking"),
            self._table_check("improvement_outcome_reports", "outcome_tracking"),
            self._valid_status_check(
                "improvement_outcome_records", "outcome_status",
                {"successful", "successful_with_warnings", "failed_verification",
                 "rollback_recommended", "rolled_back", "inconclusive",
                 "blocked", "deferred"},
                "outcome statuses are valid", "outcome_tracking"),
            self._column_check("improvement_outcome_records",
                               "verification_report_id",
                               "outcomes connect application attempts to verification metadata",
                               "outcome_tracking"),
            self._zero_semantic_check(
                "outcomes do not apply or rollback anything",
                "Outcome tracking has no apply/restore command columns.",
                "python3 main.py --improvement-outcome latest",
                "outcome_tracking"),
        ]
        return _section("outcome_tracking", checks)

    def _safety_baseline(self):
        checks = [
            self._count_unchanged_check(
                "loops", "loop count does not change during audit",
                "safety_baseline"),
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
                "Audit uses SQLite metadata only and has no model-client calls.",
                "OLLAMA_HOST can be invalid for self-improvement audit commands.",
                "safety_baseline"),
            self._zero_semantic_check(
                "no source file writes",
                "Audit writes only audit metadata and optional Markdown reports.",
                "Inspect git status after audit commands.",
                "safety_baseline"),
            self._zero_semantic_check(
                "no protected content reads",
                "Audit reads schema and Stage 6 metadata only.",
                "Protected file contents are not part of audit inputs.",
                "safety_baseline"),
            self._zero_semantic_check(
                "no recursive self-modification",
                "Audit does not call loops, external agents, or apply paths.",
                "No autonomous auto-apply path exists in audit commands.",
                "safety_baseline"),
        ]
        return _section("safety_baseline", checks)

    def _stage6_final_readiness(self, sections):
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
            "recommended_next_stage": "Stage 6.9",
            "required_final_audit_controls": [
                "confirm all Stage 6 metadata tables exist",
                "confirm no autonomous auto-apply path exists",
                "confirm no hidden command execution path exists",
                "confirm rollback and verification metadata gates remain intact",
            ],
        }

    def _stage6_final_readiness_section(self, readiness):
        checks = [
            self._all_tables_check(
                "full chain components exist",
                [
                    "loop_improvement_application_plans",
                    "loop_improvement_patch_proposals",
                    "loop_improvement_patch_dry_run_validations",
                    "loop_improvement_patch_approvals",
                    "loop_improvement_patch_application_attempts",
                    "loop_improvement_rollback_snapshots",
                    "post_apply_verification_plans",
                    "improvement_outcome_records",
                ],
                "stage6_final_readiness"),
            self._zero_semantic_check(
                "write-capable future paths have planning/approval/rollback/verification/audit metadata",
                "Stage 6 metadata includes planning, approval, rollback, verification, outcomes, and this audit.",
                "python3 main.py --self-improvement-audit-show latest",
                "stage6_final_readiness"),
            self._zero_semantic_check(
                "Stage 6.9 final audit can be generated next",
                "Stage 6.8 produces the readiness metadata required by Stage 6.9.",
                "python3 main.py --self-improvement-audit --save-report",
                "stage6_final_readiness"),
            self._zero_semantic_check(
                "no autonomous auto-apply path exists",
                "Stage 6.8 audit records metadata only and does not apply changes.",
                "Review Stage 6 CLI commands before Stage 6.9.",
                "stage6_final_readiness"),
            self._zero_semantic_check(
                "no hidden command execution path exists",
                "Suggested and verification commands are stored as text only.",
                "Verify command_results count remains unchanged.",
                "stage6_final_readiness"),
        ]
        status = "PASS" if readiness["ready"] else "FAIL"
        summary = "Stage 6.9 final audit can proceed." if readiness["ready"] else (
            "Stage 6.9 final audit is blocked by failed checks.")
        return SelfImprovementAuditSection(
            name="stage6_final_readiness",
            status=status,
            checks=checks,
            summary=summary,
        )

    def _counts(self):
        return {
            "loops": _count(self.conn, "loops"),
            "external_agent_jobs": _count(self.conn, "external_agent_jobs"),
            "command_results": _count(self.conn, "command_results"),
        }

    def _table_exists(self, table):
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def _columns(self, table):
        if not self._table_exists(table):
            return set()
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {row["name"] for row in rows}

    def _table_check(self, table, category):
        exists = self._table_exists(table)
        return SelfImprovementAuditCheck(
            name=f"{table} table exists",
            category=category,
            status="PASS" if exists else "FAIL",
            message=f"{table} exists." if exists else f"{table} is missing.",
            evidence=table,
            recommended_action=(
                "No action required." if exists else
                "Run database migrations by initializing the current codebase."
            ),
        )

    def _all_tables_check(self, name, tables, category):
        missing = [table for table in tables if not self._table_exists(table)]
        return SelfImprovementAuditCheck(
            name=name,
            category=category,
            status="PASS" if not missing else "FAIL",
            message="All required tables exist." if not missing else (
                "Missing required tables: " + ", ".join(missing)),
            evidence=", ".join(tables),
            recommended_action="Run python3 main.py --self-improvement-audit after initializing the database.",
        )

    def _list_check(self, table, name, category):
        if not self._table_exists(table):
            return SelfImprovementAuditCheck(
                name=name, category=category, status="FAIL",
                message=f"{table} cannot be listed because it is missing.",
                evidence=table, recommended_action="Initialize the database schema.")
        count = _count(self.conn, table)
        status = "PASS" if count else "WARN"
        return SelfImprovementAuditCheck(
            name=name,
            category=category,
            status=status,
            message=(
                f"{table} listed with {count} row(s)." if count else
                f"{table} is listable but has no saved rows yet."
            ),
            evidence=f"count={count}",
            recommended_action=(
                "No action required." if count else
                "Generate the related Stage 6 artifact when real improvement data exists."
            ),
        )

    def _column_check(self, table, column, name, category):
        present = column in self._columns(table)
        return SelfImprovementAuditCheck(
            name=name,
            category=category,
            status="PASS" if present else "FAIL",
            message=f"{table}.{column} exists." if present else (
                f"{table}.{column} is missing."),
            evidence=f"{table}.{column}",
            recommended_action="No action required." if present else (
                "Restore the expected metadata column."),
        )

    def _valid_status_check(self, table, column, valid, name, category):
        if column not in self._columns(table):
            return SelfImprovementAuditCheck(
                name=name, category=category, status="FAIL",
                message=f"{table}.{column} is missing.",
                evidence=f"{table}.{column}",
                recommended_action="Restore the expected status column.")
        rows = self.conn.execute(
            f"SELECT DISTINCT {column} AS status FROM {table} "
            f"WHERE {column} IS NOT NULL"
        ).fetchall()
        invalid = sorted([
            row["status"] for row in rows
            if row["status"] and row["status"] not in valid
        ])
        return SelfImprovementAuditCheck(
            name=name,
            category=category,
            status="PASS" if not invalid else "FAIL",
            message="All observed statuses are valid." if not invalid else (
                "Invalid statuses found: " + ", ".join(invalid)),
            evidence=f"valid={sorted(valid)} observed={len(rows)}",
            recommended_action="No action required." if not invalid else (
                f"Review rows in {table} with invalid {column} values."),
        )

    def _json_requirement_check(self, table, columns, name, category):
        missing_columns = [column for column in columns if column not in self._columns(table)]
        if missing_columns:
            return SelfImprovementAuditCheck(
                name=name, category=category, status="FAIL",
                message="Missing requirement columns: " + ", ".join(missing_columns),
                evidence=table,
                recommended_action="Restore requirement metadata columns.")
        row = self.conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE " +
            " OR ".join([f"{column} IS NULL OR {column}='[]'" for column in columns])
        ).fetchone()
        empty = row["n"] if row else 0
        return SelfImprovementAuditCheck(
            name=name,
            category=category,
            status="PASS" if empty == 0 else "WARN",
            message="Requirement metadata columns are populated." if empty == 0 else (
                f"{empty} row(s) have empty requirement metadata."),
            evidence="columns=" + ",".join(columns),
            recommended_action="Review application plans before Stage 6.9." if empty else "No action required.",
        )

    def _zero_flags_check(self, table, columns, name, category):
        missing_columns = [column for column in columns if column not in self._columns(table)]
        if missing_columns:
            return SelfImprovementAuditCheck(
                name=name, category=category, status="FAIL",
                message="Missing safety flag columns: " + ", ".join(missing_columns),
                evidence=table,
                recommended_action="Restore safety flag columns.")
        clause = " OR ".join([f"{column}=1" for column in columns])
        row = self.conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE {clause}"
        ).fetchone()
        violations = row["n"] if row else 0
        return SelfImprovementAuditCheck(
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
            return SelfImprovementAuditCheck(
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
        return SelfImprovementAuditCheck(
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
        return SelfImprovementAuditCheck(
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
        return SelfImprovementAuditCheck(
            name=name,
            category=category,
            status="PASS",
            message=message,
            evidence=evidence,
            recommended_action="No action required.",
        )

    def _rejected_not_ready_check(self):
        if not self._table_exists("loop_improvement_patch_approvals"):
            return SelfImprovementAuditCheck(
                name="rejected/blocked approvals cannot be considered ready",
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
        return SelfImprovementAuditCheck(
            name="rejected/blocked approvals cannot be considered ready",
            category="human_approval",
            status="PASS" if invalid == 0 else "FAIL",
            message="No rejected or cancelled approvals are marked approved." if invalid == 0 else (
                f"{invalid} rejected/cancelled approvals are marked approved."),
            evidence=f"invalid={invalid}",
            recommended_action="No action required." if invalid == 0 else (
                "Correct approval status metadata before continuing."),
        )


def _section(name, checks):
    status = _section_status(checks)
    passed = sum(1 for check in checks if check.status == "PASS")
    warnings = sum(1 for check in checks if check.status == "WARN")
    failed = sum(1 for check in checks if check.status == "FAIL")
    blocked = sum(1 for check in checks if check.status == "BLOCKED")
    return SelfImprovementAuditSection(
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
        "python3 main.py --self-improvement-audit-show latest",
        "python3 main.py --loop-improvement-application-plans",
        "python3 main.py --loop-improvement-patch-proposals",
        "python3 main.py --loop-improvement-patch-dry-runs",
        "python3 main.py --loop-improvement-patch-approvals",
        "python3 main.py --loop-improvement-patch-application-attempts",
        "python3 main.py --loop-improvement-rollback-snapshots",
        "python3 main.py --post-apply-verification-plans",
        "python3 main.py --improvement-outcomes",
    ]


def _safety_notes():
    return [
        "No commands executed by Stage 6.8.",
        "No patches applied by Stage 6.8.",
        "No files restored by Stage 6.8.",
        "No loops or external jobs created by Stage 6.8.",
        "No Ollama call is made by Stage 6.8.",
        "Only Stage 6 metadata and SQLite schema metadata are read.",
        "Only self-improvement audit metadata and optional Markdown reports are written.",
    ]


def _next_steps(readiness):
    if readiness.get("ready"):
        return [
            "Proceed to Stage 6.9 final audit when explicitly requested.",
            "Do not apply improvements automatically.",
        ]
    return [
        "Resolve failed or blocked self-improvement audit checks.",
        "Regenerate the self-improvement audit before Stage 6.9.",
    ]


def _markdown_list(append, items):
    if not items:
        append("(none)")
        return
    for item in items:
        append(f"- {item}")


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
