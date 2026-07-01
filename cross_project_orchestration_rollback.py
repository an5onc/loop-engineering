"""Stage 11.6 — Orchestration Rollback Coordination."""

from dataclasses import dataclass, field

import database
import cross_project_orchestration_runs as runs_mod


@dataclass
class CrossProjectOrchestrationRollbackStatus:
    run_id: int
    total_snapshots: int
    restored_steps: int
    entries: list = field(default_factory=list)


class CrossProjectOrchestrationRollbackCoordinator:
    def __init__(self, conn):
        self.conn = conn
        self.runs = runs_mod.CrossProjectOrchestrationRunManager(conn)

    def status(self, run_id):
        run = self.runs.get_run(int(run_id))
        if run is None:
            raise ValueError(f"no cross-project orchestration run {run_id}")
        entries = []
        restored = 0
        for step in run.steps:
            snapshots = self.conn.execute(
                "SELECT s.* FROM cross_project_execution_snapshots s "
                "JOIN cross_project_execution_confirmations c "
                "ON s.confirmation_id=c.id "
                "WHERE c.step_id=? AND c.command_proposal_id=? "
                "ORDER BY s.id DESC",
                (step.stage10_step_id, step.command_proposal_id)).fetchall()
            restores = []
            for snapshot in snapshots:
                restores.extend(database.list_cross_project_execution_rollback_restores(
                    self.conn, snapshot_id=snapshot["id"]))
            if any(r["restores_files"] for r in restores):
                restored += 1
            entries.append({
                "run_step_id": step.id,
                "orchestration_step_id": step.orchestration_step_id,
                "snapshots": [s["id"] for s in snapshots],
                "restores": [r["id"] for r in restores],
            })
        return CrossProjectOrchestrationRollbackStatus(
            run_id=run.id,
            total_snapshots=sum(len(e["snapshots"]) for e in entries),
            restored_steps=restored,
            entries=entries)
