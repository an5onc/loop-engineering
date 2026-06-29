"""Safe, narrow Git layer (Stage 1.5).

Only a fixed allowlist of read/commit operations is implemented. There is NO
generic "run any git command" entry point, so destructive operations (push,
pull, reset, checkout, clean, rm) simply do not exist here. Every call runs git
with shell=False from the project root.
"""

import subprocess
from dataclasses import dataclass
from typing import List, Optional

import config

# Note: git operations are run with cwd = the workspace root_path (passed in by
# the caller). add/diff are scoped to the workspace's allowed write paths.

GIT_TIMEOUT = 30  # seconds


@dataclass
class GitCommandResult:
    command: str
    exit_code: Optional[int]
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def _run_git(project_dir, args: List[str]) -> GitCommandResult:
    """Run `git <args>` from project_dir with no shell. Internal only."""
    cmd = ["git"] + args
    display = " ".join(cmd)
    try:
        proc = subprocess.run(
            cmd, cwd=str(project_dir), capture_output=True, text=True,
            shell=False, timeout=GIT_TIMEOUT,
        )
        return GitCommandResult(display, proc.returncode, proc.stdout, proc.stderr)
    except FileNotFoundError:
        return GitCommandResult(display, None, "", "git executable not found")
    except subprocess.TimeoutExpired:
        return GitCommandResult(display, None, "", "git command timed out")


def is_git_repo(project_dir) -> bool:
    r = _run_git(project_dir, ["rev-parse", "--is-inside-work-tree"])
    return r.exit_code == 0 and r.stdout.strip() == "true"


def git_status(project_dir) -> GitCommandResult:
    return _run_git(project_dir, ["status", "--short"])


def _write_paths(workspace) -> List[str]:
    if workspace is not None and getattr(workspace, "allowed_write_paths", None):
        return list(workspace.allowed_write_paths)
    return [config.WORKSPACE_DIR]


def git_diff(project_dir, workspace=None) -> GitCommandResult:
    args = ["diff", "--"] + [f"{p}/" for p in _write_paths(workspace)]
    return _run_git(project_dir, args)


def git_add_workspace(project_dir, workspace=None) -> GitCommandResult:
    # Only ever stages the allowed write paths — never the whole repo.
    args = ["add", "--"] + [f"{p}/" for p in _write_paths(workspace)]
    return _run_git(project_dir, args)


def git_commit(project_dir, message: str) -> GitCommandResult:
    # message is passed as a single argv element; shell=False means no injection.
    return _run_git(project_dir, ["commit", "-m", message])


def get_current_branch(project_dir) -> Optional[str]:
    r = _run_git(project_dir, ["branch", "--show-current"])
    if r.ok and r.stdout.strip():
        return r.stdout.strip()
    return None


def get_last_commit(project_dir) -> Optional[str]:
    r = _run_git(project_dir, ["rev-parse", "HEAD"])
    if r.ok and r.stdout.strip():
        return r.stdout.strip()
    return None


def workspace_has_changes(status_result: GitCommandResult, workspace=None) -> bool:
    """True if `git status --short` shows any path under an allowed write path."""
    prefixes = [f"{p}/" for p in _write_paths(workspace)]
    for line in (status_result.stdout or "").splitlines():
        # status --short lines look like "XY path" (or "?? path").
        path = line[3:] if len(line) > 3 else line
        if any(pre in line or path.startswith(pre) for pre in prefixes):
            return True
    return False
