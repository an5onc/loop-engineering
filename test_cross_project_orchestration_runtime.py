import os
import tempfile
import unittest

import database
from test_cross_project_execution_sessions import _count
from test_cross_project_orchestration_plans import _seed_stage10_scope


class CrossProjectOrchestrationRuntimeTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_confirmations as confirmations
        import cross_project_execution_snapshots as snapshots
        import cross_project_orchestration_dry_run as dry_run
        import cross_project_orchestration_plans as plans
        import cross_project_orchestration_runs as runs
        import cross_project_orchestration_runtime as runtime
        self.runtime = runtime
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "rt.db"))
        self.addCleanup(self.conn.close)
        root = os.path.join(self.td.name, "alpha")
        os.makedirs(root)
        _, _, _, _, self.session, checks = _seed_stage10_scope(
            self.conn, root, os.path.join(self.td.name, "packets"))
        self.conn.execute(
            "UPDATE cross_project_execution_command_proposals SET command_text='pwd' "
            "WHERE id=?", (checks[0].command_proposal_id,))
        self.conn.commit()
        plan = plans.CrossProjectOrchestrationPlanBuilder(self.conn).build_plan(
            self.session.id)
        d = dry_run.CrossProjectOrchestrationDryRunValidator(self.conn).validate(plan.id)
        self.run = runs.CrossProjectOrchestrationRunManager(self.conn).start(plan.id, d.id)
        self.step = self.run.steps[0]
        gate = confirmations.CrossProjectExecutionConfirmationGate(self.conn)
        c = gate.request(self.session.id, self.step.stage10_step_id,
                         self.step.command_proposal_id)
        self.confirmation = gate.set_status(c.id, "approved")
        self.snapshot = snapshots.CrossProjectExecutionSnapshotBuilder(
            self.conn).create_snapshot(self.session.id, self.confirmation.id)

    def test_advance_requires_explicit_confirm_and_runs_one_stage10_attempt(self):
        engine = self.runtime.CrossProjectOrchestrationRuntime(self.conn)
        with self.assertRaises(ValueError):
            engine.advance(self.run.id, self.step.step_id, self.confirmation.id,
                           self.snapshot.id, confirm_execution=False)
        result = engine.advance(self.run.id, self.step.step_id, self.confirmation.id,
                                self.snapshot.id, confirm_execution=True)
        self.assertEqual(result.status, "executed")
        self.assertEqual(result.attempt_id, 1)
        self.assertEqual(_count(self.conn, "cross_project_execution_attempts"), 1)
        self.assertEqual(_count(self.conn, "command_results"), 0)
        self.assertEqual(_count(self.conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
