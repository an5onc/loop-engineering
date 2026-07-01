import unittest

from test_cross_project_orchestration_runtime import CrossProjectOrchestrationRuntimeTests


class CrossProjectOrchestrationRollbackTests(unittest.TestCase):
    def test_rollback_status_reports_snapshot_without_restoring(self):
        import cross_project_orchestration_rollback as rollback
        base = CrossProjectOrchestrationRuntimeTests(
            methodName="test_advance_requires_explicit_confirm_and_runs_one_stage10_attempt")
        base.setUp()
        self.addCleanup(base.doCleanups)
        status = rollback.CrossProjectOrchestrationRollbackCoordinator(
            base.conn).status(base.run.id)
        self.assertEqual(status.run_id, base.run.id)
        self.assertEqual(status.total_snapshots, 1)
        self.assertEqual(status.restored_steps, 0)


if __name__ == "__main__":
    unittest.main()
