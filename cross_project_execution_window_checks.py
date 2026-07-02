"""Stage 12.2 — Deterministic Execution Window Checks."""

import datetime
from dataclasses import dataclass

import database
import cross_project_execution_windows as windows_mod


@dataclass
class CrossProjectExecutionWindowCheck:
    id: int
    run_id: int
    run_step_id: int
    window_id: int
    status: str
    reason: str
    checked_at: str


def check_from_row(row):
    return CrossProjectExecutionWindowCheck(
        id=row["id"], run_id=row["run_id"], run_step_id=row["run_step_id"],
        window_id=row["window_id"], status=row["status"] or "",
        reason=row["reason"] or "", checked_at=row["checked_at"] or "")


def _now():
    return datetime.datetime.now()


def _evaluate(window, now):
    """Pure evaluation of a single window at a moment in time.

    Statuses: open | closed | not_started | expired | missing.
    Operator open/close is authoritative; optional time bounds narrow an
    open window. No window is ever active without an operator open action.
    """
    if window is None:
        return "missing", "no execution window is defined for this run"
    if window.status == "defined":
        return "closed", f"window {window.id} has not been opened by an operator"
    if window.status == "closed":
        return "closed", f"window {window.id} was closed by an operator"
    if window.status != "open":
        return "closed", f"window {window.id} has unknown status '{window.status}'"
    if window.starts_at:
        starts = datetime.datetime.fromisoformat(window.starts_at)
        if now < starts:
            return "not_started", f"window {window.id} starts at {window.starts_at}"
    if window.ends_at:
        ends = datetime.datetime.fromisoformat(window.ends_at)
        if now > ends:
            return "expired", f"window {window.id} ended at {window.ends_at}"
    return "open", f"window {window.id} is open"


def select_window(windows, now):
    """Pick the governing window: the first open one, else the newest."""
    window, status, reason = None, "missing", (
        "no execution window is defined for this run")
    for candidate in windows:
        candidate_status, candidate_reason = _evaluate(candidate, now)
        if window is None:
            window, status, reason = candidate, candidate_status, candidate_reason
        if candidate_status == "open":
            return candidate, candidate_status, candidate_reason
    return window, status, reason


class CrossProjectExecutionWindowChecker:
    def __init__(self, conn):
        self.conn = conn
        self.windows = windows_mod.CrossProjectExecutionWindowManager(conn)

    def check(self, run_id, run_step_id=None, now=None):
        run = database.get_cross_project_orchestration_run(self.conn, int(run_id))
        if run is None:
            raise ValueError(f"no cross-project orchestration run {run_id}")
        moment = now or _now()
        windows = self.windows.list_windows(run_id=run["id"], limit=200)
        window, status, reason = select_window(windows, moment)
        check_id = database.save_cross_project_execution_window_check(
            self.conn, run["id"], run_step_id,
            window.id if window else None, status, reason,
            moment.isoformat(timespec="seconds"))
        return check_from_row(database.get_cross_project_execution_window_check(
            self.conn, check_id))
