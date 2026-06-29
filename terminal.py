"""Restricted command execution, confined to the workspace.

Safety model:
  - Allowlist of command families (python, python3, pytest, ls, cat, pwd).
  - Explicit blocklist of dangerous families for clear error messages.
  - No shell: commands run with shell=False (no operator interpretation).
  - Shell operators (; && || | > >> < $() ` newline) are rejected outright.
  - Arguments may not reference paths outside the workspace (.., absolute, ~,
    null bytes).
  - cwd is forced to stay inside the workspace.
  - Every command has a wall-clock timeout.
"""

import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import config
import filesystem
import project_workspace

_WS_MANAGER = project_workspace.WorkspaceManager()

# Command families that may run.
ALLOWED_FAMILIES = {"python", "python3", "pytest", "ls", "cat", "pwd"}

# Families we explicitly name as blocked (for friendly reasons). Anything not in
# ALLOWED_FAMILIES is blocked regardless; this set just improves the message.
BLOCKED_FAMILIES = {
    "rm", "mv", "cp", "chmod", "chown", "sudo", "curl", "wget", "git", "pip",
    "pip3", "npm", "pnpm", "yarn", "brew", "docker", "open", "osascript", "ssh",
    "scp", "rsync", "find", "xargs", "sed", "awk", "perl", "ruby", "node",
    "bash", "sh", "zsh",
}

# Substrings that indicate shell metacharacters / chaining.
SHELL_OPERATORS = [";", "&&", "||", "|", ">>", ">", "<", "$(", "`", "\n", "\r", "&"]

# Only these `python -m <module>` modules may run (no http.server, pip, venv...).
SAFE_PY_MODULES = {"unittest", "pytest"}


@dataclass
class CommandResult:
    command: str
    allowed: bool
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False
    reason_if_blocked: str = ""

    @property
    def succeeded(self) -> bool:
        return self.allowed and not self.timed_out and self.exit_code == 0


def _arg_is_unsafe(arg: str) -> Optional[str]:
    """Return a reason string if an argument references an unsafe path."""
    if "\x00" in arg:
        return "null byte in argument"
    if ".." in arg.split("/") or ".." in arg.split(os.sep) or "/../" in arg or arg.startswith("../") or arg == "..":
        return "'..' path traversal in argument"
    if arg.startswith("~"):
        return "'~' home path in argument"
    if os.path.isabs(arg):
        return "absolute path in argument"
    return None


def _validate_python_invocation(args: List[str]) -> Optional[str]:
    """Whitelist safe `python`/`python3` forms. Blocks inline code (-c), stdin,
    risky -m modules, and the bare REPL. Returns a reason string if blocked."""
    if not args:
        return "python REPL/stdin is not allowed; run a .py script or -m unittest/pytest"
    a0 = args[0]
    if a0 in ("-V", "--version"):
        return None
    if a0 == "-m":
        if len(args) < 2:
            return "python -m requires a module"
        mod = args[1]
        if mod not in SAFE_PY_MODULES:
            return (f"python -m {mod!r} not allowed "
                    f"(only {sorted(SAFE_PY_MODULES)})")
        return None
    if a0 == "-c" or a0 == "-" or a0.startswith("-c") or a0.startswith("-"):
        return f"python inline/flag form not allowed: {a0!r} (no -c, no stdin)"
    if not a0.endswith(".py"):
        return f"python target must be a .py script inside the workspace: {a0!r}"
    return None


def _safety_check(command: str) -> Tuple[bool, str, List[str]]:
    """Return (allowed, reason, tokens)."""
    if command is None or command.strip() == "":
        return False, "empty command", []

    # Shell operators / chaining.
    for op in SHELL_OPERATORS:
        if op in command:
            label = "newline" if op in ("\n", "\r") else op
            return False, f"shell operator not allowed: {label!r}", []

    # Tokenize without a shell.
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return False, f"could not parse command: {exc}", []
    if not tokens:
        return False, "empty command", []

    base = os.path.basename(tokens[0])

    if base in BLOCKED_FAMILIES:
        return False, f"blocked command family: {base!r}", tokens
    if base not in ALLOWED_FAMILIES:
        return False, f"command not in allowlist: {base!r}", tokens

    # Python: only allow safe invocation forms (no inline code / stdin / risky -m).
    if base in ("python", "python3"):
        preason = _validate_python_invocation(tokens[1:])
        if preason:
            return False, preason, tokens

    # Validate every argument's paths (abs / .. / ~ / null).
    for arg in tokens[1:]:
        reason = _arg_is_unsafe(arg)
        if reason:
            return False, f"{reason}: {arg!r}", tokens

    return True, "", tokens


def is_safe_command(command: str) -> bool:
    """Public boolean check used by callers and tests."""
    allowed, _reason, _tokens = _safety_check(command)
    return allowed


def _cwd_allowed(cwd, workspace) -> bool:
    if workspace is not None:
        return _WS_MANAGER.is_path_allowed_for_command(workspace, str(cwd))
    base = filesystem.workspace_dir()
    real = os.path.realpath(str(cwd))
    return real == base or real.startswith(base + os.sep)


def run_command(command: str, cwd, timeout_seconds: int = None, workspace=None) -> CommandResult:
    """Run a single command safely inside `cwd` (an allowed command path)."""
    if timeout_seconds is None:
        timeout_seconds = config.COMMAND_TIMEOUT

    allowed, reason, tokens = _safety_check(command)
    if not allowed:
        return CommandResult(command=command, allowed=False, reason_if_blocked=reason)

    if not _cwd_allowed(cwd, workspace):
        return CommandResult(
            command=command, allowed=False,
            reason_if_blocked=f"outside allowed command path: {cwd}",
        )

    # Resolve `python`/`python3` to the running interpreter so the allowlisted
    # interpreter runs regardless of which alias exists on this machine's PATH.
    if os.path.basename(tokens[0]) in ("python", "python3"):
        tokens = [sys.executable] + tokens[1:]

    start = time.perf_counter()
    try:
        proc = subprocess.run(
            tokens,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
            env={"PATH": os.environ.get("PATH", ""), "HOME": str(cwd)},
        )
        duration = time.perf_counter() - start
        return CommandResult(
            command=command, allowed=True, exit_code=proc.returncode,
            stdout=proc.stdout, stderr=proc.stderr,
            duration_seconds=duration, timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.perf_counter() - start
        return CommandResult(
            command=command, allowed=True, exit_code=None,
            stdout=exc.stdout or "" if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr or "" if isinstance(exc.stderr, str) else ""),
            duration_seconds=duration, timed_out=True,
            reason_if_blocked="",
        )
    except (OSError, ValueError) as exc:
        duration = time.perf_counter() - start
        return CommandResult(
            command=command, allowed=True, exit_code=None,
            stderr=f"execution error: {exc}",
            duration_seconds=duration, timed_out=False,
        )


def run_suggested_commands(commands: List[str], cwd, workspace=None) -> List[CommandResult]:
    """Run a list of suggested commands, honoring the MAX_COMMANDS cap."""
    results: List[CommandResult] = []
    for command in (commands or [])[: config.MAX_COMMANDS]:
        results.append(run_command(command, cwd, workspace=workspace))
    return results
