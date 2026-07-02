"""Stage 12.1 — Execution Window Open/Close Controls."""

import datetime

import database
import cross_project_execution_windows as windows_mod


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


class CrossProjectExecutionWindowControlGate:
    """One-way operator transitions: defined -> open -> closed.

    A closed window can never reopen; define a new window instead.
    """

    def __init__(self, conn):
        self.conn = conn
        self.windows = windows_mod.CrossProjectExecutionWindowManager(conn)

    def open_window(self, window_id, opened_by=None):
        window = self.windows.get_window(int(window_id))
        if window is None:
            raise ValueError(f"no execution window {window_id}")
        if window.status != "defined":
            raise ValueError(
                f"execution window {window.id} is '{window.status}'; "
                "only a defined window can be opened")
        database.update_cross_project_execution_window_status(
            self.conn, window.id, "open", opened_at=_now_iso(),
            opened_by=opened_by or "operator")
        database.save_cross_project_execution_window_event(
            self.conn, window.id, "opened", f"by={opened_by or 'operator'}")
        return self.windows.get_window(window.id)

    def close_window(self, window_id, closed_by=None):
        window = self.windows.get_window(int(window_id))
        if window is None:
            raise ValueError(f"no execution window {window_id}")
        if window.status != "open":
            raise ValueError(
                f"execution window {window.id} is '{window.status}'; "
                "only an open window can be closed")
        database.update_cross_project_execution_window_status(
            self.conn, window.id, "closed", closed_at=_now_iso(),
            closed_by=closed_by or "operator")
        database.save_cross_project_execution_window_event(
            self.conn, window.id, "closed", f"by={closed_by or 'operator'}")
        return self.windows.get_window(window.id)
