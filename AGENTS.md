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

## Multi-Project Operations (Stage 7)

Loop Engineering can register and coordinate work across multiple projects. The
entire layer is metadata-only and fail-closed.

- Registry / validation / observatory are read-only over metadata; they never
  read project file contents, run commands, or call a model.
- A cross-project handoff or schedule is produced **only** when a valid
  `approved` approval that references the same plan exists.
- Nothing in Stage 7 performs cross-project writes, hidden command execution,
  hidden model calls, or auto-run; suggested commands are emitted as text for a
  human to run manually.
- Typical flow:
  `--register-project KEY --root PATH` → `--validate-projects`
  → `--multi-project-observatory` → `--plan-cross-project-work "TASK"`
  → `--request-cross-project-approval PLAN_ID`
  → `--set-cross-project-approval APPROVAL_ID approved`
  → `--handoff-cross-project-plan PLAN_ID --approval APPROVAL_ID`
  → (optional) `--schedule-cross-project-plan PLAN_ID --approval APPROVAL_ID --window manual`
  → `--multi-project-audit` / `--multi-project-stage7-audit`.
- Stage 7 generated reports/packets are ignored runtime artifacts (see
  `.gitignore`): `multi_project_observatory_reports/`,
  `cross_project_handoff_packets/`, `multi_project_audit_reports/`,
  `multi_project_stage7_audit_reports/`.

## Governance & Fleet Reporting (Stage 8)

Stage 8 adds a governance layer on top of the Stage 7 registry. Metadata-only,
fail-closed, and no cross-project execution.

- Policies are named sets of deterministic rules from a fixed `RULE_REGISTRY`
  (fleet rules: required validation, staleness, blocked handling, approval
  freshness, handoff/schedule integrity, audit recency). No expression language.
- Evaluation reads registry/validation/plan/approval/handoff/schedule/audit
  metadata only — never project file contents — and produces findings.
- A finding-based **waiver** (with owner + expiry) suppresses a matching finding
  only while it is `active` and unexpired; expired/revoked waivers never suppress.
- Review queue, trends, action planner (advisory text only), evidence export
  (excludes secrets/contents/DB snapshots), and audits are all read-only.
- Typical flow:
  `--create-governance-policy --default` → `--evaluate-governance-policies`
  → `--create-governance-review-items EVALUATION_ID`
  → `--create-governance-waiver FINDING_ID --owner O --reason "..." --expiry-days N`
  → `--fleet-governance-report` → `--governance-trends`
  → `--plan-governance-actions` → `--export-governance-evidence`
  → `--multi-project-governance-audit` → `--multi-project-stage8-audit`.
- Stage 8 generated reports are ignored runtime artifacts (see `.gitignore`):
  `governance_policy_evaluation_reports/`, `fleet_governance_reports/`,
  `governance_trend_reports/`, `governance_evidence_exports/`,
  `multi_project_governance_audit_reports/`,
  `multi_project_stage8_audit_reports/`.

## Controlled Cross-Project Execution Planning (Stage 9)

Stage 9 plans cross-project execution but still does not execute it. The layer
is metadata-only until a later explicitly approved execution stage.

- Intents, readiness reports, execution plans, command proposals, dry-runs,
  approvals, handoff packets, and audits never run commands, call models, create
  loops/jobs, auto-commit, or write registered project roots.
- Generated command proposals are advisory text only. If a generated command is
  only advisory, do not execute it unless the user explicitly asks.
- A Stage 9 approval request is allowed only after a passing dry-run, and an
  execution handoff is allowed only when an `approved` approval references the
  same plan and dry-run.
- Typical flow:
  `--create-cross-project-execution-intent --source-type TYPE --source-id ID --title "..."`
  → `--cross-project-execution-readiness INTENT_ID`
  → `--plan-cross-project-execution INTENT_ID --readiness REPORT_ID`
  → `--propose-cross-project-execution-commands PLAN_ID`
  → `--dry-run-cross-project-execution PLAN_ID`
  → `--request-cross-project-execution-approval PLAN_ID --dry-run DRY_RUN_ID`
  → `--set-cross-project-execution-approval APPROVAL_ID approved`
  → `--handoff-cross-project-execution PLAN_ID --approval APPROVAL_ID`
  → `--cross-project-execution-audit` / `--cross-project-stage9-audit`.
- Stage 9 generated reports/packets are ignored runtime artifacts (see
  `.gitignore`): `cross_project_execution_readiness_reports/`,
  `cross_project_execution_handoff_packets/`,
  `cross_project_execution_audit_reports/`,
  `cross_project_stage9_audit_reports/`.

## Controlled Cross-Project Execution (Stage 10)

Stage 10 is the first cross-project layer that can execute a command, but only
one explicitly confirmed project step at a time.

- Execution requires a Stage 9 plan, latest passing dry-run, approved Stage 9
  approval, matching handoff, Stage 10 confirmation, rollback snapshot, and
  explicit `--confirm-execution`.
- Commands must route through `terminal.run_command`; do not add alternate
  subprocess paths for Stage 10 execution.
- Stage 10 writes only Stage 10 metadata tables and optional ignored reports. It
  must not write loop `command_results`, create loops, create external jobs,
  auto-commit, push, create branches, call Ollama, or execute batches.
- Rollback restore requires preview plus explicit `--confirm-restore` and may
  restore only files captured in the snapshot.
- Typical flow:
  `--prepare-cross-project-execution PLAN_ID --approval APPROVAL_ID`
  → `--resolve-cross-project-execution-scope SESSION_ID`
  → `--request-cross-project-execution-confirmation SESSION_ID --step STEP_ID --command PROPOSAL_ID`
  → `--set-cross-project-execution-confirmation CONFIRMATION_ID approved`
  → `--snapshot-cross-project-execution SESSION_ID --confirmation CONFIRMATION_ID`
  → `--execute-cross-project-command SESSION_ID --confirmation CONFIRMATION_ID --snapshot SNAPSHOT_ID --confirm-execution`
  → `--verify-cross-project-execution ATTEMPT_ID`
  → `--record-cross-project-execution-outcome ATTEMPT_ID`
  → `--cross-project-runtime-audit` / `--cross-project-stage10-audit`.
- Stage 10 generated reports are ignored runtime artifacts:
  `cross_project_execution_snapshot_reports/`,
  `cross_project_execution_runtime_reports/`,
  `cross_project_stage10_audit_reports/`.


<claude-mem-context>
# Memory Context

# [loop-engineering] recent context, 2026-06-30 8:28am MDT

Legend: 🎯session 🔴bugfix 🟣feature 🔄refactor ✅change 🔵discovery ⚖️decision 🚨security_alert 🔐security_note
Format: ID TIME TYPE TITLE
Fetch details: get_observations([IDs]) | Search: mem-search skill

Stats: 50 obs (23,001t read) | 1,310,859t work | 98% savings

### Jun 27, 2026
S135 Complete comprehensive re-audit of Stage 3.2.1/3.2.2 hotfixes in isolated environment, verifying all four prior warnings are fixed and no security regressions introduced; confirm system ready for Stage 3.3. (Jun 27 at 4:48 PM)
S136 Build and verify Stage 3.3 (External Agent Job Packets) — subsystem for creating, storing, validating, and resuming external agent handoffs with full safety checks and database persistence. (Jun 27 at 4:48 PM)
S137 Complete Stage 3.4 external agent job queue with priority/labels/notes metadata, archive/unarchive lifecycle, and defensive type safety for migrated SQLite columns (Jun 27 at 5:07 PM)
S138 Build Stage 3.5 — External Agent Job Dashboard & Triage layer for Loop Engineering framework; verify all functionality and safety constraints. (Jun 27 at 5:36 PM)
1539 5:39p 🔵 Loop Engineering framework includes external dashboard and job management system
1540 5:40p 🔵 Dashboard operates in DB-only mode independent of Ollama availability
1541 " 🟣 Stage 3.5 — External Agent Job Dashboard with triage filters
1542 " 🔵 Dashboard implementation complete; all compilation, audit, and rendering tests pass
S139 Verify and document completion of Stage 3.6 — External Agent Completion Inbox System: a file-drop workflow enabling external agents to complete jobs by dropping completion.json or completion.txt into job directories, followed by sync commands to import and resume. (Jun 27 at 5:40 PM)
1543 5:41p ✅ Infrastructure for external completion inbox added to database schema
1544 5:43p 🟣 Stage 3.6 — External Agent Completion Inbox implemented
1545 " ✅ External completion inbox integrated into quality gate system
1546 " ✅ External completion inbox stop condition added to stop-conditions registry
1547 5:44p 🟣 External completion inbox CLI commands integrated into main.py
1548 " 🟣 External completion inbox commands wired into main() dispatcher
S140 Build and validate external job batch operations for Loop Engineering framework Stage 1.2, including proper error handling, event recording, and audit trails (Jun 27 at 5:48 PM)
S141 Continuation of Loop Engineering Stage 1 development: Validate completion of Stage 3.7 External Agent Batch Operations feature after comprehensive testing in prior session (Jun 27 at 5:56 PM)
S142 Complete Stage 3.8 External Agent Batch Reports: verify implementation, document feature in README, run final regression and safety tests. (Jun 27 at 5:58 PM)
S143 Perform final Stage 4 audit of Loop Engineering Observatory subsystem (stages 4.0–4.9) to verify stability, safety, completeness, and Stage 5 readiness. Independent verification across 11 subsystems without implementing new features, committing changes, or executing suggested remediation commands. (Jun 27 at 6:06 PM)
1592 6:13p 🔵 Existing code structure reviewed for Stage 3.9 integration points
1593 " 🟣 Added external_job_health_events database table to schema
1594 6:14p 🟣 Added database functions for external job health event persistence
1596 9:55p 🟣 Observatory Trend Analysis Engine (Stage 4.2)
1597 10:04p 🟣 Observatory Failure Drilldown (Stage 4.3) — Complete Implementation
1598 10:36p 🟣 Observatory Remediation Plans (Stage 4.4) — Turn findings into structured improvement plans
### Jun 28, 2026
1600 9:09p 🟣 Stage 4.6 Observatory Action Review implemented
1601 9:45p 🟣 Observatory Action Execution Handoff (Stage 4.7) - Complete Implementation
1602 9:55p 🟣 Stage 4.8 — Observatory Action Handoff Review layer implemented
1603 10:19p 🔵 Baseline safety counts recorded for Stage 4 audit
1604 " 🔵 audit_hotfix.py validation: 38/38 safety checks passed
1605 10:20p 🔵 Stage 4 regression test suite: 48/48 tests passed
1606 " 🔵 Stage 4.0 snapshot commands: all successful, no side effects
1607 " 🔵 Stage 4.1 reports: created successfully, no side effects
1608 " 🔵 Stage 4.2 trends: analysis complete with report persistence, no side effects
1609 10:21p 🔵 Stage 4.3 failure drilldown: all clustering and filtering work, no side effects
1610 " 🔵 Stage 4.3 failure clustering: reasonable classifications and cluster distribution
1611 " 🔵 Stage 4.4 remediation plans: all sources and filters work, no side effects
1612 " 🔵 Stage 4.5 action queue: works successfully, duplicate prevention verified
1613 10:23p 🔵 Observatory action storage: 19 tables in database, dedup working at row level
1614 " 🔵 Observatory action storage verified: 9 action items with no database side effects
1615 " 🔵 Stage 4.6 action review: all grouping dimensions work, no side effects
1616 " 🔵 Stage 4.7 dry-run handoffs: all types safe, no loops/jobs created
1617 " 🔵 Handoff creation requires explicit confirmation flags, defaults to dry-run
1618 10:24p 🔵 Stage 4.8 handoff review: all grouping and filtering work, no side effects
1619 " 🔵 Stage 4.9 audit passed with 36/36 checks, Stage 5 readiness confirmed
1620 " 🔵 Observatory commands resilient to invalid Ollama: all exit 0 with no errors
1621 " 🔵 Core command regression: all six core commands still working
1622 " 🔵 Stage 4 audit complete: all sections pass, safety confirmed, Stage 5 ready
1623 10:25p 🔵 Final validation: no protected content leaked, ResourceWarnings persist
1624 10:53p 🔵 Stage 4 Observatory subsystem files ready for commit
1625 10:55p 🔵 Stage 4 Observatory subsystem dependency structure identified
1626 10:58p ✅ .gitignore updated to exclude Stage 4 report directories
1627 " 🔵 Stage 4 pre-commit verification passed all checks
1628 10:59p ✅ 54 source and documentation files staged for Stage 4 commit
1629 11:00p 🔵 Stage 4 commit staged changeset verified: 57 files, 23,530 insertions
1630 " 🟣 Stage 4 Observatory subsystem committed to repository
1631 11:01p 🔵 Post-commit verification: Stage 4 commit successful, working tree clean
S144 Commit Stage 4 Observatory subsystem safely to Git—create a clean, verified commit with only Stage 4 source, tests, and documentation; exclude runtime artifacts and generated reports. (Jun 28 at 11:01 PM)
1632 11:04p 🟣 Stage 4.9 Observatory Final Audit and Stage 5 Readiness Summary
1633 11:27p 🟣 Stage 5.0 Loop Improvement Engine implemented and verified

Access 1311k tokens of past work via get_observations([IDs]) or mem-search skill.
</claude-mem-context>
