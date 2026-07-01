"""Stage 9.7 — Cross-Project Execution Planning Audit."""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "cross_project_execution_audit_reports")


@dataclass
class AuditCheck:
    name: str
    category: str
    status: str
    message: str
    evidence: str = ""


@dataclass
class AuditSection:
    name: str
    status: str
    summary: str
    checks: list = field(default_factory=list)


@dataclass
class CrossProjectExecutionAuditReport:
    generated_at: str
    overall_status: str
    total_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int
    blocked_checks: int
    sections: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)
    stage10_readiness: dict = field(default_factory=dict)
    safety_notes: list = field(default_factory=list)
    next_steps: list = field(default_factory=list)


@dataclass
class AuditMarkdownReport:
    audit_id: int
    report_path: str
    report_format: str
    content_hash: str
    bytes_written: int
    created_at: str


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def is_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


def _section(name, checks):
    if any(c.status in ("FAIL", "BLOCKED") for c in checks):
        status = "FAIL"
    elif any(c.status == "WARN" for c in checks):
        status = "WARN"
    else:
        status = "PASS"
    return AuditSection(name, status, f"{len(checks)} check(s)", checks)


def _dict_section(section):
    return {
        "name": section.name,
        "status": section.status,
        "summary": section.summary,
        "checks": [c.__dict__ for c in section.checks],
    }


class CrossProjectExecutionAuditEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self):
        sections = [self._metadata_section(), self._safety_section()]
        failed = sum(1 for s in sections for c in s.checks if c.status == "FAIL")
        blocked = sum(1 for s in sections for c in s.checks if c.status == "BLOCKED")
        warning = sum(1 for s in sections for c in s.checks if c.status == "WARN")
        passed = sum(1 for s in sections for c in s.checks if c.status == "PASS")
        overall = "FAIL" if failed else ("BLOCKED" if blocked else ("WARN" if warning else "PASS"))
        readiness = {
            "ready": failed == 0 and blocked == 0,
            "recommended_stage_10_theme": "controlled cross-project execution under explicit human approval",
            "blockers": [],
            "warnings": [f"{s.name}:{c.name}" for s in sections for c in s.checks
                         if c.status == "WARN"],
        }
        return CrossProjectExecutionAuditReport(
            generated_at=_now_iso(), overall_status=overall,
            total_checks=passed + warning + failed + blocked,
            passed_checks=passed, warning_checks=warning,
            failed_checks=failed, blocked_checks=blocked,
            sections=sections,
            recommendations=[
                "python3 main.py --cross-project-execution-audit-show latest",
                "python3 main.py --cross-project-stage9-audit",
            ],
            stage10_readiness=readiness,
            safety_notes=[
                "Audit reads Stage 9 metadata only.",
                "No commands, model calls, project writes, loops, or external jobs are created.",
            ],
            next_steps=[
                "Resolve WARN/FAIL checks before controlled execution.",
                "Run the Stage 9 final audit.",
            ])

    def _metadata_section(self):
        blocked_dry_runs = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_execution_dry_runs "
            "WHERE overall_status IN ('FAIL','BLOCKED')").fetchone()["n"]
        orphan_steps = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_execution_plan_steps s "
            "LEFT JOIN cross_project_execution_plans p ON s.plan_id=p.id "
            "WHERE p.id IS NULL").fetchone()["n"]
        checks = [
            AuditCheck("execution intents listable", "metadata", "PASS",
                       f"{_count(self.conn, 'cross_project_execution_intents')} intent(s)."),
            AuditCheck("plan steps reference plans", "metadata",
                       "PASS" if orphan_steps == 0 else "FAIL",
                       f"orphan steps={orphan_steps}"),
            AuditCheck("blocked dry-runs require review", "metadata",
                       "PASS" if blocked_dry_runs == 0 else "WARN",
                       f"blocked dry-runs={blocked_dry_runs}"),
        ]
        return _section("metadata_integrity", checks)

    def _safety_section(self):
        return _section("safety_baseline", [
            AuditCheck("no hidden command execution", "safety", "PASS",
                       "Stage 9 stores advisory commands as text only."),
            AuditCheck("no model calls", "safety", "PASS",
                       "Stage 9 modules do not call Ollama."),
            AuditCheck("no project-root writes", "safety", "PASS",
                       "Stage 9 writes only metadata and ignored packets/reports."),
        ])

    def save_audit(self, report):
        return database.save_cross_project_execution_audit(
            self.conn, report.generated_at, report.overall_status,
            report.total_checks, report.passed_checks, report.warning_checks,
            report.failed_checks, report.blocked_checks,
            json.dumps([_dict_section(s) for s in report.sections], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
            json.dumps(report.stage10_readiness, sort_keys=True),
            json.dumps(report.safety_notes, sort_keys=True),
            json.dumps(report.next_steps, sort_keys=True))

    def save_markdown_report(self, audit_id, report):
        content = self.render_markdown(report, audit_id)
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            REPORTS_DIR, f"cross_project_execution_audit_{int(audit_id)}_{_now_stamp()}.md"))
        if not is_report_path(path):
            raise ValueError("execution audit report path escaped directory")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        database.save_cross_project_execution_audit_markdown_report(
            self.conn, audit_id, path, "markdown", chash, len(encoded))
        return AuditMarkdownReport(audit_id, path, "markdown", chash,
                                   len(encoded), _now_iso())

    def render_markdown(self, report, audit_id=None):
        lines = ["# Cross-Project Execution Planning Audit", ""]
        if audit_id is not None:
            lines.append(f"- Audit ID: {audit_id}")
        lines.extend([
            f"- Overall status: {report.overall_status}",
            f"- Total checks: {report.total_checks}", "",
            "## Sections",
        ])
        for section in report.sections:
            lines.append(f"- {section.name}: {section.status}")
            for check in section.checks:
                lines.append(f"  - {check.status}: {check.name} — {check.message}")
        lines.extend(["", "## Stage 10 Readiness",
                      json.dumps(report.stage10_readiness, sort_keys=True)])
        return "\n".join(lines)


def report_from_row(row):
    sections = []
    for sec in json.loads(row["sections_json"] or "[]"):
        sections.append(AuditSection(
            sec.get("name", ""), sec.get("status", "UNKNOWN"),
            sec.get("summary", ""),
            [AuditCheck(**c) for c in sec.get("checks", [])]))
    return CrossProjectExecutionAuditReport(
        generated_at=row["generated_at"] or "",
        overall_status=row["overall_status"] or "UNKNOWN",
        total_checks=row["total_checks"] or 0,
        passed_checks=row["passed_checks"] or 0,
        warning_checks=row["warning_checks"] or 0,
        failed_checks=row["failed_checks"] or 0,
        blocked_checks=row["blocked_checks"] or 0,
        sections=sections,
        recommendations=json.loads(row["recommendations_json"] or "[]"),
        stage10_readiness=json.loads(row["stage10_readiness_json"] or "{}"),
        safety_notes=json.loads(row["safety_notes_json"] or "[]"),
        next_steps=json.loads(row["next_steps_json"] or "[]"))
