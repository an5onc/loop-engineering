"""Prompt templates for each role in the loop.

All builders take the active LoopDefinition so behavior adapts per loop:
filesystem-disabled loops instruct the Coder to emit no files, terminal-disabled
loops instruct it to emit no commands, and the design loops change what the
Coder's `summary` should contain. Enforcement still happens in the engine — the
prompts only steer the models.
"""

SUPERVISOR_SYSTEM = (
    "You are the Supervisor in a multi-agent engineering loop. "
    "You think in clear, numbered steps. You do not write the final code yourself; "
    "you direct the Coder. Be concise and unambiguous."
)

CODER_SYSTEM = (
    "You are the Coder in a multi-agent engineering loop. "
    "You implement exactly what the plan specifies and you act on reviewer feedback. "
    "You return your work as STRICT JSON. "
    "You never wrap the JSON in prose or markdown fences."
)

REVIEWER_SYSTEM = (
    "You are the Reviewer in a multi-agent engineering loop. "
    "You judge the Coder's work against the task, plan, and the active loop's goal, "
    "then return a STRICT JSON verdict. You never wrap the JSON in markdown fences."
)

_CODER_CONTRACT = (
    "Return ONLY a single JSON object (no markdown, no prose) with EXACTLY these keys:\n"
    "{\n"
    '  "summary": "what you produced and how it satisfies the objective",\n'
    '  "files": [\n'
    '    {"path": "relative/path.py", "content": "FULL file contents as a string"}\n'
    "  ],\n"
    '  "commands": ["safe shell commands to run inside the workspace"],\n'
    '  "notes": ["any caveats or follow-ups"]\n'
    "}\n"
    "Rules for `path`: relative only, inside the workspace, no leading '/', no '..', "
    "no '~'. Provide COMPLETE file contents (not diffs). Include test files when useful.\n"
    "Rules for `commands`: ONLY these families are allowed and will run "
    "(python, python3, pytest, ls, cat, pwd). No shell operators "
    "(; && || | > < $() backticks). No paths with '..', '~', or absolute paths. "
    "To run tests prefer: `python -m unittest <file>` or `pytest <file>`."
)


def _loop_context(loop) -> str:
    """Per-loop steering text injected into every prompt."""
    tools = ", ".join(loop.allowed_tools) if loop.allowed_tools else "none"
    lines = [
        f"Active loop: {loop.name} (v{loop.version}) — {loop.description}",
        f"Permitted tools: {tools}.",
    ]
    if not loop.filesystem_enabled:
        lines.append(
            "FILESYSTEM WRITES ARE DISABLED for this loop: return an EMPTY \"files\" "
            "list. Do not propose writing any files.")
    if not loop.terminal_enabled:
        lines.append(
            "COMMAND EXECUTION IS DISABLED for this loop: return an EMPTY \"commands\" "
            "list.")
    # Output-shape guidance for the design/review loops.
    if loop.name == "prompt_design":
        lines.append(
            "GOAL: put the final designed prompt as the \"summary\" value "
            "(files=[], commands=[]).")
    elif loop.name == "loop_design":
        lines.append(
            "GOAL: put a COMPLETE loop definition JSON (as a string) in \"summary\", "
            "with keys: name, display_name, description, version, trigger_type, "
            "objective_template, default_models, max_retries, allowed_tools, "
            "safety_level, tags. (files=[], commands=[]).")
    elif loop.name == "code_review":
        lines.append(
            "GOAL: do NOT write files. Put your review findings in \"summary\" and "
            "\"notes\". You may suggest safe read/test commands in \"commands\".")
    return "\n".join(lines)


def plan_prompt(task: str, loop, project_context: str = "", memory_context: str = "",
                context_summary: str = "") -> str:
    ctx = (f"{project_context}\n\n" if project_context
           else "PROJECT CONTEXT:\n- (no project scan available; proceed normally)\n\n")
    mem = (f"{memory_context}\n\n" if memory_context
           else "MEMORY CONTEXT:\n- (no relevant memory found; proceed normally)\n\n")
    cp = f"{context_summary}\n\n" if context_summary else ""
    return (
        f"{_loop_context(loop)}\n\n"
        f"{ctx}"
        f"{mem}"
        f"{cp}"
        f"Objective:\n{loop.objective(task)}\n\n"
        "Produce a short, numbered plan the Coder can follow, consistent with the "
        "active loop's permitted tools, the project context, relevant memory, and "
        "the context pack above. Do NOT write implementation code. Output only the plan."
    )


def implement_prompt(task: str, plan: str, loop, file_context: str = "") -> str:
    fc = f"{file_context}\n\n" if file_context else ""
    return (
        f"{_loop_context(loop)}\n\n"
        f"{fc}"
        f"Objective:\n{loop.objective(task)}\n\n"
        f"Supervisor's plan:\n{plan}\n\n"
        "Carry out the plan and produce your output.\n\n"
        f"{_CODER_CONTRACT}"
    )


def revise_prompt(task, plan, previous_files, feedback, loop, commands_rendered="",
                  file_context="") -> str:
    cmd_block = (
        f"\nCommand / output from your previous attempt:\n{commands_rendered}\n"
        if commands_rendered else ""
    )
    fc = f"{file_context}\n\n" if file_context else ""
    return (
        f"{_loop_context(loop)}\n\n"
        f"{fc}"
        f"Objective:\n{loop.objective(task)}\n\n"
        f"Supervisor's plan:\n{plan}\n\n"
        f"Your previous output:\n{previous_files}\n"
        f"{cmd_block}\n"
        f"The Reviewer REJECTED it with this feedback:\n{feedback}\n\n"
        "Produce a corrected, COMPLETE result that resolves every required change.\n\n"
        f"{_CODER_CONTRACT}"
    )


def intake_prompt(req) -> str:
    """Intake Analyst: analyze a raw task. STRICT JSON."""
    loops = ", ".join(req.available_loops) if req.available_loops else "code_build, code_review, test_fix, prompt_design, loop_design"
    return (
        f"Raw user task:\n{req.raw_task}\n\n"
        f"Workspace: {req.workspace_name or '(default internal)'} "
        f"(profile: {req.workspace_profile or 'sandbox'})\n"
        f"Available loop types: {loops}\n"
        f"Explicit loop requested: {req.loop_type or '(none)'}\n"
        f"Project context available: {req.project_context_available}; "
        f"memory: {req.memory_context_available}; context pack: {req.context_pack_available}\n\n"
        "Analyze the task. Return ONLY a single JSON object (no markdown, no prose) "
        "with EXACTLY these keys:\n"
        "{\n"
        '  "clarified_task": "an executable restatement of the task",\n'
        '  "intent_summary": "one sentence on the user intent",\n'
        '  "detected_loop_type": "code_build|code_review|test_fix|prompt_design|loop_design",\n'
        '  "confidence_score": 0.0,\n'
        '  "ambiguity_score": 0.0,\n'
        '  "risk_level": "low|medium|high|critical",\n'
        '  "missing_details": [],\n'
        '  "assumptions": [],\n'
        '  "clarification_required": true,\n'
        '  "clarification_questions": [\n'
        '    {"id": "q1", "question": "...", "reason": "...", "required": true, "suggested_answers": []}\n'
        "  ],\n"
        '  "recommended_workspace": null,\n'
        '  "recommended_profile": null,\n'
        '  "recommended_template": null,\n'
        '  "recommended_next_action": "proceed|ask_clarification|block"\n'
        "}"
    )


def test_analyst_prompt(task, plan, files_rendered, commands_rendered, loop) -> str:
    """Test Analyst: diagnose a command/test failure. STRICT JSON."""
    return (
        f"{_loop_context(loop)}\n\n"
        f"Objective:\n{loop.objective(task)}\n\n"
        f"Plan:\n{plan}\n\n"
        f"Files:\n{files_rendered}\n\n"
        f"Command / test output (a failure occurred):\n{commands_rendered}\n\n"
        "Diagnose the failure. Return ONLY a single JSON object (no markdown, no "
        "prose) with EXACTLY these keys:\n"
        "{\n"
        '  "failure_detected": true or false,\n'
        '  "failure_type": "test_failure|runtime_error|syntax_error|missing_dependency|unsafe_command_blocked|unknown",\n'
        '  "summary": "one or two sentence overview",\n'
        '  "root_cause": "the underlying cause",\n'
        '  "evidence": ["specific lines/messages from the output"],\n'
        '  "recommended_changes": ["concrete changes the Coder should make"],\n'
        '  "confidence_score": a number between 0.0 and 1.0\n'
        "}"
    )


def review_prompt(task, plan, files_rendered, loop, commands_rendered="",
                  file_context="", external_completion="") -> str:
    cmd_block = (
        f"Command / test output:\n{commands_rendered}\n\n"
        if commands_rendered else "No commands were executed.\n\n"
    )
    fc = f"{file_context}\n\n" if file_context else ""
    ec = f"{external_completion}\n\n" if external_completion else ""
    return (
        f"{_loop_context(loop)}\n\n"
        f"{ec}"
        f"{fc}"
        f"Objective:\n{loop.objective(task)}\n\n"
        f"Plan:\n{plan}\n\n"
        f"Coder's output:\n{files_rendered}\n\n"
        f"{cmd_block}"
        "Judge the output against the objective and the active loop's goal. "
        "For build/test loops, files must be correct and any tests must pass. "
        "For review/design loops, judge the quality of the analysis/prompt/loop "
        "definition (there will be no files). "
        "Return ONLY a single JSON object (no markdown, no prose) with EXACTLY these keys:\n"
        "{\n"
        '  "approved": true or false,\n'
        '  "summary": "one or two sentence overall assessment",\n'
        '  "issues": ["problems found; empty if none"],\n'
        '  "required_changes": ["concrete changes needed; empty if approved"],\n'
        '  "confidence_score": a number between 0.0 and 1.0,\n'
        '  "stop_reason": "short reason for your decision"\n'
        "}"
    )
