import os
import tempfile
import unittest

import database
from test_cross_project_restoration_targets import seed_blocked_run


class CrossProjectRestorationIntegrityTests(unittest.TestCase):
    def setUp(self):
        import cross_project_gated_restoration as gated
        import cross_project_restoration_integrity as integrity
        import cross_project_restoration_previews as previews
        self.integrity = integrity
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "ic.db"))
        self.addCleanup(self.conn.close)
        self.seed = seed_blocked_run(self.conn, self.td.name)
        self.checker = integrity.CrossProjectRestorationIntegrityChecker(self.conn)
        self.previews = previews.CrossProjectRestorationPreviewBinder(self.conn)
        self.engine = gated.CrossProjectGatedRestorationEngine(self.conn)

    def _restore(self):
        self.previews.preview(self.seed["run"].id, self.seed["step"].step_id)
        return self.engine.restore(self.seed["run"].id,
                                   self.seed["step"].step_id,
                                   confirm_restore=True)

    def test_check_requires_completed_restoration(self):
        with self.assertRaises(ValueError):
            self.checker.check(self.seed["run"].id, self.seed["step"].id)

    def test_clean_restore_is_verified(self):
        self._restore()
        check = self.checker.check(self.seed["run"].id, self.seed["step"].id)
        self.assertEqual(check.status, "verified")
        self.assertEqual(check.matched_files, 1)
        self.assertEqual(check.mismatched_files, 0)
        self.assertEqual(check.missing_files, 0)
        with open(self.seed["target_file"], encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "before")

    def test_corrupted_file_is_mismatch(self):
        self._restore()
        with open(self.seed["target_file"], "w", encoding="utf-8") as fh:
            fh.write("corrupted")
        check = self.checker.check(self.seed["run"].id, self.seed["step"].id)
        self.assertEqual(check.status, "mismatch")
        self.assertEqual(check.mismatched_files, 1)

    def test_deleted_file_is_missing(self):
        self._restore()
        os.remove(self.seed["target_file"])
        check = self.checker.check(self.seed["run"].id, self.seed["step"].id)
        self.assertEqual(check.status, "mismatch")
        self.assertEqual(check.missing_files, 1)


if __name__ == "__main__":
    unittest.main()
