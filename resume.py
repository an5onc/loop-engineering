"""External Agent Auto-Resume (Stage 3.2).

Resumes a paused external-agent loop: imports the external completion (file/text
or an already-stored one), re-inspects the workspace, runs the Reviewer with the
completion context, updates loop status, regenerates the report, and optionally
commits. Resume NEVER bypasses framework safety — it re-checks the real
workspace, the quality gates, the stop conditions, approvals, and the Reviewer.
"""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Optional

import agent_registry
import approval_gates
import database
import external_agents
import filesystem
import git_tools
import loop_engine
import loop_registry
import ollama_client
import project_workspace
import prompts
import reports
import stop_conditions

PAUSED_STATES = {"PAUSED_EXTERNAL_AGENT", "NEEDS_EXTERNAL_AGENT"}
_REGISTRY = loop_registry.LoopRegistry()
_AGENTS = agent_registry.AgentRegistry()


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


@dataclass
class ResumeRequest:
    loop_id: int
    completion_file: Optional[str] = None
    completion_text: Optional[str] = None
    require_approval: bool = False
    approval_mode: Optional[str] = None
    commit: bool = False
    commit_message: Optional[str] = None
    created_at: str = field(default_factory=_now)


@dataclass
class ResumeResult:
    loop_id: int
    resumed: bool
    status: str
    stop_reason: str
    report_path: Optional[str] = None
    created_at: str = field(default_factory=_now)


def _generate_report(conn, loop_id):
    try:
        gen = reports.ReportGenerator(conn)
        content = gen.generate_markdown_report(loop_id)
        path = gen.save_report(loop_id, content)
        database.save_run_report(conn, loop_id, path, "markdown",
                                 hashlib.sha256(content.encode("utf-8")).hexdigest(),
                                 len(content.encode("utf-8")))
        return path
    except Exception:
        return None


class ResumeEngine:
    def resume(self, conn, request: ResumeRequest, resume_type="resume",
               on_event=None) -> ResumeResult:
        rec = database.LoopRecorder(conn, request.loop_id)
        loop = database.get_loop(conn, request.loop_id)
        status_before = loop["status"] if loop else None

        def emit(msg):
            if on_event:
                on_event(msg)

        def finalize(status_after, stop_reason, report_path=None,
                     completion_imported=False, commit_requested=False,
                     commit_created=False, resumed=False):
            database.save_resume_event(
                conn, request.loop_id, resume_type, completion_imported,
                status_before, status_after, stop_reason, report_path,
                commit_requested, commit_created,
                json.dumps({"resumed": resumed}))
            rec.save_metric("resume_used", 1, "bool")
            rec.save_metric("resume_completion_imported",
                            1 if completion_imported else 0, "bool")
            rec.save_metric("resume_status_before", None, "string",
                            metric_text=status_before)
            rec.save_metric("resume_status_after", None, "string",
                            metric_text=status_after)
            rec.save_metric("resume_commit_requested",
                            1 if commit_requested else 0, "bool")
            rec.save_metric("resume_commit_created",
                            1 if commit_created else 0, "bool")
            return ResumeResult(loop_id=request.loop_id, resumed=resumed,
                                status=status_after, stop_reason=stop_reason,
                                report_path=report_path)

        # 1) Loop must exist and be resumable.
        ext_events = database.get_external_agent_events(conn, request.loop_id) if loop else []
        resumable = bool(loop) and (status_before in PAUSED_STATES or len(ext_events) > 0)
        rec.save_quality_gate_result(
            0, "resume_loop_valid", resumable, True,
            "info" if resumable else "error",
            "loop resumable" if resumable else "loop not resumable")
        if not resumable:
            rec.save_stop_condition_result(0, "resume_invalid_loop_state", True,
                                           "high", "loop cannot be resumed")
            return finalize(status_before or "UNKNOWN", "resume_invalid_loop_state")

        # 2) Completion must be available (new or already stored).
        completion = None
        try:
            if request.completion_file:
                completion = external_agents.load_completion_file(request.completion_file)
            elif request.completion_text:
                completion = external_agents.parse_completion_summary(request.completion_text)
        except ValueError as exc:
            rec.save_quality_gate_result(0, "resume_completion_available", False,
                                         True, "error", str(exc))
            rec.save_stop_condition_result(0, "resume_missing_completion", True,
                                           "high", str(exc))
            return finalize(status_before, "resume_missing_completion")

        existing = database.get_external_agent_completion(conn, request.loop_id)
        have = completion is not None or existing is not None
        rec.save_quality_gate_result(
            0, "resume_completion_available", have, True,
            "info" if have else "error",
            "completion available" if have else "no completion provided")
        if not have:
            rec.save_stop_condition_result(0, "resume_missing_completion", True,
                                           "high", "no completion provided")
            return finalize(status_before, "resume_missing_completion")

        newly_imported = completion is not None
        if completion is None and existing is not None:
            cj = json.loads(existing["completion_json"] or "{}")
            completion = external_agents.ExternalAgentCompletion(
                agent_name=cj.get("agent_name", ""),
                status=existing["completion_status"] or "completed",
                summary=cj.get("summary", ""), files_changed=cj.get("files_changed", []),
                commands_run=cj.get("commands_run", []), tests_run=cj.get("tests_run", []),
                tests_passed=cj.get("tests_passed"), issues=cj.get("issues", []),
                notes=cj.get("notes", []), next_steps=cj.get("next_steps", []),
                parsed=bool(existing["completion_parsed"]))

        # 3) Workspace must be valid; re-inspect.
        ws = project_workspace.WorkspaceManager(conn).get_workspace(loop["workspace_name"])
        if ws is None or project_workspace.WorkspaceManager().validate_workspace(ws):
            rec.save_stop_condition_result(0, "resume_workspace_violation", True,
                                           "critical", "workspace invalid/missing")
            rec.save_quality_gate_result(0, "resume_review_completed", False, True,
                                         "error", "blocked before review")
            database.finish_loop(conn, request.loop_id, "BLOCKED",
                                 "resume_workspace_violation",
                                 loop["retry_count"] or 0,
                                 loop["total_duration_seconds"] or 0.0)
            rp = _generate_report(conn, request.loop_id)
            return finalize("BLOCKED", "resume_workspace_violation", rp,
                            completion_imported=newly_imported, resumed=True)

        loop_def = (_REGISTRY.get_loop(loop["loop_type"])
                    or _REGISTRY.get_loop(loop_registry.DEFAULT_LOOP))
        roles, _e = loop_engine.resolve_roles(loop_def, _AGENTS, {})
        # Compare against the handoff snapshot so only the external agent's
        # deltas count. Stale pre-existing artifacts (e.g. __pycache__) are
        # ignored; sensitive paths (.env/.git/keys/...) still block.
        snapshot_json = database.get_external_agent_snapshot(conn, request.loop_id)
        deltas = external_agents.compute_external_deltas(snapshot_json, ws)
        changed = deltas["changed"]
        violations = deltas["violations"]
        inspection = {"allowed_changed": list(changed),
                      "disallowed_changed": list(violations)}
        emit(f"workspace deltas: {len(changed)} changed, {len(violations)} "
             f"disallowed/protected, {len(deltas['ignored'])} ignored (generated)")
        ext_violation = bool(violations)
        ext_failed = completion.status in ("failed", "blocked")
        ext_mismatch = any(
            project_workspace.is_sensitive_protected_path(str(c)) or ".." in str(c).split("/")
            or os.path.isabs(str(c)) for c in completion.files_changed)
        if violations:
            rec.save_stop_condition_result(0, "resume_workspace_violation", True,
                                           "critical", "disallowed/protected change")

        if newly_imported:
            database.save_external_agent_completion(conn, request.loop_id, completion)
        self._save_completion_metrics(rec, completion, newly_imported)

        # 4) Reviewer (unless blocked by a safety violation).
        review = None
        if not (ext_failed or ext_violation or ext_mismatch):
            rendered = "\n\n".join(
                f"### {p}\n```\n{filesystem.read_file(p, workspace=ws) if p not in violations else ''}\n```"
                for p in changed) or "(no files)"
            ext_ctx = external_agents.format_completion_context(completion, inspection)
            plan = next((s["response"] for s in database.get_steps(conn, request.loop_id)
                         if s["step_name"] == "supervisor_plan"), "")
            rev = roles["reviewer"]
            rprompt = prompts.review_prompt(loop["task"], plan, rendered, loop_def,
                                            "", "", ext_ctx)
            rres = ollama_client.generate(rev.model, rprompt, system=rev.system_prompt,
                                          temperature=rev.temperature)
            rec.save_step("reviewer_review", "reviewer", rev.model, 0, rprompt,
                          rres.text, rres.latency_s, rres.prompt_tokens,
                          rres.output_tokens, rres.tokens_per_sec)
            review = loop_engine._parse_review(rres.text)
            rec.save_review(0, review)
            emit(f"reviewer approved={review.approved} confidence={review.confidence_score}")

        reviewed = review is not None
        rec.save_quality_gate_result(0, "resume_review_completed", reviewed, True,
                                     "info" if reviewed else "error",
                                     "reviewer ran" if reviewed else "review skipped (safety)")
        rec.save_quality_gate_result(0, "external_completion_reviewed", reviewed, True,
                                     "info" if reviewed else "error",
                                     "completion reviewed" if reviewed else "review skipped")
        rec.save_quality_gate_result(0, "external_completion_valid", True, True,
                                     "info", "completion parsed/stored")
        rec.save_quality_gate_result(0, "external_completion_matches_workspace",
                                     not ext_mismatch, False,
                                     "info" if not ext_mismatch else "warning",
                                     "claimed changes consistent" if not ext_mismatch
                                     else "claimed changes conflict")

        # 5) Decide via the stop-condition engine.
        sc_engine = stop_conditions.StopConditionEngine.for_loop(loop_def)
        ctx = stop_conditions.EvalContext(
            attempt=1, max_attempts=1, loop_name=loop_def.name, fs_enabled=True,
            term_enabled=False, review_only=False, coder_parse_ok=True,
            proposed_file_count=len(changed),
            files_changed=len(inspection["allowed_changed"]),
            unsafe_path_count=0, unsafe_command_count=0, commands_executed=0,
            commands_failed=0, command_timed_out=0,
            review_parse_ok=(review.parse_ok if review else True),
            review_approved=(review.approved if review else False),
            review_confidence=(review.confidence_score if review else 0.0),
            min_reviewer_confidence=sc_engine.min_reviewer_confidence,
            analyst_used=False, analyst_parse_ok=True, tests_run=False,
            tests_passed=None, repeated_failure=False,
            external_violation=ext_violation, external_completion_failed=ext_failed,
            external_completion_mismatch=ext_mismatch)
        gate_results = sc_engine.evaluate_gates(ctx)
        cond_results = sc_engine.evaluate_conditions(ctx)
        decision = sc_engine.decide(ctx, gate_results, cond_results)
        for g in gate_results:
            rec.save_quality_gate_result(0, g.gate_name, g.passed, g.required,
                                         g.severity, g.message)
        for c in cond_results:
            rec.save_stop_condition_result(0, c.condition_name, c.triggered,
                                           c.severity, c.message)
        final = decision.final_status or ("APPROVED" if (review and review.approved) else "REJECTED")

        # 6) Optional commit — only when APPROVED and --commit (approval-gated).
        commit_created = False
        if final == "APPROVED" and request.commit and ws.allow_git:
            do_commit = True
            if request.require_approval:
                eng = approval_gates.ApprovalGateEngine(
                    approval_gates.ApprovalPolicy(name="resume", enabled=True),
                    mode=request.approval_mode or "interactive")
                areq = approval_gates.ApprovalRequest(
                    request.loop_id, 0, "git_commit_gate", "git_commit", "high",
                    "commit on resume")
                adec = eng.evaluate(areq)
                rec.save_approval_event(areq, adec)
                do_commit = adec.approved
            if do_commit and git_tools.is_git_repo(ws.root_path):
                add = git_tools.git_add_workspace(ws.root_path, ws)
                rec.save_git_event("add", add.command, add.exit_code, add.stdout, add.stderr)
                msg = request.commit_message or f"Loop #{request.loop_id}: resume"
                cr = git_tools.git_commit(ws.root_path, msg)
                rec.save_git_event("commit", cr.command, cr.exit_code, cr.stdout, cr.stderr)
                commit_created = cr.ok

        database.finish_loop(conn, request.loop_id, final,
                             decision.stop_reason or "resumed",
                             loop["retry_count"] or 0,
                             loop["total_duration_seconds"] or 0.0)
        rp = _generate_report(conn, request.loop_id)
        return finalize(final, decision.stop_reason or "resumed", rp,
                        completion_imported=newly_imported,
                        commit_requested=request.commit,
                        commit_created=commit_created, resumed=True)

    @staticmethod
    def _save_completion_metrics(rec, completion, newly_imported):
        rec.save_metric("external_completion_imported", 1 if newly_imported else 0, "bool")
        rec.save_metric("external_completion_parsed",
                        1 if completion.parsed else 0, "bool")
        if completion.tests_passed is not None:
            rec.save_metric("external_completion_tests_passed",
                            1 if completion.tests_passed else 0, "bool")
        rec.save_metric("external_completion_file_count",
                        len(completion.files_changed), "count")
        rec.save_metric("external_completion_command_count",
                        len(completion.commands_run), "count")
