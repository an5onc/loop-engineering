import os
import tempfile
import unittest

import database
from test_cross_project_execution_sessions import _count
from test_cross_project_restoration_targets import seed_blocked_run


class CrossProjectRestorationPreviewTests(unittest.TestCase):
    def setUp(self):
        import cross_project_restoration_previews as previews
        self.previews = previews
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "pv.db"))
        self.addCleanup(self.conn.close)

    def test_preview_records_stage10_preview_and_rollback_row(self):
        seed = seed_blocked_run(self.conn, self.td.name)
        binder = self.previews.CrossProjectRestorationPreviewBinder(self.conn)
        preview = binder.preview(seed["run"].id, seed["step"].step_id)
        self.assertEqual(preview.status, "previewed")
        self.assertEqual(preview.snapshot_id, seed["snapshot"].id)
        self.assertEqual(preview.total_files, 1)
        stage10 = database.get_cross_project_execution_rollback_restore(
            self.conn, preview.restore_id)
        self.assertEqual(stage10["status"], "restore_preview")
        self.assertFalse(stage10["restores_files"])
        rollback = database.get_cross_project_orchestration_step_rollback(
            self.conn, preview.rollback_id)
        self.assertEqual(rollback["status"], "previewed")
        self.assertEqual(rollback["restore_id"], preview.restore_id)
        events = self.conn.execute(
            "SELECT event_type FROM cross_project_orchestration_run_events "
            "WHERE run_id=?", (seed["run"].id,)).fetchall()
        self.assertIn("rollback_previewed", [r["event_type"] for r in events])
        with open(seed["target_file"], encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "before")

    def test_preview_refused_on_non_blocked_step(self):
        seed = seed_blocked_run(self.conn, self.td.name, advance=False)
        binder = self.previews.CrossProjectRestorationPreviewBinder(self.conn)
        with self.assertRaises(ValueError):
            binder.preview(seed["run"].id, seed["step"].step_id)
        self.assertEqual(
            _count(self.conn, "cross_project_execution_rollback_restores"), 0)
        self.assertEqual(
            _count(self.conn, "cross_project_orchestration_step_rollbacks"), 0)


if __name__ == "__main__":
    unittest.main()
