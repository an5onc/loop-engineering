import unittest

from test_cross_project_orchestration_runtime import CrossProjectOrchestrationRuntimeTests


class CrossProjectOrchestrationVerificationTests(unittest.TestCase):
    def test_verification_marks_step_succeeded_after_stage10_pass(self):
        import cross_project_orchestration_verification as verification
        base = CrossProjectOrchestrationRuntimeTests(
            methodName="test_advance_requires_explicit_confirm_and_runs_one_stage10_attempt")
        base.setUp()
        self.addCleanup(base.doCleanups)
        advancement = base.runtime.CrossProjectOrchestrationRuntime(base.conn).advance(
            base.run.id, base.step.step_id, base.confirmation.id, base.snapshot.id,
            confirm_execution=True)
        result = verification.CrossProjectOrchestrationVerificationBinder(
            base.conn).verify_step(base.run.id, base.step.step_id)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.attempt_id, advancement.attempt_id)


if __name__ == "__main__":
    unittest.main()
