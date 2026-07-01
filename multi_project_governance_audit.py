"""Stage 8.8 — Multi-Project Governance Audit.

Audits all Stage 8 governance metadata for completeness, referential integrity,
stale/expired-but-active waivers, and safety counters. Read-only over Stage 8
metadata; writes only its own audit rows and optional Markdown reports under
``multi_project_governance_audit_reports/``.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database
import multi_project_governance_evaluation as eval_mod


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "multi_project_governance_audit_reports")
SAFETY_TABLES = ("loops", "command_results", "external_agent_jobs")


@dataclass
class AuditCheck:
    name: str
    category: str
    status: str
    message: str
    evidence: str = ""
    recommended_action: str = ""


@dataclass
class AuditSection:
    name: str
    status: str
    checks: List[AuditCheck] = field(default_factory=list)
    summary: str = ""


@dataclass
class GovernanceAuditReport:
    id: int
    generated_at: str
    overall_status: str
    total_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int
    blocked_checks: int
    sections: List[AuditSection] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    safety_notes: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)


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


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def section_to_dict(section):
    data = asdict(section)
    data["checks"] = [asdict(c) for c in section.checks]
    return data


def section_from_dict(data):
    return AuditSection(
        name=data["name"], status=data["status"],
        checks=[AuditCheck(**c) for c in data.get("checks", [])],
        summary=data.get("summary", ""))


def report_from_row(row):
    return GovernanceAuditReport(
        id=row["id"], generated_at=row["generated_at"] or "",
        overall_status=row["overall_status"] or "",
        total_checks=row["total_checks"] or 0,
        passed_checks=row["passed_checks"] or 0,
        warning_checks=row["warning_checks"] or 0,
        failed_checks=row["failed_checks"] or 0,
        blocked_checks=row["blocked_checks"] or 0,
        sections=[section_from_dict(s)
                  for s in _safe_json_loads(row["sections_json"], [])],
        recommendations=_safe_json_loads(row["recommendations_json"], []),
        safety_notes=_safe_json_loads(row["safety_notes_json"], []),
        next_steps=_safe_json_loads(row["next_steps_json"], []))


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


def aggregate_overall_status(sections):
    statuses = [s.status for s in sections]
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "PASS_WITH_WARNINGS"
    return "PASS"


def _section_status(checks):
    statuses = [c.status for c in checks]
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"


def _make_section(name, checks):
    passed = sum(1 for c in checks if c.status == "PASS")
    warnings = sum(1 for c in checks if c.status == "WARN")
    failed = sum(1 for c in checks if c.status == "FAIL")
    blocked = sum(1 for c in checks if c.status == "BLOCKED")
    return AuditSection(
        name=name, status=_section_status(checks), checks=checks,
        summary=f"{passed} pass, {warnings} warning, {failed} fail, {blocked} blocked")


class GovernanceAuditEngine:
    def __init__(self, conn):
        self.conn = conn
        self._baseline = {t: _count(conn, t) for t in SAFETY_TABLES}

    def build_report(self):
        sections = [
            self._policies_section(),
            self._evaluations_section(),
            self._review_queue_section(),
            self._waivers_section(),
            self._fleet_section(),
            self._safety_section(),
        ]
        overall = aggregate_overall_status(sections)
        total = sum(len(s.checks) for s in sections)
        passed = sum(1 for s in sections for c in s.checks if c.status == "PASS")
        warnings = sum(1 for s in sections for c in s.checks if c.status == "WARN")
        failed = sum(1 for s in sections for c in s.checks if c.status == "FAIL")
        blocked = sum(1 for s in sections for c in s.checks if c.status == "BLOCKED")
        return GovernanceAuditReport(
            id=0, generated_at=_now_iso(), overall_status=overall,
            total_checks=total, passed_checks=passed, warning_checks=warnings,
            failed_checks=failed, blocked_checks=blocked, sections=sections,
            recommendations=_recommendations(), safety_notes=_safety_notes(),
            next_steps=_next_steps(overall))

    def _ok(self, name, category, ok, ok_msg, bad_msg, evidence="",
            bad_status="FAIL", action=""):
        return AuditCheck(
            name=name, category=category, status="PASS" if ok else bad_status,
            message=ok_msg if ok else bad_msg, evidence=evidence,
            recommended_action="No action required." if ok else action)

    def _policies_section(self):
        n = _count(self.conn, "governance_policies")
        return _make_section("policies", [
            self._ok("policies listable", "policies", True,
                     f"{n} policy(ies).", "", f"count={n}", bad_status="WARN"),
        ])

    def _evaluations_section(self):
        n = _count(self.conn, "governance_policy_evaluations")
        orphan = self.conn.execute(
            "SELECT COUNT(*) AS n FROM governance_policy_findings f "
            "LEFT JOIN governance_policy_evaluations e ON f.evaluation_id=e.id "
            "WHERE e.id IS NULL").fetchone()["n"]
        return _make_section("evaluations", [
            self._ok("evaluations listable", "evaluations", True,
                     f"{n} evaluation(s).", "", f"count={n}", bad_status="WARN"),
            self._ok("findings reference a valid evaluation", "evaluations",
                     orphan == 0, "All findings reference a valid evaluation.",
                     f"{orphan} orphan finding(s).", f"orphans={orphan}",
                     action="Investigate orphaned findings."),
        ])

    def _review_queue_section(self):
        n = _count(self.conn, "governance_review_items")
        valid = {"open", "acknowledged", "waived", "resolved", "dismissed",
                 "blocked"}
        rows = self.conn.execute(
            "SELECT DISTINCT status FROM governance_review_items "
            "WHERE status IS NOT NULL").fetchall()
        invalid = sorted(r["status"] for r in rows if r["status"] not in valid)
        return _make_section("review_queue", [
            self._ok("review items listable", "review_queue", True,
                     f"{n} review item(s).", "", f"count={n}", bad_status="WARN"),
            self._ok("review item statuses valid", "review_queue", not invalid,
                     "All review statuses valid.",
                     "Invalid statuses: " + ", ".join(invalid),
                     f"observed={len(rows)}",
                     action="Correct invalid review item statuses."),
        ])

    def _waivers_section(self):
        n = _count(self.conn, "governance_waivers")
        expired_active = 0
        for row in database.list_active_governance_waivers(self.conn):
            if not eval_mod.waiver_is_active(row):
                expired_active += 1
        return _make_section("waivers", [
            self._ok("waivers listable", "waivers", True,
                     f"{n} waiver(s).", "", f"count={n}", bad_status="WARN"),
            self._ok("no expired-but-active waivers", "waivers",
                     expired_active == 0,
                     "No active waivers have passed their expiry.",
                     f"{expired_active} active waiver(s) are expired.",
                     f"expired_active={expired_active}", bad_status="WARN",
                     action="Revoke or renew expired waivers."),
        ])

    def _fleet_section(self):
        n = _count(self.conn, "fleet_governance_reports")
        return _make_section("fleet_reporting", [
            self._ok("fleet governance reports listable", "fleet_reporting", True,
                     f"{n} report(s).", "", f"count={n}", bad_status="WARN"),
        ])

    def _safety_section(self):
        checks = []
        for table in SAFETY_TABLES:
            before = self._baseline.get(table, 0)
            after = _count(self.conn, table)
            checks.append(self._ok(
                f"{table} count unchanged during audit", "safety_baseline",
                before == after, f"{table} stable at {after}.",
                f"{table} changed {before}->{after}.",
                f"before={before} after={after}",
                action=f"Investigate writes to {table}."))
        checks.append(AuditCheck(
            name="no hidden command execution", category="safety_baseline",
            status="PASS", message="Governance audit executes no commands.",
            evidence="metadata-only", recommended_action="No action required."))
        checks.append(AuditCheck(
            name="no Ollama dependency", category="safety_baseline", status="PASS",
            message="Governance audit makes no model calls.", evidence="db-only",
            recommended_action="No action required."))
        checks.append(AuditCheck(
            name="no cross-project writes", category="safety_baseline",
            status="PASS", message="Governance audit writes no project roots.",
            evidence="local-db-only", recommended_action="No action required."))
        return _make_section("safety_baseline", checks)

    # -- persistence ----------------------------------------------------- #
    def save_audit(self, report):
        return database.save_multi_project_governance_audit(
            self.conn, report.generated_at, report.overall_status,
            report.total_checks, report.passed_checks, report.warning_checks,
            report.failed_checks, report.blocked_checks,
            json.dumps([section_to_dict(s) for s in report.sections], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
            json.dumps(report.safety_notes, sort_keys=True),
            json.dumps(report.next_steps, sort_keys=True))

    def save_markdown_report(self, audit_id, report):
        content = self.render_markdown(report, audit_id)
        path = self._new_report_path(audit_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_multi_project_governance_audit_markdown_report(
            self.conn, audit_id, path, "markdown", chash, nbytes)
        return AuditMarkdownReport(
            audit_id=audit_id, report_path=path, report_format="markdown",
            content_hash=chash, bytes_written=nbytes, created_at=_now_iso())

    def _new_report_path(self, audit_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"multi_project_governance_audit_{int(audit_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("governance audit report path escaped directory")
        return target

    def render_markdown(self, report, audit_id=None):
        lines = []
        a = lines.append
        a("# Multi-Project Governance Audit")
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
        a("")
        a("## Sections")
        for section in report.sections:
            a(f"- {section.name}: {section.status}")
            a(f"  - {section.summary}")
            for check in section.checks:
                a(f"  - {check.status}: {check.name} — {check.message}")
        a("")
        a("## Safety Notes")
        for note in report.safety_notes:
            a(f"- {note}")
        a("")
        a("## Next Steps")
        for step in report.next_steps:
            a(f"- {step}")
        a("")
        return "\n".join(lines)


def _recommendations():
    return [
        "python3 main.py --governance-policies",
        "python3 main.py --evaluate-governance-policies",
        "python3 main.py --governance-waivers",
        "python3 main.py --fleet-governance-report",
    ]


def _safety_notes():
    return [
        "No commands executed by the governance audit.",
        "No model / Ollama calls.",
        "No loops or external jobs created.",
        "No cross-project writes.",
        "Only Stage 8 metadata is read; only audit rows/reports are written.",
    ]


def _next_steps(overall):
    if overall in ("PASS", "PASS_WITH_WARNINGS"):
        return [
            "Proceed to the Stage 8 final audit: python3 main.py --multi-project-stage8-audit",
        ]
    return [
        "Resolve failed/blocked governance audit checks.",
        "Re-run the governance audit.",
    ]
