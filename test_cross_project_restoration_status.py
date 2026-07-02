import os
import tempfile
import unittest

import database
from test_cross_project_restoration_targets import seed_blocked_run


class CrossProjectRestorationStatusTests(unittest.TestCase):
    def setUp(self):
        import cross_project_gated_restoration as gated
        import cross_project_orchestration_retry_policies as retry_policies
        import cross_project_restoration_integrity as integrity
        import cross_project_restoration_outcomes as outcomes
        import cross_project_restoration_previews as previews
        import cross_project_restoration_status as status_mod
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "rs.db"))
        self.addCleanup(self.conn.close)
        self.seed = seed_blocked_run(self.conn, self.td.name)
        self.resolver = status_mod.CrossProjectRestorationStatusResolver(self.conn)
        self.previews = previews.CrossProjectRestorationPreviewBinder(self.conn)
        self.engine = gated.CrossProjectGatedRestorationEngine(self.conn)
        self.integrity = integrity.CrossProjectRestorationIntegrityChecker(
            self.conn)
        self.outcomes = outcomes.CrossProjectRestorationOutcomeBinder(self.conn)
        self.policies = retry_policies.CrossProjectOrchestrationRetryPolicyManager(
            self.conn)

    def _resolve(self):
        return self.resolver.resolve(self.seed["run"].id,
                                     step_id=self.seed["step"].step_id)

    def test_lifecycle_next_actions(self):
        status = self._resolve()
        self.assertEqual(status.eligibility, "eligible")
        self.assertIn("--preview-orchestration-restoration", status.next_action)

        self.previews.preview(self.seed["run"].id, self.seed["step"].step_id)
        status = self._resolve()
        self.assertTrue(status.previewed)
        self.assertIn("--confirm-restore", status.next_action)

        self.engine.restore(self.seed["run"].id, self.seed["step"].step_id,
                            confirm_restore=True)
        status = self._resolve()
        self.assertTrue(status.restored)
        self.assertIn("--check-restoration-integrity", status.next_action)

        self.integrity.check(self.seed["run"].id, self.seed["step"].id)
        status = self._resolve()
        self.assertEqual(status.integrity_status, "verified")
        self.assertIn("--record-restoration-outcome", status.next_action)

        self.outcomes.record(self.seed["run"].id, self.seed["step"].id)
        status = self._resolve()
        self.assertIn("--set-orchestration-retry-policy", status.next_action)

        self.policies.set_policy(self.seed["run"].id, 1)
        status = self._resolve()
        self.assertIn("--request-orchestration-retry", status.next_action)

        step = database.get_cross_project_orchestration_run_step(
            self.conn, self.seed["step"].id)
        self.assertEqual(step["status"], "blocked")

    def test_integrity_mismatch_guides_re_restore(self):
        self.previews.preview(self.seed["run"].id, self.seed["step"].step_id)
        self.engine.restore(self.seed["run"].id, self.seed["step"].step_id,
                            confirm_restore=True)
        with open(self.seed["target_file"], "w", encoding="utf-8") as fh:
            fh.write("corrupted")
        self.integrity.check(self.seed["run"].id, self.seed["step"].id)
        status = self._resolve()
        self.assertEqual(status.integrity_status, "mismatch")
        self.assertIn("integrity mismatch", status.next_action)

    def test_run_without_blocked_steps(self):
        td2 = tempfile.TemporaryDirectory()
        self.addCleanup(td2.cleanup)
        conn2 = database.init_db(os.path.join(td2.name, "rs2.db"))
        self.addCleanup(conn2.close)
        seed2 = seed_blocked_run(conn2, td2.name, advance=False)
        import cross_project_restoration_status as status_mod
        status = status_mod.CrossProjectRestorationStatusResolver(
            conn2).resolve(seed2["run"].id)
        self.assertEqual(status.eligibility, "no_blocked_steps")
        self.assertIn("no restoration needed", status.next_action)

    def test_non_blocked_step_reports_no_restoration_needed(self):
        database.update_cross_project_orchestration_run_step(
            self.conn, self.seed["step"].id, "executed")
        status = self._resolve()
        self.assertIn("no restoration needed", status.next_action)


if __name__ == "__main__":
    unittest.main()
