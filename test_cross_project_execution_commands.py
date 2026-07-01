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


class CrossProjectExecutionCommandTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_intents as intents
        import cross_project_execution_readiness as readiness
        import cross_project_execution_plans as plans
        import cross_project_execution_commands as commands
        self.commands = commands
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "c.db"))
        self.addCleanup(self.conn.close)
        self.registry = registry_mod.ProjectRegistry(self.conn)
        self.a = os.path.join(self.td.name, "a"); os.makedirs(self.a)
        self.registry.register_project("alpha", self.a)
        intent = intents.CrossProjectExecutionIntentRegistry(
            self.conn).create_intent("manual", 0, "execute", "owner")
        ready = readiness.CrossProjectExecutionReadinessResolver(
            self.conn).resolve(intent.id)
        self.plan = plans.CrossProjectExecutionPlanBuilder(
            self.conn).build_plan(intent.id, ready.id)

    def test_propose_commands_as_advisory_text(self):
        proposals = self.commands.CrossProjectExecutionCommandProposer(
            self.conn).propose(self.plan.id)
        self.assertTrue(proposals)
        self.assertEqual(proposals[0].status, "proposed")
        self.assertIn("validate-project", proposals[0].command_text)
        self.assertTrue(proposals[0].requires_approval)
        self.assertEqual(proposals[0].allowlist_category, "metadata_validation")

    def test_missing_plan_fails_closed(self):
        with self.assertRaises(ValueError):
            self.commands.CrossProjectExecutionCommandProposer(self.conn).propose(9999)

    def test_persistence_and_listing(self):
        proposer = self.commands.CrossProjectExecutionCommandProposer(self.conn)
        proposals = proposer.propose(self.plan.id)
        self.assertEqual(
            database.list_cross_project_execution_command_proposals(
                self.conn)[0]["id"], proposals[0].id)
        self.assertEqual(
            proposer.get_proposal(proposals[0].id).command_type,
            "validation")

    def test_propose_is_idempotent_for_plan(self):
        proposer = self.commands.CrossProjectExecutionCommandProposer(self.conn)
        first = proposer.propose(self.plan.id)
        second = proposer.propose(self.plan.id)
        self.assertEqual([p.id for p in second], [p.id for p in first])
        self.assertEqual(
            len(database.list_cross_project_execution_command_proposals(
                self.conn, plan_id=self.plan.id)),
            len(first))

    def test_no_side_effect_tables(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        self.commands.CrossProjectExecutionCommandProposer(
            self.conn).propose(self.plan.id)
        self.assertEqual({t: _count(self.conn, t) for t in before}, before)

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
        prop = _run_cli(["--propose-cross-project-execution-commands", str(pid)],
                        cwd, env)
        self.assertEqual(prop.returncode, 0, prop.stderr)
        lst = _run_cli(["--cross-project-execution-command-proposals"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)
        cid = database.list_cross_project_execution_command_proposals(conn)[0]["id"]
        show = _run_cli(
            ["--cross-project-execution-command-proposal", str(cid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
