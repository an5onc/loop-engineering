import os
import tempfile
import unittest

import database
from test_cross_project_orchestration_plans import _seed_stage10_scope


class CrossProjectOrchestrationRunTests(unittest.TestCase):
    def setUp(self):
        import cross_project_orchestration_dry_run as dry_run
        import cross_project_orchestration_plans as plans
        import cross_project_orchestration_runs as runs
        self.runs = runs
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "r.db"))
        self.addCleanup(self.conn.close)
        root = os.path.join(self.td.name, "alpha")
        os.makedirs(root)
        _, _, _, _, session, _ = _seed_stage10_scope(
            self.conn, root, os.path.join(self.td.name, "packets"))
        self.plan = plans.CrossProjectOrchestrationPlanBuilder(
            self.conn).build_plan(session.id)
        self.dry_run = dry_run.CrossProjectOrchestrationDryRunValidator(
            self.conn).validate(self.plan.id)

    def test_start_run_requires_latest_passing_dry_run(self):
        manager = self.runs.CrossProjectOrchestrationRunManager(self.conn)
        run = manager.start(self.plan.id, self.dry_run.id)
        self.assertEqual(run.status, "running")
        self.assertEqual(run.total_steps, 1)
        self.assertEqual(run.steps[0].status, "pending")
        with self.assertRaises(ValueError):
            manager.start(self.plan.id, 9999)


if __name__ == "__main__":
    unittest.main()
