import os
import subprocess
import sys
import tempfile
import unittest

import database


class LoopImprovementSelfAuditTests(unittest.TestCase):
    def test_audit_report_generation_and_section_aggregation(self):
        import loop_improvement_self_audit as self_audit

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "self_audit.db"))
            self.addCleanup(conn.close)

            report = self_audit.LoopImprovementSelfAuditEngine(conn).build_report()

            self.assertIn(report.overall_status,
                          {"PASS", "PASS_WITH_WARNINGS", "FAIL", "BLOCKED"})
            self.assertGreaterEqual(report.total_checks, 35)
            self.assertEqual(
                report.total_checks,
                report.passed_checks + report.warning_checks +
                report.failed_checks + report.blocked_checks,
            )
            section_names = {section.name for section in report.sections}
            self.assertEqual(
                section_names,
                {
                    "application_planning",
                    "patch_proposals",
                    "dry_run_validation",
                    "human_approval",
                    "safe_application",
                    "rollback",
                    "post_apply_verification",
                    "outcome_tracking",
                    "safety_baseline",
                    "stage6_final_readiness",
                },
            )
            for section in report.sections:
                self.assertIn(section.status, {"PASS", "WARN", "FAIL", "BLOCKED"})
                self.assertTrue(section.checks)
                self.assertTrue(section.summary)

    def test_overall_status_logic(self):
        import loop_improvement_self_audit as self_audit

        mk = lambda status: self_audit.SelfImprovementAuditSection(
            name=status, status=status, checks=[], summary=status)

        self.assertEqual(self_audit.aggregate_overall_status([mk("PASS")]), "PASS")
        self.assertEqual(
            self_audit.aggregate_overall_status([mk("PASS"), mk("WARN")]),
            "PASS_WITH_WARNINGS",
        )
        self.assertEqual(
            self_audit.aggregate_overall_status([mk("PASS"), mk("FAIL")]),
            "FAIL",
        )
        self.assertEqual(
            self_audit.aggregate_overall_status([mk("FAIL"), mk("BLOCKED")]),
            "BLOCKED",
        )

    def test_persistence_and_markdown_path_safety(self):
        import loop_improvement_self_audit as self_audit

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "self_audit.db"))
            self.addCleanup(conn.close)
            old_reports_dir = self_audit.REPORTS_DIR
            self_audit.REPORTS_DIR = os.path.join(td, "reports")
            self.addCleanup(setattr, self_audit, "REPORTS_DIR", old_reports_dir)
            engine = self_audit.LoopImprovementSelfAuditEngine(conn)
            report = engine.build_report()

            audit_id = engine.save_audit(report)
            markdown = engine.save_markdown_report(audit_id, report)
            stored = self_audit.report_from_row(
                database.get_self_improvement_audit(conn, audit_id)
            )

            self.assertEqual(stored.total_checks, report.total_checks)
            self.assertEqual(
                database.list_self_improvement_audits(conn, limit=1)[0]["id"],
                audit_id,
            )
            self.assertTrue(self_audit.is_markdown_report_path(markdown.report_path))
            self.assertTrue(os.path.realpath(markdown.report_path).startswith(
                os.path.realpath(self_audit.REPORTS_DIR) + os.sep
            ))
            self.assertEqual(
                database.get_self_improvement_audit_markdown_report(
                    conn, audit_id
                )["report_format"],
                "markdown",
            )

    def test_safety_baseline_counts_do_not_change(self):
        import loop_improvement_self_audit as self_audit

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "self_audit.db"))
            self.addCleanup(conn.close)
            before_counts = {
                table: _count(conn, table)
                for table in ("loops", "external_agent_jobs", "command_results")
            }

            engine = self_audit.LoopImprovementSelfAuditEngine(conn)
            report = engine.build_report()
            audit_id = engine.save_audit(report)

            self.assertGreater(audit_id, 0)
            self.assertEqual(
                {table: _count(conn, table) for table in before_counts},
                before_counts,
            )
            safety = _section(report, "safety_baseline")
            self.assertIn(safety.status, {"PASS", "WARN"})
            self.assertIn("no Ollama dependency", _check_names(safety))

    def test_safe_application_flags_detect_all_mutation_attempts(self):
        import loop_improvement_self_audit as self_audit

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "self_audit.db"))
            self.addCleanup(conn.close)
            _insert_application_attempt_with_flags(
                conn, applies_changes=1, writes_files=1,
                executes_commands=1, commits_changes=0, generates_patch=1)

            report = self_audit.LoopImprovementSelfAuditEngine(conn).build_report()
            safe_application = _section(report, "safe_application")

            self.assertEqual(safe_application.status, "FAIL")
            failing = [
                check for check in safe_application.checks
                if check.name.startswith("application attempts do not apply changes")
            ]
            self.assertEqual(len(failing), 1)
            self.assertEqual(failing[0].status, "FAIL")
            self.assertIn("writes_files", failing[0].evidence)

    def test_final_readiness_calculation(self):
        import loop_improvement_self_audit as self_audit

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "self_audit.db"))
            self.addCleanup(conn.close)
            report = self_audit.LoopImprovementSelfAuditEngine(conn).build_report()

            readiness = report.stage6_final_readiness

            self.assertIn("ready", readiness)
            self.assertIn("blockers", readiness)
            self.assertIn("warnings", readiness)
            self.assertEqual(readiness["recommended_next_stage"], "Stage 6.9")
            self.assertTrue(readiness["required_final_audit_controls"])

    def test_cli_paths_use_temp_database_invalid_ollama(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "self_audit.db")
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

            create = _run_cli(["--self-improvement-audit"], cwd, env)
            self.assertEqual(create.returncode, 0, create.stderr)
            self.assertIn("SELF-IMPROVEMENT AUDIT", create.stdout)
            self.assertIn("No commands executed", create.stdout)

            saved = _run_cli(["--self-improvement-audit", "--save-report"], cwd, env)
            self.assertEqual(saved.returncode, 0, saved.stderr)
            self.assertIn("Markdown report", saved.stdout)

            listing = _run_cli(["--self-improvement-audits"], cwd, env)
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertIn("SELF-IMPROVEMENT AUDITS", listing.stdout)

            show = _run_cli(["--self-improvement-audit-show", "latest"], cwd, env)
            self.assertEqual(show.returncode, 0, show.stderr)
            self.assertIn("STAGE 6 FINAL READINESS", show.stdout)

            self.assertGreaterEqual(
                len(database.list_self_improvement_audits(conn, limit=10)),
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


def _insert_application_attempt_with_flags(conn, **flags):
    values = {
        "applies_changes": 0,
        "writes_files": 0,
        "executes_commands": 0,
        "commits_changes": 0,
        "generates_patch": 0,
    }
    values.update(flags)
    conn.execute(
        "INSERT INTO loop_improvement_patch_application_attempts "
        "(generated_at, approval_id, validation_id, patch_proposal_id, "
        "application_plan_id, status, approval_confirmed, "
        "rollback_snapshot_required, rollback_snapshot_present, "
        "total_target_files, target_files_json, blockers_json, "
        "safety_notes_json, required_next_controls_json, applies_changes, "
        "writes_files, executes_commands, commits_changes, generates_patch) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "2026-06-29T00:00:00", 1, 1, 1, 1, "audit_fixture", 1, 1,
            0, 1, '["README.md"]', "[]", "[]", "[]",
            values["applies_changes"], values["writes_files"],
            values["executes_commands"], values["commits_changes"],
            values["generates_patch"],
        ),
    )
    conn.commit()


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
