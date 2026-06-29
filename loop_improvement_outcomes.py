"""Improvement Outcome Tracker (Stage 6.7).

This stage records deterministic outcome metadata for controlled
self-improvement attempts after application and verification. It reads only
existing application, verification, rollback, approval, and proposal metadata.
It never applies patches, restores files, executes commands, runs tests, calls
Ollama, creates loops/jobs, commits, imports completions, or mutates framework
definitions.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database
import loop_improvement_patch_application
import loop_improvement_post_apply_verification


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "improvement_outcome_reports")
OUTCOME_STATUSES = {
    "successful",
    "successful_with_warnings",
    "failed_verification",
    "rollback_recommended",
    "rolled_back",
    "inconclusive",
    "blocked",
    "deferred",
}


@dataclass
class ImprovementOutcomeSignal:
    signal_type: str
    status: str
    message: str
    evidence: str
    weight: int


@dataclass
class ImprovementOutcomeRecord:
    id: int
    application_attempt_id: int
    verification_plan_id: int
    verification_report_id: int
    patch_proposal_id: int
    approval_id: int
    application_plan_id: int
    generated_at: str
    outcome_status: str
    success_score: int
    risk_before: str
    risk_after: str
    verification_status: str
    rollback_status: str
    summary: str
    signals: List[ImprovementOutcomeSignal] = field(default_factory=list)
    lessons: List[str] = field(default_factory=list)
    follow_up_actions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)


@dataclass
class ImprovementOutcomeReport:
    id: int
    outcome_id: int
    generated_at: str
    overall_status: str
    summary: str
    signals: List[ImprovementOutcomeSignal] = field(default_factory=list)
    lessons: List[str] = field(default_factory=list)
    follow_up_actions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)


@dataclass
class ImprovementOutcomeMarkdownReport:
    outcome_report_id: int
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


def signal_to_dict(signal):
    return asdict(signal)


def signal_from_dict(data):
    return ImprovementOutcomeSignal(**data)


def outcome_from_row(row):
    return ImprovementOutcomeRecord(
        id=row["id"],
        application_attempt_id=row["application_attempt_id"],
        verification_plan_id=row["verification_plan_id"] or 0,
        verification_report_id=row["verification_report_id"] or 0,
        patch_proposal_id=row["patch_proposal_id"] or 0,
        approval_id=row["approval_id"] or 0,
        application_plan_id=row["application_plan_id"] or 0,
        generated_at=row["generated_at"] or "",
        outcome_status=row["outcome_status"] or "",
        success_score=row["success_score"] or 0,
        risk_before=row["risk_before"] or "unknown",
        risk_after=row["risk_after"] or "unknown",
        verification_status=row["verification_status"] or "missing",
        rollback_status=row["rollback_status"] or "unknown",
        summary=row["summary"] or "",
        signals=[
            signal_from_dict(item)
            for item in _safe_json_loads(row["signals_json"], [])
        ],
        lessons=_safe_json_loads(row["lessons_json"], []),
        follow_up_actions=_safe_json_loads(row["follow_up_actions_json"], []),
        warnings=_safe_json_loads(row["warnings_json"], []),
        next_steps=_safe_json_loads(row["next_steps_json"], []),
    )


def report_from_row(row):
    return ImprovementOutcomeReport(
        id=row["id"],
        outcome_id=row["outcome_id"],
        generated_at=row["generated_at"] or "",
        overall_status=row["overall_status"] or "",
        summary=row["summary"] or "",
        signals=[
            signal_from_dict(item)
            for item in _safe_json_loads(row["signals_json"], [])
        ],
        lessons=_safe_json_loads(row["lessons_json"], []),
        follow_up_actions=_safe_json_loads(row["follow_up_actions_json"], []),
        warnings=_safe_json_loads(row["warnings_json"], []),
        next_steps=_safe_json_loads(row["next_steps_json"], []),
    )


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


class LoopImprovementOutcomeEngine:
    def __init__(self, conn):
        self.conn = conn

    def create_outcome_record(self, application_attempt_id):
        row = database.get_loop_improvement_patch_application_attempt(
            self.conn, int(application_attempt_id))
        if row is None:
            raise ValueError(
                f"no loop improvement patch application attempt {application_attempt_id}"
            )
        attempt = loop_improvement_patch_application.application_attempt_from_row(row)
        proposal = database.get_loop_improvement_patch_proposal(
            self.conn, attempt.patch_proposal_id)
        approval = database.get_loop_improvement_patch_approval(
            self.conn, attempt.approval_id)
        app_plan = database.get_loop_improvement_application_plan(
            self.conn, attempt.application_plan_id)
        verification_plan = database.get_latest_post_apply_verification_plan_for_attempt(
            self.conn, int(application_attempt_id))
        verification_report = None
        if verification_plan is not None:
            verification_report = (
                database.get_latest_post_apply_verification_report_for_plan(
                    self.conn, verification_plan["id"])
            )
        rollback_snapshot = database.get_latest_loop_improvement_rollback_snapshot_for_attempt(
            self.conn, int(application_attempt_id))

        verification_status = _verification_status(
            verification_plan, verification_report)
        rollback_status = _rollback_status(attempt, rollback_snapshot)
        risk_before = _risk_before(verification_plan)
        outcome_status = _outcome_status(
            attempt, verification_status, rollback_status)
        success_score = _success_score(
            outcome_status, verification_status, rollback_status,
            bool(proposal), bool(approval), bool(verification_plan),
            bool(verification_report))
        risk_after = _risk_after(risk_before, outcome_status, rollback_status)
        signals = _signals(
            attempt=attempt,
            application_attempt_id=int(application_attempt_id),
            proposal=proposal,
            approval=approval,
            app_plan=app_plan,
            verification_plan=verification_plan,
            verification_report=verification_report,
            rollback_snapshot=rollback_snapshot,
            verification_status=verification_status,
            rollback_status=rollback_status,
            outcome_status=outcome_status,
        )
        lessons = _lessons(signals, outcome_status, verification_status)
        follow_up_actions = _follow_up_actions(outcome_status, verification_status)
        warnings = _warnings(signals, outcome_status, risk_before)
        next_steps = _next_steps(outcome_status)
        return ImprovementOutcomeRecord(
            id=0,
            application_attempt_id=int(application_attempt_id),
            verification_plan_id=verification_plan["id"] if verification_plan else 0,
            verification_report_id=verification_report["id"] if verification_report else 0,
            patch_proposal_id=attempt.patch_proposal_id,
            approval_id=attempt.approval_id,
            application_plan_id=attempt.application_plan_id,
            generated_at=_now_iso(),
            outcome_status=outcome_status,
            success_score=success_score,
            risk_before=risk_before,
            risk_after=risk_after,
            verification_status=verification_status,
            rollback_status=rollback_status,
            summary=_summary(outcome_status, success_score, verification_status),
            signals=signals,
            lessons=lessons,
            follow_up_actions=follow_up_actions,
            warnings=warnings,
            next_steps=next_steps,
        )

    def save_outcome_record(self, record):
        return database.save_improvement_outcome_record(
            self.conn,
            record.application_attempt_id,
            record.verification_plan_id,
            record.verification_report_id,
            record.patch_proposal_id,
            record.approval_id,
            record.application_plan_id,
            record.generated_at,
            record.outcome_status,
            record.success_score,
            record.risk_before,
            record.risk_after,
            record.verification_status,
            record.rollback_status,
            record.summary,
            json.dumps([signal_to_dict(s) for s in record.signals], sort_keys=True),
            json.dumps(record.lessons, sort_keys=True),
            json.dumps(record.follow_up_actions, sort_keys=True),
            json.dumps(record.warnings, sort_keys=True),
            json.dumps(record.next_steps, sort_keys=True),
        )

    def create_report(self, outcome_id):
        row = database.get_improvement_outcome_record(self.conn, int(outcome_id))
        if row is None:
            raise ValueError(f"no improvement outcome record {outcome_id}")
        record = outcome_from_row(row)
        return ImprovementOutcomeReport(
            id=0,
            outcome_id=int(outcome_id),
            generated_at=_now_iso(),
            overall_status=record.outcome_status,
            summary=record.summary,
            signals=list(record.signals),
            lessons=list(record.lessons),
            follow_up_actions=list(record.follow_up_actions),
            warnings=list(record.warnings),
            next_steps=list(record.next_steps),
        )

    def save_report(self, report):
        return database.save_improvement_outcome_report(
            self.conn,
            report.outcome_id,
            report.generated_at,
            report.overall_status,
            report.summary,
            json.dumps([signal_to_dict(s) for s in report.signals], sort_keys=True),
            json.dumps(report.lessons, sort_keys=True),
            json.dumps(report.follow_up_actions, sort_keys=True),
            json.dumps(report.warnings, sort_keys=True),
            json.dumps(report.next_steps, sort_keys=True),
        )

    def save_markdown_report(self, report_id, report):
        content = self.render_markdown(report, report_id)
        path = self._new_report_path(report_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_improvement_outcome_markdown_report(
            self.conn, report_id, path, "markdown", chash, nbytes)
        return ImprovementOutcomeMarkdownReport(
            outcome_report_id=report_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def render_markdown(self, report, report_id=None):
        lines = []
        a = lines.append
        a("# Improvement Outcome Report")
        a("")
        a("## Summary")
        if report_id is not None:
            a(f"- Report ID: {report_id}")
        a(f"- Outcome ID: {report.outcome_id}")
        a(f"- Generated at: {report.generated_at}")
        a(f"- Overall status: {report.overall_status}")
        a(f"- Summary: {report.summary}")
        a("")
        a("## Signals")
        _markdown_signals(a, report.signals)
        a("")
        a("## Lessons")
        _markdown_list(a, report.lessons)
        a("")
        a("## Follow-Up Actions")
        _markdown_list(a, report.follow_up_actions)
        a("")
        a("## Warnings")
        _markdown_list(a, report.warnings)
        a("")
        a("## Next Steps")
        _markdown_list(a, report.next_steps)
        a("")
        a("## Safety Notes")
        _markdown_list(a, _safety_notes())
        a("")
        return "\n".join(lines)

    def _new_report_path(self, report_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"improvement_outcome_{int(report_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("improvement outcome report path escaped directory")
        return target


def _verification_status(verification_plan, verification_report):
    if verification_report is not None:
        return verification_report["overall_status"] or "missing"
    if verification_plan is None:
        return "missing"
    plan = loop_improvement_post_apply_verification.plan_from_row(verification_plan)
    if plan.status == "manually_verified":
        return "PASS"
    if plan.status == "failed":
        return "FAIL"
    if plan.status == "blocked":
        return "BLOCKED"
    if plan.status == "deferred":
        return "PENDING"
    return "PENDING"


def _rollback_status(attempt, rollback_snapshot):
    if rollback_snapshot is not None:
        return "snapshot_available"
    if attempt.status == loop_improvement_patch_application.BLOCKED_ROLLBACK_REQUIRED:
        return "required_missing"
    if attempt.rollback_snapshot_required and not attempt.rollback_snapshot_present:
        return "required_missing"
    return "not_required_or_missing"


def _risk_before(verification_plan):
    if verification_plan is None:
        return "unknown"
    return verification_plan["risk_level"] or "unknown"


def _outcome_status(attempt, verification_status, rollback_status):
    if rollback_status == "required_missing":
        return "rollback_recommended"
    if verification_status == "FAIL":
        return "failed_verification"
    if verification_status == "BLOCKED":
        return "blocked"
    if verification_status == "PASS":
        return "successful"
    if verification_status == "PASS_WITH_WARNINGS":
        return "successful_with_warnings"
    if verification_status in ("PENDING", "missing"):
        return "inconclusive"
    if attempt.status in ("blocked", "blocked_rollback_required"):
        return "blocked"
    return "inconclusive"


def _success_score(outcome_status, verification_status, rollback_status,
                   has_proposal, has_approval, has_plan, has_report):
    if outcome_status == "successful":
        score = 92
    elif outcome_status == "successful_with_warnings":
        score = 82
    elif outcome_status == "failed_verification":
        score = 25
    elif outcome_status in ("blocked", "rollback_recommended"):
        score = 20
    elif outcome_status == "rolled_back":
        score = 30
    elif outcome_status == "deferred":
        score = 35
    else:
        score = 40
    if rollback_status == "snapshot_available":
        score += 5
    if has_proposal:
        score += 2
    if has_approval:
        score += 2
    if has_plan:
        score += 2
    if has_report:
        score += 2
    if verification_status == "missing":
        score -= 10
    return max(0, min(100, score))


def _risk_after(risk_before, outcome_status, rollback_status):
    if outcome_status in ("successful", "successful_with_warnings"):
        return "decreased" if rollback_status == "snapshot_available" else risk_before
    if outcome_status in ("failed_verification", "blocked", "rollback_recommended"):
        return "increased"
    return risk_before


def _signals(**ctx):
    signals = []
    attempt = ctx["attempt"]
    _add(signals, "application_attempt_found", "pass",
         f"Application attempt {ctx['application_attempt_id']} metadata loaded.",
         f"application_attempt_id={ctx['application_attempt_id']}",
         10)
    _add_present(signals, "approval_found", ctx["approval"],
                 f"approval_id={attempt.approval_id}", 8)
    _add_present(signals, "patch_proposal_found", ctx["proposal"],
                 f"patch_proposal_id={attempt.patch_proposal_id}", 8)
    _add_present(signals, "rollback_snapshot_found", ctx["rollback_snapshot"],
                 f"application_attempt_id={ctx['application_attempt_id']}", 10)
    _add_present(signals, "verification_plan_found", ctx["verification_plan"],
                 f"application_attempt_id={ctx['application_attempt_id']}", 12)
    _add_present(signals, "verification_report_found", ctx["verification_report"],
                 f"verification_status={ctx['verification_status']}", 12)
    if ctx["verification_status"] in ("PASS", "PASS_WITH_WARNINGS"):
        _add(signals, "verification_passed", "pass",
             "Post-apply verification passed or passed with warnings.",
             ctx["verification_status"], 20)
    elif ctx["verification_status"] == "FAIL":
        _add(signals, "verification_failed", "fail",
             "Post-apply verification failed.", "FAIL", -20)
    if ctx["rollback_status"] == "required_missing":
        _add(signals, "rollback_needed", "warning",
             "Rollback is required or recommended before treating the attempt as complete.",
             ctx["rollback_status"], -15)
    if (ctx["approval"] and ctx["proposal"] and ctx["verification_plan"] and
            ctx["rollback_status"] == "snapshot_available"):
        _add(signals, "safety_requirements_satisfied", "pass",
             "Approval, proposal, verification, and rollback metadata are present.",
             "metadata chain complete", 15)
    missing = []
    if not ctx["approval"]:
        missing.append("approval")
    if not ctx["proposal"]:
        missing.append("patch_proposal")
    if not ctx["verification_plan"]:
        missing.append("verification_plan")
    if not ctx["verification_report"]:
        missing.append("verification_report")
    if missing:
        _add(signals, "missing_metadata", "warning",
             "Some outcome source metadata is missing.",
             ", ".join(missing), -10)
    if ctx["outcome_status"] in ("inconclusive", "rollback_recommended",
                                 "failed_verification", "blocked", "deferred"):
        _add(signals, "manual_follow_up_required", "warning",
             "Operator follow-up is required before closure.",
             ctx["outcome_status"], -5)
    return signals


def _add_present(signals, signal_type, row, evidence, weight):
    if row is None:
        _add(signals, signal_type, "missing",
             f"{signal_type.replace('_', ' ')} metadata was not found.",
             evidence, -abs(weight))
    else:
        _add(signals, signal_type, "pass",
             f"{signal_type.replace('_', ' ')} metadata was found.",
             evidence, abs(weight))


def _add(signals, signal_type, status, message, evidence, weight):
    signals.append(ImprovementOutcomeSignal(
        signal_type=signal_type,
        status=status,
        message=message,
        evidence=evidence,
        weight=weight,
    ))


def _lessons(signals, outcome_status, verification_status):
    lessons = []
    signal_types = {signal.signal_type for signal in signals}
    if "verification_passed" in signal_types:
        lessons.append("Manual post-apply verification is the strongest success signal.")
    if "rollback_snapshot_found" in signal_types:
        lessons.append("Rollback metadata improves confidence in controlled application.")
    if "missing_metadata" in signal_types:
        lessons.append("Outcome confidence drops when verification or source metadata is missing.")
    if outcome_status == "failed_verification":
        lessons.append("Failed verification should feed future dry-run and approval criteria.")
    if verification_status == "missing":
        lessons.append("Do not classify high-risk improvements as successful without verification.")
    return lessons or ["No durable lesson can be inferred until more metadata is available."]


def _follow_up_actions(outcome_status, verification_status):
    if outcome_status in ("successful", "successful_with_warnings"):
        return ["Record the result and use lessons in future improvement planning."]
    if outcome_status == "failed_verification":
        return ["Investigate failed checks and consider a new improvement action."]
    if outcome_status == "rollback_recommended":
        return ["Review rollback snapshot and decide manually whether rollback is needed."]
    if outcome_status == "blocked":
        return ["Resolve blockers before any further self-improvement work."]
    if outcome_status == "deferred":
        return ["Keep the outcome open until verification evidence is available."]
    if verification_status in ("missing", "PENDING"):
        return ["Create or complete post-apply verification before closing the outcome."]
    return ["Review outcome metadata manually."]


def _warnings(signals, outcome_status, risk_before):
    warnings = [
        "Stage 6.7 records outcome metadata only and never executes commands.",
        "No command_results rows are created by outcome tracking.",
    ]
    if outcome_status not in ("successful", "successful_with_warnings"):
        warnings.append("Outcome is not successful; manual follow-up is required.")
    if risk_before == "high" and outcome_status not in (
            "successful", "successful_with_warnings"):
        warnings.append("High-risk changes require passed verification before closure.")
    if any(signal.signal_type == "missing_metadata" for signal in signals):
        warnings.append("Missing metadata makes the outcome less reliable.")
    return warnings


def _next_steps(outcome_status):
    if outcome_status in ("successful", "successful_with_warnings"):
        return ["Keep audit metadata and continue only with explicit operator direction."]
    if outcome_status == "failed_verification":
        return ["Stop, preserve rollback path, and plan a corrective follow-up."]
    if outcome_status == "rollback_recommended":
        return ["Stop and review rollback options manually; do not restore automatically."]
    if outcome_status == "blocked":
        return ["Resolve blockers and regenerate outcome metadata after new evidence."]
    return ["Gather verification evidence and update the outcome status manually."]


def _summary(outcome_status, success_score, verification_status):
    return (
        f"Outcome {outcome_status} with success score {success_score}/100 "
        f"and verification status {verification_status}."
    )


def _safety_notes():
    return [
        "Stage 6.7 never executes commands or runs tests automatically.",
        "Stage 6.7 never applies patches or restores files.",
        "Stage 6.7 never calls Ollama, creates loops, creates external jobs, imports completions, or resumes jobs.",
        "Stage 6.7 reads metadata only and writes outcome metadata plus optional Markdown reports.",
        "Manual status updates do not apply, rollback, commit, or mutate framework definitions.",
    ]


def _markdown_signals(append, signals):
    if not signals:
        append("(none)")
        return
    for signal in signals:
        append(f"- {signal.signal_type} [{signal.status}]")
        append(f"  - Message: {signal.message}")
        append(f"  - Evidence: {signal.evidence}")
        append(f"  - Weight: {signal.weight}")


def _markdown_list(append, items):
    if not items:
        append("(none)")
        return
    for item in items:
        append(f"- {item}")
