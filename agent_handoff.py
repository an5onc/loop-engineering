"""Portable agent-to-agent handoff generator for Loop Engineering.

The handoff file is intentionally repo-tracked text, not runtime database state.
It gives the next workstation or agent enough context to pull, verify, and keep
building without depending on local Codex memory, ignored reports, or absolute
machine paths.
"""

import argparse
import datetime
import os
import subprocess
from dataclasses import dataclass, field
from typing import List


REQUIRED_IGNORES = [
    "__pycache__/",
    "loop_engineering.db",
    "reports/",
    "external_agent_jobs/",
    "external_agent_handoffs/",
    "external_batch_reports/",
    "loop_improvement_reports/",
    "loop_improvement_review_reports/",
]

CORE_VERIFICATION = [
    "python3 -m py_compile *.py",
    "python3 audit_hotfix.py",
    "python3 -m unittest test_agent_handoff.py test_loop_improvement.py test_loop_improvement_review.py",
]


@dataclass
class HandoffCheckResult:
    ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def build_handoff(repo_root="."):
    repo_root = os.path.abspath(repo_root)
    remote = _git(repo_root, ["remote", "get-url", "origin"]) or "(no origin configured)"
    branch = _git(repo_root, ["branch", "--show-current"]) or "(unknown)"
    generated = datetime.datetime.now().isoformat(timespec="seconds")
    clone_target = remote if remote.startswith("http") or remote.startswith("git@") else "REMOTE_URL"
    lines = []
    a = lines.append
    a("# Loop Engineering Agent Handoff")
    a("")
    a(f"- Generated at: {generated}")
    a(f"- Branch: `{branch}`")
    a(f"- Remote: `{remote}`")
    a("")
    a("## Start Here")
    a("")
    a("```bash")
    a(f"git clone {clone_target}")
    a("cd loop-engineering")
    a("git checkout main")
    a("git pull --ff-only")
    a("python3 agent_handoff.py --check")
    a("```")
    a("")
    a("## Expected Clone State")
    a("")
    a("- After `git pull --ff-only`, `git status --short --branch` should show a clean `main` checkout.")
    a("- Source-machine local files are not part of the handoff unless committed and pushed.")
    a("- Local `workspace/` smoke files and generated reports are intentionally omitted from portable handoffs.")
    a("")
    a("## Verification Commands")
    a("")
    for cmd in CORE_VERIFICATION:
        a(f"- `{cmd}`")
    a("")
    a("## Agent Contract")
    a("")
    a("- Read `AGENTS.md` and this file before making changes.")
    a("- Run `git pull --ff-only` before continuing work on another workstation.")
    a("- Do not commit runtime artifacts, generated reports, local databases, or workspace smoke files.")
    a("- Keep handoffs portable: avoid absolute machine paths in committed handoff text.")
    a("- Before ending work, run `python3 agent_handoff.py --write` and commit the updated handoff if project state changed.")
    a("- Push `main` after verified commits so another agent can clone and continue from the same state.")
    a("")
    a("## Runtime Artifacts")
    a("")
    a("These are intentionally local-only and ignored:")
    for pattern in REQUIRED_IGNORES:
        a(f"- `{pattern}`")
    a("")
    a("## Next Agent Checklist")
    a("")
    a("1. Confirm `git status --short --branch`.")
    a("2. Run the verification commands above.")
    a("3. Inspect open project docs: `README.md`, `AGENTS.md`, and this handoff.")
    a("4. Continue from the latest pushed `main`; do not rely on local Codex memory.")
    a("")
    return "\n".join(lines)


def write_handoff(repo_root=".", path=None):
    repo_root = os.path.abspath(repo_root)
    target = path or os.path.join(repo_root, "HANDOFF.md")
    content = build_handoff(repo_root)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(content)
        fh.write("\n")
    return target


def check_handoff_system(repo_root="."):
    repo_root = os.path.abspath(repo_root)
    errors = []
    warnings = []
    if not os.path.isdir(os.path.join(repo_root, ".git")):
        errors.append("repo root does not contain .git")
    if not os.path.exists(os.path.join(repo_root, "AGENTS.md")):
        errors.append("AGENTS.md is missing")
    if not os.path.exists(os.path.join(repo_root, "HANDOFF.md")):
        warnings.append("HANDOFF.md is missing; run python3 agent_handoff.py --write")
    gitignore = _read(os.path.join(repo_root, ".gitignore"))
    for pattern in REQUIRED_IGNORES:
        if pattern not in gitignore:
            errors.append(f".gitignore missing runtime artifact pattern: {pattern}")
    remote = _git(repo_root, ["remote", "get-url", "origin"])
    if not remote:
        errors.append("origin remote is not configured")
    branch = _git(repo_root, ["branch", "--show-current"])
    if branch != "main":
        warnings.append(f"current branch is {branch or '(unknown)'}, expected main")
    return HandoffCheckResult(ok=not errors, errors=errors, warnings=warnings)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate or check agent handoff state.")
    parser.add_argument("--write", action="store_true", help="write HANDOFF.md")
    parser.add_argument("--check", action="store_true", help="check handoff readiness")
    parser.add_argument("--path", default=None, help="handoff path for --write")
    args = parser.parse_args(argv)
    if args.write:
        target = write_handoff(".", args.path)
        print(f"wrote {target}")
        return 0
    if args.check:
        result = check_handoff_system(".")
        for warning in result.warnings:
            print(f"WARNING: {warning}")
        for error in result.errors:
            print(f"ERROR: {error}")
        print("handoff check: PASS" if result.ok else "handoff check: FAIL")
        return 0 if result.ok else 1
    print(build_handoff("."))
    return 0


def _git(cwd, args):
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
