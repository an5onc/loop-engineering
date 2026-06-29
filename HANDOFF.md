# Loop Engineering Agent Handoff

- Generated at: 2026-06-29T15:05:28
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

## Next Agent Checklist

1. Confirm `git status --short --branch`.
2. Run the verification commands above.
3. Inspect open project docs: `README.md`, `AGENTS.md`, and this handoff.
4. Continue from the latest pushed `main`; do not rely on local Codex memory.

