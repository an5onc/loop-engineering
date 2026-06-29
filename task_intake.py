"""Task Intake & Clarification (Stage 2.9).

Analyzes a raw user task BEFORE any side effects: detects ambiguity/risk/missing
details and decides whether to proceed with a clarified task or ask the user for
clarification. Safety-critical decisions (clarification_required, risk_level,
recommended_next_action) are computed by deterministic heuristics so behavior is
predictable; the optional `intake_analyst` model only enriches natural-language
fields (clarified_task, intent_summary, question wording).
"""

import datetime
import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

VALID_LOOP_TYPES = ("code_build", "code_review", "test_fix", "prompt_design", "loop_design")

_CRITICAL_PHRASES = ["rm -rf", "delete all", "drop database", "drop table",
                     "wipe", "destroy everything", "force push", "force-push"]
_HIGH_WORDS = {"delete", "deploy", "publish", "release", "drop", "destroy",
               "commit", "push", "remove"}
_VAGUE_PHRASES = ["fix the app", "fix it", "make it better", "improve things",
                  "do stuff", "help me", "clean up", "optimize everything",
                  "make it work", "sort it out"]
_CONCRETE_HINTS = {"function", "module", "class", "test", "tests", "endpoint",
                   "feature", "file", "readme", "docs", "schema", "api", "calculator"}
_EXT_RE = re.compile(r"\b[\w/.-]+\.(py|ts|tsx|js|jsx|html|css|json|sql|md|toml|yml|yaml)\b")


@dataclass
class TaskIntakeRequest:
    raw_task: str
    loop_type: Optional[str] = None          # explicit --loop (or None)
    workspace_name: Optional[str] = None
    workspace_profile: Optional[str] = None
    template_name: Optional[str] = None
    rendered_task: Optional[str] = None
    available_loops: List[str] = field(default_factory=list)
    available_agents: List[str] = field(default_factory=list)
    project_context_available: bool = False
    memory_context_available: bool = False
    context_pack_available: bool = False
    created_at: str = ""


@dataclass
class TaskClarificationQuestion:
    id: str
    question: str
    reason: str
    required: bool = True
    suggested_answers: List[str] = field(default_factory=list)


@dataclass
class TaskIntakeResult:
    raw_task: str
    clarified_task: str
    intent_summary: str
    detected_loop_type: str
    confidence_score: float
    ambiguity_score: float
    risk_level: str
    missing_details: List[str]
    assumptions: List[str]
    clarification_required: bool
    clarification_questions: List[TaskClarificationQuestion]
    recommended_workspace: Optional[str] = None
    recommended_profile: Optional[str] = None
    recommended_template: Optional[str] = None
    recommended_next_action: str = "proceed"
    parse_ok: bool = True
    created_at: str = ""


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _detect_loop_type(task_l):
    if "review" in task_l:
        return "code_review"
    if any(w in task_l for w in ("loop definition", "design a loop", "reusable loop")):
        return "loop_design"
    if "prompt" in task_l:
        return "prompt_design"
    if any(w in task_l for w in ("bug", "test", "fix", "failing", "regression")):
        return "test_fix"
    return "code_build"


class TaskIntakeEngine:
    def __init__(self, conn=None):
        self.conn = conn

    def _heuristic(self, req: TaskIntakeRequest) -> TaskIntakeResult:
        raw = (req.raw_task or "").strip()
        task_l = raw.lower()
        words = [w for w in re.split(r"\s+", task_l) if w]

        has_ext = bool(_EXT_RE.search(raw))
        has_concrete = has_ext or any(h in task_l for h in _CONCRETE_HINTS)
        is_vague_phrase = any(p in task_l for p in _VAGUE_PHRASES)
        too_short = len(words) < 4

        # Risk.
        risk = "low"
        if any(p in task_l for p in _CRITICAL_PHRASES):
            risk = "critical"
        elif any(re.search(rf"\b{re.escape(w)}\b", task_l) for w in _HIGH_WORDS):
            risk = "high"

        detected = _detect_loop_type(task_l)

        missing, questions, assumptions = [], [], []

        # Ambiguity.
        vague = (is_vague_phrase or (too_short and not has_concrete)
                 or (not has_concrete and len(words) < 6))
        ambiguity = 0.85 if vague else (0.4 if not has_concrete else 0.15)
        confidence = round(1.0 - ambiguity, 2)

        clarify = vague
        if vague:
            missing.append("the task is too vague to execute safely")
            questions.append(TaskClarificationQuestion(
                "q1", "What specifically should be built or changed, and where?",
                "the task is too vague to execute safely", True, []))
        if not has_concrete and not vague:
            missing.append("target file(s)/module(s) are unclear")
            questions.append(TaskClarificationQuestion(
                "q2", "Which file(s) or module(s) should this affect?",
                "target files are unclear", True, []))
            clarify = True

        # Domain-specific missing details.
        if detected == "test_fix" and any(w in task_l for w in ("bug", "fix")) \
                and not any(w in task_l for w in ("reproduce", "steps", "when", "error")):
            missing.append("bug reproduction steps are missing")
        if detected == "code_build" and "feature" in task_l \
                and not any(w in task_l for w in ("accept", "criteria", "should")):
            missing.append("acceptance criteria are missing for the feature")
        if detected == "test_fix" and "test" in task_l and not has_concrete:
            missing.append("test target is unclear")

        if risk in ("high", "critical"):
            assumptions.append(f"task is {risk}-risk; safety/approval will gate side effects")

        clarified = raw
        if clarify:
            action = "ask_clarification"
        else:
            action = "proceed"
            assumptions.append("defaults are safe; proceeding inside the selected workspace")

        return TaskIntakeResult(
            raw_task=raw, clarified_task=clarified,
            intent_summary=f"Intent: {raw[:120]}",
            detected_loop_type=detected, confidence_score=confidence,
            ambiguity_score=ambiguity, risk_level=risk, missing_details=missing,
            assumptions=assumptions, clarification_required=clarify,
            clarification_questions=questions,
            recommended_workspace=req.workspace_name,
            recommended_profile=req.workspace_profile,
            recommended_template=req.template_name,
            recommended_next_action=action, parse_ok=True, created_at=_now())

    def analyze(self, req: TaskIntakeRequest, model=None, system="",
                generate_fn=None) -> TaskIntakeResult:
        """Heuristics are authoritative; the model only enriches text fields."""
        result = self._heuristic(req)
        if model and generate_fn:
            try:
                import prompts
                res = generate_fn(model, prompts.intake_prompt(req), system=system)
                data = _extract_json(res.text if hasattr(res, "text") else str(res))
                if data is None:
                    result.parse_ok = False
                else:
                    # Enrich text only (never relax safety decisions).
                    if data.get("clarified_task") and not result.clarification_required:
                        result.clarified_task = str(data["clarified_task"])
                    if data.get("intent_summary"):
                        result.intent_summary = str(data["intent_summary"])
                    if isinstance(data.get("assumptions"), list):
                        for a in data["assumptions"]:
                            if str(a) not in result.assumptions:
                                result.assumptions.append(str(a))
                    # NOTE: risk_level, clarification_required, and
                    # recommended_next_action stay heuristic-authoritative — the
                    # model never changes safety-critical decisions (avoids both
                    # false blocks and unsafe relaxation).
            except Exception:
                result.parse_ok = True  # model unavailable -> heuristic stands
        return result


def _extract_json(text):
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text or "", re.DOTALL)
    cand = m.group(1) if m else None
    if cand is None:
        s = (text or "").find("{")
        if s == -1:
            return None
        depth = 0
        for i in range(s, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    cand = text[s:i + 1]
                    break
    if cand is None:
        return None
    try:
        return json.loads(cand)
    except json.JSONDecodeError:
        return None
