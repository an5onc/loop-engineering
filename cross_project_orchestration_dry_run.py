"""Stage 11.1 — Orchestration Dry-Run Validator."""

import datetime
import json
from dataclasses import dataclass, field

import database
import cross_project_orchestration_plans as plans_mod


@dataclass
class CrossProjectOrchestrationDryRunFinding:
    status: str
    category: str
    message: str
    evidence: str = ""


@dataclass
class CrossProjectOrchestrationDryRun:
    id: int
    plan_id: int
    generated_at: str
    overall_status: str
    total_findings: int
    passed_findings: int
    failed_findings: int
    blocked_findings: int
    summary: str
    findings: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def dry_run_from_row(conn, row):
    findings = [
        CrossProjectOrchestrationDryRunFinding(
            status=r["status"] or "", category=r["category"] or "",
            message=r["message"] or "", evidence=r["evidence"] or "")
        for r in database.list_cross_project_orchestration_dry_run_findings(
            conn, row["id"])
    ]
    return CrossProjectOrchestrationDryRun(
        id=row["id"], plan_id=row["orchestration_plan_id"],
        generated_at=row["generated_at"] or "",
        overall_status=row["overall_status"] or "",
        total_findings=row["total_findings"] or 0,
        passed_findings=row["passed_findings"] or 0,
        failed_findings=row["failed_findings"] or 0,
        blocked_findings=row["blocked_findings"] or 0,
        summary=row["summary"] or "", findings=findings)


class CrossProjectOrchestrationDryRunValidator:
    def __init__(self, conn):
        self.conn = conn
        self.plans = plans_mod.CrossProjectOrchestrationPlanBuilder(conn)

    def validate(self, plan_id):
        plan = self.plans.get_plan(int(plan_id))
        if plan is None:
            raise ValueError(f"no cross-project orchestration plan {plan_id}")
        findings = []
        if not plan.steps:
            findings.append(CrossProjectOrchestrationDryRunFinding(
                "BLOCKED", "steps", "orchestration plan has no steps"))
        for step in plan.steps:
            if step.status == "ready":
                if not step.stage10_scope_check_id or not step.command_proposal_id:
                    findings.append(CrossProjectOrchestrationDryRunFinding(
                        "BLOCKED", "gating_metadata",
                        f"ready step {step.id} lacks Stage 10 gating metadata"))
                else:
                    findings.append(CrossProjectOrchestrationDryRunFinding(
                        "PASS", "gating_metadata",
                        f"step {step.id} has Stage 10 scope and command metadata"))
            elif step.command_proposal_id:
                findings.append(CrossProjectOrchestrationDryRunFinding(
                    "BLOCKED", "blocked_step_executable",
                    f"blocked step {step.id} still references executable command"))
            else:
                findings.append(CrossProjectOrchestrationDryRunFinding(
                    "PASS", "blocked_step_recorded",
                    f"blocked step {step.id} remains non-executable"))
        blocked = sum(1 for f in findings if f.status == "BLOCKED")
        failed = sum(1 for f in findings if f.status == "FAIL")
        passed = sum(1 for f in findings if f.status == "PASS")
        overall = "BLOCKED" if blocked else ("FAIL" if failed else "PASS")
        rid = database.save_cross_project_orchestration_dry_run(
            self.conn, plan.id, _now_iso(), overall, len(findings), passed,
            failed, blocked,
            f"Stage 11 orchestration dry-run for plan {plan.id}: {overall}")
        for item in findings:
            database.save_cross_project_orchestration_dry_run_finding(
                self.conn, rid, plan.id, item.status, item.category, item.message,
                item.evidence)
        return self.get_dry_run(rid)

    def get_dry_run(self, dry_run_id):
        row = database.get_cross_project_orchestration_dry_run(
            self.conn, int(dry_run_id))
        return dry_run_from_row(self.conn, row) if row else None
