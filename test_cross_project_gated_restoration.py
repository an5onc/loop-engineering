import os
import tempfile
import unittest

import database
from test_cross_project_execution_sessions import _count
from test_cross_project_restoration_targets import seed_blocked_run


class CrossProjectGatedRestorationTests(unittest.TestCase):
    def setUp(self):
        import cross_project_gated_restoration as gated
        import cross_project_restoration_previews as previews
        self.gated = gated
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "gr.db"))
        self.addCleanup(self.conn.close)
        self.seed = seed_blocked_run(self.conn, self.td.name)
        self.engine = gated.CrossProjectGatedRestorationEngine(self.conn)
        self.previews = previews.CrossProjectRestorationPreviewBinder(self.conn)

    def _damage_file(self):
        with open(self.seed["target_file"], "w", encoding="utf-8") as fh:
            fh.write("after")

    def test_restore_requires_explicit_confirm(self):
        self.previews.preview(self.seed["run"].id, self.seed["step"].step_id)
        with self.assertRaises(ValueError):
            self.engine.restore(self.seed["run"].id, self.seed["step"].step_id,
                                confirm_restore=False)
        restores = database.list_cross_project_execution_rollback_restores(
            self.conn)
        self.assertTrue(all(not r["restores_files"] for r in restores))

    def test_restore_requires_prior_preview(self):
        with self.assertRaises(ValueError):
            self.engine.restore(self.seed["run"].id, self.seed["step"].step_id,
                                confirm_restore=True)
        restores = database.list_cross_project_execution_rollback_restores(
            self.conn)
        self.assertTrue(all(not r["restores_files"] for r in restores))

    def test_stale_preview_of_other_snapshot_cannot_authorize(self):
        self.previews.preview(self.seed["run"].id, self.seed["step"].step_id)
        self.conn.execute(
            "UPDATE cross_project_orchestration_step_rollbacks SET snapshot_id=? "
            "WHERE status='previewed'", (self.seed["snapshot"].id + 100,))
        self.conn.commit()
        with self.assertRaises(ValueError):
            self.engine.restore(self.seed["run"].id, self.seed["step"].step_id,
                                confirm_restore=True)

    def test_confirmed_restore_reverts_file_and_keeps_step_blocked(self):
        self.previews.preview(self.seed["run"].id, self.seed["step"].step_id)
        self._damage_file()
        result = self.engine.restore(self.seed["run"].id,
                                     self.seed["step"].step_id,
                                     confirm_restore=True)
        self.assertEqual(result.status, "restored")
        self.assertEqual(result.restored_files, 1)
        with open(self.seed["target_file"], encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "before")
        step = database.get_cross_project_orchestration_run_step(
            self.conn, self.seed["step"].id)
        self.assertEqual(step["status"], "blocked")
        run = database.get_cross_project_orchestration_run(
            self.conn, self.seed["run"].id)
        self.assertEqual(run["status"], "blocked")
        stage10 = database.get_cross_project_execution_rollback_restore(
            self.conn, result.restore_id)
        self.assertTrue(stage10["restores_files"])
        rollback = database.get_cross_project_orchestration_step_rollback(
            self.conn, result.rollback_id)
        self.assertEqual(rollback["status"], "restored")
        self.assertEqual(rollback["restore_id"], result.restore_id)
        self.assertEqual(_count(self.conn, "cross_project_execution_attempts"), 1)
        self.assertEqual(_count(self.conn, "command_results"), 0)
        self.assertEqual(_count(self.conn, "external_agent_jobs"), 0)

    def test_restore_requires_fresh_preview_after_prior_restore(self):
        self.previews.preview(self.seed["run"].id, self.seed["step"].step_id)
        self._damage_file()
        first = self.engine.restore(self.seed["run"].id,
                                    self.seed["step"].step_id,
                                    confirm_restore=True)
        with self.assertRaises(ValueError):
            self.engine.restore(self.seed["run"].id,
                                self.seed["step"].step_id,
                                confirm_restore=True)
        self.previews.preview(self.seed["run"].id, self.seed["step"].step_id)
        self._damage_file()
        second = self.engine.restore(self.seed["run"].id,
                                     self.seed["step"].step_id,
                                     confirm_restore=True)
        self.assertNotEqual(first.rollback_id, second.rollback_id)
        with open(self.seed["target_file"], encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "before")


if __name__ == "__main__":
    unittest.main()
