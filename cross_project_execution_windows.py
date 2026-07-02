"""Stage 12.0 — Operator-Defined Execution Windows."""

import datetime
from dataclasses import dataclass

import database


@dataclass
class CrossProjectExecutionWindow:
    id: int
    run_id: int
    label: str
    status: str
    starts_at: str = ""
    ends_at: str = ""
    opened_at: str = ""
    opened_by: str = ""
    closed_at: str = ""
    closed_by: str = ""
    notes: str = ""


def window_from_row(row):
    return CrossProjectExecutionWindow(
        id=row["id"], run_id=row["run_id"], label=row["label"] or "",
        status=row["status"] or "", starts_at=row["starts_at"] or "",
        ends_at=row["ends_at"] or "", opened_at=row["opened_at"] or "",
        opened_by=row["opened_by"] or "", closed_at=row["closed_at"] or "",
        closed_by=row["closed_by"] or "", notes=row["notes"] or "")


def _parse_iso(value, flag):
    try:
        return datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"execution window {flag} must be an ISO timestamp")


class CrossProjectExecutionWindowManager:
    def __init__(self, conn):
        self.conn = conn

    def define_window(self, run_id, label, starts_at=None, ends_at=None,
                      notes=None):
        run = database.get_cross_project_orchestration_run(self.conn, int(run_id))
        if run is None:
            raise ValueError(f"no cross-project orchestration run {run_id}")
        if not label or not str(label).strip():
            raise ValueError("execution window requires a non-empty --label")
        starts = _parse_iso(starts_at, "--starts") if starts_at else None
        ends = _parse_iso(ends_at, "--ends") if ends_at else None
        if starts and ends and ends <= starts:
            raise ValueError("execution window --ends must be after --starts")
        window_id = database.save_cross_project_execution_window(
            self.conn, run["id"], str(label).strip(), "defined",
            starts.isoformat(timespec="seconds") if starts else None,
            ends.isoformat(timespec="seconds") if ends else None,
            notes)
        database.save_cross_project_execution_window_event(
            self.conn, window_id, "defined",
            f"run={run['id']} label={str(label).strip()}")
        return self.get_window(window_id)

    def get_window(self, window_id):
        row = database.get_cross_project_execution_window(self.conn, int(window_id))
        return window_from_row(row) if row else None

    def list_windows(self, run_id=None, limit=50):
        rows = database.list_cross_project_execution_windows(
            self.conn, run_id=run_id, limit=limit)
        return [window_from_row(row) for row in rows]
