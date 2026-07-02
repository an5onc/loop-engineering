import os
import tempfile
import unittest

import database
from test_cross_project_execution_windows import _seed_orchestration_run
from test_cross_project_restoration_targets import seed_blocked_run


class MultiRunPlannerTests(unittest.TestCase):
    def setUp(self):
        import multi_run_planner as planner
        import multi_run_sessions as sessions
        self.planner_mod = planner
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "pl.db"))
        self.addCleanup(self.conn.close)
        self.sessions = sessions.MultiRunSessionManager(self.conn)
        self.planner = planner.MultiRunAdvancementPlanner(self.conn)

    def test_empty_session_is_empty(self):
        session = self.sessions.create_session("s")
        result = self.planner.plan(session.id)
        self.assertEqual(result.status, "empty")
        self.assertIsNone(result.selected_run_id)

    def test_selects_ready_step_deterministically(self):
        seed = seed_blocked_run(self.conn, self.td.name, advance=False)
        session = self.sessions.create_session("s")
        self.sessions.add_run(session.id, seed["run"].id)
        first = self.planner.plan(session.id)
        second = self.planner.plan(session.id)
        self.assertEqual(first.status, "selected")
        self.assertEqual(first.selected_run_id, seed["run"].id)
        self.assertEqual(first.selected_run_step_id, seed["step"].id)
        self.assertEqual(first.selected_run_id, second.selected_run_id)
        self.assertEqual(first.selected_run_step_id,
                         second.selected_run_step_id)
        self.assertIn(f"--advance-multi-run-session {session.id}",
                      first.required_command)
        self.assertNotIn("SESSION_ID", first.required_command)

    def test_refuses_selection_when_restoration_needed(self):
        seed = seed_blocked_run(self.conn, self.td.name)
        session = self.sessions.create_session("s")
        self.sessions.add_run(session.id, seed["run"].id)
        result = self.planner.plan(session.id)
        self.assertEqual(result.status, "recovery_required")
        self.assertIsNone(result.selected_run_id)
        self.assertIn("--restoration-status", result.required_command)

    def test_skips_completed_runs_with_reasons(self):
        done = _seed_orchestration_run(self.conn, status="succeeded")
        session = self.sessions.create_session("s")
        self.sessions.add_run(session.id, done)
        result = self.planner.plan(session.id)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.skipped,
                         [{"run_id": done, "reason": "run completed"}])

    def test_planner_writes_only_stage14_rows(self):
        seed = seed_blocked_run(self.conn, self.td.name, advance=False)
        session = self.sessions.create_session("s")
        self.sessions.add_run(session.id, seed["run"].id)
        before = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_execution_attempts"
        ).fetchone()["n"]
        self.planner.plan(session.id)
        after = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cross_project_execution_attempts"
        ).fetchone()["n"]
        self.assertEqual(before, after)
        rows = database.list_multi_run_planner_reports(
            self.conn, session_id=session.id)
        self.assertEqual(len(rows), 1)

    def test_markdown_report_written_inside_dir(self):
        session = self.sessions.create_session("s")
        result = self.planner.plan(session.id)
        path = self.planner.save_markdown_report(result)
        self.addCleanup(os.remove, path)
        base = os.path.realpath(self.planner_mod.REPORTS_DIR)
        self.assertTrue(os.path.realpath(path).startswith(base + os.sep))


if __name__ == "__main__":
    unittest.main()
