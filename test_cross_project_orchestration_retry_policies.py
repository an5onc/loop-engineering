import os
import tempfile
import unittest

import database
from test_cross_project_execution_windows import _seed_orchestration_run


class CrossProjectOrchestrationRetryPolicyTests(unittest.TestCase):
    def setUp(self):
        import cross_project_orchestration_retry_policies as policies
        self.policies = policies
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "rp.db"))
        self.addCleanup(self.conn.close)
        self.run_id = _seed_orchestration_run(self.conn)
        self.manager = policies.CrossProjectOrchestrationRetryPolicyManager(self.conn)

    def test_set_policy_within_cap(self):
        policy = self.manager.set_policy(self.run_id, 2, created_by="anson")
        self.assertEqual(policy.max_retries, 2)
        self.assertEqual(policy.status, "active")
        self.assertEqual(policy.created_by, "anson")
        found = self.manager.get_policy_for_run(self.run_id)
        self.assertEqual(found.id, policy.id)

    def test_set_policy_requires_existing_run(self):
        with self.assertRaises(ValueError):
            self.manager.set_policy(999, 1)

    def test_set_policy_enforces_bounds(self):
        with self.assertRaises(ValueError):
            self.manager.set_policy(self.run_id, 0)
        with self.assertRaises(ValueError):
            self.manager.set_policy(self.run_id, self.policies.MAX_RETRY_LIMIT + 1)
        with self.assertRaises(ValueError):
            self.manager.set_policy(self.run_id, "many")

    def test_policy_is_write_once_per_run(self):
        self.manager.set_policy(self.run_id, 1)
        with self.assertRaises(ValueError):
            self.manager.set_policy(self.run_id, 3)


if __name__ == "__main__":
    unittest.main()
