# Loop Engineering Agent Contract

This repository is intended to move cleanly between agents and workstations.
Do not depend on local Codex memory, local SQLite state, ignored reports, or
absolute paths from another machine.

## Start Every Session

1. Run `git pull --ff-only`.
2. Read `HANDOFF.md`, `README.md`, and this file.
3. Run `python3 agent_handoff.py --check`.
4. Inspect `git status --short --branch` before editing.
5. Treat untracked runtime files, local reports, and `workspace/` smoke files as
   local-only unless the user explicitly asks to preserve them.

## Before Ending Work

1. Run the relevant tests for the change.
2. Run `python3 agent_handoff.py --write` if project state, verification, or
   next steps changed.
3. Commit only source, tests, docs, and portable handoff files.
4. Do not commit ignored runtime artifacts:
   - `loop_engineering.db`
   - generated report directories
   - external agent job folders
   - `__pycache__/`
5. Push `main` after verified commits so the next workstation can continue from
   the same state.

## Safety Rules

- Do not loosen filesystem, terminal, Git, approval, workspace, or external-agent
  safety gates.
- Do not commit secrets, protected file contents, local database snapshots, or
  generated handoff packets with protected context.
- Keep committed handoff text portable: use repo-relative paths and commands.
- If a generated command is only advisory, do not execute it unless the user
  explicitly asks.

## Verification Baseline

Use these as the minimum checks for handoff-system changes:

```bash
python3 -m py_compile *.py
python3 -m unittest test_agent_handoff.py
python3 audit_hotfix.py
```

Broader framework changes should also run the focused feature tests and the
Observatory regression suite documented in `README.md`.
