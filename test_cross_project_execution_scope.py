import os
import tempfile
import unittest

import database
from test_cross_project_execution_sessions import _seed_stage9_handoff


class CrossProjectExecutionScopeTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_sessions as sessions
        import cross_project_execution_scope as scope
        self.scope = scope
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "scope.db"))
        self.addCleanup(self.conn.close)
        self.root = os.path.join(self.td.name, "alpha")
        os.makedirs(self.root)
        plan, dry, approval, packet = _seed_stage9_handoff(
            self.conn, self.root, os.path.join(self.td.name, "packets"))
        self.session = sessions.CrossProjectExecutionSessionManager(
            self.conn).prepare(plan.id, approval.id)

    def test_resolve_scope_records_command_cwd_and_allowlist(self):
        checks = self.scope.CrossProjectExecutionScopeResolver(
            self.conn).resolve(self.session.id)
        self.assertTrue(checks)
        self.assertEqual(checks[0].status, "ready")
        self.assertEqual(checks[0].command_cwd, os.path.realpath(self.root))
        self.assertTrue(checks[0].command_allowed)

    def test_resolve_scope_blocks_missing_project_root(self):
        os.rmdir(self.root)
        checks = self.scope.CrossProjectExecutionScopeResolver(
            self.conn).resolve(self.session.id)
        self.assertEqual(checks[0].status, "blocked")
        self.assertIn("missing project root", checks[0].blocked_reasons)


if __name__ == "__main__":
    unittest.main()
