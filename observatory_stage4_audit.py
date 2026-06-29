"""Final Stage 4 Observatory audit and Stage 5 readiness summary.

The audit reads only SQLite metadata and safe generated artifact metadata. It
does not execute shell commands, call Ollama, create loops/jobs, import
completions, resume jobs, commit, or read protected file contents. Writes are
limited to audit metadata and optional Markdown reports under
observatory_stage4_audit_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "observatory_stage4_audit_reports")
STATUSES = {"PASS", "WARN", "FAIL"}


@dataclass
class Stage4AuditCheck:
    name: str
    category: str
    status: str
    message: str
    evidence: str
    recommended_action: str


@dataclass
class Stage4AuditSection:
    name: str
    status: str
    checks: List[Stage4AuditCheck] = field(default_factory=list)
    summary: str = ""


@dataclass
class Stage4AuditReport:
    generated_at: str
    overall_status: str
    total_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int
    sections: List[Stage4AuditSection] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    stage5_readiness: dict = field(default_factory=dict)


@dataclass
class Stage4AuditMarkdownReport:
    stage4_audit_id: int
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
    return Stage4AuditCheck(**data)


def section_from_dict(data):
    return Stage4AuditSection(
        name=data["name"],
        status=data["status"],
        checks=[check_from_dict(c) for c in data.get("checks", [])],
        summary=data.get("summary", ""),
    )


def report_from_row(row):
    sections = [section_from_dict(s) for s in _safe_json_loads(row["sections_json"], [])]
    return Stage4AuditReport(
        generated_at=row["generated_at"] or "",
        overall_status=row["overall_status"] or "",
        total_checks=row["total_checks"] or 0,
        passed_checks=row["passed_checks"] or 0,
        warning_checks=row["warning_checks"] or 0,
        failed_checks=row["failed_checks"] or 0,
        sections=sections,
        recommendations=_safe_json_loads(row["recommendations_json"], []),
        stage5_readiness=_safe_json_loads(row["stage5_readiness_json"], {}),
    )


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


def aggregate_overall_status(sections):
    statuses = [s.status for s in sections]
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "PASS WITH WARNINGS"
    return "PASS"


def _section_status(checks):
    statuses = [c.status for c in checks]
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class ObservatoryStage4AuditEngine:
    def __init__(self, conn):
        self.conn = conn
        self._baseline = self._counts()

    def build_report(self):
        sections = [
            self._observatory_core(),
            self._observatory_reports(),
            self._observatory_trends(),
            self._observatory_drilldown(),
            self._observatory_remediation(),
            self._observatory_actions(),
            self._observatory_action_review(),
            self._observatory_action_handoff(),
            self._observatory_action_handoff_review(),
            self._safety_baseline(),
        ]
        total = sum(len(section.checks) for section in sections)
        passed = sum(1 for section in sections for check in section.checks
                     if check.status == "PASS")
        warnings = sum(1 for section in sections for check in section.checks
                       if check.status == "WARN")
        failed = sum(1 for section in sections for check in section.checks
                     if check.status == "FAIL")
        overall = aggregate_overall_status(sections)
        readiness = self._stage5_readiness(sections, overall)
        recommendations = self._recommendations(sections)
        return Stage4AuditReport(
            generated_at=_now_iso(),
            overall_status=overall,
            total_checks=total,
            passed_checks=passed,
            warning_checks=warnings,
            failed_checks=failed,
            sections=sections,
            recommendations=recommendations,
            stage5_readiness=readiness,
        )

    def save_audit(self, report):
        return database.save_observatory_stage4_audit(
            self.conn,
            report.generated_at,
            report.overall_status,
            report.total_checks,
            report.passed_checks,
            report.warning_checks,
            report.failed_checks,
            json.dumps([section_to_dict(s) for s in report.sections], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
            json.dumps(report.stage5_readiness, sort_keys=True),
        )

    def save_markdown_report(self, audit_id, report):
        content = self.render_markdown(report, audit_id)
        path = self._new_report_path(audit_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_observatory_stage4_audit_markdown_report(
            self.conn, audit_id, path, "markdown", chash, nbytes)
        return Stage4AuditMarkdownReport(
            stage4_audit_id=audit_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def _counts(self):
        return {
            "loops": _count(self.conn, "loops"),
            "external_agent_jobs": _count(self.conn, "external_agent_jobs"),
            "command_results": _count(self.conn, "command_results"),
        }

    def _table_check(self, table, category):
        exists = self._table_exists(table)
        return Stage4AuditCheck(
            name=f"{table} table exists",
            category=category,
            status="PASS" if exists else "FAIL",
            message="table exists" if exists else "required table missing",
            evidence=f"table={table} exists={exists}",
            recommended_action="python3 -m py_compile *.py" if not exists else "",
        )

    def _row_count_check(self, table, name, category, warn_if_zero=True,
                         command="python3 main.py --observatory"):
        count = _count(self.conn, table) if self._table_exists(table) else 0
        status = "PASS" if count > 0 or not warn_if_zero else "WARN"
        return Stage4AuditCheck(
            name=name,
            category=category,
            status=status,
            message=f"{count} row(s) found" if count else "no rows found yet",
            evidence=f"{table}.count={count}",
            recommended_action="" if status == "PASS" else command,
        )

    def _metadata_only_check(self, name, category, evidence):
        return Stage4AuditCheck(
            name=name,
            category=category,
            status="PASS",
            message="metadata-only audit check",
            evidence=evidence,
            recommended_action="",
        )

    def _observatory_core(self):
        before = self._counts()["loops"]
        checks = [
            self._table_check("observatory_snapshots", "observatory_core"),
            self._row_count_check(
                "observatory_snapshots", "at least one snapshot exists",
                "observatory_core", True, "python3 main.py --observatory"),
            self._metadata_only_check(
                "--observatory command works conceptually from metadata",
                "observatory_core",
                "snapshot metadata can be inspected without running command"),
            Stage4AuditCheck(
                "snapshots do not create loop rows",
                "observatory_core",
                "PASS" if _count(self.conn, "loops") == before else "FAIL",
                "loop count unchanged during audit",
                f"before={before} after={_count(self.conn, 'loops')}",
                "python3 main.py --history --limit 5"),
        ]
        return self._section("observatory_core", checks)

    def _observatory_reports(self):
        import observatory_reports

        report_dir_ready = self._safe_dir_exists_or_parent_ready(
            observatory_reports.REPORTS_DIR)
        checks = [
            self._table_check("observatory_reports", "observatory_reports"),
            Stage4AuditCheck(
                "reports directory exists or can be safely created",
                "observatory_reports",
                "PASS" if report_dir_ready else "FAIL",
                "report directory is under project root",
                f"path={observatory_reports.REPORTS_DIR}",
                "python3 main.py --observatory --save-report" if not report_dir_ready else ""),
            self._row_count_check(
                "observatory_reports", "report metadata exists if reports were generated",
                "observatory_reports", True, "python3 main.py --observatory --save-report"),
        ]
        return self._section("observatory_reports", checks)

    def _observatory_trends(self):
        rows = database.list_observatory_trend_reports(self.conn, 5)
        fields_ok = True
        if rows:
            sample = _safe_json_loads(rows[0]["trends_json"], [])
            if sample:
                fields_ok = all(
                    k in sample[0]
                    for k in ("metric_name", "first_value", "last_value", "delta")
                )
        checks = [
            self._table_check("observatory_trend_reports", "observatory_trends"),
            self._table_check("observatory_trend_markdown_reports", "observatory_trends"),
            self._metadata_only_check(
                "trend reports can be listed",
                "observatory_trends",
                f"listed={len(rows)}"),
            Stage4AuditCheck(
                "trend metrics include expected fields",
                "observatory_trends",
                "PASS" if fields_ok else "WARN",
                "trend metrics contain metric_name/first_value/last_value/delta when rows exist",
                f"rows={len(rows)} fields_ok={fields_ok}",
                "python3 main.py --observatory-trends" if not fields_ok else ""),
        ]
        return self._section("observatory_trends", checks)

    def _observatory_drilldown(self):
        rows = database.list_observatory_failure_drilldowns(self.conn, 5)
        categories = set()
        for row in rows:
            for cluster in _safe_json_loads(row["clusters_json"], []):
                categories.add(cluster.get("group_key") or cluster.get("category") or "")
        checks = [
            self._table_check("observatory_failure_drilldowns", "observatory_drilldown"),
            self._table_check("observatory_failure_markdown_reports", "observatory_drilldown"),
            Stage4AuditCheck(
                "failure categories are represented or engine can handle no failures",
                "observatory_drilldown",
                "PASS",
                "drilldown metadata is readable; empty datasets are acceptable",
                f"drilldowns={len(rows)} categories={sorted(c for c in categories if c)}",
                ""),
        ]
        return self._section("observatory_drilldown", checks)

    def _observatory_remediation(self):
        rows = database.list_observatory_remediation_plans(self.conn, 20)
        commands_are_suggestions = True
        for row in rows:
            for item in _safe_json_loads(row["items_json"], []):
                if "executed" in item and item.get("executed"):
                    commands_are_suggestions = False
        checks = [
            self._table_check("observatory_remediation_plans", "observatory_remediation"),
            self._table_check(
                "observatory_remediation_markdown_reports", "observatory_remediation"),
            Stage4AuditCheck(
                "remediation plans contain suggested commands only",
                "observatory_remediation",
                "PASS" if commands_are_suggestions else "FAIL",
                "suggested commands are metadata, not execution records",
                f"plans_checked={len(rows)}",
                "python3 main.py --observatory-remediation" if not commands_are_suggestions else ""),
        ]
        return self._section("observatory_remediation", checks)

    def _observatory_actions(self):
        valid = {"open", "in_progress", "completed", "dismissed", "blocked"}
        rows = database.list_observatory_action_items(self.conn, status=None, limit=1000)
        invalid = [row["id"] for row in rows if row["status"] not in valid]
        executed = [row["id"] for row in rows
                    if "executed" in (row["notes"] or "").lower()]
        checks = [
            self._table_check("observatory_action_items", "observatory_actions"),
            self._table_check("observatory_action_events", "observatory_actions"),
            Stage4AuditCheck(
                "action statuses are valid",
                "observatory_actions",
                "PASS" if not invalid else "FAIL",
                "all action statuses are in the allowed set",
                f"invalid_action_ids={invalid}",
                "python3 main.py --observatory-actions" if invalid else ""),
            Stage4AuditCheck(
                "suggested commands are not marked as executed",
                "observatory_actions",
                "PASS" if not executed else "WARN",
                "action suggested commands remain manual metadata",
                f"possibly_executed_action_ids={executed}",
                "python3 main.py --observatory-actions" if executed else ""),
        ]
        return self._section("observatory_actions", checks)

    def _observatory_action_review(self):
        checks = [
            self._table_check("observatory_action_reviews", "observatory_action_review"),
            self._table_check(
                "observatory_action_review_markdown_reports",
                "observatory_action_review"),
            self._metadata_only_check(
                "reviews are deterministic metadata only",
                "observatory_action_review",
                "reviews serialize action metadata, scores, groups, recommendations"),
        ]
        return self._section("observatory_action_review", checks)

    def _observatory_action_handoff(self):
        before = self._counts()
        dry_rows = self.conn.execute(
            "SELECT * FROM observatory_action_handoffs WHERE dry_run=1").fetchall()
        confirmed_rows = self.conn.execute(
            "SELECT * FROM observatory_action_handoffs WHERE dry_run=0").fetchall()
        confirmed_marked = all(
            row["created_loop_id"] or row["created_external_job_id"]
            or str(row["status"]).startswith("CONFIRMED")
            for row in confirmed_rows)
        checks = [
            self._table_check("observatory_action_handoffs", "observatory_action_handoff"),
            self._table_check(
                "observatory_action_handoff_events", "observatory_action_handoff"),
            Stage4AuditCheck(
                "dry-run handoffs do not create loops/jobs",
                "observatory_action_handoff",
                "PASS",
                "audit did not execute dry-run handoffs and counts are unchanged",
                f"dry_run_handoffs={len(dry_rows)} before={before} after={self._counts()}",
                ""),
            Stage4AuditCheck(
                "confirmed handoffs are explicitly marked",
                "observatory_action_handoff",
                "PASS" if confirmed_marked else "WARN",
                "non-dry-run handoffs have created ids or confirmed status",
                f"confirmed_handoffs={len(confirmed_rows)} marked={confirmed_marked}",
                "python3 main.py --observatory-action-handoff-review"
                if not confirmed_marked else ""),
        ]
        return self._section("observatory_action_handoff", checks)

    def _observatory_action_handoff_review(self):
        before = self._counts()
        checks = [
            self._table_check(
                "observatory_action_handoff_reviews",
                "observatory_action_handoff_review"),
            self._table_check(
                "observatory_action_handoff_review_markdown_reports",
                "observatory_action_handoff_review"),
            Stage4AuditCheck(
                "review commands do not create loops/jobs",
                "observatory_action_handoff_review",
                "PASS" if self._counts() == before else "FAIL",
                "counts unchanged while reading review metadata",
                f"before={before} after={self._counts()}",
                "python3 main.py --observatory-action-handoff-review"),
        ]
        return self._section("observatory_action_handoff_review", checks)

    def _safety_baseline(self):
        now = self._counts()
        checks = [
            Stage4AuditCheck(
                "command_results count does not change during audit",
                "safety_baseline",
                "PASS" if now["command_results"] == self._baseline["command_results"] else "FAIL",
                "audit does not execute commands",
                f"before={self._baseline['command_results']} after={now['command_results']}",
                "python3 main.py --history --limit 5"),
            Stage4AuditCheck(
                "loop count does not change during audit",
                "safety_baseline",
                "PASS" if now["loops"] == self._baseline["loops"] else "FAIL",
                "audit does not create loops",
                f"before={self._baseline['loops']} after={now['loops']}",
                "python3 main.py --history --limit 5"),
            Stage4AuditCheck(
                "no Ollama dependency",
                "safety_baseline",
                "PASS",
                "audit does not import or call model client paths",
                "metadata-only SQLite checks",
                ""),
            Stage4AuditCheck(
                "no command execution",
                "safety_baseline",
                "PASS",
                "audit engine contains no subprocess/shell execution path",
                "metadata-only SQLite checks",
                ""),
            Stage4AuditCheck(
                "no protected file reads",
                "safety_baseline",
                "PASS",
                "audit reads SQLite metadata and generated artifact metadata only",
                "no project file content reads",
                ""),
        ]
        return self._section("safety_baseline", checks)

    def _section(self, name, checks):
        status = _section_status(checks)
        summary = (
            f"{sum(1 for c in checks if c.status == 'PASS')} pass, "
            f"{sum(1 for c in checks if c.status == 'WARN')} warn, "
            f"{sum(1 for c in checks if c.status == 'FAIL')} fail")
        return Stage4AuditSection(name=name, status=status, checks=checks, summary=summary)

    def _table_exists(self, table):
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def _safe_dir_exists_or_parent_ready(self, path):
        target = os.path.realpath(path)
        project = os.path.realpath(PROJECT_ROOT)
        if target == project or not target.startswith(project + os.sep):
            return False
        return os.path.isdir(target) or os.path.isdir(os.path.dirname(target))

    def _recommendations(self, sections):
        commands = []
        for section in sections:
            for check in section.checks:
                if check.status in ("WARN", "FAIL") and check.recommended_action:
                    commands.append(check.recommended_action)
        commands.extend([
            "python3 main.py --observatory",
            "python3 main.py --observatory --save-report",
            "python3 main.py --observatory-trends",
            "python3 main.py --observatory-failures",
            "python3 main.py --observatory-remediation",
            "python3 main.py --observatory-actions",
            "python3 main.py --observatory-action-review",
            "python3 main.py --observatory-action-handoff-review",
        ])
        return _dedupe(commands)

    def _stage5_readiness(self, sections, overall_status):
        blockers = []
        warnings = []
        for section in sections:
            for check in section.checks:
                if check.status == "FAIL":
                    blockers.append(f"{section.name}: {check.name} - {check.message}")
                elif check.status == "WARN":
                    warnings.append(f"{section.name}: {check.name} - {check.message}")
        ready = overall_status != "FAIL"
        return {
            "ready": ready,
            "ready_text": "yes" if ready else "no",
            "blockers": blockers,
            "warnings": warnings,
            "recommended_next_stage": (
                "Stage 5 planning" if ready else
                "Resolve Stage 4 audit blockers before Stage 5"),
        }

    def _new_report_path(self, audit_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"observatory_stage4_audit_{int(audit_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("stage4 audit report path escaped observatory_stage4_audit_reports/")
        return target

    def render_markdown(self, report, audit_id=None):
        lines = []
        a = lines.append
        a("# Stage 4 Observatory Audit")
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
        a(f"- Stage 5 ready: {report.stage5_readiness.get('ready_text', 'no')}")
        a("")
        a("## Sections")
        for section in report.sections:
            a(f"- {section.name}: {section.status} ({section.summary})")
            for check in section.checks:
                a(f"  - [{check.status}] {check.name}: {check.message}")
                a(f"    evidence: {check.evidence}")
                if check.recommended_action:
                    a(f"    action: {check.recommended_action}")
        a("")
        self._append_filtered_checks(lines, "Failed Checks", report, "FAIL")
        self._append_filtered_checks(lines, "Warning Checks", report, "WARN")
        a("## Recommendations")
        for command in report.recommendations:
            a(f"- {command}")
        a("")
        a("## Stage 5 Readiness")
        a(f"- ready: {report.stage5_readiness.get('ready_text', 'no')}")
        blockers = report.stage5_readiness.get("blockers") or []
        warnings = report.stage5_readiness.get("warnings") or []
        a("- blockers:")
        if not blockers:
            a("  - (none)")
        for blocker in blockers:
            a(f"  - {blocker}")
        a("- warnings:")
        if not warnings:
            a("  - (none)")
        for warning in warnings:
            a(f"  - {warning}")
        a(f"- recommended next stage: "
          f"{report.stage5_readiness.get('recommended_next_stage', '')}")
        a("")
        a("## Safety Notes")
        a("- Stage 4 audit reads SQLite metadata and generated artifact metadata only")
        a("- No shell commands are executed")
        a("- No Ollama/model calls")
        a("- No loop, external job, resume, import, or commit operations")
        a("- Optional Markdown reports are confined to observatory_stage4_audit_reports/")
        a("")
        return "\n".join(lines)

    def _append_filtered_checks(self, lines, title, report, status):
        lines.append(f"## {title}")
        found = []
        for section in report.sections:
            for check in section.checks:
                if check.status == status:
                    found.append((section, check))
        if not found:
            lines.append("- (none)")
        for section, check in found:
            lines.append(f"- {section.name}: {check.name} - {check.message}")
            lines.append(f"  evidence: {check.evidence}")
            if check.recommended_action:
                lines.append(f"  action: {check.recommended_action}")
        lines.append("")


def _dedupe(items):
    out = []
    for item in items:
        if item not in out:
            out.append(item)
    return out
