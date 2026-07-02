"""Stage 13.2 — Gated Orchestration Restoration Engine."""

from dataclasses import dataclass, field

import database
import cross_project_execution_rollback as rollback_mod
import cross_project_restoration_targets as targets_mod


@dataclass
class CrossProjectGatedRestoration:
    rollback_id: int
    run_id: int
    run_step_id: int
    orchestration_step_id: int
    snapshot_id: int
    restore_id: int
    status: str
    total_files: int
    restored_files: int
    safety_notes: list = field(default_factory=list)


class CrossProjectGatedRestorationEngine:
    """Stage 13 restoration path.

    All file writes delegate to the Stage 10 rollback engine — Stage 13
    introduces no file-write path of its own. Restoration requires an
    eligible blocked step, a preview of the same snapshot that is newer than
    the latest restore, and the literal --confirm-restore flag. It never
    re-opens the step: only a Stage 12 retry authorization may do that.
    """

    def __init__(self, conn):
        self.conn = conn
        self.targets = targets_mod.CrossProjectRestorationTargetResolver(conn)
        self.engine = rollback_mod.CrossProjectExecutionRollbackEngine(conn)

    def restore(self, run_id, step_id, confirm_restore=False):
        if not confirm_restore:
            raise ValueError(
                "orchestration restoration requires explicit --confirm-restore")
        target = self.targets.resolve(run_id, step_id)
        self._require_preview(target)
        stage10 = self.engine.restore(target.snapshot_id, confirm_restore=True)
        rollback_id = database.save_cross_project_orchestration_step_rollback(
            self.conn, target.run_id, target.run_step_id,
            target.orchestration_step_id, target.snapshot_id, stage10.id,
            "restored",
            f"Restored snapshot {target.snapshot_id} via Stage 10 restore "
            f"{stage10.id}; step remains blocked until a Stage 12 retry.")
        database.save_cross_project_orchestration_run_event(
            self.conn, target.run_id, "rollback_restored",
            f"step={target.run_step_id} snapshot={target.snapshot_id} "
            f"restore={stage10.id} files={stage10.restored_files}")
        return CrossProjectGatedRestoration(
            rollback_id=rollback_id, run_id=target.run_id,
            run_step_id=target.run_step_id,
            orchestration_step_id=target.orchestration_step_id,
            snapshot_id=target.snapshot_id, restore_id=stage10.id,
            status="restored", total_files=stage10.total_files,
            restored_files=stage10.restored_files,
            safety_notes=_safety_notes())

    def _require_preview(self, target):
        latest_preview = None
        latest_restore = None
        for row in database.list_cross_project_orchestration_step_rollbacks(
                self.conn, run_id=target.run_id):
            if (row["run_step_id"] == target.run_step_id
                    and row["snapshot_id"] == target.snapshot_id):
                if row["status"] == "previewed" and latest_preview is None:
                    latest_preview = row
                if row["status"] == "restored" and latest_restore is None:
                    latest_restore = row
        if (latest_preview is not None and
                (latest_restore is None or latest_preview["id"] > latest_restore["id"])):
            return
        raise ValueError(
            f"restoration of snapshot {target.snapshot_id} requires a fresh "
            "preview since the latest restore "
            "(--preview-orchestration-restoration)")


def _safety_notes():
    return [
        "Stage 13 delegates all file writes to the Stage 10 rollback engine.",
        "Restoration required a fresh preview of the same snapshot since the "
        "latest restore and explicit --confirm-restore.",
        "Only files captured in the snapshot were restored.",
        "The blocked step was not re-opened; use a Stage 12 retry "
        "authorization to re-open it.",
    ]
