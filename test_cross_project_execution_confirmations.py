import os
import tempfile
import unittest

import database
from test_cross_project_execution_sessions import _seed_stage9_handoff


class CrossProjectExecutionConfirmationTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_confirmations as confirmations
        import cross_project_execution_scope as scope
        import cross_project_execution_sessions as sessions
        self.confirmations = confirmations
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "c.db"))
        self.addCleanup(self.conn.close)
        root = os.path.join(self.td.name, "alpha")
        os.makedirs(root)
        plan, dry, approval, packet = _seed_stage9_handoff(
            self.conn, root, os.path.join(self.td.name, "packets"))
        session = sessions.CrossProjectExecutionSessionManager(
            self.conn).prepare(plan.id, approval.id)
        self.check = scope.CrossProjectExecutionScopeResolver(
            self.conn).resolve(session.id)[0]
        self.session = session

    def test_request_and_approve_exact_command_confirmation(self):
        gate = self.confirmations.CrossProjectExecutionConfirmationGate(self.conn)
        confirmation = gate.request(
            self.session.id, self.check.step_id, self.check.command_proposal_id)
        self.assertEqual(confirmation.status, "requested")
        approved = gate.set_status(confirmation.id, "approved", decided_by="test")
        self.assertTrue(self.confirmations.is_usable(approved))

    def test_mismatched_command_fails_closed(self):
        gate = self.confirmations.CrossProjectExecutionConfirmationGate(self.conn)
        with self.assertRaises(ValueError):
            gate.request(self.session.id, self.check.step_id, 9999)


if __name__ == "__main__":
    unittest.main()
