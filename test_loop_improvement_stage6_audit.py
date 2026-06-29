import os
import subprocess
import sys
import tempfile
import unittest

import database


class LoopImprovementStage6AuditTests(unittest.TestCase):
    def test_stage6_audit_report_generation_and_sections(self):
        import loop_improvement_stage6_audit as stage6_audit

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "stage6_audit.db"))
            self.addCleanup(conn.close)

            report = stage6_audit.LoopImprovementStage6AuditEngine(conn).build_report()

            self.assertIn(report.overall_status,
                          {"PASS", "PASS_WITH_WARNINGS", "FAIL", "BLOCKED"})
            self.assertGreaterEqual(report.total_checks, 40)
            self.assertEqual(
                report.total_checks,
                report.passed_checks + report.warning_checks +
                report.failed_checks + report.blocked_checks,
            )
            self.assertEqual(
                {section.name for section in report.sections},
                {
                    "application_planning",
                    "patch_proposal_generation",
                    "dry_run_validation",
                    "human_approval",
                    "safe_application",
                    "rollback_snapshot",
                    "post_apply_verification",
                    "outcome_tracking",
                    "self_improvement_audit",
                    "safety_baseline",
                    "stage7_readiness",
                },
            )
            for section in report.sections:
                self.assertIn(section.status, {"PASS", "WARN", "FAIL", "BLOCKED"})
                self.assertTrue(section.checks)
                self.assertTrue(section.summary)

    def test_overall_status_logic(self):
        import loop_improvement_stage6_audit as stage6_audit

        mk = lambda status: stage6_audit.Stage6AuditSection(
            name=status, status=status, checks=[], summary=status)

        self.assertEqual(stage6_audit.aggregate_overall_status([mk("PASS")]), "PASS")
        self.assertEqual(
            stage6_audit.aggregate_overall_status([mk("PASS"), mk("WARN")]),
            "PASS_WITH_WARNINGS",
        )
        self.assertEqual(
            stage6_audit.aggregate_overall_status([mk("PASS"), mk("FAIL")]),
            "FAIL",
        )
        self.assertEqual(
            stage6_audit.aggregate_overall_status([mk("FAIL"), mk("BLOCKED")]),
            "BLOCKED",
        )

    def test_stage7_readiness_shape(self):
        import loop_improvement_stage6_audit as stage6_audit

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "stage6_audit.db"))
            self.addCleanup(conn.close)
            report = stage6_audit.LoopImprovementStage6AuditEngine(conn).build_report()

            readiness = report.stage7_readiness

            self.assertIn("ready", readiness)
            self.assertIn("blockers", readiness)
            self.assertIn("warnings", readiness)
            self.assertEqual(
                readiness["recommended_stage_7_theme"],
                "Multi-Project Operations",
            )
            self.assertIn("workspace isolation",
                          readiness["required_stage_7_safety_controls"])
            self.assertIn("no hidden model or command execution",
                          readiness["required_stage_7_safety_controls"])

    def test_persistence_and_markdown_path_safety(self):
        import loop_improvement_stage6_audit as stage6_audit

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "stage6_audit.db"))
            self.addCleanup(conn.close)
            old_reports_dir = stage6_audit.REPORTS_DIR
            stage6_audit.REPORTS_DIR = os.path.join(td, "reports")
            self.addCleanup(setattr, stage6_audit, "REPORTS_DIR", old_reports_dir)
            engine = stage6_audit.LoopImprovementStage6AuditEngine(conn)
            report = engine.build_report()

            audit_id = engine.save_audit(report)
            markdown = engine.save_markdown_report(audit_id, report)
            stored = stage6_audit.report_from_row(
                database.get_loop_improvement_stage6_audit(conn, audit_id)
            )

            self.assertEqual(stored.total_checks, report.total_checks)
            self.assertEqual(
                database.list_loop_improvement_stage6_audits(conn, limit=1)[0]["id"],
                audit_id,
            )
            self.assertTrue(stage6_audit.is_markdown_report_path(markdown.report_path))
            self.assertTrue(os.path.realpath(markdown.report_path).startswith(
                os.path.realpath(stage6_audit.REPORTS_DIR) + os.sep
            ))
            self.assertEqual(
                database.get_loop_improvement_stage6_audit_markdown_report(
                    conn, audit_id
                )["report_format"],
                "markdown",
            )

    def test_safety_counts_do_not_change(self):
        import loop_improvement_stage6_audit as stage6_audit

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "stage6_audit.db"))
            self.addCleanup(conn.close)
            before_counts = {
                table: _count(conn, table)
                for table in ("loops", "external_agent_jobs", "command_results")
            }

            engine = stage6_audit.LoopImprovementStage6AuditEngine(conn)
            report = engine.build_report()
            audit_id = engine.save_audit(report)

            self.assertGreater(audit_id, 0)
            self.assertEqual(
                {table: _count(conn, table) for table in before_counts},
                before_counts,
            )
            safety = _section(report, "safety_baseline")
            self.assertIn("no hidden command execution", _check_names(safety))
            self.assertIn("no hidden external-agent execution", _check_names(safety))

    def test_cli_paths_use_temp_database_invalid_ollama(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "stage6_audit.db")
            conn = database.init_db(db_path)
            self.addCleanup(conn.close)
            before_counts = {
                table: _count(conn, table)
                for table in ("loops", "external_agent_jobs", "command_results")
            }
            env = dict(os.environ)
            env["LOOP_DB_FILE"] = db_path
            env["OLLAMA_HOST"] = "http://127.0.0.1:9"
            cwd = os.path.dirname(os.path.abspath(__file__))

            create = _run_cli(["--loop-improvement-stage6-audit"], cwd, env)
            self.assertEqual(create.returncode, 0, create.stderr)
            self.assertIn("STAGE 6 CONTROLLED SELF-IMPROVEMENT AUDIT",
                          create.stdout)
            self.assertIn("No commands executed", create.stdout)

            saved = _run_cli(
                ["--loop-improvement-stage6-audit", "--save-report"], cwd, env)
            self.assertEqual(saved.returncode, 0, saved.stderr)
            self.assertIn("Markdown report", saved.stdout)

            listing = _run_cli(["--loop-improvement-stage6-audits"], cwd, env)
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertIn("STAGE 6 CONTROLLED SELF-IMPROVEMENT AUDITS",
                          listing.stdout)

            show = _run_cli(
                ["--loop-improvement-stage6-audit-show", "latest"], cwd, env)
            self.assertEqual(show.returncode, 0, show.stderr)
            self.assertIn("STAGE 7 READINESS", show.stdout)

            self.assertGreaterEqual(
                len(database.list_loop_improvement_stage6_audits(conn, limit=10)),
                2,
            )
            self.assertEqual(
                {table: _count(conn, table) for table in before_counts},
                before_counts,
            )


def _section(report, name):
    for section in report.sections:
        if section.name == name:
            return section
    raise AssertionError(f"missing section {name}")


def _check_names(section):
    return {check.name for check in section.checks}


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _run_cli(args, cwd, env):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


if __name__ == "__main__":
    unittest.main()
