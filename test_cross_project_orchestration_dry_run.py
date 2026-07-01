import os
import tempfile
import unittest

import database
from test_cross_project_orchestration_plans import _seed_stage10_scope


class CrossProjectOrchestrationDryRunTests(unittest.TestCase):
    def setUp(self):
        import cross_project_orchestration_dry_run as dry_run
        import cross_project_orchestration_plans as plans
        self.dry_run = dry_run
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "d.db"))
        self.addCleanup(self.conn.close)
        root = os.path.join(self.td.name, "alpha")
        os.makedirs(root)
        _, _, _, _, self.session, _ = _seed_stage10_scope(
            self.conn, root, os.path.join(self.td.name, "packets"))
        self.plan = plans.CrossProjectOrchestrationPlanBuilder(
            self.conn).build_plan(self.session.id)

    def test_dry_run_passes_for_structurally_safe_plan(self):
        report = self.dry_run.CrossProjectOrchestrationDryRunValidator(
            self.conn).validate(self.plan.id)
        self.assertEqual(report.overall_status, "PASS")
        self.assertEqual(report.plan_id, self.plan.id)
        self.assertTrue(report.findings)

    def test_dry_run_blocks_ready_step_without_command_metadata(self):
        self.conn.execute(
            "UPDATE cross_project_orchestration_steps SET command_proposal_id=NULL "
            "WHERE orchestration_plan_id=?", (self.plan.id,))
        self.conn.commit()
        report = self.dry_run.CrossProjectOrchestrationDryRunValidator(
            self.conn).validate(self.plan.id)
        self.assertEqual(report.overall_status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
