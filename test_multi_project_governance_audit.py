import os
import subprocess
import sys
import tempfile
import unittest

import database


EXPECTED_SECTIONS = {
    "policies", "evaluations", "review_queue", "waivers",
    "fleet_reporting", "safety_baseline",
}


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _run_cli(args, cwd, env):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


class MultiProjectGovernanceAuditTests(unittest.TestCase):
    def setUp(self):
        import multi_project_governance_audit as audit
        self.audit = audit
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "a.db"))
        self.addCleanup(self.conn.close)

    def test_report_sections(self):
        report = self.audit.GovernanceAuditEngine(self.conn).build_report()
        self.assertEqual({s.name for s in report.sections}, EXPECTED_SECTIONS)
        self.assertIn(report.overall_status,
                      {"PASS", "PASS_WITH_WARNINGS", "FAIL", "BLOCKED"})
        for s in report.sections:
            self.assertTrue(s.checks)

    def test_stale_waiver_flagged(self):
        import datetime
        past = (datetime.datetime.now()
                - datetime.timedelta(days=1)).isoformat(timespec="seconds")
        database.save_governance_waiver(
            self.conn, "p::not_stale::alpha", "p", "not_stale", "alpha",
            "reason", "owner", past, "active", None, None)
        report = self.audit.GovernanceAuditEngine(self.conn).build_report()
        waivers = next(s for s in report.sections if s.name == "waivers")
        names = {c.name: c.status for c in waivers.checks}
        self.assertIn("no expired-but-active waivers", names)
        self.assertEqual(names["no expired-but-active waivers"], "WARN")

    def test_safety_counts_unchanged(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        engine = self.audit.GovernanceAuditEngine(self.conn)
        report = engine.build_report()
        engine.save_audit(report)
        self.assertEqual({t: _count(self.conn, t) for t in before}, before)
        safety = next(s for s in report.sections if s.name == "safety_baseline")
        self.assertIn("no hidden command execution",
                      {c.name for c in safety.checks})

    def test_persistence_and_markdown_safety(self):
        engine = self.audit.GovernanceAuditEngine(self.conn)
        old = self.audit.REPORTS_DIR
        self.audit.REPORTS_DIR = os.path.join(self.td.name, "reports")
        self.addCleanup(setattr, self.audit, "REPORTS_DIR", old)
        report = engine.build_report()
        audit_id = engine.save_audit(report)
        md = engine.save_markdown_report(audit_id, report)
        self.assertTrue(self.audit.is_markdown_report_path(md.report_path))
        self.assertTrue(os.path.realpath(md.report_path).startswith(
            os.path.realpath(self.audit.REPORTS_DIR) + os.sep))
        stored = self.audit.report_from_row(
            database.get_multi_project_governance_audit(self.conn, audit_id))
        self.assertEqual(stored.total_checks, report.total_checks)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))

        run = _run_cli(["--multi-project-governance-audit"], cwd, env)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("MULTI-PROJECT GOVERNANCE AUDIT", run.stdout)

        saved = _run_cli(["--multi-project-governance-audit", "--save-report"],
                         cwd, env)
        self.assertEqual(saved.returncode, 0, saved.stderr)

        lst = _run_cli(["--multi-project-governance-audits"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)

        show = _run_cli(["--multi-project-governance-audit-show", "latest"],
                        cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)

        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
