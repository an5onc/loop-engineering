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
    "multi_project_observatory_reports/",
    "cross_project_handoff_packets/",
    "multi_project_audit_reports/",
    "multi_project_stage7_audit_reports/",
    "governance_policy_evaluation_reports/",
    "fleet_governance_reports/",
    "governance_trend_reports/",
    "governance_evidence_exports/",
    "multi_project_governance_audit_reports/",
    "multi_project_stage8_audit_reports/",
    "cross_project_execution_readiness_reports/",
    "cross_project_execution_handoff_packets/",
    "cross_project_execution_audit_reports/",
    "cross_project_stage9_audit_reports/",
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
    a("## Multi-Project Operations (Stage 7)")
    a("")
    a("Loop Engineering can register and operate across multiple projects. This")
    a("layer is metadata-only and fail-closed: it performs no hidden writes, no")
    a("hidden command/model execution, and no cross-project mutation without an")
    a("explicit approved approval.")
    a("")
    a("- Register / inspect: `--register-project KEY --root PATH`, `--projects`, `--project KEY`")
    a("- Validate: `--validate-projects`, `--project-validation-reports`")
    a("- Observe (read-only): `--multi-project-observatory [--save-report]`")
    a("- Plan -> approve -> handoff/schedule:")
    a("  `--plan-cross-project-work \"TASK\"` -> `--request-cross-project-approval PLAN_ID`")
    a("  -> `--set-cross-project-approval APPROVAL_ID approved`")
    a("  -> `--handoff-cross-project-plan PLAN_ID --approval APPROVAL_ID`")
    a("  -> `--schedule-cross-project-plan PLAN_ID --approval APPROVAL_ID --window manual`")
    a("- Audit: `--multi-project-audit`, `--multi-project-stage7-audit [--save-report]`")
    a("- A handoff or schedule is created only when a valid approved approval exists.")
    a("")
    a("## Governance & Fleet Reporting (Stage 8)")
    a("")
    a("Stage 8 adds metadata-only governance on top of the registry: fleet policies,")
    a("deterministic evaluation into findings, a review queue, finding-based waivers")
    a("(with owner + expiry; expired waivers stop suppressing), trends, an action")
    a("planner (advisory text only), evidence export, and Stage 8 audits.")
    a("")
    a("- Policies: `--create-governance-policy --default`, `--governance-policies`")
    a("- Evaluate: `--evaluate-governance-policies [--save-report]` -> findings")
    a("- Triage: `--create-governance-review-items EVALUATION_ID`, `--governance-review-items`")
    a("- Waivers (fail-closed): `--create-governance-waiver FINDING_ID --owner O --reason \"...\" --expiry-days N`")
    a("- Fleet / trends / evidence: `--fleet-governance-report`, `--governance-trends`, `--export-governance-evidence`")
    a("- Audit: `--multi-project-governance-audit`, `--multi-project-stage8-audit [--save-report]`")
    a("- No cross-project execution, no hidden command/model runs, no project-root writes.")
    a("")
    a("## Controlled Cross-Project Execution Planning (Stage 9)")
    a("")
    a("Stage 9 turns approved-looking cross-project intent into deterministic")
    a("execution readiness reports, execution plans, advisory command proposals,")
    a("dry-runs, approval requests, portable handoff packets, and audits. It is")
    a("still planning-only: no commands are run and no project roots are written.")
    a("")
    a("- Intent: `--create-cross-project-execution-intent --source-type TYPE --source-id ID --title \"...\" --owner \"...\"`")
    a("- Readiness: `--cross-project-execution-readiness INTENT_ID [--save-report]`")
    a("- Plan: `--plan-cross-project-execution INTENT_ID --readiness REPORT_ID`")
    a("- Advisory commands: `--propose-cross-project-execution-commands PLAN_ID`")
    a("- Dry-run / approval: `--dry-run-cross-project-execution PLAN_ID` -> `--request-cross-project-execution-approval PLAN_ID --dry-run DRY_RUN_ID`")
    a("- Handoff: `--handoff-cross-project-execution PLAN_ID --approval APPROVAL_ID`")
    a("- Audit: `--cross-project-execution-audit`, `--cross-project-stage9-audit [--save-report]`")
    a("- No hidden command/model runs, no project-root writes, no external jobs, no auto-commit.")
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
