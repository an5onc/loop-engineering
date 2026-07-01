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


def _git_head(root, branch="main"):
    gitdir = os.path.join(root, ".git")
    os.makedirs(gitdir, exist_ok=True)
    with open(os.path.join(gitdir, "HEAD"), "w") as fh:
        fh.write(f"ref: refs/heads/{branch}\n")


class MultiProjectValidationTests(unittest.TestCase):
    def setUp(self):
        import multi_project_validation as validation
        self.validation = validation
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "v.db"))
        self.addCleanup(self.conn.close)
        self.registry = registry_mod.ProjectRegistry(self.conn)
        self.root = os.path.join(self.td.name, "proj_a")
        os.makedirs(self.root)
        _git_head(self.root, "main")

    def test_validate_healthy_project(self):
        self.registry.register_project(
            "alpha", self.root, repo_url="https://x/y.git", default_branch="main")
        validator = self.validation.ProjectValidator(self.conn)
        report = validator.validate_project("alpha")
        self.assertIn(report.overall_status,
                      {"PASS", "PASS_WITH_WARNINGS"})
        self.assertTrue(report.root_exists)
        self.assertTrue(report.checks)
        self.assertEqual(report.branch_metadata, "main")

    def test_missing_root_warns_not_crash(self):
        self.registry.register_project("alpha", self.root)
        # Remove the root after registration -> stale.
        import shutil
        shutil.rmtree(self.root)
        validator = self.validation.ProjectValidator(self.conn)
        report = validator.validate_project("alpha")
        self.assertFalse(report.root_exists)
        self.assertIn(report.overall_status, {"PASS_WITH_WARNINGS", "WARN", "FAIL"})
        names = {c.name for c in report.checks}
        self.assertIn("root exists", names)

    def test_overlapping_roots_flagged(self):
        sub = os.path.join(self.root, "inner")
        os.makedirs(sub)
        self.registry.register_project("alpha", self.root)
        self.registry.register_project("beta", sub)
        validator = self.validation.ProjectValidator(self.conn)
        report = validator.validate_project("beta")
        overlap = [c for c in report.checks if "overlap" in c.name]
        self.assertTrue(overlap)
        self.assertIn(overlap[0].status, {"FAIL", "BLOCKED"})
        self.assertIn(report.overall_status, {"FAIL", "BLOCKED"})

    def test_allowed_write_paths_outside_root_fail(self):
        outside = os.path.join(self.td.name, "elsewhere")
        os.makedirs(outside)
        self.registry.register_project(
            "alpha", self.root, allowed_write_paths=[outside])
        validator = self.validation.ProjectValidator(self.conn)
        report = validator.validate_project("alpha")
        bad = [c for c in report.checks if "allowed_write_paths" in c.name]
        self.assertTrue(bad)
        self.assertEqual(bad[0].status, "FAIL")

    def test_unknown_project_fails_closed(self):
        validator = self.validation.ProjectValidator(self.conn)
        with self.assertRaises(ValueError):
            validator.validate_project("ghost")

    def test_persistence_and_listing(self):
        self.registry.register_project("alpha", self.root)
        validator = self.validation.ProjectValidator(self.conn)
        report = validator.validate_project("alpha")
        self.assertGreater(report.id, 0)
        stored = database.get_project_validation_report(self.conn, report.id)
        self.assertEqual(stored["project_key"], "alpha")
        reports = database.list_project_validation_reports(self.conn)
        self.assertEqual(reports[0]["id"], report.id)

    def test_validate_all(self):
        b = os.path.join(self.td.name, "b"); os.makedirs(b)
        self.registry.register_project("alpha", self.root)
        self.registry.register_project("beta", b)
        validator = self.validation.ProjectValidator(self.conn)
        reports = validator.validate_all()
        self.assertEqual(len(reports), 2)

    def test_no_side_effect_tables(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        self.registry.register_project("alpha", self.root)
        validator = self.validation.ProjectValidator(self.conn)
        validator.validate_project("alpha")
        self.assertEqual({t: _count(self.conn, t) for t in before}, before)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        _run_cli(["--register-project", "alpha", "--root", self.root], cwd, env)

        one = _run_cli(["--validate-project", "alpha"], cwd, env)
        self.assertEqual(one.returncode, 0, one.stderr)
        self.assertIn("alpha", one.stdout)

        allv = _run_cli(["--validate-projects"], cwd, env)
        self.assertEqual(allv.returncode, 0, allv.stderr)

        reports = _run_cli(["--project-validation-reports"], cwd, env)
        self.assertEqual(reports.returncode, 0, reports.stderr)

        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        rid = database.list_project_validation_reports(conn)[0]["id"]
        show = _run_cli(["--project-validation-report", str(rid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
