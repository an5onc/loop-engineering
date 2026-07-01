import os
import tempfile
import unittest

import database
from test_cross_project_orchestration_plans import _seed_stage10_scope


class CrossProjectOrchestrationControlTests(unittest.TestCase):
    def setUp(self):
        import cross_project_orchestration_controls as controls
        import cross_project_orchestration_dry_run as dry_run
        import cross_project_orchestration_plans as plans
        import cross_project_orchestration_runs as runs
        self.controls = controls
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "c.db"))
        self.addCleanup(self.conn.close)
        root = os.path.join(self.td.name, "alpha")
        os.makedirs(root)
        _, _, _, _, session, _ = _seed_stage10_scope(
            self.conn, root, os.path.join(self.td.name, "packets"))
        plan = plans.CrossProjectOrchestrationPlanBuilder(self.conn).build_plan(session.id)
        d = dry_run.CrossProjectOrchestrationDryRunValidator(self.conn).validate(plan.id)
        self.run = runs.CrossProjectOrchestrationRunManager(self.conn).start(plan.id, d.id)
        self.step = self.run.steps[0]

    def test_control_resolver_reports_required_stage10_gates_without_creating_them(self):
        before = self.conn.execute(
            "SELECT COUNT(*) FROM cross_project_execution_confirmations").fetchone()[0]
        control = self.controls.CrossProjectOrchestrationControlResolver(
            self.conn).resolve(self.run.id, self.step.step_id)
        self.assertEqual(control.status, "needs_confirmation")
        self.assertIn("Stage 10 confirmation", control.required_controls[0])
        after = self.conn.execute(
            "SELECT COUNT(*) FROM cross_project_execution_confirmations").fetchone()[0]
        self.assertEqual(before, after)

    def test_control_resolver_ignores_foreign_session_confirmation(self):
        import cross_project_execution_confirmations as confirmations

        gate = confirmations.CrossProjectExecutionConfirmationGate(self.conn)
        orchestration_step = database.get_cross_project_orchestration_step(
            self.conn, self.step.orchestration_step_id)
        confirmation = gate.request(
            orchestration_step["session_id"], self.step.stage10_step_id,
            self.step.command_proposal_id)
        self.conn.execute(
            "UPDATE cross_project_execution_confirmations SET session_id=? WHERE id=?",
            (999999, confirmation.id))
        self.conn.commit()
        control = self.controls.CrossProjectOrchestrationControlResolver(
            self.conn).resolve(self.run.id, self.step.step_id)
        self.assertEqual(control.status, "needs_confirmation")


if __name__ == "__main__":
    unittest.main()
