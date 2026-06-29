"""Loop Registry (Stage 1.6): named, reusable loop definitions.

A LoopDefinition describes *how* a loop should behave — which tools it may use,
how the agents should be steered, and metadata. Tool permissions in
`allowed_tools` are enforced by the engine (see loop_engine.py); a tool that is
not listed never runs, regardless of what the models emit.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import config

# The only tools a loop may ever be granted.
SUPPORTED_TOOLS = {"filesystem", "terminal", "git"}

_BUILTIN_DATE = "2026-06-26T00:00:00Z"


@dataclass
class LoopDefinition:
    name: str
    display_name: str
    description: str
    version: str
    trigger_type: str
    objective_template: str
    default_models: Dict[str, str]
    max_retries: int
    allowed_tools: List[str]
    safety_level: str
    tags: List[str] = field(default_factory=list)
    created_at: str = _BUILTIN_DATE
    updated_at: str = _BUILTIN_DATE
    # Agent assignments (Stage 1.7); default to the core agents.
    supervisor_agent: str = "supervisor"
    coder_agent: str = "coder"
    reviewer_agent: str = "reviewer"
    # Optional test-analyst agent (Stage 1.8); None = not used.
    test_analyst_agent: Optional[str] = None
    # Stop conditions + quality gates (Stage 1.9).
    stop_conditions: List[str] = field(default_factory=list)
    quality_gates: List[str] = field(default_factory=list)
    min_reviewer_confidence: float = 0.70

    # Convenience permission checks.
    def allows(self, tool: str) -> bool:
        return tool in self.allowed_tools

    @property
    def filesystem_enabled(self) -> bool:
        return "filesystem" in self.allowed_tools

    @property
    def terminal_enabled(self) -> bool:
        return "terminal" in self.allowed_tools

    @property
    def git_enabled(self) -> bool:
        return "git" in self.allowed_tools

    def objective(self, task: str) -> str:
        try:
            return self.objective_template.format(task=task)
        except (KeyError, IndexError):
            return task


def validate_loop_definition(loop: LoopDefinition) -> List[str]:
    """Return a list of validation errors (empty list == valid)."""
    errors: List[str] = []
    if not loop.name or not isinstance(loop.name, str):
        errors.append("name must be a non-empty string")
    if not loop.objective_template:
        errors.append("objective_template is required")
    if not isinstance(loop.max_retries, int) or loop.max_retries < 0:
        errors.append("max_retries must be an integer >= 0")
    unknown = set(loop.allowed_tools) - SUPPORTED_TOOLS
    if unknown:
        errors.append(f"unknown tools not allowed: {sorted(unknown)}")
    if not isinstance(loop.default_models, dict):
        errors.append("default_models must be a dict")
    return errors


def load_builtin_loops() -> Dict[str, LoopDefinition]:
    """Construct the five built-in loop definitions."""
    models = {"supervisor": config.SUPERVISOR_MODEL, "coder": config.CODER_MODEL}

    loops = [
        LoopDefinition(
            name="code_build",
            display_name="Code Build",
            description="Build or modify code safely inside workspace/.",
            version="1.0",
            trigger_type="manual",
            objective_template="Build or modify code to accomplish this task: {task}",
            default_models=dict(models),
            max_retries=3,
            allowed_tools=["filesystem", "terminal", "git"],
            safety_level="standard",
            tags=["code", "build", "default"],
            test_analyst_agent="test_analyst",
        ),
        LoopDefinition(
            name="code_review",
            display_name="Code Review",
            description="Review generated code without making file changes.",
            version="1.0",
            trigger_type="manual",
            objective_template=(
                "Review the code currently in the workspace for this concern: {task}. "
                "Do NOT modify any files; report findings only."
            ),
            default_models=dict(models),
            max_retries=2,
            allowed_tools=["terminal"],  # read/test commands only; no fs, no git
            safety_level="read_only",
            tags=["code", "review"],
        ),
        LoopDefinition(
            name="test_fix",
            display_name="Test & Fix",
            description="Run tests, analyze failures, and revise files until tests pass.",
            version="1.0",
            trigger_type="manual",
            objective_template=(
                "Run the tests and fix any failures for this task: {task}. "
                "Iterate until the tests pass."
            ),
            default_models=dict(models),
            max_retries=3,
            allowed_tools=["filesystem", "terminal"],  # no git
            safety_level="standard",
            tags=["test", "fix"],
            test_analyst_agent="test_analyst",
        ),
        LoopDefinition(
            name="prompt_design",
            display_name="Prompt Design",
            description="Generate structured prompts for agents or local models.",
            version="1.0",
            trigger_type="manual",
            objective_template=(
                "Design a high-quality, structured prompt for this need: {task}. "
                "Output only the final prompt text."
            ),
            default_models=dict(models),
            max_retries=1,
            allowed_tools=[],  # no tools at all
            safety_level="read_only",
            tags=["prompt", "design"],
            coder_agent="prompt_designer",
        ),
        LoopDefinition(
            name="loop_design",
            display_name="Loop Design",
            description="Design new reusable loop definitions.",
            version="1.0",
            trigger_type="manual",
            objective_template=(
                "Design a new reusable loop definition for this purpose: {task}. "
                "Output a structured loop definition as JSON."
            ),
            default_models=dict(models),
            max_retries=1,
            allowed_tools=[],
            safety_level="read_only",
            tags=["loop", "design", "meta"],
            coder_agent="loop_designer",
        ),
    ]

    # Stop conditions per loop (Stage 1.9); all loops evaluate all quality gates.
    all_gates = [
        "valid_coder_json", "safe_file_paths", "safe_commands_only",
        "reviewer_json_valid", "test_analyst_json_valid", "commands_successful",
        "files_written", "reviewer_confidence_minimum",
        "reviewer_consistency_valid",
        "workspace_valid", "workspace_write_allowed",
        "workspace_command_allowed", "protected_paths_blocked",
        "workspace_profile_valid",
        "approval_policy_valid", "required_approval_obtained",
        "declined_approval_respected",
    ]
    stop_by_loop = {
        "code_build": ["reviewer_approved", "max_retries_reached",
                       "unsafe_operation_blocked", "command_timeout",
                       "no_files_changed", "repeated_failure"],
        "test_fix": ["test_passed", "test_failed_after_retries",
                     "max_retries_reached", "command_timeout", "repeated_failure"],
        "code_review": ["reviewer_approved", "max_retries_reached"],
        "prompt_design": ["reviewer_approved", "max_retries_reached"],
        "loop_design": ["reviewer_approved", "max_retries_reached"],
    }
    for lp in loops:
        lp.quality_gates = list(all_gates)
        conds = list(stop_by_loop.get(lp.name, ["reviewer_approved", "max_retries_reached"]))
        # Workspace violations / invalid profile are terminal for every loop.
        conds.append("workspace_violation_blocked")
        conds.append("workspace_profile_invalid")
        conds.append("human_approval_declined")
        conds.append("needs_external_agent")
        conds.append("external_agent_workspace_violation")
        conds.append("external_completion_failed")
        conds.append("external_completion_workspace_mismatch")
        lp.stop_conditions = conds

    return {lp.name: lp for lp in loops}


class LoopRegistry:
    """Holds loop definitions and serves them by name."""

    def __init__(self, loops: Optional[Dict[str, LoopDefinition]] = None):
        self._loops: Dict[str, LoopDefinition] = {}
        for lp in (loops or load_builtin_loops()).values():
            self.register(lp)

    def register(self, loop: LoopDefinition) -> None:
        errors = validate_loop_definition(loop)
        if errors:
            raise ValueError(f"invalid loop '{loop.name}': {errors}")
        self._loops[loop.name] = loop

    def list_loops(self) -> List[LoopDefinition]:
        return sorted(self._loops.values(), key=lambda lp: lp.name)

    def get_loop(self, name: str) -> Optional[LoopDefinition]:
        return self._loops.get(name)

    def names(self) -> List[str]:
        return sorted(self._loops.keys())


DEFAULT_LOOP = "code_build"
