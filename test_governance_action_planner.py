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


class GovernanceActionPlannerTests(unittest.TestCase):
    def setUp(self):
        import governance_action_planner as planner
        self.planner = planner
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "ap.db"))
        self.addCleanup(self.conn.close)
        self.registry = registry_mod.ProjectRegistry(self.conn)
        self.policies = policies_mod.GovernancePolicyRegistry(self.conn)
        self.a = os.path.join(self.td.name, "a"); os.makedirs(self.a)

    def _failing_eval(self):
        self.registry.register_project("alpha", self.a)
        shutil.rmtree(self.a)
        self.policies.create_policy("p", ["not_stale"])
        return eval_mod.GovernanceEvaluationEngine(self.conn).evaluate()

    def test_plan_from_unresolved_findings(self):
        ev = self._failing_eval()
        plan = self.planner.GovernanceActionPlanner(self.conn).plan(ev.id)
        self.assertEqual(plan.source_evaluation_id, ev.id)
        self.assertEqual(len(plan.items), 1)
        self.assertEqual(plan.status, "proposed")
        self.assertTrue(plan.suggested_commands)

    def test_plan_uses_latest_evaluation_by_default(self):
        ev = self._failing_eval()
        plan = self.planner.GovernanceActionPlanner(self.conn).plan()
        self.assertEqual(plan.source_evaluation_id, ev.id)

    def test_no_evaluations_fails_closed(self):
        planner = self.planner.GovernanceActionPlanner(self.conn)
        with self.assertRaises(ValueError):
            planner.plan()

    def test_unknown_evaluation_fails_closed(self):
        planner = self.planner.GovernanceActionPlanner(self.conn)
        with self.assertRaises(ValueError):
            planner.plan(9999)

    def test_clean_eval_has_no_items(self):
        self.registry.register_project("alpha", self.a)
        self.policies.create_policy("p", ["not_stale"])
        ev = eval_mod.GovernanceEvaluationEngine(self.conn).evaluate()
        plan = self.planner.GovernanceActionPlanner(self.conn).plan(ev.id)
        self.assertEqual(len(plan.items), 0)

    def test_commands_are_text_only(self):
        ev = self._failing_eval()
        plan = self.planner.GovernanceActionPlanner(self.conn).plan(ev.id)
        for item in plan.items:
            for cmd in item.suggested_commands:
                self.assertIsInstance(cmd, str)

    def test_persistence_and_listing(self):
        ev = self._failing_eval()
        planner = self.planner.GovernanceActionPlanner(self.conn)
        plan = planner.plan(ev.id)
        self.assertGreater(plan.id, 0)
        self.assertEqual(
            database.list_governance_action_plans(self.conn)[0]["id"], plan.id)
        reloaded = planner.get_plan(plan.id)
        self.assertEqual(len(reloaded.items), len(plan.items))

    def test_no_side_effect_tables(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        ev = self._failing_eval()
        self.planner.GovernanceActionPlanner(self.conn).plan(ev.id)
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

        plan = _run_cli(["--plan-governance-actions"], cwd, env)
        self.assertEqual(plan.returncode, 0, plan.stderr)
        self.assertIn("GOVERNANCE ACTION PLAN", plan.stdout)

        lst = _run_cli(["--governance-action-plans"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)

        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        pid = database.list_governance_action_plans(conn)[0]["id"]
        show = _run_cli(["--governance-action-plan", str(pid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)

        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
