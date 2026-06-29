import os
import subprocess
import sys
import tempfile
import unittest

import database
from test_loop_improvement_patch_application import _seed_approved_approval


class LoopImprovementOutcomeTests(unittest.TestCase):
    def test_missing_verification_produces_inconclusive_outcome(self):
        import loop_improvement_outcomes as outcomes

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "outcomes.db"))
            self.addCleanup(conn.close)
            attempt_id = _seed_application_attempt(conn)

            engine = outcomes.LoopImprovementOutcomeEngine(conn)
            record = engine.create_outcome_record(attempt_id)
            outcome_id = engine.save_outcome_record(record)
            stored = outcomes.outcome_from_row(
                database.get_improvement_outcome_record(conn, outcome_id)
            )

            self.assertEqual(stored.application_attempt_id, attempt_id)
            self.assertEqual(stored.outcome_status, "inconclusive")
            self.assertEqual(stored.verification_status, "missing")
            self.assertGreater(stored.success_score, 0)
            self.assertLess(stored.success_score, 60)
            self.assertIn("verification_plan_found", _signal_types(stored))
            self.assertIn("missing_metadata", _signal_types(stored))
            self.assertIn("manual_follow_up_required", _signal_types(stored))

    def test_verified_pass_produces_successful_with_safety_signals(self):
        import loop_improvement_outcomes as outcomes

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "outcomes.db"))
            self.addCleanup(conn.close)
            attempt_id = _seed_application_attempt(conn)
            _seed_rollback_snapshot(conn, attempt_id)
            plan_id, report_id = _seed_verification(
                conn, attempt_id, plan_status="manually_verified")

            record = outcomes.LoopImprovementOutcomeEngine(
                conn).create_outcome_record(attempt_id)

            self.assertEqual(record.verification_plan_id, plan_id)
            self.assertEqual(record.verification_report_id, report_id)
            self.assertIn(record.outcome_status,
                          {"successful", "successful_with_warnings"})
            self.assertGreaterEqual(record.success_score, 75)
            self.assertEqual(record.verification_status, "PASS_WITH_WARNINGS")
            self.assertEqual(record.rollback_status, "snapshot_available")
            signal_types = _signal_types(record)
            self.assertIn("verification_passed", signal_types)
            self.assertIn("rollback_snapshot_found", signal_types)
            self.assertIn("safety_requirements_satisfied", signal_types)

    def test_failed_and_blocked_verification_map_to_terminal_outcomes(self):
        import loop_improvement_outcomes as outcomes

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "outcomes.db"))
            self.addCleanup(conn.close)
            failed_attempt = _seed_application_attempt(conn)
            _seed_verification(conn, failed_attempt, plan_status="failed")
            blocked_attempt = _seed_application_attempt(conn)
            _seed_verification(conn, blocked_attempt, plan_status="blocked")

            failed = outcomes.LoopImprovementOutcomeEngine(
                conn).create_outcome_record(failed_attempt)
            blocked = outcomes.LoopImprovementOutcomeEngine(
                conn).create_outcome_record(blocked_attempt)

            self.assertEqual(failed.outcome_status, "failed_verification")
            self.assertEqual(failed.verification_status, "FAIL")
            self.assertIn("verification_failed", _signal_types(failed))
            self.assertLess(failed.success_score, 50)
            self.assertEqual(blocked.outcome_status, "blocked")
            self.assertEqual(blocked.verification_status, "BLOCKED")

    def test_rollback_recommended_and_manual_status_update(self):
        import loop_improvement_outcomes as outcomes

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "outcomes.db"))
            self.addCleanup(conn.close)
            attempt_id = _seed_application_attempt(conn, status="blocked_rollback_required")
            engine = outcomes.LoopImprovementOutcomeEngine(conn)
            outcome_id = engine.save_outcome_record(
                engine.create_outcome_record(attempt_id))

            stored = outcomes.outcome_from_row(
                database.get_improvement_outcome_record(conn, outcome_id))
            updated = database.update_improvement_outcome_status(
                conn, outcome_id, "rolled_back")

            self.assertEqual(stored.outcome_status, "rollback_recommended")
            self.assertEqual(stored.rollback_status, "required_missing")
            self.assertIn("rollback_needed", _signal_types(stored))
            self.assertEqual(updated["outcome_status"], "rolled_back")

    def test_report_generation_and_markdown_path_safety(self):
        import loop_improvement_outcomes as outcomes

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "outcomes.db"))
            self.addCleanup(conn.close)
            old_reports_dir = outcomes.REPORTS_DIR
            outcomes.REPORTS_DIR = os.path.join(td, "reports")
            self.addCleanup(setattr, outcomes, "REPORTS_DIR", old_reports_dir)
            attempt_id = _seed_application_attempt(conn)
            _seed_verification(conn, attempt_id, plan_status="manually_verified")
            engine = outcomes.LoopImprovementOutcomeEngine(conn)
            outcome_id = engine.save_outcome_record(
                engine.create_outcome_record(attempt_id))

            report = engine.create_report(outcome_id)
            report_id = engine.save_report(report)
            markdown = engine.save_markdown_report(report_id, report)

            self.assertEqual(report.outcome_id, outcome_id)
            self.assertIn(report.overall_status,
                          {"successful", "successful_with_warnings"})
            self.assertTrue(outcomes.is_markdown_report_path(markdown.report_path))
            self.assertTrue(os.path.realpath(markdown.report_path).startswith(
                os.path.realpath(outcomes.REPORTS_DIR) + os.sep
            ))
            self.assertEqual(
                database.get_improvement_outcome_markdown_report(
                    conn, report_id
                )["report_format"],
                "markdown",
            )

    def test_outcome_tracker_does_not_mutate_runtime_or_execute_commands(self):
        import loop_improvement_outcomes as outcomes

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "outcomes.db"))
            self.addCleanup(conn.close)
            attempt_id = _seed_application_attempt(conn)
            before_counts = {
                table: _count(conn, table)
                for table in ("loops", "external_agent_jobs", "command_results")
            }

            engine = outcomes.LoopImprovementOutcomeEngine(conn)
            outcome_id = engine.save_outcome_record(
                engine.create_outcome_record(attempt_id))
            report_id = engine.save_report(engine.create_report(outcome_id))

            self.assertGreater(outcome_id, 0)
            self.assertGreater(report_id, 0)
            self.assertEqual(
                {table: _count(conn, table) for table in before_counts},
                before_counts,
            )

    def test_cli_outcome_paths_use_temp_database_invalid_ollama(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "outcomes.db")
            conn = database.init_db(db_path)
            self.addCleanup(conn.close)
            attempt_id = _seed_application_attempt(conn)
            _seed_verification(conn, attempt_id, plan_status="manually_verified")
            env = dict(os.environ)
            env["LOOP_DB_FILE"] = db_path
            env["OLLAMA_HOST"] = "http://127.0.0.1:9"
            cwd = os.path.dirname(os.path.abspath(__file__))

            create = _run_cli(["--record-improvement-outcome", "latest"], cwd, env)
            self.assertEqual(create.returncode, 0, create.stderr)
            self.assertIn("IMPROVEMENT OUTCOME RECORD", create.stdout)
            self.assertIn("Executes commands   : False", create.stdout)

            listing = _run_cli(["--improvement-outcomes"], cwd, env)
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertIn("status=successful", listing.stdout)

            show = _run_cli(["--improvement-outcome", "latest"], cwd, env)
            self.assertEqual(show.returncode, 0, show.stderr)
            self.assertIn("SIGNALS", show.stdout)

            report = _run_cli(["--improvement-outcome-report", "latest"], cwd, env)
            self.assertEqual(report.returncode, 0, report.stderr)
            self.assertIn("IMPROVEMENT OUTCOME REPORT", report.stdout)

            saved = _run_cli(
                ["--improvement-outcome-report", "latest", "--save-report"],
                cwd,
                env,
            )
            self.assertEqual(saved.returncode, 0, saved.stderr)
            self.assertIn("Markdown report", saved.stdout)

            status = _run_cli(
                [
                    "--set-improvement-outcome-status",
                    "latest",
                    "successful_with_warnings",
                ],
                cwd,
                env,
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("status -> successful_with_warnings", status.stdout)
            self.assertEqual(_count(conn, "command_results"), 0)
            self.assertEqual(_count(conn, "loops"), 0)
            self.assertEqual(_count(conn, "external_agent_jobs"), 0)


def _seed_application_attempt(conn, status="applied"):
    import loop_improvement_patch_application as application

    approval_id = _seed_approved_approval(conn)
    engine = application.LoopImprovementPatchApplicationEngine(conn)
    attempt = engine.create_application_attempt(approval_id)
    attempt.status = status
    attempt.rollback_snapshot_present = status != "blocked_rollback_required"
    return engine.save_application_attempt(attempt)


def _seed_verification(conn, attempt_id, plan_status):
    import loop_improvement_post_apply_verification as verification

    engine = verification.PostApplyVerificationEngine(conn)
    plan = engine.create_plan(attempt_id)
    plan_id = engine.save_plan(plan)
    database.update_post_apply_verification_status(conn, plan_id, plan_status)
    report_id = engine.save_report(engine.create_report(plan_id))
    return plan_id, report_id


def _seed_rollback_snapshot(conn, attempt_id):
    return database.save_loop_improvement_rollback_snapshot(
        conn,
        "2026-06-29T00:00:00",
        attempt_id,
        1,
        1,
        1,
        "snapshot_created",
        0,
        0,
        0,
        "[]",
        "[]",
        "[]",
        "[]",
        False,
        False,
        False,
        False,
    )


def _signal_types(record):
    return {signal.signal_type for signal in record.signals}


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
