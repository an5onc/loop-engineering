"""Stage 10.6 — Cross-Project Execution Rollback Preview and Restore."""

import base64
import datetime
import json
import os
from dataclasses import dataclass, field

import database
import cross_project_execution_snapshots as snapshots_mod
import multi_project_registry
import project_workspace


@dataclass
class CrossProjectExecutionRollbackRestore:
    id: int
    snapshot_id: int
    generated_at: str
    status: str
    total_files: int
    restored_files: int
    missing_files: int
    restores_files: bool
    safety_notes: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def restore_from_row(row):
    return CrossProjectExecutionRollbackRestore(
        id=row["id"], snapshot_id=row["snapshot_id"],
        generated_at=row["generated_at"] or "", status=row["status"] or "",
        total_files=row["total_files"] or 0, restored_files=row["restored_files"] or 0,
        missing_files=row["missing_files"] or 0,
        restores_files=bool(row["restores_files"]),
        safety_notes=_safe_json_loads(row["safety_notes_json"], []))


class CrossProjectExecutionRollbackEngine:
    def __init__(self, conn):
        self.conn = conn
        self.registry = multi_project_registry.ProjectRegistry(conn)

    def preview(self, snapshot_id):
        snapshot = snapshots_mod.CrossProjectExecutionSnapshotBuilder(
            self.conn).get_snapshot(int(snapshot_id))
        if snapshot is None:
            raise ValueError(f"no cross-project execution snapshot {snapshot_id}")
        rid = database.save_cross_project_execution_rollback_restore(
            self.conn, snapshot.id, _now_iso(), "restore_preview",
            snapshot.total_files, 0, snapshot.missing_files, False,
            json.dumps(_safety_notes(), sort_keys=True))
        database.save_cross_project_execution_rollback_event(
            self.conn, rid, "preview", f"snapshot={snapshot.id}")
        return restore_from_row(database.get_cross_project_execution_rollback_restore(
            self.conn, rid))

    def restore(self, snapshot_id, confirm_restore=False):
        if not confirm_restore:
            raise ValueError("rollback restore requires explicit --confirm-restore")
        snapshot = snapshots_mod.CrossProjectExecutionSnapshotBuilder(
            self.conn).get_snapshot(int(snapshot_id))
        if snapshot is None:
            raise ValueError(f"no cross-project execution snapshot {snapshot_id}")
        confirmation = database.get_cross_project_execution_confirmation(
            self.conn, snapshot.confirmation_id)
        project = self.registry.get_project(confirmation["project_key"])
        if project is None:
            raise ValueError(f"no registered project {confirmation['project_key']}")
        restored = 0
        for item in snapshot.files:
            if not item.file_exists:
                continue
            _restore_file(project, item)
            restored += 1
        rid = database.save_cross_project_execution_rollback_restore(
            self.conn, snapshot.id, _now_iso(), "restored", snapshot.total_files,
            restored, snapshot.missing_files, True,
            json.dumps(_safety_notes(), sort_keys=True))
        database.save_cross_project_execution_rollback_event(
            self.conn, rid, "restored", f"snapshot={snapshot.id} restored={restored}")
        return restore_from_row(database.get_cross_project_execution_rollback_restore(
            self.conn, rid))


def _restore_file(project, item):
    rel = snapshots_mod._validate_target_file(item.target_file)
    root = os.path.realpath(project.root_path)
    target = os.path.realpath(os.path.join(root, rel))
    allowed = [os.path.realpath(os.path.join(root, p))
               for p in list(project.allowed_write_paths or ["."])]
    if not any(target == d or target.startswith(d + os.sep) for d in allowed):
        raise ValueError(f"rollback target outside allowed paths: {rel}")
    if project_workspace.is_protected_path(rel):
        raise ValueError(f"rollback target is protected: {rel}")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(base64.b64decode(item.content_base64.encode("ascii")))


def _safety_notes():
    return [
        "rollback restore requires explicit confirmation",
        "restore writes only files captured in the rollback snapshot",
        "protected paths and path traversal remain blocked",
    ]
