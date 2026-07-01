import os
import tempfile
import unittest

import database
from test_cross_project_execution_sessions import _count, _seed_stage9_handoff


class CrossProjectExecutionRuntimeTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_confirmations as confirmations
        import cross_project_execution_runtime as runtime
        import cross_project_execution_scope as scope
        import cross_project_execution_sessions as sessions
        import cross_project_execution_snapshots as snapshots
        self.runtime = runtime
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "rt.db"))
        self.addCleanup(self.conn.close)
        self.root = os.path.join(self.td.name, "alpha")
        os.makedirs(self.root)
        plan, dry, approval, packet = _seed_stage9_handoff(
            self.conn, self.root, os.path.join(self.td.name, "packets"))
        session = sessions.CrossProjectExecutionSessionManager(
            self.conn).prepare(plan.id, approval.id)
        check = scope.CrossProjectExecutionScopeResolver(self.conn).resolve(
            session.id)[0]
        self.conn.execute(
            "UPDATE cross_project_execution_command_proposals SET command_text='pwd' "
            "WHERE id=?", (check.command_proposal_id,))
        self.conn.commit()
        gate = confirmations.CrossProjectExecutionConfirmationGate(self.conn)
        c = gate.request(session.id, check.step_id, check.command_proposal_id)
        self.confirmation = gate.set_status(c.id, "approved")
        self.snapshot = snapshots.CrossProjectExecutionSnapshotBuilder(
            self.conn).create_snapshot(session.id, self.confirmation.id)
        self.session = session

    def test_execute_requires_explicit_confirm_and_uses_stage10_attempt_table(self):
        engine = self.runtime.CrossProjectExecutionRuntime(self.conn)
        with self.assertRaises(ValueError):
            engine.execute(self.session.id, self.confirmation.id, self.snapshot.id,
                           confirm_execution=False)
        attempt = engine.execute(self.session.id, self.confirmation.id,
                                 self.snapshot.id, confirm_execution=True)
        self.assertEqual(attempt.status, "succeeded")
        self.assertEqual(attempt.exit_code, 0)
        self.assertEqual(_count(self.conn, "command_results"), 0)
        self.assertEqual(_count(self.conn, "external_agent_jobs"), 0)

    def test_execute_blocks_non_allowlisted_command_without_core_side_effects(self):
        self.conn.execute(
            "UPDATE cross_project_execution_command_proposals SET command_text='rm unsafe' "
            "WHERE id=?", (self.confirmation.command_proposal_id,))
        self.conn.commit()
        attempt = self.runtime.CrossProjectExecutionRuntime(self.conn).execute(
            self.session.id, self.confirmation.id, self.snapshot.id,
            confirm_execution=True)
        self.assertEqual(attempt.status, "blocked")
        self.assertFalse(attempt.allowed)
        self.assertEqual(_count(self.conn, "command_results"), 0)


if __name__ == "__main__":
    unittest.main()
