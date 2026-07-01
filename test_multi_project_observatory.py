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


class MultiProjectObservatoryTests(unittest.TestCase):
    def setUp(self):
        import multi_project_observatory as obs
        self.obs = obs
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "o.db"))
        self.addCleanup(self.conn.close)
        self.registry = registry_mod.ProjectRegistry(self.conn)
        self.root = os.path.join(self.td.name, "proj_a")
        os.makedirs(self.root)

    def test_snapshot_summary_counts(self):
        b = os.path.join(self.td.name, "b"); os.makedirs(b)
        self.registry.register_project("alpha", self.root)
        self.registry.register_project("beta", b)
        self.registry.set_status("beta", "blocked")
        observatory = self.obs.MultiProjectObservatory(self.conn)
        snapshot = observatory.build_snapshot()
        self.assertEqual(snapshot.summary["total_projects"], 2)
        self.assertEqual(snapshot.summary["active"], 1)
        self.assertEqual(snapshot.summary["blocked"], 1)
        self.assertEqual(len(snapshot.projects), 2)
        for project in snapshot.projects:
            self.assertIn("loop_count", project)
            self.assertIn("external_job_count", project)
            self.assertIn("latest_validation_status", project)

    def test_stale_project_needs_attention(self):
        import shutil
        self.registry.register_project("alpha", self.root)
        shutil.rmtree(self.root)
        observatory = self.obs.MultiProjectObservatory(self.conn)
        snapshot = observatory.build_snapshot()
        alpha = snapshot.projects[0]
        self.assertTrue(alpha["stale"])
        self.assertTrue(alpha["needs_attention"])
        self.assertGreaterEqual(snapshot.summary["stale_count"], 1)

    def test_loop_count_metadata(self):
        self.registry.register_project("alpha", self.root)
        database.insert_loop(self.conn, "t", "m", "m", "m",
                             workspace_root=self.root)
        observatory = self.obs.MultiProjectObservatory(self.conn)
        snapshot = observatory.build_snapshot()
        self.assertEqual(snapshot.projects[0]["loop_count"], 1)

    def test_persistence_and_report_path_safety(self):
        self.registry.register_project("alpha", self.root)
        observatory = self.obs.MultiProjectObservatory(self.conn)
        old_dir = self.obs.REPORTS_DIR
        self.obs.REPORTS_DIR = os.path.join(self.td.name, "reports")
        self.addCleanup(setattr, self.obs, "REPORTS_DIR", old_dir)
        snapshot = observatory.build_snapshot()
        snapshot_id = observatory.save_snapshot(snapshot)
        self.assertGreater(snapshot_id, 0)
        report = observatory.save_report(snapshot_id)
        self.assertTrue(self.obs.is_report_path(report.report_path))
        self.assertTrue(os.path.realpath(report.report_path).startswith(
            os.path.realpath(self.obs.REPORTS_DIR) + os.sep))
        self.assertEqual(
            database.list_multi_project_observatory_snapshots(self.conn)[0]["id"],
            snapshot_id)
        self.assertIsNotNone(
            database.get_multi_project_observatory_report(self.conn, snapshot_id))

    def test_no_side_effect_tables(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        self.registry.register_project("alpha", self.root)
        observatory = self.obs.MultiProjectObservatory(self.conn)
        snap = observatory.build_snapshot()
        observatory.save_snapshot(snap)
        self.assertEqual({t: _count(self.conn, t) for t in before}, before)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        _run_cli(["--register-project", "alpha", "--root", self.root], cwd, env)

        dash = _run_cli(["--multi-project-observatory"], cwd, env)
        self.assertEqual(dash.returncode, 0, dash.stderr)
        self.assertIn("MULTI-PROJECT OBSERVATORY", dash.stdout)

        saved = _run_cli(["--multi-project-observatory", "--save-report"], cwd, env)
        self.assertEqual(saved.returncode, 0, saved.stderr)

        snaps = _run_cli(["--multi-project-snapshots"], cwd, env)
        self.assertEqual(snaps.returncode, 0, snaps.stderr)

        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        sid = database.list_multi_project_observatory_snapshots(conn)[0]["id"]
        show = _run_cli(["--multi-project-snapshot", str(sid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
