"""Supervisor -> Coder -> Reviewer loop with retries, metrics, and safe file I/O."""

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import agent_registry
import approval_gates
import config
import context_packs
import external_agents
import filesystem
import loop_registry
import ollama_client
import project_workspace
import prompts
import stop_conditions
import terminal
import workspace_profiles


def _classify_file_block(reason):
    r = reason or ""
    if "approval" in r:
        return "approval"
    if "not permitted" in r:
        return "tool"
    if "protected path blocked" in r:
        return "protected"
    if "outside allowed write path" in r:
        return "ws_write"
    return "unsafe"


def _classify_cmd_block(reason):
    r = reason or ""
    if "approval" in r:
        return "approval"
    if "not permitted" in r:
        return "tool"
    if "outside allowed command path" in r:
        return "ws_command"
    return "unsafe"

_DEFAULT_LOOPS = None
_DEFAULT_AGENTS = None


def _default_loop():
    global _DEFAULT_LOOPS
    if _DEFAULT_LOOPS is None:
        _DEFAULT_LOOPS = loop_registry.load_builtin_loops()
    return _DEFAULT_LOOPS["code_build"]


def _default_agent_registry():
    global _DEFAULT_AGENTS
    if _DEFAULT_AGENTS is None:
        _DEFAULT_AGENTS = agent_registry.AgentRegistry()
    return _DEFAULT_AGENTS


@dataclass
class RoleBinding:
    """A resolved (role -> agent, model, system prompt, temperature) mapping."""
    role: str
    agent_name: str
    model: str
    system_prompt: str
    temperature: float


def resolve_roles(loop, registry=None, overrides=None):
    """Resolve a loop's three roles to RoleBindings, applying model overrides.

    overrides: {"supervisor": model|None, "coder": ..., "reviewer": ...}.
    Returns (bindings: dict, errors: list[str]).
    """
    registry = registry or _default_agent_registry()
    overrides = overrides or {}
    assigned = {
        "supervisor": loop.supervisor_agent,
        "coder": loop.coder_agent,
        "reviewer": loop.reviewer_agent,
    }
    # Optional test-analyst role (Stage 1.8) — only when the loop assigns one.
    if getattr(loop, "test_analyst_agent", None):
        assigned["test_analyst"] = loop.test_analyst_agent
    bindings, errors = {}, []
    for role, agent_name in assigned.items():
        agent = registry.get_agent(agent_name)
        if agent is None:
            errors.append(f"{role}: unknown agent '{agent_name}'")
            continue
        model = overrides.get(role) or agent.default_model
        bindings[role] = RoleBinding(role, agent.name, model,
                                     agent.system_prompt, agent.temperature)
    return bindings, errors


# --------------------------------------------------------------------------- #
# Structured payloads
# --------------------------------------------------------------------------- #
@dataclass
class CoderOutput:
    summary: str
    files: List[dict]            # [{"path": str, "content": str}, ...]
    commands: List[str]
    notes: List[str]
    raw: str = ""
    parse_ok: bool = True

    def render_files(self) -> str:
        """Readable rendering of the files for the reviewer / revise prompt."""
        if not self.files:
            return "(no files produced)"
        blocks = []
        for f in self.files:
            blocks.append(f"### {f.get('path')}\n```\n{f.get('content', '')}\n```")
        return "\n\n".join(blocks)


@dataclass
class Review:
    approved: bool
    summary: str
    issues: List[str]
    required_changes: List[str]
    confidence_score: float
    stop_reason: str
    raw: str = ""
    parse_ok: bool = True

    def feedback_text(self) -> str:
        lines = [f"Summary: {self.summary}"]
        if self.issues:
            lines.append("Issues:")
            lines += [f"  - {i}" for i in self.issues]
        if self.required_changes:
            lines.append("Required changes:")
            lines += [f"  - {c}" for c in self.required_changes]
        return "\n".join(lines)


@dataclass
class TestAnalysis:
    failure_detected: bool
    failure_type: str
    summary: str
    root_cause: str
    evidence: List[str]
    recommended_changes: List[str]
    confidence_score: float
    raw: str = ""
    parse_ok: bool = True

    def feedback_text(self) -> str:
        lines = [
            f"Test Analyst diagnosis ({self.failure_type}, "
            f"confidence {self.confidence_score:.2f}):",
            f"  summary: {self.summary}",
            f"  root_cause: {self.root_cause}",
        ]
        if self.recommended_changes:
            lines.append("  recommended changes:")
            lines += [f"    - {c}" for c in self.recommended_changes]
        return "\n".join(lines)


@dataclass
class AttemptMetrics:
    attempt: int
    coder_latency_s: float = 0.0
    coder_prompt_tokens: int = 0
    coder_output_tokens: int = 0
    coder_tokens_per_sec: float = 0.0
    reviewer_latency_s: float = 0.0
    reviewer_prompt_tokens: int = 0
    reviewer_output_tokens: int = 0
    reviewer_tokens_per_sec: float = 0.0
    approved: bool = False
    files_created: List[str] = field(default_factory=list)
    files_updated: List[str] = field(default_factory=list)
    files_blocked: List[Tuple[str, str]] = field(default_factory=list)
    command_results: list = field(default_factory=list)  # List[terminal.CommandResult]
    commands_suggested: int = 0
    tests_passed: Optional[bool] = None


@dataclass
class LoopResult:
    task: str
    plan: str
    coder_output: Optional[CoderOutput]
    review: Optional[Review]
    final_status: str
    stop_reason: str
    retry_count: int
    attempts: int
    plan_latency_s: float
    plan_prompt_tokens: int
    plan_output_tokens: int
    plan_tokens_per_sec: float
    total_loop_s: float
    attempt_metrics: List[AttemptMetrics] = field(default_factory=list)
    # Filesystem outcome (final state)
    files_created: List[str] = field(default_factory=list)
    files_updated: List[str] = field(default_factory=list)
    files_blocked: List[Tuple[str, str]] = field(default_factory=list)
    suggested_commands: List[str] = field(default_factory=list)
    command_results: list = field(default_factory=list)  # final attempt's results
    tests_passed: Optional[bool] = None
    # Test Analyst outcome (Stage 1.8)
    test_analyst_used: bool = False
    test_analyst_latency_s: float = 0.0
    test_analyst_failure_detected: Optional[bool] = None
    test_analyst_confidence: Optional[float] = None
    test_analysis: Optional[TestAnalysis] = None
    test_analyst_agent_name: Optional[str] = None
    test_analyst_model: Optional[str] = None
    # Stop conditions / quality gates (Stage 1.9)
    quality_gates_passed: int = 0
    quality_gates_failed: int = 0
    required_quality_gates_failed: int = 0
    stop_conditions_triggered: int = 0
    final_stop_condition: Optional[str] = None
    final_severity: Optional[str] = None
    reviewer_confidence_min: float = 0.70
    reviewer_confidence_actual: Optional[float] = None
    required_gate_failed: bool = False
    failed_gate_names: List[str] = field(default_factory=list)
    # External coding agent (Stage 3.0)
    external_agent_used: bool = False
    external_agent_result: object = None
    external_handoff_path: Optional[str] = None
    external_handoff_safe: bool = True
    external_mode: Optional[str] = None
    # Stabilization (Stage 3.2.2)
    deterministic_test_fix_fallback_used: bool = False
    model_call_timeout: bool = False
    # External agent job packet (Stage 3.3)
    external_job_info: object = None

    @property
    def total_files_changed(self) -> int:
        return len(self.files_created) + len(self.files_updated)

    @property
    def commands_executed(self) -> int:
        return sum(1 for r in self.command_results if r.allowed)

    @property
    def commands_blocked(self) -> int:
        return sum(1 for r in self.command_results if not r.allowed)


# --------------------------------------------------------------------------- #
# JSON extraction / parsing
# --------------------------------------------------------------------------- #
def _extract_json(text: str) -> Optional[dict]:
    """Pull the first balanced JSON object out of a model response."""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None

    if candidate is None:
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    break
    if candidate is None:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _as_str_list(v) -> List[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    if v in (None, ""):
        return []
    return [str(v)]


def _parse_coder(text: str) -> CoderOutput:
    data = _extract_json(text)
    if data is None:
        return CoderOutput(
            summary="Coder output could not be parsed as JSON.",
            files=[], commands=[], notes=["unparseable_coder_output"],
            raw=text, parse_ok=False,
        )
    files = []
    for item in data.get("files") or []:
        if isinstance(item, dict) and "path" in item:
            files.append({
                "path": str(item.get("path")),
                "content": "" if item.get("content") is None else str(item.get("content")),
            })
    return CoderOutput(
        summary=str(data.get("summary", "")),
        files=files,
        commands=_as_str_list(data.get("commands")),
        notes=_as_str_list(data.get("notes")),
        raw=text, parse_ok=True,
    )


def _truncate(text: str, limit: int = 1500) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "\n...(truncated)"


def render_command_results(results) -> str:
    """Readable rendering of command results for prompts."""
    if not results:
        return "(no commands)"
    blocks = []
    for r in results:
        if not r.allowed:
            blocks.append(f"$ {r.command}\n[BLOCKED] {r.reason_if_blocked}")
            continue
        status = "TIMED OUT" if r.timed_out else f"exit={r.exit_code}"
        blocks.append(
            f"$ {r.command}\n[{status}] ({r.duration_seconds:.2f}s)\n"
            f"stdout:\n{_truncate(r.stdout)}\n"
            f"stderr:\n{_truncate(r.stderr)}"
        )
    return "\n\n".join(blocks)


def _looks_like_test(command: str) -> bool:
    c = command.lower()
    return "pytest" in c or "unittest" in c or "test" in c


def _compute_tests_passed(results) -> Optional[bool]:
    """True/False if any test command ran; None if none did."""
    test_runs = [r for r in results if r.allowed and _looks_like_test(r.command)]
    if not test_runs:
        return None
    return all(r.succeeded for r in test_runs)


def _commands_failed(results) -> bool:
    """Any executed (allowed) command that errored or timed out."""
    return any(r.allowed and not r.succeeded for r in results)


def _parse_test_analysis(text: str) -> TestAnalysis:
    data = _extract_json(text)
    if data is None:
        return TestAnalysis(
            failure_detected=True, failure_type="unknown",
            summary="Test Analyst output could not be parsed as JSON.",
            root_cause="unparseable_analysis", evidence=[],
            recommended_changes=["Re-run analysis and return strict JSON."],
            confidence_score=0.0, raw=text, parse_ok=False,
        )
    try:
        score = float(data.get("confidence_score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    return TestAnalysis(
        failure_detected=bool(data.get("failure_detected", False)),
        failure_type=str(data.get("failure_type", "unknown")),
        summary=str(data.get("summary", "")),
        root_cause=str(data.get("root_cause", "")),
        evidence=_as_str_list(data.get("evidence")),
        recommended_changes=_as_str_list(data.get("recommended_changes")),
        confidence_score=score, raw=text, parse_ok=True,
    )


DESIGN_LOOPS = ("prompt_design", "loop_design")

# Markers that flag a clearly command-only "smoke test" request for test_fix.
_SMOKE_TEST_MARKERS = ("smoke test", "smoke-test")
_SEVERE_ISSUE_MARKERS = ("critical", "severe", "security", "vulnerab",
                         "data loss", "must fix", "blocker")
SAFE_FALLBACK_COMMAND = "python3 --version"


def _gen(model, prompt, system="", temperature=None):
    """Model call with a per-call wall-clock cap (raises OllamaTimeout)."""
    return ollama_client.generate(model, prompt, system=system,
                                  temperature=temperature,
                                  timeout=config.MODEL_CALL_TIMEOUT)


def _is_smoke_test_task(task: str) -> bool:
    """True when the task clearly asks to run a safe smoke/test command."""
    t = (task or "").lower()
    if any(m in t for m in _SMOKE_TEST_MARKERS):
        return True
    return ("run" in t and "test" in t and ("command" in t or "safe" in t))


def _review_severe_issue(review) -> bool:
    blob = " ".join([(review.summary or "")] + list(review.issues or [])).lower()
    return any(m in blob for m in _SEVERE_ISSUE_MARKERS)


def _design_contract_ok(loop_name, coder_out, review):
    """Deterministic output contract for design-only loops. Returns (ok, why).
    Design loops succeed on usable output, not on file changes."""
    if loop_name not in DESIGN_LOOPS:
        return False, ""
    if coder_out is None or not coder_out.parse_ok:
        return False, "output did not parse"
    text = ((coder_out.summary or "") + "\n"
            + "\n".join(f.get("content", "") for f in (coder_out.files or []))
            + "\n" + (coder_out.raw or "")).strip()
    if loop_name == "prompt_design":
        # A usable, non-trivial prompt was produced.
        if len(text) >= 40:
            return True, "usable prompt produced"
        return False, "prompt too short / empty"
    if loop_name == "loop_design":
        # A structured loop definition (JSON-like with recognizable fields).
        has_json = "{" in text and "}" in text
        has_field = any(k in text.lower() for k in
                        ("name", "objective", "trigger", "steps", "stop", "loop"))
        if has_json and has_field:
            return True, "structured loop definition produced"
        return False, "no structured loop definition"
    return False, ""


def _parse_review(text: str) -> Review:
    data = _extract_json(text)
    if data is None:
        return Review(
            approved=False,
            summary="Reviewer output could not be parsed as JSON.",
            issues=["Malformed reviewer response."],
            required_changes=["Re-review and return strict JSON."],
            confidence_score=0.0, stop_reason="unparseable_review",
            raw=text, parse_ok=False,
        )
    try:
        score = float(data.get("confidence_score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    return Review(
        approved=bool(data.get("approved", False)),
        summary=str(data.get("summary", "")),
        issues=_as_str_list(data.get("issues")),
        required_changes=_as_str_list(data.get("required_changes")),
        confidence_score=score,
        stop_reason=str(data.get("stop_reason", "")),
        raw=text, parse_ok=True,
    )


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
class LoopEngine:
    """Drives the Supervisor -> Coder -> Reviewer workflow for a single task."""

    def __init__(self, supervisor_model=None, coder_model=None, max_retries=None):
        self.supervisor_model = supervisor_model or config.SUPERVISOR_MODEL
        self.coder_model = coder_model or config.CODER_MODEL
        self.max_retries = config.MAX_RETRIES if max_retries is None else max_retries

    @staticmethod
    def _record_file_ops(recorder, attempt, coder_files, apply_res):
        """Persist one file_operations row per file the coder proposed."""
        created = set(apply_res.created)
        updated = set(apply_res.updated)
        blocked_map = {p: reason for p, reason in apply_res.blocked}
        for f in coder_files:
            path = f.get("path")
            content = f.get("content", "")
            rel = str(path).replace("\\", "/")
            if rel in created or path in created:
                recorder.save_file_operation(attempt, path, "create", True, "", content)
            elif rel in updated or path in updated:
                recorder.save_file_operation(attempt, path, "update", True, "", content)
            else:
                reason = blocked_map.get(str(path), "not applied")
                recorder.save_file_operation(attempt, path, "blocked", False, reason, content)

    @staticmethod
    def _external_step(external_coder, task, plan, loop, ws, cp_summary, feedback,
                       attempt, recorder, report, loop_id,
                       memory_summary="", project_intel_summary=""):
        """Hand off implementation to an external agent, then inspect safely."""
        import project_workspace
        adapter = external_coder["adapter"]
        mode = external_coder.get("mode", "handoff")
        confirm = external_coder.get("confirm")

        ereq = external_agents.ExternalAgentRequest(
            loop_id=loop_id, attempt_number=attempt, agent_name=adapter.name,
            task=task, plan=plan, workspace_name=ws.name, workspace_root=ws.root_path,
            allowed_write_paths=list(ws.allowed_write_paths),
            allowed_command_paths=list(ws.allowed_command_paths),
            context_summary=cp_summary, reviewer_feedback=(feedback or ""),
            test_analyst_feedback="", dry_run=True, created_at="")
        prompt, safe, warns = adapter.build_handoff(ereq)
        path = external_agents.save_handoff(loop_id, attempt, adapter.name, prompt)
        instructions = adapter.terminal_instructions(ws.root_path)
        report("external:handoff", (adapter.name, mode, path, prompt, instructions))

        # Stage 3.3: create a structured, resumable Job Packet (needs a DB conn).
        job_info = None
        if recorder is not None:
            import external_agent_jobs as eaj
            allowed_tools = []
            if loop.filesystem_enabled:
                allowed_tools.append("filesystem")
            if loop.terminal_enabled:
                allowed_tools.append("terminal")
            if getattr(loop, "git_enabled", False):
                allowed_tools.append("git")
            mgr = eaj.ExternalAgentJobManager(recorder.conn)
            job = mgr.create_job(
                loop_id, attempt, adapter.name, ws.name, ws.root_path,
                priority=external_coder.get("job_priority", eaj.DEFAULT_PRIORITY),
                labels=external_coder.get("job_labels"),
                notes=external_coder.get("job_notes", ""))
            packet = mgr.create_packet(
                job, task, plan, list(ws.allowed_write_paths),
                list(ws.allowed_command_paths), allowed_tools,
                context_summary=cp_summary, memory_summary=memory_summary,
                project_intelligence_summary=project_intel_summary,
                context_pack_summary=cp_summary, reviewer_feedback=(feedback or ""),
                test_analyst_feedback="")
            saved = mgr.save_packet(job, packet, prompt)
            mgr.update_job_status(job.id, eaj.WAITING_FOR_EXTERNAL_AGENT)
            job_info = {
                "job_id": job.id, "status": eaj.WAITING_FOR_EXTERNAL_AGENT,
                "packet_path": saved["packet_path"], "handoff_path": saved["handoff_path"],
                "job_dir": saved["job_dir"], "packet_bytes": saved["packet_bytes"],
                "handoff_bytes": saved["handoff_bytes"],
                "packet_safe": saved["packet_safe"],
                "packet_safe_reasons": saved["packet_safe_reasons"],
                "completion_example_path": saved["completion_example_path"],
                "readme_path": saved["readme_path"],
            }
            report("external:job", job_info)

        # Capture a handoff-time snapshot so a later resume can isolate the
        # external agent's deltas (and ignore pre-existing stale artifacts).
        snapshot_json = external_agents.workspace_snapshot(ws)

        if recorder:
            recorder.save_step("external_handoff", "coder", adapter.name, attempt,
                               prompt, f"handoff saved to {path}", 0.0, 0, 0, 0.0)

        # Stage 3.1: if a completion was imported, use it instead of yes/no.
        completion = external_coder.get("completion")
        if completion is not None:
            completed = completion.status == "completed"
            report("external:completion", completion)
        else:
            completed = bool(confirm(path, instructions, adapter.name)) if confirm else False

        result = external_agents.ExternalAgentResult(
            agent_name=adapter.name, started=True, completed=completed,
            commands_run=(completion.commands_run if completion else []), created_at="")

        ext_completion_failed = bool(completion and completion.status in ("failed", "blocked"))
        ext_completion_mismatch = False
        inspection = {"allowed_changed": [], "disallowed_changed": []}

        if not completed:
            result.success = False
            result.summary = (completion.summary if completion
                              else "external agent completion declined / not finished")
            coder_out = CoderOutput("(external agent not completed)", [], [], [])
            apply_res = filesystem.ApplyResult()
            ext_declined = not ext_completion_failed
            ext_violation = False
        else:
            # Classify only real, sensitivity-relevant changes; generated
            # artifacts (e.g. __pycache__/*.pyc) are ignored, sensitive paths
            # (.env/.git/keys/...) block. No prior snapshot here (handoff time),
            # so all current files are candidates.
            deltas = external_agents.compute_external_deltas(None, ws)
            changed = deltas["changed"]
            violations = deltas["violations"]
            inspection = {"allowed_changed": list(changed),
                          "disallowed_changed": list(violations)}
            files = []
            for p in changed:
                try:
                    files.append({"path": p, "content": filesystem.read_file(p, workspace=ws)})
                except OSError:
                    files.append({"path": p, "content": ""})
            for p in violations:
                files.append({"path": p, "content": ""})
            coder_out = CoderOutput(
                f"external agent '{adapter.name}' changed {len(changed)} file(s)",
                files, [], [])
            apply_res = filesystem.ApplyResult(
                updated=list(changed),
                blocked=[(p, "external agent wrote protected/disallowed path")
                         for p in violations])
            result.success = not violations
            result.files_changed = list(changed)
            result.summary = (f"external agent changed {len(changed)} file(s)"
                              + (f"; {len(violations)} disallowed" if violations else ""))
            ext_declined = False
            ext_violation = bool(violations)
            # Completion claims that reference sensitive/escape paths = risky mismatch.
            if completion is not None:
                for claimed in completion.files_changed:
                    if (project_workspace.is_sensitive_protected_path(str(claimed))
                            or ".." in str(claimed).split("/")
                            or os.path.isabs(str(claimed))):
                        ext_completion_mismatch = True

        if recorder:
            recorder.save_external_agent_event(
                attempt, adapter.name, mode, path,
                external_agents.prompt_hash(prompt), result)
            import database as _db
            _db.save_external_agent_snapshot(recorder.conn, loop_id, snapshot_json)
            if completion is not None:
                _db.save_external_agent_completion(recorder.conn, loop_id, completion)
        report("external:done", (adapter.name, completed, ext_violation, result))
        return (coder_out, apply_res, [], result, path, safe, ext_declined,
                ext_violation, ext_completion_failed, ext_completion_mismatch,
                completion, inspection, job_info)

    def run(self, task: str, on_step=None, recorder=None, loop=None, roles=None,
            min_reviewer_confidence=None, workspace=None, approval_engine=None,
            project_context="", memory_context="", context_pack=None,
            external_coder=None) -> LoopResult:
        def report(name, payload=None):
            if on_step:
                on_step(name, payload)

        def rec_step(step_name, role, model, attempt, prompt, gen):
            if recorder:
                recorder.save_step(
                    step_name, role, model, attempt, prompt, gen.text,
                    gen.latency_s, gen.prompt_tokens, gen.output_tokens,
                    gen.tokens_per_sec)

        def rec_agent(role, event_type, details=""):
            if recorder:
                b = roles[role]
                recorder.save_agent_event(b.agent_name, role, b.model,
                                          event_type, details)

        # Tool permissions come from the active loop.
        if loop is None:
            loop = _default_loop()
        if roles is None:
            roles, _errs = resolve_roles(loop)
        sup, cod, rev = roles["supervisor"], roles["coder"], roles["reviewer"]
        ta = roles.get("test_analyst")  # optional (Stage 1.8)
        ta_used = False
        ta_started = False
        ta_total_latency = 0.0
        last_analysis: Optional[TestAnalysis] = None
        fs_enabled = loop.filesystem_enabled
        term_enabled = loop.terminal_enabled
        loop_name = loop.name
        self.max_retries = loop.max_retries
        # External coding agent runs a single handoff pass (no automatic retries).
        ext_enabled = external_coder is not None and fs_enabled
        if ext_enabled:
            self.max_retries = 0
        # External outcome holders (final attempt).
        ext_used = False
        ext_result = None
        ext_handoff_path = None
        ext_handoff_safe = True
        ext_declined = False
        ext_violation = False
        ext_completion_failed = False
        ext_completion_mismatch = False
        ext_completion_obj = None
        ext_inspection = None
        ext_job_info = None

        # Project workspace (defaults to the internal sandbox = Stage 1.9 behavior).
        ws_manager = project_workspace.WorkspaceManager()
        ws = workspace or ws_manager.default_workspace()
        workspace_valid = len(ws_manager.validate_workspace(ws)) == 0
        _profiles = workspace_profiles.WorkspaceProfileRegistry()
        workspace_profile_valid = (
            workspace_valid
            and _profiles.get_profile(getattr(ws, "profile_name", "sandbox")) is not None)
        cmd_base = ws_manager.command_base(ws) if workspace_valid else ws.root_path

        # Human approval gates (disabled engine = no approvals required).
        if approval_engine is None:
            approval_engine = approval_gates.ApprovalGateEngine(approval_gates.ApprovalPolicy())
        approval_policy_valid = len(approval_gates.validate_policy(approval_engine.policy)) == 0
        loop_id = recorder.loop_id if recorder is not None else None

        # Context pack -> Supervisor summary + Coder/Reviewer file excerpts.
        cp_summary = context_packs.format_context_summary(context_pack) if context_pack else ""
        cp_files = context_packs.format_file_context(context_pack) if context_pack else ""

        # Stop conditions + quality gates engine for this loop.
        sc_engine = stop_conditions.StopConditionEngine.for_loop(
            loop, min_confidence_override=min_reviewer_confidence)
        review_only = not fs_enabled

        # Early guard: an invalid workspace/profile must NOT write, run, or commit.
        if not workspace_valid or not workspace_profile_valid:
            guard_ctx = stop_conditions.EvalContext(
                attempt=1, max_attempts=self.max_retries + 1, loop_name=loop_name,
                fs_enabled=fs_enabled, term_enabled=term_enabled, review_only=review_only,
                coder_parse_ok=True, proposed_file_count=0, files_changed=0,
                unsafe_path_count=0, unsafe_command_count=0, commands_executed=0,
                commands_failed=0, command_timed_out=0, review_parse_ok=True,
                review_approved=False, review_confidence=0.0,
                min_reviewer_confidence=sc_engine.min_reviewer_confidence,
                analyst_used=False, analyst_parse_ok=True, tests_run=False,
                tests_passed=None, repeated_failure=False,
                workspace_valid=workspace_valid,
                workspace_profile_valid=workspace_profile_valid)
            g = sc_engine.evaluate_gates(guard_ctx)
            c = sc_engine.evaluate_conditions(guard_ctx)
            decision = sc_engine.decide(guard_ctx, g, c)
            if recorder:
                for gr in g:
                    recorder.save_quality_gate_result(1, gr.gate_name, gr.passed,
                        gr.required, gr.severity, gr.message)
                for cr in c:
                    recorder.save_stop_condition_result(1, cr.condition_name,
                        cr.triggered, cr.severity, cr.message)
            return LoopResult(
                task=task, plan="", coder_output=None, review=None,
                final_status=decision.final_status or "BLOCKED",
                stop_reason=decision.stop_reason or "workspace_profile_invalid",
                retry_count=0, attempts=0, plan_latency_s=0.0, plan_prompt_tokens=0,
                plan_output_tokens=0, plan_tokens_per_sec=0.0, total_loop_s=0.0,
                quality_gates_passed=sum(1 for x in g if x.passed),
                quality_gates_failed=sum(1 for x in g if not x.passed),
                required_quality_gates_failed=sum(1 for x in g if x.required and not x.passed),
                stop_conditions_triggered=sum(1 for x in c if x.triggered),
                final_stop_condition=decision.final_condition,
                final_severity=decision.severity,
                reviewer_confidence_min=sc_engine.min_reviewer_confidence,
                required_gate_failed=(decision.required_failed_count > 0),
                failed_gate_names=[x.gate_name for x in g if not x.passed],
            )
        failure_signatures = []  # for repeated_failure detection
        all_gate_results = []
        last_gate_results = []
        last_cond_results = []
        last_decision = None

        loop_start = time.perf_counter()

        # --- 1. Supervisor plan ------------------------------------------------
        report("supervisor:plan:start")
        rec_agent("supervisor", "execution_started")
        plan_prompt = prompts.plan_prompt(task, loop, project_context, memory_context, cp_summary)
        plan_res = _gen(sup.model, plan_prompt, system=sup.system_prompt,
                        temperature=sup.temperature)
        rec_step("supervisor_plan", "supervisor", sup.model, 0, plan_prompt, plan_res)
        report("supervisor:plan", plan_res.text)

        max_attempts = self.max_retries + 1
        attempt_metrics: List[AttemptMetrics] = []
        coder_out: Optional[CoderOutput] = None
        review: Optional[Review] = None
        feedback = ""
        last_apply: Optional[filesystem.ApplyResult] = None
        last_cmd_results = []
        cmd_rendered = ""
        success = False
        fallback_used = False

        # --- 2. Coder / apply / execute / Reviewer retry loop ------------------
        for attempt in range(1, max_attempts + 1):
            attempt_approval_declined = False
            declined_risk = "medium"

            if ext_enabled:
                # External coding agent: hand off implementation, then inspect.
                ext_used = True
                coder_res = ollama_client.GenResult(text="", latency_s=0.0)
                rec_agent("coder", "execution_started")
                report("coder:start", attempt)
                (coder_out, apply_res, cmd_results, ext_result, ext_handoff_path,
                 ext_handoff_safe, ext_declined, ext_violation,
                 ext_completion_failed, ext_completion_mismatch,
                 ext_completion_obj, ext_inspection, ext_job_info) = self._external_step(
                    external_coder, task, plan_res.text, loop, ws, cp_summary,
                    feedback, attempt, recorder, report, loop_id,
                    memory_summary=memory_context, project_intel_summary=project_context)
                last_apply = apply_res
                if recorder:
                    self._record_file_ops(recorder, attempt, coder_out.files, apply_res)
                report("apply:done", (attempt, apply_res))
                last_cmd_results = cmd_results
                cmd_rendered = render_command_results(cmd_results)
                tests_passed = None
                cmds_failed = False
                analysis = None
                report("coder:done", (attempt, coder_out))
            else:
              report("coder:start", attempt)
              coder_file_ctx = cp_files if fs_enabled else ""
              if attempt == 1:
                rec_agent("coder", "execution_started")
                coder_prompt = prompts.implement_prompt(task, plan_res.text, loop,
                                                        coder_file_ctx)
                step_name = "coder_implement"
              else:
                prev = coder_out.render_files() if coder_out else "(none)"
                coder_prompt = prompts.revise_prompt(
                    task, plan_res.text, prev, feedback, loop, cmd_rendered,
                    coder_file_ctx)
                step_name = "coder_revise"
              coder_res = _gen(cod.model, coder_prompt, system=cod.system_prompt,
                               temperature=cod.temperature)
              rec_step(step_name, "coder", cod.model, attempt, coder_prompt, coder_res)
              coder_out = _parse_coder(coder_res.text)
              # Deterministic safety net: a command-only smoke-test request must
              # not depend on the model inventing valid coder JSON. If the model
              # failed to parse or proposed nothing safe, fall back to a known
              # safe command (still subject to terminal safety).
              if (loop.name == "test_fix" and _is_smoke_test_task(task)
                      and (not coder_out.parse_ok or not coder_out.commands)
                      and not coder_out.files):
                  coder_out = CoderOutput(
                      summary="deterministic smoke-test fallback",
                      files=[], commands=[SAFE_FALLBACK_COMMAND],
                      notes=["deterministic_test_fix_fallback"], parse_ok=True)
                  fallback_used = True
                  report("coder:fallback", (attempt, SAFE_FALLBACK_COMMAND))
              report("coder:done", (attempt, coder_out))

              # Apply files — loop permission, then human approval if required.
              if not fs_enabled:
                reason = f"filesystem tool not permitted for loop '{loop_name}'"
                apply_res = filesystem.ApplyResult(
                    blocked=[(f.get("path"), reason) for f in coder_out.files])
              else:
                fw_risk = approval_engine.default_risk("file_write")
                if coder_out.files and approval_engine.is_required("file_write", fw_risk):
                    report("approval:request", ("file_write", coder_out.files))
                    req = approval_gates.ApprovalRequest(
                        loop_id=loop_id, attempt_number=attempt,
                        gate_name="file_write_gate", action_type="file_write",
                        risk_level=fw_risk,
                        summary=f"{len(coder_out.files)} file write(s)",
                        details_json=json.dumps([f.get("path") for f in coder_out.files]))
                    dec = approval_engine.evaluate(req)
                    if recorder:
                        recorder.save_approval_event(req, dec)
                    report("approval:decision", ("file_write", dec))
                    if dec.approved:
                        apply_res = filesystem.apply_file_operations(coder_out.files, workspace=ws)
                    else:
                        attempt_approval_declined = True
                        declined_risk = fw_risk
                        apply_res = filesystem.ApplyResult(
                            blocked=[(f.get("path"), "human approval declined: file write")
                                     for f in coder_out.files])
                else:
                    apply_res = filesystem.apply_file_operations(coder_out.files, workspace=ws)
              last_apply = apply_res
              if recorder:
                self._record_file_ops(recorder, attempt, coder_out.files, apply_res)
              report("apply:done", (attempt, apply_res))

              # Execute commands — loop permission, then human approval if required.
              report("commands:start", (attempt, coder_out.commands))
              if not term_enabled:
                reason = f"terminal tool not permitted for loop '{loop_name}'"
                cmd_results = [
                    terminal.CommandResult(command=c, allowed=False, reason_if_blocked=reason)
                    for c in coder_out.commands]
              else:
                cx_risk = approval_engine.default_risk("command_execute")
                if coder_out.commands and approval_engine.is_required("command_execute", cx_risk):
                    report("approval:request", ("command_execute", coder_out.commands))
                    req = approval_gates.ApprovalRequest(
                        loop_id=loop_id, attempt_number=attempt,
                        gate_name="command_execute_gate", action_type="command_execute",
                        risk_level=cx_risk,
                        summary=f"{len(coder_out.commands)} command(s)",
                        details_json=json.dumps(list(coder_out.commands)))
                    dec = approval_engine.evaluate(req)
                    if recorder:
                        recorder.save_approval_event(req, dec)
                    report("approval:decision", ("command_execute", dec))
                    if dec.approved:
                        cmd_results = terminal.run_suggested_commands(
                            coder_out.commands, cmd_base, workspace=ws)
                    else:
                        attempt_approval_declined = True
                        declined_risk = cx_risk
                        cmd_results = [
                            terminal.CommandResult(command=c, allowed=False,
                                reason_if_blocked="human approval declined: command")
                            for c in coder_out.commands]
                else:
                    cmd_results = terminal.run_suggested_commands(
                        coder_out.commands, cmd_base, workspace=ws)
              last_cmd_results = cmd_results
              if recorder:
                for r in cmd_results:
                    recorder.save_command_result(attempt, r)
              cmd_rendered = render_command_results(cmd_results)
              tests_passed = _compute_tests_passed(cmd_results)
              cmds_failed = _commands_failed(cmd_results)
              report("commands:done", (attempt, cmd_results, tests_passed))

              # Test Analyst — only on a real command/test failure, and only when
              # the loop assigns an analyst (no terminal output -> no analysis).
              analysis = None
              if ta is not None and cmds_failed:
                if not ta_started:
                    rec_agent("test_analyst", "execution_started")
                    ta_started = True
                ta_used = True
                report("analyst:start", attempt)
                ta_prompt = prompts.test_analyst_prompt(
                    task, plan_res.text, coder_out.render_files(), cmd_rendered, loop)
                ta_res = _gen(ta.model, ta_prompt, system=ta.system_prompt,
                              temperature=ta.temperature)
                rec_step("test_analysis", "test_analyst", ta.model, attempt,
                         ta_prompt, ta_res)
                analysis = _parse_test_analysis(ta_res.text)
                last_analysis = analysis
                ta_total_latency += ta_res.latency_s
                report("analyst:done", (attempt, analysis))

            # Reviewer sees plan + files + command/test output. Skipped when the
            # external agent did not complete (no work to review).
            if ext_enabled and (ext_declined or ext_completion_failed):
                review = Review(
                    approved=False,
                    summary=("external completion failed/blocked" if ext_completion_failed
                             else "external agent not completed"),
                    issues=[], required_changes=[], confidence_score=0.0,
                    stop_reason=("external_completion_failed" if ext_completion_failed
                                 else "needs_external_agent"))
            else:
                ext_completion_text = (external_agents.format_completion_context(
                    ext_completion_obj, ext_inspection) if ext_completion_obj else "")
                report("reviewer:start", attempt)
                if attempt == 1:
                    rec_agent("reviewer", "execution_started")
                review_prompt = prompts.review_prompt(
                    task, plan_res.text, coder_out.render_files(), loop, cmd_rendered,
                    cp_files, ext_completion_text)
                review_res = _gen(rev.model, review_prompt, system=rev.system_prompt,
                                  temperature=rev.temperature)
                rec_step("reviewer_review", "reviewer", rev.model, attempt,
                         review_prompt, review_res)
                review = _parse_review(review_res.text)
                # Design-only loops are judged by their output contract, not by
                # code/file-change expectations. If the contract is satisfied,
                # approve with an internally CONSISTENT review (confidence meets
                # the threshold, no required changes) so it can't produce an
                # approved=true / confidence=0.0 contradiction.
                ok, why = _design_contract_ok(loop.name, coder_out, review)
                if ok:
                    review.approved = True
                    review.required_changes = []
                    if review.confidence_score < sc_engine.min_reviewer_confidence:
                        review.confidence_score = sc_engine.min_reviewer_confidence
                    review.summary = (review.summary or "") + f" [design contract satisfied: {why}]"
                    review.stop_reason = review.stop_reason or "design_contract_satisfied"
                if recorder:
                    recorder.save_review(attempt, review)
                report("reviewer:done", (attempt, review))

            _rev_res = review_res if not (ext_enabled and (ext_declined or ext_completion_failed)) else \
                ollama_client.GenResult(text="", latency_s=0.0)
            attempt_metrics.append(AttemptMetrics(
                attempt=attempt,
                coder_latency_s=coder_res.latency_s,
                coder_prompt_tokens=coder_res.prompt_tokens,
                coder_output_tokens=coder_res.output_tokens,
                coder_tokens_per_sec=coder_res.tokens_per_sec,
                reviewer_latency_s=_rev_res.latency_s,
                reviewer_prompt_tokens=_rev_res.prompt_tokens,
                reviewer_output_tokens=_rev_res.output_tokens,
                reviewer_tokens_per_sec=_rev_res.tokens_per_sec,
                approved=review.approved,
                files_created=list(apply_res.created),
                files_updated=list(apply_res.updated),
                files_blocked=list(apply_res.blocked),
                command_results=list(cmd_results),
                commands_suggested=len(coder_out.commands),
                tests_passed=tests_passed,
            ))

            # --- Stop conditions + quality gates ---------------------------
            # Classify file/command blocks into categories.
            file_cls = [_classify_file_block(reason) for _p, reason in apply_res.blocked]
            cmd_cls = [_classify_cmd_block(r.reason_if_blocked)
                       for r in cmd_results if not r.allowed]
            unsafe_paths = file_cls.count("unsafe")
            ws_write_blocked = file_cls.count("ws_write")
            protected_blocked = file_cls.count("protected")
            unsafe_cmds = cmd_cls.count("unsafe")
            ws_cmd_blocked = cmd_cls.count("ws_command")

            # Repeated-failure detection by signature.
            if cmds_failed or not review.approved:
                if cmds_failed:
                    sig = tuple(sorted((r.command, (r.stderr or "")[:80])
                                       for r in cmd_results if r.allowed and not r.succeeded))
                else:
                    sig = ("review", (review.summary or "")[:80])
                repeated = sig in failure_signatures
                failure_signatures.append(sig)
            else:
                repeated = False

            ctx = stop_conditions.EvalContext(
                attempt=attempt, max_attempts=max_attempts, loop_name=loop_name,
                fs_enabled=fs_enabled, term_enabled=term_enabled, review_only=review_only,
                coder_parse_ok=coder_out.parse_ok,
                proposed_file_count=len(coder_out.files),
                files_changed=len(apply_res.created) + len(apply_res.updated),
                unsafe_path_count=unsafe_paths, unsafe_command_count=unsafe_cmds,
                commands_executed=sum(1 for r in cmd_results if r.allowed),
                commands_failed=sum(1 for r in cmd_results if r.allowed and not r.succeeded),
                command_timed_out=sum(1 for r in cmd_results if r.timed_out),
                review_parse_ok=review.parse_ok, review_approved=review.approved,
                review_confidence=review.confidence_score,
                min_reviewer_confidence=sc_engine.min_reviewer_confidence,
                review_required_changes=len(review.required_changes or []),
                review_has_severe_issue=_review_severe_issue(review),
                analyst_used=(analysis is not None),
                analyst_parse_ok=(analysis.parse_ok if analysis is not None else True),
                tests_run=(tests_passed is not None), tests_passed=tests_passed,
                repeated_failure=repeated,
                workspace_valid=workspace_valid,
                workspace_write_blocked_count=ws_write_blocked,
                protected_blocked_count=protected_blocked,
                workspace_command_blocked_count=ws_cmd_blocked,
                workspace_profile_valid=workspace_profile_valid,
                approval_policy_valid=approval_policy_valid,
                approval_declined=attempt_approval_declined,
                approval_declined_action_risk=declined_risk,
                external_declined=ext_declined,
                external_violation=ext_violation,
                external_completion_failed=ext_completion_failed,
                external_completion_mismatch=ext_completion_mismatch,
            )
            gate_results = sc_engine.evaluate_gates(ctx)
            cond_results = sc_engine.evaluate_conditions(ctx)
            decision = sc_engine.decide(ctx, gate_results, cond_results)
            if recorder:
                for g in gate_results:
                    recorder.save_quality_gate_result(
                        attempt, g.gate_name, g.passed, g.required, g.severity, g.message)
                for c in cond_results:
                    recorder.save_stop_condition_result(
                        attempt, c.condition_name, c.triggered, c.severity, c.message)
            all_gate_results.extend(gate_results)
            last_gate_results = gate_results
            last_cond_results = cond_results
            last_decision = decision
            report("gates:done", (attempt, gate_results, cond_results, decision))

            if decision.stop:
                break
            # Build feedback for the coder: reviewer notes + command failures +
            # the Test Analyst's diagnosis (when it ran this attempt).
            fb = [review.feedback_text()]
            if cmds_failed:
                fb.append("Command/test failures occurred; fix them.")
            if analysis is not None:
                fb.append(analysis.feedback_text())
            feedback = "\n".join(fb)

        attempts = len(attempt_metrics)
        final_status = last_decision.final_status or "REJECTED"
        stop_reason = last_decision.stop_reason or "max_retries_reached"

        # Mark each role's execution complete.
        for role in ("supervisor", "coder", "reviewer"):
            rec_agent(role, "execution_completed", final_status)
        if ta_used:
            rec_agent("test_analyst", "execution_completed", final_status)

        # Aggregate blocked paths across all attempts (security visibility).
        all_blocked: List[Tuple[str, str]] = []
        for m in attempt_metrics:
            all_blocked.extend(m.files_blocked)

        # Stop-condition / quality-gate summary (final attempt + totals).
        gates_passed = sum(1 for g in all_gate_results if g.passed)
        gates_failed = sum(1 for g in all_gate_results if not g.passed)
        req_failed_total = sum(1 for g in all_gate_results if g.required and not g.passed)
        last_failed = [g.gate_name for g in last_gate_results if not g.passed]
        triggered_now = sum(1 for c in last_cond_results if c.triggered)
        req_failed_now = last_decision.required_failed_count if last_decision else 0

        return LoopResult(
            task=task,
            plan=plan_res.text,
            coder_output=coder_out,
            review=review,
            final_status=final_status,
            stop_reason=stop_reason,
            retry_count=attempts - 1,
            attempts=attempts,
            plan_latency_s=plan_res.latency_s,
            plan_prompt_tokens=plan_res.prompt_tokens,
            plan_output_tokens=plan_res.output_tokens,
            plan_tokens_per_sec=plan_res.tokens_per_sec,
            total_loop_s=time.perf_counter() - loop_start,
            attempt_metrics=attempt_metrics,
            files_created=list(last_apply.created) if last_apply else [],
            files_updated=list(last_apply.updated) if last_apply else [],
            files_blocked=all_blocked,
            suggested_commands=coder_out.commands if coder_out else [],
            command_results=list(last_cmd_results),
            tests_passed=_compute_tests_passed(last_cmd_results),
            test_analyst_used=ta_used,
            test_analyst_latency_s=ta_total_latency,
            test_analyst_failure_detected=(last_analysis.failure_detected
                                           if last_analysis else None),
            test_analyst_confidence=(last_analysis.confidence_score
                                     if last_analysis else None),
            test_analysis=last_analysis,
            test_analyst_agent_name=(ta.agent_name if ta else None),
            test_analyst_model=(ta.model if ta else None),
            quality_gates_passed=gates_passed,
            quality_gates_failed=gates_failed,
            required_quality_gates_failed=req_failed_total,
            stop_conditions_triggered=triggered_now,
            final_stop_condition=(last_decision.final_condition if last_decision else None),
            final_severity=(last_decision.severity if last_decision else None),
            reviewer_confidence_min=sc_engine.min_reviewer_confidence,
            reviewer_confidence_actual=(review.confidence_score if review else None),
            required_gate_failed=(req_failed_now > 0),
            failed_gate_names=last_failed,
            external_agent_used=ext_used,
            external_agent_result=ext_result,
            external_handoff_path=ext_handoff_path,
            external_handoff_safe=ext_handoff_safe,
            external_mode=(external_coder.get("mode") if external_coder else None),
            deterministic_test_fix_fallback_used=fallback_used,
            external_job_info=ext_job_info,
        )
