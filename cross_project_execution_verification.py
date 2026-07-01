"""Stage 10.5 — Post-Execution Verification Runner."""

import datetime
from dataclasses import dataclass, field

import database


@dataclass
class CrossProjectExecutionVerificationFinding:
    status: str
    category: str
    message: str
    evidence: str = ""


@dataclass
class CrossProjectExecutionVerificationRun:
    id: int
    attempt_id: int
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


def verification_run_from_row(conn, row):
    findings = [
        CrossProjectExecutionVerificationFinding(
            status=r["status"] or "", category=r["category"] or "",
            message=r["message"] or "", evidence=r["evidence"] or "")
        for r in database.list_cross_project_execution_verification_findings(
            conn, row["id"])
    ]
    return CrossProjectExecutionVerificationRun(
        id=row["id"], attempt_id=row["attempt_id"],
        generated_at=row["generated_at"] or "",
        overall_status=row["overall_status"] or "",
        total_findings=row["total_findings"] or 0,
        passed_findings=row["passed_findings"] or 0,
        failed_findings=row["failed_findings"] or 0,
        blocked_findings=row["blocked_findings"] or 0,
        summary=row["summary"] or "", findings=findings)


class CrossProjectExecutionVerificationRunner:
    def __init__(self, conn):
        self.conn = conn

    def verify(self, attempt_id):
        attempt = database.get_cross_project_execution_attempt(self.conn, int(attempt_id))
        if attempt is None:
            raise ValueError(f"no cross-project execution attempt {attempt_id}")
        findings = []
        if attempt["allowed"]:
            findings.append(CrossProjectExecutionVerificationFinding(
                "PASS", "command_allowed", "Execution command passed allowlist gate."))
        else:
            findings.append(CrossProjectExecutionVerificationFinding(
                "BLOCKED", "command_allowed", attempt["reason_if_blocked"] or "blocked"))
        if attempt["status"] == "succeeded":
            findings.append(CrossProjectExecutionVerificationFinding(
                "PASS", "attempt_status", "Execution attempt succeeded."))
        else:
            findings.append(CrossProjectExecutionVerificationFinding(
                "FAIL", "attempt_status", f"Execution attempt status={attempt['status']}"))
        blocked = sum(1 for f in findings if f.status == "BLOCKED")
        failed = sum(1 for f in findings if f.status == "FAIL")
        passed = sum(1 for f in findings if f.status == "PASS")
        overall = "BLOCKED" if blocked else ("FAIL" if failed else "PASS")
        rid = database.save_cross_project_execution_verification_run(
            self.conn, attempt["id"], _now_iso(), overall, len(findings),
            passed, failed, blocked,
            f"Post-execution verification for attempt {attempt['id']}: {overall}")
        for item in findings:
            database.save_cross_project_execution_verification_finding(
                self.conn, rid, attempt["id"], item.status, item.category,
                item.message, item.evidence)
        return self.get_run(rid)

    def get_run(self, run_id):
        row = database.get_cross_project_execution_verification_run(
            self.conn, int(run_id))
        return verification_run_from_row(self.conn, row) if row else None
