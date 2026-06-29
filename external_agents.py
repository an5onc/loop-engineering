"""External Coding Agent Adapters (Stage 3.0).

Lets the Loop Engine delegate the *implementation* step to an external terminal
coding agent (Claude Code, Codex) while the Supervisor, safety gates, memory,
reports, and approvals stay inside this framework.

Stage 3.0 is **handoff (manual) mode only**: the adapter generates a complete
handoff prompt, saves it under external_agent_handoffs/, prints terminal
instructions, and waits for the user to confirm completion. It never automates
the external tool, never edits files itself, and never bypasses workspace
safety — after confirmation the engine inspects the workspace and blocks
disallowed/protected changes.
"""

import datetime
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
HANDOFFS_DIR = os.path.realpath(os.path.join(PROJECT_ROOT, "external_agent_handoffs"))

SUPPORTED_MODES = ("handoff",)
_SECRET_MARKERS = ["-----BEGIN", "PRIVATE KEY", "password=", "secret=", "api_key="]


@dataclass
class ExternalAgentRequest:
    loop_id: Optional[int]
    attempt_number: int
    agent_name: str
    task: str
    plan: str
    workspace_name: str
    workspace_root: str
    allowed_write_paths: List[str]
    allowed_command_paths: List[str]
    context_summary: str = ""
    reviewer_feedback: str = ""
    test_analyst_feedback: str = ""
    max_duration_seconds: int = 1800
    dry_run: bool = True
    created_at: str = ""


@dataclass
class ExternalAgentResult:
    agent_name: str
    started: bool = False
    completed: bool = False
    success: bool = False
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    files_changed: List[str] = field(default_factory=list)
    commands_run: List[str] = field(default_factory=list)
    summary: str = ""
    error: str = ""
    created_at: str = ""


VALID_COMPLETION_STATUS = ("completed", "failed", "blocked", "partial")
_MAX_COMPLETION_BYTES = 200 * 1024


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


@dataclass
class ExternalAgentCompletion:
    agent_name: str = ""
    loop_id: Optional[int] = None
    attempt_number: int = 1
    status: str = "completed"
    summary: str = ""
    files_changed: List[str] = field(default_factory=list)
    commands_run: List[str] = field(default_factory=list)
    tests_run: List[str] = field(default_factory=list)
    tests_passed: Optional[bool] = None
    issues: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    raw_text: str = ""
    parsed: bool = False
    created_at: str = ""


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


def _as_list(v):
    if isinstance(v, list):
        return [str(x) for x in v]
    if v in (None, ""):
        return []
    return [str(v)]


def _as_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        if v.lower() in ("true", "yes", "1"):
            return True
        if v.lower() in ("false", "no", "0"):
            return False
    return None


def parse_completion_summary(text: str) -> ExternalAgentCompletion:
    """Parse a structured-JSON completion, falling back to raw text."""
    data = _extract_json(text)
    if data is not None:
        try:
            lid = int(data["loop_id"]) if data.get("loop_id") not in (None, "") else None
        except (ValueError, TypeError):
            lid = None
        try:
            att = int(data.get("attempt_number", 1) or 1)
        except (ValueError, TypeError):
            att = 1
        return ExternalAgentCompletion(
            agent_name=str(data.get("agent_name", "")), loop_id=lid,
            attempt_number=att, status=str(data.get("status", "completed")).lower(),
            summary=str(data.get("summary", "")),
            files_changed=_as_list(data.get("files_changed")),
            commands_run=_as_list(data.get("commands_run")),
            tests_run=_as_list(data.get("tests_run")),
            tests_passed=_as_bool(data.get("tests_passed")),
            issues=_as_list(data.get("issues")), notes=_as_list(data.get("notes")),
            next_steps=_as_list(data.get("next_steps")),
            raw_text=text or "", parsed=True, created_at=_now())
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    summary = " ".join(lines[:3])[:300] if lines else ""
    return ExternalAgentCompletion(
        status="completed", summary=summary, raw_text=text or "", parsed=False,
        created_at=_now())


def load_completion_file(path) -> ExternalAgentCompletion:
    """Read a completion file (user-provided, read-only, size-capped)."""
    real = os.path.realpath(os.path.expanduser(str(path)))
    if not os.path.isfile(real):
        raise ValueError(f"completion file not found: {path}")
    if os.path.getsize(real) > _MAX_COMPLETION_BYTES:
        raise ValueError("completion file too large (>200 KB)")
    with open(real, "r", encoding="utf-8", errors="replace") as fh:
        return parse_completion_summary(fh.read())


def validate_completion(completion: ExternalAgentCompletion) -> List[str]:
    """Return validation notes (empty == clean). A completion is always 'valid'
    for the gate because raw text is safely stored even when unparsed."""
    notes = []
    if completion is None:
        return ["no completion provided"]
    if completion.parsed and completion.status not in VALID_COMPLETION_STATUS:
        notes.append(f"unknown status {completion.status!r}")
    return notes


class ExternalAgentAdapter:
    name = "base"
    display_name = "External Agent"
    tool_command = "your-agent"

    def build_handoff(self, req: ExternalAgentRequest):
        """Return (prompt, safe, warnings). Includes NO file contents/secrets."""
        write = ", ".join(req.allowed_write_paths) or "(none)"
        cmd = ", ".join(req.allowed_command_paths) or "(none)"
        lines = [
            f"# External Coding Agent Handoff — {self.display_name}",
            "",
            f"Project workspace: {req.workspace_name}",
            f"Workspace root: {req.workspace_root}",
            f"Allowed write paths: {write}",
            f"Allowed command paths: {cmd}",
            f"Loop ID: {req.loop_id}",
            f"Attempt number: {req.attempt_number}",
            "",
            "## Task",
            req.task,
            "",
            "## Supervisor plan",
            req.plan or "(no plan)",
        ]
        if req.context_summary:
            lines += ["", "## Relevant context (summaries only — no file contents)",
                      req.context_summary]
        if req.reviewer_feedback:
            lines += ["", "## Reviewer feedback (from a previous attempt)",
                      req.reviewer_feedback]
        if req.test_analyst_feedback:
            lines += ["", "## Test analyst feedback", req.test_analyst_feedback]
        lines += [
            "",
            "## Safety rules (MANDATORY)",
            f"- Only edit files under the allowed write paths: {write}.",
            "- Do not edit files outside allowed paths.",
            "- Do not run unsafe commands (no rm, curl, sudo, git push, etc.).",
            f"- Only run commands inside: {cmd}.",
            "- Do not commit unless instructed.",
            "- Do not modify protected files (.git/, .env, secrets, keys, node_modules/).",
            "- Do not loosen safety systems.",
            "- Stop after verification.",
            "",
            "## What you may change",
            f"- Files under: {write}",
            "## What you may run",
            f"- Commands under: {cmd}",
            "",
            "## Completion checklist",
            "- [ ] Implemented the task within allowed write paths only.",
            "- [ ] Ran allowed verification (e.g. unit tests) if applicable.",
            "- [ ] Did not touch protected or out-of-scope files.",
            "- [ ] Did not commit.",
            "- [ ] Verified the change works, then stopped.",
            "",
            "## Completion Response JSON",
            "",
            "When finished, return this JSON exactly:",
            "",
            "{",
            f'  "agent_name": "{self.name}",',
            f'  "loop_id": {req.loop_id if req.loop_id is not None else "CURRENT_LOOP_ID"},',
            f'  "attempt_number": {req.attempt_number},',
            '  "status": "completed|failed|blocked",',
            '  "summary": "What you changed and why",',
            '  "files_changed": [],',
            '  "commands_run": [],',
            '  "tests_run": [],',
            '  "tests_passed": true,',
            '  "issues": [],',
            '  "notes": [],',
            '  "next_steps": []',
            "}",
            "",
            "## How to Resume This Loop",
            "",
            "After you finish, give the user the completion JSON above.",
            "",
            "Preferred command:",
            "",
            f"  python3 main.py --resume {req.loop_id if req.loop_id is not None else 'LOOP_ID'} "
            "--external-completion-file completion.json",
            "",
            "Backward-compatible command:",
            "",
            f"  python3 main.py --import-external-completion {req.loop_id if req.loop_id is not None else 'LOOP_ID'} "
            "--external-completion-file completion.json",
        ]
        prompt = "\n".join(lines)
        warnings = []
        safe = True
        low = prompt.lower()
        for m in _SECRET_MARKERS:
            if m.lower() in low:
                safe = False
                warnings.append(f"handoff prompt contained a secret marker: {m!r}")
        return prompt, safe, warnings

    def terminal_instructions(self, workspace_root: str) -> str:
        return (f"  cd {workspace_root}\n"
                f"  {self.tool_command}\n"
                "  # then paste the handoff prompt shown above")


class ClaudeCodeAdapter(ExternalAgentAdapter):
    name = "claude"
    display_name = "Claude Code"
    tool_command = "claude"


class CodexAdapter(ExternalAgentAdapter):
    name = "codex"
    display_name = "Codex"
    tool_command = "codex"


class ExternalAgentRegistry:
    def __init__(self):
        self._adapters = {a.name: a for a in (ClaudeCodeAdapter(), CodexAdapter())}

    def get(self, name):
        return self._adapters.get(name)

    def names(self):
        return sorted(self._adapters.keys())


def save_handoff(loop_id, attempt_number, agent_name, prompt) -> str:
    """Write the handoff prompt to a sandboxed internal path under HANDOFFS_DIR."""
    os.makedirs(HANDOFFS_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"loop_{int(loop_id or 0)}_attempt_{int(attempt_number)}_{agent_name}_{ts}.md"
    target = os.path.realpath(os.path.join(HANDOFFS_DIR, fname))
    base = os.path.realpath(HANDOFFS_DIR)
    if target != base and not target.startswith(base + os.sep):
        raise ValueError("handoff path escaped external_agent_handoffs/ (refusing)")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(prompt)
    return target


def prompt_hash(prompt) -> str:
    return hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()[:16]


def workspace_snapshot(ws) -> str:
    """Capture {relpath: content-hash} of the workspace write base at handoff
    time, so a later resume can compute only the external agent's deltas."""
    import filesystem
    snap = {}
    for rel in filesystem.list_files(ws):
        try:
            content = filesystem.read_file(rel, workspace=ws)
            snap[rel] = hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()[:16]
        except OSError:
            snap[rel] = "?"
    return json.dumps(snap)


def compute_external_deltas(snapshot_json, ws):
    """Compare the current workspace against a handoff snapshot.

    Returns dict with: changed (added/modified, non-generated), violations
    (sensitive paths among the deltas), deleted, ignored (generated artifacts).
    With no snapshot, falls back to classifying current files by sensitivity."""
    import filesystem
    import project_workspace as pw
    current = {}
    for rel in filesystem.list_files(ws):
        try:
            content = filesystem.read_file(rel, workspace=ws)
            current[rel] = hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()[:16]
        except OSError:
            current[rel] = "?"

    if snapshot_json:
        try:
            snap = json.loads(snapshot_json)
        except (json.JSONDecodeError, TypeError):
            snap = {}
        delta_paths = [p for p, h in current.items()
                       if p not in snap or snap[p] != h]
        deleted = [p for p in snap if p not in current]
    else:
        # No snapshot (legacy / in-run): treat all current files as candidates.
        delta_paths = list(current.keys())
        deleted = []

    changed, violations, ignored = [], [], []
    for p in delta_paths:
        if pw.is_sensitive_protected_path(p):
            violations.append(p)
        elif pw.is_generated_ignored_path(p):
            ignored.append(p)
        else:
            changed.append(p)
    return {"changed": changed, "violations": violations,
            "deleted": deleted, "ignored": ignored}


def format_completion_context(completion, inspection=None) -> str:
    """Build the EXTERNAL AGENT COMPLETION block for the Reviewer prompt."""
    if completion is None:
        return ""
    c = completion
    lines = [
        "EXTERNAL AGENT COMPLETION:",
        f"- Agent name: {c.agent_name or '(unknown)'}",
        f"- Status: {c.status}",
        f"- Summary: {c.summary or '(none)'}",
        f"- Files changed (claimed): {', '.join(c.files_changed) or '(none)'}",
        f"- Commands run (claimed): {', '.join(c.commands_run) or '(none)'}",
        f"- Tests run (claimed): {', '.join(c.tests_run) or '(none)'}",
        f"- Tests passed (claimed): {c.tests_passed}",
        f"- Issues: {', '.join(c.issues) or '(none)'}",
        f"- Notes: {', '.join(c.notes) or '(none)'}",
        f"- Next steps: {', '.join(c.next_steps) or '(none)'}",
        f"- Parsed as JSON: {c.parsed}",
    ]
    if inspection is not None:
        allowed = inspection.get("allowed_changed", [])
        disallowed = inspection.get("disallowed_changed", [])
        lines += [
            "",
            "FRAMEWORK WORKSPACE INSPECTION:",
            f"- Actual changed files (allowed): {', '.join(allowed) or '(none)'}",
            f"- Disallowed/protected changed files: {', '.join(disallowed) or '(none)'}",
        ]
    return "\n".join(lines)
