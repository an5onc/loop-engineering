import os
import subprocess
import sys
import tempfile
import unittest

import database
import multi_project_registry as registry_mod
import cross_project_planner as planner_mod
import cross_project_approvals as approvals_mod


EXPECTED_SECTIONS = {
    "registry", "validation", "observatory", "planning", "approvals",
    "handoffs", "schedules", "safety_baseline", "stage8_readiness",
}


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _run_cli(args, cwd, env):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


class MultiProjectAuditTests(unittest.TestCase):
    def setUp(self):
        import multi_project_audit as audit
        self.audit = audit
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "a.db"))
        self.addCleanup(self.conn.close)
        self.registry = registry_mod.ProjectRegistry(self.conn)
        self.a = os.path.join(self.td.name, "a"); os.makedirs(self.a)
        self.registry.register_project("alpha", self.a)

    def test_report_sections(self):
        report = self.audit.MultiProjectAuditEngine(self.conn).build_report()
        self.assertIn(report.overall_status,
                      {"PASS", "PASS_WITH_WARNINGS", "FAIL", "BLOCKED"})
        self.assertEqual({s.name for s in report.sections}, EXPECTED_SECTIONS)
        for section in report.sections:
            self.assertIn(section.status, {"PASS", "WARN", "FAIL", "BLOCKED"})
            self.assertTrue(section.checks)
            self.assertTrue(section.summary)

    def test_aggregate_status(self):
        mk = lambda s: self.audit.AuditSection(name=s, status=s, checks=[], summary=s)
        self.assertEqual(self.audit.aggregate_overall_status([mk("PASS")]), "PASS")
        self.assertEqual(
            self.audit.aggregate_overall_status([mk("PASS"), mk("WARN")]),
            "PASS_WITH_WARNINGS")
        self.assertEqual(
            self.audit.aggregate_overall_status([mk("PASS"), mk("FAIL")]), "FAIL")
        self.assertEqual(
            self.audit.aggregate_overall_status([mk("FAIL"), mk("BLOCKED")]),
            "BLOCKED")

    def test_stage8_readiness_shape(self):
        report = self.audit.MultiProjectAuditEngine(self.conn).build_report()
        readiness = report.stage8_readiness
        self.assertIn("ready", readiness)
        self.assertIn("blockers", readiness)
        self.assertIn("warnings", readiness)
        self.assertTrue(readiness.get("recommended_stage_8_theme"))

    def test_persistence_and_markdown_safety(self):
        engine = self.audit.MultiProjectAuditEngine(self.conn)
        old_dir = self.audit.REPORTS_DIR
        self.audit.REPORTS_DIR = os.path.join(self.td.name, "reports")
        self.addCleanup(setattr, self.audit, "REPORTS_DIR", old_dir)
        report = engine.build_report()
        audit_id = engine.save_audit(report)
        md = engine.save_markdown_report(audit_id, report)
        self.assertTrue(self.audit.is_markdown_report_path(md.report_path))
        self.assertTrue(os.path.realpath(md.report_path).startswith(
            os.path.realpath(self.audit.REPORTS_DIR) + os.sep))
        stored = self.audit.report_from_row(
            database.get_multi_project_audit(self.conn, audit_id))
        self.assertEqual(stored.total_checks, report.total_checks)

    def test_safety_counts_unchanged(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        engine = self.audit.MultiProjectAuditEngine(self.conn)
        report = engine.build_report()
        engine.save_audit(report)
        self.assertEqual({t: _count(self.conn, t) for t in before}, before)
        safety = next(s for s in report.sections if s.name == "safety_baseline")
        names = {c.name for c in safety.checks}
        self.assertIn("no hidden command execution", names)

    def test_handoff_with_rejected_approval_flagged(self):
        plan = planner_mod.CrossProjectPlanner(self.conn).plan_work("work")
        gate = approvals_mod.CrossProjectApprovalGate(self.conn)
        approval = gate.request_approval(plan.id)
        gate.set_status(approval.id, "approved")
        import cross_project_handoff as handoff_mod
        old = handoff_mod.PACKETS_DIR
        handoff_mod.PACKETS_DIR = os.path.join(self.td.name, "packets")
        self.addCleanup(setattr, handoff_mod, "PACKETS_DIR", old)
        handoff_mod.CrossProjectHandoffBuilder(self.conn).create_handoff(
            plan.id, approval.id)
        # Now revoke the approval after the fact.
        gate.set_status(approval.id, "rejected")
        report = self.audit.MultiProjectAuditEngine(self.conn).build_report()
        handoffs = next(s for s in report.sections if s.name == "handoffs")
        self.assertEqual(handoffs.status, "FAIL")

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        _run_cli(["--register-project", "alpha", "--root", self.a], cwd, env)

        run = _run_cli(["--multi-project-audit"], cwd, env)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("MULTI-PROJECT AUDIT", run.stdout)

        saved = _run_cli(["--multi-project-audit", "--save-report"], cwd, env)
        self.assertEqual(saved.returncode, 0, saved.stderr)

        lst = _run_cli(["--multi-project-audits"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)

        show = _run_cli(["--multi-project-audit-show", "latest"], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)

        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
