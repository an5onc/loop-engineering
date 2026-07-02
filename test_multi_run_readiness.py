import os
import tempfile
import unittest

import database
from test_cross_project_restoration_targets import seed_blocked_run


class MultiRunReadinessTests(unittest.TestCase):
    def setUp(self):
        import multi_run_readiness as readiness
        import multi_run_sessions as sessions
        self.readiness_mod = readiness
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "rd.db"))
        self.addCleanup(self.conn.close)
        self.sessions = sessions.MultiRunSessionManager(self.conn)
        self.engine = readiness.MultiRunReadinessEngine(self.conn)

    def test_empty_session_reports_empty(self):
        session = self.sessions.create_session("s")
        report = self.engine.build(session.id)
        self.assertEqual(report.overall_status, "empty")
        self.assertIn("--add-run-to-multi-run-session", report.next_action)

    def test_missing_session_fails_closed(self):
        with self.assertRaises(ValueError):
            self.engine.build(999)

    def test_pending_run_walks_window_then_ready(self):
        import cross_project_execution_window_controls as controls
        seed = seed_blocked_run(self.conn, self.td.name, advance=False)
        window_gate = controls.CrossProjectExecutionWindowControlGate(self.conn)
        window_gate.close_window(seed["window"].id)
        session = self.sessions.create_session("s")
        self.sessions.add_run(session.id, seed["run"].id)
        report = self.engine.build(session.id)
        self.assertEqual(report.overall_status, "needs_open_window")

        import cross_project_execution_windows as windows
        w2 = windows.CrossProjectExecutionWindowManager(self.conn).define_window(
            seed["run"].id, "w2")
        window_gate.open_window(w2.id)
        report = self.engine.build(session.id)
        self.assertEqual(report.overall_status, "ready")
        self.assertIn("--advance-multi-run-session", report.next_action)

    def test_blocked_run_recovery_walkthrough(self):
        import cross_project_gated_restoration as gated
        import cross_project_orchestration_retry_policies as retry_policies
        import cross_project_restoration_outcomes as outcomes
        import cross_project_restoration_previews as previews
        seed = seed_blocked_run(self.conn, self.td.name)
        session = self.sessions.create_session("s")
        self.sessions.add_run(session.id, seed["run"].id)

        report = self.engine.build(session.id)
        self.assertEqual(report.overall_status, "needs_restoration")
        self.assertIn("--restoration-status", report.next_action)
        self.assertEqual(self.sessions.get_session(session.id).status, "blocked")

        previews.CrossProjectRestorationPreviewBinder(self.conn).preview(
            seed["run"].id, seed["step"].step_id)
        gated.CrossProjectGatedRestorationEngine(self.conn).restore(
            seed["run"].id, seed["step"].step_id, confirm_restore=True)
        report = self.engine.build(session.id)
        self.assertEqual(report.overall_status, "needs_restoration")
        self.assertIn("--record-restoration-outcome", report.next_action)

        outcomes.CrossProjectRestorationOutcomeBinder(self.conn).record(
            seed["run"].id, seed["step"].id)
        report = self.engine.build(session.id)
        self.assertEqual(report.overall_status, "needs_retry_authorization")
        self.assertIn("--set-orchestration-retry-policy", report.next_action)

        retry_policies.CrossProjectOrchestrationRetryPolicyManager(
            self.conn).set_policy(seed["run"].id, 1)
        report = self.engine.build(session.id)
        self.assertEqual(report.overall_status, "needs_retry_authorization")
        self.assertIn("--request-orchestration-retry", report.next_action)

    def test_completed_run_reports_completed(self):
        seed = seed_blocked_run(self.conn, self.td.name, advance=False)
        database.update_cross_project_orchestration_run_status(
            self.conn, seed["run"].id, "succeeded")
        session = self.sessions.create_session("s")
        self.sessions.add_run(session.id, seed["run"].id)
        report = self.engine.build(session.id)
        self.assertEqual(report.overall_status, "completed")

    def test_readiness_only_writes_stage14_rows(self):
        seed = seed_blocked_run(self.conn, self.td.name, advance=False)
        session = self.sessions.create_session("s")
        self.sessions.add_run(session.id, seed["run"].id)
        before = {
            table: self.conn.execute(
                f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in (
                "cross_project_execution_attempts",
                "cross_project_execution_window_checks",
                "cross_project_orchestration_step_controls",
                "cross_project_restoration_targets",
                "cross_project_restoration_statuses",
            )
        }
        self.engine.build(session.id)
        after = {
            table: self.conn.execute(
                f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in before
        }
        self.assertEqual(before, after)
        rows = database.list_multi_run_readiness_reports(
            self.conn, session_id=session.id)
        self.assertEqual(len(rows), 1)

    def test_markdown_report_written_inside_dir(self):
        session = self.sessions.create_session("s")
        report = self.engine.build(session.id)
        path = self.engine.save_markdown_report(report)
        self.addCleanup(os.remove, path)
        base = os.path.realpath(self.readiness_mod.REPORTS_DIR)
        self.assertTrue(os.path.realpath(path).startswith(base + os.sep))


if __name__ == "__main__":
    unittest.main()
