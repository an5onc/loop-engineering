import os
import tempfile
import unittest

import database
from test_cross_project_execution_runtime import CrossProjectExecutionRuntimeTests


class CrossProjectExecutionVerificationTests(unittest.TestCase):
    def test_verification_run_records_required_pass(self):
        import cross_project_execution_verification as verification
        base = CrossProjectExecutionRuntimeTests(methodName="test_execute_requires_explicit_confirm_and_uses_stage10_attempt_table")
        base.setUp()
        self.addCleanup(base.td.cleanup)
        self.addCleanup(base.conn.close)
        attempt = base.runtime.CrossProjectExecutionRuntime(base.conn).execute(
            base.session.id, base.confirmation.id, base.snapshot.id,
            confirm_execution=True)
        run = verification.CrossProjectExecutionVerificationRunner(
            base.conn).verify(attempt.id)
        self.assertEqual(run.overall_status, "PASS")
        self.assertGreaterEqual(run.total_findings, 1)


if __name__ == "__main__":
    unittest.main()
