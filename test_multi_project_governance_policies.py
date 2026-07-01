import os
import subprocess
import sys
import tempfile
import unittest

import database


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _run_cli(args, cwd, env):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


class GovernancePolicyRegistryTests(unittest.TestCase):
    def setUp(self):
        import multi_project_governance_policies as policies
        self.policies = policies
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "g.db"))
        self.addCleanup(self.conn.close)

    def test_rule_registry_shape(self):
        self.assertTrue(self.policies.RULE_REGISTRY)
        for key, rule in self.policies.RULE_REGISTRY.items():
            self.assertIn(rule.default_severity, ("fail", "warn"))
            self.assertIn(rule.scope, ("project", "fleet"))
            self.assertTrue(callable(rule.evaluate))

    def test_named_fleet_rules_present(self):
        for key in ("require_validation", "validation_not_failing",
                    "not_stale", "blocked_project_handling",
                    "approval_freshness", "handoff_schedule_integrity",
                    "audit_recency"):
            self.assertIn(key, self.policies.RULE_REGISTRY)

    def test_create_and_get(self):
        engine = self.policies.GovernancePolicyRegistry(self.conn)
        keys = ["not_stale", "require_validation"]
        policy = engine.create_policy("baseline", keys, name="Baseline")
        self.assertGreater(policy.id, 0)
        self.assertEqual(policy.status, "active")
        fetched = engine.get_policy(policy.id)
        self.assertEqual(fetched.rule_keys, keys)

    def test_invalid_key_rejected(self):
        engine = self.policies.GovernancePolicyRegistry(self.conn)
        with self.assertRaises(ValueError):
            engine.create_policy("bad key!", ["not_stale"])

    def test_unknown_rule_rejected(self):
        engine = self.policies.GovernancePolicyRegistry(self.conn)
        with self.assertRaises(ValueError):
            engine.create_policy("p", ["nope"])

    def test_empty_rules_rejected(self):
        engine = self.policies.GovernancePolicyRegistry(self.conn)
        with self.assertRaises(ValueError):
            engine.create_policy("p", [])

    def test_duplicate_rejected(self):
        engine = self.policies.GovernancePolicyRegistry(self.conn)
        engine.create_policy("dup", ["not_stale"])
        with self.assertRaises(ValueError):
            engine.create_policy("dup", ["not_stale"])
        self.assertEqual(_count(self.conn, "governance_policies"), 1)

    def test_set_status_valid_invalid(self):
        engine = self.policies.GovernancePolicyRegistry(self.conn)
        p = engine.create_policy("p", ["not_stale"])
        updated = engine.set_status(p.id, "inactive")
        self.assertEqual(updated.status, "inactive")
        with self.assertRaises(ValueError):
            engine.set_status(p.id, "bogus")

    def test_set_status_unknown_id_fails_closed(self):
        engine = self.policies.GovernancePolicyRegistry(self.conn)
        with self.assertRaises(ValueError):
            engine.set_status(999, "inactive")

    def test_ensure_default_idempotent(self):
        engine = self.policies.GovernancePolicyRegistry(self.conn)
        a = engine.ensure_default_policy()
        b = engine.ensure_default_policy()
        self.assertEqual(a.id, b.id)
        self.assertEqual(_count(self.conn, "governance_policies"), 1)

    def test_no_side_effect_tables(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        engine = self.policies.GovernancePolicyRegistry(self.conn)
        engine.create_policy("p", ["not_stale"])
        self.assertEqual({t: _count(self.conn, t) for t in before}, before)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))

        empty = _run_cli(["--governance-policies"], cwd, env)
        self.assertEqual(empty.returncode, 0, empty.stderr)

        created = _run_cli(
            ["--create-governance-policy", "--default"], cwd, env)
        self.assertEqual(created.returncode, 0, created.stderr)

        listed = _run_cli(["--governance-policies"], cwd, env)
        self.assertEqual(listed.returncode, 0, listed.stderr)

        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        pid = database.list_governance_policies(conn)[0]["id"]
        show = _run_cli(["--governance-policy", str(pid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)

        status = _run_cli(
            ["--set-governance-policy-status", str(pid), "inactive"], cwd, env)
        self.assertEqual(status.returncode, 0, status.stderr)

        bad = _run_cli(["--governance-policy", "9999"], cwd, env)
        self.assertEqual(bad.returncode, 1)

        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
