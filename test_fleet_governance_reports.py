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


class FleetGovernanceReportTests(unittest.TestCase):
    def setUp(self):
        import fleet_governance_reports as fleet
        self.fleet = fleet
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "f.db"))
        self.addCleanup(self.conn.close)
        self.registry = registry_mod.ProjectRegistry(self.conn)
        self.a = os.path.join(self.td.name, "a"); os.makedirs(self.a)

    def test_report_sections(self):
        self.registry.register_project("alpha", self.a)
        report = self.fleet.FleetGovernanceReporter(self.conn).build_report()
        for key in ("project_health", "stale_projects", "blocked_projects",
                    "missing_validations", "planning", "policy_summary"):
            self.assertIn(key, report.sections)
        self.assertEqual(report.summary["total_projects"], 1)

    def test_stale_and_blocked_counts(self):
        import shutil
        b = os.path.join(self.td.name, "b"); os.makedirs(b)
        self.registry.register_project("alpha", self.a)
        self.registry.register_project("beta", b)
        self.registry.set_status("beta", "blocked")
        shutil.rmtree(self.a)
        report = self.fleet.FleetGovernanceReporter(self.conn).build_report()
        self.assertGreaterEqual(report.summary["stale_projects"], 1)
        self.assertEqual(report.summary["blocked_projects"], 1)

    def test_persistence_and_report_path_safety(self):
        self.registry.register_project("alpha", self.a)
        reporter = self.fleet.FleetGovernanceReporter(self.conn)
        old = self.fleet.REPORTS_DIR
        self.fleet.REPORTS_DIR = os.path.join(self.td.name, "reports")
        self.addCleanup(setattr, self.fleet, "REPORTS_DIR", old)
        report = reporter.build_report()
        rid = reporter.save_report(report)
        self.assertGreater(rid, 0)
        md = reporter.save_markdown_report(rid)
        self.assertTrue(self.fleet.is_report_path(md.report_path))
        self.assertTrue(os.path.realpath(md.report_path).startswith(
            os.path.realpath(self.fleet.REPORTS_DIR) + os.sep))
        self.assertEqual(
            database.list_fleet_governance_reports(self.conn)[0]["id"], rid)

    def test_no_side_effect_tables(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        self.registry.register_project("alpha", self.a)
        reporter = self.fleet.FleetGovernanceReporter(self.conn)
        reporter.save_report(reporter.build_report())
        self.assertEqual({t: _count(self.conn, t) for t in before}, before)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        _run_cli(["--register-project", "alpha", "--root", self.a], cwd, env)

        rep = _run_cli(["--fleet-governance-report"], cwd, env)
        self.assertEqual(rep.returncode, 0, rep.stderr)
        self.assertIn("FLEET GOVERNANCE REPORT", rep.stdout)

        saved = _run_cli(["--fleet-governance-report", "--save-report"], cwd, env)
        self.assertEqual(saved.returncode, 0, saved.stderr)

        lst = _run_cli(["--fleet-governance-reports"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)

        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        rid = database.list_fleet_governance_reports(conn)[0]["id"]
        show = _run_cli(["--fleet-governance-report-show", str(rid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)

        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
