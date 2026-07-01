import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import database
import multi_project_registry as registry_mod
import multi_project_governance_policies as policies_mod
import multi_project_governance_evaluation as eval_mod


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _run_cli(args, cwd, env):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


class GovernanceReviewQueueTests(unittest.TestCase):
    def setUp(self):
        import governance_review_queue as queue
        self.queue = queue
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "q.db"))
        self.addCleanup(self.conn.close)
        self.registry = registry_mod.ProjectRegistry(self.conn)
        self.policies = policies_mod.GovernancePolicyRegistry(self.conn)
        self.a = os.path.join(self.td.name, "a"); os.makedirs(self.a)

    def _failing_evaluation(self):
        self.registry.register_project("alpha", self.a)
        shutil.rmtree(self.a)
        self.policies.create_policy("p", ["not_stale"])
        return eval_mod.GovernanceEvaluationEngine(self.conn).evaluate()

    def test_create_review_items_from_findings(self):
        ev = self._failing_evaluation()
        engine = self.queue.GovernanceReviewQueue(self.conn)
        items = engine.create_items(ev.id)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].status, "open")
        self.assertEqual(items[0].rule_key, "not_stale")

    def test_create_review_items_is_idempotent_for_evaluation(self):
        ev = self._failing_evaluation()
        engine = self.queue.GovernanceReviewQueue(self.conn)
        first = engine.create_items(ev.id)
        second = engine.create_items(ev.id)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(len(engine.list_items()), 1)

    def test_pass_findings_do_not_create_items(self):
        self.registry.register_project("alpha", self.a)
        self.policies.create_policy("p", ["not_stale"])
        ev = eval_mod.GovernanceEvaluationEngine(self.conn).evaluate()
        engine = self.queue.GovernanceReviewQueue(self.conn)
        items = engine.create_items(ev.id)
        self.assertEqual(items, [])

    def test_unknown_evaluation_fails_closed(self):
        engine = self.queue.GovernanceReviewQueue(self.conn)
        with self.assertRaises(ValueError):
            engine.create_items(9999)

    def test_status_transitions(self):
        ev = self._failing_evaluation()
        engine = self.queue.GovernanceReviewQueue(self.conn)
        item = engine.create_items(ev.id)[0]
        for status in ("acknowledged", "waived", "resolved", "dismissed", "blocked"):
            updated = engine.set_status(item.id, status)
            self.assertEqual(updated.status, status)

    def test_invalid_status_rejected(self):
        ev = self._failing_evaluation()
        engine = self.queue.GovernanceReviewQueue(self.conn)
        item = engine.create_items(ev.id)[0]
        with self.assertRaises(ValueError):
            engine.set_status(item.id, "closed")

    def test_set_status_unknown_item_fails(self):
        engine = self.queue.GovernanceReviewQueue(self.conn)
        with self.assertRaises(ValueError):
            engine.set_status(4242, "acknowledged")

    def test_listing_and_filter(self):
        ev = self._failing_evaluation()
        engine = self.queue.GovernanceReviewQueue(self.conn)
        item = engine.create_items(ev.id)[0]
        engine.set_status(item.id, "resolved")
        self.assertEqual(len(engine.list_items(status="resolved")), 1)
        self.assertEqual(len(engine.list_items(status="open")), 0)

    def test_no_side_effect_tables(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        ev = self._failing_evaluation()
        engine = self.queue.GovernanceReviewQueue(self.conn)
        item = engine.create_items(ev.id)[0]
        engine.set_status(item.id, "acknowledged")
        self.assertEqual({t: _count(self.conn, t) for t in before}, before)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        _run_cli(["--register-project", "alpha", "--root", self.a], cwd, env)
        shutil.rmtree(self.a)
        _run_cli(["--create-governance-policy", "np", "--rules", "not_stale"],
                 cwd, env)
        _run_cli(["--evaluate-governance-policies"], cwd, env)
        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        eid = database.list_governance_policy_evaluations(conn)[0]["id"]

        create = _run_cli(
            ["--create-governance-review-items", str(eid)], cwd, env)
        self.assertEqual(create.returncode, 0, create.stderr)

        lst = _run_cli(["--governance-review-items"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)

        iid = database.list_governance_review_items(conn)[0]["id"]
        setst = _run_cli(
            ["--set-governance-review-status", str(iid), "acknowledged"], cwd, env)
        self.assertEqual(setst.returncode, 0, setst.stderr)

        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
