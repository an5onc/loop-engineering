import os
import subprocess
import sys
import tempfile
import unittest

import database
from test_cross_project_execution_dry_run import _make_plan


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _run_cli(args, cwd, env):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


class CrossProjectExecutionAuditTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_audit as audit
        self.audit = audit
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "a.db"))
        self.addCleanup(self.conn.close)

    def test_audit_builds_and_persists(self):
        report = self.audit.CrossProjectExecutionAuditEngine(
            self.conn).build_report()
        self.assertGreater(report.total_checks, 0)
        audit_id = self.audit.CrossProjectExecutionAuditEngine(
            self.conn).save_audit(report)
        self.assertGreater(audit_id, 0)
        self.assertEqual(
            database.list_cross_project_execution_audits(self.conn)[0]["id"],
            audit_id)

    def test_audit_detects_blocked_dry_run(self):
        root = os.path.join(self.td.name, "alpha"); os.makedirs(root)
        plan = _make_plan(self.conn, root)
        database.save_cross_project_execution_dry_run(
            self.conn, plan.id, "now", "BLOCKED", 1, 0, 0, 0, 1,
            "blocked fixture")
        report = self.audit.CrossProjectExecutionAuditEngine(
            self.conn).build_report()
        self.assertIn(report.overall_status, ("WARN", "FAIL"))

    def test_markdown_report_path_safety(self):
        engine = self.audit.CrossProjectExecutionAuditEngine(self.conn)
        old = self.audit.REPORTS_DIR
        self.audit.REPORTS_DIR = os.path.join(self.td.name, "reports")
        self.addCleanup(setattr, self.audit, "REPORTS_DIR", old)
        report = engine.build_report()
        audit_id = engine.save_audit(report)
        md = engine.save_markdown_report(audit_id, report)
        self.assertTrue(self.audit.is_report_path(md.report_path))

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        audit = _run_cli(["--cross-project-execution-audit"], cwd, env)
        self.assertEqual(audit.returncode, 0, audit.stderr)
        lst = _run_cli(["--cross-project-execution-audits"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)
        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        aid = database.list_cross_project_execution_audits(conn)[0]["id"]
        show = _run_cli(
            ["--cross-project-execution-audit-show", str(aid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
