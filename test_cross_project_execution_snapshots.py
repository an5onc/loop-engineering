import os
import tempfile
import unittest

import database
from test_cross_project_execution_sessions import _seed_stage9_handoff


class CrossProjectExecutionSnapshotTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_confirmations as confirmations
        import cross_project_execution_scope as scope
        import cross_project_execution_sessions as sessions
        import cross_project_execution_snapshots as snapshots
        self.snapshots = snapshots
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "sn.db"))
        self.addCleanup(self.conn.close)
        self.root = os.path.join(self.td.name, "alpha")
        os.makedirs(self.root)
        with open(os.path.join(self.root, "safe.txt"), "w", encoding="utf-8") as fh:
            fh.write("before")
        plan, dry, approval, packet = _seed_stage9_handoff(
            self.conn, self.root, os.path.join(self.td.name, "packets"))
        self.session = sessions.CrossProjectExecutionSessionManager(
            self.conn).prepare(plan.id, approval.id)
        check = scope.CrossProjectExecutionScopeResolver(self.conn).resolve(
            self.session.id)[0]
        gate = confirmations.CrossProjectExecutionConfirmationGate(self.conn)
        c = gate.request(self.session.id, check.step_id, check.command_proposal_id)
        self.confirmation = gate.set_status(c.id, "approved")

    def test_snapshot_captures_allowlisted_target_file(self):
        snap = self.snapshots.CrossProjectExecutionSnapshotBuilder(
            self.conn).create_snapshot(self.session.id, self.confirmation.id,
                                      target_files=["safe.txt"])
        self.assertEqual(snap.status, "snapshot_created")
        self.assertEqual(snap.captured_files, 1)
        self.assertEqual(snap.files[0].content_sha256,
                         self.snapshots._sha256_text("before"))

    def test_snapshot_rejects_protected_or_escaping_paths(self):
        builder = self.snapshots.CrossProjectExecutionSnapshotBuilder(self.conn)
        with self.assertRaises(ValueError):
            builder.create_snapshot(self.session.id, self.confirmation.id,
                                    target_files=["../escape.txt"])
        with self.assertRaises(ValueError):
            builder.create_snapshot(self.session.id, self.confirmation.id,
                                    target_files=[".env"])


if __name__ == "__main__":
    unittest.main()
