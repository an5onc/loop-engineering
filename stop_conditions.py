"""Explicit Stop Conditions and Quality Gates (Stage 1.9).

Quality gates check *whether an attempt's output is acceptable* (valid JSON,
safe paths, safe commands, confidence, ...). Stop conditions decide *whether and
why the loop should stop* (approved, max retries, unsafe op, tests passed, ...).

This module is pure logic: the engine builds an EvalContext of precomputed
signals for each attempt and asks the StopConditionEngine to evaluate gates,
evaluate conditions, and produce a StopDecision. Keeping it side-effect-free
makes it directly unit-testable.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# --------------------------------------------------------------------------- #
# Definitions
# --------------------------------------------------------------------------- #
@dataclass
class StopCondition:
    name: str
    description: str
    condition_type: str
    severity: str
    enabled: bool = True
    config: dict = field(default_factory=dict)


@dataclass
class QualityGate:
    name: str
    description: str
    gate_type: str
    required: bool
    enabled: bool = True
    config: dict = field(default_factory=dict)


@dataclass
class StopConditionResult:
    condition_name: str
    triggered: bool
    severity: str
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class QualityGateResult:
    gate_name: str
    passed: bool
    required: bool
    severity: str
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class StopDecision:
    stop: bool
    final_status: Optional[str]
    stop_reason: Optional[str]
    severity: Optional[str]
    final_condition: Optional[str]
    required_failed_count: int
    success: bool


DEFAULT_MIN_CONFIDENCE = 0.70


# --------------------------------------------------------------------------- #
# Per-attempt signals
# --------------------------------------------------------------------------- #
@dataclass
class EvalContext:
    attempt: int
    max_attempts: int
    loop_name: str
    fs_enabled: bool
    term_enabled: bool
    review_only: bool
    coder_parse_ok: bool
    proposed_file_count: int
    files_changed: int
    unsafe_path_count: int
    unsafe_command_count: int
    commands_executed: int
    commands_failed: int
    command_timed_out: int
    review_parse_ok: bool
    review_approved: bool
    review_confidence: float
    min_reviewer_confidence: float
    analyst_used: bool
    analyst_parse_ok: bool
    tests_run: bool
    tests_passed: Optional[bool]
    repeated_failure: bool
    # Workspace signals (Stage 2.0)
    workspace_valid: bool = True
    workspace_write_blocked_count: int = 0
    protected_blocked_count: int = 0
    workspace_command_blocked_count: int = 0
    workspace_profile_valid: bool = True
    # Approval signals (Stage 2.2)
    approval_policy_valid: bool = True
    approval_declined: bool = False
    approval_declined_action_risk: str = "medium"
    # External coding agent signals (Stage 3.0 / 3.1)
    external_declined: bool = False
    external_violation: bool = False
    external_completion_failed: bool = False
    external_completion_mismatch: bool = False
    # Reviewer-consistency signals (Stage 3.2.2)
    review_required_changes: int = 0
    review_has_severe_issue: bool = False


# --------------------------------------------------------------------------- #
# Built-in registries
# --------------------------------------------------------------------------- #
def builtin_quality_gates() -> Dict[str, QualityGate]:
    g = [
        QualityGate("valid_coder_json", "Coder output must parse into structured JSON.", "format", True),
        QualityGate("safe_file_paths", "All file paths must stay inside workspace/.", "safety", True),
        QualityGate("safe_commands_only", "Only allowed commands may execute.", "safety", True),
        QualityGate("reviewer_json_valid", "Reviewer output must parse into review JSON.", "format", False),
        QualityGate("test_analyst_json_valid", "Test analyst output must parse into JSON when used.", "format", False),
        QualityGate("commands_successful", "Executed commands must exit successfully.", "result", False),
        QualityGate("files_written", "At least one file written for build/fix loops.", "result", False),
        QualityGate("reviewer_confidence_minimum", "Reviewer confidence must meet the minimum.", "quality", False),
        QualityGate("reviewer_consistency_valid", "Reviewer verdict must be internally consistent (no approved+low-confidence / approved+required-changes / approved+severe-issue).", "quality", True),
        QualityGate("workspace_valid", "Workspace exists and root path is valid.", "workspace", True),
        QualityGate("workspace_write_allowed", "All writes are inside allowed write paths.", "workspace", True),
        QualityGate("workspace_command_allowed", "All commands run inside allowed command paths.", "workspace", True),
        QualityGate("protected_paths_blocked", "Protected paths are not modified.", "workspace", True),
        QualityGate("workspace_profile_valid", "Selected workspace profile exists and validates.", "workspace", True),
        QualityGate("approval_policy_valid", "Approval policy is valid.", "approval", True),
        QualityGate("required_approval_obtained", "Required approval was obtained before a controlled action.", "approval", False),
        QualityGate("declined_approval_respected", "A declined approval prevented the action.", "approval", False),
        # Evaluated post-run by the report system (not in the attempt loop).
        QualityGate("report_generated", "A run report was generated and persisted.", "report", True),
        # Recorded when a scan runs / a loop uses project intelligence.
        QualityGate("project_intelligence_safe", "Project scan read only allowed, non-protected files.", "intel", True),
        # Recorded when a loop uses memory search.
        QualityGate("memory_context_safe", "Memory search was read-only (SQLite + internal reports).", "memory", True),
        # Recorded when a context pack is built / used.
        QualityGate("context_pack_safe", "Context pack read only allowed, non-protected files.", "context", True),
        # Task intake gates (Stage 2.9).
        QualityGate("task_intake_valid", "Intake JSON parsed correctly.", "intake", True),
        QualityGate("clarification_resolved", "Required clarification questions were answered.", "intake", True),
        QualityGate("intake_risk_accepted", "High/critical-risk tasks require approval before side effects.", "intake", True),
        # External coding agent gates (Stage 3.0).
        QualityGate("external_agent_handoff_safe", "Handoff prompt generated safely (no secrets, allowed paths only).", "external", True),
        QualityGate("external_agent_changes_within_workspace", "External agent changes stayed within allowed write paths.", "external", True),
        QualityGate("external_agent_completion_confirmed", "User confirmed external agent completion before review.", "external", True),
        # External completion import gates (Stage 3.1).
        QualityGate("external_completion_valid", "Completion was parsed or safely stored as raw text.", "external", True),
        QualityGate("external_completion_matches_workspace", "Claimed changes are consistent with the actual workspace.", "external", False),
        QualityGate("external_completion_reviewed", "Imported completion was passed to the Reviewer.", "external", True),
        # Resume gates (Stage 3.2).
        QualityGate("resume_loop_valid", "Loop exists and is resumable.", "resume", True),
        QualityGate("resume_completion_available", "Completion is available (provided or already imported).", "resume", True),
        QualityGate("resume_review_completed", "Reviewer ran after resume (unless blocked by a safety violation).", "resume", True),
        # External agent job gates (Stage 3.3).
        QualityGate("external_agent_job_packet_safe", "Job packet generated internally, no protected contents, allowed paths only, inside external_agent_jobs/.", "external", True),
        QualityGate("external_agent_job_resume_valid", "Resume targets a valid, matching, resumable job with completion available.", "external", True),
        QualityGate("external_agent_job_metadata_valid", "Job priority/labels/notes/archived/retry_count are valid and inert.", "external", True),
        QualityGate("external_completion_inbox_valid", "Inbox completion file exists inside its job dir, is the right name, parses (or is safe raw text), and imports via ResumeEngine.", "external", True),
        QualityGate("external_job_batch_selection_valid", "Batch selection resolves to existing jobs with valid filters/action; archived/cancelled skipped for sync.", "external", True),
        QualityGate("external_job_batch_action_safe", "Batch action made no deletes, ran no agent, auto-committed nothing, and used ResumeEngine for sync.", "external", True),
        QualityGate("external_batch_report_generated", "Batch report file exists inside external_batch_reports/ with saved metadata + content hash.", "external", True),
        QualityGate("external_job_health_check_safe", "External job health check was read-only unless --fix-safe and performed no commands, model calls, unsafe reads, resumes, imports, commits, or deletes.", "external", True),
    ]
    return {x.name: x for x in g}


def builtin_stop_conditions() -> Dict[str, StopCondition]:
    c = [
        StopCondition("reviewer_approved", "Stop when reviewer approves.", "success", "info"),
        StopCondition("max_retries_reached", "Stop when retry count reaches max.", "limit", "warning"),
        StopCondition("unsafe_operation_blocked", "Stop when an unsafe operation is attempted.", "safety", "critical"),
        StopCondition("repeated_failure", "Stop when the same failure repeats.", "failure", "warning"),
        StopCondition("no_files_changed", "Stop when expected file changes do not occur.", "result", "warning"),
        StopCondition("command_timeout", "Stop when a command times out.", "failure", "warning"),
        StopCondition("test_passed", "Stop successfully when tests pass and reviewer approves.", "success", "info"),
        StopCondition("test_failed_after_retries", "Stop when tests still fail after max retries.", "failure", "error"),
        StopCondition("workspace_violation_blocked", "Stop when workspace safety rules are violated.", "safety", "critical"),
        StopCondition("workspace_profile_invalid", "Stop when the workspace profile is missing or invalid.", "safety", "critical"),
        StopCondition("human_approval_declined", "Stop when human approval is declined for a required action.", "approval", "high"),
        StopCondition("needs_clarification", "Stop when clarification is required and not answered.", "intake", "high"),
        StopCondition("intake_blocked", "Stop when intake recommends blocking the task.", "intake", "critical"),
        StopCondition("intake_high_risk_requires_approval", "Stop when a high/critical-risk task has no approval enabled.", "intake", "high"),
        StopCondition("needs_external_agent", "Stop when an external agent handoff was generated but not completed.", "external", "high"),
        StopCondition("external_agent_workspace_violation", "Stop when the external agent changed files outside allowed paths.", "external", "critical"),
        StopCondition("external_agent_failed", "Stop when the external agent reported failure or completion was declined.", "external", "high"),
        StopCondition("external_completion_missing", "Stop when an external loop cannot continue (no completion).", "external", "high"),
        StopCondition("external_completion_failed", "Stop when completion status is failed or blocked.", "external", "high"),
        StopCondition("external_completion_workspace_mismatch", "Stop when claimed changes conflict with the workspace in a risky way.", "external", "critical"),
        StopCondition("resume_missing_completion", "Stop when resume is attempted without completion.", "resume", "high"),
        StopCondition("resume_invalid_loop_state", "Stop when resume is attempted on a non-resumable loop.", "resume", "high"),
        StopCondition("resume_workspace_violation", "Stop when the workspace changed outside allowed paths before/during resume.", "resume", "critical"),
        # External agent job conditions (Stage 3.3).
        StopCondition("external_agent_job_waiting", "Job created and waiting for external agent completion.", "external", "high"),
        StopCondition("external_agent_job_cancelled", "Job was cancelled by the user.", "external", "high"),
        StopCondition("external_agent_job_invalid", "Resume/cancel attempted for an invalid job.", "external", "high"),
        StopCondition("external_agent_job_archived", "Resume attempted on an archived job (unarchive first).", "external", "high"),
        StopCondition("external_completion_inbox_invalid", "Inbox completion file is malformed, outside the job dir, wrong job, or cannot safely resume.", "external", "high"),
        StopCondition("external_job_batch_invalid", "Batch request has an unknown action, invalid priority/label, no selected jobs, or jobs invalid for the action.", "external", "high"),
        StopCondition("external_batch_report_failed", "Batch report generation failed after a batch operation (batch result is unchanged).", "external", "warning"),
        StopCondition("external_job_health_critical", "Critical external job health issue detected and persisted as a health event.", "external", "critical"),
    ]
    return {x.name: x for x in c}


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
class StopConditionEngine:
    def __init__(self, stop_conditions: List[StopCondition],
                 quality_gates: List[QualityGate], min_reviewer_confidence: float):
        self.conditions = [c for c in stop_conditions if c.enabled]
        self.gates = [g for g in quality_gates if g.enabled]
        self.condition_names = {c.name for c in self.conditions}
        self.min_reviewer_confidence = min_reviewer_confidence

    @classmethod
    def for_loop(cls, loop, min_confidence_override=None):
        all_gates = builtin_quality_gates()
        all_conds = builtin_stop_conditions()
        gate_names = getattr(loop, "quality_gates", None) or list(all_gates)
        cond_names = getattr(loop, "stop_conditions", None) or ["reviewer_approved", "max_retries_reached"]
        min_conf = (min_confidence_override if min_confidence_override is not None
                    else getattr(loop, "min_reviewer_confidence", DEFAULT_MIN_CONFIDENCE))
        gates = [all_gates[n] for n in gate_names if n in all_gates]
        conds = [all_conds[n] for n in cond_names if n in all_conds]
        return cls(conds, gates, min_conf)

    # --- quality gates ---------------------------------------------------- #
    def _gate_eval(self, name, ctx: EvalContext):
        if name == "valid_coder_json":
            return ctx.coder_parse_ok, ("coder JSON parsed" if ctx.coder_parse_ok
                                        else "coder output is not valid JSON")
        if name == "safe_file_paths":
            ok = ctx.unsafe_path_count == 0
            return ok, ("all file paths safe" if ok
                        else f"{ctx.unsafe_path_count} unsafe file path(s) blocked")
        if name == "safe_commands_only":
            ok = ctx.unsafe_command_count == 0
            return ok, ("all commands safe" if ok
                        else f"{ctx.unsafe_command_count} unsafe command(s) blocked")
        if name == "reviewer_json_valid":
            return ctx.review_parse_ok, ("reviewer JSON parsed" if ctx.review_parse_ok
                                         else "reviewer output is not valid JSON")
        if name == "test_analyst_json_valid":
            ok = (not ctx.analyst_used) or ctx.analyst_parse_ok
            return ok, ("analyst not used" if not ctx.analyst_used
                        else ("analyst JSON parsed" if ok else "analyst output not valid JSON"))
        if name == "commands_successful":
            ok = ctx.commands_failed == 0
            return ok, ("no failed commands" if ok
                        else f"{ctx.commands_failed} command(s) failed")
        if name == "files_written":
            # Only loops whose objective expects file changes require a write.
            if not ctx.fs_enabled or ctx.review_only:
                return True, "n/a (review/design-only loop)"
            if ctx.files_changed > 0:
                return True, "files written"
            # Command/test-only loops (e.g. test_fix smoke runs) legitimately
            # change no files when they ran commands instead.
            if ctx.loop_name == "test_fix" and ctx.commands_executed > 0:
                return True, "n/a (command/test-only run)"
            return False, "no files written"
        if name == "reviewer_confidence_minimum":
            ok = ctx.review_confidence >= ctx.min_reviewer_confidence
            return ok, (f"confidence {ctx.review_confidence:.2f} >= "
                        f"{ctx.min_reviewer_confidence:.2f}" if ok
                        else f"confidence {ctx.review_confidence:.2f} < "
                             f"{ctx.min_reviewer_confidence:.2f}")
        if name == "reviewer_consistency_valid":
            # Only meaningful when the reviewer approved; a non-approval is
            # always internally consistent.
            if not ctx.review_approved:
                return True, "n/a (not approved)"
            if ctx.review_confidence < ctx.min_reviewer_confidence:
                return False, (f"approved but confidence {ctx.review_confidence:.2f} "
                               f"< {ctx.min_reviewer_confidence:.2f}")
            if ctx.review_required_changes > 0:
                return False, "approved but required_changes present"
            if ctx.review_has_severe_issue:
                return False, "approved but severe issues present"
            return True, "reviewer verdict internally consistent"
        if name == "workspace_valid":
            return ctx.workspace_valid, ("workspace valid" if ctx.workspace_valid
                                         else "workspace invalid")
        if name == "workspace_write_allowed":
            ok = ctx.workspace_write_blocked_count == 0
            return ok, ("all writes inside allowed paths" if ok
                        else f"{ctx.workspace_write_blocked_count} write(s) outside allowed paths")
        if name == "workspace_command_allowed":
            ok = ctx.workspace_command_blocked_count == 0
            return ok, ("all commands inside allowed paths" if ok
                        else f"{ctx.workspace_command_blocked_count} command(s) outside allowed paths")
        if name == "protected_paths_blocked":
            ok = ctx.protected_blocked_count == 0
            return ok, ("no protected-path writes attempted" if ok
                        else f"{ctx.protected_blocked_count} protected-path write(s) attempted")
        if name == "workspace_profile_valid":
            return ctx.workspace_profile_valid, ("workspace profile valid"
                if ctx.workspace_profile_valid else "workspace profile missing/invalid")
        if name == "approval_policy_valid":
            return ctx.approval_policy_valid, ("approval policy valid"
                if ctx.approval_policy_valid else "approval policy invalid")
        if name == "required_approval_obtained":
            # Fails only if an action proceeded without its required approval.
            # By construction declines skip the action, so this passes unless a
            # decline occurred (in which case the action was correctly skipped).
            ok = not ctx.approval_declined
            return ok, ("required approvals obtained" if ok
                        else "a required approval was declined (action skipped)")
        if name == "declined_approval_respected":
            ok = True  # declines always skip the action in this engine
            return ok, ("declined approvals respected" if not ctx.approval_declined
                        else "declined approval prevented the action")
        return True, "unknown gate (skipped)"

    def evaluate_gates(self, ctx: EvalContext) -> List[QualityGateResult]:
        results = []
        for g in self.gates:
            passed, msg = self._gate_eval(g.name, ctx)
            results.append(QualityGateResult(
                gate_name=g.name, passed=passed, required=g.required,
                severity=("error" if g.required else "warning"), message=msg))
        return results

    # --- stop conditions -------------------------------------------------- #
    def _cond_eval(self, name, ctx: EvalContext):
        if name == "reviewer_approved":
            return ctx.review_approved, "reviewer approved" if ctx.review_approved else "not approved"
        if name == "max_retries_reached":
            t = ctx.attempt >= ctx.max_attempts
            return t, f"attempt {ctx.attempt}/{ctx.max_attempts}"
        if name == "unsafe_operation_blocked":
            t = ctx.unsafe_path_count > 0 or ctx.unsafe_command_count > 0
            return t, (f"{ctx.unsafe_path_count} unsafe path(s), "
                       f"{ctx.unsafe_command_count} unsafe command(s)")
        if name == "repeated_failure":
            return ctx.repeated_failure, "same failure repeated" if ctx.repeated_failure else "no repeat"
        if name == "no_files_changed":
            t = ctx.fs_enabled and not ctx.review_only and ctx.files_changed == 0
            return t, "no files changed" if t else "files changed or n/a"
        if name == "command_timeout":
            t = ctx.command_timed_out > 0
            return t, f"{ctx.command_timed_out} command(s) timed out"
        if name == "test_passed":
            t = ctx.tests_passed is True and ctx.review_approved
            return t, "tests passed and approved" if t else "tests not passed or not approved"
        if name == "test_failed_after_retries":
            t = ctx.attempt >= ctx.max_attempts and ctx.tests_run and not ctx.tests_passed
            return t, "tests failed after max retries" if t else "n/a"
        if name == "workspace_violation_blocked":
            t = (not ctx.workspace_valid or ctx.workspace_write_blocked_count > 0
                 or ctx.protected_blocked_count > 0
                 or ctx.workspace_command_blocked_count > 0)
            return t, ("workspace safety rule violated" if t
                       else "no workspace violation")
        if name == "workspace_profile_invalid":
            t = not ctx.workspace_profile_valid
            return t, "workspace profile missing/invalid" if t else "profile valid"
        if name == "human_approval_declined":
            return ctx.approval_declined, ("human approval declined"
                if ctx.approval_declined else "no approval declined")
        if name == "needs_external_agent":
            return ctx.external_declined, ("external agent not completed"
                if ctx.external_declined else "n/a")
        if name == "external_agent_workspace_violation":
            return ctx.external_violation, ("external agent changed disallowed files"
                if ctx.external_violation else "n/a")
        if name == "external_agent_failed":
            return ctx.external_declined, ("external agent failed/declined"
                if ctx.external_declined else "n/a")
        if name == "external_completion_missing":
            return False, "n/a"  # handled by the import command directly
        if name == "external_completion_failed":
            return ctx.external_completion_failed, ("completion status failed/blocked"
                if ctx.external_completion_failed else "n/a")
        if name == "external_completion_workspace_mismatch":
            return ctx.external_completion_mismatch, ("claimed changes conflict with workspace"
                if ctx.external_completion_mismatch else "n/a")
        return False, "unknown condition"

    def evaluate_conditions(self, ctx: EvalContext) -> List[StopConditionResult]:
        results = []
        for c in self.conditions:
            triggered, msg = self._cond_eval(c.name, ctx)
            results.append(StopConditionResult(
                condition_name=c.name, triggered=triggered,
                severity=c.severity, message=msg))
        return results

    # --- decision --------------------------------------------------------- #
    def decide(self, ctx, gate_results, cond_results) -> StopDecision:
        triggered = {c.condition_name for c in cond_results if c.triggered}
        required_failed = [g for g in gate_results if g.required and not g.passed]
        n_req = len(required_failed)
        cmds_ok = ctx.commands_failed == 0
        is_test_loop = "test_passed" in self.condition_names
        is_last = ctx.attempt >= ctx.max_attempts

        if is_test_loop:
            success = "test_passed" in triggered
        else:
            success = ("reviewer_approved" in triggered) and cmds_ok
        final_ok = success and not required_failed

        # External agent outcomes are terminal.
        if "external_completion_workspace_mismatch" in triggered:
            return StopDecision(True, "BLOCKED", "external_completion_workspace_mismatch",
                                "critical", "external_completion_workspace_mismatch", n_req, False)
        if "external_agent_workspace_violation" in triggered:
            return StopDecision(True, "BLOCKED", "external_agent_workspace_violation",
                                "critical", "external_agent_workspace_violation", n_req, False)
        if "external_completion_failed" in triggered:
            return StopDecision(True, "BLOCKED", "external_completion_failed",
                                "high", "external_completion_failed", n_req, False)
        if "needs_external_agent" in triggered:
            return StopDecision(True, "PAUSED_EXTERNAL_AGENT", "needs_external_agent",
                                "high", "needs_external_agent", n_req, False)
        # Workspace and unsafe-op violations are always terminal.
        if "workspace_profile_invalid" in triggered:
            return StopDecision(True, "BLOCKED", "workspace_profile_invalid",
                                "critical", "workspace_profile_invalid", n_req, False)
        if "workspace_violation_blocked" in triggered:
            return StopDecision(True, "BLOCKED", "workspace_violation_blocked",
                                "critical", "workspace_violation_blocked", n_req, False)
        if "unsafe_operation_blocked" in triggered:
            return StopDecision(True, "BLOCKED", "unsafe_operation_blocked",
                                "critical", "unsafe_operation_blocked", n_req, False)
        if "human_approval_declined" in triggered:
            status = "BLOCKED" if ctx.approval_declined_action_risk == "critical" else "NEEDS_HUMAN"
            return StopDecision(True, status, "human_approval_declined",
                                "high", "human_approval_declined", n_req, False)
        # A reviewer that approved but is internally contradictory can never be
        # APPROVED — surface it explicitly instead of a misleading success.
        consistency_failed = any(
            not g.passed for g in gate_results
            if g.gate_name == "reviewer_consistency_valid")
        if consistency_failed and ctx.review_approved:
            return StopDecision(True, "REVIEW_INCONSISTENT", "reviewer_consistency_valid",
                                "error", "reviewer_consistency_valid", n_req, False)
        if final_ok:
            cond = "test_passed" if is_test_loop else "reviewer_approved"
            return StopDecision(True, "APPROVED", cond, "info", cond, n_req, True)
        if "repeated_failure" in triggered:
            return StopDecision(True, "REJECTED", "repeated_failure", "warning",
                                "repeated_failure", n_req, False)
        if is_last:
            if is_test_loop and "test_failed_after_retries" in triggered:
                return StopDecision(True, "REJECTED", "test_failed_after_retries",
                                    "error", "test_failed_after_retries", n_req, False)
            return StopDecision(True, "REJECTED", "max_retries_reached", "warning",
                                "max_retries_reached", n_req, False)
        return StopDecision(False, None, None, None, None, n_req, False)
