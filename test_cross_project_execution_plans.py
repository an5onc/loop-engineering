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


class CrossProjectExecutionPlanTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_intents as intents
        import cross_project_execution_readiness as readiness
        import cross_project_execution_plans as plans
        self.intents = intents
        self.readiness = readiness
        self.plans = plans
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "p.db"))
        self.addCleanup(self.conn.close)
        self.registry = registry_mod.ProjectRegistry(self.conn)
        self.a = os.path.join(self.td.name, "a"); os.makedirs(self.a)
        self.registry.register_project("alpha", self.a)
        self.intent = self.intents.CrossProjectExecutionIntentRegistry(
            self.conn).create_intent("manual", 0, "execute", "owner")
        self.ready = self.readiness.CrossProjectExecutionReadinessResolver(
            self.conn).resolve(self.intent.id)

    def test_build_plan_from_readiness(self):
        plan = self.plans.CrossProjectExecutionPlanBuilder(
            self.conn).build_plan(self.intent.id, self.ready.id)
        self.assertEqual(plan.intent_id, self.intent.id)
        self.assertEqual(plan.readiness_report_id, self.ready.id)
        self.assertEqual(plan.status, "planned")
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].project_key, "alpha")
        self.assertTrue(plan.required_approvals)
        self.assertTrue(plan.rollback_requirements)
        self.assertTrue(plan.validation_requirements)

    def test_mismatched_readiness_fails_closed(self):
        other = self.intents.CrossProjectExecutionIntentRegistry(
            self.conn).create_intent("manual", 0, "other", "owner")
        with self.assertRaises(ValueError):
            self.plans.CrossProjectExecutionPlanBuilder(
                self.conn).build_plan(other.id, self.ready.id)

    def test_missing_intent_or_readiness_fails(self):
        builder = self.plans.CrossProjectExecutionPlanBuilder(self.conn)
        with self.assertRaises(ValueError):
            builder.build_plan(9999, self.ready.id)
        with self.assertRaises(ValueError):
            builder.build_plan(self.intent.id, 9999)

    def test_persistence_and_listing(self):
        builder = self.plans.CrossProjectExecutionPlanBuilder(self.conn)
        plan = builder.build_plan(self.intent.id, self.ready.id)
        self.assertGreater(plan.id, 0)
        self.assertEqual(builder.get_plan(plan.id).steps[0].project_key, "alpha")
        self.assertEqual(
            database.list_cross_project_execution_plans(self.conn)[0]["id"],
            plan.id)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        _run_cli(["--register-project", "alpha", "--root", self.a], cwd, env)
        _run_cli([
            "--create-cross-project-execution-intent", "--source-type", "manual",
            "--source-id", "0", "--title", "x", "--owner", "operator"], cwd, env)
        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        iid = database.list_cross_project_execution_intents(conn)[0]["id"]
        _run_cli(["--cross-project-execution-readiness", str(iid)], cwd, env)
        rid = database.list_cross_project_execution_readiness_reports(conn)[0]["id"]
        build = _run_cli([
            "--plan-cross-project-execution", str(iid), "--readiness", str(rid)],
            cwd, env)
        self.assertEqual(build.returncode, 0, build.stderr)
        lst = _run_cli(["--cross-project-execution-plans"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)
        pid = database.list_cross_project_execution_plans(conn)[0]["id"]
        show = _run_cli(["--cross-project-execution-plan", str(pid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
