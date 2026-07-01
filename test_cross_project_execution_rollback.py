import os
import tempfile
import unittest

import database
from test_cross_project_execution_snapshots import CrossProjectExecutionSnapshotTests


class CrossProjectExecutionRollbackTests(unittest.TestCase):
    def test_restore_requires_confirm_and_restores_snapshot_file(self):
        import cross_project_execution_rollback as rollback
        base = CrossProjectExecutionSnapshotTests(methodName="test_snapshot_captures_allowlisted_target_file")
        base.setUp()
        self.addCleanup(base.td.cleanup)
        self.addCleanup(base.conn.close)
        snap = base.snapshots.CrossProjectExecutionSnapshotBuilder(
            base.conn).create_snapshot(base.session.id, base.confirmation.id,
                                      target_files=["safe.txt"])
        path = os.path.join(base.root, "safe.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("after")
        engine = rollback.CrossProjectExecutionRollbackEngine(base.conn)
        preview = engine.preview(snap.id)
        self.assertFalse(preview.restores_files)
        with self.assertRaises(ValueError):
            engine.restore(snap.id, confirm_restore=False)
        restored = engine.restore(snap.id, confirm_restore=True)
        self.assertTrue(restored.restores_files)
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "before")


if __name__ == "__main__":
    unittest.main()
