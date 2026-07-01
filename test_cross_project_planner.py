import os
import subprocess
import sys
import tempfile
import unittest

import database
import multi_project_registry as registry_mod


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _run_cli(args, cwd, env):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


class CrossProjectPlannerTests(unittest.TestCase):
    def setUp(self):
        import cross_project_planner as planner
        self.planner = planner
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "p.db"))
        self.addCleanup(self.conn.close)
        self.registry = registry_mod.ProjectRegistry(self.conn)
        self.a = os.path.join(self.td.name, "a"); os.makedirs(self.a)
        self.b = os.path.join(self.td.name, "b"); os.makedirs(self.b)

    def test_plan_includes_active_excludes_others(self):
        self.registry.register_project("alpha", self.a)
        self.registry.register_project("beta", self.b)
        self.registry.set_status("beta", "archived")
        engine = self.planner.CrossProjectPlanner(self.conn)
        plan = engine.plan_work("Review safety drift")
        self.assertIn("alpha", plan.included_project_keys)
        self.assertIn("beta", plan.excluded_project_keys)
        self.assertEqual(plan.status, "proposed")
        self.assertEqual(len(plan.items), 1)
        self.assertEqual(plan.items[0].project_key, "alpha")

    def test_blocked_project_creates_safety_blocker(self):
        self.registry.register_project("alpha", self.a)
        self.registry.set_status("alpha", "blocked")
        engine = self.planner.CrossProjectPlanner(self.conn)
        plan = engine.plan_work("Touch alpha")
        self.assertTrue(plan.safety_blockers)
        self.assertEqual(plan.status, "blocked")

    def test_required_approvals_present(self):
        self.registry.register_project("alpha", self.a)
        engine = self.planner.CrossProjectPlanner(self.conn)
        plan = engine.plan_work("Do work")
        self.assertTrue(plan.required_approvals)

    def test_persistence_and_listing(self):
        self.registry.register_project("alpha", self.a)
        engine = self.planner.CrossProjectPlanner(self.conn)
        plan = engine.plan_work("Do work")
        self.assertGreater(plan.id, 0)
        reloaded = engine.get_plan(plan.id)
        self.assertEqual(reloaded.source_request, "Do work")
        self.assertEqual(reloaded.included_project_keys, plan.included_project_keys)
        self.assertEqual(
            database.list_cross_project_work_plans(self.conn)[0]["id"], plan.id)
        events = database.list_cross_project_plan_events(self.conn, plan.id)
        self.assertTrue(events)

    def test_set_status_valid_and_invalid(self):
        self.registry.register_project("alpha", self.a)
        engine = self.planner.CrossProjectPlanner(self.conn)
        plan = engine.plan_work("Do work")
        updated = engine.set_status(plan.id, "approved_for_handoff")
        self.assertEqual(updated.status, "approved_for_handoff")
        with self.assertRaises(ValueError):
            engine.set_status(plan.id, "garbage")

    def test_no_side_effect_tables(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        self.registry.register_project("alpha", self.a)
        engine = self.planner.CrossProjectPlanner(self.conn)
        engine.plan_work("Do work")
        self.assertEqual({t: _count(self.conn, t) for t in before}, before)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        _run_cli(["--register-project", "alpha", "--root", self.a], cwd, env)

        plan = _run_cli(
            ["--plan-cross-project-work", "Review all projects"], cwd, env)
        self.assertEqual(plan.returncode, 0, plan.stderr)
        self.assertIn("CROSS-PROJECT", plan.stdout.upper())

        plans = _run_cli(["--cross-project-plans"], cwd, env)
        self.assertEqual(plans.returncode, 0, plans.stderr)

        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        pid = database.list_cross_project_work_plans(conn)[0]["id"]
        show = _run_cli(["--cross-project-plan", str(pid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)

        status = _run_cli(
            ["--set-cross-project-plan-status", str(pid), "cancelled"], cwd, env)
        self.assertEqual(status.returncode, 0, status.stderr)

        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
