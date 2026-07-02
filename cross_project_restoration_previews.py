"""Stage 13.1 — Restoration Preview Binder."""

from dataclasses import dataclass, field

import database
import cross_project_execution_rollback as rollback_mod
import cross_project_restoration_targets as targets_mod


@dataclass
class CrossProjectRestorationPreview:
    rollback_id: int
    run_id: int
    run_step_id: int
    orchestration_step_id: int
    snapshot_id: int
    restore_id: int
    status: str
    total_files: int
    missing_files: int
    safety_notes: list = field(default_factory=list)


class CrossProjectRestorationPreviewBinder:
    """Binds a Stage 10 restore preview to a blocked orchestration step.

    Metadata-only: the Stage 10 preview writes no project files.
    """

    def __init__(self, conn):
        self.conn = conn
        self.targets = targets_mod.CrossProjectRestorationTargetResolver(conn)
        self.engine = rollback_mod.CrossProjectExecutionRollbackEngine(conn)

    def preview(self, run_id, step_id):
        target = self.targets.resolve(run_id, step_id)
        stage10 = self.engine.preview(target.snapshot_id)
        rollback_id = database.save_cross_project_orchestration_step_rollback(
            self.conn, target.run_id, target.run_step_id,
            target.orchestration_step_id, target.snapshot_id, stage10.id,
            "previewed",
            f"Previewed snapshot {target.snapshot_id} via Stage 10 restore "
            f"{stage10.id}; no files were written.")
        database.save_cross_project_orchestration_run_event(
            self.conn, target.run_id, "rollback_previewed",
            f"step={target.run_step_id} snapshot={target.snapshot_id} "
            f"restore={stage10.id}")
        return CrossProjectRestorationPreview(
            rollback_id=rollback_id, run_id=target.run_id,
            run_step_id=target.run_step_id,
            orchestration_step_id=target.orchestration_step_id,
            snapshot_id=target.snapshot_id, restore_id=stage10.id,
            status="previewed", total_files=stage10.total_files,
            missing_files=stage10.missing_files,
            safety_notes=stage10.safety_notes)
