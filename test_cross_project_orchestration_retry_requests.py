import json
import os
import tempfile
import unittest

import database
from test_cross_project_execution_windows import _seed_orchestration_run


class CrossProjectOrchestrationRetryRequestTests(unittest.TestCase):
    def setUp(self):
        import cross_project_orchestration_retry_policies as policies
        import cross_project_orchestration_retry_requests as requests
        self.requests = requests
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "rr.db"))
        self.addCleanup(self.conn.close)
        self.run_id = _seed_orchestration_run(self.conn, status="blocked")
        self.run_step_id = database.save_cross_project_orchestration_run_step(
            self.conn, self.run_id, 11, 21, 31, "alpha", 1, "blocked")
        self.policies = policies.CrossProjectOrchestrationRetryPolicyManager(
            self.conn)
        self.gate = requests.CrossProjectOrchestrationRetryGate(self.conn)

    def _seed_advancement(self, status="blocked"):
        return database.save_cross_project_orchestration_step_advancement(
            self.conn, self.run_id, self.run_step_id, 11, 1, 1, 1, status,
            json.dumps([]))

    def test_retry_requires_active_policy(self):
        self._seed_advancement()
        with self.assertRaises(ValueError):
            self.gate.request_retry(self.run_id, 11)

    def test_retry_requires_blocked_step(self):
        self.policies.set_policy(self.run_id, 1)
        database.update_cross_project_orchestration_run_step(
            self.conn, self.run_step_id, "pending")
        with self.assertRaises(ValueError):
            self.gate.request_retry(self.run_id, 11)

    def test_retry_requires_prior_advancement(self):
        self.policies.set_policy(self.run_id, 1)
        with self.assertRaises(ValueError):
            self.gate.request_retry(self.run_id, 11)

    def test_authorize_reopens_step_and_run(self):
        self.policies.set_policy(self.run_id, 2)
        self._seed_advancement()
        request = self.gate.request_retry(self.run_id, 11, requested_by="anson",
                                          reason="transient failure")
        self.assertEqual(request.status, "authorized")
        self.assertEqual(request.attempt_number, 2)
        self.assertEqual(request.run_step_id, self.run_step_id)
        step = database.get_cross_project_orchestration_run_step(
            self.conn, self.run_step_id)
        self.assertEqual(step["status"], "pending")
        run = database.get_cross_project_orchestration_run(self.conn, self.run_id)
        self.assertEqual(run["status"], "running")
        events = self.conn.execute(
            "SELECT event_type FROM cross_project_orchestration_run_events "
            "WHERE run_id=?", (self.run_id,)).fetchall()
        self.assertIn("retry_authorized", [row["event_type"] for row in events])

    def test_no_stacked_authorized_requests(self):
        self.policies.set_policy(self.run_id, 2)
        self._seed_advancement()
        self.gate.request_retry(self.run_id, 11)
        database.update_cross_project_orchestration_run_step(
            self.conn, self.run_step_id, "blocked")
        with self.assertRaises(ValueError):
            self.gate.request_retry(self.run_id, 11)

    def test_retry_budget_exhaustion_fails_closed(self):
        self.policies.set_policy(self.run_id, 1)
        self._seed_advancement()
        self._seed_advancement()
        with self.assertRaises(ValueError):
            self.gate.request_retry(self.run_id, 11)


if __name__ == "__main__":
    unittest.main()
