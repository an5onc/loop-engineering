# Loop Engineering Agent Handoff

- Generated at: 2026-07-01T15:34:37
- Branch: `main`
- Remote: `https://github.com/an5onc/loop-engineering.git`

## Start Here

```bash
git clone https://github.com/an5onc/loop-engineering.git
cd loop-engineering
git checkout main
git pull --ff-only
python3 agent_handoff.py --check
```

## Expected Clone State

- After `git pull --ff-only`, `git status --short --branch` should show a clean `main` checkout.
- Source-machine local files are not part of the handoff unless committed and pushed.
- Local `workspace/` smoke files and generated reports are intentionally omitted from portable handoffs.

## Verification Commands

- `python3 -m py_compile *.py`
- `python3 audit_hotfix.py`
- `python3 -m unittest test_agent_handoff.py test_loop_improvement.py test_loop_improvement_review.py`

## Agent Contract

- Read `AGENTS.md` and this file before making changes.
- Run `git pull --ff-only` before continuing work on another workstation.
- Do not commit runtime artifacts, generated reports, local databases, or workspace smoke files.
- Keep handoffs portable: avoid absolute machine paths in committed handoff text.
- Before ending work, run `python3 agent_handoff.py --write` and commit the updated handoff if project state changed.
- Push `main` after verified commits so another agent can clone and continue from the same state.

## Runtime Artifacts

These are intentionally local-only and ignored:
- `__pycache__/`
- `loop_engineering.db`
- `reports/`
- `external_agent_jobs/`
- `external_agent_handoffs/`
- `external_batch_reports/`
- `loop_improvement_reports/`
- `loop_improvement_review_reports/`
- `multi_project_observatory_reports/`
- `cross_project_handoff_packets/`
- `multi_project_audit_reports/`
- `multi_project_stage7_audit_reports/`
- `governance_policy_evaluation_reports/`
- `fleet_governance_reports/`
- `governance_trend_reports/`
- `governance_evidence_exports/`
- `multi_project_governance_audit_reports/`
- `multi_project_stage8_audit_reports/`
- `cross_project_execution_readiness_reports/`
- `cross_project_execution_handoff_packets/`
- `cross_project_execution_audit_reports/`
- `cross_project_stage9_audit_reports/`
- `cross_project_execution_snapshot_reports/`
- `cross_project_execution_runtime_reports/`
- `cross_project_stage10_audit_reports/`
- `cross_project_orchestration_reports/`
- `cross_project_orchestration_audit_reports/`
- `cross_project_stage11_audit_reports/`

## Multi-Project Operations (Stage 7)

Loop Engineering can register and operate across multiple projects. This
layer is metadata-only and fail-closed: it performs no hidden writes, no
hidden command/model execution, and no cross-project mutation without an
explicit approved approval.

- Register / inspect: `--register-project KEY --root PATH`, `--projects`, `--project KEY`
- Validate: `--validate-projects`, `--project-validation-reports`
- Observe (read-only): `--multi-project-observatory [--save-report]`
- Plan -> approve -> handoff/schedule:
  `--plan-cross-project-work "TASK"` -> `--request-cross-project-approval PLAN_ID`
  -> `--set-cross-project-approval APPROVAL_ID approved`
  -> `--handoff-cross-project-plan PLAN_ID --approval APPROVAL_ID`
  -> `--schedule-cross-project-plan PLAN_ID --approval APPROVAL_ID --window manual`
- Audit: `--multi-project-audit`, `--multi-project-stage7-audit [--save-report]`
- A handoff or schedule is created only when a valid approved approval exists.

## Governance & Fleet Reporting (Stage 8)

Stage 8 adds metadata-only governance on top of the registry: fleet policies,
deterministic evaluation into findings, a review queue, finding-based waivers
(with owner + expiry; expired waivers stop suppressing), trends, an action
planner (advisory text only), evidence export, and Stage 8 audits.

- Policies: `--create-governance-policy --default`, `--governance-policies`
- Evaluate: `--evaluate-governance-policies [--save-report]` -> findings
- Triage: `--create-governance-review-items EVALUATION_ID`, `--governance-review-items`
- Waivers (fail-closed): `--create-governance-waiver FINDING_ID --owner O --reason "..." --expiry-days N`
- Fleet / trends / evidence: `--fleet-governance-report`, `--governance-trends`, `--export-governance-evidence`
- Audit: `--multi-project-governance-audit`, `--multi-project-stage8-audit [--save-report]`
- No cross-project execution, no hidden command/model runs, no project-root writes.

## Controlled Cross-Project Execution Planning (Stage 9)

Stage 9 turns approved-looking cross-project intent into deterministic
execution readiness reports, execution plans, advisory command proposals,
dry-runs, approval requests, portable handoff packets, and audits. It is
still planning-only: no commands are run and no project roots are written.

- Intent: `--create-cross-project-execution-intent --source-type TYPE --source-id ID --title "..." --owner "..."`
- Readiness: `--cross-project-execution-readiness INTENT_ID [--save-report]`
- Plan: `--plan-cross-project-execution INTENT_ID --readiness REPORT_ID`
- Advisory commands: `--propose-cross-project-execution-commands PLAN_ID`
- Dry-run / approval: `--dry-run-cross-project-execution PLAN_ID` -> `--request-cross-project-execution-approval PLAN_ID --dry-run DRY_RUN_ID`
- Handoff: `--handoff-cross-project-execution PLAN_ID --approval APPROVAL_ID`
- Audit: `--cross-project-execution-audit`, `--cross-project-stage9-audit [--save-report]`
- No hidden command/model runs, no project-root writes, no external jobs, no auto-commit.

## Controlled Cross-Project Execution (Stage 10)

Stage 10 can execute exactly one confirmed cross-project command at a time.
It requires a Stage 9 plan, latest passing dry-run, approved Stage 9
approval, matching handoff, Stage 10 confirmation, rollback snapshot, and
explicit `--confirm-execution`.

- Session: `--prepare-cross-project-execution PLAN_ID --approval APPROVAL_ID`
- Scope: `--resolve-cross-project-execution-scope SESSION_ID`
- Confirmation: `--request-cross-project-execution-confirmation SESSION_ID --step STEP_ID --command PROPOSAL_ID` -> `--set-cross-project-execution-confirmation CONFIRMATION_ID approved`
- Snapshot: `--snapshot-cross-project-execution SESSION_ID --confirmation CONFIRMATION_ID`
- Execute: `--execute-cross-project-command SESSION_ID --confirmation CONFIRMATION_ID --snapshot SNAPSHOT_ID --confirm-execution`
- Verify/outcome/audit: `--verify-cross-project-execution ATTEMPT_ID` -> `--record-cross-project-execution-outcome ATTEMPT_ID` -> `--cross-project-stage10-audit`
- Execution uses `terminal.run_command`; no alternate subprocess path, hidden model call, external job, auto-commit, push, branch creation, or batch execution.

## Controlled Multi-Step Orchestration (Stage 11)

Stage 11 coordinates multiple Stage 10 single-step executions while keeping
Stage 10 as the only runtime execution layer. It adds orchestration plans,
dry-runs, runs, step controls, one-step advancement, verification binding,
rollback status, reports, and audits.

- Plan/dry-run/run: `--plan-cross-project-orchestration SESSION_ID` -> `--dry-run-cross-project-orchestration PLAN_ID` -> `--start-cross-project-orchestration PLAN_ID --dry-run DRY_RUN_ID`
- Controls: `--cross-project-orchestration-step-controls RUN_ID --step STEP_ID`
- Advance one step: `--advance-cross-project-orchestration RUN_ID --step STEP_ID --confirmation CONFIRMATION_ID --snapshot SNAPSHOT_ID --confirm-execution`
- Verify/report/audit: `--verify-cross-project-orchestration-step RUN_ID --step STEP_ID` -> `--cross-project-orchestration-report RUN_ID` -> `--cross-project-stage11-audit`
- No parallel execution, automatic retry, automatic rollback, Git mutation, external job, hidden model call, or broader command allowlist.

## Next Agent Checklist

1. Confirm `git status --short --branch`.
2. Run the verification commands above.
3. Inspect open project docs: `README.md`, `AGENTS.md`, and this handoff.
4. Continue from the latest pushed `main`; do not rely on local Codex memory.

