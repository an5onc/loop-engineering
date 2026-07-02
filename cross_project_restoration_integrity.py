"""Stage 13.3 — Post-Restore Integrity Check (read-only)."""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field

import database
import cross_project_execution_snapshots as snapshots_mod
import multi_project_registry


@dataclass
class CrossProjectRestorationIntegrityCheck:
    id: int
    run_id: int
    run_step_id: int
    rollback_id: int
    snapshot_id: int
    restore_id: int
    generated_at: str
    total_files: int
    matched_files: int
    mismatched_files: int
    missing_files: int
    status: str
    detail: list = field(default_factory=list)


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def check_from_row(row):
    return CrossProjectRestorationIntegrityCheck(
        id=row["id"], run_id=row["run_id"], run_step_id=row["run_step_id"],
        rollback_id=row["rollback_id"], snapshot_id=row["snapshot_id"],
        restore_id=row["restore_id"], generated_at=row["generated_at"] or "",
        total_files=row["total_files"] or 0,
        matched_files=row["matched_files"] or 0,
        mismatched_files=row["mismatched_files"] or 0,
        missing_files=row["missing_files"] or 0, status=row["status"] or "",
        detail=_safe_json_loads(row["detail_json"], []))


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def latest_restored_rollback(conn, run_id, run_step_id):
    for row in database.list_cross_project_orchestration_step_rollbacks(
            conn, run_id=run_id):
        if row["run_step_id"] == run_step_id and row["status"] == "restored":
            return row
    return None


class CrossProjectRestorationIntegrityChecker:
    """Compares restored files on disk against the snapshot manifest.

    Pure hashing — never writes project files.
    """

    def __init__(self, conn):
        self.conn = conn
        self.snapshots = snapshots_mod.CrossProjectExecutionSnapshotBuilder(conn)
        self.registry = multi_project_registry.ProjectRegistry(conn)

    def check(self, run_id, run_step_id):
        rollback = latest_restored_rollback(self.conn, int(run_id),
                                            int(run_step_id))
        if rollback is None:
            raise ValueError(
                f"run step {run_step_id} has no completed restoration; "
                "restore first (--restore-orchestration-step)")
        snapshot = self.snapshots.get_snapshot(rollback["snapshot_id"])
        if snapshot is None:
            raise ValueError(f"no snapshot {rollback['snapshot_id']}")
        root = self._project_root(snapshot)
        matched, mismatched, missing, detail = 0, 0, 0, []
        captured = [item for item in snapshot.files if item.file_exists]
        for item in captured:
            path = os.path.join(root, item.target_file)
            if not os.path.exists(path):
                missing += 1
                detail.append({"file": item.target_file, "status": "missing"})
                continue
            with open(path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            if digest == item.content_sha256:
                matched += 1
                detail.append({"file": item.target_file, "status": "matched"})
            else:
                mismatched += 1
                detail.append({"file": item.target_file, "status": "mismatch"})
        status = "verified" if (mismatched == 0 and missing == 0) else "mismatch"
        check_id = database.save_cross_project_restoration_integrity_check(
            self.conn, rollback["run_id"], rollback["run_step_id"],
            rollback["id"], rollback["snapshot_id"], rollback["restore_id"],
            _now_iso(), len(captured), matched, mismatched, missing, status,
            json.dumps(detail, sort_keys=True))
        database.save_cross_project_orchestration_run_event(
            self.conn, rollback["run_id"], "rollback_integrity_checked",
            f"step={rollback['run_step_id']} status={status} "
            f"matched={matched} mismatched={mismatched} missing={missing}")
        return check_from_row(database.get_cross_project_restoration_integrity_check(
            self.conn, check_id))

    def _project_root(self, snapshot):
        confirmation = database.get_cross_project_execution_confirmation(
            self.conn, snapshot.confirmation_id)
        if confirmation is None:
            raise ValueError(
                f"no confirmation {snapshot.confirmation_id} for snapshot "
                f"{snapshot.id}")
        project = self.registry.get_project(confirmation["project_key"])
        if project is None:
            raise ValueError(
                f"no registered project {confirmation['project_key']}")
        return os.path.realpath(project.root_path)
