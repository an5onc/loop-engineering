"""Stage 8.1 — Policy Evaluation Engine.

Deterministically evaluates all ACTIVE governance policies against Stage 7
metadata (registered projects, validations, approvals, handoffs, schedules,
audits). Produces an evaluation with one finding per (policy, rule, subject).
Active, unexpired waivers suppress a matching failing/warning finding.

Metadata-only: no commands, no model calls, no project file-content reads, no
cross-project writes. Writes only evaluation/finding rows and optional Markdown
reports under ``governance_policy_evaluation_reports/``.
"""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

import database
import multi_project_governance_policies as policies_mod
import multi_project_registry as registry_mod


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "governance_policy_evaluation_reports")


@dataclass
class GovernanceEvaluationReport:
    id: int
    generated_at: str
    overall_status: str
    total_findings: int
    passed_findings: int
    warning_findings: int
    failed_findings: int
    waived_findings: int
    policy_keys: List[str] = field(default_factory=list)
    findings: List[dict] = field(default_factory=list)
    summary: str = ""


@dataclass
class EvaluationMarkdownReport:
    evaluation_id: int
    report_path: str
    report_format: str
    content_hash: str
    bytes_written: int
    created_at: str


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def signature(policy_key, rule_key, subject) -> str:
    return f"{policy_key}::{rule_key}::{subject}"


def is_report_path(path) -> bool:
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def waiver_is_active(row, now=None) -> bool:
    """A waiver suppresses a finding only when status='active' and not expired."""
    if (row["status"] or "") != "active":
        return False
    expiry = row["expiry"]
    if not expiry:
        return True
    parsed = _parse_iso(expiry)
    if parsed is None:
        return False
    cmp_now = now or datetime.datetime.now()
    if parsed.tzinfo is not None:
        cmp_now = datetime.datetime.now(parsed.tzinfo)
    return parsed >= cmp_now


class GovernanceEvaluationEngine:
    def __init__(self, conn):
        self.conn = conn
        self.registry = registry_mod.ProjectRegistry(conn)
        self.policies = policies_mod.GovernancePolicyRegistry(conn)

    # -- context building ------------------------------------------------ #
    def _project_views(self):
        views = []
        for project in self.registry.list_projects():
            if project.status != "active":
                continue
            root_exists = bool(project.root_path) and os.path.isdir(project.root_path)
            latest = database.latest_project_validation_report(
                self.conn, project.project_key)
            views.append(policies_mod.ProjectView(
                project_key=project.project_key, status=project.status,
                root_exists=root_exists, repo_url=project.repo_url,
                default_branch=project.default_branch,
                safety_profile_name=project.safety_profile_name,
                protected_paths=project.protected_paths,
                latest_validation_status=(
                    latest["overall_status"] if latest else "(none)"),
                has_validation=latest is not None))
        return views

    def _fleet_view(self):
        pending = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_approvals WHERE status='pending'"
        ).fetchone()["n"]
        bad_handoffs = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_handoffs h "
            "LEFT JOIN cross_project_approvals a ON h.approval_id=a.id "
            "WHERE a.id IS NULL OR a.status != 'approved'").fetchone()["n"]
        bad_schedules = self.conn.execute(
            "SELECT COUNT(*) AS n FROM multi_project_schedules s "
            "LEFT JOIN cross_project_approvals a ON s.approval_id=a.id "
            "WHERE a.id IS NULL OR a.status != 'approved'").fetchone()["n"]
        audits = self.conn.execute(
            "SELECT COUNT(*) AS n FROM multi_project_audits").fetchone()["n"]
        total = len([p for p in self.registry.list_projects()])
        return policies_mod.FleetView(
            total_projects=total, pending_approvals=pending,
            handoffs_without_approved_approval=bad_handoffs,
            schedules_without_approved_approval=bad_schedules,
            multi_project_audit_count=audits)

    def _active_waivers(self):
        now = datetime.datetime.now()
        active = {}
        for row in database.list_active_governance_waivers(self.conn):
            if waiver_is_active(row, now):
                active[row["signature"]] = row["id"]
        return active

    # -- evaluation ------------------------------------------------------ #
    def evaluate(self, persist=True) -> GovernanceEvaluationReport:
        policies = [p for p in self.policies.list_policies()
                    if p.status == "active"]
        project_views = self._project_views()
        fleet_view = self._fleet_view()
        waivers = self._active_waivers()

        findings = []
        for policy in policies:
            for rule_key in policy.rule_keys:
                rule = policies_mod.RULE_REGISTRY.get(rule_key)
                if rule is None:
                    continue
                severity = policies_mod.effective_severity(policy, rule_key)
                if rule.scope == "project":
                    for view in project_views:
                        findings.append(self._finding(
                            policy, rule_key, view.project_key, severity, rule,
                            view, waivers))
                else:  # fleet
                    findings.append(self._finding(
                        policy, rule_key, "fleet", severity, rule, fleet_view,
                        waivers))

        passed = sum(1 for f in findings if f["status"] == "PASS")
        warnings = sum(1 for f in findings if f["status"] == "WARN")
        failed = sum(1 for f in findings if f["status"] == "FAIL")
        waived = sum(1 for f in findings if f["status"] == "WAIVED")
        overall = ("FAIL" if failed else
                   "PASS_WITH_WARNINGS" if warnings else "PASS")
        summary = (f"{len(policies)} active policy(ies); {passed} pass, "
                   f"{warnings} warning, {failed} fail, {waived} waived")
        generated_at = _now_iso()
        report = GovernanceEvaluationReport(
            id=0, generated_at=generated_at, overall_status=overall,
            total_findings=len(findings), passed_findings=passed,
            warning_findings=warnings, failed_findings=failed,
            waived_findings=waived,
            policy_keys=[p.policy_key for p in policies], findings=findings,
            summary=summary)
        if persist:
            report.id = database.save_governance_policy_evaluation(
                self.conn, generated_at, overall, len(findings), passed, warnings,
                failed, waived, json.dumps(report.policy_keys), summary)
            for f in findings:
                fid = database.save_governance_policy_finding(
                    self.conn, report.id, f["policy_key"], f["rule_key"],
                    f["subject"], f["severity"], f["status"], f["signature"],
                    f["evidence"], f["message"], f.get("waiver_id"))
                f["id"] = fid
        return report

    def _finding(self, policy, rule_key, subject, severity, rule, view, waivers):
        ok, evidence = rule.evaluate(view)
        sig = signature(policy.policy_key, rule_key, subject)
        waiver_id = None
        if ok:
            status = "PASS"
        elif sig in waivers:
            status = "WAIVED"
            waiver_id = waivers[sig]
        else:
            status = "FAIL" if severity == "fail" else "WARN"
        message = (f"{rule_key} {'ok' if ok else 'violated'} for {subject}")
        return {"policy_key": policy.policy_key, "rule_key": rule_key,
                "subject": subject, "severity": severity, "status": status,
                "signature": sig, "evidence": evidence, "message": message,
                "waiver_id": waiver_id}

    def get_evaluation(self, evaluation_id) -> Optional[GovernanceEvaluationReport]:
        row = database.get_governance_policy_evaluation(self.conn, evaluation_id)
        if row is None:
            return None
        findings = [
            {"id": f["id"], "policy_key": f["policy_key"], "rule_key": f["rule_key"],
             "subject": f["subject"], "severity": f["severity"],
             "status": f["status"], "signature": f["signature"],
             "evidence": f["evidence"], "message": f["message"],
             "waiver_id": f["waiver_id"]}
            for f in database.list_governance_policy_findings(self.conn, evaluation_id)
        ]
        return GovernanceEvaluationReport(
            id=row["id"], generated_at=row["generated_at"] or "",
            overall_status=row["overall_status"] or "",
            total_findings=row["total_findings"] or 0,
            passed_findings=row["passed_findings"] or 0,
            warning_findings=row["warning_findings"] or 0,
            failed_findings=row["failed_findings"] or 0,
            waived_findings=row["waived_findings"] or 0,
            policy_keys=_safe_json_loads(row["policy_keys_json"], []),
            findings=findings, summary=row["summary"] or "")

    def list_evaluations(self, limit=50):
        return database.list_governance_policy_evaluations(self.conn, limit=limit)

    # -- markdown -------------------------------------------------------- #
    def save_markdown_report(self, evaluation_id) -> EvaluationMarkdownReport:
        report = self.get_evaluation(evaluation_id)
        if report is None:
            raise ValueError(f"no governance evaluation {evaluation_id}")
        content = self.render_markdown(report)
        path = self._new_report_path(evaluation_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_governance_policy_evaluation_markdown_report(
            self.conn, evaluation_id, path, "markdown", chash, nbytes)
        return EvaluationMarkdownReport(
            evaluation_id=evaluation_id, report_path=path, report_format="markdown",
            content_hash=chash, bytes_written=nbytes, created_at=_now_iso())

    def _new_report_path(self, evaluation_id) -> str:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"governance_evaluation_{int(evaluation_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("evaluation report path escaped reports directory")
        return target

    def render_markdown(self, report) -> str:
        lines = []
        a = lines.append
        a("# Governance Policy Evaluation")
        a("")
        a("## Summary")
        a(f"- Evaluation ID: {report.id}")
        a(f"- Generated at: {report.generated_at}")
        a(f"- Overall status: {report.overall_status}")
        a(f"- Policies: {', '.join(report.policy_keys) or '(none active)'}")
        a(f"- Findings: {report.total_findings} "
          f"(pass={report.passed_findings} warn={report.warning_findings} "
          f"fail={report.failed_findings} waived={report.waived_findings})")
        a("")
        a("## Findings")
        if not report.findings:
            a("- (none)")
        for f in report.findings:
            a(f"- [{f['status']}] {f['policy_key']} / {f['rule_key']} "
              f":: {f['subject']} ({f['severity']}) — {f['evidence']}")
        a("")
        a("## Safety Notes")
        for note in (
            "Deterministic, metadata-only evaluation.",
            "No project file contents read; no commands; no model calls.",
            "Approved, unexpired waivers suppress matching findings only.",
        ):
            a(f"- {note}")
        a("")
        return "\n".join(lines)
