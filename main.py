"""Entry point for Stage 1.2 of the Loop Engineering framework.

Usage:
    python main.py
    python main.py "your task here"
    echo "your task" | python main.py
"""

import datetime
import json
import os
import sys

import agent_registry
import config
import database
import filesystem
import git_tools
import loop_engine as loop_engine_mod
import loop_registry
import loop_templates
import memory_search
import approval_gates
import context_packs
import external_agents
import ollama_client
import observatory
import observatory_actions
import observatory_action_handoff
import observatory_action_handoff_review
import observatory_action_review
import observatory_drilldown
import loop_improvement
import loop_improvement_actions
import loop_improvement_application_planner
import loop_improvement_handoff
import loop_improvement_handoff_review
import loop_improvement_review
import loop_improvement_stage5_audit
import observatory_reports
import observatory_remediation
import observatory_stage4_audit
import observatory_trends
import project_intelligence
import prompts
import resume as resume_mod
import project_workspace
import replay
import reports
import stage3_cleanup
import task_intake
import workspace_profiles
from loop_engine import LoopEngine

USAGE = """Loop Engineering — orchestrates local Ollama models in a safe
plan -> implement -> execute -> review loop.

USAGE:
  python main.py "TASK" [options]
  python main.py <command> [args]

RUN OPTIONS:
  --loop NAME                 code_build | test_fix | code_review | prompt_design | loop_design
  --workspace NAME            run inside a registered project workspace
  --intake / --no-intake      enable / disable task intake & clarification
  --commit                    commit approved changes (workspace must allow git)
  --commit-message "MSG"      commit message
  --require-approval          require human approval for risky actions
  --external-coder claude|codex|none   delegate implementation to an external agent
  --external-agent-mode handoff        external agent mode (handoff only)
  --external-completion-file PATH      import an external completion (during a run)
  --external-completion-text 'JSON'    import an external completion inline

COMMANDS:
  --history [--limit N]       list recent loops
  --show LOOP_ID              show a loop's full detail
  --loops / --loop-info NAME  list loops / show one loop definition
  --agents / --agent-info N   list agents / show one agent
  --templates / --template N  list / run loop templates
  --workspaces                list registered workspaces
  --workspace-profiles        list permission profiles
  --scan-project / --project-intel        read-only project scan / intel
  --memory-search "QUERY"     search prior runs
  --context-pack "QUERY"      build a bounded context pack
  --reports / --report LOOP_ID            list / show run reports
  --observatory [--window W | --workspace W | --loop-type T | --agent A]
  --observatory --save-report             save snapshot and Markdown report
  --observatory-snapshots / --observatory-snapshot ID
  --observatory-reports / --observatory-report ID
  --observatory-trends [--limit N | --window W | --workspace W | --metric M]
  --observatory-trend-reports / --observatory-trend-report ID
  --observatory-failures [--limit N | --workspace W | --loop-type T | --category C]
  --observatory-failure-drilldowns / --observatory-failure-drilldown ID
  --observatory-remediation [--from-failures | --from-trends | --snapshot ID]
  --observatory-remediation-plans / --observatory-remediation-plan ID
  --create-observatory-actions PLAN_ID   create manual actions from remediation plan
  --observatory-actions / --observatory-action ID
  --set-observatory-action-status ID STATUS
  --set-observatory-action-notes ID "notes" / --observatory-actions-report
  --observatory-action-review [--status S | --priority P | --category C]
  --observatory-action-reviews / --observatory-action-review-show ID
  --handoff-observatory-action ACTION_ID [--type dry_run_plan|loop_task|external_agent_job]
  --observatory-action-handoffs / --observatory-action-handoff ID
  --observatory-action-handoff-review [--status S | --type T | --workspace W]
  --observatory-action-handoff-reviews / --observatory-action-handoff-review-show ID
  --observatory-stage4-audit [--save-report]
  --observatory-stage4-audits / --observatory-stage4-audit-show ID
  --loop-improvements [--from-remediation | --from-failures | --save-report]
  --loop-improvement-plans / --loop-improvement-plan ID
  --loop-improvement-proposals / --loop-improvement-proposal ID
  --set-loop-improvement-status ID accepted|rejected|deferred
  --loop-improvement-review [--priority P | --target-type T | --status S]
  --loop-improvement-reviews / --loop-improvement-review-show ID
  --create-loop-improvement-actions REVIEW_ID [--priority P | --target-type T]
  --loop-improvement-actions / --loop-improvement-action ID
  --set-loop-improvement-action-status ID open|in_progress|completed|dismissed|blocked
  --set-loop-improvement-action-notes ID "notes" / --loop-improvement-actions-report
  --loop-improvement-action-batches / --loop-improvement-action-batch ID
  --handoff-loop-improvement-action ACTION_ID [--type dry_run_plan|loop_task|external_agent_job|implementation_packet]
  --loop-improvement-handoffs / --loop-improvement-handoff ID
  --loop-improvement-handoff-review [--status S | --type T | --group-by G]
  --loop-improvement-handoff-reviews / --loop-improvement-handoff-review-show ID
  --loop-improvement-stage5-audit [--save-report]
  --loop-improvement-stage5-audits / --loop-improvement-stage5-audit-show ID
  --plan-loop-improvement-application SOURCE_ID [--source-type action|handoff|handoff_review] [--save-report]
  --loop-improvement-application-plans / --loop-improvement-application-plan ID
  --replay LOOP_ID            replay a prior loop
  --paused                    list paused external-agent loops
  --resume LOOP_ID [--external-completion-file PATH | --external-completion-text 'JSON'] [--commit]
  --import-external-completion LOOP_ID    (backward-compatible alias for --resume)
  --external-dashboard [--workspace W | --agent A | --active | --archived]
  --external-health [--agent A | --workspace W | --status S | --include-archived | --fix-safe]
  --quarantine-health-fixtures [--dry-run]                 archive known Stage 3.9 test fixtures
  --check-portable-paths                                   report stale absolute metadata paths
  --repair-portable-paths [--dry-run]                      rebase safe stale paths into this project
  --external-inbox [--status S | --include-imported]      scan job dirs for completion files
  --sync-external-completions [--dry-run | --limit N]      import all pending completions
  --sync-external-completion JOB_ID [--dry-run]            import one job's completion
  --batch-external-jobs --action ACTION [filters] [--dry-run]
      actions: sync_completions|archive|unarchive|cancel|set_priority|add_label|
               remove_label|set_labels|clear_error|mark_needs_attention|list_selected
      filters: --job-ids 1,2,3 --status S --agent A --workspace W --priority P
               --label L --active --archived --limit N
      payloads: --priority P (set_priority) --label L (add/remove) --labels a,b (set_labels)
      (every batch auto-generates a Markdown report under external_batch_reports/)
  --external-batch-reports                                 list recent batch reports
  --external-batch-report BATCH_ID                         show one batch report
  --external-jobs [--status S | --agent A | --workspace W | --active | --archived | --stale | --needs-attention]
  --external-job JOB_ID                   show one external agent job (full metadata)
  --cancel-external-job JOB_ID            cancel a job (files preserved)
  --resume-external-job JOB_ID [--external-completion-file PATH | --external-completion-text 'JSON']
  --archive-external-job JOB_ID / --unarchive-external-job JOB_ID
  --set-external-job-priority JOB_ID low|normal|high|urgent
  --set-external-job-labels JOB_ID a,b,c
  --set-external-job-notes JOB_ID "notes"
  (job creation flags: --job-priority P  --job-labels a,b  --job-notes "...")
  --help, -h                  show this help

Resume is preferred over --import-external-completion (kept for compatibility).
"""

REGISTRY = loop_registry.LoopRegistry()
AGENTS = agent_registry.AgentRegistry()
PROFILES = workspace_profiles.WorkspaceProfileRegistry()
TEMPLATES = loop_templates.LoopTemplateRegistry()
EXTERNAL = external_agents.ExternalAgentRegistry()


def _rule(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def _get_task(args) -> str:
    if args:
        return " ".join(args).strip()
    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            return piped
    try:
        entered = input("Enter a task (blank for default): ").strip()
    except EOFError:
        entered = ""
    return entered or config.DEFAULT_TASK


def _on_step(name: str, payload=None) -> None:
    if name == "supervisor:plan:start":
        print("\n[*] Supervisor is planning...")
    elif name == "coder:start":
        kind = "implementing" if payload == 1 else "revising"
        print(f"\n[*] Coder is {kind} (attempt {payload})...")
    elif name == "apply:done":
        attempt, ap = payload
        print(f"    applied: +{len(ap.created)} created, ~{len(ap.updated)} updated, "
              f"!{len(ap.blocked)} blocked")
    elif name == "commands:start":
        attempt, cmds = payload
        if cmds:
            print(f"[*] Executing {len(cmds)} suggested command(s)...")
    elif name == "commands:done":
        attempt, results, tests_passed = payload
        ran = sum(1 for r in results if r.allowed)
        blocked = sum(1 for r in results if not r.allowed)
        tp = {True: "passed", False: "FAILED", None: "n/a"}[tests_passed]
        print(f"    commands: {ran} executed, {blocked} blocked, tests {tp}")
    elif name == "external:handoff":
        agent, mode, path, prompt, instructions = payload
        print(f"\n[EXTERNAL HANDOFF] agent={agent} mode={mode}")
        print(f"  handoff prompt: {path}")
    elif name == "external:done":
        agent, completed, violation, result = payload
        status = "completed" if completed else "NOT completed"
        viol = " (WORKSPACE VIOLATION)" if violation else ""
        print(f"    external agent {agent}: {status}{viol}")
    elif name == "approval:request":
        action, items = payload
        print(f"\n[APPROVAL REQUIRED] {action}")
        if action == "file_write":
            for f in items:
                content = f.get("content", "") or ""
                nbytes = len(content.encode("utf-8"))
                print(f"  file: {f.get('path')}  (op: write, {nbytes} bytes)")
                preview = content.splitlines()[:30]
                for line in preview:
                    print(f"    | {line}")
        elif action == "command_execute":
            for c in items:
                print(f"  command: {c}")
    elif name == "approval:decision":
        action, dec = payload
        print(f"  -> {action}: {'APPROVED' if dec.approved else 'DECLINED'} "
              f"({dec.decision}: {dec.reason})")
    elif name == "analyst:start":
        print(f"[*] Test Analyst is diagnosing the failure (attempt {payload})...")
    elif name == "analyst:done":
        attempt, analysis = payload
        print(f"    -> {analysis.failure_type} "
              f"(failure_detected={analysis.failure_detected}, "
              f"confidence {analysis.confidence_score:.2f})")
    elif name == "reviewer:start":
        print(f"[*] Reviewer is reviewing (attempt {payload})...")
    elif name == "reviewer:done":
        attempt, review = payload
        verdict = "APPROVED" if review.approved else "REJECTED"
        print(f"    -> attempt {attempt}: {verdict} "
              f"(confidence {review.confidence_score:.2f})")
    elif name == "gates:done":
        attempt, gates, conds, decision = payload
        failed = [g.gate_name for g in gates if not g.passed]
        if failed:
            print(f"    gates failed: {', '.join(failed)}")
        if decision.stop:
            print(f"    stop -> {decision.final_status} ({decision.final_condition})")


def _fmt_tokens(n: int) -> str:
    return str(n) if n else "n/a"


def _fmt_tps(x: float) -> str:
    return f"{x:.1f} tok/s" if x else "n/a"


def _print_metrics(result) -> None:
    _rule("METRICS")
    print(f"Supervisor plan latency : {result.plan_latency_s:.2f}s "
          f"(prompt {_fmt_tokens(result.plan_prompt_tokens)}, "
          f"output {_fmt_tokens(result.plan_output_tokens)}, "
          f"{_fmt_tps(result.plan_tokens_per_sec)})")

    for m in result.attempt_metrics:
        print(f"\nAttempt {m.attempt}:")
        print(f"  Coder latency     : {m.coder_latency_s:.2f}s "
              f"(prompt {_fmt_tokens(m.coder_prompt_tokens)}, "
              f"output {_fmt_tokens(m.coder_output_tokens)}, "
              f"{_fmt_tps(m.coder_tokens_per_sec)})")
        print(f"  Reviewer latency  : {m.reviewer_latency_s:.2f}s "
              f"(prompt {_fmt_tokens(m.reviewer_prompt_tokens)}, "
              f"output {_fmt_tokens(m.reviewer_output_tokens)}, "
              f"{_fmt_tps(m.reviewer_tokens_per_sec)})")
        print(f"  Files             : +{len(m.files_created)} / "
              f"~{len(m.files_updated)} / !{len(m.files_blocked)} "
              f"(created/updated/blocked)")
        ran = sum(1 for r in m.command_results if r.allowed)
        blocked = sum(1 for r in m.command_results if not r.allowed)
        codes = [("T" if r.timed_out else r.exit_code) for r in m.command_results if r.allowed]
        durs = [f"{r.duration_seconds:.2f}s" for r in m.command_results if r.allowed]
        timed = sum(1 for r in m.command_results if r.timed_out)
        tp = {True: "passed", False: "FAILED", None: "n/a"}[m.tests_passed]
        print(f"  Commands          : {m.commands_suggested} suggested, "
              f"{ran} executed, {blocked} blocked, {timed} timed out")
        print(f"  Command exit codes: {codes if codes else '[]'}  durations: {durs if durs else '[]'}")
        print(f"  Tests passed      : {tp}")
        print(f"  Approved          : {m.approved}")

    tp = {True: "passed", False: "FAILED", None: "n/a"}[result.tests_passed]
    print(f"\nTotal loop time     : {result.total_loop_s:.2f}s")
    print(f"Attempts            : {result.attempts}")
    print(f"Retry count         : {result.retry_count}")
    print(f"Commands suggested  : {len(result.suggested_commands)}")
    print(f"Commands executed   : {result.commands_executed}")
    print(f"Commands blocked    : {result.commands_blocked}")
    print(f"Tests passed        : {tp}")
    print(f"Final status        : {result.final_status}")
    print(f"Stop reason         : {result.stop_reason}")


def _print_files(result, ws=None) -> None:
    _rule("WORKSPACE FILES")
    print(f"workspace: {filesystem.workspace_dir(ws) or '(read-only: no write base)'}")
    print(f"\nCreated/updated this run ({result.total_files_changed} total):")
    for p in result.files_created:
        print(f"  + {p}")
    for p in result.files_updated:
        print(f"  ~ {p}")
    if not result.total_files_changed:
        print("  (none)")

    if result.files_blocked:
        print(f"\nBLOCKED unsafe paths ({len(result.files_blocked)}):")
        for path, reason in result.files_blocked:
            print(f"  ! {path}  -> {reason}")

    print("\nSuggested commands (safe ones executed — see COMMAND EXECUTION):")
    if result.suggested_commands:
        for c in result.suggested_commands:
            print(f"  $ {c}")
    else:
        print("  (none)")

    print("\nAll files currently in workspace:")
    for p in filesystem.list_files(ws):
        print(f"  - {p}")


def _print_commands(result) -> None:
    _rule("COMMAND EXECUTION")
    results = result.command_results
    if not results:
        print("No commands were executed.")
        return
    for r in results:
        if not r.allowed:
            print(f"$ {r.command}")
            print(f"  [BLOCKED] {r.reason_if_blocked}")
            continue
        status = "TIMED OUT" if r.timed_out else f"exit {r.exit_code}"
        print(f"$ {r.command}")
        print(f"  [{status}] {r.duration_seconds:.2f}s")
        if r.stdout.strip():
            print("  stdout:")
            for line in r.stdout.rstrip().splitlines():
                print(f"    {line}")
        if r.stderr.strip():
            print("  stderr:")
            for line in r.stderr.rstrip().splitlines():
                print(f"    {line}")


def _print_test_analyst(result) -> None:
    _rule("TEST ANALYST")
    if not result.test_analyst_used:
        print("Used: no")
        return
    a = result.test_analysis
    print("Used: yes")
    print(f"Failure detected   : {a.failure_detected}")
    print(f"Failure type       : {a.failure_type}")
    print(f"Root cause         : {a.root_cause}")
    print("Recommended changes:")
    for c in (a.recommended_changes or ["(none)"]):
        print(f"  - {c}")
    print(f"Confidence score   : {a.confidence_score}")
    if not a.parse_ok:
        print("(note: analyst JSON was unparseable)")


def _print_gates_and_stops(result) -> None:
    _rule("QUALITY GATES")
    total = result.quality_gates_passed + result.quality_gates_failed
    print(f"total          : {total}")
    print(f"passed         : {result.quality_gates_passed}")
    print(f"failed         : {result.quality_gates_failed}")
    print(f"required failed: {result.required_quality_gates_failed}")
    if result.failed_gate_names:
        print(f"failed (final attempt): {', '.join(result.failed_gate_names)}")

    _rule("STOP CONDITIONS")
    print(f"final stop condition: {result.final_stop_condition}")
    print(f"stop reason         : {result.stop_reason}")
    print(f"severity            : {result.final_severity}")
    print(f"conditions triggered: {result.stop_conditions_triggered}")


def _save_approval_metrics(recorder, engine) -> None:
    required = engine.policy.enabled
    recorder.save_metric("approval_required", 1 if required else 0, "bool")
    recorder.save_metric("approval_mode", None, "string", metric_text=engine.mode)
    recorder.save_metric("auto_approve_low_risk",
                         1 if engine.policy.auto_approve_low_risk else 0, "bool")
    recorder.save_metric("approval_requests_count", engine.requests_count, "count")
    recorder.save_metric("approval_approved_count", engine.approved_count, "count")
    recorder.save_metric("approval_declined_count", engine.declined_count, "count")
    by_action = {"file_write": 0, "command_execute": 0, "git_commit": 0}
    for req, dec in engine.history:
        if dec.decision != "not_required" and req.action_type in by_action:
            by_action[req.action_type] += 1
    recorder.save_metric("file_write_approval_required", by_action["file_write"], "count")
    recorder.save_metric("command_approval_required", by_action["command_execute"], "count")
    recorder.save_metric("git_commit_approval_required", by_action["git_commit"], "count")


def _print_approvals(engine) -> None:
    _rule("APPROVALS")
    required = engine.policy.enabled
    print(f"Required : {'yes' if required else 'no'}")
    print(f"Requests : {engine.requests_count}")
    print(f"Approved : {engine.approved_count}")
    print(f"Declined : {engine.declined_count}")
    status = "n/a" if not required else (
        "all approved" if engine.declined_count == 0 else "some declined")
    print(f"Final    : {status}")
    if engine.requests_count:
        print("\nEvents:")
        for req, dec in engine.history:
            if dec.decision == "not_required":
                continue
            print(f"  attempt {req.attempt_number} {req.action_type:<16} "
                  f"risk={req.risk_level:<8} "
                  f"{'APPROVED' if dec.approved else 'DECLINED'} ({dec.reason})")


def _save_metrics(recorder, result, roles=None) -> None:
    """Persist the key metrics for a finished loop."""
    if roles:
        for role, b in roles.items():
            recorder.save_metric(f"{role}_model", None, "string", metric_text=b.model)
            recorder.save_metric(f"{role}_agent", None, "string", metric_text=b.agent_name)
    recorder.save_metric("plan_latency_seconds", result.plan_latency_s, "seconds")
    recorder.save_metric("plan_prompt_tokens", result.plan_prompt_tokens, "tokens")
    recorder.save_metric("plan_output_tokens", result.plan_output_tokens, "tokens")
    recorder.save_metric("total_duration_seconds", result.total_loop_s, "seconds")
    recorder.save_metric("attempts", result.attempts, "count")
    recorder.save_metric("retry_count", result.retry_count, "count")
    recorder.save_metric("total_files_changed", result.total_files_changed, "count")
    recorder.save_metric("commands_executed", result.commands_executed, "count")
    recorder.save_metric("commands_blocked", result.commands_blocked, "count")
    if result.tests_passed is not None:
        recorder.save_metric("tests_passed", 1 if result.tests_passed else 0, "bool")
    # Test Analyst metrics (Stage 1.8).
    recorder.save_metric("test_analyst_used", 1 if result.test_analyst_used else 0, "bool")
    recorder.save_metric("test_analyst_latency_seconds", result.test_analyst_latency_s, "seconds")
    if result.test_analyst_failure_detected is not None:
        recorder.save_metric("test_analyst_failure_detected",
                             1 if result.test_analyst_failure_detected else 0, "bool")
    if result.test_analyst_confidence is not None:
        recorder.save_metric("test_analyst_confidence_score",
                             result.test_analyst_confidence, "score")
    # Stop conditions / quality gates metrics (Stage 1.9).
    recorder.save_metric("quality_gates_passed", result.quality_gates_passed, "count")
    recorder.save_metric("quality_gates_failed", result.quality_gates_failed, "count")
    recorder.save_metric("required_quality_gates_failed",
                         result.required_quality_gates_failed, "count")
    recorder.save_metric("stop_conditions_triggered", result.stop_conditions_triggered, "count")
    recorder.save_metric("final_stop_condition", None, "string",
                         metric_text=result.final_stop_condition)
    recorder.save_metric("reviewer_confidence_minimum", result.reviewer_confidence_min, "score")
    if result.reviewer_confidence_actual is not None:
        recorder.save_metric("reviewer_confidence_actual",
                             result.reviewer_confidence_actual, "score")
    for m in result.attempt_metrics:
        recorder.save_metric(f"attempt{m.attempt}_coder_latency_seconds",
                             m.coder_latency_s, "seconds")
        recorder.save_metric(f"attempt{m.attempt}_reviewer_latency_seconds",
                             m.reviewer_latency_s, "seconds")


def _parse_run_flags(args):
    """Split run flags (--commit, --commit-message, --loop) from the task words."""
    commit = False
    commit_message = None
    loop_name = None
    overrides = {}
    min_conf = None
    workspace_name = None
    require_approval = False
    auto_approve_low_risk = False
    approval_mode = None
    use_memory = False
    no_memory = False
    memory_limit = None
    use_context_pack = False
    no_context_pack = False
    context_max_files = None
    context_max_chars = None
    context_files = []
    intake = False
    no_intake = False
    intake_mode = None
    non_interactive = False
    external_coder = "none"
    external_agent_mode = "handoff"
    external_completion_file = None
    external_completion_text = None
    job_priority = "normal"
    job_labels = None
    job_notes = ""
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--commit":
            commit = True
            i += 1
        elif a == "--commit-message":
            commit_message = args[i + 1] if i + 1 < len(args) else None
            i += 2
        elif a == "--loop":
            loop_name = args[i + 1] if i + 1 < len(args) else None
            i += 2
        elif a in ("--supervisor-model", "--coder-model", "--reviewer-model",
                   "--test-analyst-model"):
            # "--test-analyst-model" -> role "test_analyst"
            role = a[2:].rsplit("-model", 1)[0].replace("-", "_")
            overrides[role] = args[i + 1] if i + 1 < len(args) else None
            i += 2
        elif a == "--min-reviewer-confidence":
            try:
                min_conf = float(args[i + 1]) if i + 1 < len(args) else None
            except ValueError:
                min_conf = None
            i += 2
        elif a == "--workspace":
            workspace_name = args[i + 1] if i + 1 < len(args) else None
            i += 2
        elif a == "--use-memory":
            use_memory = True
            i += 1
        elif a == "--no-memory":
            no_memory = True
            i += 1
        elif a == "--memory-limit":
            try:
                memory_limit = int(args[i + 1]) if i + 1 < len(args) else None
            except ValueError:
                memory_limit = None
            i += 2
        elif a == "--use-context-pack":
            use_context_pack = True
            i += 1
        elif a == "--no-context-pack":
            no_context_pack = True
            i += 1
        elif a == "--context-max-files":
            try:
                context_max_files = int(args[i + 1]) if i + 1 < len(args) else None
            except ValueError:
                context_max_files = None
            i += 2
        elif a == "--context-max-chars":
            try:
                context_max_chars = int(args[i + 1]) if i + 1 < len(args) else None
            except ValueError:
                context_max_chars = None
            i += 2
        elif a == "--context-file":
            if i + 1 < len(args):
                context_files.append(args[i + 1])
            i += 2
        elif a == "--intake":
            intake = True
            i += 1
        elif a == "--no-intake":
            no_intake = True
            i += 1
        elif a == "--intake-mode":
            intake_mode = args[i + 1] if i + 1 < len(args) else None
            i += 2
        elif a == "--non-interactive":
            non_interactive = True
            i += 1
        elif a == "--external-coder":
            external_coder = args[i + 1] if i + 1 < len(args) else "none"
            i += 2
        elif a == "--external-agent-mode":
            external_agent_mode = args[i + 1] if i + 1 < len(args) else "handoff"
            i += 2
        elif a == "--external-completion-file":
            external_completion_file = args[i + 1] if i + 1 < len(args) else None
            i += 2
        elif a == "--external-completion-text":
            external_completion_text = args[i + 1] if i + 1 < len(args) else None
            i += 2
        elif a == "--job-priority":
            job_priority = args[i + 1] if i + 1 < len(args) else "normal"
            i += 2
        elif a == "--job-labels":
            job_labels = args[i + 1] if i + 1 < len(args) else None
            i += 2
        elif a == "--job-notes":
            job_notes = args[i + 1] if i + 1 < len(args) else ""
            i += 2
        elif a == "--require-approval":
            require_approval = True
            i += 1
        elif a == "--auto-approve-low-risk":
            auto_approve_low_risk = True
            i += 1
        elif a == "--approval-mode":
            approval_mode = args[i + 1] if i + 1 < len(args) else None
            i += 2
        else:
            rest.append(a)
            i += 1
    return (commit, commit_message, loop_name, overrides, min_conf, workspace_name,
            require_approval, auto_approve_low_risk, approval_mode,
            use_memory, no_memory, memory_limit,
            use_context_pack, no_context_pack, context_max_files, context_max_chars,
            context_files, intake, no_intake, intake_mode, non_interactive,
            external_coder, external_agent_mode, external_completion_file,
            external_completion_text, job_priority, job_labels, job_notes, rest)


def _cmd_loops() -> int:
    _rule("LOOP REGISTRY")
    print(f"{'NAME':<14} {'VERSION':<8} {'TOOLS':<26} DESCRIPTION")
    for lp in REGISTRY.list_loops():
        tools = ",".join(lp.allowed_tools) or "none"
        marker = "  (default)" if lp.name == loop_registry.DEFAULT_LOOP else ""
        print(f"{lp.name:<14} {lp.version:<8} {tools:<26} {lp.description}{marker}")
    print("\nRun a loop with:  python main.py --loop <name> \"task\"")
    return 0


def _cmd_loop_info(args) -> int:
    if not args:
        print("ERROR: --loop-info needs a loop name", file=sys.stderr)
        return 1
    lp = REGISTRY.get_loop(args[0])
    if lp is None:
        print(f"ERROR: no loop named '{args[0]}'. Try: python main.py --loops",
              file=sys.stderr)
        return 1
    _rule(f"LOOP: {lp.name}")
    print(f"display_name      : {lp.display_name}")
    print(f"description       : {lp.description}")
    print(f"version           : {lp.version}")
    print(f"trigger_type      : {lp.trigger_type}")
    print(f"objective_template: {lp.objective_template}")
    print(f"default_models    : {lp.default_models}")
    print(f"max_retries       : {lp.max_retries}")
    print(f"allowed_tools     : {lp.allowed_tools}")
    print(f"safety_level      : {lp.safety_level}")
    print(f"tags              : {lp.tags}")
    print(f"created_at        : {lp.created_at}")
    print(f"updated_at        : {lp.updated_at}")
    print(f"\npermissions       : filesystem={lp.filesystem_enabled} "
          f"terminal={lp.terminal_enabled} git={lp.git_enabled}")
    print(f"\nagents:")
    print(f"  supervisor   : {lp.supervisor_agent}")
    print(f"  coder        : {lp.coder_agent}")
    print(f"  reviewer     : {lp.reviewer_agent}")
    print(f"  test_analyst : {lp.test_analyst_agent or '(none)'}")
    print(f"\nmin_reviewer_confidence: {lp.min_reviewer_confidence}")
    print("\nstop_conditions:")
    for s in lp.stop_conditions:
        print(f"  - {s}")
    print("\nquality_gates:")
    for q in lp.quality_gates:
        print(f"  - {q}")
    return 0


def _handle_git(conn, recorder, loop_id, task, result, commit, commit_message, loop,
                ws, approval_engine=None):
    """Report git state and (optionally) commit allowed write paths on approval."""
    project_dir = ws.root_path
    _rule("GIT")
    is_repo = git_tools.is_git_repo(project_dir)
    print(f"git repo           : {is_repo}  (root: {project_dir})")

    workspace_changed = False
    commit_attempted = False
    commit_success = False

    # Enforce the loop's tool permission: no git tool -> never commit.
    if commit and not loop.git_enabled:
        reason = f"loop '{loop.name}' does not permit the git tool"
        recorder.save_git_event("skipped", "git commit", None, "", reason)
        print(f"--commit ignored: {reason}.")
        commit = False

    # Enforce the workspace's git permission.
    if commit and not ws.allow_git:
        reason = f"workspace '{ws.name}' does not allow git"
        recorder.save_git_event("skipped", "git commit", None, "", reason)
        print(f"--commit ignored: {reason}.")
        commit = False

    # A failed required quality gate blocks committing.
    if commit and result.required_gate_failed:
        reason = (f"required quality gate(s) failed: "
                  f"{', '.join(result.failed_gate_names) or 'unknown'}")
        recorder.save_git_event("skipped", "git commit", None, "", reason)
        print(f"Commit skipped: {reason}.")
        commit = False

    if not is_repo:
        print("Not a git repository — skipping git status/diff/commit.")
        if commit:
            recorder.save_git_event("skipped", "git commit", None, "",
                                    "not a git repository")
            print("Commit skipped: not a git repository.")
    else:
        branch = git_tools.get_current_branch(project_dir)
        last = git_tools.get_last_commit(project_dir)
        print(f"current branch     : {branch}")
        print(f"last commit        : {last}")

        status = git_tools.git_status(project_dir)
        recorder.save_git_event("status", status.command, status.exit_code,
                                status.stdout, status.stderr)
        workspace_changed = git_tools.workspace_has_changes(status, ws)
        print(f"workspace changed  : {workspace_changed}")
        print("git status --short :")
        for line in (status.stdout or "").splitlines() or ["  (clean)"]:
            print(f"  {line}")

        diff = git_tools.git_diff(project_dir, ws)
        recorder.save_git_event("diff", diff.command, diff.exit_code,
                                diff.stdout, diff.stderr)

        # Commit flow.
        if commit:
            message = commit_message or f"Loop #{loop_id}: {task[:60]}"
            # Human approval for the commit, if the policy requires it.
            commit_declined = False
            if approval_engine is not None:
                gc_risk = approval_engine.default_risk("git_commit")
                if approval_engine.is_required("git_commit", gc_risk):
                    print(f"\n[APPROVAL REQUIRED] git_commit")
                    print(f"  branch : {branch}")
                    print(f"  message: {message}")
                    print(f"  staging: {ws.allowed_write_paths}")
                    import json as _json
                    req = approval_gates.ApprovalRequest(
                        loop_id=loop_id, attempt_number=0, gate_name="git_commit_gate",
                        action_type="git_commit", risk_level=gc_risk,
                        summary=f"commit on {branch}",
                        details_json=_json.dumps({"message": message,
                                                  "staging": ws.allowed_write_paths}))
                    dec = approval_engine.evaluate(req)
                    recorder.save_approval_event(req, dec)
                    print(f"  -> git_commit: {'APPROVED' if dec.approved else 'DECLINED'} "
                          f"({dec.reason})")
                    commit_declined = not dec.approved
            if result.final_status != "APPROVED":
                reason = f"final status is {result.final_status}, not APPROVED"
                recorder.save_git_event("skipped", "git add/commit", None, "", reason)
                print(f"Commit skipped: {reason}.")
            elif commit_declined:
                recorder.save_git_event("skipped", "git commit", None, "",
                                        "human approval declined")
                print("Commit skipped: human approval declined.")
            else:
                commit_attempted = True
                add = git_tools.git_add_workspace(project_dir, ws)
                recorder.save_git_event("add", add.command, add.exit_code,
                                        add.stdout, add.stderr)
                print(f"git add workspace/ : exit {add.exit_code}")
                if add.stderr.strip():
                    print(f"  stderr: {add.stderr.strip()}")

                commit_res = git_tools.git_commit(project_dir, message)
                recorder.save_git_event("commit", commit_res.command,
                                        commit_res.exit_code, commit_res.stdout,
                                        commit_res.stderr)
                commit_success = commit_res.ok
                print(f"git commit         : exit {commit_res.exit_code}")
                print(f"  message: {message}")
                if commit_res.stdout.strip():
                    for line in commit_res.stdout.strip().splitlines():
                        print(f"  {line}")
                if commit_res.stderr.strip():
                    print(f"  stderr: {commit_res.stderr.strip()}")
                if commit_success:
                    print(f"new commit hash    : {git_tools.get_last_commit(project_dir)}")
        else:
            print("(no --commit flag; not committing)")

    # Git metrics.
    recorder.save_metric("git_is_repo", 1 if is_repo else 0, "bool")
    recorder.save_metric("git_workspace_changed", 1 if workspace_changed else 0, "bool")
    recorder.save_metric("git_commit_attempted", 1 if commit_attempted else 0, "bool")
    recorder.save_metric("git_commit_success", 1 if commit_success else 0, "bool")


def _cmd_workspaces() -> int:
    conn = database.init_db()
    mgr = project_workspace.WorkspaceManager(conn)
    _rule("PROJECT WORKSPACES")
    print(f"{'NAME':<18} {'GIT':<4} ROOT_PATH")
    for ws in mgr.list_workspaces():
        print(f"{ws.name:<18} {str(ws.allow_git):<4} {ws.root_path}")
    print("\nRegister:  python main.py --register-workspace <name> <path>")
    print("Use     :  python main.py --workspace <name> \"task\"")
    return 0


def _cmd_workspace_info(args) -> int:
    if not args:
        print("ERROR: --workspace-info needs a name", file=sys.stderr)
        return 1
    conn = database.init_db()
    mgr = project_workspace.WorkspaceManager(conn)
    ws = mgr.get_workspace(args[0])
    if ws is None:
        print(f"ERROR: no workspace '{args[0]}'. Try: python main.py --workspaces",
              file=sys.stderr)
        return 1
    _rule(f"WORKSPACE: {ws.name}")
    print(f"root_path             : {ws.root_path}")
    print(f"profile_name          : {ws.profile_name}")
    print(f"profile_version       : {ws.profile_version}")
    print(f"allowed_read_paths    : {ws.allowed_read_paths}")
    print(f"allowed_write_paths   : {ws.allowed_write_paths}")
    print(f"allowed_command_paths : {ws.allowed_command_paths}")
    print(f"allow_git             : {ws.allow_git}")
    print(f"created_at            : {ws.created_at}")
    print(f"updated_at            : {ws.updated_at}")
    print("\nProtected (never written): .git/ .env .env.* node_modules/ "
          "__pycache__/ .venv/ venv/ env/ .DS_Store secrets* *.pem *.key "
          "id_rsa id_ed25519")
    return 0


def _cmd_workspace_profiles() -> int:
    _rule("WORKSPACE PERMISSION PROFILES")
    print(f"{'NAME':<14} {'GIT':<4} {'SAFETY':<9} WRITE PATHS")
    for p in PROFILES.list_profiles():
        wp = ",".join(p.allowed_write_paths) or "(none)"
        print(f"{p.name:<14} {str(p.allow_git):<4} {p.safety_level:<9} {wp}")
    print("\nApply at registration:  --register-workspace NAME PATH --profile <name>")
    print("Apply to existing    :  --set-workspace-profile NAME <profile>")
    return 0


def _cmd_workspace_profile_info(args) -> int:
    if not args:
        print("ERROR: --workspace-profile-info needs a profile name", file=sys.stderr)
        return 1
    p = PROFILES.get_profile(args[0])
    if p is None:
        print(f"ERROR: no profile '{args[0]}'. Try: python main.py --workspace-profiles",
              file=sys.stderr)
        return 1
    _rule(f"PROFILE: {p.name}")
    print(f"display_name          : {p.display_name}")
    print(f"description           : {p.description}")
    print(f"version               : {p.version}")
    print(f"safety_level          : {p.safety_level}")
    print(f"allowed_read_paths    : {p.allowed_read_paths}")
    print(f"allowed_write_paths   : {p.allowed_write_paths}")
    print(f"allowed_command_paths : {p.allowed_command_paths}")
    print(f"allow_git             : {p.allow_git}")
    print(f"protected_path_patterns: {p.protected_path_patterns}")
    print(f"allowed_command_families_override: {p.allowed_command_families_override}")
    print(f"tags                  : {p.tags}")
    return 0


def _cmd_register_workspace(args) -> int:
    rest = [a for a in args]
    profile_name = workspace_profiles.DEFAULT_PROFILE
    if "--profile" in rest:
        i = rest.index("--profile")
        if i + 1 < len(rest):
            profile_name = rest[i + 1]
        rest = rest[:i] + rest[i + 2:]
    if len(rest) < 2:
        print("ERROR: usage: --register-workspace NAME PATH [--profile NAME]",
              file=sys.stderr)
        return 1
    name, path = rest[0], rest[1]
    conn = database.init_db()
    mgr = project_workspace.WorkspaceManager(conn)
    try:
        ws = mgr.create_workspace(name, path, profile_name=profile_name)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _rule("WORKSPACE REGISTERED")
    print(f"name                  : {ws.name}")
    print(f"root_path             : {ws.root_path}")
    print(f"profile               : {ws.profile_name} (v{ws.profile_version})")
    print(f"allowed_read_paths    : {ws.allowed_read_paths}")
    print(f"allowed_write_paths   : {ws.allowed_write_paths}")
    print(f"allowed_command_paths : {ws.allowed_command_paths}")
    print(f"allow_git             : {ws.allow_git}")
    return 0


def _cmd_set_workspace_profile(args) -> int:
    if len(args) < 2:
        print("ERROR: usage: --set-workspace-profile NAME PROFILE", file=sys.stderr)
        return 1
    name, profile_name = args[0], args[1]
    conn = database.init_db()
    mgr = project_workspace.WorkspaceManager(conn)
    try:
        ws = mgr.set_workspace_profile(name, profile_name)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _rule("WORKSPACE PROFILE UPDATED")
    print(f"name                  : {ws.name}")
    print(f"profile               : {ws.profile_name} (v{ws.profile_version})")
    print(f"allowed_write_paths   : {ws.allowed_write_paths}")
    print(f"allowed_command_paths : {ws.allowed_command_paths}")
    print(f"allow_git             : {ws.allow_git}")
    return 0


def _cmd_agents() -> int:
    _rule("AGENT REGISTRY")
    print(f"{'NAME':<16} {'ROLE':<10} {'MODEL':<20} DESCRIPTION")
    for ag in AGENTS.list_agents():
        print(f"{ag.name:<16} {ag.role:<10} {ag.default_model:<20} {ag.description}")
    print("\nInspect an agent with:  python main.py --agent-info <name>")
    return 0


def _cmd_agent_info(args) -> int:
    if not args:
        print("ERROR: --agent-info needs an agent name", file=sys.stderr)
        return 1
    ag = AGENTS.get_agent(args[0])
    if ag is None:
        print(f"ERROR: no agent named '{args[0]}'. Try: python main.py --agents",
              file=sys.stderr)
        return 1
    _rule(f"AGENT: {ag.name}")
    print(f"display_name      : {ag.display_name}")
    print(f"role              : {ag.role}")
    print(f"description       : {ag.description}")
    print(f"default_model     : {ag.default_model}")
    print(f"temperature       : {ag.temperature}")
    print(f"allowed_loop_types: {ag.allowed_loop_types}")
    print(f"allowed_tools     : {ag.allowed_tools}")
    print(f"output_contract   : {ag.output_contract}")
    print(f"safety_level      : {ag.safety_level}")
    print(f"tags              : {ag.tags}")
    print(f"version           : {ag.version}")
    print(f"created_at        : {ag.created_at}")
    print(f"updated_at        : {ag.updated_at}")
    print(f"\nsystem_prompt     :\n{ag.system_prompt}")
    return 0


def _generate_and_persist_report(conn, recorder, loop_id):
    """Generate + save a Markdown report after a run. Never raises."""
    import hashlib
    import time as _time
    gen = reports.ReportGenerator(conn)
    start = _time.perf_counter()
    try:
        content = gen.generate_markdown_report(loop_id)
        path = gen.save_report(loop_id, content)
        nbytes = len(content.encode("utf-8"))
        chash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        database.save_run_report(conn, loop_id, path, "markdown", chash, nbytes)
        dur = _time.perf_counter() - start
        recorder.save_metric("report_generated", 1, "bool")
        recorder.save_metric("report_bytes_written", nbytes, "bytes")
        recorder.save_metric("report_generation_seconds", dur, "seconds")
        recorder.save_metric("report_generation_failed", 0, "bool")
        recorder.save_quality_gate_result(0, "report_generated", True, True,
                                          "error", f"report saved: {path}")
        return path, None
    except Exception as exc:  # never block completion on report failure
        dur = _time.perf_counter() - start
        recorder.save_metric("report_generated", 0, "bool")
        recorder.save_metric("report_generation_seconds", dur, "seconds")
        recorder.save_metric("report_generation_failed", 1, "bool")
        recorder.save_quality_gate_result(0, "report_generated", False, True,
                                          "error", f"report generation failed: {exc}")
        return None, str(exc)


def _report_path_display(path) -> str:
    """Render a report path safely. Copied DBs may carry stale absolute paths
    pointing at another repo; flag those instead of pretending they're valid."""
    if not path:
        return "(none)"
    if os.path.exists(path):
        return path
    if os.path.isabs(path):
        return (f"missing/non-portable report path "
                f"(run --report LOOP_ID to regenerate): {path}")
    return f"missing report path (run --report LOOP_ID to regenerate): {path}"


def _cmd_report(args) -> int:
    if not args:
        print("ERROR: --report needs a LOOP_ID", file=sys.stderr)
        return 1
    try:
        loop_id = int(args[0])
    except ValueError:
        print("ERROR: LOOP_ID must be an integer", file=sys.stderr)
        return 1
    conn = database.init_db()
    if database.get_loop(conn, loop_id) is None:
        print(f"ERROR: no loop with id {loop_id}", file=sys.stderr)
        return 1
    gen = reports.ReportGenerator(conn)
    path = gen.get_report_path(loop_id)
    if path is None or not os.path.exists(path):
        # Generate on demand from SQLite data.
        content = gen.generate_markdown_report(loop_id)
        path = gen.save_report(loop_id, content)
        import hashlib
        database.save_run_report(conn, loop_id, path, "markdown",
                                 hashlib.sha256(content.encode("utf-8")).hexdigest(),
                                 len(content.encode("utf-8")))
    else:
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
    print(f"report path: {path}\n")
    print(content)
    return 0


def _cmd_reports(args) -> int:
    limit = 20
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                pass
    conn = database.init_db()
    rows = reports.ReportGenerator(conn).list_reports(limit)
    _rule(f"RUN REPORTS (latest {len(rows)})")
    if not rows:
        print("(no reports yet)")
        return 0
    print(f"{'LOOP':>5}  {'CREATED_AT':<19}  {'STATUS':<11}  TASK / PATH")
    for r in rows:
        print(f"{r['loop_id']:>5}  {str(r['created_at']):<19}  "
              f"{str(r['status']):<11}  {(r['task'] or '')[:40]}")
        print(f"{'':>5}  {_report_path_display(r['report_path'])}")
    return 0


def _cmd_history(args) -> int:
    limit = 20
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                print("ERROR: --limit needs an integer", file=sys.stderr)
                return 1
    conn = database.init_db()
    rows = database.list_loops(conn, limit)
    _rule(f"LOOP HISTORY (latest {len(rows)})")
    if not rows:
        print("(no runs recorded yet)")
        return 0
    print(f"{'ID':>4}  {'CREATED_AT':<19}  {'LOOP_TYPE':<13}  {'WORKSPACE':<14}  "
          f"{'STATUS':<9}  {'RETRY':>5}  {'DUR(s)':>7}  TASK")
    for r in rows:
        dur = f"{r['total_duration_seconds']:.1f}" if r['total_duration_seconds'] is not None else "-"
        task_preview = (r["task"] or "")[:34]
        ltype = r["loop_type"] or "-"
        wsname = r["workspace_name"] or "default"
        print(f"{r['id']:>4}  {str(r['created_at']):<19}  {str(ltype):<13}  "
              f"{str(wsname):<14}  {str(r['status']):<9}  {str(r['retry_count']):>5}  "
              f"{dur:>7}  {task_preview}")
        tmpl = r["template_name"] if "template_name" in r.keys() else None
        suffix = f"  [template: {tmpl}]" if tmpl else ""
        print(f"{'':>4}  stop_reason: {r['stop_reason']}{suffix}")
    return 0


def _cmd_show(args) -> int:
    if not args:
        print("ERROR: --show needs a LOOP_ID", file=sys.stderr)
        return 1
    try:
        loop_id = int(args[0])
    except ValueError:
        print("ERROR: LOOP_ID must be an integer", file=sys.stderr)
        return 1

    conn = database.init_db()
    loop = database.get_loop(conn, loop_id)
    if loop is None:
        print(f"ERROR: no loop with id {loop_id}", file=sys.stderr)
        return 1

    _rule(f"LOOP #{loop_id} SUMMARY")
    print(f"created_at  : {loop['created_at']}")
    print(f"task        : {loop['task']}")
    print(f"loop_type   : {loop['loop_type']}")
    print(f"loop_version: {loop['loop_version']}")
    print(f"status      : {loop['status']}")
    print(f"stop_reason : {loop['stop_reason']}")
    print(f"retry_count : {loop['retry_count']}")
    print(f"duration    : {loop['total_duration_seconds']}s")
    print(f"workspace   : {loop['workspace_name']}  (root: {loop['workspace_root']})")
    if ("intake_used" in loop.keys()) and loop["intake_used"]:
        print(f"intake      : used (status {loop['intake_status']})")
        print(f"raw_task    : {loop['raw_task']}")
        print(f"clarified   : {loop['clarified_task']}")
    print(f"models      : supervisor={loop['supervisor_model']} "
          f"coder={loop['coder_model']} reviewer={loop['reviewer_model']}")
    if loop["template_name"]:
        print(f"template    : {loop['template_name']} (v{loop['template_version']})")
        print(f"variables   : {loop['template_variables_json']}")
        print(f"rendered    : {loop['rendered_task']}")
    _pid = loop["project_intelligence_report_id"] if "project_intelligence_report_id" in loop.keys() else None
    if _pid:
        print(f"project intel: report #{_pid}")
    _cpid = loop["context_pack_id"] if "context_pack_id" in loop.keys() else None
    if _cpid:
        print(f"context pack: #{_cpid}")
    _rep = database.get_run_report(conn, loop_id)
    print(f"report      : {_report_path_display(_rep['report_path'] if _rep else None)}")
    _from = database.get_replay_events_for_new_loop(conn, loop_id)
    if _from:
        e = _from[-1]
        print(f"replay of   : loop #{e['source_loop_id']} (mode {e['replay_mode']})")
    _repl = database.get_replay_events_for_source(conn, loop_id)
    if _repl:
        print(f"replayed    : {len(_repl)} time(s)")

    steps = database.get_steps(conn, loop_id)
    reviews = database.get_reviews(conn, loop_id)
    fops = database.get_file_operations(conn, loop_id)
    cmds = database.get_command_results(conn, loop_id)
    metrics = database.get_metrics(conn, loop_id)

    attempts = max([s["attempt_number"] for s in steps], default=0)
    print(f"attempts    : {attempts}")

    _rule("STEPS")
    for s in steps:
        print(f"  #{s['id']} attempt {s['attempt_number']} {s['step_name']:<16} "
              f"role={s['agent_role']:<10} {s['latency_seconds']:.2f}s "
              f"(prompt {s['prompt_eval_count']}, output {s['eval_count']}, "
              f"{s['eval_tokens_per_second']:.1f} tok/s)")

    _rule("REVIEWS")
    for rv in reviews:
        print(f"  attempt {rv['attempt_number']}: approved={bool(rv['approved'])} "
              f"confidence={rv['confidence_score']} stop={rv['stop_reason']}")
        print(f"    summary: {rv['summary']}")
        print(f"    issues: {rv['issues_json']}")
        print(f"    required_changes: {rv['required_changes_json']}")

    _rule("FILE OPERATIONS")
    for f in fops:
        flag = "OK" if f["allowed"] else f"BLOCKED ({f['reason_if_blocked']})"
        print(f"  attempt {f['attempt_number']} {f['operation']:<7} {f['path']:<28} "
              f"{flag} bytes={f['bytes_written']} sha={(f['content_hash'] or '')[:12]}")

    executed = sum(1 for c in cmds if c["allowed"])
    blocked = sum(1 for c in cmds if not c["allowed"])
    _rule(f"COMMAND RESULTS (executed {executed}, blocked {blocked})")
    for c in cmds:
        if not c["allowed"]:
            print(f"  attempt {c['attempt_number']} [BLOCKED] {c['command']} "
                  f"-> {c['reason_if_blocked']}")
        else:
            status = "TIMED OUT" if c["timed_out"] else f"exit {c['exit_code']}"
            print(f"  attempt {c['attempt_number']} [{status}] {c['command']} "
                  f"({c['duration_seconds']:.2f}s)")

    git_events = database.get_git_events(conn, loop_id)
    _rule("GIT EVENTS")
    if not git_events:
        print("  (none)")
    for g in git_events:
        head = (g["stdout"] or g["stderr"] or "").strip().splitlines()
        head = head[0] if head else ""
        print(f"  attempt - {g['event_type']:<8} {g['command']:<28} "
              f"exit={g['exit_code']}  {head[:40]}")

    qg = database.get_quality_gate_results(conn, loop_id)
    _rule("QUALITY GATE RESULTS")
    if not qg:
        print("  (none)")
    for g in qg:
        flag = "PASS" if g["passed"] else "FAIL"
        req = "required" if g["required"] else "optional"
        print(f"  attempt {g['attempt_number']} [{flag}] {g['gate_name']:<28} "
              f"({req}, {g['severity']})  {g['message']}")

    sc = database.get_stop_condition_results(conn, loop_id)
    _rule("STOP CONDITION RESULTS")
    if not sc:
        print("  (none)")
    for s in sc:
        mark = "TRIGGERED" if s["triggered"] else "-"
        print(f"  attempt {s['attempt_number']} [{mark:<9}] {s['condition_name']:<26} "
              f"({s['severity']})  {s['message']}")

    agent_events = database.get_agent_events(conn, loop_id)
    _rule("AGENT EVENTS")
    if not agent_events:
        print("  (none)")
    for a in agent_events:
        detail = f"  {a['details_json']}" if a["details_json"] else ""
        print(f"  {a['event_type']:<20} role={a['agent_role']:<10} "
              f"agent={a['agent_name']:<14} model={a['model']}{detail}")

    approvals = database.get_approval_events(conn, loop_id)
    _rule("APPROVAL EVENTS")
    if not approvals:
        print("  (none)")
    for a in approvals:
        verdict = "APPROVED" if a["approved"] else "DECLINED"
        print(f"  attempt {a['attempt_number']} {a['action_type']:<16} "
              f"risk={a['risk_level']:<8} [{verdict}] {a['decision']} - {a['summary']}")

    ext_events = database.get_external_agent_events(conn, loop_id)
    _rule("EXTERNAL CODING AGENT EVENTS")
    if not ext_events:
        print("  (none)")
    for e in ext_events:
        print(f"  agent={e['external_agent_name']} mode={e['mode']} "
              f"completed={bool(e['completed'])} success={bool(e['success'])} "
              f"files={len(json.loads(e['files_changed_json'] or '[]'))}")
        print(f"    handoff: {e['handoff_path']}")
        if e["summary"]:
            print(f"    summary: {e['summary']}")
        if e["error"]:
            print(f"    error: {e['error']}")
        if ("completion_imported_at" in e.keys()) and e["completion_imported_at"]:
            cj = json.loads(e["completion_json"] or "{}")
            print(f"    completion: status={e['completion_status']} "
                  f"parsed={bool(e['completion_parsed'])} "
                  f"tests_passed={cj.get('tests_passed')}")
            print(f"      summary: {cj.get('summary', '')}")
            print(f"      files changed: {cj.get('files_changed', [])}")
            print(f"      commands run: {cj.get('commands_run', [])}")
            print(f"      tests run: {cj.get('tests_run', [])}")
            print(f"      issues: {cj.get('issues', [])}")
            print(f"      notes: {cj.get('notes', [])}")
            print(f"      next steps: {cj.get('next_steps', [])}")

    resume_events = database.get_resume_events(conn, loop_id)
    _rule("RESUME EVENTS")
    if not resume_events:
        print("  (none)")
    for r in resume_events:
        print(f"  type={r['resume_type']} completion_imported={bool(r['completion_imported'])} "
              f"{r['status_before']} -> {r['status_after']} stop={r['stop_reason']}")
        print(f"    commit_requested={bool(r['commit_requested'])} "
              f"commit_created={bool(r['commit_created'])}")

    job = database.get_external_agent_job_for_loop(conn, loop_id)
    if job is not None:
        import external_agent_jobs as _eaj
        jb = _eaj.ExternalAgentJobManager(conn).get_job(job["id"])
        _rule("EXTERNAL AGENT JOB")
        print(f"  job #{jb.id}  agent={jb.external_agent_name}  status={jb.status}")
        print(f"    priority={jb.priority}  archived={'yes' if jb.archived else 'no'}  "
              f"retry_count={jb.retry_count}")
        print(f"    labels: {', '.join(jb.labels) or '(none)'}")
        print(f"    notes: {jb.notes or '(none)'}")
        print(f"    last_error: {jb.last_error or '(none)'}")
        print(f"    packet : {_report_path_display(jb.packet_path)}")
        print(f"    handoff: {_report_path_display(jb.handoff_path)}")
        print(f"    completion: {jb.completion_path or '(none)'}")
        print(f"    resume : python3 main.py --resume-external-job {jb.id} "
              f"--external-completion-file completion.json")
        ibx = database.get_external_completion_inbox_events(conn, jb.id)
        if ibx:
            print("    inbox events:")
            for e in ibx:
                print(f"      {e['created_at']} {e['action']} status={e['status']}"
                      f"{' DRY' if e['dry_run'] else ''}"
                      f"{('  error=' + e['error']) if e['error'] else ''}")
        bev = database.get_external_job_batch_events(conn, job_id=jb.id, limit=10)
        if bev:
            print("    batch events:")
            seen_b = []
            for e in bev:
                verdict = "skipped" if e["skipped"] else ("ok" if e["success"] else "FAILED")
                print(f"      {e['created_at']} {e['action']} {verdict}"
                      f"{' DRY' if e['dry_run'] else ''}"
                      f"{('  error=' + e['error']) if e['error'] else ''}")
        health_events = database.get_external_job_health_events(conn, job_id=jb.id, limit=10)
        if health_events:
            print("    health events:")
            for h in health_events:
                fixed = " fixed" if h["fixed"] else ""
                print(f"      {h['created_at']} [{h['severity']}] "
                      f"{h['issue_type']}{fixed}: {h['message']}")
                print(f"        action: {h['recommended_action']}")
    else:
        health_events = database.get_external_job_health_events(conn, loop_id=loop_id, limit=10)
        if health_events:
            _rule("EXTERNAL JOB HEALTH EVENTS")
            for h in health_events:
                print(f"  job={h['job_id'] or '-'} [{h['severity']}] {h['issue_type']}")
                print(f"    {h['message']}")
                print(f"    action: {h['recommended_action']}")
                if e["batch_id"] and e["batch_id"] not in seen_b:
                    seen_b.append(e["batch_id"])
            brefs = [database.get_external_batch_report(conn, b) for b in seen_b]
            brefs = [r for r in brefs if r is not None]
            if brefs:
                print("    batch reports:")
                for r in brefs:
                    print(f"      {r['batch_id']}: {_report_path_display(r['report_path'])}")

    intake_events = database.get_task_intake_events(conn, loop_id)
    _rule("TASK INTAKE EVENTS")
    if not intake_events:
        print("  (none)")
    for ie in intake_events:
        print(f"  status={ie['status']} risk={ie['risk_level']} "
              f"confidence={ie['confidence_score']} ambiguity={ie['ambiguity_score']} "
              f"clarification_required={bool(ie['clarification_required'])}")
        print(f"    raw: {ie['raw_task']}")
        print(f"    clarified: {ie['clarified_task']}")
        qs = json.loads(ie["clarification_questions_json"] or "[]")
        ans = json.loads(ie["clarification_answers_json"] or "{}") if ie["clarification_answers_json"] else {}
        for q in qs:
            print(f"    Q[{q.get('id')}] {q.get('question')} -> A: {ans.get(q.get('id'), '(unanswered)')}")

    cp = database.get_context_pack(conn, loop_id)
    _rule("CONTEXT PACK")
    if cp is None:
        print("  (none)")
    else:
        import json as _json
        w = _json.loads(cp["warnings_json"] or "[]")
        print(f"  pack #{cp['id']}  files={cp['total_files_included']}/"
              f"{cp['total_files_considered']}  chars={cp['total_chars']}  "
              f"truncated={bool(cp['truncated'])}")
        for f in database.get_context_pack_files(conn, cp["id"]):
            print(f"    [{f['relevance_score']:>4.2f}] {f['path']} "
                  f"({f['detected_language']}) — {f['reason']}"
                  f"{' [truncated]' if f['truncated'] else ''}")
        if w:
            print(f"    warnings: {'; '.join(w)}")

    mem_events = database.get_memory_search_events(conn, loop_id)
    _rule("MEMORY SEARCH EVENTS")
    if not mem_events:
        print("  (none)")
    for me in mem_events:
        print(f"  query: {me['query']!r}  results={me['result_count']}  "
              f"used_for_context={bool(me['used_for_context'])}")
        try:
            tops = json.loads(me["top_results_json"] or "[]")
        except (ValueError, TypeError):
            tops = []
        for t in tops[:5]:
            print(f"    - [{t.get('source_type')}] {t.get('title')} :: "
                  f"{(t.get('snippet') or '')[:80]}")

    tmpl_events = database.get_loop_template_events(conn, loop_id)
    _rule("TEMPLATE EVENTS")
    if not tmpl_events:
        print("  (none)")
    for t in tmpl_events:
        print(f"  {t['template_name']} (v{t['template_version']}) [{t['status']}] "
              f"- {t['message']}")
        print(f"    vars: {t['variables_json']}")

    rev_src = database.get_replay_events_for_source(conn, loop_id)
    rev_new = database.get_replay_events_for_new_loop(conn, loop_id)
    _rule("REPLAY EVENTS")
    if not rev_src and not rev_new:
        print("  (none)")
    for e in rev_new:
        print(f"  created from loop #{e['source_loop_id']} (mode {e['replay_mode']}, "
              f"dry_run={bool(e['dry_run'])})")
    for e in rev_src:
        tgt = f"-> new loop #{e['new_loop_id']}" if e['new_loop_id'] else "(dry run)"
        print(f"  replayed (mode {e['replay_mode']}) {tgt} status={e['status']}")

    _rule("METRICS")
    for m in metrics:
        val = m["metric_text"] if m["metric_text"] is not None else m["metric_value"]
        print(f"  {m['metric_name']:<34} {val} {m['metric_unit']}")
    return 0


def _parse_completion_args(args):
    cfile = ctext = None
    i = 0
    while i < len(args):
        if args[i] == "--external-completion-file":
            cfile = args[i + 1] if i + 1 < len(args) else None; i += 2
        elif args[i] == "--external-completion-text":
            ctext = args[i + 1] if i + 1 < len(args) else None; i += 2
        else:
            i += 1
    return cfile, ctext


def _resume_finish_print(loop_id, res) -> int:
    _rule("FINAL RESULT")
    print(f"{res.status} - loop #{loop_id} "
          f"{'resumed' if res.resumed else 'not resumed'}. "
          f"Stop reason: {res.stop_reason}.")
    if res.report_path:
        print(f"Report: {res.report_path}")
    return 0 if res.status == "APPROVED" else 2


def _cmd_import_external_completion(args) -> int:
    # Backward-compatible: routes through the ResumeEngine.
    if not args:
        print("ERROR: --import-external-completion needs a LOOP_ID", file=sys.stderr)
        return 1
    try:
        loop_id = int(args[0])
    except ValueError:
        print("ERROR: LOOP_ID must be an integer", file=sys.stderr)
        return 1
    cfile, ctext = _parse_completion_args(args[1:])
    conn = database.init_db()
    if database.get_loop(conn, loop_id) is None:
        print(f"ERROR: no loop with id {loop_id}", file=sys.stderr)
        return 1
    linked_job, job_reason = stage3_cleanup.select_job_for_loop_import(conn, loop_id)
    if job_reason:
        print(f"ERROR: {job_reason}", file=sys.stderr)
        print("Use: python3 main.py --resume-external-job JOB_ID "
              "--external-completion-file completion.json", file=sys.stderr)
        return 2
    _rule("IMPORT EXTERNAL COMPLETION")
    print(f"loop #{loop_id}")
    if linked_job is not None:
        print(f"linked external job #{linked_job['id']} "
              f"status={linked_job['status'] if 'status' in linked_job.keys() else '-'}")
        if cfile:
            import external_agent_jobs as _eaj
            _eaj.ExternalAgentJobManager(conn).mark_completion_imported(linked_job["id"], cfile)
    req = resume_mod.ResumeRequest(loop_id=loop_id, completion_file=cfile,
                                   completion_text=ctext)
    res = resume_mod.ResumeEngine().resume(conn, req, resume_type="import",
                                           on_event=lambda m: print(f"  {m}"))
    if linked_job is not None:
        status_after = stage3_cleanup.update_linked_job_after_loop_import(
            conn, linked_job, cfile, res.status, res.stop_reason)
        print(f"linked external job #{linked_job['id']} -> {status_after}")
    return _resume_finish_print(loop_id, res)


def _cmd_resume(args) -> int:
    if not args:
        print("ERROR: --resume needs a LOOP_ID", file=sys.stderr)
        return 1
    try:
        loop_id = int(args[0])
    except ValueError:
        print("ERROR: LOOP_ID must be an integer", file=sys.stderr)
        return 1
    rest = args[1:]
    cfile, ctext = _parse_completion_args(rest)
    commit = "--commit" in rest
    require_approval = "--require-approval" in rest
    commit_message = approval_mode = None
    if "--commit-message" in rest:
        i = rest.index("--commit-message")
        if i + 1 < len(rest):
            commit_message = rest[i + 1]
    if "--approval-mode" in rest:
        i = rest.index("--approval-mode")
        if i + 1 < len(rest):
            approval_mode = rest[i + 1]
    conn = database.init_db()
    if database.get_loop(conn, loop_id) is None:
        print(f"ERROR: no loop with id {loop_id}", file=sys.stderr)
        return 1
    _rule("RESUME LOOP")
    print(f"loop #{loop_id}  commit={commit}")
    req = resume_mod.ResumeRequest(
        loop_id=loop_id, completion_file=cfile, completion_text=ctext,
        require_approval=require_approval, approval_mode=approval_mode,
        commit=commit, commit_message=commit_message)
    res = resume_mod.ResumeEngine().resume(conn, req, resume_type="resume",
                                           on_event=lambda m: print(f"  {m}"))
    return _resume_finish_print(loop_id, res)


def _cmd_paused(args) -> int:
    conn = database.init_db()
    rows = database.list_paused_external_loops(conn, 20)
    _rule(f"PAUSED EXTERNAL-AGENT LOOPS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for r in rows:
        print(f"#{r['id']}  {r['created_at']}  [{r['status']}]  "
              f"ws={r['workspace_name']}  agent={r['ext_agent'] or '-'}")
        print(f"    task: {(r['task'] or '')[:60]}")
        print(f"    handoff: {r['handoff_path'] or '-'}")
        print(f"    resume:  python main.py --resume {r['id']} "
              f"--external-completion-file completion.json")
    return 0


def _flag_val(args, flag):
    if flag in args:
        i = args.index(flag)
        if i + 1 < len(args):
            return args[i + 1]
    return None


def _cmd_external_jobs(args) -> int:
    import external_agent_jobs as eaj
    import external_agent_dashboard as dash
    conn = database.init_db()
    mgr = eaj.ExternalAgentJobManager(conn)
    status = _flag_val(args, "--status")
    agent = _flag_val(args, "--agent")
    workspace = _flag_val(args, "--workspace")
    archived = True if "--archived" in args else (False if "--active" in args else None)
    stale = "--stale" in args
    needs_attn = "--needs-attention" in args
    jobs = mgr._list(archived=archived, agent_name=agent, workspace_name=workspace,
                     status=status, limit=1000 if (stale or needs_attn) else 20)
    if stale:
        jobs = [j for j in jobs if dash.is_stale(j)]
    if needs_attn:
        jobs = [j for j in jobs if dash.needs_attention(j)]
    jobs = jobs[:50]
    filt = ", ".join(f for f in [
        f"status={status}" if status else "", f"agent={agent}" if agent else "",
        f"workspace={workspace}" if workspace else "",
        "archived" if archived is True else ("active" if archived is False else ""),
        "stale" if stale else "", "needs-attention" if needs_attn else ""]
        if f)
    _rule(f"EXTERNAL AGENT JOBS ({len(jobs)}{f' | {filt}' if filt else ''})")
    if not jobs:
        print("(none)")
        return 0
    for j in jobs:
        print(f"job #{j.id}  loop=#{j.loop_id}  agent={j.external_agent_name}  "
              f"[{j.status}]  priority={j.priority}  archived={'yes' if j.archived else 'no'}")
        print(f"    labels: {', '.join(j.labels) or '-'}  ws={j.workspace_name}")
        print(f"    created={j.created_at}  updated={j.updated_at}")
        print(f"    handoff: {_report_path_display(j.handoff_path)}")
    return 0


def _cmd_external_job(args) -> int:
    import external_agent_jobs as eaj
    if not args:
        print("ERROR: --external-job needs a JOB_ID", file=sys.stderr)
        return 1
    try:
        job_id = int(args[0])
    except ValueError:
        print("ERROR: JOB_ID must be an integer", file=sys.stderr)
        return 1
    conn = database.init_db()
    mgr = eaj.ExternalAgentJobManager(conn)
    s = mgr.get_job_summary(job_id)
    if not s:
        print(f"ERROR: no external agent job with id {job_id}", file=sys.stderr)
        return 1
    _rule(f"EXTERNAL AGENT JOB #{job_id}")
    print(f"loop id        : {s['loop_id']}")
    print(f"agent          : {s['agent']}")
    print(f"status         : {s['status']}")
    print(f"priority       : {s['priority']}")
    print(f"labels         : {', '.join(s['labels']) or '(none)'}")
    print(f"notes          : {s['notes'] or '(none)'}")
    print(f"archived       : {'yes' if s['archived'] else 'no'}")
    print(f"retry_count    : {s['retry_count']}")
    print(f"last_error     : {s['last_error'] or '(none)'}")
    print(f"metadata_valid : {s['metadata_valid']}"
          + (f" ({s['metadata_reasons']})" if not s['metadata_valid'] else ""))
    print(f"handoff path   : {_report_path_display(s['handoff_path'])}")
    print(f"packet path    : {_report_path_display(s['packet_path'])}")
    print(f"completion path: {s['completion_path'] or '(none)'}")
    print(f"created/updated: {s['created_at']} / {s['updated_at']}")
    print(f"completed_at   : {s['completed_at'] or '(none)'}")
    print(f"cancelled_at   : {s['cancelled_at'] or '(none)'}")
    print(f"archived_at    : {s['archived_at'] or '(none)'}")
    # Linked loop summary.
    loop = database.get_loop(conn, s["loop_id"]) if s["loop_id"] else None
    if loop is not None:
        print(f"loop summary   : {loop['loop_type']} [{loop['status']}] "
              f"task={(loop['task'] or '')[:50]}")
    print("commands:")
    print(f"  resume   : python3 main.py --resume-external-job {job_id} "
          f"--external-completion-file completion.json")
    print(f"  cancel   : python3 main.py --cancel-external-job {job_id}")
    print(f"  archive  : python3 main.py --archive-external-job {job_id}")
    print(f"  unarchive: python3 main.py --unarchive-external-job {job_id}")
    _rule("JOB TIMELINE")
    for ts, et, sb, sa in s["timeline"]:
        print(f"  {ts}  {et}  {sb} -> {sa}")
    inbox_events = database.get_external_completion_inbox_events(conn, job_id)
    if inbox_events:
        _rule("COMPLETION INBOX EVENTS")
        for e in inbox_events:
            print(f"  {e['created_at']}  {e['action']}  status={e['status']}  "
                  f"type={e['completion_type'] or '-'}"
                  f"{' DRY' if e['dry_run'] else ''}"
                  f"{('  error=' + e['error']) if e['error'] else ''}")
    batch_events = database.get_external_job_batch_events(conn, job_id=job_id, limit=10)
    if batch_events:
        _rule("BATCH EVENTS")
        seen_batches = []
        for e in batch_events:
            verdict = "skipped" if e["skipped"] else ("ok" if e["success"] else "FAILED")
            print(f"  {e['created_at']}  {e['action']}  {verdict}  "
                  f"{e['status_before']} -> {e['status_after']}"
                  f"{' DRY' if e['dry_run'] else ''}"
                  f"{('  error=' + e['error']) if e['error'] else ''}")
            if e["batch_id"] and e["batch_id"] not in seen_batches:
                seen_batches.append(e["batch_id"])
        # Batch report references involving this job.
        refs = [database.get_external_batch_report(conn, b) for b in seen_batches]
        refs = [r for r in refs if r is not None]
        if refs:
            _rule("BATCH REPORTS")
            for r in refs:
                print(f"  {r['batch_id']}  {_report_path_display(r['report_path'])}")
                print(f"    view: python3 main.py --external-batch-report {r['batch_id']}")
    health_events = database.get_external_job_health_events(conn, job_id=job_id, limit=10)
    if health_events:
        _rule("HEALTH EVENTS")
        for h in health_events:
            fixed = " fixed" if h["fixed"] else ""
            print(f"  {h['created_at']}  [{h['severity']}] {h['issue_type']}{fixed}")
            print(f"    {h['message']}")
            print(f"    action: {h['recommended_action']}")
            if h["fix_action"]:
                print(f"    fix: {h['fix_action']}")
    return 0


def _cmd_external_health(args) -> int:
    import external_job_health as health
    conn = database.init_db()
    agent = _flag_val(args, "--agent")
    workspace = _flag_val(args, "--workspace")
    status = _flag_val(args, "--status")
    include_archived = "--include-archived" in args
    fix_safe = "--fix-safe" in args

    checker = health.ExternalJobHealthChecker(conn)
    report = checker.run(agent=agent, workspace=workspace, status=status,
                         include_archived=include_archived, fix_safe=fix_safe)
    issue_counts = {}
    severity_counts = {"info": 0, "warning": 0, "error": 0, "critical": 0}
    for issue in report.issues:
        issue_counts[issue.issue_type] = issue_counts.get(issue.issue_type, 0) + 1
        severity_counts[issue.severity] = severity_counts.get(issue.severity, 0) + 1

    _rule("EXTERNAL AGENT JOB HEALTH")
    filt = ", ".join(x for x in [
        f"agent={agent}" if agent else "",
        f"workspace={workspace}" if workspace else "",
        f"status={status}" if status else "",
        "include_archived" if include_archived else "",
        "fix_safe" if fix_safe else "",
    ] if x)
    if filt:
        print(f"filter: {filt}")

    _rule("SUMMARY")
    print(f"Total jobs checked              : {report.total_jobs_checked}")
    print(f"Healthy                         : {report.healthy_jobs}")
    print(f"Warnings                        : {severity_counts.get('warning', 0)}")
    print(f"Errors                          : {severity_counts.get('error', 0)}")
    print(f"Critical                        : {severity_counts.get('critical', 0)}")
    print(f"Stale waiting jobs              : {report.stale_waiting}")
    print(f"Jobs with pending completions   : {report.pending_completions}")
    print(f"Jobs with missing files         : {report.missing_files_jobs}")
    print(f"Jobs with broken references     : {report.broken_reference_jobs}")
    print(f"Safe fixes requested            : {'yes' if fix_safe else 'no'}")
    if fix_safe:
        fixed = sum(1 for i in report.issues if i.fixed)
        print(f"Safe metadata fixes applied     : {fixed}")

    _rule("ISSUES")
    if not report.issues:
        print("(none)")
    for issue in report.issues:
        print(f"[{issue.severity}] job={issue.job_id or '-'} loop={issue.loop_id or '-'} "
              f"{issue.issue_type}")
        print(f"  message : {issue.message}")
        print(f"  action  : {issue.recommended_action}")
        if issue.fixed:
            print(f"  fixed   : {issue.fix_action}")

    _rule("RECOMMENDED ACTIONS")
    if not report.recommendations:
        print("(none)")
    for action in report.recommendations:
        print(f"- {action}")
    shown = set(report.recommendations)
    for issue in report.issues:
        if issue.job_id:
            cmd = f"python3 main.py --external-job {issue.job_id}"
            if cmd not in shown:
                print(f"- {cmd}")
                shown.add(cmd)
            cmd = f"python3 main.py --sync-external-completion {issue.job_id}"
            if issue.issue_type == "completion_waiting_import" and cmd not in shown:
                print(f"- {cmd}")
                shown.add(cmd)
            cmd = f"python3 main.py --cancel-external-job {issue.job_id}"
            if issue.issue_type in ("stale_waiting_job", "archived_waiting_job") and cmd not in shown:
                print(f"- {cmd}")
                shown.add(cmd)
            cmd = f"python3 main.py --archive-external-job {issue.job_id}"
            if cmd not in shown:
                print(f"- {cmd}")
                shown.add(cmd)
        if issue.loop_id:
            cmd = f"python3 main.py --report {issue.loop_id}"
            if issue.issue_type == "broken_report_reference" and cmd not in shown:
                print(f"- {cmd}")
                shown.add(cmd)
        try:
            details = json.loads(issue.details_json or "{}")
        except (ValueError, TypeError):
            details = {}
        batch_id = details.get("batch_id")
        if batch_id:
            cmd = f"python3 main.py --external-batch-report {batch_id}"
            if cmd not in shown:
                print(f"- {cmd}")
                shown.add(cmd)
    return 0 if not any(i.severity in ("error", "critical") for i in report.issues) else 2


def _cmd_quarantine_health_fixtures(args) -> int:
    dry_run = "--dry-run" in args
    conn = database.init_db()
    report = stage3_cleanup.quarantine_health_fixtures(conn, dry_run=dry_run)
    _rule("QUARANTINE HEALTH FIXTURES")
    print(f"Mode              : {'dry-run' if dry_run else 'apply'}")
    print(f"Fixtures matched  : {len(report.items)}")
    print(f"Fixtures changed  : {report.changed_count}")
    if not report.items:
        print("(none)")
        return 0
    for item in report.items:
        state = "already quarantined" if item.already_quarantined else (
            "would quarantine" if dry_run else "quarantined")
        print(f"- job #{item.job_id} loop=#{item.loop_id or '-'} "
              f"status={item.status}  {state}")
        print(f"  reason: {item.reason}")
    return 0


def _print_portable_path_report(report, title):
    _rule(title)
    print(f"Project root        : {report.project_root}")
    print(f"Mode                : {'dry-run' if report.dry_run else 'apply'}")
    print(f"Stale absolute paths: {report.stale_count}")
    print(f"Repairable          : {report.repairable_count}")
    print(f"Repaired            : {report.repaired_count}")
    print(f"Warnings            : {report.warning_count}")
    print(f"Quarantined skipped : {report.quarantined_count}")
    if not report.items:
        print("(none)")
        return
    for item in report.items:
        if item.quarantined:
            status = "quarantined fixture"
        elif item.repaired:
            status = "repaired"
        elif item.repairable:
            status = "repairable"
        else:
            status = "warning"
        print(f"- {item.table}#{item.row_id}.{item.column} [{status}]")
        print(f"  old: {item.old_path}")
        if item.new_path:
            print(f"  new: {item.new_path}")
        if item.warning:
            print(f"  warning: {item.warning}")


def _cmd_check_portable_paths(args) -> int:
    conn = database.init_db()
    report = stage3_cleanup.check_portable_paths(conn, project_root=os.path.dirname(os.path.abspath(__file__)))
    _print_portable_path_report(report, "CHECK PORTABLE PATHS")
    return 0 if report.warning_count == 0 else 2


def _cmd_repair_portable_paths(args) -> int:
    dry_run = "--dry-run" in args
    conn = database.init_db()
    report = stage3_cleanup.repair_portable_paths(
        conn, project_root=os.path.dirname(os.path.abspath(__file__)), dry_run=dry_run)
    _print_portable_path_report(report, "REPAIR PORTABLE PATHS")
    return 0 if report.warning_count == 0 else 2


def _observatory_filters(args):
    return {
        "window": _flag_val(args, "--window") or "all",
        "workspace": _flag_val(args, "--workspace"),
        "loop_type": _flag_val(args, "--loop-type"),
        "agent": _flag_val(args, "--agent"),
    }


def _print_observatory_summary(summary, snapshot_id=None):
    _rule("LOOP ENGINEERING OBSERVATORY")
    if snapshot_id is not None:
        print(f"Snapshot ID      : {snapshot_id}")
    print(f"Generated        : {summary.generated_at}")
    print(f"Window           : {summary.time_window.name}")
    if summary.time_window.start_at:
        print(f"Window start     : {summary.time_window.start_at}")
    _rule("SUMMARY")
    print(f"Total loops              : {summary.total_loops}")
    print(f"Approved                 : {summary.approved_loops}")
    print(f"Failed                   : {summary.failed_loops}")
    print(f"Blocked                  : {summary.blocked_loops}")
    print(f"Needs human              : {summary.needs_human_loops}")
    print(f"Paused external          : {summary.paused_external_loops}")
    print(f"Total external jobs      : {summary.total_external_jobs}")
    print(f"Waiting external jobs    : {summary.waiting_external_jobs}")
    print(f"Completed external jobs  : {summary.completed_external_jobs}")
    print(f"Blocked external jobs    : {summary.blocked_external_jobs}")
    print(f"Failed external jobs     : {summary.failed_external_jobs}")
    print(f"Reports                  : {summary.total_reports}")
    print(f"Approvals                : {summary.total_approvals}")
    print(f"Declined approvals       : {summary.declined_approvals}")
    print(f"Quality gate failures    : {summary.quality_gate_failures}")
    print(f"Stop condition triggers  : {summary.stop_condition_triggers}")

    _rule("TOP LOOP TYPES")
    if not summary.top_loop_types:
        print("(none)")
    for row in summary.top_loop_types:
        print(f"- {row['loop_type']}: count={row['count']} "
              f"approval_rate={row['approval_rate']}% "
              f"failure_rate={row['failure_rate']}%")

    _rule("TOP AGENTS")
    if not summary.top_agents:
        print("(none)")
    for row in summary.top_agents:
        print(f"- {row['agent']}: count={row['count']} "
              f"success_rate={row['success_rate']}%")

    _rule("TOP WORKSPACES")
    if not summary.top_workspaces:
        print("(none)")
    for row in summary.top_workspaces:
        print(f"- {row['workspace']}: loops={row['loop_count']} "
              f"blocked={row['blocked_count']}")

    _rule("TOP FAILURE REASONS")
    if not summary.top_failure_reasons:
        print("(none)")
    for row in summary.top_failure_reasons:
        print(f"- {row['stop_reason']}: {row['count']}")

    _rule("EXTERNAL JOB HEALTH")
    ejh = summary.external_job_health or {}
    print(f"waiting        : {ejh.get('waiting', 0)}")
    print(f"stale          : {ejh.get('stale', 0)}")
    print(f"needs attention: {ejh.get('needs_attention', 0)}")
    print(f"archived       : {ejh.get('archived', 0)}")
    print(f"cancelled      : {ejh.get('cancelled', 0)}")

    _rule("ALERTS")
    if not summary.alerts:
        print("(none)")
    for alert in summary.alerts:
        print(f"[{alert.severity}] {alert.alert_type}")
        print(f"  message : {alert.message}")
        print(f"  action  : {alert.recommended_action}")

    _rule("NEXT ACTIONS")
    actions = []
    for alert in summary.alerts:
        if alert.recommended_action not in actions:
            actions.append(alert.recommended_action)
    for base in (
        "python3 main.py --external-dashboard",
        "python3 main.py --external-health",
        "python3 main.py --external-jobs --needs-attention",
        "python3 main.py --history --limit 10",
        "python3 main.py --reports",
    ):
        if base not in actions:
            actions.append(base)
    for action in actions:
        print(f"- {action}")


def _summary_from_json(blob):
    data = json.loads(blob or "{}")
    tw = data.get("time_window") or {}
    data["time_window"] = observatory.ObservatoryTimeWindow(**tw)
    data["alerts"] = [observatory.ObservatoryAlert(**a)
                      for a in data.get("alerts", [])]
    return observatory.ObservatorySummary(**data)


def _observatory_snapshot_row(conn, value):
    if value == "latest":
        rows = database.list_observatory_snapshots(conn, 1)
        return rows[0] if rows else None
    try:
        sid = int(value)
    except ValueError:
        raise ValueError("SNAPSHOT_ID must be an integer or 'latest'")
    return database.get_observatory_snapshot(conn, sid)


def _observatory_report_path_display(path) -> str:
    if not path:
        return "(none)"
    if not observatory_reports.is_report_path(path):
        return f"invalid observatory report path metadata: {path}"
    if not os.path.exists(path):
        return f"missing observatory report path: {path}"
    return path


def _cmd_observatory(args) -> int:
    filters = _observatory_filters(args)
    save_report = "--save-report" in args
    conn = database.init_db()
    try:
        summary = observatory.ObservatoryEngine(conn).build_summary(**filters)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    summary_json = json.dumps(observatory.summary_to_dict(summary), sort_keys=True)
    filters_json = json.dumps(filters, sort_keys=True)
    snapshot_id = database.save_observatory_snapshot(
        conn, summary.generated_at, summary.time_window.name, filters_json,
        summary_json, len(summary.alerts),
        sum(1 for a in summary.alerts if a.severity == "critical"),
        sum(1 for a in summary.alerts if a.severity == "warning"),
    )
    _print_observatory_summary(summary, snapshot_id=snapshot_id)
    if save_report:
        try:
            report = observatory_reports.ObservatoryReportGenerator(conn).generate_report(
                snapshot_id)
        except Exception as exc:
            print(f"ERROR: observatory report generation failed: {exc}",
                  file=sys.stderr)
            return 1
        print(f"\nobservatory report path: {report.report_path}")
    return 0


def _cmd_observatory_snapshots(args) -> int:
    conn = database.init_db()
    rows = database.list_observatory_snapshots(conn, 20)
    _rule(f"OBSERVATORY SNAPSHOTS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for r in rows:
        print(f"#{r['id']}  {r['generated_at']}  window={r['time_window']}  "
              f"alerts={r['alert_count']} critical={r['critical_alert_count']} "
              f"warning={r['warning_alert_count']}")
        print(f"    filters: {r['filters_json']}")
    return 0


def _cmd_observatory_snapshot(args) -> int:
    if not args:
        print("ERROR: --observatory-snapshot needs a SNAPSHOT_ID", file=sys.stderr)
        return 1
    conn = database.init_db()
    if args[0] == "latest":
        rows = database.list_observatory_snapshots(conn, 1)
        row = rows[0] if rows else None
    else:
        try:
            sid = int(args[0])
        except ValueError:
            print("ERROR: SNAPSHOT_ID must be an integer or 'latest'", file=sys.stderr)
            return 1
        row = database.get_observatory_snapshot(conn, sid)
    if row is None:
        print(f"ERROR: no observatory snapshot {args[0]}", file=sys.stderr)
        return 1
    summary = _summary_from_json(row["summary_json"])
    _print_observatory_summary(summary, snapshot_id=row["id"])
    report = database.get_observatory_report(conn, row["id"])
    if report is not None:
        print(f"\nobservatory report: "
              f"{_observatory_report_path_display(report['report_path'])}")
    return 0


def _cmd_observatory_report(args) -> int:
    if not args:
        print("ERROR: --observatory-report needs a SNAPSHOT_ID", file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        snapshot = _observatory_snapshot_row(conn, args[0])
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if snapshot is None:
        print(f"ERROR: no observatory snapshot {args[0]}", file=sys.stderr)
        return 1
    gen = observatory_reports.ObservatoryReportGenerator(conn)
    row = database.get_observatory_report(conn, snapshot["id"])
    path = row["report_path"] if row else None
    if row is not None and observatory_reports.is_report_path(path) and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
    else:
        report = gen.generate_report(snapshot["id"])
        path = report.report_path
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
    print(f"observatory report path: {path}\n")
    print(content)
    return 0


def _cmd_observatory_reports(args) -> int:
    limit = 20
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                print("ERROR: --limit needs an integer", file=sys.stderr)
                return 1
    conn = database.init_db()
    rows = observatory_reports.ObservatoryReportGenerator(conn).list_reports(limit)
    _rule(f"OBSERVATORY REPORTS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for r in rows:
        print(f"snapshot={r['snapshot_id']}  created_at={r['created_at']}  "
              f"bytes={r['bytes_written']}")
        print(f"    path: {_observatory_report_path_display(r['report_path'])}")
    return 0


def _trend_filters(args):
    limit = 10
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                raise ValueError("--limit needs an integer")
    return {
        "limit": limit,
        "window": _flag_val(args, "--window"),
        "workspace": _flag_val(args, "--workspace"),
        "metric": _flag_val(args, "--metric"),
    }


def _print_trend_report(report, report_id=None, markdown_path=None):
    _rule("LOOP ENGINEERING OBSERVATORY TRENDS")
    if report_id is not None:
        print(f"Trend report ID   : {report_id}")
    if markdown_path:
        print(f"Markdown report   : {markdown_path}")
    _rule("SUMMARY")
    print(f"Snapshots analyzed: {report.snapshot_count}")
    print(f"Start snapshot    : {report.start_snapshot_id or '(none)'}")
    print(f"End snapshot      : {report.end_snapshot_id or '(none)'}")
    print(f"Generated at      : {report.generated_at}")

    _rule("KEY TRENDS")
    if not report.trends:
        print("(none)")
    for trend in report.trends:
        pct = "n/a" if trend.percent_change is None else f"{trend.percent_change}%"
        print(f"- {trend.metric_name}: first={trend.first_value} "
              f"last={trend.last_value} delta={trend.delta} "
              f"percent_change={pct} direction={trend.direction}")
        print(f"  interpretation: {trend.interpretation}")

    _rule("ALERTS")
    if not report.alerts:
        print("(none)")
    for alert in report.alerts:
        print(f"- {alert}")

    _rule("RECOMMENDATIONS")
    for rec in report.recommendations:
        print(f"- {rec}")


def _trend_report_from_row(row):
    return observatory_trends.report_from_row(row)


def _trend_markdown_path_display(path):
    if not path:
        return "(none)"
    if not observatory_trends.is_markdown_report_path(path):
        return f"invalid trend report path metadata: {path}"
    if not os.path.exists(path):
        return f"missing trend report path: {path}"
    return path


def _cmd_observatory_trends(args) -> int:
    try:
        filters = _trend_filters(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    save_report = "--save-report" in args
    conn = database.init_db()
    engine = observatory_trends.ObservatoryTrendEngine(conn)
    try:
        report = engine.build_report(**filters)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    report_id = engine.save_trend_report(report, filters)
    markdown_path = None
    if save_report:
        try:
            md = engine.save_markdown_report(report_id, report)
            markdown_path = md.report_path
        except Exception as exc:
            print(f"ERROR: observatory trend markdown generation failed: {exc}",
                  file=sys.stderr)
            return 1
    _print_trend_report(report, report_id=report_id, markdown_path=markdown_path)
    return 0


def _cmd_observatory_trend_reports(args) -> int:
    limit = 20
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                print("ERROR: --limit needs an integer", file=sys.stderr)
                return 1
    conn = database.init_db()
    rows = database.list_observatory_trend_reports(conn, limit)
    _rule(f"OBSERVATORY TREND REPORTS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for r in rows:
        md = database.get_observatory_trend_markdown_report(conn, r["id"])
        print(f"#{r['id']}  {r['generated_at']}  snapshots={r['snapshot_count']} "
              f"start={r['start_snapshot_id']} end={r['end_snapshot_id']}")
        print(f"    filters: {r['filters_json']}")
        if md is not None:
            print(f"    markdown: {_trend_markdown_path_display(md['report_path'])}")
    return 0


def _cmd_observatory_trend_report(args) -> int:
    if not args:
        print("ERROR: --observatory-trend-report needs a REPORT_ID", file=sys.stderr)
        return 1
    conn = database.init_db()
    if args[0] == "latest":
        rows = database.list_observatory_trend_reports(conn, 1)
        row = rows[0] if rows else None
    else:
        try:
            rid = int(args[0])
        except ValueError:
            print("ERROR: REPORT_ID must be an integer or 'latest'", file=sys.stderr)
            return 1
        row = database.get_observatory_trend_report(conn, rid)
    if row is None:
        print(f"ERROR: no observatory trend report {args[0]}", file=sys.stderr)
        return 1
    md = database.get_observatory_trend_markdown_report(conn, row["id"])
    report = _trend_report_from_row(row)
    _print_trend_report(
        report,
        report_id=row["id"],
        markdown_path=_trend_markdown_path_display(md["report_path"]) if md else None,
    )
    return 0


def _failure_filters(args):
    limit = 25
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                raise ValueError("--limit needs an integer")
    return {
        "limit": limit,
        "workspace": _flag_val(args, "--workspace"),
        "loop_type": _flag_val(args, "--loop-type"),
        "category": _flag_val(args, "--category"),
        "status": _flag_val(args, "--status"),
        "include_approved": "--include-approved" in args,
        "cluster_by": _flag_val(args, "--cluster-by") or "category",
    }


def _print_failure_drilldown(report, drilldown_id=None, markdown_path=None):
    filters = json.loads(report.filters_json or "{}")
    cluster_by = filters.get("cluster_by") or "category"
    _rule("LOOP FAILURE DRILLDOWN")
    if drilldown_id is not None:
        print(f"Drilldown ID   : {drilldown_id}")
    if markdown_path:
        print(f"Markdown report: {markdown_path}")
    _rule("SUMMARY")
    print(f"Total failures : {report.total_failures}")
    print(f"Filters        : {report.filters_json}")
    print(f"Cluster by     : {cluster_by}")
    print(f"Generated at   : {report.generated_at}")

    _rule("CLUSTERS")
    if not report.clusters:
        print("(none)")
    for c in report.clusters:
        print(f"- type={c.cluster_type} key={c.cluster_key} count={c.count}")
        print(f"  loop ids: {c.loop_ids}")
        print(f"  reason  : {c.representative_reason}")
        print(f"  action  : {c.recommended_action}")

    _rule("FAILURES")
    if not report.items:
        print("(none)")
    for item in report.items:
        print(f"- loop #{item.loop_id}  {item.created_at}  status={item.status}")
        print(f"  type/workspace: {item.loop_type} / {item.workspace_name}")
        print(f"  stop reason   : {item.stop_reason}")
        print(f"  category      : {item.failure_category}")
        print(f"  root cause    : {item.root_cause_hint}")
        print(f"  failed gates  : {', '.join(item.failed_quality_gates) or '(none)'}")
        print(f"  stop conditions: "
              f"{', '.join(item.triggered_stop_conditions) or '(none)'}")
        print(f"  external job  : {item.external_job_status or '(none)'}")
        print(f"  report path   : {_report_path_display(item.report_path)}")
        print(f"  action        : {item.recommended_action}")

    _rule("NEXT ACTIONS")
    for rec in report.recommendations:
        print(f"- {rec}")


def _failure_markdown_path_display(path):
    if not path:
        return "(none)"
    if not observatory_drilldown.is_markdown_report_path(path):
        return f"invalid failure report path metadata: {path}"
    if not os.path.exists(path):
        return f"missing failure report path: {path}"
    return path


def _cmd_observatory_failures(args) -> int:
    try:
        filters = _failure_filters(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    save_report = "--save-report" in args
    conn = database.init_db()
    engine = observatory_drilldown.ObservatoryDrilldownEngine(conn)
    try:
        report = engine.build_report(**filters)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    drilldown_id = engine.save_drilldown(report, cluster_by=filters["cluster_by"])
    markdown_path = None
    if save_report:
        try:
            md = engine.save_markdown_report(drilldown_id, report)
            markdown_path = md.report_path
        except Exception as exc:
            print(f"ERROR: observatory failure markdown generation failed: {exc}",
                  file=sys.stderr)
            return 1
    _print_failure_drilldown(
        report, drilldown_id=drilldown_id, markdown_path=markdown_path)
    return 0


def _cmd_observatory_failure_drilldowns(args) -> int:
    limit = 20
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                print("ERROR: --limit needs an integer", file=sys.stderr)
                return 1
    conn = database.init_db()
    rows = database.list_observatory_failure_drilldowns(conn, limit)
    _rule(f"OBSERVATORY FAILURE DRILLDOWNS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for r in rows:
        md = database.get_observatory_failure_markdown_report(conn, r["id"])
        print(f"#{r['id']}  {r['generated_at']}  failures={r['total_failures']} "
              f"cluster_by={r['cluster_by']}")
        print(f"    filters: {r['filters_json']}")
        if md is not None:
            print(f"    markdown: {_failure_markdown_path_display(md['report_path'])}")
    return 0


def _cmd_observatory_failure_drilldown(args) -> int:
    if not args:
        print("ERROR: --observatory-failure-drilldown needs a DRILLDOWN_ID",
              file=sys.stderr)
        return 1
    conn = database.init_db()
    if args[0] == "latest":
        rows = database.list_observatory_failure_drilldowns(conn, 1)
        row = rows[0] if rows else None
    else:
        try:
            drilldown_id = int(args[0])
        except ValueError:
            print("ERROR: DRILLDOWN_ID must be an integer or 'latest'", file=sys.stderr)
            return 1
        row = database.get_observatory_failure_drilldown(conn, drilldown_id)
    if row is None:
        print(f"ERROR: no observatory failure drilldown {args[0]}", file=sys.stderr)
        return 1
    report = observatory_drilldown.report_from_row(row)
    md = database.get_observatory_failure_markdown_report(conn, row["id"])
    _print_failure_drilldown(
        report,
        drilldown_id=row["id"],
        markdown_path=_failure_markdown_path_display(md["report_path"]) if md else None,
    )
    return 0


def _remediation_args(args):
    source_type = None
    source_id = None
    if "--snapshot" in args:
        source_type = "snapshot"
        val = _flag_val(args, "--snapshot")
        if not val:
            raise ValueError("--snapshot needs a SNAPSHOT_ID")
        source_id = int(val)
    if "--from-trends" in args:
        source_type = "trend"
        source_id = None
    if "--trend-report" in args:
        source_type = "trend"
        val = _flag_val(args, "--trend-report")
        if not val:
            raise ValueError("--trend-report needs a REPORT_ID")
        source_id = int(val)
    if "--from-failures" in args:
        source_type = "failure_drilldown"
        source_id = None
    if "--failure-drilldown" in args:
        source_type = "failure_drilldown"
        val = _flag_val(args, "--failure-drilldown")
        if not val:
            raise ValueError("--failure-drilldown needs a DRILLDOWN_ID")
        source_id = int(val)
    limit = 25
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            limit = int(args[i + 1])
    return {
        "source_type": source_type,
        "source_id": source_id,
        "priority": _flag_val(args, "--priority"),
        "category": _flag_val(args, "--category"),
        "limit": limit,
    }


def _print_remediation_plan(plan, plan_id=None, markdown_path=None):
    _rule("LOOP ENGINEERING REMEDIATION PLAN")
    if plan_id is not None:
        print(f"Plan ID      : {plan_id}")
    if markdown_path:
        print(f"Markdown     : {markdown_path}")
    _rule("SUMMARY")
    print(f"Source type  : {plan.source_type}")
    print(f"Source ID    : {plan.source_id}")
    print(f"Generated at : {plan.generated_at}")
    print(f"Total items  : {plan.total_items}")
    print(f"Urgent       : {plan.urgent_count}")
    print(f"High         : {plan.high_priority_count}")
    print(f"Medium       : {plan.medium_priority_count}")
    print(f"Low          : {plan.low_priority_count}")
    print(f"Summary      : {plan.summary}")

    _rule("PLAN ITEMS")
    if not plan.items:
        print("(none)")
    for item in plan.items:
        print(f"- ID {item.id}: [{item.priority}] {item.category} - {item.title}")
        print(f"  problem : {item.problem_summary}")
        print(f"  evidence: {item.evidence}")
        print(f"  loops   : {item.affected_loop_ids or []}")
        print(f"  jobs    : {item.affected_job_ids or []}")
        print(f"  action  : {item.recommended_action}")
        print(f"  command : {item.suggested_command}")
        print(f"  impact  : {item.expected_impact}")
        print(f"  risk    : {item.risk_level}")
        print(f"  effort  : {item.effort_level}")
        print(f"  status  : {item.status}")

    _rule("NEXT STEPS")
    for step in plan.next_steps:
        print(f"- {step}")


def _remediation_markdown_path_display(path):
    if not path:
        return "(none)"
    if not observatory_remediation.is_markdown_report_path(path):
        return f"invalid remediation report path metadata: {path}"
    if not os.path.exists(path):
        return f"missing remediation report path: {path}"
    return path


def _cmd_observatory_remediation(args) -> int:
    try:
        opts = _remediation_args(args)
    except (ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    save_report = "--save-report" in args
    conn = database.init_db()
    engine = observatory_remediation.ObservatoryRemediationEngine(conn)
    try:
        plan = engine.build_plan(**opts)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    plan_id = engine.save_plan(plan, opts)
    markdown_path = None
    if save_report:
        try:
            md = engine.save_markdown_report(plan_id, plan)
            markdown_path = md.report_path
        except Exception as exc:
            print(f"ERROR: observatory remediation markdown generation failed: {exc}",
                  file=sys.stderr)
            return 1
    _print_remediation_plan(plan, plan_id=plan_id, markdown_path=markdown_path)
    return 0


def _cmd_observatory_remediation_plans(args) -> int:
    limit = 20
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                print("ERROR: --limit needs an integer", file=sys.stderr)
                return 1
    conn = database.init_db()
    rows = database.list_observatory_remediation_plans(conn, limit)
    _rule(f"OBSERVATORY REMEDIATION PLANS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for r in rows:
        md = database.get_observatory_remediation_markdown_report(conn, r["id"])
        print(f"#{r['id']}  {r['generated_at']}  source={r['source_type']}:{r['source_id']} "
              f"items={r['total_items']} urgent={r['urgent_count']} "
              f"high={r['high_priority_count']}")
        print(f"    filters: {r['filters_json']}")
        if md is not None:
            print(f"    markdown: {_remediation_markdown_path_display(md['report_path'])}")
    return 0


def _cmd_observatory_remediation_plan(args) -> int:
    if not args:
        print("ERROR: --observatory-remediation-plan needs a PLAN_ID", file=sys.stderr)
        return 1
    conn = database.init_db()
    if args[0] == "latest":
        rows = database.list_observatory_remediation_plans(conn, 1)
        row = rows[0] if rows else None
    else:
        try:
            plan_id = int(args[0])
        except ValueError:
            print("ERROR: PLAN_ID must be an integer or 'latest'", file=sys.stderr)
            return 1
        row = database.get_observatory_remediation_plan(conn, plan_id)
    if row is None:
        print(f"ERROR: no observatory remediation plan {args[0]}", file=sys.stderr)
        return 1
    plan = observatory_remediation.plan_from_row(row)
    md = database.get_observatory_remediation_markdown_report(conn, row["id"])
    _print_remediation_plan(
        plan,
        plan_id=row["id"],
        markdown_path=_remediation_markdown_path_display(md["report_path"]) if md else None,
    )
    return 0


def _latest_remediation_plan_id(conn):
    rows = database.list_observatory_remediation_plans(conn, 1)
    return rows[0]["id"] if rows else None


def _latest_action_id(conn):
    rows = database.list_observatory_action_items(conn, status=None, limit=1)
    return rows[0]["id"] if rows else None


def _parse_id_or_latest(conn, value, latest_func, label):
    if value == "latest":
        found = latest_func(conn)
        if found is None:
            raise ValueError(f"no {label} rows exist")
        return found
    return int(value)


def _age(created_at):
    if not created_at:
        return "n/a"
    try:
        created = datetime.datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        now = datetime.datetime.now(created.tzinfo) if created.tzinfo else datetime.datetime.now()
        seconds = max(0, int((now - created).total_seconds()))
    except Exception:
        return "n/a"
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    return f"{hours // 24}d"


def _cmd_create_observatory_actions(args) -> int:
    if not args:
        print("ERROR: --create-observatory-actions needs a PLAN_ID", file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        plan_id = _parse_id_or_latest(conn, args[0], _latest_remediation_plan_id,
                                      "observatory remediation plan")
    except (ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    try:
        result = observatory_actions.ObservatoryActionEngine(conn).create_actions_from_plan(plan_id)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _rule("OBSERVATORY ACTIONS CREATED")
    print(f"source plan : {plan_id}")
    print(f"created     : {result['created']}")
    print(f"skipped     : {result['skipped']}")
    print("(suggested commands were not executed)")
    return 0


def _cmd_observatory_actions(args) -> int:
    status = _flag_val(args, "--status")
    if status is None:
        status = "open"
    priority = _flag_val(args, "--priority")
    category = _flag_val(args, "--category")
    limit = 25
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                print("ERROR: --limit needs an integer", file=sys.stderr)
                return 1
    conn = database.init_db()
    try:
        queue = observatory_actions.ObservatoryActionEngine(conn).list_actions(
            status=status, priority=priority, category=category, limit=limit)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _rule("OBSERVATORY ACTION QUEUE")
    print(f"Generated at     : {queue.generated_at}")
    print(f"Total shown      : {queue.total_actions}")
    print(f"Open shown       : {queue.open_actions}")
    print(f"Completed shown  : {queue.completed_actions}")
    print(f"Dismissed shown  : {queue.dismissed_actions}")
    _rule("ACTIONS")
    if not queue.actions:
        print("(none)")
    for action in queue.actions:
        print(f"#{action.id} [{action.priority}] {action.category} status={action.status} "
              f"age={_age(action.created_at)}")
        print(f"  title  : {action.title}")
        print(f"  loops  : {action.affected_loop_ids or []}")
        print(f"  jobs   : {action.affected_job_ids or []}")
        print(f"  command: {action.suggested_command}")
    return 0


def _cmd_observatory_action(args) -> int:
    if not args:
        print("ERROR: --observatory-action needs an ACTION_ID", file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        action_id = _parse_id_or_latest(conn, args[0], _latest_action_id,
                                        "observatory action")
        action = observatory_actions.ObservatoryActionEngine(conn).get_action(action_id)
    except (ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _rule(f"OBSERVATORY ACTION #{action.id}")
    print(f"source plan       : {action.source_plan_id}")
    print(f"source item       : {action.source_item_id}")
    print(f"title             : {action.title}")
    print(f"category          : {action.category}")
    print(f"priority          : {action.priority}")
    print(f"status            : {action.status}")
    print(f"problem summary   : {action.problem_summary}")
    print(f"recommended action: {action.recommended_action}")
    print(f"suggested command : {action.suggested_command}")
    print(f"affected loops    : {action.affected_loop_ids or []}")
    print(f"affected jobs     : {action.affected_job_ids or []}")
    print(f"risk / effort     : {action.risk_level} / {action.effort_level}")
    print(f"notes             : {action.notes or '(none)'}")
    print(f"created_at        : {action.created_at}")
    print(f"updated_at        : {action.updated_at or '(none)'}")
    print(f"completed_at      : {action.completed_at or '(none)'}")
    print(f"dismissed_at      : {action.dismissed_at or '(none)'}")
    _rule("UPDATE COMMANDS")
    for status in ("in_progress", "completed", "dismissed", "blocked"):
        print(f"- python3 main.py --set-observatory-action-status {action.id} {status}")
    print(f"- python3 main.py --set-observatory-action-notes {action.id} \"notes\"")
    handoffs = database.list_observatory_action_handoffs_for_action(conn, action.id, 10)
    _rule("HANDOFFS")
    if not handoffs:
        print("(none)")
    for h in handoffs:
        print(f"- #{h['id']} type={h['handoff_type']} status={h['status']} "
              f"dry_run={bool(h['dry_run'])}")
        print(f"  command: python3 main.py --observatory-action-handoff {h['id']}")
    _rule("HANDOFF COMMANDS")
    print(f"- python3 main.py --handoff-observatory-action {action.id}")
    print(f"- python3 main.py --handoff-observatory-action {action.id} --type loop_task")
    print(f"- python3 main.py --handoff-observatory-action {action.id} "
          f"--type external_agent_job --external-coder codex")
    return 0


def _cmd_set_observatory_action_status(args) -> int:
    if len(args) < 2:
        print("ERROR: usage: --set-observatory-action-status ACTION_ID STATUS",
              file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        action_id = _parse_id_or_latest(conn, args[0], _latest_action_id,
                                        "observatory action")
        action = observatory_actions.ObservatoryActionEngine(conn).update_status(
            action_id, args[1])
    except (ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _rule("OBSERVATORY ACTION STATUS UPDATED")
    print(f"action id: {action.id}")
    print(f"status   : {action.status}")
    print("(suggested command was not executed)")
    return 0


def _cmd_set_observatory_action_notes(args) -> int:
    if len(args) < 2:
        print("ERROR: usage: --set-observatory-action-notes ACTION_ID \"notes\"",
              file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        action_id = _parse_id_or_latest(conn, args[0], _latest_action_id,
                                        "observatory action")
        action = observatory_actions.ObservatoryActionEngine(conn).update_notes(
            action_id, " ".join(args[1:]))
    except (ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _rule("OBSERVATORY ACTION NOTES UPDATED")
    print(f"action id: {action.id}")
    print(f"notes    : {action.notes}")
    print("(notes were stored as plain text and not executed)")
    return 0


def _cmd_observatory_actions_report(args) -> int:
    conn = database.init_db()
    try:
        report = observatory_actions.ObservatoryActionEngine(conn).save_markdown_report()
    except Exception as exc:
        print(f"ERROR: observatory actions report failed: {exc}", file=sys.stderr)
        return 1
    _rule("OBSERVATORY ACTIONS REPORT")
    print(f"report path  : {report.report_path}")
    print(f"bytes written: {report.bytes_written}")
    return 0


def _latest_handoff_id(conn):
    rows = database.list_observatory_action_handoffs(conn, 1)
    return rows[0]["id"] if rows else None


def _cmd_handoff_observatory_action(args) -> int:
    if not args:
        print("ERROR: --handoff-observatory-action needs an ACTION_ID", file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        action_id = _parse_id_or_latest(conn, args[0], _latest_action_id,
                                        "observatory action")
    except (ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    handoff_type = _flag_val(args, "--type") or "dry_run_plan"
    target_loop_type = _flag_val(args, "--loop-type") or "code_build"
    target_workspace = _flag_val(args, "--workspace") or "default"
    external_coder = _flag_val(args, "--external-coder") or "codex"
    confirm_loop = "--confirm-create-loop" in args
    confirm_external = "--confirm-create-external-job" in args
    if confirm_loop and confirm_external:
        print("ERROR: choose only one confirmation flag", file=sys.stderr)
        return 1
    if confirm_loop and handoff_type == "dry_run_plan":
        handoff_type = "loop_task"
    if confirm_external and handoff_type == "dry_run_plan":
        handoff_type = "external_agent_job"
    if confirm_loop and handoff_type != "loop_task":
        print("ERROR: --confirm-create-loop requires --type loop_task", file=sys.stderr)
        return 1
    if confirm_external and handoff_type != "external_agent_job":
        print("ERROR: --confirm-create-external-job requires --type external_agent_job",
              file=sys.stderr)
        return 1
    try:
        engine = observatory_action_handoff.ObservatoryActionHandoffEngine(conn)
        if confirm_loop:
            return _create_observatory_handoff_loop(
                conn, engine, action_id, handoff_type, target_loop_type,
                target_workspace, external_coder, args)
        if confirm_external:
            handoff = _create_observatory_external_job_handoff(
                conn, engine, action_id, handoff_type, target_loop_type,
                target_workspace, external_coder)
        else:
            handoff = engine.create_handoff(
                action_id,
                handoff_type=handoff_type,
                target_loop_type=target_loop_type,
                target_workspace=target_workspace,
                external_coder=external_coder,
            )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _print_action_handoff(handoff, conn)
    return 0


def _latest_loop_id(conn):
    row = conn.execute("SELECT id FROM loops ORDER BY id DESC LIMIT 1").fetchone()
    return row["id"] if row else None


def _create_observatory_handoff_loop(conn, engine, action_id, handoff_type,
                                     target_loop_type, target_workspace,
                                     external_coder, args) -> int:
    action = observatory_actions.ObservatoryActionEngine(
        conn).get_action(action_id, record_view=False)
    task = engine.generate_task(action)
    loop = REGISTRY.get_loop(target_loop_type)
    if loop is None:
        print(f"ERROR: no loop named '{target_loop_type}'. Try: python main.py --loops",
              file=sys.stderr)
        return 1
    ws_manager = project_workspace.WorkspaceManager(conn)
    ws = ws_manager.get_workspace(target_workspace)
    if ws is None:
        print(f"ERROR: no workspace '{target_workspace}'. Try: python main.py --workspaces",
              file=sys.stderr)
        return 1
    roles, role_errors = loop_engine_mod.resolve_roles(loop, AGENTS, {})
    if role_errors:
        print(f"ERROR: could not resolve agents: {role_errors}", file=sys.stderr)
        return 1
    commit = "--commit" in args
    commit_message = _flag_val(args, "--commit-message")
    min_conf = None
    if _flag_val(args, "--min-reviewer-confidence"):
        try:
            min_conf = float(_flag_val(args, "--min-reviewer-confidence"))
        except ValueError:
            print("ERROR: --min-reviewer-confidence needs a number", file=sys.stderr)
            return 1
    require_approval = "--require-approval" in args
    auto_approve_low_risk = "--auto-approve-low-risk" in args
    approval_mode = _flag_val(args, "--approval-mode")
    if approval_mode is None:
        approval_mode = "interactive" if require_approval else "none"
    approval_policy = approval_gates.ApprovalPolicy(
        name="cli", enabled=require_approval,
        auto_approve_low_risk=auto_approve_low_risk)
    approval_engine = approval_gates.ApprovalGateEngine(
        approval_policy, mode=approval_mode)
    before_loop_id = _latest_loop_id(conn)
    rc = _execute_run(
        conn, task, loop, ws, roles, {}, approval_engine, min_conf, commit,
        commit_message, memory_mode="off", context_mode="off",
        intake_bundle=None, external_coder=None)
    after_loop_id = _latest_loop_id(conn)
    created_loop_id = after_loop_id if after_loop_id != before_loop_id else None
    if created_loop_id is not None:
        handoff = engine.create_handoff(
            action_id,
            handoff_type=handoff_type,
            target_loop_type=target_loop_type,
            target_workspace=target_workspace,
            external_coder=external_coder,
            confirm_create_loop=True,
            created_loop_id=created_loop_id,
        )
        _print_action_handoff(handoff, conn)
    return rc


def _create_observatory_external_job_handoff(conn, engine, action_id, handoff_type,
                                             target_loop_type, target_workspace,
                                             external_coder):
    import external_agent_jobs as eaj

    action = observatory_actions.ObservatoryActionEngine(
        conn).get_action(action_id, record_view=False)
    loop = REGISTRY.get_loop(target_loop_type)
    if loop is None:
        raise ValueError(f"no loop named '{target_loop_type}'")
    adapter = EXTERNAL.get(external_coder)
    if adapter is None:
        raise ValueError(f"unknown external coder '{external_coder}'")
    ws_manager = project_workspace.WorkspaceManager(conn)
    ws = ws_manager.get_workspace(target_workspace)
    if ws is None:
        raise ValueError(f"no workspace '{target_workspace}'")
    workspace_errors = ws_manager.validate_workspace(ws)
    if workspace_errors:
        raise ValueError("workspace validation failed: " + "; ".join(workspace_errors))

    allowed_tools = []
    if loop.filesystem_enabled:
        allowed_tools.append("filesystem")
    if loop.terminal_enabled:
        allowed_tools.append("terminal")
    if getattr(loop, "git_enabled", False):
        allowed_tools.append("git")
    affected = action.affected_loop_ids or []
    loop_id = affected[-1] if affected else None
    task = engine.generate_task(action)
    plan = ("Create a manual external-agent handoff for Observatory action "
            f"#{action.id}. Do not execute suggested commands automatically; "
            "implement only within allowed workspace paths and return completion JSON.")
    mgr = eaj.ExternalAgentJobManager(conn)
    job = mgr.create_job(
        loop_id, 1, adapter.name, ws.name, ws.root_path,
        priority=eaj.DEFAULT_PRIORITY,
        labels=["observatory", "action-handoff"],
        notes=f"Observatory action #{action.id} handoff")
    req = external_agents.ExternalAgentRequest(
        loop_id=loop_id, attempt_number=1, agent_name=adapter.name,
        task=task, plan=plan, workspace_name=ws.name, workspace_root=ws.root_path,
        allowed_write_paths=list(ws.allowed_write_paths),
        allowed_command_paths=list(ws.allowed_command_paths),
        dry_run=True, created_at="")
    prompt, safe, warnings = adapter.build_handoff(req)
    if not safe:
        raise ValueError("external handoff prompt failed safety checks: "
                         + "; ".join(warnings))
    packet = mgr.create_packet(
        job, task, plan, list(ws.allowed_write_paths),
        list(ws.allowed_command_paths), allowed_tools,
        context_summary="Observatory action metadata only.",
        memory_summary="",
        project_intelligence_summary="",
        context_pack_summary="",
        reviewer_feedback="",
        test_analyst_feedback="")
    saved = mgr.save_packet(job, packet, prompt)
    mgr.update_job_status(job.id, eaj.WAITING_FOR_EXTERNAL_AGENT)
    handoff = engine.create_handoff(
        action_id,
        handoff_type=handoff_type,
        target_loop_type=target_loop_type,
        target_workspace=target_workspace,
        external_coder=external_coder,
        confirm_create_external_job=True,
        created_external_job_id=job.id,
    )
    database.save_observatory_action_handoff_event(
        conn,
        handoff.id,
        action_id,
        "external_job_packet_created",
        json.dumps({
            "job_id": job.id,
            "job_dir": saved["job_dir"],
            "packet_safe": saved["packet_safe"],
            "packet_safe_reasons": saved["packet_safe_reasons"],
        }, sort_keys=True),
    )
    return handoff


def _print_action_handoff(handoff, conn):
    _rule("OBSERVATORY ACTION HANDOFF")
    print(f"Handoff ID       : {handoff.id}")
    print(f"Action ID        : {handoff.action_id}")
    print(f"Type             : {handoff.handoff_type}")
    print(f"Status           : {handoff.status}")
    print(f"Target loop type : {handoff.target_loop_type}")
    print(f"Target workspace : {handoff.target_workspace}")
    print(f"External coder   : {handoff.external_coder}")
    print(f"Created loop     : {handoff.created_loop_id or '(none)'}")
    print(f"Created job      : {handoff.created_external_job_id or '(none)'}")
    print(f"Created at       : {handoff.created_at}")
    _rule("GENERATED TASK")
    print(handoff.generated_task)
    _rule("SUGGESTED COMMAND")
    print(handoff.suggested_command)
    _rule("SAFETY NOTES")
    for note in handoff.safety_notes:
        print(f"- {note}")
    events = database.get_observatory_action_handoff_events(conn, handoff.id)
    _rule("EVENTS")
    if not events:
        print("(none)")
    for event in events:
        print(f"- {event['created_at']} {event['event_type']} {event['details_json']}")


def _cmd_observatory_action_handoffs(args) -> int:
    limit = 20
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                print("ERROR: --limit needs an integer", file=sys.stderr)
                return 1
    conn = database.init_db()
    rows = database.list_observatory_action_handoffs(conn, limit)
    _rule(f"OBSERVATORY ACTION HANDOFFS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for row in rows:
        print(f"#{row['id']} action={row['action_id']} type={row['handoff_type']} "
              f"status={row['status']} dry_run={bool(row['dry_run'])}")
        print(f"    target: loop={row['target_loop_type']} "
              f"workspace={row['target_workspace']} external={row['external_coder']}")
    return 0


def _cmd_observatory_action_handoff(args) -> int:
    if not args:
        print("ERROR: --observatory-action-handoff needs a HANDOFF_ID", file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        handoff_id = _parse_id_or_latest(conn, args[0], _latest_handoff_id,
                                         "observatory action handoff")
    except (ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    row = database.get_observatory_action_handoff(conn, handoff_id)
    if row is None:
        print(f"ERROR: no observatory action handoff {args[0]}", file=sys.stderr)
        return 1
    _print_action_handoff(observatory_action_handoff.handoff_from_row(row), conn)
    return 0


def _handoff_review_filters(args):
    limit = 25
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            limit = int(args[i + 1])
    return {
        "status": _flag_val(args, "--status"),
        "handoff_type": _flag_val(args, "--type"),
        "workspace": _flag_val(args, "--workspace"),
        "external_coder": _flag_val(args, "--external-coder"),
        "group_by": _flag_val(args, "--group-by") or "status",
        "limit": limit,
    }


def _print_handoff_review(report, review_id=None, markdown_path=None):
    filters = json.loads(report.filters_json or "{}")
    _rule("OBSERVATORY ACTION HANDOFF REVIEW")
    if review_id is not None:
        print(f"Review ID       : {review_id}")
    if markdown_path:
        print(f"Markdown report : {markdown_path}")
    _rule("SUMMARY")
    print(f"Generated at      : {report.generated_at}")
    print(f"Handoffs reviewed : {report.total_handoffs_reviewed}")
    print(f"Filters           : {report.filters_json}")
    print(f"Group by          : {filters.get('group_by', 'status')}")

    _rule("GROUPS")
    if not report.groups:
        print("(none)")
    for group in report.groups:
        print(f"- type={group.group_type} key={group.group_key} count={group.count}")
        print(f"  handoffs : {group.handoff_ids}")
        print(f"  summary  : {group.summary}")
        print(f"  action   : {group.recommended_action}")

    _rule("HANDOFFS")
    if not report.items:
        print("(none)")
    for item in report.items:
        print(f"- handoff #{item.handoff_id} action=#{item.action_id} "
              f"type={item.handoff_type} status={item.status}")
        print(f"  review   : {item.review_status} score={item.review_score}")
        print(f"  target   : loop={item.target_loop_type} "
              f"workspace={item.target_workspace} external={item.external_coder}")
        print(f"  created  : loop={item.created_loop_id or '(none)'} "
              f"job={item.created_external_job_id or '(none)'}")
        print(f"  task     : {item.generated_task_preview}")
        print(f"  rationale: {item.rationale}")
        print(f"  action   : {item.recommended_action}")

    _rule("NEXT STEPS")
    if not report.next_steps:
        print("(none)")
    for step in report.next_steps:
        print(f"- {step}")


def _latest_handoff_review_id(conn):
    rows = database.list_observatory_action_handoff_reviews(conn, 1)
    return rows[0]["id"] if rows else None


def _handoff_review_markdown_path_display(path):
    if not path:
        return "(none)"
    if not observatory_action_handoff_review.is_markdown_report_path(path):
        return f"invalid handoff review report path metadata: {path}"
    if not os.path.exists(path):
        return f"missing handoff review report path: {path}"
    return path


def _cmd_observatory_action_handoff_review(args) -> int:
    try:
        filters = _handoff_review_filters(args)
    except (ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    save_report = "--save-report" in args
    conn = database.init_db()
    engine = observatory_action_handoff_review.ActionHandoffReviewEngine(conn)
    try:
        report = engine.build_report(**filters)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    review_id = engine.save_review(report, group_by=filters["group_by"])
    markdown_path = None
    if save_report:
        try:
            md = engine.save_markdown_report(review_id, report)
            markdown_path = md.report_path
        except Exception as exc:
            print(f"ERROR: handoff review markdown failed: {exc}", file=sys.stderr)
            return 1
    _print_handoff_review(report, review_id=review_id, markdown_path=markdown_path)
    return 0


def _cmd_observatory_action_handoff_reviews(args) -> int:
    limit = 20
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                print("ERROR: --limit needs an integer", file=sys.stderr)
                return 1
    conn = database.init_db()
    rows = database.list_observatory_action_handoff_reviews(conn, limit)
    _rule(f"OBSERVATORY ACTION HANDOFF REVIEWS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for row in rows:
        md = database.get_observatory_action_handoff_review_markdown_report(
            conn, row["id"])
        print(f"#{row['id']}  {row['generated_at']}  "
              f"handoffs={row['total_handoffs_reviewed']} "
              f"group_by={row['group_by']}")
        print(f"    filters: {row['filters_json']}")
        if md is not None:
            print(f"    markdown: {_handoff_review_markdown_path_display(md['report_path'])}")
    return 0


def _cmd_observatory_action_handoff_review_show(args) -> int:
    if not args:
        print("ERROR: --observatory-action-handoff-review-show needs a REVIEW_ID",
              file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        review_id = _parse_id_or_latest(conn, args[0], _latest_handoff_review_id,
                                        "observatory action handoff review")
    except (ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    row = database.get_observatory_action_handoff_review(conn, review_id)
    if row is None:
        print(f"ERROR: no observatory action handoff review {args[0]}", file=sys.stderr)
        return 1
    report = observatory_action_handoff_review.report_from_row(row)
    md = database.get_observatory_action_handoff_review_markdown_report(conn, row["id"])
    _print_handoff_review(
        report,
        review_id=row["id"],
        markdown_path=_handoff_review_markdown_path_display(md["report_path"]) if md else None,
    )
    return 0


def _latest_stage4_audit_id(conn):
    rows = database.list_observatory_stage4_audits(conn, 1)
    return rows[0]["id"] if rows else None


def _stage4_audit_markdown_path_display(path):
    if not path:
        return "(none)"
    if not observatory_stage4_audit.is_markdown_report_path(path):
        return f"invalid Stage 4 audit report path metadata: {path}"
    if not os.path.exists(path):
        return f"missing Stage 4 audit report path: {path}"
    return path


def _print_stage4_audit(report, audit_id=None, markdown_path=None):
    _rule("STAGE 4 OBSERVATORY AUDIT")
    if audit_id is not None:
        print(f"Audit ID          : {audit_id}")
    if markdown_path:
        print(f"Markdown report   : {markdown_path}")
    readiness = report.stage5_readiness or {}
    _rule("SUMMARY")
    print(f"Generated at      : {report.generated_at}")
    print(f"Overall status    : {report.overall_status}")
    print(f"Total checks      : {report.total_checks}")
    print(f"Passed            : {report.passed_checks}")
    print(f"Warnings          : {report.warning_checks}")
    print(f"Failed            : {report.failed_checks}")
    print(f"Stage 5 readiness : {readiness.get('ready_text', 'no')}")

    _rule("SECTIONS")
    if not report.sections:
        print("(none)")
    for section in report.sections:
        print(f"- {section.name}: {section.status}")
        print(f"  summary: {section.summary}")
        for check in section.checks:
            print(f"  [{check.status}] {check.name}")
            print(f"    message : {check.message}")
            print(f"    evidence: {check.evidence}")
            if check.recommended_action:
                print(f"    action  : {check.recommended_action}")

    _rule("RECOMMENDATIONS")
    if not report.recommendations:
        print("(none)")
    for rec in report.recommendations:
        print(f"- {rec}")

    _rule("STAGE 5 READINESS")
    print(f"ready                : {readiness.get('ready_text', 'no')}")
    blockers = readiness.get("blockers") or []
    warnings = readiness.get("warnings") or []
    print("blockers:")
    if not blockers:
        print("- (none)")
    for blocker in blockers:
        print(f"- {blocker}")
    print("warnings:")
    if not warnings:
        print("- (none)")
    for warning in warnings:
        print(f"- {warning}")
    print(f"recommended next stage: {readiness.get('recommended_next_stage', '')}")


def _cmd_observatory_stage4_audit(args) -> int:
    save_report = "--save-report" in args
    conn = database.init_db()
    engine = observatory_stage4_audit.ObservatoryStage4AuditEngine(conn)
    try:
        report = engine.build_report()
        audit_id = engine.save_audit(report)
        markdown_path = None
        if save_report:
            md = engine.save_markdown_report(audit_id, report)
            markdown_path = md.report_path
    except Exception as exc:
        print(f"ERROR: Stage 4 audit failed: {exc}", file=sys.stderr)
        return 1
    _print_stage4_audit(report, audit_id=audit_id, markdown_path=markdown_path)
    return 0


def _cmd_observatory_stage4_audits(args) -> int:
    limit = 20
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                print("ERROR: --limit needs an integer", file=sys.stderr)
                return 1
    conn = database.init_db()
    rows = database.list_observatory_stage4_audits(conn, limit)
    _rule(f"STAGE 4 OBSERVATORY AUDITS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for row in rows:
        md = database.get_observatory_stage4_audit_markdown_report(conn, row["id"])
        print(f"#{row['id']}  {row['generated_at']}  status={row['overall_status']} "
              f"checks={row['total_checks']} pass={row['passed_checks']} "
              f"warn={row['warning_checks']} fail={row['failed_checks']}")
        if md is not None:
            print(f"    markdown: {_stage4_audit_markdown_path_display(md['report_path'])}")
    return 0


def _cmd_observatory_stage4_audit_show(args) -> int:
    if not args:
        print("ERROR: --observatory-stage4-audit-show needs an AUDIT_ID",
              file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        audit_id = _parse_id_or_latest(conn, args[0], _latest_stage4_audit_id,
                                       "observatory Stage 4 audit")
    except (ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    row = database.get_observatory_stage4_audit(conn, audit_id)
    if row is None:
        print(f"ERROR: no observatory Stage 4 audit {args[0]}", file=sys.stderr)
        return 1
    report = observatory_stage4_audit.report_from_row(row)
    md = database.get_observatory_stage4_audit_markdown_report(conn, row["id"])
    _print_stage4_audit(
        report,
        audit_id=row["id"],
        markdown_path=_stage4_audit_markdown_path_display(md["report_path"]) if md else None,
    )
    return 0


def _action_review_filters(args):
    status = _flag_val(args, "--status")
    if status is None:
        status = "open"
    limit = 25
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            limit = int(args[i + 1])
    return {
        "status": status,
        "priority": _flag_val(args, "--priority"),
        "category": _flag_val(args, "--category"),
        "group_by": _flag_val(args, "--group-by") or "category",
        "limit": limit,
    }


def _print_action_review(report, review_id=None, markdown_path=None):
    filters = json.loads(report.filters_json or "{}")
    _rule("OBSERVATORY ACTION REVIEW")
    if review_id is not None:
        print(f"Review ID       : {review_id}")
    if markdown_path:
        print(f"Markdown report : {markdown_path}")
    _rule("SUMMARY")
    print(f"Generated at    : {report.generated_at}")
    print(f"Actions reviewed: {report.total_actions_reviewed}")
    print(f"Filters         : {report.filters_json}")
    print(f"Group by        : {filters.get('group_by', 'category')}")

    _rule("TOP ACTIONS")
    if not report.top_actions:
        print("(none)")
    for item in report.top_actions:
        print(f"- action #{item.action_id} [{item.priority}] {item.category} "
              f"status={item.status} score={item.review_score}")
        print(f"  risk/effort : {item.risk_level} / {item.effort_level}")
        print(f"  loops/jobs   : {item.affected_loop_ids or []} / {item.affected_job_ids or []}")
        print(f"  title        : {item.title}")
        print(f"  rationale    : {item.rationale}")
        print(f"  next step    : {item.next_step}")
        print(f"  command      : {item.suggested_command}")

    _rule("GROUPS")
    if not report.groups:
        print("(none)")
    for group in report.groups:
        print(f"- type={group.group_type} key={group.group_key} count={group.count}")
        print(f"  actions   : {group.action_ids}")
        print(f"  highest   : {group.highest_priority}")
        print(f"  summary   : {group.summary}")
        print(f"  next step : {group.recommended_next_step}")

    _rule("RECOMMENDATIONS")
    if not report.recommendations:
        print("(none)")
    for rec in report.recommendations:
        print(f"- {rec}")

    _rule("NEXT STEPS")
    if not report.next_steps:
        print("(none)")
    for step in report.next_steps[:3]:
        print(f"- {step}")


def _action_review_markdown_path_display(path):
    if not path:
        return "(none)"
    if not observatory_action_review.is_markdown_report_path(path):
        return f"invalid action review report path metadata: {path}"
    if not os.path.exists(path):
        return f"missing action review report path: {path}"
    return path


def _cmd_observatory_action_review(args) -> int:
    try:
        filters = _action_review_filters(args)
    except (ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    save_report = "--save-report" in args
    conn = database.init_db()
    engine = observatory_action_review.ObservatoryActionReviewEngine(conn)
    try:
        report = engine.build_report(**filters)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    review_id = engine.save_review(report, group_by=filters["group_by"])
    markdown_path = None
    if save_report:
        try:
            md = engine.save_markdown_report(review_id, report)
            markdown_path = md.report_path
        except Exception as exc:
            print(f"ERROR: observatory action review markdown failed: {exc}",
                  file=sys.stderr)
            return 1
    _print_action_review(report, review_id=review_id, markdown_path=markdown_path)
    return 0


def _cmd_observatory_action_reviews(args) -> int:
    limit = 20
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                print("ERROR: --limit needs an integer", file=sys.stderr)
                return 1
    conn = database.init_db()
    rows = database.list_observatory_action_reviews(conn, limit)
    _rule(f"OBSERVATORY ACTION REVIEWS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for row in rows:
        md = database.get_observatory_action_review_markdown_report(conn, row["id"])
        print(f"#{row['id']}  {row['generated_at']}  actions={row['total_actions_reviewed']} "
              f"group_by={row['group_by']}")
        print(f"    filters: {row['filters_json']}")
        if md is not None:
            print(f"    markdown: {_action_review_markdown_path_display(md['report_path'])}")
    return 0


def _cmd_observatory_action_review_show(args) -> int:
    if not args:
        print("ERROR: --observatory-action-review-show needs a REVIEW_ID", file=sys.stderr)
        return 1
    conn = database.init_db()
    if args[0] == "latest":
        rows = database.list_observatory_action_reviews(conn, 1)
        row = rows[0] if rows else None
    else:
        try:
            review_id = int(args[0])
        except ValueError:
            print("ERROR: REVIEW_ID must be an integer or 'latest'", file=sys.stderr)
            return 1
        row = database.get_observatory_action_review(conn, review_id)
    if row is None:
        print(f"ERROR: no observatory action review {args[0]}", file=sys.stderr)
        return 1
    report = observatory_action_review.report_from_row(row)
    md = database.get_observatory_action_review_markdown_report(conn, row["id"])
    _print_action_review(
        report,
        review_id=row["id"],
        markdown_path=_action_review_markdown_path_display(md["report_path"]) if md else None,
    )
    return 0


def _improvement_args(args):
    source_type = None
    source_id = None
    if "--action-review" in args:
        source_type = "action_review"
        val = _flag_val(args, "--action-review")
        if not val:
            raise ValueError("--action-review needs a REVIEW_ID")
        source_id = int(val)
    if "--from-remediation" in args:
        source_type = "remediation_plan"
        source_id = None
    if "--remediation-plan" in args:
        source_type = "remediation_plan"
        val = _flag_val(args, "--remediation-plan")
        if not val:
            raise ValueError("--remediation-plan needs a PLAN_ID")
        source_id = int(val)
    if "--from-failures" in args:
        source_type = "failure_drilldown"
        source_id = None
    if "--failure-drilldown" in args:
        source_type = "failure_drilldown"
        val = _flag_val(args, "--failure-drilldown")
        if not val:
            raise ValueError("--failure-drilldown needs a DRILLDOWN_ID")
        source_id = int(val)
    limit = 25
    if "--limit" in args:
        val = _flag_val(args, "--limit")
        if not val:
            raise ValueError("--limit needs an integer")
        limit = int(val)
    return {
        "source_type": source_type,
        "source_id": source_id,
        "priority": _flag_val(args, "--priority"),
        "target_type": _flag_val(args, "--target-type"),
        "limit": limit,
    }


def _print_improvement_plan(plan, plan_id=None, markdown_path=None):
    _rule("LOOP IMPROVEMENT PLAN")
    if plan_id is not None:
        print(f"Plan ID      : {plan_id}")
    if markdown_path:
        print(f"Markdown     : {markdown_path}")
    _rule("SUMMARY")
    print(f"Generated at : {plan.generated_at}")
    print(f"Source type  : {plan.source_type}")
    print(f"Source ID    : {plan.source_id}")
    print(f"Total        : {plan.total_proposals}")
    print(f"Urgent       : {plan.urgent_count}")
    print(f"High         : {plan.high_count}")
    print(f"Medium       : {plan.medium_count}")
    print(f"Low          : {plan.low_count}")
    print(f"Summary      : {plan.summary}")

    _rule("PROPOSALS")
    if not plan.proposals:
        print("(none)")
    for proposal in plan.proposals:
        print(f"- ID {proposal.id}: [{proposal.priority}] "
              f"{proposal.target_type}/{proposal.target_name}")
        print(f"  title       : {proposal.title}")
        print(f"  problem     : {proposal.problem_summary}")
        print(f"  evidence    : {proposal.evidence or []}")
        print(f"  change      : {proposal.proposed_change}")
        print(f"  benefit     : {proposal.expected_benefit}")
        print(f"  risk        : {proposal.risk_level}")
        print(f"  effort      : {proposal.effort_level}")
        print(f"  loops       : {proposal.affected_loop_ids or []}")
        print(f"  actions     : {proposal.affected_action_ids or []}")
        print(f"  remediation : {proposal.affected_remediation_plan_ids or []}")
        print(f"  status      : {proposal.status}")

    _rule("NEXT STEPS")
    for step in plan.next_steps:
        if plan_id is not None:
            step = step.replace("PLAN_ID", str(plan_id))
        first_proposal = plan.proposals[0].id if plan.proposals else "PROPOSAL_ID"
        step = step.replace("PROPOSAL_ID", str(first_proposal))
        print(f"- {step}")


def _improvement_markdown_path_display(path):
    if not path:
        return "(none)"
    if not loop_improvement.is_markdown_report_path(path):
        return f"invalid improvement report path metadata: {path}"
    if not os.path.exists(path):
        return f"missing improvement report path: {path}"
    return path


def _cmd_loop_improvements(args) -> int:
    try:
        filters = _improvement_args(args)
    except (ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    save_report = "--save-report" in args
    conn = database.init_db()
    engine = loop_improvement.LoopImprovementEngine(conn)
    try:
        plan = engine.build_plan(**filters)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    plan_id = engine.save_plan(plan, filters)
    markdown_path = None
    if save_report:
        try:
            md = engine.save_markdown_report(plan_id, plan)
            markdown_path = md.report_path
        except Exception as exc:
            print(f"ERROR: loop improvement markdown failed: {exc}",
                  file=sys.stderr)
            return 1
    _print_improvement_plan(plan, plan_id=plan_id, markdown_path=markdown_path)
    return 0


def _cmd_loop_improvement_plans(args) -> int:
    limit = 20
    if "--limit" in args:
        try:
            limit = int(_flag_val(args, "--limit"))
        except (TypeError, ValueError):
            print("ERROR: --limit needs an integer", file=sys.stderr)
            return 1
    conn = database.init_db()
    rows = database.list_loop_improvement_plans(conn, limit)
    _rule(f"LOOP IMPROVEMENT PLANS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for row in rows:
        md = database.get_loop_improvement_markdown_report(conn, row["id"])
        print(f"#{row['id']}  {row['generated_at']}  "
              f"source={row['source_type']}:{row['source_id']} "
              f"proposals={row['total_proposals']} urgent={row['urgent_count']} "
              f"high={row['high_count']} medium={row['medium_count']} "
              f"low={row['low_count']}")
        print(f"    filters: {row['filters_json']}")
        if md is not None:
            print(f"    markdown: {_improvement_markdown_path_display(md['report_path'])}")
    return 0


def _latest_improvement_plan_id(conn):
    rows = database.list_loop_improvement_plans(conn, 1)
    return rows[0]["id"] if rows else None


def _latest_improvement_proposal_id(conn):
    rows = database.list_loop_improvement_proposals(conn, limit=1)
    return rows[0]["id"] if rows else None


def _cmd_loop_improvement_plan(args) -> int:
    if not args:
        print("ERROR: --loop-improvement-plan needs a PLAN_ID", file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        plan_id = _parse_id_or_latest(
            conn, args[0], _latest_improvement_plan_id, "loop improvement plan")
    except ValueError:
        print("ERROR: PLAN_ID must be an integer or 'latest'", file=sys.stderr)
        return 1
    row = database.get_loop_improvement_plan(conn, plan_id)
    if row is None:
        print(f"ERROR: no loop improvement plan {args[0]}", file=sys.stderr)
        return 1
    plan = loop_improvement.plan_from_row(row)
    md = database.get_loop_improvement_markdown_report(conn, row["id"])
    _print_improvement_plan(
        plan,
        plan_id=row["id"],
        markdown_path=_improvement_markdown_path_display(md["report_path"]) if md else None,
    )
    return 0


def _cmd_loop_improvement_proposals(args) -> int:
    limit = 25
    if "--limit" in args:
        try:
            limit = int(_flag_val(args, "--limit"))
        except (TypeError, ValueError):
            print("ERROR: --limit needs an integer", file=sys.stderr)
            return 1
    conn = database.init_db()
    rows = database.list_loop_improvement_proposals(
        conn,
        status=_flag_val(args, "--status"),
        priority=_flag_val(args, "--priority"),
        target_type=_flag_val(args, "--target-type"),
        limit=limit,
    )
    _rule(f"LOOP IMPROVEMENT PROPOSALS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for row in rows:
        print(f"#{row['id']}  plan={row['plan_id']}  [{row['priority']}] "
              f"{row['target_type']}/{row['target_name']}  status={row['status']}")
        print(f"    title: {row['title']}")
        print(f"    problem: {row['problem_summary']}")
        print(f"    change: {row['proposed_change']}")
    return 0


def _cmd_loop_improvement_proposal(args) -> int:
    if not args:
        print("ERROR: --loop-improvement-proposal needs a PROPOSAL_ID", file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        proposal_id = _parse_id_or_latest(
            conn, args[0], _latest_improvement_proposal_id,
            "loop improvement proposal")
    except ValueError:
        print("ERROR: PROPOSAL_ID must be an integer or 'latest'", file=sys.stderr)
        return 1
    row = database.get_loop_improvement_proposal(conn, proposal_id)
    if row is None:
        print(f"ERROR: no loop improvement proposal {args[0]}", file=sys.stderr)
        return 1
    proposal = loop_improvement.proposal_from_row(row)
    _rule("LOOP IMPROVEMENT PROPOSAL")
    print(f"ID          : {proposal.id}")
    print(f"Plan ID     : {row['plan_id']}")
    print(f"Priority    : {proposal.priority}")
    print(f"Target type : {proposal.target_type}")
    print(f"Target name : {proposal.target_name}")
    print(f"Title       : {proposal.title}")
    print(f"Problem     : {proposal.problem_summary}")
    print(f"Evidence    : {proposal.evidence or []}")
    print(f"Change      : {proposal.proposed_change}")
    print(f"Benefit     : {proposal.expected_benefit}")
    print(f"Risk        : {proposal.risk_level}")
    print(f"Effort      : {proposal.effort_level}")
    print(f"Loops       : {proposal.affected_loop_ids or []}")
    print(f"Actions     : {proposal.affected_action_ids or []}")
    print(f"Remediation : {proposal.affected_remediation_plan_ids or []}")
    print(f"Status      : {proposal.status}")
    return 0


def _cmd_set_loop_improvement_status(args) -> int:
    if len(args) < 2:
        print("ERROR: --set-loop-improvement-status needs PROPOSAL_ID STATUS",
              file=sys.stderr)
        return 1
    status = args[1]
    if status not in loop_improvement.STATUSES:
        print("ERROR: status must be proposed, accepted, rejected, deferred, "
              "or converted_to_action", file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        proposal_id = _parse_id_or_latest(
            conn, args[0], _latest_improvement_proposal_id,
            "loop improvement proposal")
    except ValueError:
        print("ERROR: PROPOSAL_ID must be an integer or 'latest'", file=sys.stderr)
        return 1
    if database.get_loop_improvement_proposal(conn, proposal_id) is None:
        print(f"ERROR: no loop improvement proposal {args[0]}", file=sys.stderr)
        return 1
    database.update_loop_improvement_proposal_status(conn, proposal_id, status)
    print(f"loop improvement proposal {proposal_id} status -> {status}")
    print("proposal status was updated; no improvement was applied automatically")
    return 0


def _improvement_review_filters(args):
    group_by = _flag_val(args, "--group-by") or "target_type"
    limit = 25
    if "--limit" in args:
        val = _flag_val(args, "--limit")
        if not val:
            raise ValueError("--limit needs an integer")
        limit = int(val)
    return {
        "status": _flag_val(args, "--status") or "proposed",
        "priority": _flag_val(args, "--priority"),
        "target_type": _flag_val(args, "--target-type"),
        "group_by": group_by,
        "limit": limit,
    }


def _print_improvement_review(report, review_id=None, group_by=None,
                              markdown_path=None):
    _rule("LOOP IMPROVEMENT PROPOSAL REVIEW")
    if review_id is not None:
        print(f"Review ID       : {review_id}")
    if markdown_path:
        print(f"Markdown        : {markdown_path}")
    _rule("SUMMARY")
    print(f"Generated at    : {report.generated_at}")
    print(f"Proposals reviewed: {report.total_proposals_reviewed}")
    print(f"Filters         : {report.filters_json}")
    print(f"Group by        : {group_by or '(unknown)'}")

    _rule("TOP PROPOSALS")
    if not report.top_proposals:
        print("(none)")
    for item in report.top_proposals:
        print(f"- proposal #{item.proposal_id} plan=#{item.plan_id} "
              f"[{item.priority}] {item.target_type}/{item.target_name}")
        print(f"  status      : {item.status}")
        print(f"  score       : {item.review_score}")
        print(f"  risk/effort : {item.risk_level} / {item.effort_level}")
        print(f"  title       : {item.title}")
        print(f"  problem     : {item.problem_summary}")
        print(f"  change      : {item.proposed_change}")
        print(f"  benefit     : {item.expected_benefit}")
        print(f"  rationale   : {item.rationale}")
        print(f"  decision    : {item.recommended_decision}")
        print(f"  command     : {item.suggested_next_command}")

    _rule("GROUPS")
    if not report.groups:
        print("(none)")
    for group in report.groups:
        print(f"- type={group.group_type} key={group.group_key} count={group.count}")
        print(f"  proposals : {group.proposal_ids}")
        print(f"  highest   : {group.highest_priority}")
        print(f"  summary   : {group.summary}")
        print(f"  next step : {group.recommended_next_step}")

    _rule("RECOMMENDATIONS")
    for cmd in report.recommendations:
        if review_id is not None:
            cmd = cmd.replace("REVIEW_ID", str(review_id))
        print(f"- {cmd}")

    _rule("NEXT STEPS")
    for cmd in report.next_steps:
        print(f"- {cmd}")


def _improvement_review_markdown_path_display(path):
    if not path:
        return "(none)"
    if not loop_improvement_review.is_markdown_report_path(path):
        return f"invalid improvement review report path metadata: {path}"
    if not os.path.exists(path):
        return f"missing improvement review report path: {path}"
    return path


def _cmd_loop_improvement_review(args) -> int:
    try:
        filters = _improvement_review_filters(args)
    except (ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    save_report = "--save-report" in args
    conn = database.init_db()
    engine = loop_improvement_review.LoopImprovementReviewEngine(conn)
    try:
        report = engine.build_report(**filters)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    review_id = engine.save_review(report, group_by=filters["group_by"])
    markdown_path = None
    if save_report:
        try:
            md = engine.save_markdown_report(review_id, report)
            markdown_path = md.report_path
        except Exception as exc:
            print(f"ERROR: loop improvement review markdown failed: {exc}",
                  file=sys.stderr)
            return 1
    _print_improvement_review(
        report, review_id=review_id, group_by=filters["group_by"],
        markdown_path=markdown_path)
    return 0


def _cmd_loop_improvement_reviews(args) -> int:
    limit = 20
    if "--limit" in args:
        try:
            limit = int(_flag_val(args, "--limit"))
        except (TypeError, ValueError):
            print("ERROR: --limit needs an integer", file=sys.stderr)
            return 1
    conn = database.init_db()
    rows = database.list_loop_improvement_reviews(conn, limit)
    _rule(f"LOOP IMPROVEMENT REVIEWS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for row in rows:
        md = database.get_loop_improvement_review_markdown_report(conn, row["id"])
        print(f"#{row['id']}  {row['generated_at']}  "
              f"proposals={row['total_proposals_reviewed']} group_by={row['group_by']}")
        print(f"    filters: {row['filters_json']}")
        if md is not None:
            print(f"    markdown: {_improvement_review_markdown_path_display(md['report_path'])}")
    return 0


def _latest_improvement_review_id(conn):
    rows = database.list_loop_improvement_reviews(conn, 1)
    return rows[0]["id"] if rows else None


def _cmd_loop_improvement_review_show(args) -> int:
    if not args:
        print("ERROR: --loop-improvement-review-show needs a REVIEW_ID", file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        review_id = _parse_id_or_latest(
            conn, args[0], _latest_improvement_review_id,
            "loop improvement review")
    except ValueError:
        print("ERROR: REVIEW_ID must be an integer or 'latest'", file=sys.stderr)
        return 1
    row = database.get_loop_improvement_review(conn, review_id)
    if row is None:
        print(f"ERROR: no loop improvement review {args[0]}", file=sys.stderr)
        return 1
    report = loop_improvement_review.report_from_row(row)
    md = database.get_loop_improvement_review_markdown_report(conn, row["id"])
    _print_improvement_review(
        report,
        review_id=row["id"],
        group_by=row["group_by"],
        markdown_path=_improvement_review_markdown_path_display(md["report_path"]) if md else None,
    )
    return 0


def _latest_improvement_action_id(conn):
    rows = database.list_loop_improvement_action_items(conn, status=None, limit=1)
    return rows[0]["id"] if rows else None


def _latest_improvement_action_batch_id(conn):
    rows = database.list_loop_improvement_action_batches(conn, 1)
    return rows[0]["id"] if rows else None


def _improvement_action_create_filters(args):
    return {
        "priority": _flag_val(args, "--priority"),
        "target_type": _flag_val(args, "--target-type"),
        "include_deferred": "--include-deferred" in args,
        "include_rejected": "--include-rejected" in args,
    }


def _cmd_create_loop_improvement_actions(args) -> int:
    if not args:
        print("ERROR: --create-loop-improvement-actions needs a REVIEW_ID",
              file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        review_id = _parse_id_or_latest(
            conn, args[0], _latest_improvement_review_id,
            "loop improvement review")
    except ValueError:
        print("ERROR: REVIEW_ID must be an integer or 'latest'", file=sys.stderr)
        return 1
    filters = _improvement_action_create_filters(args[1:])
    engine = loop_improvement_actions.LoopImprovementActionEngine(conn)
    try:
        batch = engine.create_actions_from_review(review_id, **filters)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _rule("LOOP IMPROVEMENT ACTION CONVERSION")
    print(f"Batch ID          : {batch.id}")
    print(f"Source review ID  : {batch.source_review_id}")
    print(f"Created           : {batch.created_count}")
    print(f"Skipped duplicate : {batch.skipped_duplicates}")
    print(f"Filters           : {json.dumps(filters, sort_keys=True)}")
    _rule("ACTIONS")
    if not batch.actions:
        print("(none)")
    for action in batch.actions:
        print(f"- action #{action.id} proposal=#{action.source_proposal_id} "
              f"[{action.priority}] {action.target_type}/{action.target_name}")
        print(f"  status  : {action.status}")
        print(f"  title   : {action.title}")
        print(f"  command : {action.suggested_next_command}")
    _rule("SAFETY")
    print("No proposals were applied automatically.")
    print("No suggested commands were executed.")
    print("No loops, jobs, prompts, gates, or stop conditions were changed.")
    return 0


def _cmd_loop_improvement_actions(args) -> int:
    status = _flag_val(args, "--status") or "open"
    priority = _flag_val(args, "--priority")
    target_type = _flag_val(args, "--target-type")
    limit = 25
    if "--limit" in args:
        try:
            limit = int(_flag_val(args, "--limit"))
        except (TypeError, ValueError):
            print("ERROR: --limit needs an integer", file=sys.stderr)
            return 1
    conn = database.init_db()
    engine = loop_improvement_actions.LoopImprovementActionEngine(conn)
    actions = engine.list_actions(
        status=status, priority=priority, target_type=target_type, limit=limit)
    _rule(f"LOOP IMPROVEMENT ACTIONS ({len(actions)})")
    if not actions:
        print("(none)")
        return 0
    for action in actions:
        print(f"#{action.id} review={action.source_review_id} "
              f"proposal={action.source_proposal_id} [{action.priority}] "
              f"{action.target_type}/{action.target_name} status={action.status} "
              f"age={_age(action.created_at)}")
        print(f"    title: {action.title}")
        print(f"    next : {action.suggested_next_command}")
    return 0


def _cmd_loop_improvement_action(args) -> int:
    if not args:
        print("ERROR: --loop-improvement-action needs an ACTION_ID", file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        action_id = _parse_id_or_latest(
            conn, args[0], _latest_improvement_action_id,
            "loop improvement action")
    except ValueError:
        print("ERROR: ACTION_ID must be an integer or 'latest'", file=sys.stderr)
        return 1
    engine = loop_improvement_actions.LoopImprovementActionEngine(conn)
    try:
        action = engine.get_action(action_id)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _rule("LOOP IMPROVEMENT ACTION")
    print(f"ID                    : {action.id}")
    print(f"Source review ID      : {action.source_review_id}")
    print(f"Source proposal ID    : {action.source_proposal_id}")
    print(f"Source plan ID        : {action.source_plan_id}")
    print(f"Target                : {action.target_type}/{action.target_name}")
    print(f"Title                 : {action.title}")
    print(f"Priority              : {action.priority}")
    print(f"Status                : {action.status}")
    print(f"Risk / effort         : {action.risk_level} / {action.effort_level}")
    print(f"Recommended decision  : {action.recommended_decision}")
    print(f"Problem summary       : {action.problem_summary}")
    print(f"Proposed change       : {action.proposed_change}")
    print(f"Expected benefit      : {action.expected_benefit}")
    print(f"Suggested command     : {action.suggested_next_command}")
    print(f"Affected loops        : {action.affected_loop_ids or []}")
    print(f"Affected actions      : {action.affected_action_ids or []}")
    print(f"Affected remediation  : {action.affected_remediation_plan_ids or []}")
    print(f"Notes                 : {action.notes}")
    print(f"Created at            : {action.created_at}")
    print(f"Updated at            : {action.updated_at}")
    print(f"Completed at          : {action.completed_at}")
    print(f"Dismissed at          : {action.dismissed_at}")
    _rule("STATUS COMMANDS")
    for status in ("in_progress", "completed", "dismissed", "blocked"):
        print(f"- python3 main.py --set-loop-improvement-action-status {action.id} {status}")
    print(f"- python3 main.py --set-loop-improvement-action-notes {action.id} \"notes\"")
    events = database.get_loop_improvement_action_events(conn, action.id)
    _rule("EVENTS")
    if not events:
        print("(none)")
    for event in events:
        print(f"- {event['created_at']} {event['event_type']} "
              f"{event['status_before']} -> {event['status_after']}")
    handoffs = database.list_loop_improvement_handoffs_for_action(conn, action.id, 10)
    _rule("HANDOFFS")
    if not handoffs:
        print("(none)")
    for h in handoffs:
        print(f"- #{h['id']} type={h['handoff_type']} status={h['status']} "
              f"dry_run={bool(h['dry_run'])}")
        print(f"  command: python3 main.py --loop-improvement-handoff {h['id']}")
    _rule("HANDOFF COMMANDS")
    print(f"- python3 main.py --handoff-loop-improvement-action {action.id}")
    print(f"- python3 main.py --handoff-loop-improvement-action {action.id} "
          f"--type implementation_packet")
    print(f"- python3 main.py --handoff-loop-improvement-action {action.id} "
          f"--type loop_task")
    print(f"- python3 main.py --handoff-loop-improvement-action {action.id} "
          f"--type external_agent_job --external-coder codex")
    return 0


def _cmd_set_loop_improvement_action_status(args) -> int:
    if len(args) < 2:
        print("ERROR: --set-loop-improvement-action-status needs ACTION_ID STATUS",
              file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        action_id = _parse_id_or_latest(
            conn, args[0], _latest_improvement_action_id,
            "loop improvement action")
    except ValueError:
        print("ERROR: ACTION_ID must be an integer or 'latest'", file=sys.stderr)
        return 1
    engine = loop_improvement_actions.LoopImprovementActionEngine(conn)
    try:
        action = engine.update_status(action_id, args[1])
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"loop improvement action {action.id} status -> {action.status}")
    print("proposal was not applied automatically")
    return 0


def _cmd_set_loop_improvement_action_notes(args) -> int:
    if len(args) < 2:
        print("ERROR: --set-loop-improvement-action-notes needs ACTION_ID NOTES",
              file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        action_id = _parse_id_or_latest(
            conn, args[0], _latest_improvement_action_id,
            "loop improvement action")
    except ValueError:
        print("ERROR: ACTION_ID must be an integer or 'latest'", file=sys.stderr)
        return 1
    notes = " ".join(args[1:])
    engine = loop_improvement_actions.LoopImprovementActionEngine(conn)
    try:
        action = engine.update_notes(action_id, notes)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"loop improvement action {action.id} notes updated")
    print("notes are stored as plain text and were not executed")
    return 0


def _cmd_loop_improvement_action_batches(args) -> int:
    limit = 20
    if "--limit" in args:
        try:
            limit = int(_flag_val(args, "--limit"))
        except (TypeError, ValueError):
            print("ERROR: --limit needs an integer", file=sys.stderr)
            return 1
    conn = database.init_db()
    rows = database.list_loop_improvement_action_batches(conn, limit)
    _rule(f"LOOP IMPROVEMENT ACTION BATCHES ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for row in rows:
        print(f"#{row['id']} review={row['source_review_id']} "
              f"generated={row['generated_at']} created={row['created_count']} "
              f"skipped={row['skipped_duplicates']}")
        print(f"    action ids: {row['action_ids_json']}")
        print(f"    filters   : {row['filters_json']}")
    return 0


def _cmd_loop_improvement_action_batch(args) -> int:
    if not args:
        print("ERROR: --loop-improvement-action-batch needs a BATCH_ID", file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        batch_id = _parse_id_or_latest(
            conn, args[0], _latest_improvement_action_batch_id,
            "loop improvement action batch")
    except ValueError:
        print("ERROR: BATCH_ID must be an integer or 'latest'", file=sys.stderr)
        return 1
    row = database.get_loop_improvement_action_batch(conn, batch_id)
    if row is None:
        print(f"ERROR: no loop improvement action batch {args[0]}", file=sys.stderr)
        return 1
    _rule("LOOP IMPROVEMENT ACTION BATCH")
    print(f"Batch ID          : {row['id']}")
    print(f"Source review ID  : {row['source_review_id']}")
    print(f"Generated at      : {row['generated_at']}")
    print(f"Total actions     : {row['total_actions']}")
    print(f"Created count     : {row['created_count']}")
    print(f"Skipped duplicate : {row['skipped_duplicates']}")
    print(f"Action IDs        : {row['action_ids_json']}")
    print(f"Filters           : {row['filters_json']}")
    return 0


def _cmd_loop_improvement_actions_report(args) -> int:
    conn = database.init_db()
    engine = loop_improvement_actions.LoopImprovementActionEngine(conn)
    try:
        md = engine.save_markdown_report()
    except Exception as exc:
        print(f"ERROR: loop improvement action report failed: {exc}",
              file=sys.stderr)
        return 1
    _rule("LOOP IMPROVEMENT ACTIONS REPORT")
    print(f"Markdown     : {md.report_path}")
    print(f"Bytes written: {md.bytes_written}")
    return 0


def _latest_loop_improvement_handoff_id(conn):
    rows = database.list_loop_improvement_handoffs(conn, 1)
    return rows[0]["id"] if rows else None


def _cmd_handoff_loop_improvement_action(args) -> int:
    if not args:
        print("ERROR: --handoff-loop-improvement-action needs an ACTION_ID",
              file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        action_id = _parse_id_or_latest(
            conn, args[0], _latest_improvement_action_id,
            "loop improvement action")
    except (ValueError, TypeError):
        print("ERROR: ACTION_ID must be an integer or 'latest'", file=sys.stderr)
        return 1
    handoff_type = _flag_val(args, "--type") or "dry_run_plan"
    target_loop_type = _flag_val(args, "--loop-type") or "code_build"
    target_workspace = _flag_val(args, "--workspace") or "default"
    external_coder = _flag_val(args, "--external-coder") or "codex"
    confirm_loop = "--confirm-create-loop" in args
    confirm_external = "--confirm-create-external-job" in args
    if confirm_loop and confirm_external:
        print("ERROR: choose only one confirmation flag", file=sys.stderr)
        return 1
    if confirm_loop and handoff_type == "dry_run_plan":
        handoff_type = "loop_task"
    if confirm_external and handoff_type == "dry_run_plan":
        handoff_type = "external_agent_job"
    if confirm_loop and handoff_type != "loop_task":
        print("ERROR: --confirm-create-loop requires --type loop_task", file=sys.stderr)
        return 1
    if confirm_external and handoff_type != "external_agent_job":
        print("ERROR: --confirm-create-external-job requires --type external_agent_job",
              file=sys.stderr)
        return 1
    try:
        engine = loop_improvement_handoff.LoopImprovementHandoffEngine(conn)
        if confirm_loop:
            return _create_loop_improvement_handoff_loop(
                conn, engine, action_id, handoff_type, target_loop_type,
                target_workspace, external_coder, args)
        if confirm_external:
            handoff = _create_loop_improvement_external_job_handoff(
                conn, engine, action_id, handoff_type, target_loop_type,
                target_workspace, external_coder)
        else:
            handoff = engine.create_handoff(
                action_id,
                handoff_type=handoff_type,
                target_loop_type=target_loop_type,
                target_workspace=target_workspace,
                external_coder=external_coder,
            )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _print_loop_improvement_handoff(handoff, conn)
    return 0


def _create_loop_improvement_handoff_loop(conn, engine, action_id, handoff_type,
                                          target_loop_type, target_workspace,
                                          external_coder, args) -> int:
    action = loop_improvement_actions.LoopImprovementActionEngine(
        conn).get_action(action_id, record_view=False)
    task = engine.generate_task(action)
    loop = REGISTRY.get_loop(target_loop_type)
    if loop is None:
        print(f"ERROR: no loop named '{target_loop_type}'. Try: python main.py --loops",
              file=sys.stderr)
        return 1
    ws_manager = project_workspace.WorkspaceManager(conn)
    ws = ws_manager.get_workspace(target_workspace)
    if ws is None:
        print(f"ERROR: no workspace '{target_workspace}'. Try: python main.py --workspaces",
              file=sys.stderr)
        return 1
    roles, role_errors = loop_engine_mod.resolve_roles(loop, AGENTS, {})
    if role_errors:
        print(f"ERROR: could not resolve agents: {role_errors}", file=sys.stderr)
        return 1
    commit = "--commit" in args
    commit_message = _flag_val(args, "--commit-message")
    min_conf = None
    if _flag_val(args, "--min-reviewer-confidence"):
        try:
            min_conf = float(_flag_val(args, "--min-reviewer-confidence"))
        except ValueError:
            print("ERROR: --min-reviewer-confidence needs a number", file=sys.stderr)
            return 1
    require_approval = "--require-approval" in args
    auto_approve_low_risk = "--auto-approve-low-risk" in args
    approval_mode = _flag_val(args, "--approval-mode")
    if approval_mode is None:
        approval_mode = "interactive" if require_approval else "none"
    approval_policy = approval_gates.ApprovalPolicy(
        name="cli", enabled=require_approval,
        auto_approve_low_risk=auto_approve_low_risk)
    approval_engine = approval_gates.ApprovalGateEngine(
        approval_policy, mode=approval_mode)
    before_loop_id = _latest_loop_id(conn)
    rc = _execute_run(
        conn, task, loop, ws, roles, {}, approval_engine, min_conf, commit,
        commit_message, memory_mode="off", context_mode="off",
        intake_bundle=None, external_coder=None)
    after_loop_id = _latest_loop_id(conn)
    created_loop_id = after_loop_id if after_loop_id != before_loop_id else None
    if created_loop_id is not None:
        handoff = engine.create_handoff(
            action_id,
            handoff_type=handoff_type,
            target_loop_type=target_loop_type,
            target_workspace=target_workspace,
            external_coder=external_coder,
            confirm_create_loop=True,
            created_loop_id=created_loop_id,
        )
        _print_loop_improvement_handoff(handoff, conn)
    return rc


def _create_loop_improvement_external_job_handoff(conn, engine, action_id, handoff_type,
                                                  target_loop_type, target_workspace,
                                                  external_coder):
    import external_agent_jobs as eaj

    action = loop_improvement_actions.LoopImprovementActionEngine(
        conn).get_action(action_id, record_view=False)
    loop = REGISTRY.get_loop(target_loop_type)
    if loop is None:
        raise ValueError(f"no loop named '{target_loop_type}'")
    adapter = EXTERNAL.get(external_coder)
    if adapter is None:
        raise ValueError(f"unknown external coder '{external_coder}'")
    ws_manager = project_workspace.WorkspaceManager(conn)
    ws = ws_manager.get_workspace(target_workspace)
    if ws is None:
        raise ValueError(f"no workspace '{target_workspace}'")
    workspace_errors = ws_manager.validate_workspace(ws)
    if workspace_errors:
        raise ValueError("workspace validation failed: " + "; ".join(workspace_errors))
    allowed_tools = []
    if loop.filesystem_enabled:
        allowed_tools.append("filesystem")
    if loop.terminal_enabled:
        allowed_tools.append("terminal")
    if getattr(loop, "git_enabled", False):
        allowed_tools.append("git")
    loop_id = (action.affected_loop_ids or [None])[-1]
    task = engine.generate_task(action)
    plan = ("Create a manual external-agent handoff for loop improvement action "
            f"#{action.id}. Do not execute suggested commands automatically; "
            "implement only within allowed workspace paths and return completion JSON.")
    mgr = eaj.ExternalAgentJobManager(conn)
    job = mgr.create_job(
        loop_id, 1, adapter.name, ws.name, ws.root_path,
        priority=eaj.DEFAULT_PRIORITY,
        labels=["loop-improvement", "handoff"],
        notes=f"Loop improvement action #{action.id} handoff")
    req = external_agents.ExternalAgentRequest(
        loop_id=loop_id, attempt_number=1, agent_name=adapter.name,
        task=task, plan=plan, workspace_name=ws.name, workspace_root=ws.root_path,
        allowed_write_paths=list(ws.allowed_write_paths),
        allowed_command_paths=list(ws.allowed_command_paths),
        dry_run=True, created_at="")
    prompt, safe, warnings = adapter.build_handoff(req)
    if not safe:
        raise ValueError("external handoff prompt failed safety checks: "
                         + "; ".join(warnings))
    packet = mgr.create_packet(
        job, task, plan, list(ws.allowed_write_paths),
        list(ws.allowed_command_paths), allowed_tools,
        context_summary="Loop improvement action metadata only.",
        memory_summary="",
        project_intelligence_summary="",
        context_pack_summary="",
        reviewer_feedback="",
        test_analyst_feedback="")
    saved = mgr.save_packet(job, packet, prompt)
    mgr.update_job_status(job.id, eaj.WAITING_FOR_EXTERNAL_AGENT)
    handoff = engine.create_handoff(
        action_id,
        handoff_type=handoff_type,
        target_loop_type=target_loop_type,
        target_workspace=target_workspace,
        external_coder=external_coder,
        confirm_create_external_job=True,
        created_external_job_id=job.id,
    )
    database.save_loop_improvement_handoff_event(
        conn,
        handoff.id,
        action_id,
        "external_job_packet_created",
        json.dumps({
            "job_id": job.id,
            "job_dir": saved["job_dir"],
            "packet_safe": saved["packet_safe"],
            "packet_safe_reasons": saved["packet_safe_reasons"],
        }, sort_keys=True),
    )
    return handoff


def _print_loop_improvement_handoff(handoff, conn):
    _rule("LOOP IMPROVEMENT HANDOFF")
    print(f"Handoff ID        : {handoff.id}")
    print(f"Action ID         : {handoff.action_id}")
    print(f"Proposal ID       : {handoff.source_proposal_id}")
    print(f"Type              : {handoff.handoff_type}")
    print(f"Status            : {handoff.status}")
    print(f"Scope             : {handoff.implementation_scope}")
    print(f"Target            : {handoff.target_type}/{handoff.target_name}")
    print(f"Target loop type  : {handoff.target_loop_type}")
    print(f"Target workspace  : {handoff.target_workspace}")
    print(f"External coder    : {handoff.external_coder}")
    print(f"Created loop      : {handoff.created_loop_id or '(none)'}")
    print(f"Created job       : {handoff.created_external_job_id or '(none)'}")
    print(f"Packet path       : {handoff.packet_path or '(none)'}")
    print(f"Dry run           : {handoff.dry_run}")
    print(f"Created at        : {handoff.created_at}")
    _rule("GENERATED TASK")
    print(handoff.generated_task)
    _rule("SUGGESTED COMMAND")
    print(handoff.suggested_command)
    _rule("SAFETY NOTES")
    for note in handoff.safety_notes:
        print(f"- {note}")
    events = database.get_loop_improvement_handoff_events(conn, handoff.id)
    _rule("EVENTS")
    if not events:
        print("(none)")
    for event in events:
        print(f"- {event['created_at']} {event['event_type']} {event['details_json']}")


def _cmd_loop_improvement_handoffs(args) -> int:
    limit = 20
    if "--limit" in args:
        try:
            limit = int(_flag_val(args, "--limit"))
        except (TypeError, ValueError):
            print("ERROR: --limit needs an integer", file=sys.stderr)
            return 1
    conn = database.init_db()
    rows = database.list_loop_improvement_handoffs(conn, limit)
    _rule(f"LOOP IMPROVEMENT HANDOFFS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for row in rows:
        print(f"#{row['id']} action={row['action_id']} proposal={row['source_proposal_id']} "
              f"type={row['handoff_type']} status={row['status']} "
              f"scope={row['implementation_scope']} dry_run={bool(row['dry_run'])}")
        print(f"    target: {row['target_type']}/{row['target_name']}")
        if row["packet_path"]:
            print(f"    packet: {row['packet_path']}")
    return 0


def _cmd_loop_improvement_handoff(args) -> int:
    if not args:
        print("ERROR: --loop-improvement-handoff needs a HANDOFF_ID", file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        handoff_id = _parse_id_or_latest(
            conn, args[0], _latest_loop_improvement_handoff_id,
            "loop improvement handoff")
    except (ValueError, TypeError):
        print("ERROR: HANDOFF_ID must be an integer or 'latest'", file=sys.stderr)
        return 1
    row = database.get_loop_improvement_handoff(conn, handoff_id)
    if row is None:
        print(f"ERROR: no loop improvement handoff {args[0]}", file=sys.stderr)
        return 1
    _print_loop_improvement_handoff(loop_improvement_handoff.handoff_from_row(row), conn)
    return 0


def _loop_improvement_handoff_review_filters(args):
    limit = 25
    if "--limit" in args:
        val = _flag_val(args, "--limit")
        if not val:
            raise ValueError("--limit needs an integer")
        limit = int(val)
    return {
        "status": _flag_val(args, "--status"),
        "handoff_type": _flag_val(args, "--type"),
        "implementation_scope": _flag_val(args, "--implementation-scope"),
        "target_type": _flag_val(args, "--target-type"),
        "workspace": _flag_val(args, "--workspace"),
        "external_coder": _flag_val(args, "--external-coder"),
        "group_by": _flag_val(args, "--group-by") or "status",
        "limit": limit,
    }


def _print_loop_improvement_handoff_review(report, review_id=None,
                                           markdown_path=None):
    filters = json.loads(report.filters_json or "{}")
    _rule("LOOP IMPROVEMENT HANDOFF REVIEW")
    if review_id is not None:
        print(f"Review ID          : {review_id}")
    if markdown_path:
        print(f"Markdown report    : {markdown_path}")
    _rule("SUMMARY")
    print(f"Generated at       : {report.generated_at}")
    print(f"Handoffs reviewed  : {report.total_handoffs_reviewed}")
    print(f"Filters            : {report.filters_json}")
    print(f"Group by           : {filters.get('group_by', 'status')}")
    _rule("GROUPS")
    if not report.groups:
        print("(none)")
    for group in report.groups:
        print(f"- type={group.group_type} key={group.group_key} count={group.count}")
        print(f"  handoffs : {group.handoff_ids}")
        print(f"  risk     : {group.highest_risk}")
        print(f"  summary  : {group.summary}")
        print(f"  next     : {group.recommended_next_step}")
    _rule("HANDOFFS")
    if not report.items:
        print("(none)")
    for item in report.items:
        print(f"- handoff #{item.handoff_id} action=#{item.action_id} "
              f"proposal={item.source_proposal_id} type={item.handoff_type}")
        print(f"  status/review : {item.status} / {item.review_status}")
        print(f"  score/risk    : {item.review_score} / {item.risk_level}")
        print(f"  scope         : {item.implementation_scope}")
        print(f"  target        : {item.target_type}/{item.target_name}")
        print(f"  workspace     : {item.target_workspace}")
        print(f"  external      : {item.external_coder or '(none)'}")
        print(f"  created loop  : {item.created_loop_id or '(none)'}")
        print(f"  created job   : {item.created_external_job_id or '(none)'}")
        print(f"  packet        : {item.packet_path or '(none)'}")
        print(f"  task preview  : {item.generated_task_preview}")
        print(f"  rationale     : {item.rationale}")
        print(f"  decision      : {item.recommended_decision}")
        print(f"  command       : {item.recommended_next_command}")
    _rule("NEXT STEPS")
    if not report.next_steps:
        print("(none)")
    for step in report.next_steps:
        print(f"- {step}")


def _loop_improvement_handoff_review_markdown_path_display(path):
    if not path:
        return "(none)"
    if not loop_improvement_handoff_review.is_markdown_report_path(path):
        return f"invalid handoff review report path metadata: {path}"
    if not os.path.exists(path):
        return f"missing handoff review report path: {path}"
    return path


def _cmd_loop_improvement_handoff_review(args) -> int:
    try:
        filters = _loop_improvement_handoff_review_filters(args)
    except (ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    save_report = "--save-report" in args
    conn = database.init_db()
    engine = loop_improvement_handoff_review.LoopImprovementHandoffReviewEngine(conn)
    try:
        report = engine.build_report(**filters)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    review_id = engine.save_review(report, group_by=filters["group_by"])
    markdown_path = None
    if save_report:
        try:
            md = engine.save_markdown_report(review_id, report)
            markdown_path = md.report_path
        except Exception as exc:
            print(f"ERROR: loop improvement handoff review markdown failed: {exc}",
                  file=sys.stderr)
            return 1
    _print_loop_improvement_handoff_review(
        report, review_id=review_id, markdown_path=markdown_path)
    return 0


def _latest_loop_improvement_handoff_review_id(conn):
    rows = database.list_loop_improvement_handoff_reviews(conn, 1)
    return rows[0]["id"] if rows else None


def _cmd_loop_improvement_handoff_reviews(args) -> int:
    limit = 20
    if "--limit" in args:
        try:
            limit = int(_flag_val(args, "--limit"))
        except (TypeError, ValueError):
            print("ERROR: --limit needs an integer", file=sys.stderr)
            return 1
    conn = database.init_db()
    rows = database.list_loop_improvement_handoff_reviews(conn, limit)
    _rule(f"LOOP IMPROVEMENT HANDOFF REVIEWS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for row in rows:
        md = database.get_loop_improvement_handoff_review_markdown_report(
            conn, row["id"])
        print(f"#{row['id']} {row['generated_at']} "
              f"handoffs={row['total_handoffs_reviewed']} group_by={row['group_by']}")
        print(f"    filters: {row['filters_json']}")
        if md is not None:
            print(
                "    markdown: "
                f"{_loop_improvement_handoff_review_markdown_path_display(md['report_path'])}"
            )
    return 0


def _cmd_loop_improvement_handoff_review_show(args) -> int:
    if not args:
        print("ERROR: --loop-improvement-handoff-review-show needs a REVIEW_ID",
              file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        review_id = _parse_id_or_latest(
            conn, args[0], _latest_loop_improvement_handoff_review_id,
            "loop improvement handoff review")
    except (ValueError, TypeError):
        print("ERROR: REVIEW_ID must be an integer or 'latest'", file=sys.stderr)
        return 1
    row = database.get_loop_improvement_handoff_review(conn, review_id)
    if row is None:
        print(f"ERROR: no loop improvement handoff review {args[0]}",
              file=sys.stderr)
        return 1
    report = loop_improvement_handoff_review.report_from_row(row)
    md = database.get_loop_improvement_handoff_review_markdown_report(conn, row["id"])
    _print_loop_improvement_handoff_review(
        report,
        review_id=row["id"],
        markdown_path=(
            _loop_improvement_handoff_review_markdown_path_display(md["report_path"])
            if md else None
        ),
    )
    return 0


def _latest_loop_improvement_stage5_audit_id(conn):
    rows = database.list_loop_improvement_stage5_audits(conn, 1)
    return rows[0]["id"] if rows else None


def _loop_improvement_stage5_audit_markdown_path_display(path):
    if not path:
        return "(none)"
    if not loop_improvement_stage5_audit.is_markdown_report_path(path):
        return f"invalid Stage 5 audit report path metadata: {path}"
    if not os.path.exists(path):
        return f"missing Stage 5 audit report path: {path}"
    return path


def _print_loop_improvement_stage5_audit(report, audit_id=None,
                                         markdown_path=None):
    _rule("STAGE 5 LOOP IMPROVEMENT AUDIT")
    if audit_id is not None:
        print(f"Audit ID          : {audit_id}")
    if markdown_path:
        print(f"Markdown report   : {markdown_path}")
    readiness = report.stage6_readiness or {}
    _rule("SUMMARY")
    print(f"Generated at      : {report.generated_at}")
    print(f"Overall status    : {report.overall_status}")
    print(f"Total checks      : {report.total_checks}")
    print(f"Passed            : {report.passed_checks}")
    print(f"Warnings          : {report.warning_checks}")
    print(f"Failed            : {report.failed_checks}")
    print(f"Stage 6 readiness : {readiness.get('ready_text', 'no')}")

    _rule("SECTIONS")
    if not report.sections:
        print("(none)")
    for section in report.sections:
        print(f"- {section.name}: {section.status}")
        print(f"  summary: {section.summary}")
        for check in section.checks:
            print(f"  [{check.status}] {check.name}")
            print(f"    message : {check.message}")
            print(f"    evidence: {check.evidence}")
            if check.recommended_action:
                print(f"    action  : {check.recommended_action}")

    _rule("RECOMMENDATIONS")
    if not report.recommendations:
        print("(none)")
    for rec in report.recommendations:
        print(f"- {rec}")

    _rule("STAGE 6 READINESS")
    print(f"ready                : {readiness.get('ready_text', 'no')}")
    blockers = readiness.get("blockers") or []
    warnings = readiness.get("warnings") or []
    print("blockers:")
    if not blockers:
        print("- (none)")
    for blocker in blockers:
        print(f"- {blocker}")
    print("warnings:")
    if not warnings:
        print("- (none)")
    for warning in warnings:
        print(f"- {warning}")
    print(f"recommended next stage: {readiness.get('recommended_next_stage', '')}")
    print("required Stage 6 safety controls:")
    controls = readiness.get("required_safety_controls") or []
    if not controls:
        print("- (none)")
    for control in controls:
        print(f"- {control}")


def _cmd_loop_improvement_stage5_audit(args) -> int:
    save_report = "--save-report" in args
    conn = database.init_db()
    engine = loop_improvement_stage5_audit.LoopImprovementStage5AuditEngine(conn)
    try:
        report = engine.build_report()
        audit_id = engine.save_audit(report)
        markdown_path = None
        if save_report:
            md = engine.save_markdown_report(audit_id, report)
            markdown_path = md.report_path
    except Exception as exc:
        print(f"ERROR: Stage 5 audit failed: {exc}", file=sys.stderr)
        return 1
    _print_loop_improvement_stage5_audit(
        report, audit_id=audit_id, markdown_path=markdown_path)
    return 0


def _cmd_loop_improvement_stage5_audits(args) -> int:
    limit = 20
    if "--limit" in args:
        try:
            limit = int(_flag_val(args, "--limit"))
        except (TypeError, ValueError):
            print("ERROR: --limit needs an integer", file=sys.stderr)
            return 1
    conn = database.init_db()
    rows = database.list_loop_improvement_stage5_audits(conn, limit)
    _rule(f"STAGE 5 LOOP IMPROVEMENT AUDITS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for row in rows:
        md = database.get_loop_improvement_stage5_audit_markdown_report(
            conn, row["id"])
        print(f"#{row['id']}  {row['generated_at']}  status={row['overall_status']} "
              f"checks={row['total_checks']} pass={row['passed_checks']} "
              f"warn={row['warning_checks']} fail={row['failed_checks']}")
        if md is not None:
            print(
                "    markdown: "
                f"{_loop_improvement_stage5_audit_markdown_path_display(md['report_path'])}"
            )
    return 0


def _cmd_loop_improvement_stage5_audit_show(args) -> int:
    if not args:
        print("ERROR: --loop-improvement-stage5-audit-show needs an AUDIT_ID",
              file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        audit_id = _parse_id_or_latest(
            conn, args[0], _latest_loop_improvement_stage5_audit_id,
            "loop improvement Stage 5 audit")
    except (ValueError, TypeError):
        print("ERROR: AUDIT_ID must be an integer or 'latest'", file=sys.stderr)
        return 1
    row = database.get_loop_improvement_stage5_audit(conn, audit_id)
    if row is None:
        print(f"ERROR: no loop improvement Stage 5 audit {args[0]}",
              file=sys.stderr)
        return 1
    report = loop_improvement_stage5_audit.report_from_row(row)
    md = database.get_loop_improvement_stage5_audit_markdown_report(conn, row["id"])
    _print_loop_improvement_stage5_audit(
        report,
        audit_id=row["id"],
        markdown_path=(
            _loop_improvement_stage5_audit_markdown_path_display(md["report_path"])
            if md else None
        ),
    )
    return 0


def _latest_loop_improvement_application_plan_id(conn):
    rows = database.list_loop_improvement_application_plans(conn, 1)
    return rows[0]["id"] if rows else None


def _latest_loop_improvement_application_source_id(conn, source_type):
    if source_type == "action":
        return _latest_improvement_action_id(conn)
    if source_type == "handoff":
        return _latest_loop_improvement_handoff_id(conn)
    if source_type == "handoff_review":
        return _latest_loop_improvement_handoff_review_id(conn)
    raise ValueError(f"unknown application plan source type '{source_type}'")


def _application_plan_markdown_path_display(path):
    if not path:
        return "(none)"
    if not loop_improvement_application_planner.is_markdown_report_path(path):
        return f"invalid application plan report path metadata: {path}"
    if not os.path.exists(path):
        return f"missing application plan report path: {path}"
    return path


def _print_loop_improvement_application_plan(plan, plan_id=None,
                                             markdown_path=None):
    _rule("LOOP IMPROVEMENT APPLICATION PLAN")
    if plan_id is not None:
        print(f"Application Plan ID : {plan_id}")
    if markdown_path:
        print(f"Markdown report     : {markdown_path}")
    print(f"Generated at        : {plan.generated_at}")
    print(f"Source              : {plan.source_type} #{plan.source_id}")
    print(f"Status              : {plan.status}")
    print(f"Total items         : {plan.total_items}")
    print(f"Generates patch     : {plan.generates_patch}")
    print(f"Applies changes     : {plan.applies_changes}")
    print(f"Risk assessment     : {plan.risk_assessment}")

    _rule("TARGET FILES")
    if not plan.target_files:
        print("(none)")
    for path in plan.target_files:
        print(f"- {path}")

    _rule("PATCH INTENT")
    print(plan.patch_intent_summary or "(none)")

    _rule("ITEMS")
    if not plan.items:
        print("(none)")
    for item in plan.items:
        print(f"- action #{item.source_action_id} "
              f"handoff={item.source_handoff_id or '(none)'} "
              f"{item.target_type}/{item.target_name}")
        print(f"  risk   : {item.risk_level}")
        print(f"  files  : {', '.join(item.target_files) or '(none)'}")
        print(f"  intent : {item.patch_intent_summary}")

    _rule("REQUIRED APPROVALS")
    for approval in plan.required_approvals:
        print(f"- {approval}")

    _rule("ROLLBACK REQUIREMENTS")
    for requirement in plan.rollback_requirements:
        print(f"- {requirement}")

    _rule("VALIDATION REQUIREMENTS")
    for requirement in plan.validation_requirements:
        print(f"- {requirement}")

    _rule("SAFETY")
    for note in plan.safety_notes:
        print(f"- {note}")

    _rule("RECOMMENDED NEXT COMMANDS")
    for command in plan.recommended_next_commands:
        if plan_id is not None:
            command = command.replace("PLAN_ID", str(plan_id))
        print(f"- {command}")


def _cmd_plan_loop_improvement_application(args) -> int:
    if not args:
        print("ERROR: --plan-loop-improvement-application needs a SOURCE_ID",
              file=sys.stderr)
        return 1
    source_type = _flag_val(args, "--source-type") or "action"
    if source_type not in loop_improvement_application_planner.SOURCE_TYPES:
        print("ERROR: --source-type must be action, handoff, or handoff_review",
              file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        source_id = _parse_id_or_latest(
            conn,
            args[0],
            lambda c: _latest_loop_improvement_application_source_id(c, source_type),
            f"loop improvement {source_type}",
        )
    except (ValueError, TypeError):
        print("ERROR: SOURCE_ID must be an integer or 'latest'", file=sys.stderr)
        return 1
    engine = loop_improvement_application_planner.LoopImprovementApplicationPlanner(conn)
    try:
        plan = engine.build_plan(source_type=source_type, source_id=source_id)
        plan_id = engine.save_plan(plan)
        markdown_path = None
        if "--save-report" in args:
            md = engine.save_markdown_report(plan_id, plan)
            markdown_path = md.report_path
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: loop improvement application planning failed: {exc}",
              file=sys.stderr)
        return 1
    _print_loop_improvement_application_plan(
        plan, plan_id=plan_id, markdown_path=markdown_path)
    return 0


def _cmd_loop_improvement_application_plans(args) -> int:
    limit = 20
    if "--limit" in args:
        try:
            limit = int(_flag_val(args, "--limit"))
        except (TypeError, ValueError):
            print("ERROR: --limit needs an integer", file=sys.stderr)
            return 1
    conn = database.init_db()
    rows = database.list_loop_improvement_application_plans(conn, limit)
    _rule(f"LOOP IMPROVEMENT APPLICATION PLANS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for row in rows:
        md = database.get_loop_improvement_application_plan_markdown_report(
            conn, row["id"])
        print(f"#{row['id']}  {row['generated_at']}  "
              f"source={row['source_type']}:{row['source_id']} "
              f"status={row['status']} items={row['total_items']} "
              f"generates_patch={bool(row['generates_patch'])} "
              f"applies_changes={bool(row['applies_changes'])}")
        print(f"    targets: {row['target_files_json']}")
        if md is not None:
            print(
                "    markdown: "
                f"{_application_plan_markdown_path_display(md['report_path'])}"
            )
    return 0


def _cmd_loop_improvement_application_plan(args) -> int:
    if not args:
        print("ERROR: --loop-improvement-application-plan needs a PLAN_ID",
              file=sys.stderr)
        return 1
    conn = database.init_db()
    try:
        plan_id = _parse_id_or_latest(
            conn,
            args[0],
            _latest_loop_improvement_application_plan_id,
            "loop improvement application plan",
        )
    except (ValueError, TypeError):
        print("ERROR: PLAN_ID must be an integer or 'latest'", file=sys.stderr)
        return 1
    row = database.get_loop_improvement_application_plan(conn, plan_id)
    if row is None:
        print(f"ERROR: no loop improvement application plan {args[0]}",
              file=sys.stderr)
        return 1
    plan = loop_improvement_application_planner.plan_from_row(row)
    md = database.get_loop_improvement_application_plan_markdown_report(conn, row["id"])
    _print_loop_improvement_application_plan(
        plan,
        plan_id=row["id"],
        markdown_path=(
            _application_plan_markdown_path_display(md["report_path"])
            if md else None
        ),
    )
    return 0


def _cmd_archive_external_job(args, unarchive=False) -> int:
    import external_agent_jobs as eaj
    if not args:
        print(f"ERROR: --{'un' if unarchive else ''}archive-external-job needs a JOB_ID",
              file=sys.stderr)
        return 1
    try:
        job_id = int(args[0])
    except ValueError:
        print("ERROR: JOB_ID must be an integer", file=sys.stderr)
        return 1
    conn = database.init_db()
    mgr = eaj.ExternalAgentJobManager(conn)
    if mgr.get_job(job_id) is None:
        print(f"ERROR: no external agent job with id {job_id}", file=sys.stderr)
        return 1
    if unarchive:
        mgr.unarchive_job(job_id)
        print(f"job #{job_id} unarchived")
    else:
        mgr.archive_job(job_id)
        print(f"job #{job_id} archived (files preserved; unarchive to resume)")
    return 0


def _cmd_set_external_job_priority(args) -> int:
    import external_agent_jobs as eaj
    if len(args) < 2:
        print("ERROR: usage: --set-external-job-priority JOB_ID PRIORITY", file=sys.stderr)
        return 1
    try:
        job_id = int(args[0])
    except ValueError:
        print("ERROR: JOB_ID must be an integer", file=sys.stderr)
        return 1
    conn = database.init_db()
    mgr = eaj.ExternalAgentJobManager(conn)
    if mgr.get_job(job_id) is None:
        print(f"ERROR: no external agent job with id {job_id}", file=sys.stderr)
        return 1
    pr = mgr.update_job_priority(job_id, args[1])
    print(f"job #{job_id} priority -> {pr}")
    return 0


def _cmd_set_external_job_labels(args) -> int:
    import external_agent_jobs as eaj
    if len(args) < 2:
        print("ERROR: usage: --set-external-job-labels JOB_ID a,b,c", file=sys.stderr)
        return 1
    try:
        job_id = int(args[0])
    except ValueError:
        print("ERROR: JOB_ID must be an integer", file=sys.stderr)
        return 1
    conn = database.init_db()
    mgr = eaj.ExternalAgentJobManager(conn)
    if mgr.get_job(job_id) is None:
        print(f"ERROR: no external agent job with id {job_id}", file=sys.stderr)
        return 1
    lbls = mgr.update_job_labels(job_id, args[1])
    print(f"job #{job_id} labels -> {', '.join(lbls) or '(none)'}")
    return 0


def _cmd_set_external_job_notes(args) -> int:
    import external_agent_jobs as eaj
    if len(args) < 2:
        print("ERROR: usage: --set-external-job-notes JOB_ID \"notes\"", file=sys.stderr)
        return 1
    try:
        job_id = int(args[0])
    except ValueError:
        print("ERROR: JOB_ID must be an integer", file=sys.stderr)
        return 1
    conn = database.init_db()
    mgr = eaj.ExternalAgentJobManager(conn)
    if mgr.get_job(job_id) is None:
        print(f"ERROR: no external agent job with id {job_id}", file=sys.stderr)
        return 1
    mgr.update_job_notes(job_id, args[1])
    print(f"job #{job_id} notes updated")
    return 0


def _cmd_external_dashboard(args) -> int:
    import external_agent_dashboard as dash
    conn = database.init_db()
    workspace = _flag_val(args, "--workspace")
    agent = _flag_val(args, "--agent")
    archived = True if "--archived" in args else (False if "--active" in args else None)
    renderer = dash.ExternalJobDashboardRenderer(conn)
    summary = renderer.render(workspace=workspace, agent=agent, archived=archived)
    health_events = database.list_external_job_health_events(conn, 20)
    if health_events:
        sev = {}
        pending = 0
        critical = 0
        for h in health_events:
            sev[h["severity"]] = sev.get(h["severity"], 0) + 1
            if h["issue_type"] == "completion_waiting_import":
                pending += 1
            if h["severity"] == "critical":
                critical += 1
        _rule("HEALTH SUMMARY (latest persisted events)")
        print(f"events shown : {len(health_events)}")
        print(f"warnings     : {sev.get('warning', 0)}")
        print(f"errors       : {sev.get('error', 0)}")
        print(f"critical     : {critical}")
        print(f"pending completions: {pending}")
        print("refresh      : python3 main.py --external-health")
    # Record dashboard metrics on the most recent EXISTING job's loop (never
    # create a loop just to view the dashboard).
    newest = summary.newest
    if newest is not None and newest.loop_id is not None:
        rec = database.LoopRecorder(conn, newest.loop_id)
        rec.save_metric("external_dashboard_viewed", 1, "bool")
        rec.save_metric("external_jobs_needing_attention_count",
                        summary.needing_attention, "count")
        rec.save_metric("external_jobs_stale_count", summary.stale, "count")
    return 0


def _cmd_external_inbox(args) -> int:
    import external_completion_inbox as inbox
    conn = database.init_db()
    sc = inbox.ExternalCompletionInboxScanner(conn)
    status = _flag_val(args, "--status")
    include_imported = "--include-imported" in args
    items = sc.scan_inbox(status=status, include_imported=include_imported)
    pending = [i for i in items if i.exists and not i.imported
               and not i.archived and not i.cancelled and i.error is None]
    _rule(f"EXTERNAL COMPLETION INBOX ({len(items)} item(s), {len(pending)} pending)")
    if not items:
        print("(no completion files found in external_agent_jobs/job_*/ )")
    for it in items:
        flags = []
        if it.imported:
            flags.append("imported")
        if it.archived:
            flags.append("archived")
        if it.cancelled:
            flags.append("cancelled")
        if it.ignored_txt:
            flags.append("completion.txt IGNORED (json preferred)")
        if it.error:
            flags.append(f"ERROR: {it.error}")
        print(f"job #{it.job_id}  loop=#{it.loop_id}  {it.agent_name}  "
              f"[{it.job_status}]  type={it.completion_type or '-'}  "
              f"parseable={it.parseable}{(' | ' + ', '.join(flags)) if flags else ''}")
        print(f"    completion: {it.completion_path or '(none)'}")
        if it.exists and not it.imported and not it.archived and not it.cancelled and not it.error:
            print(f"    sync: python3 main.py --sync-external-completion {it.job_id}")
    # Metrics on the newest affected loop (never a new loop).
    if items and items[0].loop_id is not None:
        rec = database.LoopRecorder(conn, items[0].loop_id)
        rec.save_metric("external_completion_inbox_scanned", 1, "bool")
        rec.save_metric("external_completion_inbox_pending_count", len(pending), "count")
    return 0


def _print_sync_result(r):
    if r.get("status") == "dry_run":
        print(f"  job #{r['job_id']}: WOULD import {r.get('completion_type')} "
              f"completion (dry-run, not resumed)")
    elif r.get("status") == "skipped":
        print(f"  job #{r['job_id']}: skipped ({r.get('error')})")
    elif r.get("status") == "failed":
        print(f"  job #{r['job_id']}: FAILED ({r.get('error')}) — not resumed")
    else:
        print(f"  job #{r['job_id']}: imported -> resume {r.get('status')} "
              f"(job status {r.get('job_status')})")
        if r.get("report_path"):
            print(f"    report: {r['report_path']}")


def _cmd_sync_external_completions(args) -> int:
    import external_completion_inbox as inbox
    conn = database.init_db()
    sc = inbox.ExternalCompletionInboxScanner(conn)
    dry_run = "--dry-run" in args
    limit = 20
    lv = _flag_val(args, "--limit")
    if lv:
        try:
            limit = int(lv)
        except ValueError:
            pass
    _rule(f"SYNC EXTERNAL COMPLETIONS{' (DRY RUN)' if dry_run else ''}")
    results = sc.import_all_pending(limit=limit, dry_run=dry_run)
    if not results:
        print("  (no pending completions)")
    for r in results:
        _print_sync_result(r)
    imported = sum(1 for r in results if r.get("imported"))
    failed = sum(1 for r in results if r.get("status") == "failed")
    # Record sync metrics per affected loop.
    for r in results:
        if r.get("loop_id") is not None and not dry_run:
            rec = database.LoopRecorder(conn, r["loop_id"])
            rec.save_metric("external_completion_inbox_imported_count",
                            1 if r.get("imported") else 0, "count")
            rec.save_metric("external_completion_inbox_failed_count",
                            1 if r.get("status") == "failed" else 0, "count")
    print(f"\n{imported} imported, {failed} failed, {len(results)} processed"
          f"{' (dry-run)' if dry_run else ''}.")
    return 0


def _cmd_sync_external_completion(args) -> int:
    import external_completion_inbox as inbox
    if not args:
        print("ERROR: --sync-external-completion needs a JOB_ID", file=sys.stderr)
        return 1
    try:
        job_id = int(args[0])
    except ValueError:
        print("ERROR: JOB_ID must be an integer", file=sys.stderr)
        return 1
    dry_run = "--dry-run" in args
    conn = database.init_db()
    if database.get_external_agent_job(conn, job_id) is None:
        print(f"ERROR: no external agent job with id {job_id}", file=sys.stderr)
        return 1
    sc = inbox.ExternalCompletionInboxScanner(conn)
    _rule(f"SYNC EXTERNAL COMPLETION job #{job_id}{' (DRY RUN)' if dry_run else ''}")
    r = sc.import_completion_for_job(job_id, dry_run=dry_run)
    _print_sync_result(r)
    return 0 if r.get("status") in ("APPROVED", "dry_run") else (
        2 if r.get("status") in ("failed", "skipped") else 0)


def _cmd_batch_external_jobs(args) -> int:
    import external_job_batch as batch
    conn = database.init_db()
    action = _flag_val(args, "--action")
    if not action:
        print("ERROR: --batch-external-jobs needs --action", file=sys.stderr)
        return 1
    job_ids = None
    jids_raw = _flag_val(args, "--job-ids")
    if jids_raw:
        try:
            job_ids = [int(x) for x in jids_raw.split(",") if x.strip()]
        except ValueError:
            print("ERROR: --job-ids must be a comma-separated list of integers",
                  file=sys.stderr)
            return 1
    archived = True if "--archived" in args else (False if "--active" in args else None)
    limit = 100
    lv = _flag_val(args, "--limit")
    if lv:
        try:
            limit = int(lv)
        except ValueError:
            pass
    req = batch.ExternalJobBatchRequest(
        action=action, job_ids=job_ids,
        status_filter=_flag_val(args, "--status"),
        agent_filter=_flag_val(args, "--agent"),
        workspace_filter=_flag_val(args, "--workspace"),
        priority_filter=_flag_val(args, "--priority") if action != "set_priority" else None,
        label_filter=_flag_val(args, "--label") if action not in ("add_label", "remove_label") else None,
        archived=archived, dry_run="--dry-run" in args, limit=limit,
        priority=_flag_val(args, "--priority"),
        label=_flag_val(args, "--label"),
        labels=_flag_val(args, "--labels"), created_at="")

    mgr = batch.ExternalJobBatchManager(conn)
    result = mgr.run(req)

    _rule("EXTERNAL JOB BATCH")
    print(f"Batch ID    : {result.batch_id}")
    print(f"Action      : {result.action}")
    print(f"Dry run     : {'yes' if result.dry_run else 'no'}")
    filt = ", ".join(f for f in [
        f"job_ids={job_ids}" if job_ids else "",
        f"status={req.status_filter}" if req.status_filter else "",
        f"agent={req.agent_filter}" if req.agent_filter else "",
        f"workspace={req.workspace_filter}" if req.workspace_filter else "",
        f"priority={req.priority_filter}" if req.priority_filter else "",
        f"label={req.label_filter}" if req.label_filter else "",
        "archived" if archived is True else ("active" if archived is False else "")]
        if f)
    print(f"Filters     : {filt or '(none)'}")

    if not result.valid_selection:
        print(f"\nINVALID BATCH: {result.invalid_reason} (external_job_batch_invalid)")
        # Record the stop condition + failed gate on any resolvable job loops.
        for jid in (job_ids or []):
            j = database.get_external_agent_job(conn, jid)
            if j is not None and j["loop_id"] is not None:
                rec = database.LoopRecorder(conn, j["loop_id"])
                rec.save_stop_condition_result(0, "external_job_batch_invalid", True,
                                               "high", result.invalid_reason)
                rec.save_quality_gate_result(0, "external_job_batch_selection_valid",
                                             False, True, "error", result.invalid_reason)
        return 2

    print(f"Total selected: {result.total_selected}")
    print(f"Success     : {result.total_success}")
    print(f"Skipped     : {result.total_skipped}")
    print(f"Failed      : {result.total_failed}")
    print(f"\n{'JOB':>5}  {'LOOP':>5}  {'BEFORE':<24}  {'AFTER':<24}  RESULT")
    for it in result.item_results:
        verdict = "skipped" if it.skipped else ("ok" if it.success else "FAILED")
        print(f"{it.job_id:>5}  {str(it.loop_id):>5}  {str(it.status_before):<24}  "
              f"{str(it.status_after):<24}  {verdict}"
              f"{('  ' + it.error) if it.error else ''}")

    # Quality gates + metrics on each affected EXISTING loop (never a new loop).
    sync_like = req.action in batch.SYNC_ACTIONS
    for it in result.item_results:
        if it.loop_id is None:
            continue
        rec = database.LoopRecorder(conn, it.loop_id)
        rec.save_quality_gate_result(
            0, "external_job_batch_selection_valid", True, True, "info",
            f"selection valid for action {result.action}")
        rec.save_quality_gate_result(
            0, "external_job_batch_action_safe", True, True, "info",
            "dry-run safe; no deletes; no agent exec; ResumeEngine used for sync"
            if not result.dry_run else "dry-run: no changes")
        rec.save_metric("external_batch_action_used", 1, "bool")
        rec.save_metric("external_batch_action", None, "string", metric_text=result.action)
        rec.save_metric("external_batch_success", 1 if it.success and not it.skipped else 0, "bool")
        rec.save_metric("external_batch_skipped", 1 if it.skipped else 0, "bool")
        rec.save_metric("external_batch_failed", 1 if (not it.success and not it.skipped) else 0, "bool")

    # Stage 3.8: always generate a durable Markdown batch report (incl. dry-run).
    import external_batch_reports as ebr
    gen = ebr.ExternalBatchReportGenerator(conn)
    report = None
    try:
        content = gen.generate_batch_report(result.batch_id, req=req, result=result)
        report = gen.save_batch_report(result.batch_id, content, action=result.action,
                                       dry_run=result.dry_run)
        print(f"\nBatch report: {report.report_path} ({report.bytes_written} bytes)")
    except Exception as exc:
        print(f"\nWARNING: batch report generation failed: {exc} "
              "(external_batch_report_failed) — batch result above is unchanged.",
              file=sys.stderr)
    for it in result.item_results:
        if it.loop_id is None:
            continue
        rec = database.LoopRecorder(conn, it.loop_id)
        if report is not None:
            within = report.report_path.startswith(ebr.REPORTS_DIR + os.sep)
            ok = within and bool(report.content_hash)
            rec.save_quality_gate_result(
                0, "external_batch_report_generated", ok, True,
                "info" if ok else "error",
                "batch report written inside external_batch_reports/ with hash"
                if ok else "batch report path/hash invalid")
            rec.save_metric("external_batch_report_generated", 1, "bool")
            rec.save_metric("external_batch_report_bytes", report.bytes_written, "bytes")
            rec.save_metric("external_batch_report_path", None, "string",
                            metric_text=report.report_path)
        else:
            rec.save_stop_condition_result(
                0, "external_batch_report_failed", True, "warning",
                "batch report generation failed (batch result unchanged)")
            rec.save_metric("external_batch_report_generated", 0, "bool")
    return 0 if result.total_failed == 0 else 2


def _cmd_external_batch_reports(args) -> int:
    import external_batch_reports as ebr
    conn = database.init_db()
    rows = ebr.ExternalBatchReportGenerator(conn).list_batch_reports(20)
    _rule(f"EXTERNAL BATCH REPORTS ({len(rows)})")
    if not rows:
        print("(none)")
        return 0
    for r in rows:
        print(f"{r['batch_id']}  action={r['action']}  {r['created_at']}  "
              f"{r['bytes_written']} bytes")
        print(f"    {_report_path_display(r['report_path'])}")
    return 0


def _cmd_external_batch_report(args) -> int:
    import external_batch_reports as ebr
    if not args:
        print("ERROR: --external-batch-report needs a BATCH_ID", file=sys.stderr)
        return 1
    batch_id = args[0]
    conn = database.init_db()
    gen = ebr.ExternalBatchReportGenerator(conn)
    row = database.get_external_batch_report(conn, batch_id)
    events = database.get_external_job_batch_events(conn, batch_id=batch_id, limit=10000)
    path = row["report_path"] if row else None
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
        print(f"report path: {path}\n")
        print(content)
        return 0
    # Metadata exists but file missing (or never saved): regenerate from events.
    if not events and row is None:
        print(f"ERROR: no batch report or batch events for {batch_id}", file=sys.stderr)
        return 1
    if not events:
        print(f"ERROR: report file missing and no batch events to regenerate {batch_id}",
              file=sys.stderr)
        return 1
    print(f"(report file missing — regenerating {batch_id} from batch events)")
    content = gen.generate_batch_report(batch_id)
    action = events[0]["action"]
    dry = bool(events[0]["dry_run"])
    report = gen.save_batch_report(batch_id, content, action=action, dry_run=dry)
    print(f"report path: {report.report_path}\n")
    print(content)
    return 0


def _cmd_cancel_external_job(args) -> int:
    import external_agent_jobs as eaj
    if not args:
        print("ERROR: --cancel-external-job needs a JOB_ID", file=sys.stderr)
        return 1
    try:
        job_id = int(args[0])
    except ValueError:
        print("ERROR: JOB_ID must be an integer", file=sys.stderr)
        return 1
    conn = database.init_db()
    job = database.get_external_agent_job(conn, job_id)
    if job is None:
        # external_agent_job_invalid
        print(f"ERROR: no external agent job with id {job_id} "
              "(external_agent_job_invalid)", file=sys.stderr)
        return 1
    mgr = eaj.ExternalAgentJobManager(conn)
    mgr.update_job_status(job_id, eaj.CANCELLED)
    database.update_external_agent_job(conn, job_id, cancelled_at=database._now_iso())
    if job["loop_id"]:
        database.LoopRecorder(conn, job["loop_id"]).save_stop_condition_result(
            0, "external_agent_job_cancelled", True, "high",
            f"job #{job_id} cancelled by user")
    # If the loop is still waiting on this job, reflect the cancellation.
    loop = database.get_loop(conn, job["loop_id"]) if job["loop_id"] else None
    if loop is not None and loop["status"] in ("PAUSED_EXTERNAL_AGENT", "NEEDS_EXTERNAL_AGENT"):
        database.finish_loop(conn, job["loop_id"], "CANCELLED",
                             "external_agent_job_cancelled",
                             loop["retry_count"] or 0, loop["total_duration_seconds"] or 0.0)
        database.save_external_agent_job_event(
            conn, job_id, job["loop_id"], "loop_cancelled",
            loop["status"], "CANCELLED", "{}")
    _rule("CANCEL EXTERNAL JOB")
    print(f"job #{job_id} -> CANCELLED (files preserved at {job['packet_path']})")
    return 0


def _cmd_resume_external_job(args) -> int:
    import external_agent_jobs as eaj
    if not args:
        print("ERROR: --resume-external-job needs a JOB_ID", file=sys.stderr)
        return 1
    try:
        job_id = int(args[0])
    except ValueError:
        print("ERROR: JOB_ID must be an integer", file=sys.stderr)
        return 1
    cfile, ctext = _parse_completion_args(args[1:])
    conn = database.init_db()
    job = database.get_external_agent_job(conn, job_id)
    mgr = eaj.ExternalAgentJobManager(conn)
    if job is None:
        print(f"ERROR: no external agent job with id {job_id} "
              "(external_agent_job_invalid)", file=sys.stderr)
        return 1
    # Archived jobs are not resumable until unarchived (external_agent_job_archived).
    if eaj._truthy(job["archived"] if "archived" in job.keys() else 0):
        if job["loop_id"]:
            database.LoopRecorder(conn, job["loop_id"]).save_stop_condition_result(
                0, "external_agent_job_archived", True, "high",
                f"resume attempted on archived job #{job_id}")
        print(f"ERROR: job #{job_id} is archived; unarchive it first "
              f"(python3 main.py --unarchive-external-job {job_id})", file=sys.stderr)
        return 2
    # external_agent_job_resume_valid gate.
    valid = (job["loop_id"] is not None
             and job["status"] in eaj.RESUMABLE_STATUSES
             and (cfile or ctext or database.get_external_agent_completion(conn, job["loop_id"])))
    if not valid:
        if job["loop_id"]:
            rec = database.LoopRecorder(conn, job["loop_id"])
            rec.save_quality_gate_result(0, "external_agent_job_resume_valid", False,
                                         True, "error", "job not resumable / completion missing")
            rec.save_stop_condition_result(0, "external_agent_job_invalid", True, "high",
                                           f"resume attempted on non-resumable job #{job_id}")
        print(f"ERROR: job #{job_id} is not resumable (status={job['status']}, "
              "completion missing, or no linked loop)", file=sys.stderr)
        return 2
    loop_id = job["loop_id"]
    database.LoopRecorder(conn, loop_id).save_quality_gate_result(
        0, "external_agent_job_resume_valid", True, True, "info",
        "job exists, matches loop, resumable, completion available")
    _rule(f"RESUME EXTERNAL JOB #{job_id}")
    print(f"loop #{loop_id}  agent={job['external_agent_name']}")
    if cfile:
        mgr.mark_completion_imported(job_id, cfile)
    req = resume_mod.ResumeRequest(loop_id=loop_id, completion_file=cfile,
                                   completion_text=ctext)
    res = resume_mod.ResumeEngine().resume(conn, req, resume_type="resume_external_job",
                                           on_event=lambda m: print(f"  {m}"))
    # Map the resume outcome onto the job status.
    status_map = {"APPROVED": eaj.APPROVED, "BLOCKED": eaj.BLOCKED,
                  "REJECTED": eaj.REVIEWED, "REVIEW_INCONSISTENT": eaj.REVIEWED,
                  "FAILED": eaj.FAILED}
    mgr.update_job_status(job_id, status_map.get(res.status, eaj.REVIEWED))
    if res.status == "APPROVED":
        database.update_external_agent_job(conn, job_id,
                                           completed_at=database._now_iso())
    elif res.status in ("FAILED", "BLOCKED", "REVIEW_INCONSISTENT"):
        mgr.record_job_error(job_id, f"resume ended {res.status}: {res.stop_reason}")
    return _resume_finish_print(loop_id, res)


def _cmd_context_pack(args) -> int:
    query = None
    workspace_name = None
    max_files = context_packs.DEFAULT_MAX_FILES
    max_chars = context_packs.DEFAULT_MAX_TOTAL_CHARS
    explicit = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--workspace":
            workspace_name = args[i + 1] if i + 1 < len(args) else None; i += 2
        elif a == "--context-max-files":
            try:
                max_files = int(args[i + 1])
            except (ValueError, IndexError):
                pass
            i += 2
        elif a == "--context-max-chars":
            try:
                max_chars = int(args[i + 1])
            except (ValueError, IndexError):
                pass
            i += 2
        elif a == "--context-file":
            if i + 1 < len(args):
                explicit.append(args[i + 1])
            i += 2
        elif query is None and not a.startswith("--"):
            query = a; i += 1
        else:
            i += 1
    if not query:
        print("ERROR: --context-pack needs a task string", file=sys.stderr)
        return 1
    conn = database.init_db()
    ws = project_workspace.WorkspaceManager(conn).get_workspace(workspace_name)
    if ws is None:
        print(f"ERROR: no workspace '{workspace_name}'.", file=sys.stderr)
        return 1
    req = context_packs.ContextPackRequest(
        workspace_name=ws.name, task=query, explicit_paths=explicit,
        max_files=max_files, max_total_chars=max_chars)
    pack = context_packs.ContextPackBuilder(conn).build(req, ws)
    cp_id = database.save_context_pack(conn, pack, None)  # loop_id null (no run)
    _rule(f"CONTEXT PACK — {ws.name} (pack #{cp_id})")
    print(f"task            : {pack.task}")
    print(f"files considered: {pack.total_files_considered}")
    print(f"files included  : {pack.total_files_included}")
    print(f"total chars     : {pack.total_chars}")
    print(f"truncated       : {pack.truncated}")
    print(f"safe            : {pack.safe}")
    print("\nincluded files:")
    for f in pack.files:
        print(f"  [{f.relevance_score:>4.2f}] {f.path} ({f.detected_language}) — "
              f"{f.reason}{' [truncated]' if f.truncated else ''}")
    if pack.warnings:
        print("\nwarnings:")
        for w in pack.warnings:
            print(f"  - {w}")
    return 0


def _cmd_context_packs(args) -> int:
    workspace_name = None
    if "--workspace" in args:
        i = args.index("--workspace")
        if i + 1 < len(args):
            workspace_name = args[i + 1]
    conn = database.init_db()
    rows = database.list_context_packs(conn, workspace_name, 20)
    _rule(f"CONTEXT PACKS (latest {len(rows)})")
    if not rows:
        print("(none)")
        return 0
    print(f"{'ID':>4}  {'LOOP':>5}  {'WS':<14}  {'FILES':>5}  {'CHARS':>6}  TASK")
    for r in rows:
        print(f"{r['id']:>4}  {str(r['loop_id'] or '-'):>5}  "
              f"{str(r['workspace_name']):<14}  {r['total_files_included']:>5}  "
              f"{r['total_chars']:>6}  {(r['task'] or '')[:40]}")
    return 0


def _cmd_memory_search(args) -> int:
    query = None
    workspace_name = None
    limit = 10
    source = "all"
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--workspace":
            workspace_name = args[i + 1] if i + 1 < len(args) else None
            i += 2
        elif a == "--limit":
            try:
                limit = int(args[i + 1])
            except (ValueError, IndexError):
                pass
            i += 2
        elif a == "--source":
            source = args[i + 1] if i + 1 < len(args) else "all"
            i += 2
        elif query is None and not a.startswith("--"):
            query = a
            i += 1
        else:
            i += 1
    if not query:
        print("ERROR: --memory-search needs a query string", file=sys.stderr)
        return 1
    if source not in memory_search.SOURCE_ALIASES:
        print(f"ERROR: --source must be one of {sorted(memory_search.SOURCE_ALIASES)}",
              file=sys.stderr)
        return 1
    conn = database.init_db()
    mq = memory_search.MemorySearchQuery(
        query=query, workspace_name=workspace_name, limit=limit, source_types=[source])
    results = memory_search.MemorySearchEngine(conn).search(mq)
    _rule(f"MEMORY SEARCH — '{query}' (source={source}, {len(results)} results)")
    if not results:
        print("(no matching memory)")
        return 0
    for r in results:
        ws = f" [{r.workspace_name}]" if r.workspace_name else ""
        print(f"  [{r.score:>5.2f}] {r.source_type:<26}{ws} {r.title}")
        print(f"          {r.snippet[:120]}")
    return 0


def _load_project_context(conn, ws):
    """Return (report_id, context_text) for the latest scan of ws, or (None, '')."""
    row = database.get_latest_project_intelligence_report(conn, ws.name)
    if row is None:
        return None, ""
    try:
        rj = json.loads(row["report_json"] or "{}")
    except (ValueError, TypeError):
        return None, ""
    text = project_intelligence.format_project_context(rj, ws.profile_name)
    return row["id"], text


def _cmd_scan_project(args) -> int:
    workspace_name = None
    if "--workspace" in args:
        i = args.index("--workspace")
        if i + 1 < len(args):
            workspace_name = args[i + 1]
    conn = database.init_db()
    ws = project_workspace.WorkspaceManager(conn).get_workspace(workspace_name)
    if ws is None:
        print(f"ERROR: no workspace '{workspace_name}'.", file=sys.stderr)
        return 1
    if project_workspace.WorkspaceManager().validate_workspace(ws):
        print(f"ERROR: workspace '{ws.name}' is invalid; cannot scan.", file=sys.stderr)
        return 1
    report = project_intelligence.ProjectIntelligenceScanner().scan(ws)
    rid = database.save_project_intelligence_report(conn, report)
    s = report.structure_summary
    _rule(f"PROJECT SCAN — {ws.name} (report #{rid})")
    print(f"root            : {s.root_path}")
    print(f"files scanned   : {s.total_files_scanned}")
    print(f"dirs scanned    : {s.total_dirs_scanned}")
    print(f"ignored files   : {s.ignored_files_count}")
    print(f"languages       : {', '.join(s.languages_detected) or '(none)'}")
    print(f"scan safe       : {report.scan_safe}")
    print(f"\nimportant files : {', '.join(s.important_files[:10]) or '(none)'}")
    print(f"test files      : {', '.join(s.test_files[:10]) or '(none)'}")
    print(f"config files    : {', '.join(s.config_files[:10]) or '(none)'}")
    print(f"docs            : {', '.join(s.documentation_files[:10]) or '(none)'}")
    if report.warnings:
        print("\nwarnings:")
        for w in report.warnings:
            print(f"  - {w}")
    if report.recommendations:
        print("\nrecommendations:")
        for r in report.recommendations:
            print(f"  - {r}")
    print(f"\nSaved as report #{rid}. View: python main.py --project-intel-report {rid}")
    return 0


def _cmd_project_intel(args) -> int:
    workspace_name = None
    if "--workspace" in args:
        i = args.index("--workspace")
        if i + 1 < len(args):
            workspace_name = args[i + 1]
    conn = database.init_db()
    ws = project_workspace.WorkspaceManager(conn).get_workspace(workspace_name)
    name = ws.name if ws else (workspace_name or "default")
    row = database.get_latest_project_intelligence_report(conn, name)
    if row is None:
        print(f"No project intelligence for workspace '{name}'. "
              f"Run: python main.py --scan-project"
              f"{' --workspace ' + name if name != 'default' else ''}")
        return 0
    return _print_intel_report(row)


def _cmd_project_intel_report(args) -> int:
    if not args:
        print("ERROR: --project-intel-report needs a REPORT_ID", file=sys.stderr)
        return 1
    try:
        rid = int(args[0])
    except ValueError:
        print("ERROR: REPORT_ID must be an integer", file=sys.stderr)
        return 1
    conn = database.init_db()
    row = database.get_project_intelligence_report(conn, rid)
    if row is None:
        print(f"ERROR: no report #{rid}", file=sys.stderr)
        return 1
    return _print_intel_report(row, full=True)


def _print_intel_report(row, full=False) -> int:
    rj = json.loads(row["report_json"] or "{}")
    st = rj.get("structure", {})
    _rule(f"PROJECT INTELLIGENCE — {row['workspace_name']} (report #{row['id']})")
    print(f"generated_at    : {row['generated_at']}")
    print(f"files scanned   : {st.get('total_files_scanned')}")
    print(f"dirs scanned    : {st.get('total_dirs_scanned')}")
    print(f"ignored files   : {st.get('ignored_files_count')}")
    print(f"languages       : {', '.join(st.get('languages_detected', [])) or '(none)'}")
    print(f"important files : {', '.join(st.get('important_files', [])[:15]) or '(none)'}")
    print(f"test files      : {', '.join(st.get('test_files', [])[:15]) or '(none)'}")
    print(f"config files    : {', '.join(st.get('config_files', [])[:15]) or '(none)'}")
    print(f"docs            : {', '.join(st.get('documentation_files', [])[:15]) or '(none)'}")
    if rj.get("warnings"):
        print("warnings        : " + "; ".join(rj["warnings"]))
    if rj.get("recommendations"):
        print("recommendations : " + "; ".join(rj["recommendations"]))
    if full:
        _rule("TOP FILES")
        for f in rj.get("files", [])[:25]:
            print(f"  [{f['importance_score']:.2f}] {f['file_type']:<7} {f['path']} "
                  f"({f['detected_language']}, {f['line_count']} lines) — {f['reason']}")
    return 0


def _cmd_templates() -> int:
    _rule("LOOP TEMPLATES")
    print(f"{'NAME':<16} {'CATEGORY':<10} {'LOOP_TYPE':<14} DESCRIPTION")
    for t in TEMPLATES.list_templates():
        print(f"{t.name:<16} {t.category:<10} {t.default_loop_type:<14} {t.description}")
    print("\nInspect:  python main.py --template-info <name>")
    print("Run    :  python main.py --template <name> --var key=value ...")
    return 0


def _cmd_template_info(args) -> int:
    if not args:
        print("ERROR: --template-info needs a name", file=sys.stderr)
        return 1
    t = TEMPLATES.get_template(args[0])
    if t is None:
        print(f"ERROR: no template '{args[0]}'. Try: python main.py --templates",
              file=sys.stderr)
        return 1
    _rule(f"TEMPLATE: {t.name}")
    print(f"display_name         : {t.display_name}")
    print(f"description          : {t.description}")
    print(f"version              : {t.version}")
    print(f"category             : {t.category}")
    print(f"default_loop_type    : {t.default_loop_type}")
    print(f"objective_template   : {t.objective_template}")
    print(f"trigger_template     : {t.trigger_template}")
    print(f"recommended_agents   : {t.recommended_agents}")
    print(f"required_variables   : {t.required_variables}")
    print(f"optional_variables   : {t.optional_variables}")
    print(f"default_tools        : {t.default_tools}")
    print(f"default_quality_gates: {t.default_quality_gates}")
    print(f"default_stop_conditions: {t.default_stop_conditions}")
    print(f"safety_level         : {t.safety_level}")
    print(f"tags                 : {t.tags}")
    return 0


def _cmd_template(args) -> int:
    if not args:
        print("ERROR: --template needs a NAME", file=sys.stderr)
        return 1
    name = args[0]
    rest = args[1:]
    variables = {}
    filtered = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--var":
            if i + 1 < len(rest) and "=" in rest[i + 1]:
                k, v = rest[i + 1].split("=", 1)
                variables[k.strip()] = v
            i += 2
        else:
            filtered.append(a)
            i += 1

    tmpl = TEMPLATES.get_template(name)
    if tmpl is None:
        print(f"ERROR: no template '{name}'. Try: python main.py --templates",
              file=sys.stderr)
        return 1
    try:
        rendered_task = TEMPLATES.render(name, variables)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    (commit, commit_message, loop_name, overrides, min_conf, workspace_name,
     require_approval, auto_low, approval_mode,
     use_memory, no_memory, memory_limit,
     use_context_pack, no_context_pack, context_max_files, context_max_chars,
     context_files, intake, no_intake, intake_mode, non_interactive,
     external_coder_name, external_agent_mode, _ecf, _ect,
     t_job_priority, t_job_labels, t_job_notes,
     _task_args) = _parse_run_flags(filtered)
    if approval_mode is None:
        approval_mode = "interactive" if require_approval else "none"
    memory_mode = "off" if no_memory else ("on" if use_memory else "auto")
    context_mode = "off" if no_context_pack else ("on" if use_context_pack else "auto")
    intake_mode = _resolve_intake_mode(intake, no_intake, intake_mode)
    external_coder = _build_external_coder(
        external_coder_name, external_agent_mode, job_priority=t_job_priority,
        job_labels=t_job_labels, job_notes=t_job_notes)

    loop_type = loop_name or tmpl.default_loop_type
    loop = REGISTRY.get_loop(loop_type)
    if loop is None:
        print(f"ERROR: no loop named '{loop_type}'.", file=sys.stderr)
        return 1
    roles, role_errors = loop_engine_mod.resolve_roles(loop, AGENTS, overrides)
    if role_errors:
        print(f"ERROR: could not resolve agents: {role_errors}", file=sys.stderr)
        return 1

    conn = database.init_db()
    ws = project_workspace.WorkspaceManager(conn).get_workspace(workspace_name)
    if ws is None:
        print(f"ERROR: no workspace '{workspace_name}'.", file=sys.stderr)
        return 1

    # Templates skip intake by default; only --intake-mode always runs it.
    intake_bundle = None
    if intake_mode == "always":
        orig_rendered = rendered_task
        dec = _run_and_decide_intake(conn, orig_rendered, ws, loop_type,
                                     non_interactive, require_approval)
        if not dec["proceed"]:
            return _intake_stop_run(conn, orig_rendered, dec, ws, loop_type)
        rendered_task = dec["clarified_task"]
        intake_bundle = {"result": dec["result"], "status": dec["status"],
                         "answers": dec["answers"], "raw_task": orig_rendered,
                         "clarified_task": rendered_task}

    policy = approval_gates.ApprovalPolicy(name="cli", enabled=require_approval,
                                           auto_approve_low_risk=auto_low)
    approval_engine = approval_gates.ApprovalGateEngine(policy, mode=approval_mode)
    template_ctx = {"name": tmpl.name, "version": tmpl.version,
                    "variables": variables, "rendered_task": rendered_task}
    return _execute_run(conn, rendered_task, loop, ws, roles, overrides,
                        approval_engine, min_conf, commit, commit_message,
                        replay_request=None, template_ctx=template_ctx,
                        memory_mode=memory_mode, memory_limit=memory_limit,
                        context_mode=context_mode, context_max_files=context_max_files,
                        context_max_chars=context_max_chars, context_files=context_files,
                        intake_bundle=intake_bundle, external_coder=external_coder)


def _resolve_intake_mode(intake, no_intake, intake_mode):
    if no_intake:
        return "never"
    if intake_mode in ("auto", "always", "never"):
        return intake_mode
    if intake:
        return "always"
    return "auto"


def _print_task_intake(result, used):
    _rule("TASK INTAKE")
    print(f"Used                : {'yes' if used else 'no'}")
    if not used or result is None:
        return
    print(f"Raw task            : {result.raw_task}")
    print(f"Clarified task      : {result.clarified_task}")
    print(f"Detected loop type  : {result.detected_loop_type}")
    print(f"Confidence          : {result.confidence_score}")
    print(f"Ambiguity           : {result.ambiguity_score}")
    print(f"Risk level          : {result.risk_level}")
    print(f"Clarification req'd : {result.clarification_required}")
    print(f"Assumptions         : {result.assumptions}")
    if result.recommended_next_action != "proceed":
        print(f"Recommended action  : {result.recommended_next_action}")


def _run_and_decide_intake(conn, raw_task, ws, explicit_loop_name, non_interactive,
                           approval_enabled):
    """Run intake analysis and decide proceed/stop. Interactive Q&A when needed."""
    eng = task_intake.TaskIntakeEngine(conn)
    req = task_intake.TaskIntakeRequest(
        raw_task=raw_task, loop_type=explicit_loop_name, workspace_name=ws.name,
        workspace_profile=ws.profile_name, available_loops=REGISTRY.names(),
        available_agents=AGENTS.names(),
        project_context_available=(database.get_latest_project_intelligence_report(
            conn, ws.name) is not None))
    if ollama_client.is_alive():
        ag = AGENTS.get_agent("intake_analyst")
        result = eng.analyze(req, model=ag.default_model, system=ag.system_prompt,
                             generate_fn=ollama_client.generate)
    else:
        result = eng.analyze(req)

    _print_task_intake(result, True)
    rec_loop = result.detected_loop_type
    base = dict(result=result, clarified_task=result.clarified_task, rec_loop=rec_loop,
                answers={})

    def stop(status, cond):
        d = dict(base); d.update(proceed=False, status=status,
                                 stop_condition=cond, final_status=status)
        return d

    if result.recommended_next_action == "block":
        return stop("BLOCKED", "intake_blocked")
    if result.clarification_required:
        if non_interactive:
            return stop("NEEDS_CLARIFICATION", "needs_clarification")
        print("\nClarification required:")
        answers = {}
        for q in result.clarification_questions:
            try:
                ans = input(f"  [{q.id}] {q.question} ").strip()
            except EOFError:
                ans = ""
            if q.required and not ans:
                print("  (required question unanswered — stopping)")
                return stop("NEEDS_CLARIFICATION", "needs_clarification")
            answers[q.id] = ans
        clarified = raw_task + "\n\nClarifications:\n" + "\n".join(
            f"- {q.question}: {answers.get(q.id, '')}"
            for q in result.clarification_questions)
        result.clarified_task = clarified
        if result.risk_level in ("high", "critical") and not approval_enabled:
            d = stop("BLOCKED", "intake_high_risk_requires_approval")
            d["clarified_task"] = clarified; d["answers"] = answers
            return d
        return dict(proceed=True, result=result, clarified_task=clarified,
                    rec_loop=rec_loop, answers=answers, status="clarified")
    if result.risk_level in ("high", "critical") and not approval_enabled:
        return stop("BLOCKED", "intake_high_risk_requires_approval")
    return dict(proceed=True, result=result, clarified_task=result.clarified_task,
                rec_loop=rec_loop, answers={}, status="proceeded")


def _persist_intake(recorder, conn, loop_id, result, status, answers, proceed,
                    approval_enabled):
    database.save_task_intake_event(
        conn, loop_id, result, status,
        json.dumps(answers) if answers else None)
    recorder.save_metric("intake_used", 1, "bool")
    recorder.save_metric("intake_confidence_score", result.confidence_score, "score")
    recorder.save_metric("intake_ambiguity_score", result.ambiguity_score, "score")
    recorder.save_metric("intake_clarification_required",
                         1 if result.clarification_required else 0, "bool")
    recorder.save_metric("intake_question_count",
                         len(result.clarification_questions), "count")
    recorder.save_metric("intake_risk_level", None, "string", metric_text=result.risk_level)
    recorder.save_metric("intake_detected_loop_type", None, "string",
                         metric_text=result.detected_loop_type)
    recorder.save_quality_gate_result(
        0, "task_intake_valid", result.parse_ok, True,
        "info" if result.parse_ok else "error",
        "intake JSON parsed" if result.parse_ok else "intake JSON unparseable")
    clar_ok = (not result.clarification_required) or proceed
    recorder.save_quality_gate_result(
        0, "clarification_resolved", clar_ok, True,
        "info" if clar_ok else "error",
        "clarification resolved" if clar_ok else "clarification not resolved")
    risk_ok = result.risk_level not in ("high", "critical") or approval_enabled
    recorder.save_quality_gate_result(
        0, "intake_risk_accepted", risk_ok, True,
        "info" if risk_ok else "error",
        "risk accepted" if risk_ok else "high-risk task without approval")


def _intake_stop_run(conn, raw_task, dec, ws, loop_name) -> int:
    """Create a stopped loop (no Supervisor/Coder/Reviewer, no side effects)."""
    result = dec["result"]
    loop_type = loop_name or dec["rec_loop"] or "code_build"
    lid = database.insert_loop(
        conn, dec["clarified_task"] or raw_task, config.SUPERVISOR_MODEL,
        config.CODER_MODEL, config.SUPERVISOR_MODEL, loop_type=loop_type,
        loop_version="1.0", workspace_name=ws.name, workspace_root=ws.root_path,
        raw_task=raw_task, clarified_task=dec["clarified_task"], intake_used=True,
        intake_status=dec["status"])
    recorder = database.LoopRecorder(conn, lid)
    _persist_intake(recorder, conn, lid, result, dec["status"], dec["answers"],
                    proceed=False, approval_enabled=False)
    recorder.save_stop_condition_result(0, dec["stop_condition"], True, "high",
                                        f"intake -> {dec['status']}")
    database.finish_loop(conn, lid, dec["final_status"], dec["stop_condition"], 0, 0.0)
    _generate_and_persist_report(conn, recorder, lid)
    _rule("FINAL RESULT")
    print(f"{dec['final_status']} — intake stopped before any Supervisor/Coder/"
          f"Reviewer call. Stop reason: {dec['stop_condition']}.")
    print(f"Saved to database as loop #{lid} "
          f"(view with: python main.py --show {lid}).")
    return 2


def _load_completion(completion_file, completion_text):
    """Load an ExternalAgentCompletion from a file or inline text, or None."""
    if completion_file:
        return external_agents.load_completion_file(completion_file)
    if completion_text:
        return external_agents.parse_completion_summary(completion_text)
    return None


def _build_external_coder(name, mode, completion=None, job_priority="normal",
                          job_labels=None, job_notes=""):
    """Return an external_coder dict for the engine, or None if 'none'/invalid."""
    if not name or name == "none":
        return None
    adapter = EXTERNAL.get(name)
    if adapter is None:
        print(f"WARNING: unknown external coder '{name}'; ignoring.", file=sys.stderr)
        return None
    if mode not in external_agents.SUPPORTED_MODES:
        print(f"WARNING: external-agent-mode '{mode}' unsupported; using 'handoff'.",
              file=sys.stderr)
        mode = "handoff"

    def confirm(handoff_path, instructions, agent_name):
        print(f"\n[EXTERNAL CODER] Hand this off to {agent_name} ({mode} mode).")
        print("Run, in a separate terminal:")
        print(instructions)
        print(f"Handoff prompt saved to:\n  {handoff_path}")
        try:
            ans = input("\nDid the external agent finish? [y/N] ").strip().lower()
        except EOFError:
            ans = ""
        return ans in ("y", "yes")

    return {"adapter": adapter, "mode": mode, "confirm": confirm,
            "completion": completion, "job_priority": job_priority,
            "job_labels": job_labels, "job_notes": job_notes}


def _execute_run(conn, task, loop, ws, roles, overrides, approval_engine,
                 min_conf, commit, commit_message, replay_request=None,
                 template_ctx=None, memory_mode="auto", memory_limit=None,
                 context_mode="auto", context_max_files=None,
                 context_max_chars=None, context_files=None,
                 intake_bundle=None, external_coder=None) -> int:
    """Shared run pipeline used by normal runs, replays, and templates."""
    sup, cod, rev = roles["supervisor"], roles["coder"], roles["reviewer"]
    ws_manager = project_workspace.WorkspaceManager(conn)
    # Do NOT create dirs for an invalid workspace (write_base makedirs); that would
    # turn a "missing" workspace valid and let a replay run. Let the engine block it.
    ws_valid = len(ws_manager.validate_workspace(ws)) == 0
    write_base = ws_manager.write_base(ws) if ws_valid else "(invalid workspace)"

    # Load latest project intelligence for this workspace (if any) -> Supervisor.
    intel_report_id, project_context_text = _load_project_context(conn, ws)

    # Memory search (read-only, SQLite) BEFORE inserting this loop's row.
    mem_limit = memory_limit or 5
    use_mem = False
    if memory_mode != "off":
        prior = conn.execute("SELECT COUNT(*) FROM loops").fetchone()[0]
        use_mem = memory_mode == "on" or prior > 0
    mem_results = []
    memory_context_text = ""
    if use_mem:
        mq = memory_search.MemorySearchQuery(
            query=task, workspace_name=ws.name, limit=mem_limit, source_types=["all"])
        mem_results = memory_search.MemorySearchEngine(conn).search(mq)
        memory_context_text = memory_search.format_memory_context(mem_results)
    mem_injected = bool(use_mem and mem_results)

    # Context pack (read-only file excerpts) BEFORE inserting this loop's row.
    cp_files_n = context_max_files or context_packs.DEFAULT_MAX_FILES
    cp_chars_n = context_max_chars or context_packs.DEFAULT_MAX_TOTAL_CHARS
    explicit_ctx = context_files or []
    use_cp = False
    if context_mode != "off":
        pi_exists = database.get_latest_project_intelligence_report(conn, ws.name) is not None
        use_cp = context_mode == "on" or pi_exists or bool(explicit_ctx)
    context_pack = None
    if use_cp:
        creq = context_packs.ContextPackRequest(
            workspace_name=ws.name, task=task, explicit_paths=explicit_ctx,
            max_files=cp_files_n, max_total_chars=cp_chars_n)
        context_pack = context_packs.ContextPackBuilder(conn).build(
            creq, ws, loop_type=loop.name)

    if intake_bundle is None:
        _print_task_intake(None, False)
    print("Loop Engineering — Stage 2.9")
    if replay_request is not None:
        print(f"Replay             : source loop #{replay_request.source_loop_id}, "
              f"mode={replay_request.replay_mode}")
    print(f"Loop               : {loop.name} (v{loop.version})  "
          f"tools={loop.allowed_tools or 'none'}")
    print(f"Approval           : required={approval_engine.policy.enabled} "
          f"mode={approval_engine.mode} "
          f"auto_low_risk={approval_engine.policy.auto_approve_low_risk}")
    print(f"Workspace          : {ws.name}  (root: {ws.root_path})")
    print(f"Workspace profile  : {ws.profile_name} (v{ws.profile_version})")
    print(f"Allowed write paths: {ws.allowed_write_paths or '(none)'}")
    print(f"Allowed cmd paths  : {ws.allowed_command_paths}")
    print(f"Git allowed        : {'yes' if ws.allow_git else 'no'}")
    print(f"Write base         : {write_base}")
    print(f"Supervisor agent   : {sup.agent_name} -> {sup.model}")
    print(f"Coder agent        : {cod.agent_name} -> {cod.model}")
    print(f"Reviewer agent     : {rev.agent_name} -> {rev.model}")
    if "test_analyst" in roles:
        ta = roles["test_analyst"]
        print(f"Test analyst agent : {ta.agent_name} -> {ta.model} (on failure)")
    print(f"Ollama             : {config.OLLAMA_HOST}")
    print(f"Max retries        : {loop.max_retries}")
    print(f"Min reviewer conf  : {min_conf if min_conf is not None else loop.min_reviewer_confidence}")
    print(f"Project intel      : {('report #' + str(intel_report_id)) if intel_report_id else '(none — run --scan-project)'}")
    print(f"Memory             : {('used (' + str(len(mem_results)) + ' results)') if use_mem else 'disabled'}")
    print(f"Context pack       : {('used (' + str(context_pack.total_files_included) + ' files)') if context_pack else 'disabled'}")
    print(f"Database           : {database.db_path()}")

    if not ollama_client.is_alive():
        print(
            f"\nERROR: Ollama is not reachable at {config.OLLAMA_HOST}.\n"
            "Start it with `ollama serve` and ensure the models are pulled:\n"
            f"  ollama pull {config.SUPERVISOR_MODEL}\n"
            f"  ollama pull {config.CODER_MODEL}",
            file=sys.stderr,
        )
        return 1

    _rule("TASK")
    print(task)
    if template_ctx is not None:
        print(f"(rendered from template '{template_ctx['name']}')")
    if commit:
        print("(--commit: will commit workspace/ only if APPROVED)")

    tvars_json = (json.dumps(template_ctx["variables"]) if template_ctx else None)
    loop_id = database.insert_loop(
        conn, task, sup.model, cod.model, rev.model,
        loop_type=loop.name, loop_version=loop.version,
        workspace_name=ws.name, workspace_root=ws.root_path,
        template_name=(template_ctx["name"] if template_ctx else None),
        template_version=(template_ctx["version"] if template_ctx else None),
        template_variables_json=tvars_json,
        rendered_task=(template_ctx["rendered_task"] if template_ctx else None),
        project_intelligence_report_id=intel_report_id,
        raw_task=(intake_bundle["raw_task"] if intake_bundle else None),
        clarified_task=(intake_bundle["clarified_task"] if intake_bundle else None),
        intake_used=(True if intake_bundle else None),
        intake_status=(intake_bundle["status"] if intake_bundle else None))
    recorder = database.LoopRecorder(conn, loop_id)
    print(f"Loop id            : {loop_id}")

    # Task intake persistence (event + metrics + gates) when used.
    if intake_bundle is not None:
        _persist_intake(recorder, conn, loop_id, intake_bundle["result"],
                        intake_bundle["status"], intake_bundle["answers"],
                        proceed=True, approval_enabled=approval_engine.policy.enabled)
    else:
        recorder.save_metric("intake_used", 0, "bool")

    # Project intelligence usage metrics + safety gate.
    recorder.save_metric("project_intelligence_used", 1 if intel_report_id else 0, "bool")
    if intel_report_id:
        recorder.save_metric("project_intelligence_report_id", intel_report_id, "id")
        recorder.save_quality_gate_result(0, "project_intelligence_safe", True, True,
                                          "info", "scan read only allowed/non-protected files")

    # Memory search usage: event + metrics + read-only safety gate.
    recorder.save_metric("memory_search_used", 1 if use_mem else 0, "bool")
    recorder.save_metric("memory_search_result_count", len(mem_results), "count")
    recorder.save_metric("memory_search_limit", mem_limit, "count")
    recorder.save_metric("memory_context_injected", 1 if mem_injected else 0, "bool")
    if use_mem:
        tops = [{"source_type": r.source_type, "source_id": r.source_id,
                 "title": r.title, "snippet": r.snippet, "score": r.score}
                for r in mem_results[:5]]
        database.save_memory_search_event(
            conn, loop_id, task, ws.name, json.dumps(["all"]), len(mem_results),
            json.dumps(tops), use_mem)
        recorder.save_quality_gate_result(0, "memory_context_safe", True, True,
                                          "info", "read-only SQLite + internal report files")

    # Context pack persistence (metadata only) + metrics + safety gate.
    recorder.save_metric("context_pack_used", 1 if context_pack else 0, "bool")
    if context_pack is not None:
        cp_id = database.save_context_pack(conn, context_pack, loop_id)
        database.set_loop_context_pack_id(conn, loop_id, cp_id)
        recorder.save_metric("context_pack_file_count",
                             context_pack.total_files_included, "count")
        recorder.save_metric("context_pack_total_chars", context_pack.total_chars, "chars")
        recorder.save_metric("context_pack_truncated",
                             1 if context_pack.truncated else 0, "bool")
        recorder.save_quality_gate_result(
            0, "context_pack_safe", context_pack.safe, True,
            "info" if context_pack.safe else "error",
            "read-only allowed/non-protected files" if context_pack.safe
            else "an explicit unsafe file was requested")

    if template_ctx is not None:
        recorder.save_metric("template_used", 1, "bool")
        recorder.save_metric("template_name", None, "string",
                             metric_text=template_ctx["name"])
        recorder.save_metric("template_version", None, "string",
                             metric_text=template_ctx["version"])
        recorder.save_metric("template_variable_count",
                             len(template_ctx["variables"]), "count")
        recorder.save_metric("rendered_task_length", len(task), "chars")
        database.save_loop_template_event(
            conn, loop_id, template_ctx["name"], template_ctx["version"],
            tvars_json, task, "rendered", "template rendered into task")

    if replay_request is not None:
        recorder.save_metric("replay_is_replay", 1, "bool")
        recorder.save_metric("replay_source_loop_id",
                             replay_request.source_loop_id, "id")
        recorder.save_metric("replay_mode", None, "string",
                             metric_text=replay_request.replay_mode)

    for role, b in roles.items():
        recorder.save_agent_event(
            b.agent_name, role, b.model,
            "overridden" if bool(overrides.get(role)) else "resolved",
            f"loop={loop.name}; model={b.model}")

    engine = LoopEngine()
    try:
        result = engine.run(task, on_step=_on_step, recorder=recorder,
                            loop=loop, roles=roles, min_reviewer_confidence=min_conf,
                            workspace=ws, approval_engine=approval_engine,
                            project_context=project_context_text,
                            memory_context=(memory_context_text if use_mem else ""),
                            context_pack=context_pack, external_coder=external_coder)
    except ollama_client.OllamaTimeout as exc:
        recorder.save_metric("model_call_timeout", 1, "bool")
        database.finish_loop(conn, loop_id, "FAILED", "model_call_timeout", 0, 0.0)
        print(f"\nFAILED: model call timed out. {exc}", file=sys.stderr)
        if replay_request is not None:
            _save_replay_final(conn, replay_request, loop_id, "FAILED", "model_call_timeout")
        return 2
    except ollama_client.OllamaError as exc:
        database.finish_loop(conn, loop_id, "ERROR", str(exc), 0, 0.0)
        print(f"\nERROR: {exc}", file=sys.stderr)
        if replay_request is not None:
            _save_replay_final(conn, replay_request, loop_id, "ERROR", str(exc))
        return 1

    database.finish_loop(conn, loop_id, result.final_status, result.stop_reason,
                         result.retry_count, result.total_loop_s)
    _save_metrics(recorder, result, roles)

    # Stabilization metrics (Stage 3.2.2).
    recorder.save_metric("deterministic_test_fix_fallback_used",
                         1 if result.deterministic_test_fix_fallback_used else 0, "bool")
    recorder.save_metric("model_call_timeout",
                         1 if result.model_call_timeout else 0, "bool")

    # External agent job packet metrics + safety gate (Stage 3.3).
    ji = result.external_job_info
    recorder.save_metric("external_agent_job_created", 1 if ji else 0, "bool")
    if ji:
        recorder.save_metric("external_agent_job_id", ji["job_id"], "id")
        recorder.save_metric("external_agent_job_status", None, "string",
                             metric_text=ji["status"])
        recorder.save_metric("external_agent_packet_written",
                             1 if ji.get("packet_path") else 0, "bool")
        recorder.save_metric("external_agent_packet_bytes", ji.get("packet_bytes", 0), "bytes")
        recorder.save_metric("external_agent_handoff_bytes", ji.get("handoff_bytes", 0), "bytes")
        safe = bool(ji.get("packet_safe"))
        recorder.save_quality_gate_result(
            0, "external_agent_job_packet_safe", safe, True,
            "info" if safe else "error",
            "packet generated safely (internal path, allowed paths only, no secrets)"
            if safe else f"packet safety failed: {ji.get('packet_safe_reasons')}")
        if ji.get("status") == "WAITING_FOR_EXTERNAL_AGENT":
            recorder.save_stop_condition_result(
                0, "external_agent_job_waiting", True, "high",
                f"job #{ji['job_id']} waiting for external agent completion")
        # Job queue/metadata metrics + validity gate (Stage 3.4).
        import external_agent_jobs as _eaj
        _job = _eaj.ExternalAgentJobManager(conn).get_job(ji["job_id"])
        if _job is not None:
            recorder.save_metric("external_job_priority", None, "string",
                                 metric_text=_job.priority)
            recorder.save_metric("external_job_archived", 1 if _job.archived else 0, "bool")
            recorder.save_metric("external_job_retry_count", _job.retry_count, "count")
            mvalid, mreasons = _eaj.validate_metadata(
                _job.priority, _job.labels, _job.notes,
                1 if _job.archived else 0, _job.retry_count)
            recorder.save_quality_gate_result(
                0, "external_agent_job_metadata_valid", mvalid, True,
                "info" if mvalid else "error",
                "job metadata valid" if mvalid else f"invalid metadata: {mreasons}")

    # External coding agent metrics + safety gates (Stage 3.0).
    recorder.save_metric("external_agent_used", 1 if result.external_agent_used else 0, "bool")
    if result.external_agent_used:
        er = result.external_agent_result
        recorder.save_metric("external_agent_name", None, "string",
                             metric_text=(er.agent_name if er else None))
        recorder.save_metric("external_agent_mode", None, "string",
                             metric_text=result.external_mode)
        recorder.save_metric("external_agent_completed",
                             1 if (er and er.completed) else 0, "bool")
        recorder.save_metric("external_agent_success",
                             1 if (er and er.success) else 0, "bool")
        recorder.save_metric("external_agent_duration_seconds",
                             (er.duration_seconds if er else 0.0), "seconds")
        recorder.save_metric("external_agent_files_changed_count",
                             (len(er.files_changed) if er else 0), "count")
        # Gates: handoff safe, changes within workspace, completion confirmed.
        recorder.save_quality_gate_result(
            0, "external_agent_handoff_safe", result.external_handoff_safe, True,
            "info" if result.external_handoff_safe else "error",
            "handoff generated safely" if result.external_handoff_safe
            else "handoff prompt contained unsafe content")
        within = not (result.final_stop_condition == "external_agent_workspace_violation")
        recorder.save_quality_gate_result(
            0, "external_agent_changes_within_workspace", within, True,
            "info" if within else "error",
            "changes within allowed paths" if within
            else "external agent changed disallowed/protected files")
        confirmed = bool(er and er.completed)
        recorder.save_quality_gate_result(
            0, "external_agent_completion_confirmed", confirmed, True,
            "info" if confirmed else "error",
            "completion confirmed" if confirmed else "completion not confirmed")
        # Imported-completion metrics + gates (Stage 3.1).
        comp_row = database.get_external_agent_completion(conn, loop_id)
        if comp_row is not None:
            import json as _json
            cj = _json.loads(comp_row["completion_json"] or "{}")
            recorder.save_metric("external_completion_imported", 1, "bool")
            recorder.save_metric("external_completion_parsed",
                                 1 if comp_row["completion_parsed"] else 0, "bool")
            tp = cj.get("tests_passed")
            if tp is not None:
                recorder.save_metric("external_completion_tests_passed",
                                     1 if tp else 0, "bool")
            recorder.save_metric("external_completion_file_count",
                                 len(cj.get("files_changed", [])), "count")
            recorder.save_metric("external_completion_command_count",
                                 len(cj.get("commands_run", [])), "count")
            recorder.save_quality_gate_result(
                0, "external_completion_valid", True, True, "info",
                "completion parsed/stored")
            cmatch = result.final_stop_condition != "external_completion_workspace_mismatch"
            recorder.save_quality_gate_result(
                0, "external_completion_matches_workspace", cmatch, False,
                "info" if cmatch else "warning",
                "claimed changes consistent" if cmatch else "claimed changes conflict")
            reviewed = result.final_status not in ("NEEDS_EXTERNAL_AGENT",)
            recorder.save_quality_gate_result(
                0, "external_completion_reviewed", reviewed, True,
                "info" if reviewed else "error",
                "completion reviewed" if reviewed else "completion not reviewed")

    _rule("SUPERVISOR PLAN")
    print(result.plan)

    _rule("FINAL CODER SUMMARY")
    co = result.coder_output
    if co is not None:
        print(co.summary or "(no summary)")
        if co.notes:
            print("\nNotes:")
            for n in co.notes:
                print(f"  - {n}")
        if not co.parse_ok:
            print("(note: coder JSON was unparseable; no files applied)")

    _print_files(result, ws)
    _print_commands(result)
    _print_test_analyst(result)
    _print_gates_and_stops(result)

    _rule("FINAL REVIEW (structured)")
    r = result.review
    if r is not None:
        print(f"approved         : {r.approved}")
        print(f"summary          : {r.summary}")
        print(f"issues           : {r.issues}")
        print(f"required_changes : {r.required_changes}")
        print(f"confidence_score : {r.confidence_score}")
        print(f"stop_reason      : {r.stop_reason}")
        if not r.parse_ok:
            print("(note: reviewer JSON was unparseable; treated as rejection)")

    _print_metrics(result)

    _handle_git(conn, recorder, loop_id, task, result, commit, commit_message, loop,
                ws, approval_engine)
    _save_approval_metrics(recorder, approval_engine)
    _print_approvals(approval_engine)

    # Persist the replay link BEFORE report generation (report shows replay note).
    if replay_request is not None:
        _save_replay_final(conn, replay_request, loop_id, result.final_status,
                           result.stop_reason)

    report_path, report_err = _generate_and_persist_report(conn, recorder, loop_id)

    tp = {True: "passed", False: "FAILED", None: "n/a"}[result.tests_passed]
    _rule("FINAL RESULT")
    print(f"{result.final_status} after {result.attempts} attempt(s) "
          f"({result.retry_count} retr{'y' if result.retry_count == 1 else 'ies'}). "
          f"Stop reason: {result.stop_reason}. "
          f"Files changed: {result.total_files_changed}. "
          f"Commands executed: {result.commands_executed}. Tests: {tp}.")
    print(f"Saved to database as loop #{loop_id} "
          f"(view with: python main.py --show {loop_id}).")
    if report_path:
        print(f"Report: {report_path}")
    else:
        print(f"Report generation FAILED: {report_err}", file=sys.stderr)
    return 0 if result.final_status == "APPROVED" else 2


def _replay_settings_json(req) -> str:
    keys = ("task", "loop_type", "workspace_name", "supervisor_model",
            "coder_model", "reviewer_model", "test_analyst_model", "approval_mode",
            "require_approval", "auto_approve_low_risk", "min_reviewer_confidence",
            "commit")
    return json.dumps({k: getattr(req, k) for k in keys})


def _save_replay_final(conn, req, new_loop_id, status, stop_reason):
    database.save_replay_event(conn, req.source_loop_id, new_loop_id,
                               req.replay_mode, False, status, stop_reason,
                               _replay_settings_json(req))


def _replay_dry_run(conn, req, ws) -> int:
    profile = ws.profile_name if ws is not None else "(workspace not found)"
    ws_root = ws.root_path if ws is not None else "(unknown)"
    _rule("REPLAY DRY RUN")
    print(f"Source loop ID       : {req.source_loop_id}")
    src = database.get_loop(conn, req.source_loop_id)
    print(f"Source task          : {src['task'] if src else '(unknown)'}")
    print(f"Replay mode          : {req.replay_mode}")
    print(f"Reconstructed task   : {req.task}")
    print(f"Loop type            : {req.loop_type}")
    print(f"Workspace            : {req.workspace_name} (root: {ws_root})")
    print(f"Workspace profile    : {profile}")
    print(f"Supervisor model     : {req.supervisor_model or '(agent default)'}")
    print(f"Coder model          : {req.coder_model or '(agent default)'}")
    print(f"Reviewer model       : {req.reviewer_model or '(agent default)'}")
    print(f"Test analyst model   : {req.test_analyst_model or '(agent default)'}")
    print(f"Approval mode        : {req.approval_mode}")
    print(f"Require approval     : {req.require_approval}")
    print(f"Auto approve low risk: {req.auto_approve_low_risk}")
    print(f"Min reviewer conf    : {req.min_reviewer_confidence}")
    print(f"Commit enabled       : {req.commit}")
    print(f"Commit message       : {req.commit_message or '(auto)'}")
    if req.template_name:
        print(f"Template             : {req.template_name} (v{req.template_version})")
        print(f"Template variables   : {req.template_variables_json}")
        print(f"Rendered task        : {req.rendered_task}")
    print(f"Context pack         : {'used (will rebuild fresh)' if req.context_pack_used else 'not used'}")
    if req.source_raw_task or req.source_clarified_task:
        print(f"Source raw task      : {req.source_raw_task}")
        print(f"Source clarified task: {req.source_clarified_task}")
    print("Intake               : not re-run by default (use --intake-mode always to re-run)")
    if ws is None:
        print("\nWARNING: workspace not found — a real replay would stop with "
              "BLOCKED before any model call or side effect.")
        would = "Would BLOCK before model calls (workspace invalid)."
    else:
        errs = project_workspace.WorkspaceManager().validate_workspace(ws)
        if errs:
            print(f"\nWARNING: workspace invalid ({errs}) — a real replay would "
                  "stop with BLOCKED before any side effect.")
            would = "Would BLOCK before model calls (workspace invalid)."
        else:
            would = (f"Would run loop '{req.loop_type}' on workspace "
                     f"'{req.workspace_name}' and re-check all gates/approvals.")
    print(f"What would run       : {would}")
    database.save_replay_event(conn, req.source_loop_id, None, req.replay_mode,
                               True, "dry_run", "n/a", _replay_settings_json(req))
    print("\n(dry run — no loop created, no model called, nothing written)")
    return 0


def _replay_execute(conn, req, intake_mode="never", non_interactive=False) -> int:
    ws_manager = project_workspace.WorkspaceManager(conn)
    ws = ws_manager.get_workspace(req.workspace_name)
    if ws is None:
        # Build an intentionally-invalid workspace so the engine blocks before
        # any model call or side effect (never silently fall back to default).
        ws = project_workspace.ProjectWorkspace(
            name=req.workspace_name,
            root_path=os.path.join(project_workspace.PROJECT_ROOT, "__missing_workspace__"),
            allowed_read_paths=["."], allowed_write_paths=["workspace"],
            allowed_command_paths=["workspace"], allow_git=False,
            profile_name="sandbox", profile_version="1.0")
    loop = REGISTRY.get_loop(req.loop_type) or REGISTRY.get_loop(loop_registry.DEFAULT_LOOP)
    overrides = req.model_overrides()
    roles, errs = loop_engine_mod.resolve_roles(loop, AGENTS, overrides)
    if errs:
        print(f"ERROR: could not resolve agents: {errs}", file=sys.stderr)
        return 1
    policy = approval_gates.ApprovalPolicy(
        name="replay", enabled=req.require_approval,
        auto_approve_low_risk=req.auto_approve_low_risk)
    engine = approval_gates.ApprovalGateEngine(policy, mode=req.approval_mode)
    # Preserve template metadata on the replayed loop, if the source had it.
    template_ctx = None
    if req.template_name:
        try:
            tvars = json.loads(req.template_variables_json or "{}")
        except (ValueError, TypeError):
            tvars = {}
        template_ctx = {"name": req.template_name, "version": req.template_version,
                        "variables": tvars,
                        "rendered_task": req.rendered_task or req.task}
    # Exact replay preserves whether a context pack was used; a fresh pack is
    # always rebuilt under current safety rules (old transient contents never reused).
    ctx_mode = "auto"
    if req.replay_mode == "exact":
        ctx_mode = "on" if req.context_pack_used else "off"

    # Replay does NOT re-run intake by default (exact uses the source clarified
    # task). --intake-mode always re-runs intake on the replayed task.
    task = req.task
    intake_bundle = None
    if intake_mode == "always" and ws_manager.validate_workspace(ws) == []:
        dec = _run_and_decide_intake(conn, task, ws, req.loop_type, non_interactive,
                                     req.require_approval)
        if not dec["proceed"]:
            return _intake_stop_run(conn, task, dec, ws, req.loop_type)
        task = dec["clarified_task"]
        intake_bundle = {"result": dec["result"], "status": dec["status"],
                         "answers": dec["answers"], "raw_task": req.task,
                         "clarified_task": task}

    return _execute_run(conn, task, loop, ws, roles, overrides, engine,
                        req.min_reviewer_confidence, req.commit, req.commit_message,
                        replay_request=req, template_ctx=template_ctx,
                        context_mode=ctx_mode, intake_bundle=intake_bundle)


def _cmd_replay(args) -> int:
    if not args:
        print("ERROR: --replay needs a LOOP_ID", file=sys.stderr)
        return 1
    try:
        source_id = int(args[0])
    except ValueError:
        print("ERROR: LOOP_ID must be an integer", file=sys.stderr)
        return 1
    rest = args[1:]
    replay_mode = "exact"
    dry_run = False
    filtered = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--replay-mode":
            replay_mode = rest[i + 1] if i + 1 < len(rest) else "exact"
            i += 2
        elif a == "--dry-run":
            dry_run = True
            i += 1
        else:
            filtered.append(a)
            i += 1
    (commit, commit_message, _loop_name, overrides, min_conf, workspace_name,
     require_approval, auto_low, approval_mode,
     _use_memory, _no_memory, _memory_limit,
     _ucp, _ncp, _cmf, _cmc, _cfiles,
     r_intake, r_no_intake, r_intake_mode, r_non_interactive,
     _ext_name, _ext_mode, _ecf, _ect, _jp, _jl, _jn,
     _task_args) = _parse_run_flags(filtered)

    conn = database.init_db()
    cli = {
        "workspace": workspace_name,
        "supervisor_model": overrides.get("supervisor"),
        "coder_model": overrides.get("coder"),
        "reviewer_model": overrides.get("reviewer"),
        "test_analyst_model": overrides.get("test_analyst"),
        "require_approval": require_approval, "approval_mode": approval_mode,
        "auto_approve_low_risk": auto_low, "min_conf": min_conf,
        "commit": commit, "commit_message": commit_message, "dry_run": dry_run,
    }
    try:
        req = replay.ReplayEngine(conn).reconstruct(source_id, replay_mode, cli)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    intake_mode = _resolve_intake_mode(r_intake, r_no_intake, r_intake_mode)
    if req.dry_run:
        ws = project_workspace.WorkspaceManager(conn).get_workspace(req.workspace_name)
        return _replay_dry_run(conn, req, ws)
    return _replay_execute(conn, req, intake_mode, r_non_interactive)


def _cmd_help() -> int:
    print(USAGE)
    return 0


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] in ("--help", "-h", "help"):
        return _cmd_help()
    if args and args[0] == "--history":
        return _cmd_history(args[1:])
    if args and args[0] == "--show":
        return _cmd_show(args[1:])
    if args and args[0] == "--loops":
        return _cmd_loops()
    if args and args[0] == "--loop-info":
        return _cmd_loop_info(args[1:])
    if args and args[0] == "--agents":
        return _cmd_agents()
    if args and args[0] == "--agent-info":
        return _cmd_agent_info(args[1:])
    if args and args[0] == "--workspaces":
        return _cmd_workspaces()
    if args and args[0] == "--workspace-info":
        return _cmd_workspace_info(args[1:])
    if args and args[0] == "--register-workspace":
        return _cmd_register_workspace(args[1:])
    if args and args[0] == "--workspace-profiles":
        return _cmd_workspace_profiles()
    if args and args[0] == "--workspace-profile-info":
        return _cmd_workspace_profile_info(args[1:])
    if args and args[0] == "--set-workspace-profile":
        return _cmd_set_workspace_profile(args[1:])
    if args and args[0] == "--report":
        return _cmd_report(args[1:])
    if args and args[0] == "--reports":
        return _cmd_reports(args[1:])
    if args and args[0] == "--observatory":
        return _cmd_observatory(args[1:])
    if args and args[0] == "--observatory-snapshots":
        return _cmd_observatory_snapshots(args[1:])
    if args and args[0] == "--observatory-snapshot":
        return _cmd_observatory_snapshot(args[1:])
    if args and args[0] == "--observatory-reports":
        return _cmd_observatory_reports(args[1:])
    if args and args[0] == "--observatory-report":
        return _cmd_observatory_report(args[1:])
    if args and args[0] == "--observatory-trends":
        return _cmd_observatory_trends(args[1:])
    if args and args[0] == "--observatory-trend-reports":
        return _cmd_observatory_trend_reports(args[1:])
    if args and args[0] == "--observatory-trend-report":
        return _cmd_observatory_trend_report(args[1:])
    if args and args[0] == "--observatory-failures":
        return _cmd_observatory_failures(args[1:])
    if args and args[0] == "--observatory-failure-drilldowns":
        return _cmd_observatory_failure_drilldowns(args[1:])
    if args and args[0] == "--observatory-failure-drilldown":
        return _cmd_observatory_failure_drilldown(args[1:])
    if args and args[0] == "--observatory-remediation":
        return _cmd_observatory_remediation(args[1:])
    if args and args[0] == "--observatory-remediation-plans":
        return _cmd_observatory_remediation_plans(args[1:])
    if args and args[0] == "--observatory-remediation-plan":
        return _cmd_observatory_remediation_plan(args[1:])
    if args and args[0] == "--create-observatory-actions":
        return _cmd_create_observatory_actions(args[1:])
    if args and args[0] == "--observatory-actions":
        return _cmd_observatory_actions(args[1:])
    if args and args[0] == "--observatory-action":
        return _cmd_observatory_action(args[1:])
    if args and args[0] == "--set-observatory-action-status":
        return _cmd_set_observatory_action_status(args[1:])
    if args and args[0] == "--set-observatory-action-notes":
        return _cmd_set_observatory_action_notes(args[1:])
    if args and args[0] == "--observatory-actions-report":
        return _cmd_observatory_actions_report(args[1:])
    if args and args[0] == "--handoff-observatory-action":
        return _cmd_handoff_observatory_action(args[1:])
    if args and args[0] == "--observatory-action-handoffs":
        return _cmd_observatory_action_handoffs(args[1:])
    if args and args[0] == "--observatory-action-handoff":
        return _cmd_observatory_action_handoff(args[1:])
    if args and args[0] == "--observatory-action-handoff-review":
        return _cmd_observatory_action_handoff_review(args[1:])
    if args and args[0] == "--observatory-action-handoff-reviews":
        return _cmd_observatory_action_handoff_reviews(args[1:])
    if args and args[0] == "--observatory-action-handoff-review-show":
        return _cmd_observatory_action_handoff_review_show(args[1:])
    if args and args[0] == "--observatory-stage4-audit":
        return _cmd_observatory_stage4_audit(args[1:])
    if args and args[0] == "--observatory-stage4-audits":
        return _cmd_observatory_stage4_audits(args[1:])
    if args and args[0] == "--observatory-stage4-audit-show":
        return _cmd_observatory_stage4_audit_show(args[1:])
    if args and args[0] == "--observatory-action-review":
        return _cmd_observatory_action_review(args[1:])
    if args and args[0] == "--observatory-action-reviews":
        return _cmd_observatory_action_reviews(args[1:])
    if args and args[0] == "--observatory-action-review-show":
        return _cmd_observatory_action_review_show(args[1:])
    if args and args[0] == "--loop-improvements":
        return _cmd_loop_improvements(args[1:])
    if args and args[0] == "--loop-improvement-plans":
        return _cmd_loop_improvement_plans(args[1:])
    if args and args[0] == "--loop-improvement-plan":
        return _cmd_loop_improvement_plan(args[1:])
    if args and args[0] == "--loop-improvement-proposals":
        return _cmd_loop_improvement_proposals(args[1:])
    if args and args[0] == "--loop-improvement-proposal":
        return _cmd_loop_improvement_proposal(args[1:])
    if args and args[0] == "--set-loop-improvement-status":
        return _cmd_set_loop_improvement_status(args[1:])
    if args and args[0] == "--loop-improvement-review":
        return _cmd_loop_improvement_review(args[1:])
    if args and args[0] == "--loop-improvement-reviews":
        return _cmd_loop_improvement_reviews(args[1:])
    if args and args[0] == "--loop-improvement-review-show":
        return _cmd_loop_improvement_review_show(args[1:])
    if args and args[0] == "--create-loop-improvement-actions":
        return _cmd_create_loop_improvement_actions(args[1:])
    if args and args[0] == "--loop-improvement-actions":
        return _cmd_loop_improvement_actions(args[1:])
    if args and args[0] == "--loop-improvement-action":
        return _cmd_loop_improvement_action(args[1:])
    if args and args[0] == "--set-loop-improvement-action-status":
        return _cmd_set_loop_improvement_action_status(args[1:])
    if args and args[0] == "--set-loop-improvement-action-notes":
        return _cmd_set_loop_improvement_action_notes(args[1:])
    if args and args[0] == "--loop-improvement-action-batches":
        return _cmd_loop_improvement_action_batches(args[1:])
    if args and args[0] == "--loop-improvement-action-batch":
        return _cmd_loop_improvement_action_batch(args[1:])
    if args and args[0] == "--loop-improvement-actions-report":
        return _cmd_loop_improvement_actions_report(args[1:])
    if args and args[0] == "--handoff-loop-improvement-action":
        return _cmd_handoff_loop_improvement_action(args[1:])
    if args and args[0] == "--loop-improvement-handoffs":
        return _cmd_loop_improvement_handoffs(args[1:])
    if args and args[0] == "--loop-improvement-handoff":
        return _cmd_loop_improvement_handoff(args[1:])
    if args and args[0] == "--loop-improvement-handoff-review":
        return _cmd_loop_improvement_handoff_review(args[1:])
    if args and args[0] == "--loop-improvement-handoff-reviews":
        return _cmd_loop_improvement_handoff_reviews(args[1:])
    if args and args[0] == "--loop-improvement-handoff-review-show":
        return _cmd_loop_improvement_handoff_review_show(args[1:])
    if args and args[0] == "--loop-improvement-stage5-audit":
        return _cmd_loop_improvement_stage5_audit(args[1:])
    if args and args[0] == "--loop-improvement-stage5-audits":
        return _cmd_loop_improvement_stage5_audits(args[1:])
    if args and args[0] == "--loop-improvement-stage5-audit-show":
        return _cmd_loop_improvement_stage5_audit_show(args[1:])
    if args and args[0] == "--plan-loop-improvement-application":
        return _cmd_plan_loop_improvement_application(args[1:])
    if args and args[0] == "--loop-improvement-application-plans":
        return _cmd_loop_improvement_application_plans(args[1:])
    if args and args[0] == "--loop-improvement-application-plan":
        return _cmd_loop_improvement_application_plan(args[1:])
    if args and args[0] == "--replay":
        return _cmd_replay(args[1:])
    if args and args[0] == "--templates":
        return _cmd_templates()
    if args and args[0] == "--template-info":
        return _cmd_template_info(args[1:])
    if args and args[0] == "--template":
        return _cmd_template(args[1:])
    if args and args[0] == "--scan-project":
        return _cmd_scan_project(args[1:])
    if args and args[0] == "--project-intel":
        return _cmd_project_intel(args[1:])
    if args and args[0] == "--project-intel-report":
        return _cmd_project_intel_report(args[1:])
    if args and args[0] == "--memory-search":
        return _cmd_memory_search(args[1:])
    if args and args[0] == "--context-pack":
        return _cmd_context_pack(args[1:])
    if args and args[0] == "--context-packs":
        return _cmd_context_packs(args[1:])
    if args and args[0] == "--import-external-completion":
        return _cmd_import_external_completion(args[1:])
    if args and args[0] == "--paused":
        return _cmd_paused(args[1:])
    if args and args[0] == "--resume":
        return _cmd_resume(args[1:])
    if args and args[0] == "--external-dashboard":
        return _cmd_external_dashboard(args[1:])
    if args and args[0] == "--external-health":
        return _cmd_external_health(args[1:])
    if args and args[0] == "--quarantine-health-fixtures":
        return _cmd_quarantine_health_fixtures(args[1:])
    if args and args[0] == "--check-portable-paths":
        return _cmd_check_portable_paths(args[1:])
    if args and args[0] == "--repair-portable-paths":
        return _cmd_repair_portable_paths(args[1:])
    if args and args[0] == "--external-inbox":
        return _cmd_external_inbox(args[1:])
    if args and args[0] == "--sync-external-completions":
        return _cmd_sync_external_completions(args[1:])
    if args and args[0] == "--sync-external-completion":
        return _cmd_sync_external_completion(args[1:])
    if args and args[0] == "--batch-external-jobs":
        return _cmd_batch_external_jobs(args[1:])
    if args and args[0] == "--external-batch-reports":
        return _cmd_external_batch_reports(args[1:])
    if args and args[0] == "--external-batch-report":
        return _cmd_external_batch_report(args[1:])
    if args and args[0] == "--external-jobs":
        return _cmd_external_jobs(args[1:])
    if args and args[0] == "--external-job":
        return _cmd_external_job(args[1:])
    if args and args[0] == "--cancel-external-job":
        return _cmd_cancel_external_job(args[1:])
    if args and args[0] == "--resume-external-job":
        return _cmd_resume_external_job(args[1:])
    if args and args[0] == "--archive-external-job":
        return _cmd_archive_external_job(args[1:])
    if args and args[0] == "--unarchive-external-job":
        return _cmd_archive_external_job(args[1:], unarchive=True)
    if args and args[0] == "--set-external-job-priority":
        return _cmd_set_external_job_priority(args[1:])
    if args and args[0] == "--set-external-job-labels":
        return _cmd_set_external_job_labels(args[1:])
    if args and args[0] == "--set-external-job-notes":
        return _cmd_set_external_job_notes(args[1:])

    (commit, commit_message, loop_name, overrides, min_conf, workspace_name,
     require_approval, auto_approve_low_risk, approval_mode,
     use_memory, no_memory, memory_limit,
     use_context_pack, no_context_pack, context_max_files, context_max_chars,
     context_files, intake, no_intake, intake_mode, non_interactive,
     external_coder_name, external_agent_mode, external_completion_file,
     external_completion_text, job_priority, job_labels, job_notes,
     task_args) = _parse_run_flags(args)
    memory_mode = "off" if no_memory else ("on" if use_memory else "auto")
    context_mode = "off" if no_context_pack else ("on" if use_context_pack else "auto")
    intake_mode = _resolve_intake_mode(intake, no_intake, intake_mode)
    try:
        _completion = _load_completion(external_completion_file, external_completion_text)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    external_coder = _build_external_coder(external_coder_name, external_agent_mode,
                                           _completion, job_priority=job_priority,
                                           job_labels=job_labels, job_notes=job_notes)
    explicit_loop = loop_name is not None

    if approval_mode is None:
        approval_mode = "interactive" if require_approval else "none"
    approval_policy = approval_gates.ApprovalPolicy(
        name="cli", enabled=require_approval,
        auto_approve_low_risk=auto_approve_low_risk)
    approval_engine = approval_gates.ApprovalGateEngine(approval_policy, mode=approval_mode)

    # Initialize persistence + resolve workspace (needed before intake).
    conn = database.init_db()
    ws_manager = project_workspace.WorkspaceManager(conn)
    ws = ws_manager.get_workspace(workspace_name)
    if ws is None:
        print(f"ERROR: no workspace '{workspace_name}'. Try: python main.py --workspaces",
              file=sys.stderr)
        return 1

    raw_task = _get_task(task_args)
    task = raw_task
    intake_bundle = None

    # --- Task intake (auto for non-template tasks) -------------------------
    if intake_mode != "never":
        dec = _run_and_decide_intake(conn, raw_task, ws, loop_name, non_interactive,
                                     require_approval)
        if not dec["proceed"]:
            return _intake_stop_run(conn, raw_task, dec, ws, loop_name)
        task = dec["clarified_task"]
        if not explicit_loop and dec["rec_loop"]:
            loop_name = dec["rec_loop"]
        intake_bundle = {"result": dec["result"], "status": dec["status"],
                         "answers": dec["answers"], "raw_task": raw_task,
                         "clarified_task": task}

    loop = REGISTRY.get_loop(loop_name or loop_registry.DEFAULT_LOOP)
    if loop is None:
        print(f"ERROR: no loop named '{loop_name}'. Try: python main.py --loops",
              file=sys.stderr)
        return 1
    roles, role_errors = loop_engine_mod.resolve_roles(loop, AGENTS, overrides)
    if role_errors:
        print(f"ERROR: could not resolve agents: {role_errors}", file=sys.stderr)
        return 1

    return _execute_run(conn, task, loop, ws, roles, overrides, approval_engine,
                        min_conf, commit, commit_message, replay_request=None,
                        memory_mode=memory_mode, memory_limit=memory_limit,
                        context_mode=context_mode, context_max_files=context_max_files,
                        context_max_chars=context_max_chars, context_files=context_files,
                        intake_bundle=intake_bundle, external_coder=external_coder)


if __name__ == "__main__":
    raise SystemExit(main())
