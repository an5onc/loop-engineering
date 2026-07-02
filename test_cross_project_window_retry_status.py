import json
import os
import tempfile
import unittest

import database
from test_cross_project_execution_windows import _seed_orchestration_run


class CrossProjectWindowRetryStatusTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_window_controls as controls
        import cross_project_execution_windows as windows
        import cross_project_orchestration_retry_policies as policies
        import cross_project_window_retry_status as status_mod
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "st.db"))
        self.addCleanup(self.conn.close)
        self.run_id = _seed_orchestration_run(self.conn)
        self.run_step_id = database.save_cross_project_orchestration_run_step(
            self.conn, self.run_id, 11, 21, 31, "alpha", 1, "pending")
        self.windows = windows.CrossProjectExecutionWindowManager(self.conn)
        self.gate = controls.CrossProjectExecutionWindowControlGate(self.conn)
        self.policies = policies.CrossProjectOrchestrationRetryPolicyManager(
            self.conn)
        self.resolver = status_mod.CrossProjectWindowRetryStatusResolver(self.conn)

    def _seed_advancement(self, confirmation_id=1):
        return database.save_cross_project_orchestration_step_advancement(
            self.conn, self.run_id, self.run_step_id, 11, confirmation_id, 1, 1,
            "blocked", json.dumps([]))

    def test_missing_window_asks_to_define(self):
        status = self.resolver.resolve(self.run_id)
        self.assertEqual(status.window_status, "missing")
        self.assertIn("define an execution window", status.next_action)

    def test_defined_window_asks_to_open(self):
        self.windows.define_window(self.run_id, "w")
        status = self.resolver.resolve(self.run_id)
        self.assertEqual(status.window_status, "closed")
        self.assertIn("open an execution window", status.next_action)

    def test_open_window_with_pending_step_asks_to_advance(self):
        window = self.windows.define_window(self.run_id, "w")
        self.gate.open_window(window.id)
        status = self.resolver.resolve(self.run_id)
        self.assertEqual(status.window_status, "open")
        self.assertIn("advance the pending step", status.next_action)

    def test_blocked_step_without_policy_asks_for_policy(self):
        window = self.windows.define_window(self.run_id, "w")
        self.gate.open_window(window.id)
        database.update_cross_project_orchestration_run_step(
            self.conn, self.run_step_id, "blocked")
        status = self.resolver.resolve(self.run_id, step_id=11)
        self.assertIn("set a retry policy", status.next_action)

    def test_blocked_step_with_budget_suggests_restore_first(self):
        window = self.windows.define_window(self.run_id, "w")
        self.gate.open_window(window.id)
        database.update_cross_project_orchestration_run_step(
            self.conn, self.run_step_id, "blocked")
        self.policies.set_policy(self.run_id, 2)
        self._seed_advancement()
        status = self.resolver.resolve(self.run_id, step_id=11)
        self.assertEqual(status.retries_used, 0)
        self.assertEqual(status.retries_allowed, 2)
        self.assertIn("restore first", status.next_action)
        self.assertIn("request an authorized retry", status.next_action)

    def test_blocked_step_after_restore_asks_for_retry_request(self):
        window = self.windows.define_window(self.run_id, "w")
        self.gate.open_window(window.id)
        database.update_cross_project_orchestration_run_step(
            self.conn, self.run_step_id, "blocked")
        self.policies.set_policy(self.run_id, 2)
        self._seed_advancement()
        database.save_cross_project_orchestration_step_rollback(
            self.conn, self.run_id, self.run_step_id, 11, 1, 1, "restored",
            "restored for test")
        status = self.resolver.resolve(self.run_id, step_id=11)
        self.assertTrue(status.next_action.startswith(
            "request an authorized retry"))

    def test_authorized_request_asks_for_fresh_confirmation_advance(self):
        window = self.windows.define_window(self.run_id, "w")
        self.gate.open_window(window.id)
        database.update_cross_project_orchestration_run_step(
            self.conn, self.run_step_id, "blocked")
        policy = self.policies.set_policy(self.run_id, 2)
        self._seed_advancement()
        database.save_cross_project_orchestration_retry_request(
            self.conn, self.run_id, self.run_step_id, 11, policy.id, 2,
            "authorized", "operator", None)
        status = self.resolver.resolve(self.run_id, step_id=11)
        self.assertIn("fresh", status.next_action)

    def test_exhausted_budget_reports_exhaustion(self):
        window = self.windows.define_window(self.run_id, "w")
        self.gate.open_window(window.id)
        database.update_cross_project_orchestration_run_step(
            self.conn, self.run_step_id, "blocked")
        self.policies.set_policy(self.run_id, 1)
        self._seed_advancement(confirmation_id=1)
        self._seed_advancement(confirmation_id=2)
        status = self.resolver.resolve(self.run_id, step_id=11)
        self.assertEqual(status.retries_used, 1)
        self.assertIn("retry budget exhausted", status.next_action)
        self.assertIn("--restoration-status", status.next_action)


if __name__ == "__main__":
    unittest.main()
