import os
import tempfile
import unittest

import database
from test_cross_project_execution_sessions import _count
from test_cross_project_orchestration_plans import _seed_stage10_scope


class CrossProjectGatedAdvancementTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_confirmations as confirmations
        import cross_project_execution_snapshots as snapshots
        import cross_project_execution_window_controls as window_controls
        import cross_project_execution_windows as windows
        import cross_project_gated_advancement as gated
        import cross_project_orchestration_dry_run as dry_run
        import cross_project_orchestration_plans as plans
        import cross_project_orchestration_retry_policies as retry_policies
        import cross_project_orchestration_retry_requests as retry_requests
        import cross_project_orchestration_runs as runs
        self.confirmations = confirmations
        self.snapshots = snapshots
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "ga.db"))
        self.addCleanup(self.conn.close)
        root = os.path.join(self.td.name, "alpha")
        os.makedirs(root)
        _, _, _, _, self.session, checks = _seed_stage10_scope(
            self.conn, root, os.path.join(self.td.name, "packets"))
        self.proposal_id = checks[0].command_proposal_id
        self._set_command("pwd")
        plan = plans.CrossProjectOrchestrationPlanBuilder(self.conn).build_plan(
            self.session.id)
        d = dry_run.CrossProjectOrchestrationDryRunValidator(self.conn).validate(plan.id)
        self.run = runs.CrossProjectOrchestrationRunManager(self.conn).start(plan.id, d.id)
        self.step = self.run.steps[0]
        self.confirmation_gate = confirmations.CrossProjectExecutionConfirmationGate(
            self.conn)
        self.snapshot_builder = snapshots.CrossProjectExecutionSnapshotBuilder(
            self.conn)
        self.confirmation, self.snapshot = self._fresh_confirmation_and_snapshot()
        self.engine = gated.CrossProjectGatedAdvancementEngine(self.conn)
        self.windows = windows.CrossProjectExecutionWindowManager(self.conn)
        self.window_gate = window_controls.CrossProjectExecutionWindowControlGate(
            self.conn)
        self.policies = retry_policies.CrossProjectOrchestrationRetryPolicyManager(
            self.conn)
        self.retry_gate = retry_requests.CrossProjectOrchestrationRetryGate(self.conn)

    def _set_command(self, command_text):
        self.conn.execute(
            "UPDATE cross_project_execution_command_proposals SET command_text=? "
            "WHERE id=?", (command_text, self.proposal_id))
        self.conn.commit()

    def _fresh_confirmation_and_snapshot(self):
        c = self.confirmation_gate.request(
            self.session.id, self.step.stage10_step_id, self.proposal_id)
        confirmation = self.confirmation_gate.set_status(c.id, "approved")
        snapshot = self.snapshot_builder.create_snapshot(
            self.session.id, confirmation.id)
        return confirmation, snapshot

    def _open_window(self):
        window = self.windows.define_window(self.run.id, "test-window")
        return self.window_gate.open_window(window.id)

    def test_advance_requires_explicit_confirm(self):
        self._open_window()
        with self.assertRaises(ValueError):
            self.engine.advance(self.run.id, self.step.step_id,
                                self.confirmation.id, self.snapshot.id,
                                confirm_execution=False)
        self.assertEqual(_count(self.conn, "cross_project_execution_attempts"), 0)
        self.assertEqual(_count(self.conn, "cross_project_gated_advancements"), 0)

    def test_advance_refuses_without_window(self):
        with self.assertRaises(ValueError):
            self.engine.advance(self.run.id, self.step.step_id,
                                self.confirmation.id, self.snapshot.id,
                                confirm_execution=True)
        self.assertEqual(_count(self.conn, "cross_project_execution_attempts"), 0)
        checks = database.list_cross_project_execution_window_checks(
            self.conn, run_id=self.run.id)
        self.assertEqual(checks[0]["status"], "missing")

    def test_advance_refuses_with_closed_window(self):
        window = self._open_window()
        self.window_gate.close_window(window.id)
        with self.assertRaises(ValueError):
            self.engine.advance(self.run.id, self.step.step_id,
                                self.confirmation.id, self.snapshot.id,
                                confirm_execution=True)
        self.assertEqual(_count(self.conn, "cross_project_execution_attempts"), 0)

    def test_advance_succeeds_with_open_window(self):
        window = self._open_window()
        result = self.engine.advance(self.run.id, self.step.step_id,
                                     self.confirmation.id, self.snapshot.id,
                                     confirm_execution=True)
        self.assertEqual(result.status, "executed")
        self.assertEqual(result.attempt_number, 1)
        self.assertEqual(result.window_id, window.id)
        self.assertIsNone(result.retry_request_id)
        self.assertEqual(_count(self.conn, "cross_project_execution_attempts"), 1)
        self.assertEqual(
            _count(self.conn, "cross_project_orchestration_step_advancements"), 1)
        self.assertEqual(_count(self.conn, "command_results"), 0)
        self.assertEqual(_count(self.conn, "external_agent_jobs"), 0)

    def test_retry_requires_authorization_and_fresh_confirmation(self):
        self._open_window()
        self._set_command("python missing_script.py")
        first = self.engine.advance(self.run.id, self.step.step_id,
                                    self.confirmation.id, self.snapshot.id,
                                    confirm_execution=True)
        self.assertEqual(first.status, "blocked")
        run = database.get_cross_project_orchestration_run(self.conn, self.run.id)
        self.assertEqual(run["status"], "blocked")

        with self.assertRaises(ValueError):
            self.engine.advance(self.run.id, self.step.step_id,
                                self.confirmation.id, self.snapshot.id,
                                confirm_execution=True)

        self.policies.set_policy(self.run.id, 1)
        request = self.retry_gate.request_retry(self.run.id, self.step.step_id)
        self.assertEqual(request.status, "authorized")
        self.assertEqual(request.attempt_number, 2)

        with self.assertRaises(ValueError):
            self.engine.advance(self.run.id, self.step.step_id,
                                self.confirmation.id, self.snapshot.id,
                                confirm_execution=True)

        self._set_command("pwd")
        confirmation, snapshot = self._fresh_confirmation_and_snapshot()
        retry = self.engine.advance(self.run.id, self.step.step_id,
                                    confirmation.id, snapshot.id,
                                    confirm_execution=True)
        self.assertEqual(retry.status, "executed")
        self.assertEqual(retry.attempt_number, 2)
        self.assertEqual(retry.retry_request_id, request.id)
        consumed = database.get_cross_project_orchestration_retry_request(
            self.conn, request.id)
        self.assertEqual(consumed["status"], "consumed")
        self.assertEqual(consumed["advancement_id"], retry.advancement_id)
        self.assertEqual(_count(self.conn, "cross_project_execution_attempts"), 2)


if __name__ == "__main__":
    unittest.main()
