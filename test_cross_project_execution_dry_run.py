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


def _make_plan(conn, root):
    import cross_project_execution_intents as intents
    import cross_project_execution_readiness as readiness
    import cross_project_execution_plans as plans
    import cross_project_execution_commands as commands
    registry_mod.ProjectRegistry(conn).register_project("alpha", root)
    intent = intents.CrossProjectExecutionIntentRegistry(conn).create_intent(
        "manual", 0, "execute", "owner")
    ready = readiness.CrossProjectExecutionReadinessResolver(conn).resolve(intent.id)
    plan = plans.CrossProjectExecutionPlanBuilder(conn).build_plan(intent.id, ready.id)
    commands.CrossProjectExecutionCommandProposer(conn).propose(plan.id)
    return plan


class CrossProjectExecutionDryRunTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_dry_run as dry
        self.dry = dry
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "d.db"))
        self.addCleanup(self.conn.close)
        self.a = os.path.join(self.td.name, "a"); os.makedirs(self.a)
        self.plan = _make_plan(self.conn, self.a)

    def test_dry_run_passes_for_safe_plan(self):
        report = self.dry.CrossProjectExecutionDryRunValidator(
            self.conn).validate(self.plan.id)
        self.assertEqual(report.plan_id, self.plan.id)
        self.assertEqual(report.overall_status, "PASS")
        self.assertTrue(report.findings)

    def test_dry_run_blocks_missing_command_proposals(self):
        import cross_project_execution_intents as intents
        import cross_project_execution_readiness as readiness
        import cross_project_execution_plans as plans
        b = os.path.join(self.td.name, "b"); os.makedirs(b)
        registry_mod.ProjectRegistry(self.conn).register_project("beta", b)
        intent = intents.CrossProjectExecutionIntentRegistry(self.conn).create_intent(
            "manual", 0, "other", "owner")
        ready = readiness.CrossProjectExecutionReadinessResolver(self.conn).resolve(
            intent.id)
        plan = plans.CrossProjectExecutionPlanBuilder(self.conn).build_plan(
            intent.id, ready.id)
        report = self.dry.CrossProjectExecutionDryRunValidator(
            self.conn).validate(plan.id)
        self.assertEqual(report.overall_status, "BLOCKED")

    def test_dry_run_blocks_missing_gating_metadata(self):
        step = database.list_cross_project_execution_plan_steps(
            self.conn, self.plan.id)[0]
        self.conn.execute(
            "UPDATE cross_project_execution_plan_steps SET gating_json='{}' "
            "WHERE id=?", (step["id"],))
        self.conn.commit()
        report = self.dry.CrossProjectExecutionDryRunValidator(
            self.conn).validate(self.plan.id)
        self.assertEqual(report.overall_status, "BLOCKED")
        self.assertIn("missing_gating", [f.category for f in report.findings])

    def test_missing_plan_fails_closed(self):
        with self.assertRaises(ValueError):
            self.dry.CrossProjectExecutionDryRunValidator(self.conn).validate(9999)

    def test_persistence_and_listing(self):
        validator = self.dry.CrossProjectExecutionDryRunValidator(self.conn)
        report = validator.validate(self.plan.id)
        self.assertEqual(validator.get_dry_run(report.id).plan_id, self.plan.id)
        self.assertEqual(
            database.list_cross_project_execution_dry_runs(self.conn)[0]["id"],
            report.id)

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
        _run_cli([
            "--plan-cross-project-execution", str(iid), "--readiness", str(rid)],
            cwd, env)
        pid = database.list_cross_project_execution_plans(conn)[0]["id"]
        _run_cli(["--propose-cross-project-execution-commands", str(pid)], cwd, env)
        dry = _run_cli(["--dry-run-cross-project-execution", str(pid)], cwd, env)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        lst = _run_cli(["--cross-project-execution-dry-runs"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)
        did = database.list_cross_project_execution_dry_runs(conn)[0]["id"]
        show = _run_cli(["--cross-project-execution-dry-run", str(did)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
