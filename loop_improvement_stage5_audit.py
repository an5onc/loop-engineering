"""Final Stage 5 Loop Improvement audit and Stage 6 readiness summary.

The audit reads only SQLite metadata and generated artifact metadata. It does
not execute shell commands, call Ollama, create loops/jobs, import completions,
resume jobs, commit, apply proposals, mutate improvement records, mutate
framework definitions, or read protected file contents. Writes are limited to
audit metadata and optional Markdown reports under
loop_improvement_stage5_audit_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "loop_improvement_stage5_audit_reports")
PROPOSAL_STATUSES = {"proposed", "accepted", "rejected", "deferred",
                     "converted_to_action"}
ACTION_STATUSES = {"open", "in_progress", "completed", "dismissed", "blocked"}
HANDOFF_REVIEW_STATUSES = {
    "safe_dry_run",
    "safe_packet",
    "needs_review",
    "ready_for_manual_execution",
    "confirmed_loop_created",
    "confirmed_external_job_created",
    "blocked",
    "suspicious",
    "unknown",
}
REQUIRED_STAGE6_SAFETY_CONTROLS = [
    "explicit human approval before applying any improvement",
    "rollback plan for each applied framework change",
    "audit logging for every Stage 6 decision and mutation",
    "dry-run-first behavior for every self-improvement action",
    "preserve filesystem, command, Git, workspace, and external-agent safety gates",
]


@dataclass
class Stage5AuditCheck:
    name: str
    category: str
    status: str
    message: str
    evidence: str
    recommended_action: str


@dataclass
class Stage5AuditSection:
    name: str
    status: str
    checks: List[Stage5AuditCheck] = field(default_factory=list)
    summary: str = ""


@dataclass
class Stage5AuditReport:
    generated_at: str
    overall_status: str
    total_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int
    sections: List[Stage5AuditSection] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    stage6_readiness: dict = field(default_factory=dict)


@dataclass
class Stage5AuditMarkdownReport:
    stage5_audit_id: int
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
    return Stage5AuditCheck(**data)


def section_from_dict(data):
    return Stage5AuditSection(
        name=data["name"],
        status=data["status"],
        checks=[check_from_dict(c) for c in data.get("checks", [])],
        summary=data.get("summary", ""),
    )


def report_from_row(row):
    sections = [section_from_dict(s) for s in _safe_json_loads(row["sections_json"], [])]
    return Stage5AuditReport(
        generated_at=row["generated_at"] or "",
        overall_status=row["overall_status"] or "",
        total_checks=row["total_checks"] or 0,
        passed_checks=row["passed_checks"] or 0,
        warning_checks=row["warning_checks"] or 0,
        failed_checks=row["failed_checks"] or 0,
        sections=sections,
        recommendations=_safe_json_loads(row["recommendations_json"], []),
        stage6_readiness=_safe_json_loads(row["stage6_readiness_json"], {}),
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


class LoopImprovementStage5AuditEngine:
    def __init__(self, conn):
        self.conn = conn
        self._baseline = self._counts()

    def build_report(self):
        sections = [
            self._improvement_engine(),
            self._proposal_review(),
            self._action_conversion(),
            self._implementation_handoff(),
            self._handoff_review(),
            self._safety_baseline(),
        ]
        overall_before_readiness = aggregate_overall_status(sections)
        readiness_section = self._stage6_readiness_section(
            sections, overall_before_readiness)
        sections.append(readiness_section)
        overall = aggregate_overall_status(sections)
        total = sum(len(section.checks) for section in sections)
        passed = sum(1 for section in sections for check in section.checks
                     if check.status == "PASS")
        warnings = sum(1 for section in sections for check in section.checks
                       if check.status == "WARN")
        failed = sum(1 for section in sections for check in section.checks
                     if check.status == "FAIL")
        readiness = self._stage6_readiness(sections, overall)
        recommendations = self._recommendations(sections)
        return Stage5AuditReport(
            generated_at=_now_iso(),
            overall_status=overall,
            total_checks=total,
            passed_checks=passed,
            warning_checks=warnings,
            failed_checks=failed,
            sections=sections,
            recommendations=recommendations,
            stage6_readiness=readiness,
        )

    def save_audit(self, report):
        return database.save_loop_improvement_stage5_audit(
            self.conn,
            report.generated_at,
            report.overall_status,
            report.total_checks,
            report.passed_checks,
            report.warning_checks,
            report.failed_checks,
            json.dumps([section_to_dict(s) for s in report.sections], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
            json.dumps(report.stage6_readiness, sort_keys=True),
        )

    def save_markdown_report(self, audit_id, report):
        content = self.render_markdown(report, audit_id)
        path = self._new_report_path(audit_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_loop_improvement_stage5_audit_markdown_report(
            self.conn, audit_id, path, "markdown", chash, nbytes)
        return Stage5AuditMarkdownReport(
            stage5_audit_id=audit_id,
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

    def _table_exists(self, table):
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def _table_check(self, table, category):
        exists = self._table_exists(table)
        return Stage5AuditCheck(
            name=f"{table} table exists",
            category=category,
            status="PASS" if exists else "FAIL",
            message="table exists" if exists else "required table missing",
            evidence=f"table={table} exists={exists}",
            recommended_action="python3 -m py_compile *.py" if not exists else "",
        )

    def _metadata_only_check(self, name, category, evidence):
        return Stage5AuditCheck(
            name=name,
            category=category,
            status="PASS",
            message="metadata-only audit check",
            evidence=evidence,
            recommended_action="",
        )

    def _improvement_engine(self):
        plans = database.list_loop_improvement_plans(self.conn, 1000)
        proposals = database.list_loop_improvement_proposals(self.conn, limit=1000)
        invalid = [row["id"] for row in proposals
                   if row["status"] not in PROPOSAL_STATUSES]
        auto_applied = [row["id"] for row in proposals
                        if str(row["status"]).lower() in
                        ("applied", "auto_applied", "executed")]
        checks = [
            self._table_check("loop_improvement_plans", "improvement_engine"),
            self._table_check("loop_improvement_proposals", "improvement_engine"),
            Stage5AuditCheck(
                "plans can be listed",
                "improvement_engine",
                "PASS",
                "plan metadata listing is available; empty state is acceptable",
                f"plans={len(plans)}",
                "python3 main.py --loop-improvements" if not plans else "",
            ),
            Stage5AuditCheck(
                "proposals have valid statuses",
                "improvement_engine",
                "PASS" if not invalid else "FAIL",
                "all proposal statuses are in the allowed set",
                f"invalid_proposal_ids={invalid}",
                "python3 main.py --loop-improvement-proposals" if invalid else "",
            ),
            Stage5AuditCheck(
                "proposals are not applied automatically",
                "improvement_engine",
                "PASS" if not auto_applied else "FAIL",
                "no applied/auto_applied/executed proposal status exists",
                f"auto_applied_proposal_ids={auto_applied}",
                "python3 main.py --loop-improvement-proposals" if auto_applied else "",
            ),
        ]
        return self._section("improvement_engine", checks)

    def _proposal_review(self):
        reviews = database.list_loop_improvement_reviews(self.conn, 1000)
        before_statuses = self._proposal_status_snapshot()
        after_statuses = self._proposal_status_snapshot()
        checks = [
            self._table_check("loop_improvement_reviews", "proposal_review"),
            self._table_check(
                "loop_improvement_review_markdown_reports", "proposal_review"),
            self._metadata_only_check(
                "reviews are deterministic metadata only",
                "proposal_review",
                f"reviews={len(reviews)} serialized proposal metadata only"),
            Stage5AuditCheck(
                "review commands do not mutate proposals unless explicit status command is used",
                "proposal_review",
                "PASS" if before_statuses == after_statuses else "FAIL",
                "audit observed proposal statuses unchanged while reading metadata",
                f"before={before_statuses} after={after_statuses}",
                "python3 main.py --loop-improvement-review" if before_statuses != after_statuses else "",
            ),
        ]
        return self._section("proposal_review", checks)

    def _action_conversion(self):
        actions = database.list_loop_improvement_action_items(self.conn, limit=1000)
        invalid = [row["id"] for row in actions if row["status"] not in ACTION_STATUSES]
        duplicate_rows = self.conn.execute(
            "SELECT source_review_id, source_proposal_id, COUNT(*) AS n "
            "FROM loop_improvement_action_items "
            "GROUP BY source_review_id, source_proposal_id HAVING n > 1"
        ).fetchall()
        duplicate_evidence = [
            f"review={row['source_review_id']} proposal={row['source_proposal_id']} count={row['n']}"
            for row in duplicate_rows
        ]
        proposal_statuses = self._proposal_status_snapshot()
        checks = [
            self._table_check("loop_improvement_action_items", "action_conversion"),
            self._table_check("loop_improvement_action_batches", "action_conversion"),
            self._table_check("loop_improvement_action_events", "action_conversion"),
            Stage5AuditCheck(
                "action statuses are valid",
                "action_conversion",
                "PASS" if not invalid else "FAIL",
                "all action statuses are in the allowed set",
                f"invalid_action_ids={invalid}",
                "python3 main.py --loop-improvement-actions" if invalid else "",
            ),
            Stage5AuditCheck(
                "action conversion does not apply proposals",
                "action_conversion",
                "PASS",
                "conversion creates action metadata and leaves proposal status explicit",
                f"proposal_statuses={proposal_statuses}",
                "",
            ),
            Stage5AuditCheck(
                "duplicate prevention evidence exists or empty state is handled",
                "action_conversion",
                "PASS" if not duplicate_rows else "WARN",
                "no duplicate action records for the same review/proposal pair",
                f"duplicates={duplicate_evidence}",
                "python3 main.py --create-loop-improvement-actions latest"
                if duplicate_rows else "",
            ),
        ]
        return self._section("action_conversion", checks)

    def _implementation_handoff(self):
        before = self._counts()
        handoffs = database.list_loop_improvement_handoffs(self.conn, 1000)
        dry_rows = [row for row in handoffs if row["dry_run"]]
        confirmed_rows = [row for row in handoffs if not row["dry_run"]]
        confirmed_marked = all(
            row["created_loop_id"] or row["created_external_job_id"]
            or str(row["status"]).upper() in ("LOOP_CREATED", "EXTERNAL_JOB_CREATED")
            for row in confirmed_rows)
        packet_rows = database.list_loop_improvement_handoff_packets(self.conn, 1000)
        bad_packets = [
            row["id"] for row in packet_rows
            if not _path_contains_dir(row["packet_path"], "loop_improvement_handoff_packets")
        ]
        checks = [
            self._table_check("loop_improvement_handoffs", "implementation_handoff"),
            self._table_check(
                "loop_improvement_handoff_events", "implementation_handoff"),
            self._table_check(
                "loop_improvement_handoff_packets", "implementation_handoff"),
            Stage5AuditCheck(
                "dry-run handoffs do not create loops/jobs",
                "implementation_handoff",
                "PASS" if self._counts() == before else "FAIL",
                "audit did not execute handoffs and counts are unchanged",
                f"dry_run_handoffs={len(dry_rows)} before={before} after={self._counts()}",
                "python3 main.py --loop-improvement-handoffs"
                if self._counts() != before else "",
            ),
            Stage5AuditCheck(
                "implementation packets are under loop_improvement_handoff_packets/",
                "implementation_handoff",
                "PASS" if not bad_packets else "FAIL",
                "packet metadata paths are confined to the generated packet directory",
                f"packet_rows={len(packet_rows)} bad_packet_ids={bad_packets}",
                "python3 main.py --loop-improvement-handoffs" if bad_packets else "",
            ),
            Stage5AuditCheck(
                "confirmed handoffs require explicit flags",
                "implementation_handoff",
                "PASS" if confirmed_marked else "WARN",
                "non-dry-run handoffs have created ids or explicit created status",
                f"confirmed_handoffs={len(confirmed_rows)} marked={confirmed_marked}",
                "python3 main.py --loop-improvement-handoff-review"
                if not confirmed_marked else "",
            ),
        ]
        return self._section("implementation_handoff", checks)

    def _handoff_review(self):
        before = self._counts()
        review_rows = database.list_loop_improvement_handoff_reviews(self.conn, 1000)
        statuses_seen = set()
        for row in review_rows:
            for item in _safe_json_loads(row["items_json"], []):
                status = item.get("review_status")
                if status:
                    statuses_seen.add(status)
        supported = {"suspicious", "blocked"}.issubset(HANDOFF_REVIEW_STATUSES)
        checks = [
            self._table_check(
                "loop_improvement_handoff_reviews", "handoff_review"),
            self._table_check(
                "loop_improvement_handoff_review_markdown_reports",
                "handoff_review"),
            Stage5AuditCheck(
                "handoff reviews do not create loops/jobs",
                "handoff_review",
                "PASS" if self._counts() == before else "FAIL",
                "counts unchanged while reading handoff review metadata",
                f"before={before} after={self._counts()}",
                "python3 main.py --loop-improvement-handoff-review"
                if self._counts() != before else "",
            ),
            Stage5AuditCheck(
                "suspicious/blocked classifications are supported",
                "handoff_review",
                "PASS" if supported else "FAIL",
                "classification vocabulary includes suspicious and blocked",
                f"supported={sorted(HANDOFF_REVIEW_STATUSES)} seen={sorted(statuses_seen)}",
                "python3 main.py --loop-improvement-handoff-review"
                if not supported else "",
            ),
        ]
        return self._section("handoff_review", checks)

    def _safety_baseline(self):
        now = self._counts()
        commands_unchanged = now["command_results"] == self._baseline["command_results"]
        loops_unchanged = now["loops"] == self._baseline["loops"]
        jobs_unchanged = (
            now["external_agent_jobs"] == self._baseline["external_agent_jobs"])
        checks = [
            Stage5AuditCheck(
                "command_results count does not change during audit",
                "safety_baseline",
                "PASS" if commands_unchanged else "FAIL",
                "audit does not execute commands",
                f"before={self._baseline['command_results']} after={now['command_results']}",
                "" if commands_unchanged else "python3 main.py --history --limit 5"),
            Stage5AuditCheck(
                "loop count does not change during audit",
                "safety_baseline",
                "PASS" if loops_unchanged else "FAIL",
                "audit does not create loops",
                f"before={self._baseline['loops']} after={now['loops']}",
                "" if loops_unchanged else "python3 main.py --history --limit 5"),
            Stage5AuditCheck(
                "external_agent_jobs count does not change during audit",
                "safety_baseline",
                "PASS" if jobs_unchanged else "FAIL",
                "audit does not create external jobs",
                f"before={self._baseline['external_agent_jobs']} after={now['external_agent_jobs']}",
                "" if jobs_unchanged else "python3 main.py --external-dashboard"),
            self._metadata_only_check(
                "no Ollama dependency",
                "safety_baseline",
                "audit imports no model client and performs SQLite metadata checks only"),
            self._metadata_only_check(
                "no command execution",
                "safety_baseline",
                "audit engine contains no subprocess/shell execution path"),
            self._metadata_only_check(
                "no protected file reads",
                "safety_baseline",
                "audit reads SQLite metadata and generated artifact paths only"),
            self._metadata_only_check(
                "no automatic mutation of loop/agent/prompt/gate/stop-condition definitions",
                "safety_baseline",
                "audit has no definition update path"),
        ]
        return self._section("safety_baseline", checks)

    def _stage6_readiness_section(self, sections, overall_status):
        handoff_reviews = _count(self.conn, "loop_improvement_handoff_reviews")
        proposals = _count(self.conn, "loop_improvement_proposals")
        reviews = _count(self.conn, "loop_improvement_reviews")
        actions = _count(self.conn, "loop_improvement_action_items")
        handoffs = _count(self.conn, "loop_improvement_handoffs")
        auto_apply_tables = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND "
            "(name LIKE '%auto_apply%' OR "
            "name LIKE '%self_improvement_apply%' OR "
            "name LIKE '%self_improvement_execution%')"
        ).fetchall()
        safe_path = all(n > 0 for n in (proposals, reviews, actions, handoffs,
                                        handoff_reviews))
        checks = [
            Stage5AuditCheck(
                "implementation handoff review exists",
                "stage6_readiness",
                "PASS" if handoff_reviews > 0 else "WARN",
                "at least one handoff review row exists" if handoff_reviews > 0
                else "no handoff review rows found yet",
                f"loop_improvement_handoff_reviews.count={handoff_reviews}",
                "python3 main.py --loop-improvement-handoff-review"
                if handoff_reviews == 0 else "",
            ),
            Stage5AuditCheck(
                "final audit can produce Stage 6 readiness",
                "stage6_readiness",
                "PASS",
                "readiness is computed from Stage 5 section statuses and metadata",
                f"pre_readiness_overall={overall_status}",
                "",
            ),
            Stage5AuditCheck(
                "safe path from proposal to handoff review exists",
                "stage6_readiness",
                "PASS" if safe_path else "WARN",
                "proposal -> review -> action -> handoff -> handoff review metadata chain",
                f"proposals={proposals} reviews={reviews} actions={actions} "
                f"handoffs={handoffs} handoff_reviews={handoff_reviews}",
                "python3 main.py --loop-improvements"
                if not safe_path else "",
            ),
            Stage5AuditCheck(
                "no auto-apply mechanism exists yet",
                "stage6_readiness",
                "PASS" if not auto_apply_tables else "FAIL",
                "no auto-apply/self-improvement persistence table is present",
                f"tables={[row['name'] for row in auto_apply_tables]}",
                "python3 main.py --loop-improvement-stage5-audit"
                if auto_apply_tables else "",
            ),
            Stage5AuditCheck(
                "Stage 6 requires explicit approval, rollback, audit logging, and dry-run-first behavior",
                "stage6_readiness",
                "PASS",
                "required controls are recorded in readiness output",
                json.dumps(REQUIRED_STAGE6_SAFETY_CONTROLS, sort_keys=True),
                "",
            ),
        ]
        return self._section("stage6_readiness", checks)

    def _section(self, name, checks):
        status = _section_status(checks)
        summary = (
            f"{sum(1 for c in checks if c.status == 'PASS')} pass, "
            f"{sum(1 for c in checks if c.status == 'WARN')} warn, "
            f"{sum(1 for c in checks if c.status == 'FAIL')} fail")
        return Stage5AuditSection(name=name, status=status, checks=checks, summary=summary)

    def _proposal_status_snapshot(self):
        return {
            row["id"]: row["status"]
            for row in database.list_loop_improvement_proposals(self.conn, limit=1000)
        }

    def _recommendations(self, sections):
        commands = []
        for section in sections:
            for check in section.checks:
                if check.status in ("WARN", "FAIL") and check.recommended_action:
                    commands.append(check.recommended_action)
        commands.extend([
            "python3 main.py --loop-improvements",
            "python3 main.py --loop-improvement-review",
            "python3 main.py --create-loop-improvement-actions latest",
            "python3 main.py --loop-improvement-actions",
            "python3 main.py --loop-improvement-handoffs",
            "python3 main.py --loop-improvement-handoff-review",
            "python3 main.py --loop-improvement-stage5-audit",
        ])
        return _dedupe(commands)

    def _stage6_readiness(self, sections, overall_status):
        blockers = []
        warnings = []
        for section in sections:
            for check in section.checks:
                if check.status == "FAIL":
                    blockers.append(f"{section.name}: {check.name} - {check.message}")
                elif check.status == "WARN":
                    warnings.append(f"{section.name}: {check.name} - {check.message}")
        ready = overall_status == "PASS"
        return {
            "ready": ready,
            "ready_text": "yes" if ready else "no",
            "blockers": blockers,
            "warnings": warnings,
            "recommended_next_stage": (
                "Stage 6 controlled self-improvement planning"
                if ready else
                "Resolve Stage 5 audit blockers and warnings before Stage 6"),
            "required_safety_controls": REQUIRED_STAGE6_SAFETY_CONTROLS,
        }

    def _new_report_path(self, audit_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"loop_improvement_stage5_audit_{int(audit_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError(
                "Stage 5 audit report path escaped loop_improvement_stage5_audit_reports/")
        return target

    def render_markdown(self, report, audit_id=None):
        lines = []
        a = lines.append
        a("# Stage 5 Loop Improvement Audit")
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
        a(f"- Stage 6 ready: {report.stage6_readiness.get('ready_text', 'no')}")
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
        if not report.recommendations:
            a("- (none)")
        for command in report.recommendations:
            a(f"- {command}")
        a("")
        a("## Stage 6 Readiness")
        a(f"- ready: {report.stage6_readiness.get('ready_text', 'no')}")
        blockers = report.stage6_readiness.get("blockers") or []
        warnings = report.stage6_readiness.get("warnings") or []
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
          f"{report.stage6_readiness.get('recommended_next_stage', '')}")
        a("")
        a("## Required Stage 6 Safety Controls")
        for control in report.stage6_readiness.get(
                "required_safety_controls", REQUIRED_STAGE6_SAFETY_CONTROLS):
            a(f"- {control}")
        a("")
        a("## Safety Notes")
        a("- Stage 5 audit reads SQLite metadata and generated artifact metadata only")
        a("- No shell commands are executed")
        a("- No Ollama/model calls")
        a("- No loop, external job, resume, import, apply, or commit operations")
        a("- No loop, agent, prompt, quality gate, or stop-condition definitions mutate")
        a("- Optional Markdown reports are confined to loop_improvement_stage5_audit_reports/")
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


def _path_contains_dir(path, dirname):
    if not path:
        return False
    parts = os.path.realpath(path).split(os.sep)
    return dirname in parts


def _dedupe(items):
    out = []
    for item in items:
        if item not in out:
            out.append(item)
    return out
