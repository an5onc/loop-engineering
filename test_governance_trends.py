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


class GovernanceTrendTests(unittest.TestCase):
    def setUp(self):
        import governance_trends as trends
        self.trends = trends
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "t.db"))
        self.addCleanup(self.conn.close)
        self.registry = registry_mod.ProjectRegistry(self.conn)
        self.policies = policies_mod.GovernancePolicyRegistry(self.conn)
        self.a = os.path.join(self.td.name, "a"); os.makedirs(self.a)

    def _evaluate(self):
        eval_mod.GovernanceEvaluationEngine(self.conn).evaluate()

    def test_snapshot_points_from_evaluations(self):
        self.registry.register_project("alpha", self.a)
        self.policies.create_policy("p", ["not_stale"])
        self._evaluate()
        self._evaluate()
        snap = self.trends.GovernanceTrendTracker(self.conn).build_snapshot()
        self.assertEqual(snap.summary["evaluations"], 2)
        self.assertEqual(len(snap.points), 2)

    def test_empty_snapshot_ok(self):
        snap = self.trends.GovernanceTrendTracker(self.conn).build_snapshot()
        self.assertEqual(snap.summary["evaluations"], 0)
        self.assertEqual(snap.points, [])

    def test_counts_only_no_contents(self):
        self.registry.register_project("alpha", self.a)
        self.policies.create_policy("p", ["not_stale"])
        self._evaluate()
        snap = self.trends.GovernanceTrendTracker(self.conn).build_snapshot()
        for pt in snap.points:
            self.assertIn("failed", pt)
            self.assertIn("overall_status", pt)

    def test_persistence_and_report_path_safety(self):
        self.registry.register_project("alpha", self.a)
        self.policies.create_policy("p", ["not_stale"])
        self._evaluate()
        tracker = self.trends.GovernanceTrendTracker(self.conn)
        old = self.trends.REPORTS_DIR
        self.trends.REPORTS_DIR = os.path.join(self.td.name, "reports")
        self.addCleanup(setattr, self.trends, "REPORTS_DIR", old)
        snap = tracker.build_snapshot()
        sid = tracker.save_snapshot(snap)
        md = tracker.save_markdown_report(sid)
        self.assertTrue(self.trends.is_report_path(md.report_path))
        self.assertTrue(os.path.realpath(md.report_path).startswith(
            os.path.realpath(self.trends.REPORTS_DIR) + os.sep))
        self.assertEqual(
            database.list_governance_trend_snapshots(self.conn)[0]["id"], sid)

    def test_no_side_effect_tables(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        self.registry.register_project("alpha", self.a)
        self.policies.create_policy("p", ["not_stale"])
        self._evaluate()
        tracker = self.trends.GovernanceTrendTracker(self.conn)
        tracker.save_snapshot(tracker.build_snapshot())
        self.assertEqual({t: _count(self.conn, t) for t in before}, before)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        _run_cli(["--register-project", "alpha", "--root", self.a], cwd, env)
        _run_cli(["--create-governance-policy", "--default"], cwd, env)
        _run_cli(["--evaluate-governance-policies"], cwd, env)

        tr = _run_cli(["--governance-trends"], cwd, env)
        self.assertEqual(tr.returncode, 0, tr.stderr)
        self.assertIn("GOVERNANCE TRENDS", tr.stdout)

        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        self.assertEqual(len(database.list_governance_trend_snapshots(conn)), 1)

        saved = _run_cli(["--governance-trends", "--save-report"], cwd, env)
        self.assertEqual(saved.returncode, 0, saved.stderr)

        lst = _run_cli(["--governance-trend-snapshots"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)

        sid = database.list_governance_trend_snapshots(conn)[0]["id"]
        show = _run_cli(["--governance-trend-snapshot", str(sid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)

        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
