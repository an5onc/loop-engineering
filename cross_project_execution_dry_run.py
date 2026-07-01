"""Stage 9.4 — Dry-Run Validator for Cross-Project Execution Plans."""

import datetime
from dataclasses import dataclass, field
from typing import Optional

import database
import cross_project_execution_plans as plans_mod


@dataclass
class DryRunFinding:
    id: int
    dry_run_id: int
    plan_id: int
    project_key: str
    status: str
    category: str
    message: str
    evidence: str


@dataclass
class CrossProjectExecutionDryRunReport:
    id: int
    plan_id: int
    generated_at: str
    overall_status: str
    total_findings: int
    passed_findings: int
    warning_findings: int
    failed_findings: int
    blocked_findings: int
    summary: str
    findings: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def finding_from_row(row):
    return DryRunFinding(
        id=row["id"], dry_run_id=row["dry_run_id"], plan_id=row["plan_id"],
        project_key=row["project_key"] or "", status=row["status"] or "",
        category=row["category"] or "", message=row["message"] or "",
        evidence=row["evidence"] or "")


def report_from_row(conn, row):
    findings = [finding_from_row(r)
                for r in database.list_cross_project_execution_dry_run_findings(
                    conn, row["id"])]
    return CrossProjectExecutionDryRunReport(
        id=row["id"], plan_id=row["plan_id"],
        generated_at=row["generated_at"] or "",
        overall_status=row["overall_status"] or "UNKNOWN",
        total_findings=row["total_findings"] or 0,
        passed_findings=row["passed_findings"] or 0,
        warning_findings=row["warning_findings"] or 0,
        failed_findings=row["failed_findings"] or 0,
        blocked_findings=row["blocked_findings"] or 0,
        summary=row["summary"] or "", findings=findings)


class CrossProjectExecutionDryRunValidator:
    def __init__(self, conn):
        self.conn = conn
        self.plans = plans_mod.CrossProjectExecutionPlanBuilder(conn)

    def validate(self, plan_id):
        plan = self.plans.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"no cross-project execution plan {plan_id}")
        findings = []
        proposals = database.list_cross_project_execution_command_proposals(
            self.conn, plan_id=plan.id)
        proposal_step_ids = {p["step_id"] for p in proposals}
        for step in plan.steps:
            if step.status == "blocked":
                findings.append({
                    "project_key": step.project_key, "status": "BLOCKED",
                    "category": "blocked_step",
                    "message": step.blocked_reason or "step is blocked",
                    "evidence": f"step={step.id}",
                })
            elif not all(step.gating.get(k) is True for k in (
                    "requires_dry_run", "requires_human_approval",
                    "requires_validation", "no_auto_execution")):
                findings.append({
                    "project_key": step.project_key, "status": "BLOCKED",
                    "category": "missing_gating",
                    "message": "planned step is missing required execution gates",
                    "evidence": f"step={step.id}",
                })
            elif step.id not in proposal_step_ids:
                findings.append({
                    "project_key": step.project_key, "status": "BLOCKED",
                    "category": "missing_command_proposals",
                    "message": "planned step has no advisory command proposals",
                    "evidence": f"step={step.id}",
                })
            else:
                findings.append({
                    "project_key": step.project_key, "status": "PASS",
                    "category": "advisory_only",
                    "message": "step has advisory proposals and required gates",
                    "evidence": f"step={step.id}",
                })
        if not findings:
            findings.append({
                "project_key": "fleet", "status": "WARN",
                "category": "empty_plan",
                "message": "plan contains no project steps",
                "evidence": f"plan={plan.id}",
            })
        passed = sum(1 for f in findings if f["status"] == "PASS")
        warning = sum(1 for f in findings if f["status"] == "WARN")
        failed = sum(1 for f in findings if f["status"] == "FAIL")
        blocked = sum(1 for f in findings if f["status"] == "BLOCKED")
        overall = "BLOCKED" if blocked else ("FAIL" if failed else ("WARN" if warning else "PASS"))
        summary = (f"{len(findings)} finding(s): pass={passed} warn={warning} "
                   f"fail={failed} blocked={blocked}")
        dry_run_id = database.save_cross_project_execution_dry_run(
            self.conn, plan.id, _now_iso(), overall, len(findings),
            passed, warning, failed, blocked, summary)
        for f in findings:
            database.save_cross_project_execution_dry_run_finding(
                self.conn, dry_run_id, plan.id, f["project_key"], f["status"],
                f["category"], f["message"], f["evidence"])
        return self.get_dry_run(dry_run_id)

    def get_dry_run(self, dry_run_id) -> Optional[CrossProjectExecutionDryRunReport]:
        row = database.get_cross_project_execution_dry_run(self.conn, dry_run_id)
        return report_from_row(self.conn, row) if row else None

    def list_dry_runs(self, limit=50):
        return database.list_cross_project_execution_dry_runs(self.conn, limit=limit)
