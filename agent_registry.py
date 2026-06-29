"""Agent Registry (Stage 1.7): named, reusable agent definitions.

An AgentDefinition describes *who* performs a role in a loop — its model, system
prompt, temperature, output contract, and which loops/tools it may serve. Loops
(loop_registry.py) reference agents by name; the engine resolves those names to
agents and uses each agent's system prompt + model (subject to CLI overrides).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import config
import loop_registry
import prompts

SUPPORTED_TOOLS = loop_registry.SUPPORTED_TOOLS
KNOWN_ROLES = {"supervisor", "coder", "reviewer", "designer", "analyst"}

_BUILTIN_DATE = "2026-06-26T00:00:00Z"


@dataclass
class AgentDefinition:
    name: str
    display_name: str
    role: str
    description: str
    default_model: str
    temperature: float
    system_prompt: str
    allowed_loop_types: List[str]
    allowed_tools: List[str]
    output_contract: str
    safety_level: str
    tags: List[str] = field(default_factory=list)
    version: str = "1.0"
    created_at: str = _BUILTIN_DATE
    updated_at: str = _BUILTIN_DATE

    def allows_loop(self, loop_name: str) -> bool:
        # "*" (or empty) means the agent may serve any loop.
        return (not self.allowed_loop_types
                or "*" in self.allowed_loop_types
                or loop_name in self.allowed_loop_types)


def validate_agent_definition(agent: AgentDefinition) -> List[str]:
    """Return a list of validation errors (empty list == valid)."""
    errors: List[str] = []
    if not agent.name or not isinstance(agent.name, str):
        errors.append("name must be a non-empty string")
    if not agent.role:
        errors.append("role is required")
    if not agent.default_model:
        errors.append("default_model is required")
    if not isinstance(agent.temperature, (int, float)) or not (0.0 <= agent.temperature <= 2.0):
        errors.append("temperature must be a number in [0.0, 2.0]")
    unknown = set(agent.allowed_tools) - SUPPORTED_TOOLS
    if unknown:
        errors.append(f"unknown tools not allowed: {sorted(unknown)}")
    if not isinstance(agent.allowed_loop_types, list):
        errors.append("allowed_loop_types must be a list")
    if not agent.system_prompt:
        errors.append("system_prompt is required")
    return errors


def load_builtin_agents() -> Dict[str, AgentDefinition]:
    agents = [
        AgentDefinition(
            name="supervisor",
            display_name="Supervisor",
            role="supervisor",
            description="Create plans, route work, enforce loop objectives, and decide next actions.",
            default_model=config.SUPERVISOR_MODEL,
            temperature=config.TEMPERATURE,
            system_prompt=prompts.SUPERVISOR_SYSTEM,
            allowed_loop_types=["*"],
            allowed_tools=[],
            output_contract="plan_text",
            safety_level="standard",
            tags=["core", "planning"],
        ),
        AgentDefinition(
            name="coder",
            display_name="Coder",
            role="coder",
            description="Generate structured file operations and command suggestions.",
            default_model=config.CODER_MODEL,
            temperature=config.TEMPERATURE,
            system_prompt=prompts.CODER_SYSTEM,
            allowed_loop_types=["*"],
            allowed_tools=["filesystem", "terminal"],
            output_contract="file_json",
            safety_level="standard",
            tags=["core", "coding"],
        ),
        AgentDefinition(
            name="reviewer",
            display_name="Reviewer",
            role="reviewer",
            description="Evaluate plans, code, files, command output, and stop conditions.",
            default_model=config.SUPERVISOR_MODEL,
            temperature=config.TEMPERATURE,
            system_prompt=prompts.REVIEWER_SYSTEM,
            allowed_loop_types=["*"],
            allowed_tools=[],
            output_contract="review_json",
            safety_level="standard",
            tags=["core", "review"],
        ),
        AgentDefinition(
            name="prompt_designer",
            display_name="Prompt Designer",
            role="coder",
            description="Generate high-quality reusable prompts.",
            default_model=config.SUPERVISOR_MODEL,
            temperature=config.TEMPERATURE,
            system_prompt=(
                "You are the Prompt Designer. You craft clear, structured, reusable "
                "prompts for AI agents and local models. You do not write code or "
                "files. You return STRICT JSON; put the final prompt in the "
                "\"summary\" field, with empty files and commands."
            ),
            allowed_loop_types=["prompt_design"],
            allowed_tools=[],
            output_contract="prompt_text",
            safety_level="read_only",
            tags=["design", "prompt"],
        ),
        AgentDefinition(
            name="loop_designer",
            display_name="Loop Designer",
            role="coder",
            description="Generate reusable loop definitions.",
            default_model=config.SUPERVISOR_MODEL,
            temperature=config.TEMPERATURE,
            system_prompt=(
                "You are the Loop Designer. You design reusable loop definitions for "
                "the Loop Engineering framework. You return STRICT JSON; put a complete "
                "loop definition JSON (as a string) in the \"summary\" field, with "
                "empty files and commands."
            ),
            allowed_loop_types=["loop_design"],
            allowed_tools=[],
            output_contract="loop_json",
            safety_level="read_only",
            tags=["design", "loop", "meta"],
        ),
        AgentDefinition(
            name="intake_analyst",
            display_name="Intake Analyst",
            role="analyst",
            description="Analyze raw user goals and convert them into structured executable loop tasks.",
            default_model=config.SUPERVISOR_MODEL,
            temperature=config.TEMPERATURE,
            system_prompt=(
                "You are the Intake Analyst. You analyze a raw user task, detect "
                "ambiguity, risk, and missing details, and return a STRICT JSON "
                "object describing a clarified, executable task or the clarification "
                "needed. You never write code, run commands, or take side effects."
            ),
            allowed_loop_types=["*"],
            allowed_tools=[],
            output_contract="intake_json",
            safety_level="read_only",
            tags=["intake", "clarification"],
        ),
        AgentDefinition(
            name="test_analyst",
            display_name="Test Analyst",
            role="analyst",
            description="Analyze command/test failures and propose fixes.",
            default_model=config.SUPERVISOR_MODEL,
            temperature=config.TEMPERATURE,
            system_prompt=(
                "You are the Test Analyst. You read test/command output, diagnose the "
                "root cause of failures, and propose concrete fixes. You are concise "
                "and evidence-driven."
            ),
            allowed_loop_types=["test_fix"],
            allowed_tools=["terminal"],
            output_contract="analysis_json",
            safety_level="standard",
            tags=["test", "analysis"],
        ),
    ]
    return {a.name: a for a in agents}


class AgentRegistry:
    def __init__(self, agents: Optional[Dict[str, AgentDefinition]] = None):
        self._agents: Dict[str, AgentDefinition] = {}
        for a in (agents or load_builtin_agents()).values():
            self.register(a)

    def register(self, agent: AgentDefinition) -> None:
        errors = validate_agent_definition(agent)
        if errors:
            raise ValueError(f"invalid agent '{agent.name}': {errors}")
        self._agents[agent.name] = agent

    def list_agents(self) -> List[AgentDefinition]:
        return sorted(self._agents.values(), key=lambda a: a.name)

    def get_agent(self, name: str) -> Optional[AgentDefinition]:
        return self._agents.get(name)

    def names(self) -> List[str]:
        return sorted(self._agents.keys())
