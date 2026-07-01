import os
import shutil
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


class CrossProjectExecutionReadinessTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_intents as intents
        import cross_project_execution_readiness as readiness
        self.intents = intents
        self.readiness = readiness
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "r.db"))
        self.addCleanup(self.conn.close)
        self.registry = registry_mod.ProjectRegistry(self.conn)
        self.a = os.path.join(self.td.name, "a"); os.makedirs(self.a)
        self.b = os.path.join(self.td.name, "b"); os.makedirs(self.b)
        self.intent = self.intents.CrossProjectExecutionIntentRegistry(
            self.conn).create_intent("manual", 0, "execute", "owner")

    def test_readiness_marks_active_project_ready(self):
        self.registry.register_project("alpha", self.a)
        report = self.readiness.CrossProjectExecutionReadinessResolver(
            self.conn).resolve(self.intent.id)
        self.assertEqual(report.intent_id, self.intent.id)
        self.assertEqual(report.summary["ready_projects"], 1)
        self.assertEqual(report.project_results[0]["status"], "ready")

    def test_missing_root_and_blocked_project_blocked(self):
        self.registry.register_project("alpha", self.a)
        self.registry.register_project("beta", self.b)
        shutil.rmtree(self.a)
        self.registry.set_status("beta", "blocked")
        report = self.readiness.CrossProjectExecutionReadinessResolver(
            self.conn).resolve(self.intent.id)
        statuses = {p["project_key"]: p["status"] for p in report.project_results}
        self.assertEqual(statuses["alpha"], "blocked")
        self.assertEqual(statuses["beta"], "blocked")
        self.assertEqual(report.overall_status, "BLOCKED")

    def test_fail_level_governance_finding_blocks(self):
        self.registry.register_project("alpha", self.a)
        eid = database.save_governance_policy_evaluation(
            self.conn, "now", "FAIL", 1, 0, 0, 1, 0, '["p"]', "fail")
        database.save_governance_policy_finding(
            self.conn, eid, "p", "not_stale", "alpha", "fail", "FAIL",
            "p::not_stale::alpha", "evidence", "message", None)
        report = self.readiness.CrossProjectExecutionReadinessResolver(
            self.conn).resolve(self.intent.id)
        self.assertEqual(report.project_results[0]["status"], "blocked")

    def test_invalid_intent_fails_closed(self):
        with self.assertRaises(ValueError):
            self.readiness.CrossProjectExecutionReadinessResolver(
                self.conn).resolve(9999)

    def test_persistence_and_report_path_safety(self):
        self.registry.register_project("alpha", self.a)
        resolver = self.readiness.CrossProjectExecutionReadinessResolver(self.conn)
        old = self.readiness.REPORTS_DIR
        self.readiness.REPORTS_DIR = os.path.join(self.td.name, "reports")
        self.addCleanup(setattr, self.readiness, "REPORTS_DIR", old)
        report = resolver.resolve(self.intent.id)
        md = resolver.save_markdown_report(report.id)
        self.assertTrue(self.readiness.is_report_path(md.report_path))
        self.assertEqual(
            database.list_cross_project_execution_readiness_reports(
                self.conn)[0]["id"], report.id)

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
        res = _run_cli(["--cross-project-execution-readiness", str(iid)], cwd, env)
        self.assertEqual(res.returncode, 0, res.stderr)
        lst = _run_cli(["--cross-project-execution-readiness-reports"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)
        rid = database.list_cross_project_execution_readiness_reports(conn)[0]["id"]
        show = _run_cli(
            ["--cross-project-execution-readiness-show", str(rid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
