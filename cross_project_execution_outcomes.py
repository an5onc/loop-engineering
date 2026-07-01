"""Stage 10.7 — Cross-Project Execution Outcome Tracker."""

import datetime
import json
from dataclasses import dataclass, field

import database


@dataclass
class CrossProjectExecutionOutcome:
    id: int
    attempt_id: int
    generated_at: str
    status: str
    summary: str
    verification_run_id: int = None
    rollback_restore_id: int = None
    remaining_risks: list = field(default_factory=list)
    next_steps: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def outcome_from_row(row):
    return CrossProjectExecutionOutcome(
        id=row["id"], attempt_id=row["attempt_id"],
        generated_at=row["generated_at"] or "", status=row["status"] or "",
        summary=row["summary"] or "",
        verification_run_id=row["verification_run_id"],
        rollback_restore_id=row["rollback_restore_id"],
        remaining_risks=_safe_json_loads(row["remaining_risks_json"], []),
        next_steps=_safe_json_loads(row["next_steps_json"], []))


class CrossProjectExecutionOutcomeTracker:
    def __init__(self, conn):
        self.conn = conn

    def record(self, attempt_id):
        attempt = database.get_cross_project_execution_attempt(self.conn, int(attempt_id))
        if attempt is None:
            raise ValueError(f"no cross-project execution attempt {attempt_id}")
        verification = _latest(database.list_cross_project_execution_verification_runs(
            self.conn, attempt_id=attempt["id"]))
        restores = database.list_cross_project_execution_rollback_restores(
            self.conn, snapshot_id=attempt["snapshot_id"])
        restore = _latest([r for r in restores if r["restores_files"]])
        if restore:
            status = "rolled_back"
        elif verification and verification["overall_status"] == "PASS" and attempt["status"] == "succeeded":
            status = "succeeded"
        elif attempt["status"] == "blocked":
            status = "blocked"
        else:
            status = "failed"
        risks = [] if status == "succeeded" else ["operator review required before retry"]
        oid = database.save_cross_project_execution_outcome(
            self.conn, attempt["id"], _now_iso(), status,
            f"Execution attempt {attempt['id']} outcome: {status}",
            verification["id"] if verification else None,
            restore["id"] if restore else None,
            json.dumps(risks, sort_keys=True),
            json.dumps(_next_steps(status), sort_keys=True))
        return outcome_from_row(database.get_cross_project_execution_outcome(
            self.conn, oid))


def _latest(rows):
    return rows[0] if rows else None


def _next_steps(status):
    if status == "succeeded":
        return ["review Stage 10 audit before any additional execution"]
    if status == "rolled_back":
        return ["inspect rollback result before retry"]
    return ["fix blockers and rerun dry-run/confirmation flow"]
