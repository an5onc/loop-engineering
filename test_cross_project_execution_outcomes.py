import unittest

from test_cross_project_execution_runtime import CrossProjectExecutionRuntimeTests


class CrossProjectExecutionOutcomeTests(unittest.TestCase):
    def test_outcome_summarizes_successful_verified_attempt(self):
        import cross_project_execution_outcomes as outcomes
        import cross_project_execution_verification as verification
        base = CrossProjectExecutionRuntimeTests(methodName="test_execute_requires_explicit_confirm_and_uses_stage10_attempt_table")
        base.setUp()
        self.addCleanup(base.td.cleanup)
        self.addCleanup(base.conn.close)
        attempt = base.runtime.CrossProjectExecutionRuntime(base.conn).execute(
            base.session.id, base.confirmation.id, base.snapshot.id,
            confirm_execution=True)
        verification.CrossProjectExecutionVerificationRunner(base.conn).verify(
            attempt.id)
        outcome = outcomes.CrossProjectExecutionOutcomeTracker(
            base.conn).record(attempt.id)
        self.assertEqual(outcome.status, "succeeded")


if __name__ == "__main__":
    unittest.main()
