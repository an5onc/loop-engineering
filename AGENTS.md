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

## Controlled Multi-Step Orchestration (Stage 11)

Stage 11 coordinates multiple Stage 10 single-step executions without adding a
new executor or broader permissions.

- Orchestration plans, dry-runs, runs, controls, reports, and audits are
  metadata over Stage 10 records.
- Advancement executes at most one step per explicit CLI invocation and
  delegates to Stage 10 runtime. Do not add alternate subprocess paths.
- Every advanced step still requires approved Stage 10 confirmation, rollback
  snapshot, allowlisted command, confined cwd, and `--confirm-execution`.
- Failed or unverified steps block later steps. No automatic retry, rollback,
  batch execution, parallel execution, Git mutation, external jobs, or model
  calls.
- Typical flow:
  `--plan-cross-project-orchestration SESSION_ID`
  → `--dry-run-cross-project-orchestration PLAN_ID`
  → `--start-cross-project-orchestration PLAN_ID --dry-run DRY_RUN_ID`
  → `--cross-project-orchestration-step-controls RUN_ID --step STEP_ID`
  → `--advance-cross-project-orchestration RUN_ID --step STEP_ID --confirmation CONFIRMATION_ID --snapshot SNAPSHOT_ID --confirm-execution`
  → `--verify-cross-project-orchestration-step RUN_ID --step STEP_ID`
  → `--cross-project-orchestration-audit` / `--cross-project-stage11-audit`.
- Stage 11 generated reports are ignored runtime artifacts:
  `cross_project_orchestration_reports/`,
  `cross_project_orchestration_audit_reports/`,
  `cross_project_stage11_audit_reports/`.

## Execution Windows & Retry Policy (Stage 12)

Stage 12 adds operator-defined execution windows and a bounded retry policy on
top of Stage 11 orchestration. It introduces no new execution path: the gated
advancement engine delegates to the Stage 11 runtime, which delegates to
Stage 10.

- Advancement now requires an open operator execution window. Windows start
  `defined`, must be explicitly opened, and never reopen after closing;
  optional ISO time bounds narrow an open window. A missing or non-open
  window fails closed.
- Retries are metadata authorizations only. A retry policy is write-once per
  run with `--max-retries` between 1 and 3. A retry request is granted only
  for a blocked step with budget remaining; it re-opens the step and executes
  nothing.
- Every attempt — first or retry — requires its own approved Stage 10
  confirmation, snapshot, and literal `--confirm-execution`. A confirmation id
  can never be reused for the same run step; the audits verify this.
- The Stage 12 final audit also verifies dynamically that the command
  allowlist is unchanged.
- Typical flow:
  `--define-execution-window RUN_ID --label LABEL`
  → `--open-execution-window WINDOW_ID`
  → `--advance-cross-project-orchestration ... --confirm-execution`
  → on failure: `--set-orchestration-retry-policy RUN_ID --max-retries N`
  → `--request-orchestration-retry RUN_ID --step STEP_ID`
  → fresh confirmation + snapshot → advance again
  → `--cross-project-window-retry-audit` / `--cross-project-stage12-audit`.
- Stage 12 generated reports are ignored runtime artifacts:
  `cross_project_window_retry_reports/`,
  `cross_project_window_retry_audit_reports/`,
  `cross_project_stage12_audit_reports/`.

## Operator Rollback Restoration (Stage 13)

Stage 13 lets an operator restore the Stage 10 snapshot behind a blocked
orchestration step, through the orchestration layer. It introduces no new
execution or file-write path.

- All file writes delegate to the Stage 10 rollback engine
  (`cross_project_execution_rollback.py`), which re-validates containment and
  protected paths at restore time. Do not add an alternate restore path.
- Restoration is fail-closed: it requires an eligible blocked step (latest
  advancement blocked, with a snapshot), a fresh preview of the same snapshot
  since the latest restore, and the literal `--confirm-restore` flag.
- Restoration never re-opens the step or run. Only a Stage 12 retry
  authorization (`--request-orchestration-retry`) may re-open a blocked step;
  the audits verify this.
- By design, restoration is not gated by execution windows: windows govern
  when commands may run; restoration is recovery.
- The integrity check re-hashes restored files against the snapshot manifest
  (read-only); the outcome binder records the Stage 10 `rolled_back` outcome.
- Typical flow:
  `--resolve-orchestration-restoration RUN_ID --step STEP_ID`
  → `--preview-orchestration-restoration RUN_ID --step STEP_ID`
  → `--restore-orchestration-step RUN_ID --step STEP_ID --confirm-restore`
  → `--check-restoration-integrity RUN_ID --step STEP_ID`
  → `--record-restoration-outcome RUN_ID --step STEP_ID`
  → `--restoration-status RUN_ID` → Stage 12 retry flow
  → `--cross-project-restoration-audit` / `--cross-project-stage13-audit`.
- Stage 13 generated reports are ignored runtime artifacts:
  `cross_project_restoration_reports/`,
  `cross_project_restoration_audit_reports/`,
  `cross_project_stage13_audit_reports/`.

## Multi-Run Orchestration Sessions (Stage 14)

Stage 14 groups existing orchestration runs into an operator-managed session
for coordination. It has no executor and no new execution, retry, restore, or
file-write path.

- Session advancement executes at most one step per CLI invocation and
  delegates only to Stage 12 gated advancement (Stage 12 → 11 → 10). Stage 14
  modules must never import subprocess or call the terminal runner or model
  client directly; the runtime audit scans module source for this.
- Shared session gates are advisory coordination metadata. An approved gate
  is required for session advancement but can never replace per-step
  confirmation, snapshot, cwd, allowlist, execution window, retry
  authorization, restoration preview/confirm, or `--confirm-execution`.
- A run may be active in only one open session; closed sessions are immutable
  except for read-only reports and audits.
- Readiness, planner, and recovery outputs are deterministic advisory
  metadata: they never execute, confirm, snapshot, open windows, retry,
  restore, or re-open steps. Recovery guidance emits the exact manual Stage
  12/13 commands.
- Typical flow:
  `--create-multi-run-session "TITLE"`
  → `--add-run-to-multi-run-session SESSION_ID RUN_ID`
  → `--define-multi-run-gate SESSION_ID --label LABEL`
  → `--approve-multi-run-gate GATE_ID`
  → `--multi-run-readiness SESSION_ID` / `--plan-multi-run-advancement SESSION_ID`
  → `--advance-multi-run-session SESSION_ID --run RUN_ID --step STEP_ID --confirmation CONFIRMATION_ID --snapshot SNAPSHOT_ID --confirm-execution`
  → on blocked steps: `--multi-run-recovery-status SESSION_ID` (manual Stage 13/12 recovery)
  → `--multi-run-session-report SESSION_ID`
  → `--multi-run-session-audit` / `--cross-project-stage14-audit`.
- Stage 14 generated reports are ignored runtime artifacts:
  `multi_run_readiness_reports/`, `multi_run_planner_reports/`,
  `multi_run_recovery_reports/`, `multi_run_session_reports/`,
  `multi_run_session_audit_reports/`, `cross_project_stage14_audit_reports/`.


<claude-mem-context>
# Memory Context

# [loop-engineering] recent context, 2026-07-01 9:37pm MDT

Legend: 🎯session 🔴bugfix 🟣feature 🔄refactor ✅change 🔵discovery ⚖️decision 🚨security_alert 🔐security_note
Format: ID TIME TYPE TITLE
Fetch details: get_observations([IDs]) | Search: mem-search skill

Stats: 50 obs (23,965t read) | 776,181t work | 97% savings

### Jul 1, 2026
S164 User asked if they should proceed to the next stage or if alternatives are recommended; Claude recommended dogfooding Stages 7-10 on a real project before building Stage 11 (Jul 1 at 2:51 PM)
S165 Stage 7→10 dogfood execution plan review and real-project integration testing (Jul 1 at 3:03 PM)
S169 Stage 11 dogfood testing validation completed; ready to confirm Stage 12 next steps (Jul 1 at 3:13 PM)
S173 Design Stage 12 implementation plan for controlled execution windows and limited retry policy, layered on Stage 11 orchestration (Jul 1 at 3:49 PM)
S175 Complete implementation, comprehensive testing, and documentation of Stage 12 (Execution Windows & Retry Policy) for the loop-engineering orchestration framework (Jul 1 at 6:52 PM)
S178 Complete Stage 13 operator-driven rollback restoration implementation, validation, and integration with documentation and test infrastructure (Jul 1 at 7:28 PM)
1922 8:07p 🔵 Stage 11 orchestration safety controls validated end-to-end
1923 8:08p ⚖️ Stage 13 architecture designed: operator-driven rollback restoration with preview-first invariant
1924 " ✅ Stage 13 implementation sequenced into 8 atomic tasks; Stage 10 foundation verified
1925 8:09p ✅ Database schema extended with 9 Stage 13 restoration tables
1971 8:23p 🟣 Orchestration advancement fail-closed behavior verified
1972 " 🟣 Cross-project orchestration execution tracking implemented
1973 " 🟣 Stage 7→11 metadata flow end-to-end validated
1974 " 🔵 Disposable project isolation maintained data integrity
1975 8:24p 🟣 Stage 11 Orchestration Safety Validation Completed
1976 " 🔵 Stage 13 Rollback Restoration Safety Validated
1977 " ✅ Stage 13 Operator-Driven Rollback Restoration Documented
1978 " ✅ Stage 13 Agent Contract and Handoff Configuration Updated
1979 8:25p ✅ Stage 13 Integrated into Agent Handoff Generation and Tests
1980 8:27p 🔵 Stage 13 Integration Verified: Full Test Suite Passing
1981 8:28p 🟣 Stage 13 Two-Pass Dogfood Test Driver Implemented
1982 8:29p 🔵 Stage 13 Dogfood Validation Complete: Both Passes Successful
1983 " 🔵 Stage 13 Implementation Complete: 28 Changes Ready for Commit
S179 Stage 13 operator-driven rollback restoration implementation — complete audit-passing feature with preview-first gate and fail-closed semantics ready for Stage 14 (Jul 1 at 8:30 PM)
1984 8:32p ⚖️ Stage 13 Plan: Controlled Operator-Driven Rollback Restoration Architecture
1985 8:42p 🟣 Stage 13 operator-driven rollback restoration implementation complete with preview-first gate and fail-closed semantics
S180 Implement Stage 14 Multi-Run Orchestration Sessions: session coordination layer that groups Stage 11/12 runs without introducing an executor, with readiness inspection, deterministic advancement planner, advisory gates, and recovery guidance (Jul 1 at 8:44 PM)
1986 8:50p 🔵 Stage 14 baseline repository state confirmed
1987 8:51p 🔵 Stage 13 restoration audit mechanisms reviewed for Stage 14 design
1988 8:53p 🔵 Full regression test suite passes; run status semantics and Stage 11-12 documentation patterns reviewed
1989 " ⚖️ Stage 14 implementation initiated with database schema and helpers task
1990 " ⚖️ Stage 14 implementation decomposed into 6 tracked work tasks (14.0–14.9)
1991 " ⚖️ Stage 14 work tasks completed; Task 19 (database schema) moved to in_progress
1992 8:54p 🟣 Stage 14 database schema implemented with 17 new tables
2022 9:09p 🔵 Stage 11 orchestration verification passed with fail-closed enforcement
2023 " ✅ Stage 14 Multi-Run Orchestration Sessions specification documented in AGENTS.md
2024 " ✅ README.md updated to document Stage 14 as primary orchestration layer
2025 9:10p ✅ agent_handoff.py updated to configure Stage 14 report directories as ignored runtime artifacts
2026 " ✅ agent_handoff.py and test_agent_handoff.py updated to include Stage 14 in portable handoff
2027 9:13p 🔵 Stage 14 documentation complete and verified: all tests pass, all checks pass
2028 9:14p 🔵 Stage 14 comprehensive dogfood test harness created
2029 " 🔵 Stage 14 dogfood two-pass test completed successfully; assertion count needs adjustment
2030 9:15p 🔵 Stage 14 dogfood test assertion corrected; two-pass verification now complete
2031 " 🔵 Stage 14 multi-run orchestration sessions dogfood verification complete: both passes PASS
2032 " 🔵 Stage 14 implementation complete: 8 modified files + 17 new Stage 14 modules
S181 User asked how many more stages until the project is complete and ready for production. Claude analyzed the infinite stage-generation loop and recommended a practical path to production readiness. (Jul 1 at 9:16 PM)
2033 9:24p 🟣 Stage 14: Multi-run session lifecycle and governance system
2034 " 🔵 Stage 14 design deviation: recovery-needed refusal precedes delegation
2035 " 🟣 Stage 14 audit framework: runtime audits with graceful degradation
2036 " 🟣 Stage 14 verification: 532 passing tests with full dogfood validation
2037 9:31p 🔵 Stage 14 audit layer has two critical coverage gaps allowing invalid metadata and protected content
2038 " ✅ Added MARKER_SCAN_TABLES constant to enumerate all Stage 14 report tables for protected-content audit
2039 9:32p 🔴 Fixed Stage 14 advancement audit to validate complete metadata linkage with Stage 12 rows
2040 " 🔴 Fixed protected-content audit to scan all Stage 14 report and audit tables
2041 " ✅ Added regression tests for P1 advancement linkage metadata validation
2042 " ✅ Added regression tests for P2 protected-content audit coverage across all Stage 14 report tables
2044 " 🔵 P2 fix causes audit to BLOCK on missing report tables instead of reporting FAIL
2045 9:33p ✅ Fixed test regression and documented expected behavior for missing scanned report tables
2048 9:35p 🔵 Adversarial verification confirms audit gaps are fixed; fabricated bad metadata now correctly fails
S182 Fix two Stage 14 audit coverage gaps that allowed invalid metadata and undetected protected content to pass final audit verification (Jul 1 at 9:35 PM)
**Investigated**: Reviewed the original audit findings that identified P1 (mismatched session advancement metadata not validated) and P2 (protected-content audit scanning only one of six Stage 14 report tables). Reproduced both scenarios in temporary database to confirm the gaps existed. Examined the existing _check_advancements_reference_stage12 and _check_reports_no_protected_markers methods to understand their limitations.

**Learned**: P1 gap: the advancement audit only checked for row existence (gated_advancement_id IS NULL) but did not validate that run_id, run_step_id, attempt_id, and status matched between Stage 14 and Stage 12 rows — allowing fabricated mismatched metadata to pass. P2 gap: protected-content scanning relied on database.list_multi_run_session_reports() which only covered multi_run_session_reports, leaving readiness_reports, planner_reports, recovery_reports, and audit tables unscanned. Missing scanned tables in the new implementation cause sqlite3.Error and BLOCK (not FAIL), requiring test adjustments to distinguish between required-table-missing (FAIL) and scanned-table-missing (BLOCK) scenarios.

**Completed**: Fixed _check_advancements_reference_stage12 to validate all five fields (id, run_id, run_step_id, attempt_id, status) between Stage 14 and Stage 12 rows using null-safe IS NOT comparisons. Added MARKER_SCAN_TABLES constant listing all six scanned tables. Refactored _check_reports_no_protected_markers to iterate through MARKER_SCAN_TABLES with per-table hit counting and reporting. Added six regression tests: test_matching_advancement_linkage_passes, test_mismatched_advancement_linkage_fails (with per-field subtests), test_protected_marker_in_readiness_report_fails, test_protected_marker_in_planner_report_fails, test_protected_marker_in_recovery_report_fails, and test_missing_scanned_report_table_degrades_to_blocked. Fixed test_audit_fails_when_required_table_missing to drop multi_run_session_events instead of multi_run_recovery_reports. Verified all changes with full test suite (538 tests pass), hotfix audit (38/38 checks), and adversarial scenarios (both P1 and P2 now correctly fail).

**Next Steps**: Stage 14 audit fixes are complete and fully verified. All 538 tests pass, 67 Stage 14 and handoff tests pass, adversarial scenarios confirm the fixes work, and the system is commit-ready. No active work remaining in this session — waiting for commit decision.


Access 776k tokens of past work via get_observations([IDs]) or mem-search skill.
</claude-mem-context>
