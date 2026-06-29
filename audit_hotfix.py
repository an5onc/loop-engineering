"""Stage 3.2.1 hotfix regression audit (local, non-destructive, no cloud/Ollama).

Runs deterministic checks for every audit finding fixed in this stage:
  1. python3 -c (and unsafe -m) is blocked; safe forms allowed.
  2. python3 main.py --help / -h prints usage and exits 0.
  3. prompt_design / loop_design do not write files / run commands / commit.
  4. command-only test_fix does not fail solely from the files_written gate.
  5. external handoff prompts include --resume instructions.
  6. stale __pycache__ does not block a resume; a protected .env does.

Usage:  python3 audit_hotfix.py
Exit 0 if all checks pass, 1 otherwise.
"""

import os
import subprocess
import sys
import tempfile

import external_agents as ea
import loop_registry
import project_workspace as pw
import stop_conditions as sc
import terminal

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _ctx(**over):
    """Build an EvalContext with safe defaults, overriding selected fields."""
    base = dict(attempt=1, max_attempts=1, loop_name="code_build",
                fs_enabled=True, term_enabled=True, review_only=False,
                coder_parse_ok=True, proposed_file_count=0, files_changed=0,
                unsafe_path_count=0, unsafe_command_count=0, commands_executed=0,
                commands_failed=0, command_timed_out=0, review_parse_ok=True,
                review_approved=True, review_confidence=0.9,
                min_reviewer_confidence=0.6, analyst_used=False,
                analyst_parse_ok=True, tests_run=False, tests_passed=None,
                repeated_failure=False)
    base.update(over)
    return sc.EvalContext(**base)


def audit_python_c_blocked():
    blocked = [
        'python3 -c "print(123)"',
        'python -c "print(123)"',
        "python3 -c \"__import__('pathlib').Path('/tmp/x.txt').write_text('e')\"",
        "python3 /tmp/safe.py",
        "python3 ../safe.py",
        "python3 -m http.server",
        "python3",
    ]
    allowed = [
        "python3 workspace/safe.py",
        "python3 safe.py",
        "python3 -m unittest test_x.py",
        "python3 -m pytest tests/test_x.py",
        "pytest tests/test_x.py",
    ]
    for c in blocked:
        check(f"blocked: {c}", not terminal.is_safe_command(c))
    for c in allowed:
        check(f"allowed: {c}", terminal.is_safe_command(c))


def audit_help():
    for flag in ("--help", "-h"):
        p = subprocess.run([sys.executable, "main.py", flag],
                           capture_output=True, text=True, timeout=30,
                           cwd=os.path.dirname(os.path.abspath(__file__)))
        ok = p.returncode == 0 and "USAGE" in p.stdout and "--resume" in p.stdout
        check(f"main.py {flag} prints usage, exit 0", ok,
              f"exit={p.returncode}")


def audit_design_loops_no_side_effects():
    reg = loop_registry.LoopRegistry()
    for name in ("prompt_design", "loop_design"):
        lp = reg.get_loop(name)
        ok = (not lp.filesystem_enabled and not lp.terminal_enabled
              and not getattr(lp, "git_enabled", False))
        check(f"{name}: no fs/terminal/git tools", ok,
              f"fs={lp.filesystem_enabled} term={lp.terminal_enabled}")
    # files_written gate is n/a for design loops (fs disabled).
    eng = sc.StopConditionEngine.for_loop(reg.get_loop("prompt_design"))
    ctx = _ctx(loop_name="prompt_design", fs_enabled=False, term_enabled=False)
    res = {g.gate_name: g.passed for g in eng.evaluate_gates(ctx)}
    check("prompt_design files_written gate n/a (passes)",
          res.get("files_written", True))


def audit_test_fix_command_only_gate():
    reg = loop_registry.LoopRegistry()
    eng = sc.StopConditionEngine.for_loop(reg.get_loop("test_fix"))
    # Command-only run: fs enabled, no files written, but a command executed.
    ctx = _ctx(loop_name="test_fix", files_changed=0, commands_executed=1)
    gates = {g.gate_name: g.passed for g in eng.evaluate_gates(ctx)}
    check("test_fix command-only does not fail files_written",
          gates.get("files_written", False))


def audit_handoff_has_resume():
    for adapter in (ea.ClaudeCodeAdapter(), ea.CodexAdapter()):
        req = ea.ExternalAgentRequest(42, 1, adapter.name, "t", "p", "ws", "/x",
                                      ["workspace"], ["workspace"])
        prompt, _, _ = adapter.build_handoff(req)
        check(f"{adapter.name} handoff has exact '## Completion Response JSON'",
              "## Completion Response JSON" in prompt)
        check(f"{adapter.name} handoff has '## How to Resume This Loop'",
              "## How to Resume This Loop" in prompt)
        check(f"{adapter.name} handoff shows '--resume 42' as preferred",
              "--resume 42" in prompt
              and prompt.index("--resume 42") < prompt.index("--import-external-completion 42"))
        check(f"{adapter.name} handoff keeps --import-external-completion as backward-compatible",
              "Backward-compatible" in prompt and "--import-external-completion 42" in prompt)


def audit_reviewer_consistency_gate():
    reg = loop_registry.LoopRegistry()
    eng = sc.StopConditionEngine.for_loop(reg.get_loop("loop_design"))
    # Contradictory: approved=True but confidence 0.0 -> gate fails, not APPROVED.
    bad = _ctx(loop_name="loop_design", fs_enabled=False, term_enabled=False,
               review_approved=True, review_confidence=0.0,
               min_reviewer_confidence=0.6, review_required_changes=0)
    gates = {g.gate_name: g.passed for g in eng.evaluate_gates(bad)}
    check("reviewer_consistency_valid gate exists",
          "reviewer_consistency_valid" in gates)
    check("contradictory approved+confidence=0.0 fails consistency gate",
          gates.get("reviewer_consistency_valid") is False)
    decision = eng.decide(bad, eng.evaluate_gates(bad), eng.evaluate_conditions(bad))
    check("contradictory review -> not APPROVED (REVIEW_INCONSISTENT)",
          decision.final_status == "REVIEW_INCONSISTENT", decision.final_status)
    # Consistent approval passes.
    good = _ctx(loop_name="loop_design", fs_enabled=False, term_enabled=False,
                review_approved=True, review_confidence=0.9,
                min_reviewer_confidence=0.6, review_required_changes=0)
    gg = {g.gate_name: g.passed for g in eng.evaluate_gates(good)}
    check("consistent approval passes consistency gate",
          gg.get("reviewer_consistency_valid") is True)


def audit_test_fix_no_hang():
    # The deterministic fallback + smoke-test detection must not depend on a
    # model: verify the markers and the safe fallback command directly.
    import loop_engine as le
    check("smoke-test task detected",
          le._is_smoke_test_task("Run a safe smoke test command using an allowed test command"))
    check("non-smoke task not misdetected",
          not le._is_smoke_test_task("Refactor the database module for clarity"))
    check("fallback command is terminal-safe",
          terminal.is_safe_command(le.SAFE_FALLBACK_COMMAND), le.SAFE_FALLBACK_COMMAND)


def audit_stale_report_path():
    import main
    check("missing absolute report path flagged, no crash",
          "non-portable" in main._report_path_display("/nonexistent/repo/reports/loop_9.md"))
    check("None report path -> (none)",
          main._report_path_display(None) == "(none)")


def audit_snapshot_delta():
    proj = tempfile.mkdtemp()
    mgr = pw.WorkspaceManager()
    ws = mgr.create_workspace("audit_snap", proj)
    wb = mgr.write_base(ws)
    # Stale generated artifact present BEFORE handoff.
    os.makedirs(os.path.join(wb, "src", "__pycache__"), exist_ok=True)
    open(os.path.join(wb, "src", "__pycache__", "stale.pyc"), "w").write("S")
    open(os.path.join(wb, "existing.py"), "w").write("print(1)\n")
    snap = ea.workspace_snapshot(ws)

    # Agent adds a real file + a new generated artifact.
    open(os.path.join(wb, "helper.py"), "w").write("def h():\n    return 1\n")
    os.makedirs(os.path.join(wb, "__pycache__"), exist_ok=True)
    open(os.path.join(wb, "__pycache__", "new.pyc"), "w").write("N")
    d = ea.compute_external_deltas(snap, ws)
    check("stale + new __pycache__ produce no violations",
          not d["violations"], f"violations={d['violations']}")
    check("real helper.py counted as a change", "helper.py" in d["changed"])

    # Protected .env added after handoff -> violation.
    open(os.path.join(wb, ".env"), "w").write("SECRET=1\n")
    d2 = ea.compute_external_deltas(snap, ws)
    check(".env after handoff is a violation",
          any(p.endswith(".env") for p in d2["violations"]),
          f"violations={d2['violations']}")


def main():
    print("Stage 3.2.1 / 3.2.2 hotfix audit")
    print("- terminal safety (python -c / -m)")
    audit_python_c_blocked()
    print("- --help")
    audit_help()
    print("- design loops")
    audit_design_loops_no_side_effects()
    print("- command-only test_fix gate")
    audit_test_fix_command_only_gate()
    print("- handoff resume instructions")
    audit_handoff_has_resume()
    print("- external delta / snapshot")
    audit_snapshot_delta()
    print("- reviewer consistency")
    audit_reviewer_consistency_gate()
    print("- command-only test_fix does not hang")
    audit_test_fix_no_hang()
    print("- stale/missing report paths")
    audit_stale_report_path()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
