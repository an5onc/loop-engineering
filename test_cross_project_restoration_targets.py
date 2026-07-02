import os
import tempfile
import unittest

import database
from test_cross_project_execution_sessions import _count
from test_cross_project_orchestration_plans import _seed_stage10_scope


def seed_blocked_run(conn, td_name, command_text="python3 missing_script.py",
                     advance=True):
    """Build a run whose single step is blocked by a failed attempt.

    The project root contains safe.txt ("before") captured in the Stage 10
    snapshot, so restoration tests can damage and restore it.
    Returns a dict with session, run, step, ids, and paths.
    """
    import cross_project_execution_confirmations as confirmations
    import cross_project_execution_snapshots as snapshots
    import cross_project_execution_window_controls as window_controls
    import cross_project_execution_windows as windows
    import cross_project_gated_advancement as gated
    import cross_project_orchestration_dry_run as dry_run
    import cross_project_orchestration_plans as plans
    import cross_project_orchestration_runs as runs

    root = os.path.join(td_name, "alpha")
    os.makedirs(root)
    target_file = os.path.join(root, "safe.txt")
    with open(target_file, "w", encoding="utf-8") as fh:
        fh.write("before")
    _, _, _, _, session, checks = _seed_stage10_scope(
        conn, root, os.path.join(td_name, "packets"))
    proposal_id = checks[0].command_proposal_id
    conn.execute(
        "UPDATE cross_project_execution_command_proposals SET command_text=? "
        "WHERE id=?", (command_text, proposal_id))
    conn.commit()
    plan = plans.CrossProjectOrchestrationPlanBuilder(conn).build_plan(session.id)
    d = dry_run.CrossProjectOrchestrationDryRunValidator(conn).validate(plan.id)
    run = runs.CrossProjectOrchestrationRunManager(conn).start(plan.id, d.id)
    step = run.steps[0]
    gate = confirmations.CrossProjectExecutionConfirmationGate(conn)
    c = gate.request(session.id, step.stage10_step_id, proposal_id)
    confirmation = gate.set_status(c.id, "approved")
    snapshot = snapshots.CrossProjectExecutionSnapshotBuilder(conn).create_snapshot(
        session.id, confirmation.id, target_files=["safe.txt"])
    window = windows.CrossProjectExecutionWindowManager(conn).define_window(
        run.id, "restoration-test")
    window_controls.CrossProjectExecutionWindowControlGate(conn).open_window(
        window.id)
    advancement = None
    if advance:
        advancement = gated.CrossProjectGatedAdvancementEngine(conn).advance(
            run.id, step.step_id, confirmation.id, snapshot.id,
            confirm_execution=True)
    return {
        "session": session, "run": run, "step": step,
        "proposal_id": proposal_id, "confirmation": confirmation,
        "snapshot": snapshot, "window": window, "advancement": advancement,
        "root": root, "target_file": target_file,
    }


class CrossProjectRestorationTargetTests(unittest.TestCase):
    def setUp(self):
        import cross_project_restoration_targets as targets
        self.targets = targets
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "rt.db"))
        self.addCleanup(self.conn.close)

    def test_blocked_step_is_eligible(self):
        seed = seed_blocked_run(self.conn, self.td.name)
        resolver = self.targets.CrossProjectRestorationTargetResolver(self.conn)
        target = resolver.resolve(seed["run"].id, seed["step"].step_id)
        self.assertEqual(target.status, "eligible")
        self.assertEqual(target.snapshot_id, seed["snapshot"].id)
        self.assertEqual(target.run_step_id, seed["step"].id)
        self.assertIsNotNone(target.advancement_id)
        rows = database.list_cross_project_restoration_targets(
            self.conn, run_id=seed["run"].id)
        self.assertEqual(rows[0]["status"], "eligible")

    def test_pending_step_refused_with_persisted_row(self):
        seed = seed_blocked_run(self.conn, self.td.name, advance=False)
        resolver = self.targets.CrossProjectRestorationTargetResolver(self.conn)
        with self.assertRaises(ValueError):
            resolver.resolve(seed["run"].id, seed["step"].step_id)
        rows = database.list_cross_project_restoration_targets(
            self.conn, run_id=seed["run"].id)
        self.assertEqual(rows[0]["status"], "refused")
        self.assertIn("not blocked", rows[0]["reason"])

    def test_blocked_step_without_advancement_refused(self):
        seed = seed_blocked_run(self.conn, self.td.name, advance=False)
        database.update_cross_project_orchestration_run_step(
            self.conn, seed["step"].id, "blocked")
        resolver = self.targets.CrossProjectRestorationTargetResolver(self.conn)
        with self.assertRaises(ValueError):
            resolver.resolve(seed["run"].id, seed["step"].step_id)
        rows = database.list_cross_project_restoration_targets(
            self.conn, run_id=seed["run"].id)
        self.assertIn("no prior advancement", rows[0]["reason"])

    def test_advancement_without_snapshot_refused(self):
        seed = seed_blocked_run(self.conn, self.td.name, advance=False)
        database.update_cross_project_orchestration_run_step(
            self.conn, seed["step"].id, "blocked")
        database.save_cross_project_orchestration_step_advancement(
            self.conn, seed["run"].id, seed["step"].id,
            seed["step"].orchestration_step_id, seed["confirmation"].id, None,
            1, "blocked", "[]")
        resolver = self.targets.CrossProjectRestorationTargetResolver(self.conn)
        with self.assertRaises(ValueError):
            resolver.resolve(seed["run"].id, seed["step"].step_id)
        rows = database.list_cross_project_restoration_targets(
            self.conn, run_id=seed["run"].id)
        self.assertIn("no rollback snapshot", rows[0]["reason"])

    def test_unknown_run_or_step_raises_without_rows(self):
        resolver = self.targets.CrossProjectRestorationTargetResolver(self.conn)
        with self.assertRaises(ValueError):
            resolver.resolve(999, 1)
        seed = seed_blocked_run(self.conn, self.td.name, advance=False)
        with self.assertRaises(ValueError):
            resolver.resolve(seed["run"].id, 999)
        self.assertEqual(_count(self.conn, "cross_project_restoration_targets"), 0)


if __name__ == "__main__":
    unittest.main()
