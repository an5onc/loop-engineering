"""Loop Templates (Stage 2.5): reusable, parameterized loop definitions.

A template renders an `objective_template` (with plain-text variables) into a
concrete task, then the *normal* loop engine runs it. Templates are convenience
only — they NEVER bypass workspace/profile/approval/quality-gate/stop-condition
or filesystem/terminal/git safety. Variables are plain text and are never
executed as code.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

_DATE = "2026-06-26T00:00:00Z"
SUPPORTED_TOOLS = {"filesystem", "terminal", "git"}


@dataclass
class LoopTemplate:
    name: str
    display_name: str
    description: str
    version: str
    category: str
    objective_template: str
    trigger_template: str
    default_loop_type: str
    recommended_agents: Dict[str, str]
    required_variables: List[str]
    optional_variables: List[str] = field(default_factory=list)
    default_tools: List[str] = field(default_factory=list)
    default_quality_gates: List[str] = field(default_factory=list)
    default_stop_conditions: List[str] = field(default_factory=list)
    safety_level: str = "standard"
    tags: List[str] = field(default_factory=list)
    created_at: str = _DATE
    updated_at: str = _DATE


def validate_template(t: LoopTemplate) -> List[str]:
    errors = []
    if not t.name or not isinstance(t.name, str):
        errors.append("name must be a non-empty string")
    if not t.objective_template:
        errors.append("objective_template is required")
    if not t.default_loop_type:
        errors.append("default_loop_type is required")
    if not isinstance(t.required_variables, list):
        errors.append("required_variables must be a list")
    unknown = set(t.default_tools) - SUPPORTED_TOOLS
    if unknown:
        errors.append(f"unknown tools: {sorted(unknown)}")
    if not t.safety_level:
        errors.append("safety_level is required")
    return errors


def load_builtin_templates() -> Dict[str, LoopTemplate]:
    core = {"supervisor": "supervisor", "coder": "coder", "reviewer": "reviewer"}
    templates = [
        LoopTemplate(
            name="build_feature", display_name="Build Feature",
            description="Build a feature in a project workspace.",
            version="1.0", category="build",
            objective_template=(
                "Build the feature '{feature_name}' in {target_area}. "
                "{feature_description} "
                "Acceptance criteria: {acceptance_criteria}. "
                "Include tests where appropriate."),
            trigger_template="manual: build feature {feature_name}",
            default_loop_type="code_build",
            recommended_agents=dict(core),
            required_variables=["feature_name", "feature_description",
                                "target_area", "acceptance_criteria"],
            default_tools=["filesystem", "terminal", "git"],
            default_quality_gates=["valid_coder_json", "safe_file_paths", "files_written"],
            default_stop_conditions=["reviewer_approved", "max_retries_reached"],
            tags=["feature", "build"],
        ),
        LoopTemplate(
            name="fix_bug", display_name="Fix Bug",
            description="Investigate and fix a bug.",
            version="1.0", category="fix",
            objective_template=(
                "Investigate and fix this bug: {bug_summary}. "
                "Observed behavior: {observed_behavior}. "
                "Expected behavior: {expected_behavior}. "
                "Reproduction steps: {reproduction_steps}. "
                "Add or run tests to confirm the fix."),
            trigger_template="manual: fix bug",
            default_loop_type="test_fix",
            recommended_agents=dict(core),
            required_variables=["bug_summary", "observed_behavior",
                                "expected_behavior", "reproduction_steps"],
            default_tools=["filesystem", "terminal"],
            default_quality_gates=["valid_coder_json", "safe_file_paths"],
            default_stop_conditions=["test_passed", "test_failed_after_retries"],
            tags=["bug", "fix", "test"],
        ),
        LoopTemplate(
            name="write_tests", display_name="Write Tests",
            description="Create or improve tests for existing code.",
            version="1.0", category="test",
            objective_template=(
                "Create or improve tests for {target_file_or_module}. "
                "Cover these scenarios: {test_scenarios}. Run the tests."),
            trigger_template="manual: write tests",
            default_loop_type="test_fix",
            recommended_agents=dict(core),
            required_variables=["target_file_or_module", "test_scenarios"],
            default_tools=["filesystem", "terminal"],
            default_quality_gates=["valid_coder_json", "safe_file_paths"],
            default_stop_conditions=["test_passed", "test_failed_after_retries"],
            tags=["test"],
        ),
        LoopTemplate(
            name="review_code", display_name="Review Code",
            description="Review code for correctness, safety, maintainability, and edge cases.",
            version="1.0", category="review",
            objective_template=(
                "Review {review_target} for correctness, safety, maintainability, "
                "and edge cases. Focus on: {review_focus}. Report findings only; "
                "do not modify files."),
            trigger_template="manual: review code",
            default_loop_type="code_review",
            recommended_agents=dict(core),
            required_variables=["review_target", "review_focus"],
            default_tools=["terminal"],
            default_quality_gates=["reviewer_json_valid"],
            default_stop_conditions=["reviewer_approved", "max_retries_reached"],
            tags=["review"],
        ),
        LoopTemplate(
            name="design_prompt", display_name="Design Prompt",
            description="Create a reusable high-quality agent prompt.",
            version="1.0", category="design",
            objective_template=(
                "Design a reusable, high-quality prompt for an agent with role "
                "'{agent_role}'. Goal: {goal}. Constraints: {constraints}. "
                "Output format: {output_format}."),
            trigger_template="manual: design prompt",
            default_loop_type="prompt_design",
            recommended_agents={"supervisor": "supervisor",
                                "coder": "prompt_designer", "reviewer": "reviewer"},
            required_variables=["agent_role", "goal", "constraints", "output_format"],
            default_tools=[],
            default_quality_gates=["reviewer_json_valid"],
            default_stop_conditions=["reviewer_approved", "max_retries_reached"],
            tags=["prompt", "design"],
        ),
        LoopTemplate(
            name="design_loop", display_name="Design Loop",
            description="Create a reusable loop definition.",
            version="1.0", category="design",
            objective_template=(
                "Design a reusable loop definition named '{loop_name}'. "
                "Goal: {loop_goal}. Trigger: {trigger}. Actions: {actions}. "
                "Stop condition: {stop_condition}."),
            trigger_template="manual: design loop",
            default_loop_type="loop_design",
            recommended_agents={"supervisor": "supervisor",
                                "coder": "loop_designer", "reviewer": "reviewer"},
            required_variables=["loop_name", "loop_goal", "trigger", "actions",
                                "stop_condition"],
            default_tools=[],
            default_quality_gates=["reviewer_json_valid"],
            default_stop_conditions=["reviewer_approved", "max_retries_reached"],
            tags=["loop", "design", "meta"],
        ),
    ]
    return {t.name: t for t in templates}


class LoopTemplateRegistry:
    def __init__(self, templates=None):
        self._templates = {}
        for t in (templates or load_builtin_templates()).values():
            self.register(t)

    def register(self, template: LoopTemplate):
        errors = validate_template(template)
        if errors:
            raise ValueError(f"invalid template '{template.name}': {errors}")
        self._templates[template.name] = template

    def list_templates(self):
        return sorted(self._templates.values(), key=lambda t: t.name)

    def get_template(self, name):
        return self._templates.get(name)

    def names(self):
        return sorted(self._templates.keys())

    def render(self, template_name, variables):
        """Validate required vars and render the objective into a task string."""
        t = self.get_template(template_name)
        if t is None:
            raise ValueError(f"unknown template '{template_name}'")
        variables = variables or {}
        missing = [v for v in t.required_variables
                   if not str(variables.get(v, "")).strip()]
        if missing:
            raise ValueError(f"missing required variable(s): {missing}")
        defaults = {k: "" for k in t.optional_variables}
        try:
            return t.objective_template.format(**{**defaults, **variables})
        except KeyError as exc:
            raise ValueError(f"template references unknown variable: {exc}")


def render_template(template_name, variables, registry=None):
    reg = registry or LoopTemplateRegistry()
    return reg.render(template_name, variables)
