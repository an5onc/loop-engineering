import os
import tempfile
import unittest

import database
from test_cross_project_restoration_targets import seed_blocked_run


class MultiRunRecoveryTests(unittest.TestCase):
    def setUp(self):
        import multi_run_recovery as recovery
        import multi_run_sessions as sessions
        self.recovery_mod = recovery
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "rc.db"))
        self.addCleanup(self.conn.close)
        self.sessions = sessions.MultiRunSessionManager(self.conn)
        self.engine = recovery.MultiRunRecoveryEngine(self.conn)

    def _session_with_blocked_run(self):
        seed = seed_blocked_run(self.conn, self.td.name)
        session = self.sessions.create_session("s")
        self.sessions.add_run(session.id, seed["run"].id)
        return seed, session

    def test_no_blocked_steps(self):
        session = self.sessions.create_session("s")
        status = self.engine.status(session.id)
        self.assertEqual(status.overall_status, "no_blocked_steps")

    def test_blocked_unrestored_recommends_preview_restore(self):
        seed, session = self._session_with_blocked_run()
        status = self.engine.status(session.id)
        self.assertEqual(status.overall_status, "recovery_available")
        self.assertIn("--preview-orchestration-restoration",
                      status.entries[0]["next_command"])

        import cross_project_restoration_previews as previews
        previews.CrossProjectRestorationPreviewBinder(self.conn).preview(
            seed["run"].id, seed["step"].step_id)
        status = self.engine.status(session.id)
        self.assertIn("--restore-orchestration-step",
                      status.entries[0]["next_command"])
        self.assertIn("--confirm-restore", status.entries[0]["next_command"])

    def test_restored_walkthrough_to_retry(self):
        import cross_project_gated_restoration as gated
        import cross_project_orchestration_retry_policies as retry_policies
        import cross_project_restoration_integrity as integrity
        import cross_project_restoration_outcomes as outcomes
        import cross_project_restoration_previews as previews
        seed, session = self._session_with_blocked_run()
        previews.CrossProjectRestorationPreviewBinder(self.conn).preview(
            seed["run"].id, seed["step"].step_id)
        gated.CrossProjectGatedRestorationEngine(self.conn).restore(
            seed["run"].id, seed["step"].step_id, confirm_restore=True)
        status = self.engine.status(session.id)
        self.assertIn("--check-restoration-integrity",
                      status.entries[0]["next_command"])

        integrity.CrossProjectRestorationIntegrityChecker(self.conn).check(
            seed["run"].id, seed["step"].id)
        status = self.engine.status(session.id)
        self.assertIn("--record-restoration-outcome",
                      status.entries[0]["next_command"])

        outcomes.CrossProjectRestorationOutcomeBinder(self.conn).record(
            seed["run"].id, seed["step"].id)
        status = self.engine.status(session.id)
        self.assertIn("--set-orchestration-retry-policy",
                      status.entries[0]["next_command"])

        retry_policies.CrossProjectOrchestrationRetryPolicyManager(
            self.conn).set_policy(seed["run"].id, 1)
        status = self.engine.status(session.id)
        self.assertIn("--request-orchestration-retry",
                      status.entries[0]["next_command"])

    def test_exhausted_budget_reports_blocked(self):
        import json as json_mod
        seed, session = self._session_with_blocked_run()
        import cross_project_gated_restoration as gated
        import cross_project_orchestration_retry_policies as retry_policies
        import cross_project_restoration_integrity as integrity
        import cross_project_restoration_outcomes as outcomes
        import cross_project_restoration_previews as previews
        previews.CrossProjectRestorationPreviewBinder(self.conn).preview(
            seed["run"].id, seed["step"].step_id)
        gated.CrossProjectGatedRestorationEngine(self.conn).restore(
            seed["run"].id, seed["step"].step_id, confirm_restore=True)
        integrity.CrossProjectRestorationIntegrityChecker(self.conn).check(
            seed["run"].id, seed["step"].id)
        outcomes.CrossProjectRestorationOutcomeBinder(self.conn).record(
            seed["run"].id, seed["step"].id)
        retry_policies.CrossProjectOrchestrationRetryPolicyManager(
            self.conn).set_policy(seed["run"].id, 1)
        database.save_cross_project_orchestration_step_advancement(
            self.conn, seed["run"].id, seed["step"].id,
            seed["step"].orchestration_step_id, seed["confirmation"].id + 100,
            seed["snapshot"].id, 2, "blocked", json_mod.dumps([]))
        status = self.engine.status(session.id)
        self.assertEqual(status.overall_status, "blocked")
        self.assertIn("retry budget exhausted",
                      status.entries[0]["next_command"])

    def test_recovery_is_advisory_only(self):
        seed, session = self._session_with_blocked_run()
        before = {
            table: self.conn.execute(
                f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in (
                "cross_project_execution_rollback_restores",
                "cross_project_orchestration_step_rollbacks",
                "cross_project_orchestration_retry_requests",
            )
        }
        self.engine.status(session.id)
        after = {
            table: self.conn.execute(
                f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in before
        }
        self.assertEqual(before, after)
        step = database.get_cross_project_orchestration_run_step(
            self.conn, seed["step"].id)
        self.assertEqual(step["status"], "blocked")

    def test_markdown_report_written_inside_dir(self):
        session = self.sessions.create_session("s")
        status = self.engine.status(session.id)
        path = self.engine.save_markdown_report(status)
        self.addCleanup(os.remove, path)
        base = os.path.realpath(self.recovery_mod.REPORTS_DIR)
        self.assertTrue(os.path.realpath(path).startswith(base + os.sep))


if __name__ == "__main__":
    unittest.main()
