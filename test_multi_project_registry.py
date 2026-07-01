import os
import subprocess
import sys
import tempfile
import unittest

import database


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _run_cli(args, cwd, env):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


class MultiProjectRegistryTests(unittest.TestCase):
    def setUp(self):
        import multi_project_registry as reg
        self.reg = reg
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "reg.db"))
        self.addCleanup(self.conn.close)
        self.root = os.path.join(self.td.name, "proj_a")
        os.makedirs(self.root)

    def test_register_and_get(self):
        registry = self.reg.ProjectRegistry(self.conn)
        project = registry.register_project(
            "alpha", self.root, name="Alpha", repo_url="https://x/y.git",
            default_branch="main", labels=["svc"], notes="n")
        self.assertEqual(project.project_key, "alpha")
        self.assertEqual(project.status, "active")
        self.assertTrue(os.path.isabs(project.root_path))
        fetched = registry.get_project("alpha")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.repo_url, "https://x/y.git")
        self.assertEqual(fetched.labels, ["svc"])

    def test_duplicate_key_rejected(self):
        registry = self.reg.ProjectRegistry(self.conn)
        registry.register_project("alpha", self.root)
        with self.assertRaises(ValueError):
            registry.register_project("alpha", self.root)
        self.assertEqual(_count(self.conn, "registered_projects"), 1)

    def test_missing_root_rejected(self):
        registry = self.reg.ProjectRegistry(self.conn)
        with self.assertRaises(ValueError):
            registry.register_project("ghost", os.path.join(self.td.name, "nope"))
        self.assertEqual(_count(self.conn, "registered_projects"), 0)

    def test_invalid_key_rejected(self):
        registry = self.reg.ProjectRegistry(self.conn)
        with self.assertRaises(ValueError):
            registry.register_project("bad key!", self.root)

    def test_invalid_status_rejected(self):
        registry = self.reg.ProjectRegistry(self.conn)
        registry.register_project("alpha", self.root)
        with self.assertRaises(ValueError):
            registry.set_status("alpha", "deleted")

    def test_set_status(self):
        registry = self.reg.ProjectRegistry(self.conn)
        registry.register_project("alpha", self.root)
        updated = registry.set_status("alpha", "paused")
        self.assertEqual(updated.status, "paused")
        self.assertEqual(registry.get_project("alpha").status, "paused")

    def test_summary_counts(self):
        registry = self.reg.ProjectRegistry(self.conn)
        b = os.path.join(self.td.name, "b"); os.makedirs(b)
        c = os.path.join(self.td.name, "c"); os.makedirs(c)
        registry.register_project("alpha", self.root)
        registry.register_project("beta", b)
        registry.register_project("gamma", c)
        registry.set_status("beta", "paused")
        registry.set_status("gamma", "blocked")
        summary = registry.summary()
        self.assertEqual(summary.total, 3)
        self.assertEqual(summary.active, 1)
        self.assertEqual(summary.paused, 1)
        self.assertEqual(summary.blocked, 1)
        self.assertEqual(summary.archived, 0)

    def test_no_side_effect_tables(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        registry = self.reg.ProjectRegistry(self.conn)
        registry.register_project("alpha", self.root)
        registry.set_status("alpha", "paused")
        registry.summary()
        self.assertEqual(
            {t: _count(self.conn, t) for t in before}, before)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))

        empty = _run_cli(["--projects"], cwd, env)
        self.assertEqual(empty.returncode, 0, empty.stderr)

        reg = _run_cli(
            ["--register-project", "alpha", "--root", self.root,
             "--repo", "https://x/y.git", "--branch", "main"], cwd, env)
        self.assertEqual(reg.returncode, 0, reg.stderr)

        listed = _run_cli(["--projects"], cwd, env)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("alpha", listed.stdout)

        show = _run_cli(["--project", "alpha"], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertIn("alpha", show.stdout)

        status = _run_cli(
            ["--set-project-status", "alpha", "paused"], cwd, env)
        self.assertEqual(status.returncode, 0, status.stderr)

        summary = _run_cli(["--project-registry-summary"], cwd, env)
        self.assertEqual(summary.returncode, 0, summary.stderr)
        self.assertIn("paused", summary.stdout)

        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        self.assertEqual(_count(conn, "registered_projects"), 1)
        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)

    def test_cli_duplicate_and_missing_root_fail_closed(self):
        db_path = os.path.join(self.td.name, "cli2.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        ok = _run_cli(["--register-project", "alpha", "--root", self.root], cwd, env)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        dup = _run_cli(["--register-project", "alpha", "--root", self.root], cwd, env)
        self.assertEqual(dup.returncode, 1)
        missing = _run_cli(
            ["--register-project", "beta", "--root",
             os.path.join(self.td.name, "nope")], cwd, env)
        self.assertEqual(missing.returncode, 1)


if __name__ == "__main__":
    unittest.main()
