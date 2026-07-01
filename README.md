# Loop Engineering — Stage 11

## What's new in 11 — Controlled Multi-Step Execution Orchestration

Stage 11 coordinates multiple Stage 10 single-step executions without adding a
new executor or broader permissions. It builds orchestration plans from prepared
Stage 10 sessions, validates them, starts sequential runs, reports the next
required Stage 10 controls, advances exactly one step per explicit command, and
audits the orchestration metadata.

Execution still belongs to Stage 10: every advanced step requires an approved
Stage 10 confirmation, rollback snapshot, allowlisted command, confined cwd, and
explicit `--confirm-execution`. Stage 11 does not add parallel execution, retry
loops, Git mutation, external-agent jobs, hidden model calls, or automatic
rollback.

### 11.0-11.2 Orchestration plan, dry-run, and run

```bash
python3 main.py --plan-cross-project-orchestration SESSION_ID
python3 main.py --cross-project-orchestration-plans
python3 main.py --cross-project-orchestration-plan PLAN_ID

python3 main.py --dry-run-cross-project-orchestration PLAN_ID
python3 main.py --cross-project-orchestration-dry-runs
python3 main.py --cross-project-orchestration-dry-run DRY_RUN_ID

python3 main.py --start-cross-project-orchestration PLAN_ID --dry-run DRY_RUN_ID
python3 main.py --cross-project-orchestration-runs
python3 main.py --cross-project-orchestration-run RUN_ID
```

### 11.3-11.6 Controls, advancement, verification, rollback status

```bash
python3 main.py --cross-project-orchestration-step-controls RUN_ID --step STEP_ID
python3 main.py --advance-cross-project-orchestration RUN_ID --step STEP_ID --confirmation CONFIRMATION_ID --snapshot SNAPSHOT_ID --confirm-execution
python3 main.py --verify-cross-project-orchestration-step RUN_ID --step STEP_ID
python3 main.py --cross-project-orchestration-rollback-status RUN_ID
```

### 11.7-11.9 Reports and audits

```bash
python3 main.py --cross-project-orchestration-report RUN_ID --save-report
python3 main.py --cross-project-orchestration-audit --save-report
python3 main.py --cross-project-stage11-audit --save-report
```

### Stage 11 tests

```bash
python3 -m unittest \
  test_cross_project_orchestration_plans.py \
  test_cross_project_orchestration_dry_run.py \
  test_cross_project_orchestration_runs.py \
  test_cross_project_orchestration_controls.py \
  test_cross_project_orchestration_runtime.py \
  test_cross_project_orchestration_verification.py \
  test_cross_project_orchestration_rollback.py \
  test_cross_project_orchestration_reports.py \
  test_cross_project_orchestration_audit.py \
  test_cross_project_stage11_audit.py
```

# Loop Engineering — Stage 10

## What's new in 10 — Controlled Cross-Project Execution

Stage 10 builds on the Stage 9 planning layer and can execute exactly one
approved cross-project command at a time. Execution is fail-closed: it requires
a Stage 9 plan, latest passing dry-run, approved Stage 9 approval, matching
handoff, Stage 10 confirmation, rollback snapshot, allowlisted command, and an
explicit `--confirm-execution` flag. It uses dedicated Stage 10 runtime tables,
not loop `command_results`.

### 10.0 Execution session preflight

```bash
python3 main.py --prepare-cross-project-execution PLAN_ID --approval APPROVAL_ID
python3 main.py --cross-project-execution-sessions
python3 main.py --cross-project-execution-session SESSION_ID
```

### 10.1 Scope resolution

```bash
python3 main.py --resolve-cross-project-execution-scope SESSION_ID
```

### 10.2 Human execution confirmation

```bash
python3 main.py --request-cross-project-execution-confirmation SESSION_ID --step STEP_ID --command PROPOSAL_ID
python3 main.py --set-cross-project-execution-confirmation CONFIRMATION_ID approved
```

### 10.3 Rollback snapshot

```bash
python3 main.py --snapshot-cross-project-execution SESSION_ID --confirmation CONFIRMATION_ID
```

Optional `--target-file PATH` entries capture only allowlisted, non-protected
files for rollback. Protected paths and traversal are rejected.

### 10.4 Single command execution

```bash
python3 main.py --execute-cross-project-command SESSION_ID --confirmation CONFIRMATION_ID --snapshot SNAPSHOT_ID --confirm-execution
```

Execution routes through `terminal.run_command`: no shell, no command chaining,
fixed allowlist, cwd confinement, timeout, and limited environment. Stage 10
does not auto-commit, push, create branches, call Ollama, create loops/jobs, or
create external-agent jobs.

### 10.5 Verification, rollback, outcomes, audits

```bash
python3 main.py --verify-cross-project-execution ATTEMPT_ID
python3 main.py --preview-cross-project-execution-rollback SNAPSHOT_ID
python3 main.py --restore-cross-project-execution-rollback SNAPSHOT_ID --confirm-restore
python3 main.py --record-cross-project-execution-outcome ATTEMPT_ID
python3 main.py --cross-project-runtime-audit --save-report
python3 main.py --cross-project-stage10-audit --save-report
```

### Stage 10 tests

```bash
python3 -m unittest \
  test_cross_project_execution_sessions.py \
  test_cross_project_execution_scope.py \
  test_cross_project_execution_confirmations.py \
  test_cross_project_execution_snapshots.py \
  test_cross_project_execution_runtime.py \
  test_cross_project_execution_verification.py \
  test_cross_project_execution_rollback.py \
  test_cross_project_execution_outcomes.py \
  test_cross_project_runtime_audit.py \
  test_cross_project_stage10_audit.py
```

## What's new in 9 — Controlled Cross-Project Execution Planning

Stage 9 builds on Stage 7 multi-project metadata and Stage 8 governance to
produce reviewable cross-project execution plans. It remains **planning-only**:
commands are proposed as advisory text, dry-runs validate metadata gates,
approval records are explicit, and handoff packets are portable. Nothing in
Stage 9 executes commands, calls Ollama, creates loops/jobs, commits, reads
protected file contents, or writes registered project roots.

### 9.0 Execution intent registry

Records explicit operator intent from a cross-project plan, governance action
plan, or manual request.

```bash
python3 main.py --create-cross-project-execution-intent --source-type manual --source-id 0 --title "Manual execution planning" --owner operator
python3 main.py --cross-project-execution-intents
python3 main.py --cross-project-execution-intent INTENT_ID
```

### 9.1 Execution readiness

Classifies registered projects as ready or blocked using registry, validation,
and governance metadata only.

```bash
python3 main.py --cross-project-execution-readiness INTENT_ID --save-report
python3 main.py --cross-project-execution-readiness-reports
python3 main.py --cross-project-execution-readiness-show REPORT_ID
```

### 9.2 Execution plan builder

Builds ordered, gated per-project execution steps with approvals, rollback
requirements, validation requirements, and advisory commands.

```bash
python3 main.py --plan-cross-project-execution INTENT_ID --readiness REPORT_ID
python3 main.py --cross-project-execution-plans
python3 main.py --cross-project-execution-plan PLAN_ID
```

### 9.3 Advisory command proposals

Stores per-project advisory command proposals. These are metadata records, not
jobs, and are never executed by Stage 9.

```bash
python3 main.py --propose-cross-project-execution-commands PLAN_ID
python3 main.py --cross-project-execution-command-proposals
python3 main.py --cross-project-execution-command-proposal PROPOSAL_ID
```

### 9.4 Dry-run validator

Validates the execution plan and command proposals before any approval request.
Failed or blocked dry-runs prevent approval handoff.

```bash
python3 main.py --dry-run-cross-project-execution PLAN_ID
python3 main.py --cross-project-execution-dry-runs
python3 main.py --cross-project-execution-dry-run DRY_RUN_ID
```

### 9.5 Human approval metadata

Creates approval records only when the referenced dry-run passed. Approval does
not execute anything.

```bash
python3 main.py --request-cross-project-execution-approval PLAN_ID --dry-run DRY_RUN_ID
python3 main.py --cross-project-execution-approvals
python3 main.py --cross-project-execution-approval APPROVAL_ID
python3 main.py --set-cross-project-execution-approval APPROVAL_ID approved
```

### 9.6 Execution handoff packet

Generates a portable packet for a plan with a matching approved approval and
passing dry-run. Packets exclude protected contents, secrets, local DB snapshots,
and execution side effects.

```bash
python3 main.py --handoff-cross-project-execution PLAN_ID --approval APPROVAL_ID
python3 main.py --cross-project-execution-handoffs
python3 main.py --cross-project-execution-handoff HANDOFF_ID
```

### 9.7 Execution planning audit

Audits Stage 9 execution-planning metadata for integrity, blocked dry-runs, and
safety invariants.

```bash
python3 main.py --cross-project-execution-audit --save-report
python3 main.py --cross-project-execution-audits
python3 main.py --cross-project-execution-audit-show latest
```

### 9.8 Final Stage 9 audit & Stage 10 readiness

Verifies Stage 9 modules, tables, CLI paths, report guards, and safety
invariants, and reports Stage 10 readiness. Recommended Stage 10 theme:
controlled cross-project execution under explicit human approval.

```bash
python3 main.py --cross-project-stage9-audit --save-report
python3 main.py --cross-project-stage9-audits
python3 main.py --cross-project-stage9-audit-show latest
```

### Stage 9 tests

```bash
python3 -m unittest \
  test_cross_project_execution_intents.py \
  test_cross_project_execution_readiness.py \
  test_cross_project_execution_plans.py \
  test_cross_project_execution_commands.py \
  test_cross_project_execution_dry_run.py \
  test_cross_project_execution_approvals.py \
  test_cross_project_execution_handoff.py \
  test_cross_project_execution_audit.py \
  test_cross_project_stage9_audit.py
```

## What's new in 8 — Multi-Project Governance & Fleet Reporting

Stage 8 builds on Stage 7's metadata-only multi-project layer and adds
**governance**: fleet-level policies, deterministic policy evaluation into
findings, a manual review queue, finding-based exception waivers, fleet
governance reports, trend snapshots, an action planner, evidence export, and
final Stage 8 audit readiness. It does **not** introduce cross-project execution.

### Core invariant

Stage 8 reads only SQLite metadata and safe project-registry metadata. It never
executes commands, calls Ollama, creates loops/jobs, reads protected file
contents, or writes into a registered project root. Suggested commands are
advisory **text only**.

### 8.0 Governance policy registry

Policies are named sets of deterministic rules from a fixed built-in
`RULE_REGISTRY` (fleet rules: `require_validation`, `validation_not_failing`,
`not_stale`, `blocked_project_handling`, `approval_freshness`,
`handoff_schedule_integrity`, `audit_recency`, `require_safety_profile`).

```bash
python3 main.py --create-governance-policy --default     # seed the fleet baseline
python3 main.py --create-governance-policy strict --rules not_stale,validation_not_failing,audit_recency
python3 main.py --governance-policies
python3 main.py --governance-policy POLICY_ID
python3 main.py --set-governance-policy-status POLICY_ID inactive
```

### 8.1 Policy evaluation engine

Evaluates all **active** policies against Stage 7 metadata (projects,
validations, approvals, handoffs, schedules, audits) and records one **finding**
per (policy, rule, subject). Active, unexpired waivers suppress matching
findings (status `WAIVED`).

```bash
python3 main.py --evaluate-governance-policies --save-report
python3 main.py --governance-evaluations
python3 main.py --governance-evaluation EVALUATION_ID
```

### 8.2 Fleet governance report

Read-only fleet summary: project health, stale roots, blocked projects, missing
validations, planning coverage, and the latest policy pass/fail counts.

```bash
python3 main.py --fleet-governance-report --save-report
python3 main.py --fleet-governance-reports
python3 main.py --fleet-governance-report-show REPORT_ID
```

### 8.3 Governance review queue

Converts non-passing findings into manual review items. Statuses: `open`,
`acknowledged`, `waived`, `resolved`, `dismissed`, `blocked`. No automatic
remediation or project mutation.

```bash
python3 main.py --create-governance-review-items EVALUATION_ID
python3 main.py --governance-review-items --status open
python3 main.py --set-governance-review-status ITEM_ID acknowledged
```

### 8.4 Exception / waiver registry

Explicit, auditable waivers created **from a finding**, capturing that finding's
signature plus a reason, owner, and optional expiry. Fail-closed: only `active`
and **unexpired** waivers suppress; expired waivers stop suppressing findings.

```bash
python3 main.py --create-governance-waiver FINDING_ID --owner alice --reason "root on detached volume" --expiry-days 30
python3 main.py --governance-waivers
python3 main.py --set-governance-waiver-status WAIVER_ID revoked
```

### 8.5 Governance trend snapshot

Tracks governance health over time from saved evaluations and fleet reports
(counts and direction only — no file contents).

```bash
python3 main.py --governance-trends --save-report
python3 main.py --governance-trend-snapshots
python3 main.py --governance-trend-snapshot SNAPSHOT_ID
```

### 8.6 Governance action planner

Generates a manual follow-up plan from unresolved findings. Suggested commands
are **text only** and never executed.

```bash
python3 main.py --plan-governance-actions            # uses the latest evaluation
python3 main.py --governance-action-plans
python3 main.py --governance-action-plan PLAN_ID
```

### 8.7 Governance evidence export

Exports a portable Markdown evidence packet (policy summaries, evaluation
results, waiver metadata, review-queue state, fleet summary). Excludes protected
file contents, secrets, and local DB snapshots.

```bash
python3 main.py --export-governance-evidence
python3 main.py --governance-evidence-exports
```

### 8.8 Multi-project governance audit

Audits Stage 8 metadata for completeness, referential integrity, expired-but-
active waivers, and safety counters.

```bash
python3 main.py --multi-project-governance-audit --save-report
python3 main.py --multi-project-governance-audits
python3 main.py --multi-project-governance-audit-show latest
```

### 8.9 Final Stage 8 audit & Stage 9 readiness

Verifies all Stage 8 modules, tables, CLI paths, report-path guards, and safety
invariants, and reports **Stage 9 readiness**. Recommended Stage 9 theme:
controlled cross-project execution *planning* (not execution by default).

```bash
python3 main.py --multi-project-stage8-audit --save-report
python3 main.py --multi-project-stage8-audits
python3 main.py --multi-project-stage8-audit-show latest
```

### Stage 8 tests

```bash
python3 -m unittest \
  test_multi_project_governance_policies.py \
  test_multi_project_governance_evaluation.py \
  test_fleet_governance_reports.py \
  test_governance_review_queue.py \
  test_governance_waivers.py \
  test_governance_trends.py \
  test_governance_action_planner.py \
  test_governance_evidence_export.py \
  test_multi_project_governance_audit.py \
  test_multi_project_stage8_audit.py
```

## What's new in 7 — Multi-Project Operations

Stage 7 adds a **safe, metadata-only multi-project operations layer**. Loop
Engineering can now register multiple projects, inspect their health, plan
cross-project work, gate it behind explicit approvals, produce safe
implementation handoffs, record scheduling intent, and audit the whole
subsystem — all **without** hidden writes, hidden command execution, hidden
model calls, or cross-project mutation without explicit approval.

### Safety model (the rules Stage 7 never breaks)

- **Metadata-only.** Registry, validation, observatory, planning, approvals,
  handoffs, scheduling, and audits read SQLite metadata and small git ref
  pointers (`<root>/.git/HEAD`). They never read project file *contents*.
- **No hidden execution.** No commands are run, no models/Ollama are called, and
  no loops / `command_results` / `external_agent_jobs` rows are created. Suggested
  commands are emitted as **text** for a human to run manually.
- **No cross-project writes.** Nothing in Stage 7 writes to a registered
  project's root. The only writes are local Stage 7 metadata rows and generated
  Markdown reports/packets under ignored directories.
- **Fail closed.** A cross-project handoff or schedule is created **only** when a
  valid `approved` approval that references the same plan exists. Rejected,
  cancelled, expired, pending, or mismatched approvals are refused.
- **OLLAMA-independent.** Every Stage 7 metadata command exits 0 even with an
  invalid `OLLAMA_HOST`.

### Project registry (7.0)

Register projects and track their lifecycle. Roots are resolved to absolute
realpaths, must exist, must not sit inside protected system paths, and duplicate
keys are rejected. Status is one of `active | paused | archived | blocked`.

```bash
python3 main.py --register-project myapp --root /abs/path/to/myapp --repo https://github.com/me/myapp.git --branch main
python3 main.py --projects
python3 main.py --project myapp
python3 main.py --set-project-status myapp paused
python3 main.py --project-registry-summary
```

### Project workspace validation (7.1)

Safe, read-only validation: root exists, `.git` present when a `repo_url` is set,
branch metadata read from `.git/HEAD`, roots don't overlap other registered
roots, roots aren't inside protected/system paths, and allowed/protected paths
stay within the root. Stale/missing roots produce **warnings, not crashes**.

```bash
python3 main.py --validate-project myapp
python3 main.py --validate-projects
python3 main.py --project-validation-reports
python3 main.py --project-validation-report REPORT_ID
```

### Multi-project observatory (7.2)

Read-only dashboard across all registered projects: counts by status, per-project
latest validation status, best-effort loop/external-job counts (from local DB
metadata), stale projects, and projects needing attention. `--save-report` writes
a Markdown snapshot under `multi_project_observatory_reports/`.

```bash
python3 main.py --multi-project-observatory
python3 main.py --multi-project-observatory --save-report
python3 main.py --multi-project-snapshots
python3 main.py --multi-project-snapshot SNAPSHOT_ID
```

### Cross-project work planner (7.3)

Deterministic, plan-only. Includes `active` projects, excludes the rest, detects
structural dependencies (overlapping roots), lists required approvals and safety
blockers, and emits suggested manual commands. Status is one of
`proposed | blocked | approved_for_handoff | cancelled`.

```bash
python3 main.py --plan-cross-project-work "Review all registered projects for safety drift"
python3 main.py --cross-project-plans
python3 main.py --cross-project-plan PLAN_ID
python3 main.py --set-cross-project-plan-status PLAN_ID approved_for_handoff
```

### Cross-project approval gates (7.4)

Explicit approval metadata. An approval must reference a valid plan; only an
`approved` approval is usable downstream. Statuses: `pending | approved |
rejected | expired | cancelled`.

```bash
python3 main.py --request-cross-project-approval PLAN_ID
python3 main.py --cross-project-approvals
python3 main.py --cross-project-approval APPROVAL_ID
python3 main.py --set-cross-project-approval APPROVAL_ID approved
```

### Cross-project handoff packets (7.5)

Builds a human-readable implementation packet **only** for an approved plan.
The packet includes the plan summary, projects involved, per-project safety
profile (protected path **names only** — contents are never read), explicit
non-goals, required verification commands, a completion-response JSON template,
resume instructions, and a protected-content warning. Packets are written under
`cross_project_handoff_packets/`.

```bash
python3 main.py --handoff-cross-project-plan PLAN_ID --approval APPROVAL_ID
python3 main.py --cross-project-handoffs
python3 main.py --cross-project-handoff HANDOFF_ID
```

### Controlled scheduling metadata (7.6)

Scheduling **intent only** — no timers, no daemon, no auto-run. A schedule can
only be created for a plan with a valid `approved` approval. Status changes
update metadata and never start work. Statuses: `active | paused | cancelled |
completed`.

```bash
python3 main.py --schedule-cross-project-plan PLAN_ID --approval APPROVAL_ID --window "manual"
python3 main.py --multi-project-schedules
python3 main.py --multi-project-schedule SCHEDULE_ID
python3 main.py --set-multi-project-schedule-status SCHEDULE_ID completed
```

### Multi-project audit trail (7.7)

Summarizes registry, validation, observatory, planning, approvals, handoffs,
schedules, a safety baseline, and Stage 8 readiness, with optional Markdown
reports under `multi_project_audit_reports/`. It also verifies referential
integrity (e.g. every handoff/schedule references an approved approval).

```bash
python3 main.py --multi-project-audit
python3 main.py --multi-project-audit --save-report
python3 main.py --multi-project-audits
python3 main.py --multi-project-audit-show AUDIT_ID
```

### Final Stage 7 audit (7.9)

Structurally verifies all Stage 7 modules exist and import, all Stage 7 tables
exist, all list/show commands are wired, the safety baseline holds (no hidden
execution, no Ollama dependency, no cross-project writes, no loop/command/job
rows created, no protected content reads), and reports **Stage 8 readiness
yes/no**. Reports are written under `multi_project_stage7_audit_reports/`.

```bash
python3 main.py --multi-project-stage7-audit
python3 main.py --multi-project-stage7-audit --save-report
python3 main.py --multi-project-stage7-audits
python3 main.py --multi-project-stage7-audit-show latest
```

### Stage 7 tests

```bash
python3 -m unittest \
  test_multi_project_registry.py \
  test_multi_project_validation.py \
  test_multi_project_observatory.py \
  test_cross_project_planner.py \
  test_cross_project_approvals.py \
  test_cross_project_handoff.py \
  test_multi_project_scheduling.py \
  test_multi_project_audit.py \
  test_multi_project_stage7_audit.py
```

## What's new in 3.8 — External Agent Batch Reports

Every batch operation now produces a durable, auditable Markdown report
(`external_batch_reports.py`) saved under `external_batch_reports/`:

```
external_batch_reports/batch_<batchid>_YYYYMMDD_HHMMSS.md
```

```bash
python3 main.py --batch-external-jobs --action list_selected --status WAITING_FOR_EXTERNAL_AGENT
python3 main.py --external-batch-reports          # list recent batch reports
python3 main.py --external-batch-report BATCH_ID  # print one (regenerates from events if the file is gone)
```

- A report is generated **automatically after every batch** (including
  `--dry-run`, which is clearly marked **DRY RUN** and makes no job changes).
- Sections: **Summary**, **Filters**, **Results** (per job: agent/workspace/
  priority/labels/status before→after/result/error/details), **Safety**,
  **Failures**, **Skipped**, **Next Actions** (exact follow-up commands), and
  **Outcome** (clean? human action needed? safe to continue?).
- `--external-job` and `--show LOOP_ID` link the batch reports involving a job.

**Safety:** report generation is read-only — it runs no commands, calls no
models, and mutates no jobs/loops. Paths are generated internally and confined to
`external_batch_reports/`; reports summarize only metadata/statuses/errors/safe
paths and never include protected file contents or completion raw text. New table
`external_batch_reports`; gate `external_batch_report_generated`; stop condition
`external_batch_report_failed` (a report failure prints a warning and never undoes
the batch); metrics `external_batch_report_generated/_bytes/_path`.

# Loop Engineering — Stage 3.7

## What's new in 3.7 — External Agent Batch Operations

Operate on **many** external jobs at once, safely and in controlled batches
(`external_job_batch.py`). Select jobs by ID or filters, then run one action:

```bash
python3 main.py --batch-external-jobs --action list_selected --status WAITING_FOR_EXTERNAL_AGENT
python3 main.py --batch-external-jobs --action sync_completions --dry-run
python3 main.py --batch-external-jobs --action sync_completions
python3 main.py --batch-external-jobs --action archive --status APPROVED
python3 main.py --batch-external-jobs --action set_priority --priority urgent --label safety
python3 main.py --batch-external-jobs --action set_labels --labels reviewed,batch --job-ids 1,2,3
```

- **Actions:** `sync_completions`, `archive`, `unarchive`, `cancel`,
  `set_priority`, `add_label`, `remove_label`, `set_labels`, `clear_error`,
  `mark_needs_attention`, `list_selected`.
- **Filters:** `--job-ids 1,2,3`, `--status`, `--agent`, `--workspace`,
  `--priority`, `--label`, `--active`/`--archived`, `--limit N`.
- **`--dry-run` (every action):** prints the selection + intended action and
  changes nothing — no DB writes, no resume, no completion import, no reports,
  no status change, no loop rows, no Ollama.
- **`sync_completions`** finds each selected job's `completion.json`/`.txt` and
  imports it through the existing inbox → **ResumeEngine** flow (skips jobs with
  no/invalid completion and archived/cancelled jobs).

**Safety:** batches never touch jobs outside the selection, never delete files /
reports / DB rows, never auto-commit, never run external agents, never resume
archived/cancelled jobs or jobs without a valid completion, and always use the
ResumeEngine (no Reviewer/workspace bypass). New table
`external_job_batch_events`; gates `external_job_batch_selection_valid` /
`external_job_batch_action_safe`; stop condition `external_job_batch_invalid`;
metrics `external_batch_action_used/_action/_success/_skipped/_failed`. Batch
events appear in `--external-job`, `--show LOOP_ID`, and reports.

# Loop Engineering — Stage 3.6

## What's new in 3.6 — External Agent Completion Inbox

Resume completed external jobs by dropping a completion file into the job's
generated directory, then running one sync command — no need to pass the path:

```
external_agent_jobs/job_<id>/completion.json   # structured JSON (preferred)
external_agent_jobs/job_<id>/completion.txt     # plain-text fallback
```

```bash
python3 main.py --external-inbox                       # scan job dirs, show pending
python3 main.py --external-inbox --include-imported
python3 main.py --sync-external-completions --dry-run   # show what would import (no resume)
python3 main.py --sync-external-completions --limit 5   # import all pending
python3 main.py --sync-external-completion 12           # import one job
python3 main.py --external-job 12                        # shows inbox events
```

- **`completion.json`** is parsed as structured completion JSON (invalid JSON →
  recorded error, **not** resumed). **`completion.txt`** is the plain-text
  fallback. If both exist, `completion.json` is preferred and the `.txt` is
  reported as ignored.
- **`--dry-run`** shows what would import and changes nothing (no DB writes, no
  resume, no Reviewer, no reports).
- Every real import **routes through the `ResumeEngine`** — it re-validates the
  workspace and runs the Reviewer; the job status becomes the resume result
  (`APPROVED`/`BLOCKED`/`FAILED`/`REVIEWED`).

**Safety:** the inbox only scans `external_agent_jobs/job_<id>/` for the two known
filenames, rejects any file whose realpath escapes that directory (symlink
defense) and any arbitrary/wrong path, never executes or interprets completion
contents, never auto-commits unless explicitly requested, and never imports for
archived or cancelled jobs. New table `external_completion_inbox_events`; gate
`external_completion_inbox_valid`; stop condition `external_completion_inbox_invalid`;
metrics `external_completion_inbox_scanned/_pending_count/_imported_count/_failed_count`.

# Cross-Workstation Agent Handoff

This repo includes a portable handoff system so another agent can clone the
project and continue from the same pushed state without relying on local Codex
memory or ignored runtime artifacts.

```bash
git clone https://github.com/an5onc/loop-engineering.git
cd loop-engineering
git checkout main
git pull --ff-only
python3 agent_handoff.py --check
```

Before ending a session:

```bash
python3 -m py_compile *.py
python3 audit_hotfix.py
python3 agent_handoff.py --write
git add AGENTS.md HANDOFF.md agent_handoff.py test_agent_handoff.py README.md
git commit -m "Update agent handoff"
git push origin main
```

`AGENTS.md` defines the agent contract. `HANDOFF.md` is the portable current
handoff. `agent_handoff.py --check` verifies that the repo has the expected
remote, branch, and ignored runtime artifacts. Runtime databases, generated
reports, external job folders, and local `workspace/` smoke files are not part of
the portable handoff.

# Loop Engineering — Stage 5.0

## What's new in 5.0 — Loop Improvement Engine

Stage 5.0 adds the **Loop Improvement Engine** foundation. It reads saved
Observatory metadata and proposes safe, reviewable framework improvements for
loops, agents, prompts, quality gates, stop conditions, external-agent flows,
documentation, tests, and safety policy.

```bash
python3 main.py --loop-improvements
python3 main.py --loop-improvements --from-remediation
python3 main.py --loop-improvements --from-failures
python3 main.py --loop-improvements --priority high
python3 main.py --loop-improvements --target-type quality_gate
python3 main.py --loop-improvements --save-report
python3 main.py --loop-improvement-plans
python3 main.py --loop-improvement-plan latest
python3 main.py --loop-improvement-proposals
python3 main.py --loop-improvement-proposal latest
python3 main.py --set-loop-improvement-status latest accepted
```

Default source selection uses the latest action review when available, then the
latest remediation plan, then the latest failure drilldown. Explicit source
flags are available with `--action-review REVIEW_ID`, `--remediation-plan
PLAN_ID`, and `--failure-drilldown DRILLDOWN_ID`.

Supported proposal target types include `loop_definition`, `agent_definition`,
`prompt`, `quality_gate`, `stop_condition`, `workspace_profile`,
`external_agent_flow`, `observatory_flow`, `documentation`, `testing`,
`safety_policy`, and `unknown`. Proposal statuses are `proposed`, `accepted`,
`rejected`, `deferred`, and `converted_to_action`.

Each generated plan is saved in `loop_improvement_plans`; each proposal is saved
in `loop_improvement_proposals`. Optional Markdown reports are written under:

```
loop_improvement_reports/loop_improvements_<plan_id>_YYYYMMDD_HHMMSS.md
```

Safety: improvement plans are proposals only. They are not applied
automatically, status changes only update proposal metadata, and the engine never
executes commands, calls Ollama, mutates loop/agent/prompt/gate/stop-condition
definitions, creates external jobs, imports completions, resumes jobs, commits,
or reads protected file contents. The only writes are improvement metadata and
optional Markdown reports inside `loop_improvement_reports/`.

# Loop Engineering — Stage 5.1

## What's new in 5.1 — Loop Improvement Proposal Review

Stage 5.1 adds a deterministic review layer for saved improvement proposals.
It scores and groups proposals so operators can decide which items to accept,
defer, reject, or prepare for later manual action.

```bash
python3 main.py --loop-improvement-review
python3 main.py --loop-improvement-review --priority high
python3 main.py --loop-improvement-review --target-type quality_gate
python3 main.py --loop-improvement-review --group-by risk
python3 main.py --loop-improvement-review --save-report
python3 main.py --loop-improvement-reviews
python3 main.py --loop-improvement-review-show latest
```

Default review settings are `--status proposed`, `--group-by target_type`, and
`--limit 25`. Review filters include `--priority`, `--target-type`, `--status`,
and `--limit`. Grouping supports `target_type`, `priority`, `status`, and
`risk`.

Review scoring is deterministic. It considers priority, target type, proposal
status, risk, effort, affected loops/actions/remediation plans, and high-signal
targets such as `safety_policy`, `quality_gate`, `stop_condition`, `prompt`,
`testing`, and `external_agent_flow`.

Recommended decisions are `accept`, `defer`, `reject`, `convert_to_action`, and
`needs_more_evidence`. These are advisory only; proposal status changes still
require explicit commands such as:

```bash
python3 main.py --set-loop-improvement-status 12 accepted
python3 main.py --set-loop-improvement-status 12 deferred
python3 main.py --set-loop-improvement-status 12 rejected
```

Each generated review is saved in `loop_improvement_reviews`. Optional Markdown
reports are written under:

```
loop_improvement_review_reports/loop_improvement_review_<review_id>_YYYYMMDD_HHMMSS.md
```

Safety: proposal review never applies proposals automatically, executes
commands, calls Ollama, creates loops, creates external jobs, imports
completions, resumes jobs, commits, mutates definitions, or reads protected file
contents. It reads improvement proposal metadata only and writes only review
metadata plus optional Markdown reports inside
`loop_improvement_review_reports/`.

# Loop Engineering — Stage 5.2

## What's new in 5.2 — Loop Improvement Action Conversion

Stage 5.2 adds a safe bridge from reviewed improvement proposals to manual
action items. Operators can convert accepted, conversion-ready, urgent, or high
priority proposals from a saved improvement review into durable tracking records
without applying any framework change automatically.

```bash
python3 main.py --create-loop-improvement-actions latest
python3 main.py --create-loop-improvement-actions latest --priority high
python3 main.py --create-loop-improvement-actions latest --target-type quality_gate
python3 main.py --create-loop-improvement-actions latest --include-deferred
python3 main.py --create-loop-improvement-actions latest --include-rejected
python3 main.py --loop-improvement-actions
python3 main.py --loop-improvement-actions --status open
python3 main.py --loop-improvement-actions --priority high
python3 main.py --loop-improvement-actions --target-type quality_gate
python3 main.py --loop-improvement-action 1
python3 main.py --set-loop-improvement-action-status 1 in_progress
python3 main.py --set-loop-improvement-action-status 1 completed
python3 main.py --set-loop-improvement-action-notes 1 "Reviewed and accepted"
python3 main.py --loop-improvement-action-batches
python3 main.py --loop-improvement-action-batch latest
python3 main.py --loop-improvement-actions-report
```

Action statuses are `open`, `in_progress`, `completed`, `dismissed`, and
`blocked`; newly converted actions start as `open`. Status changes set
`updated_at`, with `completed_at` populated for completed actions and
`dismissed_at` populated for dismissed actions. Notes are stored as plain text
metadata only.

Conversion skips duplicates from the same `source_review_id` and
`source_proposal_id`, records `created`, `duplicate_skipped`, `status_changed`,
`notes_updated`, and `viewed` events, and saves batch metadata in
`loop_improvement_action_batches`.

Action queue reports are written under:

```
loop_improvement_action_reports/loop_improvement_actions_YYYYMMDD_HHMMSS.md
```

Safety: improvement actions are manual tracking records only. Conversion and
action commands never execute suggested commands, call Ollama, create loops,
create external jobs, apply proposals, mutate proposal status, commit, or mutate
loop/agent/prompt/quality-gate/stop-condition definitions.

# Loop Engineering — Stage 5.3

## What's new in 5.3 — Loop Improvement Implementation Handoff

Stage 5.3 adds a controlled bridge from manual loop-improvement actions to
implementation-ready handoffs. Handoffs turn action metadata into deterministic
implementation tasks, loop-task commands, external-agent job commands, or
Markdown implementation packets without applying improvements automatically.

```bash
python3 main.py --handoff-loop-improvement-action 1
python3 main.py --handoff-loop-improvement-action 1 --type dry_run_plan
python3 main.py --handoff-loop-improvement-action 1 --type implementation_packet
python3 main.py --handoff-loop-improvement-action 1 --type loop_task
python3 main.py --handoff-loop-improvement-action 1 --type loop_task --confirm-create-loop
python3 main.py --handoff-loop-improvement-action 1 --type external_agent_job --external-coder codex
python3 main.py --handoff-loop-improvement-action 1 --type external_agent_job --external-coder codex --confirm-create-external-job
python3 main.py --loop-improvement-handoffs
python3 main.py --loop-improvement-handoff 1
```

Default handoff mode is `dry_run_plan`. It saves handoff metadata and prints the
manual command that would be used; it does not create a loop, create an external
job, call Ollama, execute commands, edit files, or mutate definitions.

`implementation_packet` creates a structured Markdown packet under:

```
loop_improvement_handoff_packets/loop_improvement_handoff_ACTIONID_YYYYMMDD_HHMMSS.md
```

The packet includes source action/proposal IDs, implementation scope, generated
task, safety constraints, suggested manual commands, a review checklist, and
next steps. Implementation scopes are inferred from proposal target type, such
as `quality_gate_update`, `prompt_contract_update`, `testing_update`,
`external_agent_flow_update`, and `observability_update`.

`loop_task` and `external_agent_job` remain dry-run handoffs unless explicitly
confirmed with `--confirm-create-loop` or `--confirm-create-external-job`.
Confirmed creation routes through existing Loop Engineering pathways and keeps
their workspace, approval, command, Git, and external-agent safety checks.

Safety: improvement handoffs never execute suggested commands, never auto-commit,
never run Claude/Codex automatically, never bypass approvals/workspace profiles,
and never mutate loop definitions, agent definitions, prompts, quality gates,
stop conditions, jobs, or workspace files from dry-run or packet generation.

# Loop Engineering — Stage 5.4

## What's new in 5.4 — Loop Improvement Handoff Review

Stage 5.4 adds a deterministic review layer for saved loop-improvement
handoffs. It classifies handoffs before manual execution, groups them for
inspection, persists review metadata, and can write optional Markdown reports
without executing suggested commands or creating loops/jobs.

```bash
python3 main.py --loop-improvement-handoff-review
python3 main.py --loop-improvement-handoff-review --status suspicious
python3 main.py --loop-improvement-handoff-review --type implementation_packet
python3 main.py --loop-improvement-handoff-review --implementation-scope quality_gate_update
python3 main.py --loop-improvement-handoff-review --target-type quality_gate
python3 main.py --loop-improvement-handoff-review --workspace default
python3 main.py --loop-improvement-handoff-review --external-coder codex
python3 main.py --loop-improvement-handoff-review --group-by type --limit 10
python3 main.py --loop-improvement-handoff-review --save-report
python3 main.py --loop-improvement-handoff-reviews
python3 main.py --loop-improvement-handoff-review-show latest
```

Review statuses include `safe_dry_run`, `safe_packet`, `needs_review`,
`ready_for_manual_execution`, `confirmed_loop_created`,
`confirmed_external_job_created`, `blocked`, `suspicious`, and `unknown`.
Recommended decisions include `inspect`, `approve_for_manual_execution`,
`defer`, `block`, `archive`, and `needs_more_evidence`.

Saved review rows live in `loop_improvement_handoff_reviews`. Optional Markdown
reports are written under:

```
loop_improvement_handoff_review_reports/loop_improvement_handoff_review_REVIEWID_YYYYMMDD_HHMMSS.md
```

Safety: handoff review reads saved handoff/action/proposal metadata only. It
does not execute suggested commands, call Ollama, create loops, create external
jobs, mutate handoffs, mutate improvement definitions, edit workspace files, or
read protected file contents.

# Loop Engineering - Stage 6.5

## What's new in 6.9 - Stage 6 Final Audit and Stage 7 Readiness

Stage 6.9 adds the final Controlled Self-Improvement audit. It verifies that
the Stage 6 subsystem is safe, complete, deterministic, auditable, and ready for
Stage 7 planning. The final chain is:

```
application plan -> patch proposal -> dry-run validation -> human approval
-> safe application attempt -> rollback snapshot / restore preview
-> post-apply verification -> outcome tracking -> self-improvement audit
-> final Stage 6 audit
```

```bash
python3 main.py --loop-improvement-stage6-audit
python3 main.py --loop-improvement-stage6-audit --save-report
python3 main.py --loop-improvement-stage6-audits
python3 main.py --loop-improvement-stage6-audit-show latest
```

Audit sections cover application planning, patch proposal generation, dry-run
validation, human approval, safe application, rollback snapshots, post-apply
verification, outcome tracking, self-improvement audit, safety baseline, and
Stage 7 readiness. Overall statuses are `PASS`, `PASS_WITH_WARNINGS`, `FAIL`,
and `BLOCKED`; check and section statuses are `PASS`, `WARN`, `FAIL`, and
`BLOCKED`.

Each final audit is saved in `loop_improvement_stage6_audits`. Optional
Markdown reports are written under:

```
loop_improvement_stage6_audit_reports/loop_improvement_stage6_audit_AUDITID_YYYYMMDD_HHMMSS.md
```

The Stage 7 readiness block reports readiness, blockers, warnings, recommended
Stage 7 theme, and required safety controls. The recommended Stage 7 theme is
`Multi-Project Operations`. Required Stage 7 controls include project registry,
workspace isolation, per-project safety profiles, no cross-project writes
without approval, project-specific audit trails, controlled scheduling, no
hidden model or command execution, and explicit user approval before cross-repo
changes.

Safety: Stage 6.9 never executes commands, runs tests automatically, writes
`command_results`, calls Ollama, applies patches, restores files, edits source
files, creates loops, creates external jobs, imports completions, resumes jobs,
commits, or mutates loop definitions, agent definitions, prompts, quality gates,
stop conditions, workspace profiles, jobs, or workspace files. It reads only
Stage 6 metadata plus safe SQLite schema metadata and writes only Stage 6 final
audit metadata plus optional Markdown reports.

## What's new in 6.8 - Self-Improvement Audit

Stage 6.8 audits the controlled self-improvement chain for safety,
completeness, and readiness before the Stage 6 final audit. It checks the full
metadata path:

```
application plan -> patch proposal -> dry-run validation -> human approval
-> safe application attempt -> rollback snapshot -> post-apply verification
-> outcome tracking
```

```bash
python3 main.py --self-improvement-audit
python3 main.py --self-improvement-audit --save-report
python3 main.py --self-improvement-audits
python3 main.py --self-improvement-audit-show latest
```

Audit sections cover application planning, patch proposals, dry-run validation,
human approval, safe application, rollback, post-apply verification, outcome
tracking, safety baseline, and Stage 6 final readiness. Statuses are `PASS`,
`PASS_WITH_WARNINGS`, `FAIL`, and `BLOCKED`; check and section statuses are
`PASS`, `WARN`, `FAIL`, and `BLOCKED`.

Each audit is saved in `self_improvement_audits`. Optional Markdown reports are
written under:

```
self_improvement_audit_reports/self_improvement_audit_AUDITID_YYYYMMDD_HHMMSS.md
```

The Stage 6 final readiness block reports `ready`, blockers, warnings,
recommended next stage (`Stage 6.9`), and required final audit controls. It is a
readiness signal only; Stage 6.8 does not advance or apply any improvement.

Safety: Stage 6.8 never executes commands, runs tests automatically, writes
`command_results`, calls Ollama, applies patches, restores files, edits source
files, creates loops, creates external jobs, imports completions, resumes jobs,
commits, or mutates loop definitions, agent definitions, prompts, quality gates,
stop conditions, workspace profiles, jobs, or workspace files. It reads only
Stage 6 metadata plus safe SQLite schema metadata and writes only self-audit
metadata plus optional Markdown reports.

## What's new in 6.7 - Improvement Outcome Tracker

Stage 6.7 records deterministic outcome metadata after controlled
self-improvement application and post-apply verification. It connects the saved
metadata chain from application plan to patch proposal, dry-run validation,
approval, application attempt, rollback snapshot, post-apply verification, and
outcome record. It answers whether the improvement appears successful, whether
verification passed, whether rollback is recommended, how risk changed, and what
should be learned for future improvements.

```bash
python3 main.py --record-improvement-outcome latest
python3 main.py --improvement-outcomes
python3 main.py --improvement-outcome latest
python3 main.py --improvement-outcome-report latest
python3 main.py --improvement-outcome-report latest --save-report
python3 main.py --set-improvement-outcome-status latest successful_with_warnings
```

Outcome statuses are `successful`, `successful_with_warnings`,
`failed_verification`, `rollback_recommended`, `rolled_back`, `inconclusive`,
`blocked`, and `deferred`. Missing or pending verification defaults to
`inconclusive`. The deterministic success score ranges from 0 to 100 and is
derived from verification status, rollback metadata, and metadata completeness.

Signals include application attempt, approval, patch proposal, rollback
snapshot, verification plan/report, verification pass/fail, rollback need,
safety completeness, missing metadata, and manual follow-up. Manual status
updates only update outcome metadata; they do not apply patches, rollback files,
run commands, commit, or mutate framework definitions.

Outcome records are saved in `improvement_outcome_records`; generated reports
are saved in `improvement_outcome_reports`. Optional Markdown reports are
written under:

```
improvement_outcome_reports/improvement_outcome_REPORTID_YYYYMMDD_HHMMSS.md
```

Safety: Stage 6.7 never executes commands, runs tests automatically, writes
`command_results`, calls Ollama, applies patches, restores files, edits source
files, creates loops, creates external jobs, imports completions, resumes jobs,
commits, or mutates loop definitions, agent definitions, prompts, quality gates,
stop conditions, workspace profiles, jobs, or workspace files. It reads metadata
only and writes outcome metadata plus optional Markdown reports.

## What's new in 6.6 - Post-Apply Verification Runner

Stage 6.6 creates metadata-only post-apply verification plans and reports for
existing Stage 6.4 application attempts. It infers manual verification commands,
focused tests, documentation checks, risk level, blockers, warnings, and next
steps. It never executes commands, writes source files, applies patches, restores
files, calls Ollama, creates loops, creates external jobs, commits, or mutates
framework definitions.

```bash
python3 main.py --create-post-apply-verification-plan latest
python3 main.py --post-apply-verification-plans
python3 main.py --post-apply-verification-plan latest
python3 main.py --post-apply-verification-report latest
python3 main.py --post-apply-verification-report latest --save-report
python3 main.py --set-post-apply-verification-status latest manually_verified
```

Each plan is saved in `post_apply_verification_plans`; each generated report is
saved in `post_apply_verification_reports`. Optional Markdown reports are
written under:

```
post_apply_verification_reports/post_apply_verification_REPORTID_YYYYMMDD_HHMMSS.md
```

Recommended verification commands are stored as text only. Stage 6.6 does not
create `command_results`; operators must run commands manually in an approved
environment and then set the plan status to `manually_verified`, `failed`,
`blocked`, or `deferred`.

Safety: Stage 6.6 preserves dry-run, human approval, patch preview, rollback,
file allowlist, workspace profile, command allowlist, no-auto-commit, and audit
requirements from earlier Stage 6 gates. Failure must stop and preserve rollback
path. There is no autonomous recursive self-modification, hidden model call, or
hidden external-agent execution.

## What's new in 6.5 - Rollback Snapshot and Restore Preview

Stage 6.5 creates rollback snapshots for guarded Stage 6.4 application
attempts. Snapshot creation reads only the allowlisted target files named by the
application attempt, stores their content in the local ignored SQLite database,
and records a manifest with file existence, size, and SHA-256 hashes. Markdown
reports include metadata and hashes only, not file contents.

```bash
python3 main.py --create-loop-improvement-rollback-snapshot latest
python3 main.py --create-loop-improvement-rollback-snapshot latest --save-report
python3 main.py --loop-improvement-rollback-snapshots
python3 main.py --loop-improvement-rollback-snapshot latest
python3 main.py --preview-loop-improvement-rollback-restore latest
```

Each snapshot is saved in `loop_improvement_rollback_snapshots`, with per-file
entries in `loop_improvement_rollback_snapshot_files` and an event log in
`loop_improvement_rollback_snapshot_events`. Optional Markdown reports are
written under:

```
loop_improvement_rollback_snapshot_reports/loop_improvement_rollback_snapshot_SNAPSHOTID_YYYYMMDD_HHMMSS.md
```

Snapshots always record `applies_changes=false`, `restores_files=false`,
`executes_commands=false`, and `commits_changes=false`. Restore preview records
an audit event but does not restore files.

Safety: Stage 6.5 blocks absolute paths, path traversal, and protected path
fragments. It does not generate patches, write target files, restore files,
execute commands, call Ollama, create loops, create external jobs, commit, apply
improvements, mutate framework definitions, or execute suggested commands.

# Loop Engineering - Stage 6.4

## What's new in 6.4 - Safe Patch Application Engine

Stage 6.4 introduces a guarded patch application attempt engine. It accepts an
approved Stage 6.3 approval record, resolves the approved patch proposal target
files, and creates an auditable application attempt. Because rollback snapshots
are introduced in Stage 6.5, Stage 6.4 fails closed with
`blocked_rollback_required` before any file write.

```bash
python3 main.py --attempt-loop-improvement-patch-application latest
python3 main.py --attempt-loop-improvement-patch-application latest --save-report
python3 main.py --loop-improvement-patch-application-attempts
python3 main.py --loop-improvement-patch-application-attempt latest
```

Each application attempt is saved in
`loop_improvement_patch_application_attempts` with an event log in
`loop_improvement_patch_application_attempt_events`. Optional Markdown reports
are written under:

```
loop_improvement_patch_application_reports/loop_improvement_patch_application_ATTEMPTID_YYYYMMDD_HHMMSS.md
```

Application attempts always record `applies_changes=false`,
`writes_files=false`, `executes_commands=false`, `commits_changes=false`, and
`generates_patch=false` until rollback snapshots and later apply controls are
implemented.

Safety: Stage 6.4 verifies approved metadata and records blockers only. It does
not generate patches, write files, edit files, execute commands, call Ollama,
create loops, create external jobs, commit, apply improvements, mutate
framework definitions, or execute suggested commands. It writes only application
attempt metadata and optional Markdown reports.

# Loop Engineering - Stage 6.3

## What's new in 6.3 - Human Approval for Patch Application

Stage 6.3 records explicit human approval decisions for patch proposals that
passed Stage 6.2 dry-run validation. A passing validation can create a pending
approval request, and a separate status command can record `approved`,
`rejected`, or `cancelled`. Approval recording is metadata only; even an
`approved` status does not apply changes.

```bash
python3 main.py --request-loop-improvement-patch-approval latest
python3 main.py --request-loop-improvement-patch-approval latest --save-report
python3 main.py --loop-improvement-patch-approvals
python3 main.py --loop-improvement-patch-approval latest
python3 main.py --set-loop-improvement-patch-approval-status latest approved "reviewed manually"
```

Each approval request is saved in `loop_improvement_patch_approvals` with an
event log in `loop_improvement_patch_approval_events`. Optional Markdown
reports are written under:

```
loop_improvement_patch_approval_reports/loop_improvement_patch_approval_APPROVALID_YYYYMMDD_HHMMSS.md
```

Approval records always store `applies_changes=false`, `generates_patch=false`,
`executes_commands=false`, and `auto_approved=false`. Failed dry-run validations
cannot create approval requests.

Safety: Stage 6.3 uses saved dry-run validation metadata only. It does not
generate patches, write patch files, edit files, execute commands, call Ollama,
create loops, create external jobs, commit, apply improvements, mutate
framework definitions, or execute suggested commands. It writes only approval
metadata and optional Markdown reports.

# Loop Engineering - Stage 6.2

## What's new in 6.2 - Dry-Run Patch Validator

Stage 6.2 validates saved Stage 6.1 patch proposals before any future patch
generation. It checks proposal eligibility, metadata-only safety flags, target
file metadata, relative file allowlist rules, protected-path exclusions, human
approval requirements, rollback requirements, and the no-command/no-file-content
dry-run boundary.

```bash
python3 main.py --validate-loop-improvement-patch-proposal latest
python3 main.py --validate-loop-improvement-patch-proposal latest --save-report
python3 main.py --loop-improvement-patch-dry-runs
python3 main.py --loop-improvement-patch-dry-run latest
```

Each dry-run validation is saved in
`loop_improvement_patch_dry_run_validations` with child rows in
`loop_improvement_patch_dry_run_checks` and an event log in
`loop_improvement_patch_dry_run_validation_events`. Optional Markdown reports
are written under:

```
loop_improvement_patch_dry_run_reports/loop_improvement_patch_dry_run_VALIDATIONID_YYYYMMDD_HHMMSS.md
```

Dry-run validations always record `generates_patch=false`,
`applies_changes=false`, `executes_commands=false`, and
`reads_file_contents=false`. A failed validation returns a non-zero CLI status
after saving the validation record, so blockers remain auditable.

Safety: Stage 6.2 uses saved patch-proposal metadata only. It does not read
source file contents, generate patches, write patch files, edit files, execute
commands, call Ollama, create loops, create external jobs, commit, apply
improvements, mutate framework definitions, or execute suggested commands. It
writes only dry-run validation metadata and optional Markdown reports.

# Loop Engineering - Stage 6.1

## What's new in 6.1 - Patch Proposal Generator

Stage 6.1 converts a saved Stage 6.0 application plan into a metadata-only
patch proposal. It breaks the application plan into per-target-file patch
intent items and records the strategy, required approvals, rollback
requirements, validation requirements, and safety notes needed before any later
stage can generate a real patch.

```bash
python3 main.py --generate-loop-improvement-patch-proposal latest
python3 main.py --generate-loop-improvement-patch-proposal latest --save-report
python3 main.py --loop-improvement-patch-proposals
python3 main.py --loop-improvement-patch-proposal latest
```

Each patch proposal is saved in `loop_improvement_patch_proposals` with child
rows in `loop_improvement_patch_proposal_items` and an event log in
`loop_improvement_patch_proposal_events`. Optional Markdown reports are written
under:

```
loop_improvement_patch_proposal_reports/loop_improvement_patch_proposal_PROPOSALID_YYYYMMDD_HHMMSS.md
```

Patch proposals always record `generates_unified_diff=false`,
`writes_patch_file=false`, `applies_changes=false`, and
`reads_file_contents=false`.

Safety: Stage 6.1 uses saved application-plan metadata only. It does not read
source file contents, generate unified diffs, write patch files, edit files,
execute commands, call Ollama, create loops, create external jobs, commit,
apply improvements, mutate framework definitions, or execute suggested
commands. It writes only patch-proposal metadata and optional Markdown reports.

# Loop Engineering - Stage 6.0

## What's new in 6.0 - Approved Improvement Application Planner

Stage 6.0 starts Controlled Self-Improvement with a metadata-only application
planner. It reads reviewed Loop Improvement actions, handoffs, or handoff
reviews and creates a structured application plan for a future human-controlled
patch workflow.

```bash
python3 main.py --plan-loop-improvement-application latest
python3 main.py --plan-loop-improvement-application latest --source-type handoff
python3 main.py --plan-loop-improvement-application latest --source-type handoff_review --save-report
python3 main.py --loop-improvement-application-plans
python3 main.py --loop-improvement-application-plan latest
```

Each application plan is saved in `loop_improvement_application_plans` with
child rows in `loop_improvement_application_plan_items` and an event log in
`loop_improvement_application_plan_events`. Optional Markdown reports are
written under:

```
loop_improvement_application_plan_reports/loop_improvement_application_plan_PLANID_YYYYMMDD_HHMMSS.md
```

Application plans include target file lists, patch intent summaries, risk
assessments, required approvals, rollback requirements, validation
requirements, safety notes, and manual next commands. Plans always record
`generates_patch=false` and `applies_changes=false`.

Safety: Stage 6.0 does not generate patches, edit files, execute commands, call
Ollama, create loops, create external jobs, commit, apply improvements, mutate
loop definitions, mutate agent definitions, mutate prompts, mutate quality
gates, mutate stop conditions, mutate workspace profiles, or execute suggested
handoff commands. It writes only application-plan metadata and optional Markdown
reports.

# Loop Engineering — Stage 5.5

## What's new in 5.5 — Stage 5 Final Audit and Stage 6 Readiness

Stage 5.5 adds a final audit layer for the full Loop Improvement subsystem. It
checks the improvement engine, proposal review, action conversion,
implementation handoff, handoff review, safety baseline, and Stage 6 readiness
without applying improvements or executing any suggested command.

```bash
python3 main.py --loop-improvement-stage5-audit
python3 main.py --loop-improvement-stage5-audit --save-report
python3 main.py --loop-improvement-stage5-audits
python3 main.py --loop-improvement-stage5-audit-show latest
```

Each audit is saved in `loop_improvement_stage5_audits`. Optional Markdown
reports are written under:

```
loop_improvement_stage5_audit_reports/loop_improvement_stage5_audit_AUDITID_YYYYMMDD_HHMMSS.md
```

The audit uses `PASS`, `WARN`, and `FAIL` checks. Overall status is `FAIL` if
any section fails, `PASS WITH WARNINGS` when warnings remain, and `PASS` only
when every check passes. Stage 6 readiness reports `ready: yes/no`, blockers,
warnings, the recommended next stage, and required Stage 6 safety controls.

Required Stage 6 safety controls are explicit human approval before applying any
improvement, rollback planning for each applied framework change, audit logging
for every decision and mutation, dry-run-first behavior, and preservation of
filesystem, command, Git, workspace, approval, and external-agent safety gates.

Safety: the Stage 5 audit reads SQLite metadata and generated artifact metadata
only. It never calls Ollama, executes commands, creates loops, creates external
jobs, imports completions, resumes jobs, commits, applies proposals, mutates
actions or handoffs except audit metadata, mutates framework definitions, or
reads protected file contents.

# Loop Engineering — Stage 4.9

## What's new in 4.9 — Stage 4 Final Audit and Readiness

Stage 4 Final Audit summarizes the full Observatory subsystem and produces a
Stage 5 readiness view. It checks Stage 4 metadata coverage, saved reports,
action and handoff review layers, and safety invariants without executing
commands, calling Ollama, creating loops/jobs, importing completions, resuming
jobs, or committing.

```bash
python3 main.py --observatory-stage4-audit
python3 main.py --observatory-stage4-audit --save-report
python3 main.py --observatory-stage4-audits
python3 main.py --observatory-stage4-audit-show latest
```

Each audit is saved in `observatory_stage4_audits`. Optional Markdown reports
are written under:

```
observatory_stage4_audit_reports/observatory_stage4_audit_<audit_id>_YYYYMMDD_HHMMSS.md
```

The readiness summary reports `ready: yes/no`, blockers, warnings, and the
recommended next stage. `PASS` means Stage 4 metadata is complete, `PASS WITH
WARNINGS` means Stage 5 can be planned with noted follow-ups, and `FAIL` means
blockers should be resolved before Stage 5.

Safety: the audit reads SQLite metadata and generated artifact metadata only.
The only writes are audit metadata and optional Markdown reports inside the
Stage 4 audit reports directory.

# Loop Engineering — Stage 4.8

## What's new in 4.8 — Observatory Action Handoff Review

Action Handoff Review audits saved handoffs before broader use. It reads only
handoff/action metadata, classifies each handoff deterministically, groups the
results, stores review snapshots, and can export a Markdown review. It does not
execute suggested commands, call Ollama, create loops, create external jobs,
resume work, import completions, or commit.

```bash
python3 main.py --observatory-action-handoff-review
python3 main.py --observatory-action-handoff-review --status safe_dry_run
python3 main.py --observatory-action-handoff-review --type external_agent_job
python3 main.py --observatory-action-handoff-review --workspace loop-engineering
python3 main.py --observatory-action-handoff-review --external-coder codex
python3 main.py --observatory-action-handoff-review --group-by status
python3 main.py --observatory-action-handoff-review --group-by type
python3 main.py --observatory-action-handoff-review --group-by workspace
python3 main.py --observatory-action-handoff-review --save-report
python3 main.py --observatory-action-handoff-reviews
python3 main.py --observatory-action-handoff-review-show latest
```

Review statuses are `safe_dry_run`, `needs_review`,
`confirmed_loop_created`, `confirmed_external_job_created`, `blocked`,
`suspicious`, and `unknown`. Default review settings are `--limit 25` and
`--group-by status`.

Each review is saved in `observatory_action_handoff_reviews`. Optional Markdown
reports are written under:

```
observatory_action_handoff_review_reports/observatory_action_handoff_review_<review_id>_YYYYMMDD_HHMMSS.md
```

Safety: handoff review never executes handoff suggested commands and never
creates loops/jobs. The only writes are review metadata and optional Markdown
reports inside the handoff review reports directory.

# Loop Engineering — Stage 4.7

## What's new in 4.7 — Observatory Action Execution Handoff

Action Handoff converts a selected Observatory action into a reviewable task for
manual execution, a future loop task, or a future external-agent job. The default
is dry-run only: it stores handoff metadata, prints the generated task, and does
not execute suggested commands, call Ollama, create loops, create external jobs,
or commit.

```bash
python3 main.py --handoff-observatory-action ACTION_ID
python3 main.py --handoff-observatory-action ACTION_ID --type dry_run_plan
python3 main.py --handoff-observatory-action ACTION_ID --type loop_task --loop-type code_review
python3 main.py --handoff-observatory-action ACTION_ID --type external_agent_job --external-coder codex
python3 main.py --handoff-observatory-action ACTION_ID --type loop_task --confirm-create-loop
python3 main.py --handoff-observatory-action ACTION_ID --type external_agent_job --external-coder codex --confirm-create-external-job
python3 main.py --observatory-action-handoffs
python3 main.py --observatory-action-handoff HANDOFF_ID
python3 main.py --observatory-action ACTION_ID
```

Handoff types are `dry_run_plan`, `loop_task`, and `external_agent_job`.
`--observatory-action ACTION_ID` shows linked handoffs and copyable dry-run
handoff commands. Every handoff is persisted in `observatory_action_handoffs`
with an event row in `observatory_action_handoff_events`.

Safety: generated tasks include source action metadata and preserve suggested
commands as context only. Loop creation happens only with `--confirm-create-loop`
and then uses the normal Loop Engineering runner, including Ollama, approvals,
workspace checks, and optional explicit `--commit`. External job creation happens
only with `--confirm-create-external-job`; it writes a normal Stage 3 job packet
and leaves the external agent waiting for a manual handoff.

# Loop Engineering — Stage 4.6

## What's new in 4.6 — Observatory Action Review

Action Review scores and groups manual Observatory actions so the next review
step is clear without executing anything. Scores are deterministic and based on
priority, category, risk, effort, status, affected loops/jobs, and whether a
suggested command exists. Safety, reliability, and external-agent health actions
rank higher; completed and dismissed actions rank lower unless explicitly
included with filters.

```bash
python3 main.py --observatory-action-review
python3 main.py --observatory-action-review --priority high
python3 main.py --observatory-action-review --category safety
python3 main.py --observatory-action-review --group-by risk
python3 main.py --observatory-action-review --save-report
python3 main.py --observatory-action-reviews
python3 main.py --observatory-action-review-show 1
python3 main.py --observatory-action-review-show latest
```

Grouping options are `category`, `priority`, `status`, and `risk`. Every review
run saves an `observatory_action_reviews` row. Optional Markdown reports are
written under:

```
observatory_action_review_reports/observatory_action_review_<review_id>_YYYYMMDD_HHMMSS.md
```

Safety: action review reads action metadata only. Suggested commands are printed
as manual next steps and are never executed; no models are called and no
loops/jobs/external jobs are mutated.

# Loop Engineering — Stage 4.5

## What's new in 4.5 — Observatory Action Queue

The Observatory Action Queue turns saved remediation plan items into durable
manual action records. Actions keep the suggested command, evidence, priority,
category, affected loops/jobs, notes, and status history, but they never execute
the suggested command or apply fixes automatically.

```bash
python3 main.py --create-observatory-actions latest
python3 main.py --observatory-actions
python3 main.py --observatory-actions --priority high
python3 main.py --observatory-actions --category safety
python3 main.py --observatory-action 1
python3 main.py --set-observatory-action-status 1 in_progress
python3 main.py --set-observatory-action-status 1 completed
python3 main.py --set-observatory-action-notes 1 "Reviewed and deferred"
python3 main.py --observatory-actions-report
```

Statuses are `open`, `in_progress`, `completed`, `dismissed`, and `blocked`.
Every creation, duplicate skip, view, status change, and notes update is recorded
in `observatory_action_events`. Action reports are generated under:

```
observatory_action_reports/observatory_actions_YYYYMMDD_HHMMSS.md
```

Safety: action queue commands only write action metadata/events and optional
Markdown reports. They do not call Ollama, execute commands, mutate loops/jobs,
import completions, resume work, commit, or read protected file contents.

# Loop Engineering — Stage 4.4

## What's new in 4.4 — Observatory Remediation Plans

Remediation Plans turn existing observatory snapshots, trend reports, and failure
drilldowns into structured, reviewable improvement plans. They are metadata-only:
no Ollama calls, command execution, loop creation, job mutation, completion
import, resume, commit, or protected file reads. Suggested commands are printed
for manual review and are never executed by the remediation planner.

Supported sources:

```bash
python3 main.py --observatory-remediation
python3 main.py --observatory-remediation --snapshot 1
python3 main.py --observatory-remediation --from-failures
python3 main.py --observatory-remediation --failure-drilldown 1
python3 main.py --observatory-remediation --from-trends
python3 main.py --observatory-remediation --trend-report 1
```

Plans can be filtered by priority or category:

```bash
python3 main.py --observatory-remediation --priority high
python3 main.py --observatory-remediation --category safety
python3 main.py --observatory-remediation --limit 10
```

Priorities are `urgent`, `high`, `medium`, and `low`. Categories include
`safety`, `reliability`, `model_quality`, `reviewer_quality`,
`workspace_configuration`, `approval_flow`, `external_agent_queue`,
`external_agent_health`, `reporting`, `observability`, `database_integrity`,
`documentation`, `testing`, and `unknown`.

Every remediation run saves an `observatory_remediation_plans` row. Use:

```bash
python3 main.py --observatory-remediation-plans
python3 main.py --observatory-remediation-plan 1
python3 main.py --observatory-remediation-plan latest
```

Markdown export is optional:

```bash
python3 main.py --observatory-remediation --save-report
```

Reports are generated internally under:

```
observatory_remediation_reports/observatory_remediation_<plan_id>_YYYYMMDD_HHMMSS.md
```

# Loop Engineering — Stage 4.3

## What's new in 4.3 — Observatory Failure Drilldown

Failure Drilldown makes failed, blocked, paused, and human-needed loops
inspectable from SQLite. It groups failures by root cause category, loop type,
workspace, agent, quality gate, stop condition, and external job state without
calling Ollama, executing commands, creating loops, resuming jobs, importing
completions, committing, mutating jobs, or reading protected file contents.

Failure categories include `model_output_invalid`, `reviewer_rejected`,
`reviewer_inconsistent`, `quality_gate_failed`, `stop_condition_triggered`,
`command_failed`, `command_blocked`, `filesystem_blocked`,
`workspace_violation`, `approval_declined`, `needs_clarification`,
`external_agent_waiting`, `external_agent_failed`, `external_job_health`,
`report_generation_failed`, and `unknown`.

```bash
python3 main.py --observatory-failures
python3 main.py --observatory-failures --category quality_gate_failed
python3 main.py --observatory-failures --cluster-by workspace
python3 main.py --observatory-failures --cluster-by quality_gate
python3 main.py --observatory-failures --save-report
python3 main.py --observatory-failure-drilldowns
python3 main.py --observatory-failure-drilldown 1
python3 main.py --observatory-failure-drilldown latest
```

Every `--observatory-failures` run saves an
`observatory_failure_drilldowns` row. `--save-report` additionally writes
Markdown under:

```
observatory_failure_reports/observatory_failures_<drilldown_id>_YYYYMMDD_HHMMSS.md
```

Markdown paths are generated internally and confined to
`observatory_failure_reports/`.

# Loop Engineering — Stage 4.2

## What's new in 4.2 — Observatory Trend Analysis

Observatory Trends compare saved `observatory_snapshots` over time and report
whether loop health, approvals, failures, blocked runs, external jobs, and safety
signals are improving, worsening, or flat. Trend analysis only reads snapshot
JSON and writes trend metadata; it does not call Ollama, execute commands, create
loops, resume jobs, import completions, mutate jobs, commit, or read protected
file contents.

Tracked metrics include total/approved/failed/blocked/needs-human loops, paused
external loops, external job totals and waiting/blocked/failed counts, reports,
approvals, declined approvals, quality gate failures, stop condition triggers,
and snapshot alert counts.

```bash
python3 main.py --observatory-trends
python3 main.py --observatory-trends --limit 20
python3 main.py --observatory-trends --metric blocked_loops
python3 main.py --observatory-trends --save-report
python3 main.py --observatory-trend-reports
python3 main.py --observatory-trend-report 1
python3 main.py --observatory-trend-report latest
```

Every `--observatory-trends` run saves an `observatory_trend_reports` row.
`--save-report` additionally writes Markdown under:

```
observatory_trend_reports/observatory_trends_<report_id>_YYYYMMDD_HHMMSS.md
```

Trend output includes summary, key trends, alerts, recommendations, and safety
notes. Markdown paths are generated internally and confined to
`observatory_trend_reports/`.

# Loop Engineering — Stage 4.1

## What's new in 4.1 — Observatory Markdown Reports

Observatory snapshots can now be exported as durable Markdown reports under:

```
observatory_reports/observatory_snapshot_<snapshot_id>_YYYYMMDD_HHMMSS.md
```

Reports are generated from persisted `observatory_snapshots` JSON only. Paths are
created internally and confined to `observatory_reports/`; report generation does
not run commands, call Ollama, start loops, resume jobs, import completions,
commit, mutate jobs, or mutate loop rows.

```bash
python3 main.py --observatory --save-report
python3 main.py --observatory --window 7d --save-report
python3 main.py --observatory-reports
python3 main.py --observatory-report 1
python3 main.py --observatory-report latest
```

Default `--observatory` behavior is unchanged: it saves a SQLite snapshot only.
Use `--save-report` to generate a report immediately, or
`--observatory-report SNAPSHOT_ID` to generate/read a report later. If report
metadata exists but the file is missing, the report is regenerated from the saved
snapshot. `--observatory-snapshot SNAPSHOT_ID` shows the linked report path when
one exists.

# Loop Engineering — Stage 4.0

## What's new in 4.0 — Loop Observatory

Stage 4.0 adds a local **Loop Observatory** foundation: a read-only CLI
observability layer over the SQLite database. It summarizes loops, agents,
workspaces, external jobs, reports, failures, approvals, retries, quality gates,
stop conditions, and safety events. It does not run commands, call Ollama,
execute external agents, import completions, resume jobs, commit, or read
protected file contents.

```bash
python3 main.py --observatory
python3 main.py --observatory --window 24h
python3 main.py --observatory --window 7d
python3 main.py --observatory --workspace loop-engineering
python3 main.py --observatory --loop-type code_build
python3 main.py --observatory --agent claude
```

Supported windows are `all` (default), `today`, `24h`, `7d`, and `30d`.
Filters may be combined with a time window.

The observatory prints: summary counts, top loop types with approval/failure
rates, top external agents, top workspaces, top failure reasons, external job
health counts, alerts, and exact next-action commands such as:

```bash
python3 main.py --external-dashboard
python3 main.py --external-health
python3 main.py --external-jobs --needs-attention
python3 main.py --history --limit 10
python3 main.py --reports
```

Every `--observatory` run saves a SQLite-only snapshot in
`observatory_snapshots`; no loop is created for viewing observability data.

```bash
python3 main.py --observatory-snapshots
python3 main.py --observatory-snapshot 1
python3 main.py --observatory-snapshot latest
```

# Loop Engineering — Stage 3 Final Cleanup

## Cleanup commands before Stage 4

Stage 3 final cleanup keeps the external-agent subsystem quiet after audit
fixtures have done their job. These commands are maintenance-only: they do not
run external agents, call Ollama, commit, delete files, or loosen safety gates.

```bash
python3 main.py --quarantine-health-fixtures --dry-run
python3 main.py --quarantine-health-fixtures
python3 main.py --check-portable-paths
python3 main.py --repair-portable-paths --dry-run
python3 main.py --repair-portable-paths
```

`--quarantine-health-fixtures` only matches controlled Stage 3.9 health-test jobs
identified by the `stage39-health` label or `stage39 health scenario:` loop task.
It archives and labels those jobs instead of deleting rows or job folders, and it
records a job event explaining the quarantine.

`--check-portable-paths` reports stale absolute metadata paths in run reports,
external jobs, external events, completion inbox events, and batch reports.
`--repair-portable-paths` only rebases a stale path when the matching generated
file already exists inside the current project root; otherwise it leaves the
metadata unchanged and reports a warning.

`--import-external-completion LOOP_ID` remains a backward-compatible alias for
loop-based resume. Job-based resume is still preferred:

```bash
python3 main.py --resume-external-job JOB_ID --external-completion-file completion.json
```

When the compatibility alias can identify a single linked external job, it now
updates that job's completion path, status, and job events consistently with the
job-based resume path. If multiple linked active jobs are ambiguous, it stops and
asks for `--resume-external-job JOB_ID`.

# Loop Engineering — Stage 3.9

## What's new in 3.9 — External Agent Job Health Checks

Stage 3.9 adds read-only **External Agent Job Health Checks** for the local
external-agent queue. Health checks inspect generated job metadata and known job
files under `external_agent_jobs/job_<id>/`; they do not run commands, call
Ollama, resume jobs, import completions, commit, delete files, or read arbitrary
project files.

```bash
python3 main.py --external-health
python3 main.py --external-health --status WAITING_FOR_EXTERNAL_AGENT
python3 main.py --external-health --agent claude
python3 main.py --external-health --workspace loop-engineering
python3 main.py --external-health --include-archived
python3 main.py --external-health --fix-safe
python3 main.py --external-job 1
```

Detected issue types include: `stale_waiting_job`, `missing_job_directory`,
`missing_handoff`, `missing_packet`, `missing_readme`,
`missing_completion_example`, `invalid_packet_json`,
`job_path_outside_allowed_dir`, `archived_waiting_job`,
`cancelled_with_completion`, `completion_waiting_import`,
`broken_report_reference`, `loop_missing_for_job`, `job_status_invalid`,
`priority_invalid`, `labels_invalid`, and `protected_content_risk`.

Default behavior is read-only. `--fix-safe` is intentionally narrow: it may record
health events and may mark an archived waiting job `CANCELLED` only when no
completion exists. It never deletes or creates job files, never imports a
completion, never resumes a loop, never calls Reviewer or Ollama, and never runs
terminal commands.

Health events persist in SQLite (`external_job_health_events`) and appear in
`--external-job JOB_ID`, `--show LOOP_ID`, run reports, and the external
dashboard health summary after a health check has been run. Safety is tracked via
the `external_job_health_check_safe` quality gate; critical findings are persisted
with the conceptual stop condition `external_job_health_critical`.

# Loop Engineering — Stage 3.5

## What's new in 3.5 — External Agent Job Dashboard & Triage

A read-only terminal **dashboard** and triage layer over the job queue
(`external_agent_dashboard.py`). It creates no loops, calls no models, and writes
no project files — it only reads the queue (and records a few dashboard metrics on
the most recent existing job, never a new loop).

```bash
python3 main.py --external-dashboard
python3 main.py --external-dashboard --agent claude
python3 main.py --external-dashboard --workspace loop-engineering
python3 main.py --external-dashboard --active      # or --archived
```

The dashboard prints: **SUMMARY** (total/active/waiting/completed/blocked/failed/
cancelled/archived, oldest-waiting, newest), **BY AGENT**, **BY PRIORITY**, **BY
WORKSPACE**, **NEEDS ATTENTION** (urgent/high waiting, failed, blocked, jobs with
`last_error`, stale >24h waiting, and paused external loops with no matching job),
**RECENT JOBS** (latest 10 with age), and **NEXT ACTIONS** (exact
`--external-job` / `--resume-external-job` / `--cancel-external-job` /
`--archive-external-job` commands).

**Triage filters** on the job list:

```bash
python3 main.py --external-jobs --stale            # waiting > 24h
python3 main.py --external-jobs --needs-attention  # failed/blocked/urgent-waiting/errored/stale
```

Job **age** is rendered human-readably (`s`/`m`/`h`/`d`); a job is **stale** when it
is `WAITING_FOR_EXTERNAL_AGENT` and its `created_at` is older than 24 hours.
Optional metrics: `external_dashboard_viewed`,
`external_jobs_needing_attention_count`, `external_jobs_stale_count`.

# Loop Engineering — Stage 3.4

## What's new in 3.4 — External Agent Job Queue & Lifecycle

External agent jobs are now a durable **local work queue**: list, filter, prioritize,
label, annotate, archive, and track jobs as first-class items (execution still stays
manual — Claude Code / Codex are not auto-run).

- **Priority** (`low|normal|high|urgent`, default `normal`), **labels** (comma-separated,
  plain text), and **notes** at creation:
  ```bash
  python3 main.py "Fix bug" --external-coder claude --job-priority high --job-labels bugfix,safety --job-notes "Waiting on Claude"
  ```
- **Queue listing & filters:**
  ```bash
  python3 main.py --external-jobs --active
  python3 main.py --external-jobs --archived
  python3 main.py --external-jobs --status WAITING_FOR_EXTERNAL_AGENT
  python3 main.py --external-jobs --agent claude
  python3 main.py --external-jobs --workspace loop-engineering
  ```
- **Lifecycle / metadata:**
  ```bash
  python3 main.py --set-external-job-priority 1 urgent
  python3 main.py --set-external-job-labels 1 bugfix,backend
  python3 main.py --set-external-job-notes 1 "Waiting on Claude completion"
  python3 main.py --archive-external-job 1
  python3 main.py --unarchive-external-job 1
  ```
- **`--external-job JOB_ID`** shows full metadata + lifecycle timeline + linked loop
  summary + resume/cancel/archive commands.
- New job columns (`priority`, `labels_json`, `notes`, `archived`, `retry_count`,
  `last_error`, `completed_at`, `cancelled_at`, `archived_at`) via safe `ALTER TABLE`
  migration; job events for `priority_updated` / `labels_updated` / `notes_updated` /
  `archived` / `unarchived` / `retry_incremented` / `error_recorded`.

**Safety:** labels and notes are **plain text only** — sanitized (control chars,
path separators and shell metacharacters stripped), length-capped, never interpreted
as paths/commands/code, and they never affect filesystem, terminal, Git, or approval
behavior. The `external_agent_job_metadata_valid` gate validates priority/labels/notes/
archived/retry_count; **archived jobs are not resumable** until unarchived
(`external_agent_job_archived` stop condition); resume still routes through the
`ResumeEngine` and cannot bypass workspace validation or the Reviewer.

# Loop Engineering — Stage 3.3

A Python application that orchestrates **local Ollama models** in a plan →
implement → execute → (analyze failures) → review loop, with **task intake &
clarification**, and the option to **delegate implementation to an external
terminal coding agent** (Claude Code / Codex) — with **structured completion
import**, **resumable paused runs**, and **External Agent Job Packets** — while
keeping the Supervisor, safety gates, memory, reports, and approvals inside this
framework.

## What's new in 3.3 — External Agent Job Packets

External handoffs are now tracked as first-class, repeatable, resumable **jobs**.
When `--external-coder` is used, the framework creates an `ExternalAgentJob` and
writes an internally-generated packet directory (execution stays manual — Claude
Code / Codex are **not** auto-run):

```
external_agent_jobs/job_<id>/
  handoff.md                # the handoff prompt (Completion Response JSON + resume)
  packet.json               # full structured job packet (summaries + allowed paths only)
  completion.json.example   # the completion schema to return
  README.md                 # what to run, what may be edited, how to resume
```

**Job lifecycle:** `CREATED → HANDOFF_READY → WAITING_FOR_EXTERNAL_AGENT →
COMPLETION_IMPORTED → REVIEWED → APPROVED` (or `BLOCKED` / `FAILED` /
`CANCELLED`). Jobs and their events persist in SQLite (`external_agent_jobs`,
`external_agent_job_events`).

**Safety:** packet paths are generated internally and confined to
`external_agent_jobs/`; packets contain only summaries, allowed paths, task/plan/
review/test feedback, the completion schema and resume commands — **never** `.env`
/ secret / key / `.git` contents or full project dumps. The packet is validated by
the `external_agent_job_packet_safe` gate; resume is validated by
`external_agent_job_resume_valid`. Resume still routes through the `ResumeEngine`,
so it cannot bypass workspace validation or the Reviewer.

```bash
python3 main.py "Add helper" --external-coder claude   # creates job + packet
python3 main.py --external-jobs                         # list jobs
python3 main.py --external-jobs --status WAITING_FOR_EXTERNAL_AGENT
python3 main.py --external-job 1                        # full job detail
python3 main.py --resume-external-job 1 --external-completion-file completion.json
python3 main.py --cancel-external-job 1                 # mark CANCELLED (files kept)
```

## Hotfix 3.2.1 — Codex audit fixes

- **CRITICAL terminal escape closed.** `python`/`python3` now run only a
  whitelisted set of forms: a `.py` script path (relative, inside the
  workspace), `-m unittest`/`-m pytest`, or `-V`/`--version`. **Inline code
  (`-c`), stdin (`-`), risky `-m` modules (e.g. `http.server`, `pip`), and the
  bare REPL are blocked** — so the `python3 -c "...write outside workspace..."`
  escape no longer runs. Shell operators, absolute paths, `..`, `~`, null bytes,
  and `shell=False` are all still enforced.
- **Loop-aware `files_written` gate.** Only loops whose objective expects file
  changes require a write. `code_build` requires files; **command-only
  `test_fix` passes when it ran commands**; design/review loops are n/a.
- **Design-loop output contracts.** `prompt_design` succeeds on a usable prompt
  and `loop_design` on a structured loop definition — they are no longer forced
  through code/file-change expectations and never touch fs/terminal/git.
- **External delta detection.** Handoffs capture a workspace snapshot; resume/
  import compares against it so **only the agent's deltas count**. Stale/new
  generated artifacts (`__pycache__`, `*.pyc`, `.DS_Store`) are ignored, while
  sensitive changes (`.env`, `.git`, keys, `node_modules`, …) still block.
- **`--help` / `-h`** print usage and exit 0 (no loop, no intake, no Ollama).
- **Handoff prompts** consistently show `--resume LOOP_ID …` (preferred);
  `--import-external-completion` remains a backward-compatible alias.
- **`audit_hotfix.py`** runs all of the above as local, non-destructive checks.

```bash
python3 -m py_compile *.py
python3 audit_hotfix.py
python3 main.py --help
```

## What's new in 3.2 — External Agent Auto-Resume

- **Paused runs.** When an external handoff is generated and completion isn't
  imported yet (the user declines the immediate yes/no), the loop is saved with
  status **`PAUSED_EXTERNAL_AGENT`** (the old `NEEDS_EXTERNAL_AGENT` stays a
  backward-compatible alias). The handoff prompt now ends with a
  **`## How to Resume This Loop`** section showing the exact `--resume` command.
- **`resume.py`** — `ResumeRequest`, `ResumeResult`, `ResumeEngine`. Resuming a
  loop imports the completion (file/text or an already-stored one), **re-inspects
  the workspace, runs the Reviewer with the completion context, updates status,
  regenerates the report**, and optionally commits (only when APPROVED + `--commit`,
  approval-gated). The Stage-3.1 `--import-external-completion` now routes through
  the same `ResumeEngine`.
- **Safety stays in the framework.** Resume never bypasses workspace/profile
  safety, approvals, quality gates, stop conditions, or the Reviewer. A missing
  completion → `resume_missing_completion`; a non-resumable loop →
  `resume_invalid_loop_state`; an out-of-bounds/protected workspace change →
  `resume_workspace_violation` (BLOCKED before review).
- **Persistence**: `resume_events` table; functions `save_/get_resume_events`,
  `list_paused_external_loops`. Metrics `resume_used`,
  `resume_completion_imported`, `resume_status_before/after`,
  `resume_commit_requested/created`. Gates `resume_loop_valid`,
  `resume_completion_available`, `resume_review_completed`. Reports + `--show`
  show resume events.

```bash
python main.py --workspace loop-engineering "Add helper" --external-coder claude
python main.py --paused
python main.py --resume 51 --external-completion-file completion.json
python main.py --resume 51 --external-completion-text '{"status":"completed","summary":"..."}'
python main.py --resume 51 --commit
python main.py --show 51
```

## What's new in 3.1 — External Agent Result Import It runs on a **registered project workspace**
governed by a named **permission profile**, with optional **human approval
gates**, persistent **Markdown run reports**, full **loop replay**, reusable
**loop templates**, read-only **project intelligence**, **project memory
search**, and bounded **context packs**. No GUI, no vector/RAG, and no external
AI frameworks — just the Ollama HTTP API and the Python standard library (incl.
`sqlite3`).

## What's new in 3.1 — External Agent Result Import

- **Structured completion** — every handoff prompt now ends with a `## Completion
  Response` JSON block the external agent should return. The framework can import
  that completion instead of relying only on yes/no.
- **`external_agents.py`** adds `ExternalAgentCompletion`,
  `parse_completion_summary` (JSON **or** plain-text fallback with `parsed=False`),
  `load_completion_file`, and `validate_completion`.
- **Two ways to import:**
  - During a run: `--external-completion-file PATH` / `--external-completion-text
    '{...}'` imports the result before the yes/no prompt.
  - After the fact: `--import-external-completion LOOP_ID --external-completion-file
    …` resumes an existing **NEEDS_EXTERNAL_AGENT** loop — it **re-inspects the
    workspace, runs the Reviewer with the completion context, and updates status**,
    without re-running the Supervisor, local Coder, or intake, and without
    auto-committing.
- **Safety stays in the framework.** The completion is *claims*; the framework
  still inspects the real workspace. Protected/disallowed changes →
  `external_agent_workspace_violation` (BLOCKED); `status: failed|blocked` →
  `external_completion_failed`; claimed paths referencing protected/`..`/absolute
  → `external_completion_workspace_mismatch` (BLOCKED).
- **Persistence**: `external_agent_events` gains completion columns; functions
  `save_/get_external_agent_completion`. Metrics `external_completion_imported`,
  `external_completion_parsed`, `external_completion_tests_passed`,
  `external_completion_file_count`, `external_completion_command_count`. Gates
  `external_completion_valid`, `external_completion_matches_workspace`,
  `external_completion_reviewed`. Reports + `--show` show the completion details.

```bash
python main.py --workspace loop-engineering "Add helper" --external-coder claude
python main.py --import-external-completion 51 --external-completion-file completion.json
python main.py --import-external-completion 51 --external-completion-text '{"status":"completed","summary":"..."}'
```

## What's new in 3.0 — External Coding Agent Adapter

## What's new in 3.0 — External Coding Agent Adapter

- **`external_agents.py`** — `ExternalAgentRequest`, `ExternalAgentResult`,
  `ExternalAgentAdapter`, `ClaudeCodeAdapter`, `CodexAdapter`,
  `ExternalAgentRegistry`. Stage 3.0 is **handoff (manual) mode only**: it never
  automates the external tool.
- **How it works:** the Supervisor still plans; instead of the local Qwen coder,
  the adapter generates a complete **handoff prompt** (saved under
  `external_agent_handoffs/`), prints `cd <root>` + `claude`/`codex` instructions,
  and asks *"Did the external agent finish? [y/N]"*. On **yes**, the framework
  inspects the workspace, blocks disallowed/protected changes, and sends the
  result to the Reviewer; on **no**, it stops with **NEEDS_EXTERNAL_AGENT**.
- **Safety — external agents never bypass the framework.** The handoff prompt
  includes the allowed write/command paths and explicit rules (no out-of-path
  edits, no unsafe commands, no commits, no protected files, stop after verify).
  After completion, changes are checked: a protected/disallowed change triggers
  `external_agent_workspace_violation` → final status **BLOCKED**, and no commit.
  The handoff prompt contains **no file contents or secrets** (summaries only).
- **Persistence**: `external_agent_events` table; metrics `external_agent_used`,
  `external_agent_name`, `external_agent_mode`, `external_agent_completed`,
  `external_agent_success`, `external_agent_duration_seconds`,
  `external_agent_files_changed_count`; gates `external_agent_handoff_safe`,
  `external_agent_changes_within_workspace`, `external_agent_completion_confirmed`;
  stop conditions `needs_external_agent`, `external_agent_workspace_violation`,
  `external_agent_failed`; reports add a `## External Coding Agent` section.
- **Flags**: `--external-coder claude|codex|none` (default `none` → unchanged
  behavior), `--external-agent-mode handoff`.

```bash
python main.py --workspace loop-engineering "Add a small helper function" --external-coder claude
python main.py --workspace loop-engineering "Add a small helper function" --external-coder codex
python main.py --show LOOP_ID
```

## What's new in 2.9 — Task Intake & Clarification

## What's new in 2.9 — Task Intake & Clarification

- **`task_intake.py`** — `TaskIntakeRequest`, `TaskIntakeResult`,
  `TaskClarificationQuestion`, `TaskIntakeEngine`. Before any side effects, a raw
  task is analyzed for ambiguity, risk, and missing details. Safety-critical
  decisions are computed by deterministic heuristics; the `intake_analyst` agent
  enriches the natural-language fields.
- **Clarification** is required for vague tasks, unclear targets, missing
  acceptance criteria / repro steps / test targets, and risky requests. In
  interactive mode the questions are asked in the terminal and folded into a
  clarified task; in `--non-interactive` mode the run **stops with
  NEEDS_CLARIFICATION** before any Supervisor/Coder/Reviewer call, file write,
  command, or commit.
- **Risk gating** — high/critical-risk tasks (delete/deploy/publish/`rm -rf`…)
  **stop before side effects** unless `--require-approval` is enabled.
- **Loop-type detection** — when `--loop` isn't given, the intake's detected loop
  type is used; an explicit `--loop` always wins.
- **Modes**: `--intake-mode auto` (default; runs for non-template tasks),
  `always`, `never`; `--intake` / `--no-intake`; `--non-interactive`.
  Templates skip intake by default (they're already structured) unless
  `--intake-mode always`.
- **Persistence**: `task_intake_events` table; the `loops` row stores `raw_task`,
  `clarified_task`, `intake_used`, `intake_status`; metrics `intake_used`,
  `intake_confidence_score`, `intake_ambiguity_score`,
  `intake_clarification_required`, `intake_question_count`, `intake_risk_level`,
  `intake_detected_loop_type`; gates `task_intake_valid`, `clarification_resolved`,
  `intake_risk_accepted`; stop conditions `needs_clarification`, `intake_blocked`,
  `intake_high_risk_requires_approval`; reports add a `## Task Intake` section.
- **Replay**: exact replay uses the source `clarified_task` and does **not** re-run
  intake by default; `--intake-mode always` re-runs it.

```bash
python main.py "fix the app" --intake
python main.py "fix the app" --intake --non-interactive
python main.py "add login" --workspace loop-engineering --intake
python main.py "add tests for calculator" --intake-mode always
python main.py --replay 25 --dry-run
```

## What's new in 2.8 — Context Packs

## What's new in 2.8 — Context Packs

- **`context_packs.py`** — `ContextPackFile`, `ContextPack`, `ContextPackRequest`,
  `ContextPackBuilder`. Selects relevant files (explicit paths, project
  intelligence, memory search, task keywords, entrypoints), reads **bounded
  excerpts**, ranks them, and produces a pack for agent prompts.
- **Bounded & read-only.** Defaults: `max_files=8`, `max_total_chars=24000`,
  `max_chars_per_file=6000` (head+tail with `truncated=true`). Honors
  `allowed_read_paths`; skips protected/`.git`/`.env`/secrets/`node_modules`/venvs,
  binary files, files > 250 KB, and symlink escapes; never executes, writes, or
  calls Ollama; never reads paths chosen directly by model output. Only metadata
  is persisted — file contents are transient (prompts only).
- **Agent prompts.** Supervisor gets a `CONTEXT PACK SUMMARY` (no contents);
  the Coder gets `RELEVANT FILE CONTEXT` excerpts (when filesystem writes are
  allowed); the Reviewer gets the same excerpts alongside the changes.
- **Explicit unsafe requests are blocked.** `--context-file .env` is excluded with
  a warning and never read; if *every* explicit file is unsafe the
  `context_pack_safe` gate fails.
- **Persistence**: `context_packs` + `context_pack_files` (metadata only); the
  `loops` row stores `context_pack_id`; metrics `context_pack_used`,
  `context_pack_file_count`, `context_pack_total_chars`, `context_pack_truncated`;
  required gate `context_pack_safe`; reports add a `## Context Pack` section.
- **Flags**: `--use-context-pack`, `--no-context-pack`, `--context-max-files N`,
  `--context-max-chars N`, `--context-file PATH` (repeatable). Default: used
  automatically when a project-intelligence report exists.

```bash
python main.py --context-pack "Improve the calculator module"
python main.py --context-pack "Improve the calculator module" --workspace loop-engineering
python main.py --context-pack "review env" --context-file .env        # .env blocked
python main.py --context-packs
python main.py --workspace loop-engineering "Improve README docs" --context-file README.md
python main.py --workspace loop-engineering "Improve the calculator" --no-context-pack
```

## What's new in 2.7 — Project Memory Search

## What's new in 2.7 — Project Memory Search

- **`memory_search.py`** — `MemorySearchQuery`, `MemorySearchResult`,
  `MemorySearchEngine`. Searches existing SQLite data (loops, steps, reviews,
  command results, file operations, run reports, project-intelligence reports,
  file summaries) with simple ranking: exact-phrase > all-terms > some-terms,
  plus title/path, same-workspace, and small recency boosts. No embeddings, no
  Ollama, no external packages.
- **Memory context for the Supervisor.** Before a loop runs, memory is searched
  with the task as the query (top 5, same workspace) and injected as a concise
  `MEMORY CONTEXT` block (similar loops, failures, reviews, reports, intel) — no
  full bodies. If nothing relevant exists, the Supervisor is told so.
- **Flags**: `--use-memory` (force on), `--no-memory` (disable), `--memory-limit N`.
  Default: memory is used automatically when prior runs exist.
- **Read-only & safe.** Search is SQLite-only; report bodies are read only from
  the internal `reports/` directory; it never writes, runs commands, calls Ollama,
  or exposes protected file contents.
- **Persistence**: `memory_search_events` table; metrics `memory_search_used`,
  `memory_search_result_count`, `memory_search_limit`, `memory_context_injected`;
  required gate `memory_context_safe`; reports add a `## Memory Context` section.

### Search sources / CLI

`--source` values: `all` (default), `loops`, `steps`, `reviews`, `commands`,
`files`, `reports`, `project_intel`.

```bash
python main.py --memory-search "calculator tests"
python main.py --memory-search "approval declined" --limit 10
python main.py --memory-search "test failure" --source commands
python main.py --memory-search "project intelligence" --source reports --workspace loop-engineering
python main.py --workspace loop-engineering "Improve the calculator module" --use-memory
python main.py --workspace loop-engineering "Improve the calculator module" --no-memory
```

## What's new in 2.6 — Project Intelligence

## What's new in 2.6 — Project Intelligence

- **`project_intelligence.py`** — `ProjectFileSummary`,
  `ProjectStructureSummary`, `ProjectIntelligenceReport`,
  `ProjectIntelligenceScanner`. Scans a workspace's allowed read paths, classifies
  files (source/test/config/docs), scores importance (0–1), and summarizes
  languages + key files.
- **Read-only & safe.** The scanner honors `allowed_read_paths`, skips protected
  paths (`.git`, `.env`, secrets, `node_modules`, venvs, `__pycache__`), skips
  binary files and files > 250 KB, never follows symlinks out of the root, never
  executes anything, and never calls Ollama.
- **Supervisor context.** Before a loop runs, the latest scan for the workspace is
  injected as a concise `PROJECT CONTEXT` block (workspace, profile, languages,
  important/test/config/docs files, warnings, recommendations) — no file
  contents. If no scan exists, the Supervisor proceeds normally and is told so.
- **Persistence**: `project_intelligence_reports` + `project_file_summaries`; the
  `loops` row stores `project_intelligence_report_id`; metrics
  `project_intelligence_used` / `project_intelligence_report_id`; required gate
  `project_intelligence_safe`; reports add a `## Project Intelligence` section.

```bash
python main.py --scan-project
python main.py --scan-project --workspace loop-engineering
python main.py --project-intel --workspace loop-engineering
python main.py --project-intel-report 1
python main.py --workspace loop-engineering "Review the current project structure and suggest the next improvement"
```

## What's new in 2.5 — Loop Templates

## What's new in 2.5 — Loop Templates

- **`loop_templates.py`** — `LoopTemplate`, `LoopTemplateRegistry`,
  `load_builtin_templates`, `list_templates`, `get_template`, `validate_template`,
  `render_template`. A template parameterizes a task with plain-text variables.
- **Built-in templates**: `build_feature`, `fix_bug`, `write_tests`,
  `review_code`, `design_prompt`, `design_loop` — each with required variables and
  a default loop type.
- **How it works**: `--template <name> --var k=value …` validates the required
  variables, renders the `objective_template` into a concrete task, picks the
  template's default loop type (unless `--loop` overrides), then runs the **normal
  loop engine**. Templates are convenience only — they do **not** bypass
  workspace/profile/approval/quality-gate/stop-condition or
  filesystem/terminal/git safety. Variables are plain text and never executed.
- **Persistence**: the `loops` row stores `template_name`, `template_version`,
  `template_variables_json`, `rendered_task`; a `loop_template_events` row is
  recorded. Metrics: `template_used`, `template_name`, `template_version`,
  `template_variable_count`, `rendered_task_length`. Reports add a `## Template`
  section; `--show`/`--history` surface the template; replay (exact) preserves it.

```bash
python main.py --templates
python main.py --template-info build_feature
python main.py --template build_feature \
  --var feature_name="Calculator" \
  --var feature_description="Create a calculator module." \
  --var target_area="workspace" \
  --var acceptance_criteria="add, subtract, multiply, divide with tests"
python main.py --template fix_bug \
  --var bug_summary="divide crashes on zero" \
  --var observed_behavior="ZeroDivisionError" \
  --var expected_behavior="returns a clear error" \
  --var reproduction_steps="call divide(4, 0)"
```

Missing a required variable produces a clear error **before** any model call.

## What's new in 2.4 — Loop Replay

## What's new in 2.4 — Loop Replay

- **`replay.py`** — `ReplayRequest`, `ReplayResult`, `ReplayEngine`. Reconstructs
  a previous run's settings (task, loop type, workspace, models, approval mode,
  min confidence) and optionally re-executes it.
- **Replay modes**:
  - `exact` (default) — reuse the source run's task, loop type, workspace, models,
    and approval settings. `--commit` stays off unless explicitly passed.
  - `task_only` — reuse only the task; everything else uses current defaults.
  - `fixed` — reuse task + loop type, but allow `--workspace`/`--*-model`/setting
    overrides.
- **`--dry-run`** prints the reconstructed settings and what *would* run — it
  calls no model, writes nothing, runs nothing, commits nothing, and creates no
  new loop row (only a `dry_run` replay event).
- **Safety — replay never bypasses current gates.** A replayed run re-checks
  workspace validity, profile validity, quality gates, stop conditions, approval
  gates, and filesystem/terminal/git safety. If the source workspace no longer
  exists or is invalid, a real replay stops with **BLOCKED** before any model
  call or side effect (dry-run shows the issue).
- **Persistence**: `replay_events` table links source ↔ new loop; `--show`
  indicates if a loop was created from a replay and whether it has been replayed.
  Metrics `replay_is_replay`, `replay_source_loop_id`, `replay_mode` are saved on
  replayed runs. Reports include a replay note (source loop + mode).

```bash
python main.py --replay 25 --dry-run
python main.py --replay 25
python main.py --replay 25 --replay-mode task_only
python main.py --replay 25 --workspace loop-engineering --dry-run
python main.py --replay 25 --coder-model qwen2.5-coder:32b
python main.py --replay 25 --commit
```

## What's new in 2.3 — Run Reports

## What's new in 2.3 — Run Reports

- **`reports.py`** — `RunReport`, `ReportGenerator`, `generate_markdown_report`,
  `save_report`, `get_report_path`, `list_reports`. After every run a Markdown
  report is generated from SQLite and saved to `reports/`.
- **Report file**: `reports/loop_<id>_<YYYYMMDD_HHMMSS>.md` — path is generated
  internally (never from model output) and confined to `reports/`.
- **Contents**: summary, agents, plan, per-attempt breakdown, final review, files
  changed, commands, approvals, git, metrics, outcome, and a concise
  **Suggested Next Step**.
- **Read-only**: reports never run commands or write outside `reports/`.
- **Resilient**: if report generation fails *after* the run completed, the run is
  not affected — `report_generated` is marked failed, the error is printed, and
  `report_generation_failed=1` is saved.
- **Persistence**: `run_reports` table (path, format, content hash, bytes).
  Metrics: `report_generated`, `report_bytes_written`, `report_generation_seconds`,
  `report_generation_failed`. Required quality gate `report_generated`.

```bash
python main.py "Create a helper file"   # auto-generates a report, prints its path
python main.py --reports                # list recent reports
python main.py --report 25              # print a run's report (generates if missing)
python main.py --show 25                # includes the report path
```

## What's new in 2.2 — Human Approval Gates

## What's new in 2.2 — Human Approval Gates

- **`approval_gates.py`** — `ApprovalRequest`, `ApprovalDecision`,
  `ApprovalPolicy`, `ApprovalGateEngine`. Before file writes, command execution,
  or git commits, the engine can require explicit approval.
- **Off by default.** With no flags, nothing changes (Stage 2.1 behavior).
- **`--require-approval`** turns on approval for writes/commands/commits; it
  defaults the mode to **interactive** (`[y/N]` prompts). `--approval-mode none`
  with required approval **fails closed** (declines) — risky actions are never
  auto-approved by default.
- **`--auto-approve-low-risk`** lets low-risk actions proceed without prompting.
- **Declines are respected**: a declined action is **not performed** — files are
  not written, commands are not run, commits are not made — and the loop stops
  with `human_approval_declined` (status **NEEDS_HUMAN**, or **BLOCKED** for
  critical risk).
- **Persistence**: `approval_events` table (per request: action, risk, decision,
  reason); shown in `--show`. Metrics: `approval_required`,
  `approval_requests_count`, `approval_approved_count`, `approval_declined_count`,
  and per-action `*_approval_required`.
- **Quality gates**: `approval_policy_valid` (required), `required_approval_obtained`,
  `declined_approval_respected`.

### Approval modes

| Mode          | Behavior                                                        |
|---------------|-----------------------------------------------------------------|
| `none` (default) | No prompting. If approval is *required* but mode is none, the action is declined (fail closed). |
| `interactive` | Prints the proposed change and asks `[y/N]`.                    |

```bash
python main.py --workspace loop-engineering "Create a helper file" --require-approval
python main.py --workspace loop-engineering "Create a helper file" --require-approval --approval-mode interactive
python main.py --workspace loop-engineering "Create a helper file" --commit --require-approval
python main.py "Quick helper" --require-approval --auto-approve-low-risk
```

Interactive prompts show: file paths + operation + a 30-line content preview +
byte count (writes); command + cwd + safety result (commands); branch + status +
staged paths + message (commits).

## What's new in 2.1 — Workspace Permission Profiles

## What's new in 2.1 — Workspace Permission Profiles

- **`workspace_profiles.py`** — `WorkspacePermissionProfile`,
  `WorkspaceProfileRegistry`, `load_builtin_profiles`, `list_profiles`,
  `get_profile`, `validate_profile`. A profile is a named bundle of
  read/write/command paths + git permission + safety level.
- **Apply at registration or later** — registering copies the profile's resolved
  permissions onto the workspace (and stores `profile_name`/`profile_version`),
  so a workspace stays inspectable even if the profile changes later.
- **Default profile = `sandbox`**, preserving Stage 2.0 behavior exactly.
- **Required gate `workspace_profile_valid`** and stop condition
  `workspace_profile_invalid`: a missing/invalid profile stops with **BLOCKED**
  before any file is written, command is run, or commit is made (and before any
  model call).
- Profiles never loosen the global protected-path rules — `.git/`, `.env`,
  `node_modules/`, `*.pem`, etc. are always blocked.

### Built-in profiles

| Profile       | Write paths                         | Cmd paths | Git | Purpose                    |
|---------------|-------------------------------------|-----------|-----|----------------------------|
| `sandbox`     | `workspace`                         | `workspace` | yes | Safest default.          |
| `source_only` | `src, app, lib, tests, workspace`   | `.`       | yes | Edit source folders.       |
| `docs_only`   | `docs, README.md, workspace`        | `workspace` | yes | Docs edits only.         |
| `tests_only`  | `tests, test, workspace`            | `.`       | yes | Test edits only.           |
| `read_only`   | (none)                              | `.`       | no  | Review/analysis only.      |

```bash
python main.py --workspace-profiles
python main.py --workspace-profile-info source_only
python main.py --register-workspace loop-engineering /Users/ansoncordeiro/dev/loop-engineering --profile sandbox
python main.py --set-workspace-profile loop-engineering source_only
python main.py --workspace loop-engineering "Create a small helper in src and a test in tests"
```

Path resolution: with a **single** write path (sandbox) a bare `calc.py` lands in
`workspace/calc.py`; with **multiple** write paths, coder paths are root-relative
and must fall inside an allowed write dir (e.g. `src/app.py` works under
`source_only`, but `src/...` is blocked under `docs_only`).

## What's new in 2.0 — Project Workspaces

## What's new in 2.0 — Project Workspaces

- **`project_workspace.py`** — `ProjectWorkspace`, `WorkspaceManager`. A workspace
  bounds where a loop may read, write, and run commands, and whether git is
  allowed.
- **Default = Stage 1.9 behavior.** With no `--workspace`, the internal
  `workspace/` sandbox is used exactly as before.
- **Register real projects** with restrictive defaults: even a registered
  project only permits writes/commands under `workspace/` until you widen the
  allowed paths.

```bash
python main.py --register-workspace loop-engineering /Users/ansoncordeiro/dev/loop-engineering
python main.py --workspaces
python main.py --workspace-info loop-engineering
python main.py --workspace loop-engineering "Create a small utility file inside workspace"
```

Default permissions when registering: `allowed_read_paths=["."]`,
`allowed_write_paths=["workspace"]`, `allowed_command_paths=["workspace"]`,
`allow_git=true`.

### Workspace safety rules

- Writes only inside `allowed_write_paths`; commands only inside
  `allowed_command_paths`; git only at the workspace root, staging only the
  allowed write paths.
- Never: path traversal, absolute-path writes, `~` paths, or writes to protected
  patterns — `.git/`, `.env`, `.env.*`, `node_modules/`, `__pycache__/`,
  `.venv/`, `venv/`, `env/`, `.DS_Store`, `secrets*`, `*.pem`, `*.key`, `id_rsa`,
  `id_ed25519`.
- A violation fails a **required** workspace quality gate
  (`workspace_valid`, `workspace_write_allowed`, `workspace_command_allowed`,
  `protected_paths_blocked`) and triggers the `workspace_violation_blocked` stop
  condition → final status **BLOCKED**, no commit. Blocked operations are
  persisted as `file_operations` with `allowed=false` and a reason.
- The `loops` table records `workspace_name` and `workspace_root`; `--history`
  shows the workspace and `--show` shows the workspace name + root.

## What's new in 1.9 — Stop Conditions & Quality Gates

## What's new in 1.9 — Stop Conditions & Quality Gates

- **`stop_conditions.py`** — `StopCondition`, `QualityGate`, their result types,
  and a pure-logic `StopConditionEngine`.
- **Quality gates** check each attempt's output. *Required* gates
  (`valid_coder_json`, `safe_file_paths`, `safe_commands_only`) are safety/format
  critical; the rest (`reviewer_json_valid`, `test_analyst_json_valid`,
  `commands_successful`, `files_written`, `reviewer_confidence_minimum`) are
  advisory. A **failed required gate blocks committing** and prevents success.
- **Stop conditions** decide *why* the loop stops: `reviewer_approved`,
  `max_retries_reached`, `unsafe_operation_blocked` (terminal/critical),
  `repeated_failure`, `no_files_changed`, `command_timeout`, `test_passed`,
  `test_failed_after_retries`. The final status (`APPROVED`/`REJECTED`/`BLOCKED`)
  and `stop_reason` come from an explicit `StopDecision`.
- **Per-loop config** — `LoopDefinition.stop_conditions`, `quality_gates`, and
  `min_reviewer_confidence` (default `0.70`). `--loop-info` now shows tools,
  agents, stop conditions, quality gates, and the min confidence.
- **Persistence** — new `quality_gate_results` and `stop_condition_results`
  tables (per attempt), shown in `--show`; metrics `quality_gates_passed/failed`,
  `required_quality_gates_failed`, `stop_conditions_triggered`,
  `final_stop_condition`, `reviewer_confidence_minimum/actual`.
- **CLI** — `--min-reviewer-confidence <0..1>` overrides the threshold for a run.

```bash
python main.py "Create a calculator module with tests" --min-reviewer-confidence 0.85
python main.py --loop-info code_build      # tools, agents, gates, stop conditions
```

### Built-in quality gates

| Gate                          | Required | Checks                                       |
|-------------------------------|----------|----------------------------------------------|
| `valid_coder_json`            | yes      | Coder output parses into structured JSON.    |
| `safe_file_paths`             | yes      | All paths stay inside `workspace/`.          |
| `safe_commands_only`          | yes      | No unsafe command was attempted.             |
| `reviewer_json_valid`         | no       | Reviewer output is valid JSON.               |
| `test_analyst_json_valid`     | no       | Analyst output is valid JSON (when used).    |
| `commands_successful`         | no       | Executed commands exited 0.                  |
| `files_written`               | no       | Build/fix loops wrote ≥1 file.               |
| `reviewer_confidence_minimum` | no       | Reviewer confidence ≥ threshold (0.70).      |

### Built-in stop conditions

`reviewer_approved`, `max_retries_reached`, `unsafe_operation_blocked`,
`repeated_failure`, `no_files_changed`, `command_timeout`, `test_passed`,
`test_failed_after_retries`. A failed **required** gate or an
`unsafe_operation_blocked` trigger stops the loop and prevents commits.

## What's new in 1.8 — the Test Analyst

## What's new in 1.8 — the Test Analyst

- **Active `test_analyst` agent** — when an executed command/test **fails**, its
  output is routed to the `test_analyst` agent for a structured diagnosis
  *before* the Coder revises.
- **Diagnosis feeds the retry** — on the next attempt the Coder receives the
  reviewer feedback, the command output, **and** the analyst's root-cause +
  recommended changes.
- **Where it runs** — assigned to `test_fix` and `code_build`
  (`LoopDefinition.test_analyst_agent`). It only runs when there is real command
  output showing a failure; loops without terminal permission never trigger it.
- **Structured output** — the analyst returns JSON: `failure_detected`,
  `failure_type` (`test_failure|runtime_error|syntax_error|missing_dependency|`
  `unsafe_command_blocked|unknown`), `summary`, `root_cause`, `evidence`,
  `recommended_changes`, `confidence_score`.
- **Persistence** — saved as a `test_analysis` step (role `test_analyst`), with
  `resolved`/`execution_started`/`execution_completed` agent events and metrics
  `test_analyst_used`, `test_analyst_latency_seconds`,
  `test_analyst_failure_detected`, `test_analyst_confidence_score`.
- **CLI override** — `--test-analyst-model <model>` (this run only; the actual
  model is saved in metrics and agent events).

```bash
python main.py --loop test_fix "Create a Python function with tests, handle edge cases, and run tests"
python main.py "Build a module with tests" --test-analyst-model qwen3:30b
```

## What's new in 1.7 — the Agent Registry

## What's new in 1.7 — the Agent Registry

- **`agent_registry.py`** — `AgentDefinition`, `AgentRegistry`,
  `load_builtin_agents`, `list_agents`, `get_agent`, `validate_agent_definition`.
- **Loops vs. agents** — a **loop** defines *what* to do and which tools are
  permitted; an **agent** defines *who* does a role (its model, system prompt,
  temperature, output contract). Loops reference agents by name; the engine
  resolves them at run time.
- **Per-loop agent assignment** — each loop names a `supervisor_agent`,
  `coder_agent`, and `reviewer_agent` (defaults: the core agents). `prompt_design`
  uses `prompt_designer` as its coder; `loop_design` uses `loop_designer`.
- **CLI model overrides** — `--supervisor-model`, `--coder-model`,
  `--reviewer-model` override the resolved model for the current run only, and
  the **actual models used** are saved to the `loops` table.
- **Agent events** — a new `agent_events` table records `resolved` / `overridden`
  / `execution_started` / `execution_completed` (and `validation_failed`) per
  run; shown in `--show`.

### Built-in agents

| Name             | Role       | Default model        | Purpose                                  |
|------------------|------------|----------------------|------------------------------------------|
| `supervisor`     | supervisor | `qwen3:30b`          | Plan, route, enforce objectives.         |
| `coder`          | coder      | `qwen2.5-coder:32b`  | Structured file ops + command suggestions.|
| `reviewer`       | reviewer   | `qwen3:30b`          | Evaluate plan/files/output, decide stop. |
| `prompt_designer`| coder      | `qwen3:30b`          | Generate reusable prompts.               |
| `loop_designer`  | coder      | `qwen3:30b`          | Generate loop definitions.               |
| `test_analyst`   | analyst    | `qwen3:30b`          | Analyze test failures, propose fixes.    |

### Agent CLI / overrides

```bash
python main.py --agents                 # list agents
python main.py --agent-info supervisor  # full agent definition

# override the model used for a role (this run only; saved as the actual model)
python main.py "Create a calculator module with tests" --coder-model qwen2.5-coder:32b
python main.py "..." --supervisor-model qwen3:30b --reviewer-model qwen3:30b
```

## What's new in 1.6 — the Loop Registry

## What's new in 1.6 — the Loop Registry

- **`loop_registry.py`** — `LoopDefinition`, `LoopRegistry`,
  `load_builtin_loops`, `list_loops`, `get_loop`, `validate_loop_definition`.
- **Named, reusable loops** — pick behavior by name instead of re-describing it.
- **Tool permissions are enforced** — `LoopDefinition.allowed_tools` lists a
  subset of `{filesystem, terminal, git}`. A tool that is **not** listed never
  runs, even if the model emits files/commands; the attempt is recorded as
  blocked. Unknown tool names are rejected by validation.
- **Per-loop prompts** — Supervisor/Coder/Reviewer steering adapts to the active
  loop (e.g. filesystem-disabled loops are told to emit no files).
- **Persisted loop type** — the `loops` table now stores `loop_type` and
  `loop_version` (added via safe `ALTER TABLE` migration); shown in `--history`
  and `--show`.

### Built-in loops

| Name           | Tools                      | Purpose                                       |
|----------------|----------------------------|-----------------------------------------------|
| `code_build`   | filesystem, terminal, git  | Build/modify code in `workspace/` (default).  |
| `code_review`  | terminal                   | Review code; **no file writes, no commit**.   |
| `test_fix`     | filesystem, terminal       | Run tests and revise files until they pass.   |
| `prompt_design`| (none)                     | Produce a final prompt; **no files/commands**.|
| `loop_design`  | (none)                     | Output a structured loop definition JSON.     |

### Registry CLI

```bash
python main.py --loops                 # list available loops
python main.py --loop-info code_build  # full definition for one loop

# run a named loop
python main.py --loop code_build  "Create a calculator module with tests"
python main.py --loop code_review "Review the workspace calculator code"
python main.py --loop prompt_design "Write a prompt for a FastAPI endpoint builder"
python main.py --loop loop_design "A loop that lints Python files"

# default loop is code_build, so this is equivalent to --loop code_build:
python main.py "Create a calculator module with tests"
```

### Tool permission behavior

- **filesystem off** → Coder is told to emit no files; any emitted file is
  **not written** and recorded as blocked.
- **terminal off** → suggested commands are **not executed** and recorded as
  blocked.
- **git off** → `--commit` is ignored with a clear message and a `skipped` git
  event is recorded.

## What's new in 1.5 — safe Git

- **`git_tools.py`** — `is_git_repo`, `git_status`, `git_diff`,
  `git_add_workspace`, `git_commit`, `get_current_branch`, `get_last_commit`,
  each returning a `GitCommandResult`.
- **Narrow allowlist** — only these git invocations exist (no generic runner):
  `git status --short`, `git diff -- workspace/`, `git add -- workspace/`,
  `git commit -m "<msg>"`, `git branch --show-current`, `git rev-parse HEAD`.
- **No destructive git** — `push`, `pull`, `reset`, `checkout`, `clean`, `rm`
  are **not implemented** anywhere, so they cannot be invoked. All git runs with
  `shell=False` from the project root; no arbitrary user shell commands.
- **Opt-in commits** — runs never commit by default. With `--commit`, a commit
  is made **only if the final status is APPROVED**, and **only `workspace/`** is
  staged.
- **Git reporting** — every run prints repo state, branch, last commit, status
  summary, and whether `workspace/` changed.
- **Persistence** — a new `git_events` table records each status/diff/add/commit/
  skipped event; `--show LOOP_ID` displays them. Metrics `git_is_repo`,
  `git_workspace_changed`, `git_commit_attempted`, `git_commit_success` are saved.

### Git safety rules

| Rule                          | Behavior                                          |
|-------------------------------|---------------------------------------------------|
| Allowed git operations        | `status --short`, `diff -- workspace/`, `add -- workspace/`, `commit -m`, `branch --show-current`, `rev-parse HEAD` |
| Blocked (not implemented)     | `push`, `pull`, `reset`, `checkout`, `clean`, `rm`, any file deletion |
| Shell                         | always `shell=False`, run from project root       |
| Arbitrary commands            | impossible — no generic git runner is exposed     |
| Commit gating                 | only when final status is APPROVED                |
| Commit scope                  | only `workspace/` is staged                       |

### Commit behavior / examples

```bash
# run, persist, report git state — but do NOT commit
python main.py "Create a calculator module with tests"

# commit workspace/ only if the run is APPROVED
python main.py "Create a calculator module with tests" --commit

# custom commit message (otherwise: "Loop #<id>: <task summary>")
python main.py "Create a calculator module with tests" --commit --commit-message "Add calculator"

# inspect a past run incl. git events
python main.py --show 1
```

## What's new in 1.4 — memory

## What's new in 1.4 — memory

- **`database.py`** — standard-library `sqlite3` persistence. The database file
  `loop_engineering.db` is created at the project root on startup; tables are
  created if missing and **old data is never deleted**.
- **Everything is saved** — one row per loop in `loops`, plus per-attempt rows in
  `steps`, `reviews`, `file_operations`, `command_results`, and `metrics`.
- **History CLI** — browse and inspect past runs without re-running them.

### Tables

| Table             | What it holds                                                  |
|-------------------|----------------------------------------------------------------|
| `loops`           | one row per run: task, status, stop_reason, retry_count, duration, models |
| `steps`           | each agent call: prompt, response, latency, token counts, tok/s |
| `reviews`         | per-attempt structured verdict (approved, issues, changes, score) |
| `file_operations` | every file op: path, operation, allowed, reason, content hash, bytes |
| `command_results` | every command: allowed, exit_code, stdout/stderr, duration, timed_out |
| `metrics`         | named metric values (latency, counts, tokens, tests passed)    |
| `git_events`      | per-run git events: status, diff, add, commit, skipped         |
| `agent_events`    | per-run agent events: resolved, overridden, started, completed |
| `quality_gate_results`   | per-attempt quality gate pass/fail with messages         |
| `stop_condition_results` | per-attempt stop condition triggered/not with messages   |
| `project_workspaces`     | registered workspaces: paths + permissions               |
| `approval_events`        | per-request human approval: action, risk, decision       |
| `run_reports`            | generated report metadata: path, hash, bytes             |
| `replay_events`          | source↔new loop links for replays (incl. dry runs)       |
| `loop_template_events`   | template render events: name, version, variables         |
| `project_intelligence_reports` | workspace scan summaries (languages, key files)    |
| `project_file_summaries` | per-file scan rows: type, importance, language, hash     |
| `memory_search_events`   | per-loop memory searches: query, results, top hits       |
| `context_packs` / `context_pack_files` | context pack metadata (no file contents)   |
| `task_intake_events`     | intake analysis: risk, ambiguity, clarification Q&A      |
| `external_agent_events`  | external agent handoffs: agent, mode, completion, changes |
| `resume_events`          | resume runs: type, status before/after, commit            |
| `external_agent_jobs`    | external agent job packets: status, paths, workspace      |
| `external_agent_job_events` | job lifecycle events: created, packet_saved, status      |
| `external_completion_inbox_events` | inbox scans/imports: discovered, validated, imported, failed |
| `external_job_batch_events` | batch operations: action, per-job before/after, success/skip |
| `external_batch_reports`   | batch report metadata: batch_id, action, path, hash, bytes |

### History commands

```bash
# list recent runs (default 20)
python main.py --history

# limit the list
python main.py --history --limit 10

# full detail for one run
python main.py --show 1
```

`--history` prints loop id, created_at, task preview, status, retry_count,
duration, and stop_reason. `--show LOOP_ID` prints the full summary: task,
status, stop reason, attempts, every step, every review, file operations,
commands executed/blocked, and metrics.

## What's new in 1.3 — safe command execution

- **`terminal.py`** — `is_safe_command`, `run_command`, `run_suggested_commands`
  with a `CommandResult` record.
- **Allowlisted commands** — only `python`, `python3`, `pytest`, `ls`, `cat`,
  `pwd` may run. Everything else (incl. `rm`, `git`, `pip`, `curl`, `bash`, …)
  is blocked.
- **No shell** — commands run with `shell=False`. Shell operators
  (`;  &&  ||  |  >  >>  <  $()  backticks  newline`) are rejected.
- **Workspace confinement** — commands run only inside `workspace/`; arguments
  with `..`, absolute paths, `~`, or null bytes are rejected.
- **Timeouts** — every command has a wall-clock timeout (default 30s).
- **Execute → review** — command/test output is fed to the Reviewer, which now
  judges the plan, the files, **and** the test results. Tests must pass to
  approve.
- **Retry on failure** — failing commands or a rejection send the command output
  plus reviewer feedback back to the Coder, which revises and re-runs.
- **More metrics** — commands suggested/executed/blocked, exit codes, durations,
  timed-out commands, and whether tests passed.

### Command safety rules

| Rule                | Behavior                                                |
|---------------------|---------------------------------------------------------|
| Allowed families    | `python`, `python3`, `pytest`, `ls`, `cat`, `pwd`       |
| Blocked families    | `rm`, `mv`, `cp`, `chmod`, `chown`, `sudo`, `curl`, `wget`, `git`, `pip`, `npm`, `pnpm`, `yarn`, `brew`, `docker`, `open`, `osascript`, `ssh`, `scp`, `rsync`, `find`, `xargs`, `sed`, `awk`, `perl`, `ruby`, `node`, `bash`, `sh`, `zsh` (and anything not allowlisted) |
| Shell operators     | `;  &&  ||  |  >  >>  <  $()  ` `` ` ``  newline` rejected |
| Unsafe arguments    | `..`, absolute paths, `~`, null bytes rejected          |
| Working directory   | forced to stay inside `workspace/`                      |
| Timeout             | `LOOP_COMMAND_TIMEOUT` seconds (default 30)             |

Run tests with `python -m unittest <file>` or `pytest <file>`.

## What's new in 1.2 — safe hands

- **`workspace/` sandbox** — every file the Coder produces is written under
  `workspace/`. Writes outside it are rejected.
- **`filesystem.py`** — `safe_join`, `write_file`, `read_file`, `list_files`,
  `apply_file_operations`. Path traversal (`..`), absolute paths, `~`, and
  symlink escapes are blocked.
- **Structured coder output** — the Coder returns JSON:
  `{"summary", "files":[{"path","content"}], "commands":[], "notes":[]}`.
- **Apply + review files** — generated files are written to `workspace/`, then
  the Reviewer judges the plan **and** the file contents.
- **Command suggestions only** — `commands` are displayed but **not executed**
  in Stage 1.2.
- **Extended metrics** — files created/updated, total files changed, blocked
  unsafe paths, and suggested commands, in addition to all 1.1 metrics.

### From 1.1

- **Retry loop** — Reviewer approves or rejects; on rejection its feedback is
  sent back to the Coder, which revises and re-applies. Retries up to
  `MAX_RETRIES`, then stops on approval or exhaustion.
- **Structured review** — `approved`, `summary`, `issues`, `required_changes`,
  `confidence_score`, `stop_reason`. Unparseable output → rejection → retry.
- **Metrics** — per-call latency, prompt/output tokens, eval tokens/sec, total
  loop time, retry count, final status, stop reason.

## `workspace/` safety rules

- All writes are confined to `workspace/` (resolved with `realpath`).
- Absolute paths, `..` traversal, `~` home paths, and null bytes are rejected.
- Symlink escapes are caught because the final real path must stay inside the
  workspace.
- Missing parent directories are created safely **inside** the workspace.
- Unsafe paths are recorded as **blocked** and never written.

## Roles

| Role       | Model                |
|------------|----------------------|
| Supervisor | `qwen3:30b`          |
| Coder      | `qwen2.5-coder:32b`  |

## Workflow

1. Accept a user task.
2. **Supervisor** creates a numbered plan.
3. **Coder** implements the plan.
4. **Reviewer** (the supervisor model) returns a structured JSON verdict.
5. If rejected, feedback goes back to the Coder and step 3–4 repeat
   (up to `MAX_RETRIES` retries).
6. Print the final implementation, structured review, and metrics.

## Project layout

| File               | Responsibility                                  |
|--------------------|-------------------------------------------------|
| `main.py`          | Entry point, I/O, orchestration of the run.     |
| `loop_engine.py`   | The plan → implement → execute → review loop.   |
| `filesystem.py`    | Safe workspace file I/O (sandboxed writes).     |
| `terminal.py`      | Safe command execution (allowlist + sandbox).   |
| `database.py`      | SQLite persistence (runs, steps, ops, metrics). |
| `git_tools.py`     | Safe, narrow Git layer (status/diff/add/commit). |
| `loop_registry.py` | Named reusable loop definitions + permissions.  |
| `agent_registry.py`| Named reusable agent definitions (role/model).  |
| `stop_conditions.py`| Stop conditions + quality gates engine.        |
| `project_workspace.py`| Project workspaces (bounded read/write/cmd).  |
| `workspace_profiles.py`| Named permission profiles for workspaces.    |
| `approval_gates.py`| Human approval gates for higher-risk actions.   |
| `reports.py`       | Markdown run-report generation from SQLite.     |
| `replay.py`        | Reconstruct + replay previous loop runs.        |
| `loop_templates.py`| Reusable parameterized loop templates.          |
| `project_intelligence.py`| Read-only workspace scan + Supervisor context. |
| `memory_search.py` | SQLite memory search over prior runs.           |
| `context_packs.py` | Bounded, safe file excerpts for agent prompts.  |
| `task_intake.py`   | Task intake & clarification before side effects.|
| `external_agents.py`| External coding agent handoff adapters.        |
| `resume.py`        | Resume paused external-agent loops.             |
| `external_agent_jobs.py` | External Agent Job Packets (create/track/resume). |
| `external_agent_dashboard.py` | Read-only job dashboard + triage (stale/attention). |
| `external_completion_inbox.py` | Scan job dirs for completion files; sync via ResumeEngine. |
| `external_job_batch.py` | Batch operations over a selection of external jobs. |
| `external_batch_reports.py` | Durable Markdown reports for batch operations. |
| `audit_hotfix.py`  | Local regression audit for the 3.2.1 hotfix.    |
| `external_agent_handoffs/` | Generated handoff prompts for external agents. |
| `reports/`         | Generated per-run Markdown reports.             |
| `ollama_client.py` | Thin client over the Ollama HTTP API.           |
| `prompts.py`       | System prompts and prompt templates per role.   |
| `config.py`        | Models, host, and tunable options.              |
| `requirements.txt` | Dependencies (stdlib only — see notes).         |
| `workspace/`       | Sandbox where generated files are written.      |
| `loop_engineering.db` | SQLite database with the full run history.   |

## Prerequisites

- [Ollama](https://ollama.com) installed and running:

  ```bash
  ollama serve
  ```

- The two models pulled locally:

  ```bash
  ollama pull qwen3:30b
  ollama pull qwen2.5-coder:32b
  ```

## Install

No third-party packages are needed (standard library only):

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

Provide a task in any of these ways:

```bash
# interactive prompt (blank uses the default task)
python main.py

# command-line argument
python main.py "Write a Python LRU cache class"

# piped stdin
echo "Write a function to validate an email address" | python main.py
```

Stage 1.2 example (creates files in `workspace/`):

```bash
python main.py "Create a simple Python calculator module with tests"
```

Stage 1.3 example (creates files **and runs the tests** in `workspace/`):

```bash
python main.py "Create a calculator module with unit tests and run the tests"
```

## Configuration

Override defaults with environment variables:

| Variable             | Default                  |
|----------------------|--------------------------|
| `OLLAMA_HOST`        | `http://localhost:11434` |
| `SUPERVISOR_MODEL`   | `qwen3:30b`              |
| `CODER_MODEL`        | `qwen2.5-coder:32b`      |
| `OLLAMA_TIMEOUT`     | `600` (seconds)          |
| `OLLAMA_TEMPERATURE` | `0.3`                    |
| `LOOP_MAX_RETRIES`   | `3`                      |
| `WORKSPACE_DIR`      | `workspace`              |
| `LOOP_COMMAND_TIMEOUT` | `30` (seconds)         |
| `LOOP_MAX_COMMANDS`  | `5`                      |
| `LOOP_DB_FILE`       | `loop_engineering.db`    |

## Notes

Stage 1.5 adds a **safe Git layer**: a narrow allowlist of git operations that
can inspect changes and, with `--commit`, create a commit staging only
`workspace/` after an APPROVED run. Destructive git operations are not
implemented and cannot be invoked. Stage 1.4's SQLite memory still records every
run (now incl. `git_events`), and the workspace sandbox + terminal allowlist are
unchanged. A GUI remains deferred to a later stage.
