import unittest

from test_cross_project_execution_runtime import CrossProjectExecutionRuntimeTests


class CrossProjectRuntimeAuditTests(unittest.TestCase):
    def test_runtime_audit_reports_pass_for_complete_attempt(self):
        import cross_project_runtime_audit as audit
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
        outcomes.CrossProjectExecutionOutcomeTracker(base.conn).record(attempt.id)
        report = audit.CrossProjectRuntimeAuditEngine(base.conn).build_report()
        self.assertEqual(report.overall_status, "PASS")


if __name__ == "__main__":
    unittest.main()
