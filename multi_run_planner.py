"""Stage 14.4 — Deterministic Multi-Run Advancement Planner (advisory)."""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field

import database
import cross_project_orchestration_runs as runs_mod
import multi_run_readiness as readiness_mod
import multi_run_sessions as sessions_mod


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "multi_run_planner_reports")


@dataclass
class MultiRunPlannerResult:
    id: int
    session_id: int
    generated_at: str
    status: str
    selected_run_id: int
    selected_run_step_id: int
    reason: str
    required_command: str
    skipped: list = field(default_factory=list)
    safety_notes: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class MultiRunAdvancementPlanner:
    """Chooses the next safest operator action across member runs.

    Advisory text only: the planner never executes, confirms, snapshots,
    opens windows, requests retries, or restores.
    """

    def __init__(self, conn):
        self.conn = conn
        self.sessions = sessions_mod.MultiRunSessionManager(conn)
        self.runs = runs_mod.CrossProjectOrchestrationRunManager(conn)

    def plan(self, session_id, now=None):
        session = self.sessions.get_session(int(session_id))
        if session is None:
            raise ValueError(f"no multi-run session {session_id}")
        members = sorted(self.sessions.active_members(session.id),
                         key=lambda m: m.run_id)
        entries, skipped = [], []
        for member in members:
            run = self.runs.get_run(member.run_id)
            if run is None:
                skipped.append({"run_id": member.run_id,
                                "reason": "run no longer exists"})
                continue
            entry = readiness_mod.assess_run(self.conn, run, now=now)
            if entry["status"] == "completed":
                skipped.append({"run_id": run.id, "reason": "run completed"})
                continue
            entries.append(entry)
        selection = self._select(session, entries, skipped)
        result_id = database.save_multi_run_planner_report(
            self.conn, session.id, _now_iso(), selection["status"],
            selection["selected_run_id"], selection["selected_run_step_id"],
            selection["reason"], selection["required_command"],
            json.dumps(skipped, sort_keys=True),
            json.dumps(_safety_notes(), sort_keys=True))
        return MultiRunPlannerResult(
            id=result_id, session_id=session.id, generated_at=_now_iso(),
            status=selection["status"],
            selected_run_id=selection["selected_run_id"],
            selected_run_step_id=selection["selected_run_step_id"],
            reason=selection["reason"],
            required_command=selection["required_command"], skipped=skipped,
            safety_notes=_safety_notes())

    def _select(self, session, entries, skipped):
        for status, verb in (("needs_restoration", "restoration"),
                             ("needs_retry_authorization",
                              "retry authorization")):
            for entry in sorted(entries, key=lambda e: e["run_id"]):
                if entry["status"] == status:
                    return {
                        "status": "recovery_required",
                        "selected_run_id": None,
                        "selected_run_step_id": None,
                        "reason": (f"run {entry['run_id']} needs {verb} before "
                                   "any step may execute"),
                        "required_command": entry["next_action"],
                    }
        candidates = [e for e in sorted(entries, key=lambda e: e["run_id"])
                      if e["status"] in ("ready", "needs_open_window",
                                         "needs_confirmation",
                                         "needs_snapshot")
                      and e["pending_steps"] > 0]
        for entry in candidates:
            run = self.runs.get_run(entry["run_id"])
            step = min((s for s in run.steps if s.status == "pending"),
                       key=lambda s: (s.sequence_number, s.id))
            command = entry["next_action"].replace(
                "SESSION_ID", str(session.id))
            reason = (f"first pending step by run id then step id; readiness "
                      f"is '{entry['status']}'")
            return {
                "status": "selected" if entry["status"] == "ready"
                          else "controls_required",
                "selected_run_id": run.id,
                "selected_run_step_id": step.id,
                "reason": reason,
                "required_command": command,
            }
        reasons = [f"run {e['run_id']}: {e['status']} — {e['next_action']}"
                   for e in entries]
        reasons.extend(f"run {s['run_id']}: skipped — {s['reason']}"
                       for s in skipped)
        return {
            "status": "blocked" if entries or skipped else "empty",
            "selected_run_id": None,
            "selected_run_step_id": None,
            "reason": "; ".join(reasons) or "session has no member runs",
            "required_command": (
                "add member runs (--add-run-to-multi-run-session)"
                if not entries and not skipped else
                "review readiness (--multi-run-readiness)"),
        }

    def save_markdown_report(self, result):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            REPORTS_DIR, f"multi_run_planner_{int(result.id)}_{_now_stamp()}.md"))
        base = os.path.realpath(REPORTS_DIR)
        if not path.startswith(base + os.sep):
            raise ValueError("planner report path escaped directory")
        content = self.render_markdown(result)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_multi_run_planner_markdown_report(
            self.conn, result.id, path, "markdown",
            hashlib.sha256(encoded).hexdigest(), len(encoded))
        return path

    def render_markdown(self, result):
        lines = [
            "# Multi-Run Advancement Plan", "",
            f"- Planner ID: {result.id}",
            f"- Session ID: {result.session_id}",
            f"- Status: {result.status}",
            f"- Selected run: {result.selected_run_id or '-'}",
            f"- Selected run step: {result.selected_run_step_id or '-'}",
            f"- Reason: {result.reason}",
            f"- Required command: {result.required_command}",
        ]
        if result.skipped:
            lines.extend(["", "## Skipped"])
            for entry in result.skipped:
                lines.append(f"- Run {entry['run_id']}: {entry['reason']}")
        return "\n".join(lines)


def _safety_notes():
    return [
        "Planner output is advisory text only; nothing was executed.",
        "The planner never creates confirmations, snapshots, windows, "
        "retries, or restores.",
        "At most one step is ever recommended per invocation.",
    ]
