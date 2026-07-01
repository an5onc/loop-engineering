import os
import subprocess
import sys
import tempfile
import unittest

import database


EXPECTED_SECTIONS = {
    "modules", "tables", "commands", "report_paths", "safety_baseline",
    "stage9_readiness",
}


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _run_cli(args, cwd, env):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


class MultiProjectStage8AuditTests(unittest.TestCase):
    def setUp(self):
        import multi_project_stage8_audit as audit
        self.audit = audit
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "s8.db"))
        self.addCleanup(self.conn.close)

    def test_sections_and_pass(self):
        report = self.audit.MultiProjectStage8AuditEngine(self.conn).build_report()
        self.assertEqual({s.name for s in report.sections}, EXPECTED_SECTIONS)
        self.assertIn(report.overall_status, {"PASS", "PASS_WITH_WARNINGS"})
        for name in ("modules", "tables", "commands", "report_paths"):
            section = next(s for s in report.sections if s.name == name)
            self.assertEqual(section.status, "PASS", f"{name} not PASS")

    def test_safety_named_checks(self):
        report = self.audit.MultiProjectStage8AuditEngine(self.conn).build_report()
        safety = next(s for s in report.sections if s.name == "safety_baseline")
        names = {c.name for c in safety.checks}
        for required in (
            "no hidden command execution",
            "no Ollama dependency",
            "no cross-project writes",
            "no loop rows created",
            "no command_results rows created",
            "no external_agent_jobs rows created",
            "no protected content reads",
            "waivers fail closed",
        ):
            self.assertIn(required, names)

    def test_stage9_readiness(self):
        report = self.audit.MultiProjectStage8AuditEngine(self.conn).build_report()
        readiness = report.stage9_readiness
        self.assertIn("ready", readiness)
        self.assertIsInstance(readiness["ready"], bool)
        self.assertIn("cross-project execution planning",
                      readiness.get("recommended_stage_9_theme", ""))

    def test_persistence_and_markdown_safety(self):
        engine = self.audit.MultiProjectStage8AuditEngine(self.conn)
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
            database.get_multi_project_stage8_audit(self.conn, audit_id))
        self.assertEqual(stored.total_checks, report.total_checks)
        self.assertEqual(
            database.list_multi_project_stage8_audits(self.conn, limit=1)[0]["id"],
            audit_id)

    def test_safety_counts_unchanged(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        engine = self.audit.MultiProjectStage8AuditEngine(self.conn)
        engine.save_audit(engine.build_report())
        self.assertEqual({t: _count(self.conn, t) for t in before}, before)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))

        run = _run_cli(["--multi-project-stage8-audit"], cwd, env)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("STAGE 8 FINAL AUDIT", run.stdout)
        self.assertIn("STAGE 9 READINESS", run.stdout)

        saved = _run_cli(["--multi-project-stage8-audit", "--save-report"],
                         cwd, env)
        self.assertEqual(saved.returncode, 0, saved.stderr)
        self.assertIn("markdown", saved.stdout.lower())

        lst = _run_cli(["--multi-project-stage8-audits"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)

        show = _run_cli(["--multi-project-stage8-audit-show", "latest"], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)

        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        self.assertGreaterEqual(
            len(database.list_multi_project_stage8_audits(conn, limit=10)), 2)
        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
