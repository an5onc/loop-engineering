"""Run Report system (Stage 2.3).

Reads a completed loop's data from SQLite and renders a human-readable Markdown
report into reports/. Reports are read-only summaries: this module never runs
commands, never writes outside reports/, and report paths are generated
internally (never taken from model output).
"""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass
from typing import List, Optional

import database

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")


@dataclass
class RunReport:
    loop_id: int
    report_path: str
    report_format: str
    content_hash: str
    bytes_written: int
    created_at: str


def _now_stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _preview(text: str, max_lines: int = 6, max_chars: int = 600) -> str:
    text = (text or "").strip()
    if not text:
        return "(none)"
    lines = text.splitlines()[:max_lines]
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars] + " …"
    return out


class ReportGenerator:
    def __init__(self, conn):
        self.conn = conn

    # --- paths ----------------------------------------------------------- #
    def report_path_for(self, loop_id: int) -> str:
        """Internally generated, sandboxed path under reports/."""
        os.makedirs(REPORTS_DIR, exist_ok=True)
        fname = f"loop_{int(loop_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, fname))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("report path escaped reports/ (refusing)")
        return target

    def get_report_path(self, loop_id: int) -> Optional[str]:
        row = database.get_run_report(self.conn, loop_id)
        return row["report_path"] if row else None

    def list_reports(self, limit: int = 20):
        return database.list_run_reports(self.conn, limit)

    def save_report(self, loop_id: int, content: str) -> str:
        path = self.report_path_for(loop_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    # --- next-step heuristic --------------------------------------------- #
    @staticmethod
    def _next_step(status: str, stop_reason: str, ws_name: str) -> str:
        s = (status or "").upper()
        if s == "APPROVED":
            return (f"Review the changes in workspace '{ws_name}' and commit them "
                    "(re-run with --commit) if they look correct.")
        if s == "NEEDS_HUMAN":
            return ("Human approval was declined. Re-run and approve the action, or "
                    "adjust the task so the change is acceptable.")
        if s == "BLOCKED":
            if "profile" in (stop_reason or ""):
                return "Register or repair the workspace profile, then re-run."
            return ("A safety rule blocked the run. Adjust the task or widen the "
                    "workspace permissions intentionally, then re-run.")
        if s == "REJECTED":
            return ("Tests or review did not pass after retries. Inspect the failing "
                    "output above and refine the task or increase max retries.")
        return "Inspect the report above and decide whether to re-run."

    # --- markdown -------------------------------------------------------- #
    def generate_markdown_report(self, loop_id: int) -> str:
        c = self.conn
        loop = database.get_loop(c, loop_id)
        if loop is None:
            raise ValueError(f"no loop with id {loop_id}")
        steps = database.get_steps(c, loop_id)
        reviews = database.get_reviews(c, loop_id)
        fops = database.get_file_operations(c, loop_id)
        cmds = database.get_command_results(c, loop_id)
        metrics = database.get_metrics(c, loop_id)
        git_events = database.get_git_events(c, loop_id)
        agent_events = database.get_agent_events(c, loop_id)
        approvals = database.get_approval_events(c, loop_id)
        gates = database.get_quality_gate_results(c, loop_id)
        stops = database.get_stop_condition_results(c, loop_id)
        mvals = {m["metric_name"]: (m["metric_text"] if m["metric_text"] is not None
                                    else m["metric_value"]) for m in metrics}

        replays = database.get_replay_events_for_new_loop(c, loop_id)

        L = []
        a = L.append
        a("# Loop Run Report\n")

        if replays:
            rp = replays[-1]
            a("> **Replay run** — reconstructed from a previous loop.")
            a(f"> - Source loop ID: {rp['source_loop_id']}")
            a(f"> - Replay mode: {rp['replay_mode']}\n")

        a("## Summary")
        a(f"- Loop ID: {loop['id']}")
        a(f"- Task: {loop['task']}")
        a(f"- Status: {loop['status']}")
        a(f"- Stop reason: {loop['stop_reason']}")
        a(f"- Loop type: {loop['loop_type']}")
        a(f"- Loop version: {loop['loop_version']}")
        a(f"- Workspace: {loop['workspace_name']} (root: {loop['workspace_root']})")
        profile_name = "sandbox"
        wrow = database.get_project_workspace(c, loop["workspace_name"]) if loop["workspace_name"] else None
        if wrow is not None and "profile_name" in wrow.keys() and wrow["profile_name"]:
            profile_name = wrow["profile_name"]
        a(f"- Workspace profile: {profile_name}")
        a(f"- Created at: {loop['created_at']}")
        dur = loop['total_duration_seconds']
        a(f"- Total duration: {dur:.2f}s" if dur is not None else "- Total duration: n/a")
        a(f"- Retry count: {loop['retry_count']}")
        if str(mvals.get("deterministic_test_fix_fallback_used", "0")) in ("1", "1.0", "True"):
            a(f"- Deterministic test_fix fallback: used (ran a known safe command)")
        if str(mvals.get("model_call_timeout", "0")) in ("1", "1.0", "True"):
            a(f"- Model call timeout: yes (loop stopped on a model timeout)")
        a("")

        pid = loop["project_intelligence_report_id"] if "project_intelligence_report_id" in loop.keys() else None
        if pid:
            prow = database.get_project_intelligence_report(c, int(pid))
            a("## Project Intelligence")
            a(f"- Report ID: {pid}")
            if prow is not None:
                import json as _json
                rj = _json.loads(prow["report_json"] or "{}")
                st = rj.get("structure", {})
                a(f"- Workspace: {prow['workspace_name']}")
                a(f"- Languages: {', '.join(st.get('languages_detected', [])) or '(none)'}")
                a(f"- Important files: {', '.join(st.get('important_files', [])[:10]) or '(none)'}")
                a(f"- Test files: {', '.join(st.get('test_files', [])[:10]) or '(none)'}")
                a(f"- Config files: {', '.join(st.get('config_files', [])[:10]) or '(none)'}")
                a(f"- Warnings: {', '.join(rj.get('warnings', [])) or '(none)'}")
                a(f"- Recommendations: {', '.join(rj.get('recommendations', [])) or '(none)'}")
            a("")

        resume_events = database.get_resume_events(c, loop_id)
        if resume_events:
            r = resume_events[-1]
            a("## Resume Events")
            a(f"- Resume type: {r['resume_type']}")
            a(f"- Completion imported: {bool(r['completion_imported'])}")
            a(f"- Status before: {r['status_before']}")
            a(f"- Status after: {r['status_after']}")
            a(f"- Stop reason: {r['stop_reason']}")
            a(f"- Commit requested: {bool(r['commit_requested'])}")
            a(f"- Commit created: {bool(r['commit_created'])}")
            a(f"- Report path: {r['report_path'] or '(none)'}")
            a("")

        job = database.get_external_agent_job_for_loop(c, loop_id)
        if job is not None:
            a("## External Agent Job")
            a(f"- Job ID: {job['id']}")
            a(f"- Agent: {job['external_agent_name']}")
            a(f"- Status: {job['status']}")
            import json as _json2
            _kk = job.keys()
            _lbls = []
            if "labels_json" in _kk and job["labels_json"]:
                try:
                    _lbls = _json2.loads(job["labels_json"])
                except (ValueError, TypeError):
                    _lbls = []
            a(f"- Priority: {(job['priority'] if 'priority' in _kk else None) or 'normal'}")
            a(f"- Labels: {', '.join(_lbls) or '(none)'}")
            a(f"- Notes: {(job['notes'] if 'notes' in _kk else '') or '(none)'}")
            a(f"- Archived: {bool(job['archived'] if 'archived' in _kk else 0)}")
            a(f"- Retry count: {(job['retry_count'] if 'retry_count' in _kk else 0) or 0}")
            a(f"- Last error: {(job['last_error'] if 'last_error' in _kk else None) or '(none)'}")
            a(f"- Completed at: {(job['completed_at'] if 'completed_at' in _kk else None) or '(none)'}")
            a(f"- Cancelled at: {(job['cancelled_at'] if 'cancelled_at' in _kk else None) or '(none)'}")
            a(f"- Archived at: {(job['archived_at'] if 'archived_at' in _kk else None) or '(none)'}")
            a(f"- Workspace: {job['workspace_name']} ({job['workspace_root']})")
            a(f"- Handoff path: {job['handoff_path'] or '(none)'}")
            a(f"- Packet path: {job['packet_path'] or '(none)'}")
            a(f"- Completion path: {job['completion_path'] or '(none)'}")
            a(f"- Resume command: python3 main.py --resume-external-job {job['id']} "
              f"--external-completion-file completion.json")
            jevs = database.get_external_agent_job_events(c, job["id"])
            if jevs:
                a("- Job events:")
                for je in jevs:
                    a(f"  - {je['created_at']} {je['event_type']} "
                      f"{je['status_before']} -> {je['status_after']}")
            ibx = database.get_external_completion_inbox_events(c, job["id"])
            if ibx:
                a(f"- Completion inbox path: {ibx[-1]['completion_path'] or '(none)'}")
                a("- Completion inbox events:")
                for e in ibx:
                    a(f"  - {e['created_at']} {e['action']} status={e['status']}"
                      f"{' (dry-run)' if e['dry_run'] else ''}"
                      f"{('  error=' + e['error']) if e['error'] else ''}")
            bev = database.get_external_job_batch_events(c, job_id=job["id"], limit=10)
            if bev:
                a("- Batch events:")
                for e in bev:
                    verdict = "skipped" if e["skipped"] else ("ok" if e["success"] else "FAILED")
                    a(f"  - {e['created_at']} {e['action']} {verdict}"
                      f"{' (dry-run)' if e['dry_run'] else ''}"
                      f"{('  error=' + e['error']) if e['error'] else ''}")
            health = database.get_external_job_health_events(c, job_id=job["id"], limit=10)
            if health:
                a("- Health events:")
                for h in health:
                    fixed = " fixed" if h["fixed"] else ""
                    a(f"  - {h['created_at']} [{h['severity']}] "
                      f"{h['issue_type']}{fixed}: {h['message']}")
                    a(f"    action: {h['recommended_action']}")
            a("")

        ext_events = database.get_external_agent_events(c, loop_id)
        if ext_events:
            e = ext_events[-1]
            import json as _json
            fc = _json.loads(e["files_changed_json"] or "[]")
            a("## External Coding Agent")
            a(f"- Agent name: {e['external_agent_name']}")
            a(f"- Mode: {e['mode']}")
            a(f"- Handoff path: {e['handoff_path']}")
            a(f"- Completed: {bool(e['completed'])}")
            a(f"- Success: {bool(e['success'])}")
            a(f"- Files changed: {len(fc)}" + (f" ({', '.join(fc[:8])})" if fc else ""))
            a(f"- Summary: {e['summary'] or '(none)'}")
            a(f"- Error: {e['error'] or '(none)'}")
            if ("completion_imported_at" in e.keys()) and e["completion_imported_at"]:
                cj = _json.loads(e["completion_json"] or "{}")
                a(f"- Completion imported: True")
                a(f"- Completion parsed: {bool(e['completion_parsed'])}")
                a(f"- Completion status: {e['completion_status']}")
                a(f"- Completion summary: {cj.get('summary', '')}")
                a(f"- Claimed files changed: {cj.get('files_changed', [])}")
                a(f"- Claimed commands run: {cj.get('commands_run', [])}")
                a(f"- Claimed tests: {cj.get('tests_run', [])}")
                a(f"- Tests passed: {cj.get('tests_passed')}")
                a(f"- Completion issues: {cj.get('issues', [])}")
                a(f"- Completion notes: {cj.get('notes', [])}")
                a(f"- Completion next steps: {cj.get('next_steps', [])}")
            else:
                a("- Completion imported: False")
            a("")

        intake_events = database.get_task_intake_events(c, loop_id)
        if intake_events:
            ie = intake_events[-1]
            a("## Task Intake")
            a(f"- Raw task: {ie['raw_task']}")
            a(f"- Clarified task: {ie['clarified_task']}")
            a(f"- Intent summary: {ie['intent_summary']}")
            a(f"- Detected loop type: {ie['detected_loop_type']}")
            a(f"- Confidence: {ie['confidence_score']}")
            a(f"- Ambiguity: {ie['ambiguity_score']}")
            a(f"- Risk level: {ie['risk_level']}")
            import json as _json
            md = _json.loads(ie["missing_details_json"] or "[]")
            asm = _json.loads(ie["assumptions_json"] or "[]")
            a(f"- Missing details: {', '.join(md) if md else '(none)'}")
            a(f"- Assumptions: {', '.join(asm) if asm else '(none)'}")
            qs = _json.loads(ie["clarification_questions_json"] or "[]")
            ans = _json.loads(ie["clarification_answers_json"] or "{}") if ie["clarification_answers_json"] else {}
            if qs:
                a("- Clarification:")
                for q in qs:
                    a(f"  - Q ({q.get('id')}): {q.get('question')}  → A: {ans.get(q.get('id'), '(unanswered)')}")
            a(f"- Intake status: {ie['status']}")
            a("")

        cpid = loop["context_pack_id"] if "context_pack_id" in loop.keys() else None
        if cpid:
            cp = database.get_context_pack_by_id(c, int(cpid))
            cpf = database.get_context_pack_files(c, int(cpid))
            a("## Context Pack")
            a(f"- Context pack ID: {cpid}")
            if cp is not None:
                a(f"- Files included: {cp['total_files_included']} / "
                  f"{cp['total_files_considered']} considered")
                a(f"- Total chars: {cp['total_chars']}")
                a(f"- Truncated: {bool(cp['truncated'])}")
                for f in cpf:
                    a(f"  - {f['path']} ({f['detected_language']}) — {f['reason']}"
                      f"{' [truncated]' if f['truncated'] else ''}")
                import json as _json
                w = _json.loads(cp["warnings_json"] or "[]")
                a(f"- Warnings: {', '.join(w) if w else '(none)'}")
            a("")

        mem_events = database.get_memory_search_events(c, loop_id)
        if mem_events:
            me = mem_events[-1]
            a("## Memory Context")
            a(f"- Query: {me['query']}")
            a(f"- Result count: {me['result_count']}")
            a(f"- Injected into Supervisor prompt: {bool(me['used_for_context'])}")
            try:
                import json as _json
                tops = _json.loads(me["top_results_json"] or "[]")
            except (ValueError, TypeError):
                tops = []
            if tops:
                a("- Top relevant past items:")
                for t in tops[:5]:
                    a(f"  - [{t.get('source_type')}] {t.get('title')}")
            a("")

        if loop["template_name"]:
            a("## Template")
            a(f"- Template name: {loop['template_name']}")
            a(f"- Template version: {loop['template_version']}")
            a(f"- Variables: {loop['template_variables_json']}")
            a(f"- Rendered task: {loop['rendered_task']}\n")

        a("## Agents")
        a(f"- Supervisor: {mvals.get('supervisor_agent','supervisor')} / {loop['supervisor_model']}")
        a(f"- Coder: {mvals.get('coder_agent','coder')} / {loop['coder_model']}")
        a(f"- Reviewer: {mvals.get('reviewer_agent','reviewer')} / {loop['reviewer_model']}")
        if mvals.get("test_analyst_used") in (1, 1.0):
            a(f"- Test Analyst: {mvals.get('test_analyst_agent','test_analyst')} / "
              f"{mvals.get('test_analyst_model','')}")
        a("")

        plan = next((s["response"] for s in steps if s["step_name"] == "supervisor_plan"), "")
        a("## Plan")
        a(_preview(plan, max_lines=40, max_chars=4000))
        a("")

        a("## Attempts")
        attempts = sorted({s["attempt_number"] for s in steps if s["attempt_number"]})
        for n in attempts:
            a(f"### Attempt {n}")
            af = [f for f in fops if f["attempt_number"] == n]
            ac = [x for x in cmds if x["attempt_number"] == n]
            a(f"- Files written: {sum(1 for f in af if f['allowed'] and f['operation'] in ('create','update'))}")
            a(f"- Files blocked: {sum(1 for f in af if not f['allowed'])}")
            a(f"- Commands executed: {sum(1 for x in ac if x['allowed'])}")
            a(f"- Commands blocked: {sum(1 for x in ac if not x['allowed'])}")
            ta = next((s for s in steps if s["attempt_number"] == n
                       and s["step_name"] == "test_analysis"), None)
            if ta is not None:
                a(f"- Test analyst: ran ({ta['latency_seconds']:.2f}s)")
            rv = next((r for r in reviews if r["attempt_number"] == n), None)
            if rv is not None:
                a(f"- Reviewer: approved={bool(rv['approved'])} "
                  f"confidence={rv['confidence_score']}")
            ag = [g for g in gates if g["attempt_number"] == n and not g["passed"]]
            if ag:
                a(f"- Failed gates: {', '.join(g['gate_name'] for g in ag)}")
            ast = [s for s in stops if s["attempt_number"] == n and s["triggered"]]
            if ast:
                a(f"- Triggered stop conditions: {', '.join(s['condition_name'] for s in ast)}")
            a("")

        a("## Final Review")
        fr = reviews[-1] if reviews else None
        if fr is not None:
            a(f"- Approved: {bool(fr['approved'])}")
            a(f"- Summary: {fr['summary']}")
            a(f"- Issues: {fr['issues_json']}")
            a(f"- Required changes: {fr['required_changes_json']}")
            a(f"- Confidence score: {fr['confidence_score']}")
        else:
            a("- (no review recorded)")
        a("")

        a("## Files Changed")
        if not fops:
            a("- (none)")
        for f in fops:
            flag = "allowed" if f["allowed"] else f"BLOCKED ({f['reason_if_blocked']})"
            a(f"- `{f['path']}` — {f['operation']}, {flag}, "
              f"{f['bytes_written']} bytes, sha {(f['content_hash'] or '')[:12]}")
        a("")

        a("## Commands")
        if not cmds:
            a("- (none)")
        for x in cmds:
            if not x["allowed"]:
                a(f"- `{x['command']}` — BLOCKED ({x['reason_if_blocked']})")
            else:
                st = "TIMED OUT" if x["timed_out"] else f"exit {x['exit_code']}"
                a(f"- `{x['command']}` — {st}, {x['duration_seconds']:.2f}s")
                if (x["stdout"] or "").strip():
                    a(f"  - stdout: `{_preview(x['stdout'], 3, 200)}`")
                if (x["stderr"] or "").strip():
                    a(f"  - stderr: `{_preview(x['stderr'], 3, 200)}`")
        a("")

        a("## Approvals")
        if not approvals:
            a("- (none)")
        for ap in approvals:
            verdict = "APPROVED" if ap["approved"] else "DECLINED"
            a(f"- {ap['action_type']} (risk {ap['risk_level']}): {verdict} "
              f"[{ap['decision']}] — {ap['reason']}")
        a("")

        a("## Git")
        a(f"- Repo: {int(mvals.get('git_is_repo', 0)) == 1}")
        a(f"- Workspace changed: {int(mvals.get('git_workspace_changed', 0)) == 1}")
        a(f"- Commit attempted: {int(mvals.get('git_commit_attempted', 0)) == 1}")
        a(f"- Commit success: {int(mvals.get('git_commit_success', 0)) == 1}")
        if git_events:
            a("- Events:")
            for g in git_events:
                a(f"  - {g['event_type']}: `{g['command']}` (exit {g['exit_code']})")
        a("")

        a("## Metrics")
        for name in ("total_duration_seconds", "plan_latency_seconds",
                     "plan_prompt_tokens", "plan_output_tokens", "attempts",
                     "retry_count", "total_files_changed", "commands_executed",
                     "commands_blocked", "tests_passed", "quality_gates_passed",
                     "quality_gates_failed", "required_quality_gates_failed",
                     "stop_conditions_triggered", "final_stop_condition",
                     "approval_requests_count", "approval_approved_count",
                     "approval_declined_count"):
            if name in mvals:
                a(f"- {name}: {mvals[name]}")
        a("")

        a("## Outcome")
        status = loop["status"]
        a(f"- Final status: {status}")
        n_written = sum(1 for f in fops if f["allowed"] and f["operation"] in ("create", "update"))
        n_blocked = sum(1 for f in fops if not f["allowed"])
        n_declined = sum(1 for ap in approvals if not ap["approved"])
        a(f"- Succeeded: {'yes' if status == 'APPROVED' else 'no'} "
          f"({n_written} file(s) written)")
        a(f"- Skipped/blocked: {n_blocked} file op(s), {n_declined} declined approval(s)")
        needs_human = status in ("NEEDS_HUMAN", "BLOCKED")
        a(f"- Human action needed: {'yes' if needs_human else 'no'}")
        a("")

        a("## Suggested Next Step")
        a(self._next_step(status, loop["stop_reason"], loop["workspace_name"] or "default"))
        a("")

        return "\n".join(L)
