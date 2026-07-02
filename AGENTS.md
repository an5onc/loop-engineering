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


<claude-mem-context>
# Memory Context

# [loop-engineering] recent context, 2026-07-01 8:32pm MDT

Legend: 🎯session 🔴bugfix 🟣feature 🔄refactor ✅change 🔵discovery ⚖️decision 🚨security_alert 🔐security_note
Format: ID TIME TYPE TITLE
Fetch details: get_observations([IDs]) | Search: mem-search skill

Stats: 50 obs (26,957t read) | 472,721t work | 94% savings

### Jun 28, 2026
S145 Build Stage 7 of the Loop Engineering framework: a safe, metadata-only multi-project operations layer enabling project registration, health inspection, cross-project work planning, approval gating, handoff generation, and scheduling metadata recording—all without hidden writes, command execution, model calls, or cross-project mutation without approval. (Jun 28 at 11:01 PM)
### Jun 30, 2026
S158 Full audit of Stage 9 pulled from remote to verify everything works as expected and identify any required changes (Jun 30 at 9:04 AM)
### Jul 1, 2026
S160 Audit Stage 10 implementation: verify compilation, tests, audits, and execution safety gates for readiness. (Jul 1 at 1:53 PM)
S161 Clarification on whether metadata is placeholder/test data requiring re-execution, or real system data; whether the system works now or requires rebuilding. (Jul 1 at 2:44 PM)
S164 User asked if they should proceed to the next stage or if alternatives are recommended; Claude recommended dogfooding Stages 7-10 on a real project before building Stage 11 (Jul 1 at 2:51 PM)
S165 Stage 7→10 dogfood execution plan review and real-project integration testing (Jul 1 at 3:03 PM)
S169 Stage 11 dogfood testing validation completed; ready to confirm Stage 12 next steps (Jul 1 at 3:13 PM)
S173 Design Stage 12 implementation plan for controlled execution windows and limited retry policy, layered on Stage 11 orchestration (Jul 1 at 3:49 PM)
S175 Complete implementation, comprehensive testing, and documentation of Stage 12 (Execution Windows & Retry Policy) for the loop-engineering orchestration framework (Jul 1 at 6:52 PM)
1882 7:16p 🔵 Stage 11 orchestration safety validation completed
1883 " 🔵 Stage 12 execution windows and retry policy infrastructure verified
1884 " 🔵 Stage 12 window and retry policy validation enforces run context requirement
1885 7:17p 🔵 Full unittest suite confirms fail-safe automation safeguards
1886 7:20p 🔵 Full test suite passes: 433 tests with zero failures
1887 " 🔵 Audit hotfix verification suite passes all 38 checks
1888 7:21p ✅ README.md updated with comprehensive Stage 12 documentation
1889 " 🔵 HANDOFF.md generated from agent_handoff.py; Stage 12 section missing
1890 7:22p 🔵 REQUIRED_IGNORES list ends at Stage 11; Stage 12 patterns missing
1891 " ✅ REQUIRED_IGNORES updated with Stage 12 artifact directory patterns
1892 " ✅ agent_handoff.py updated with comprehensive Stage 12 section
1893 " 🔵 test_agent_handoff.py lacks Stage 12 content assertions
1894 7:23p 🔵 test_agent_handoff.py test helper has incomplete .gitignore and missing Stage 12 assertions
1895 " ✅ test_agent_handoff.py updated with Stage 12 content assertions
1896 " 🔵 HANDOFF.md regenerated with Stage 12; all handoff tests passing
1897 7:24p 🔵 AGENTS.md ends at Stage 11; missing Stage 12 documentation section
1898 " 🔵 AGENTS.md Stage 11 section structure clearly defined; ready for Stage 12 insertion
1899 " ✅ AGENTS.md updated with comprehensive Stage 12 section
1900 7:25p 🔵 Stage 12 implementation complete and verified: 58 tests passing
1901 7:26p ✅ Stage 12 comprehensive dogfood test script created
1902 7:27p 🔵 Stage 12 dogfood test completed successfully: both passes OK
1903 7:28p 🔵 Stage 12 implementation complete: 8 files modified, 20 new files added
1907 7:42p 🟣 Stage 12 Complete — Execution Windows & Retry Policy
1911 7:43p 🔵 Stage 13 Foundation: Precise Architecture of Stages 10–12 Rollback/Snapshot Machinery
1913 7:50p 🔵 Stage 10–12 Rollback/Snapshot Architecture: Complete Inventory for Stage 13 Implementation
1914 7:56p 🔵 Stage 11 dogfood testing completed with fail-closed safety validation
1915 " 🔵 Stage 12 architecture: Multi-layer fail-closed gating for operator-driven orchestration advancement
1916 7:57p 🔵 Stage 12.7-12.8: Window & Retry reporting and runtime audit systems
1917 7:58p 🔵 Stage 12 CLI integration and operator workflow documented in agent handoff
1918 " 🔵 Execution outcomes track rollback restores; restore requires explicit confirmation
1919 8:02p 🔵 Stage 11 orchestration dogfood testing validated successfully
1920 8:03p ⚖️ Stage 13 implementation plan designed: controlled operator-driven rollback restoration
1921 8:04p ✅ Stage 13 implementation plan documented in persistent artifact
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
S178 Complete Stage 13 operator-driven rollback restoration implementation, validation, and integration with documentation and test infrastructure (Jul 1 at 8:30 PM)
**Investigated**: - Stage 13 architecture for fail-closed restoration (preview-first, --confirm-restore gate)
    - Integration points with Stage 10 rollback engine (delegation model, no new write path)
    - Interaction with Stage 12 retry flow (step stays blocked until retry authorization)
    - Metadata tracking across restoration targets, previews, restores, integrity checks, outcomes
    - Audit chain (restoration audit, window-retry audit, stage12 audit, stage13 audit)
    - Documentation and portable handoff system integration
    - End-to-end recovery workflows on real repo (metadata-only) and disposable project (full lifecycle)

**Learned**: - Stage 13 introduces zero new file-write paths by design; all restores delegate to Stage 10 rollback engine with re-validation
    - Fail-closed restore semantics require three gates: prior preview of same snapshot, literal --confirm-restore flag, and eligible blocked step
    - Restoration is NOT gated by execution windows; windows govern command execution, restoration is recovery
    - Preview is a first-class operation with auditable metadata (cross_project_orchestration_step_rollbacks table), enabling integrity binding
    - Outcome recording captures "rolled_back" status with full metadata linkage back to Stage 10 execution attempt
    - Status tracking guides operator through guided sequence without automation (preview → restore → verify → record → retry)
    - Restoration never re-opens blocked steps; only Stage 12 retry authorization may re-open; audits verify this invariant
    - Stage 12 guidance become state-aware: if restore exists, suggest retry directly; if not, suggest restore first
    - Portable handoff system integrates Stage 13 as standard component of cross-agent knowledge transfer

**Completed**: - Implemented 9 Stage 13 modules: target resolution, preview, gated restore, integrity verification, outcome recording, status tracking, reporting, comprehensive audit, and stage13 final audit
    - Implemented 9 corresponding test modules with full coverage (37 new tests)
    - Updated documentation: README with full Stage 13 reference guide, AGENTS.md with agent contract, HANDOFF.md regenerated with Stage 13 section
    - Updated infrastructure: database schema extensions, CLI integration in main.py, agent_handoff.py with Stage 13 report directories, .gitignore patterns
    - Validation: py_compile clean, hotfix audit 38/38 PASS, full test suite 470 tests OK
    - Dogfood validation: two-pass end-to-end testing (real repo metadata-only + disposable project recovery), both passes successful
    - Stage 13 audit: PASS with stage 14 ready: True
    - All fail-closed semantics verified, recovery workflows validated, zero side effects confirmed

**Next Steps**: Awaiting user direction: Stage 13 implementation is complete with all 28 changes ready for atomic commit. No further work in progress; the tree awaits `git add` and `stage 13` commit message per established convention (verified state committed, not in-flight work).


Access 473k tokens of past work via get_observations([IDs]) or mem-search skill.
</claude-mem-context>
