# Loop Engineering Agent Handoff

- Generated at: 2026-07-01T12:59:20
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

## Next Agent Checklist

1. Confirm `git status --short --branch`.
2. Run the verification commands above.
3. Inspect open project docs: `README.md`, `AGENTS.md`, and this handoff.
4. Continue from the latest pushed `main`; do not rely on local Codex memory.

