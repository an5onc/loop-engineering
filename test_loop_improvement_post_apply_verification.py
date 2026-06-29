import os
import subprocess
import sys
import tempfile
import unittest

import database
from test_loop_improvement_patch_application import _seed_approved_approval


class LoopImprovementPostApplyVerificationTests(unittest.TestCase):
    def test_plan_from_application_attempt_infers_required_manual_commands(self):
        import loop_improvement_patch_application as application
        import loop_improvement_post_apply_verification as verification

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "post_apply.db"))
            self.addCleanup(conn.close)
            approval_id = _seed_approved_approval(conn)
            app_engine = application.LoopImprovementPatchApplicationEngine(conn)
            attempt = app_engine.create_application_attempt(approval_id)
            attempt_id = app_engine.save_application_attempt(attempt)

            engine = verification.PostApplyVerificationEngine(conn)
            plan = engine.create_plan(attempt_id)
            plan_id = engine.save_plan(plan)
            stored = verification.plan_from_row(
                database.get_post_apply_verification_plan(conn, plan_id)
            )

            command_text = "\n".join(
                item["command"] for item in stored.verification_commands
                if item.get("command")
            )
            self.assertEqual(stored.application_attempt_id, attempt_id)
            self.assertEqual(stored.patch_proposal_id, attempt.patch_proposal_id)
            self.assertEqual(stored.approval_id, attempt.approval_id)
            self.assertEqual(stored.status, "planned")
            self.assertIn("python3 -m py_compile *.py", command_text)
            self.assertIn("python3 audit_hotfix.py", command_text)
            self.assertIn("python3 agent_handoff.py --check", command_text)
            self.assertIn("python3 -m unittest discover", command_text)
            self.assertTrue(
                all(item.get("execution") == "manual" for item in stored.verification_commands)
            )
            self.assertTrue(stored.required_checks > 0)
            self.assertTrue(stored.checks)
            self.assertEqual({check.status for check in stored.checks}, {"pending"})
            self.assertIn("does not execute commands", " ".join(stored.warnings).lower())

    def test_focused_test_inference_for_stage6_targets(self):
        import loop_improvement_post_apply_verification as verification

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "post_apply.db"))
            self.addCleanup(conn.close)
            attempt_id = _save_application_attempt_with_targets(
                conn,
                [
                    "loop_improvement_patch_application.py",
                    "database.py",
                    "main.py",
                    "README.md",
                ],
            )

            plan = verification.PostApplyVerificationEngine(conn).create_plan(attempt_id)
            command_text = "\n".join(
                item["command"] for item in plan.verification_commands
                if item.get("command")
            )
            notes = "\n".join(check.notes for check in plan.checks)

            self.assertIn(
                "python3 -m unittest test_loop_improvement_patch_application.py",
                command_text,
            )
            self.assertIn("test_loop_improvement_patch_dry_run.py", command_text)
            self.assertIn("test_loop_improvement_patch_approval.py", command_text)
            self.assertIn("python3 -m unittest discover", command_text)
            self.assertIn("README.md", notes)

    def test_status_update_report_and_markdown_path_safety(self):
        import loop_improvement_post_apply_verification as verification

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "post_apply.db"))
            self.addCleanup(conn.close)
            old_reports_dir = verification.REPORTS_DIR
            verification.REPORTS_DIR = os.path.join(td, "reports")
            self.addCleanup(setattr, verification, "REPORTS_DIR", old_reports_dir)
            attempt_id = _save_application_attempt_with_targets(
                conn, ["loop_improvement_patch_application.py"]
            )
            engine = verification.PostApplyVerificationEngine(conn)
            plan_id = engine.save_plan(engine.create_plan(attempt_id))

            updated = database.update_post_apply_verification_status(
                conn, plan_id, "manually_verified"
            )
            report = engine.create_report(plan_id)
            report_id = engine.save_report(report)
            markdown = engine.save_markdown_report(report_id, report)

            self.assertEqual(updated["status"], "manually_verified")
            self.assertIn(report.overall_status, {"PASS", "PASS_WITH_WARNINGS"})
            self.assertEqual(
                database.get_latest_post_apply_verification_report_for_plan(
                    conn, plan_id
                )["id"],
                report_id,
            )
            self.assertTrue(verification.is_markdown_report_path(markdown.report_path))
            self.assertTrue(os.path.realpath(markdown.report_path).startswith(
                os.path.realpath(verification.REPORTS_DIR) + os.sep
            ))
            self.assertEqual(
                database.get_post_apply_verification_markdown_report(
                    conn, report_id
                )["report_format"],
                "markdown",
            )

    def test_verification_metadata_does_not_mutate_runtime_or_execute_commands(self):
        import loop_improvement_post_apply_verification as verification

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "post_apply.db"))
            self.addCleanup(conn.close)
            attempt_id = _save_application_attempt_with_targets(
                conn, ["loop_improvement_patch_application.py"]
            )
            before_counts = {
                table: _count(conn, table)
                for table in ("loops", "external_agent_jobs", "command_results")
            }

            engine = verification.PostApplyVerificationEngine(conn)
            plan_id = engine.save_plan(engine.create_plan(attempt_id))
            database.update_post_apply_verification_status(conn, plan_id, "blocked")
            report_id = engine.save_report(engine.create_report(plan_id))

            self.assertGreater(plan_id, 0)
            self.assertGreater(report_id, 0)
            self.assertEqual(
                {table: _count(conn, table) for table in before_counts},
                before_counts,
            )

    def test_cli_plan_report_status_use_temp_database_invalid_ollama(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "post_apply.db")
            conn = database.init_db(db_path)
            self.addCleanup(conn.close)
            _save_application_attempt_with_targets(
                conn, ["loop_improvement_patch_application.py"]
            )
            env = dict(os.environ)
            env["LOOP_DB_FILE"] = db_path
            env["OLLAMA_HOST"] = "http://127.0.0.1:9"
            cwd = os.path.dirname(os.path.abspath(__file__))

            create = _run_cli(
                ["--create-post-apply-verification-plan", "latest"], cwd, env
            )
            self.assertEqual(create.returncode, 0, create.stderr)
            self.assertIn("POST-APPLY VERIFICATION PLAN", create.stdout)
            self.assertIn("Executes commands   : False", create.stdout)

            listing = _run_cli(["--post-apply-verification-plans"], cwd, env)
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertIn("status=planned", listing.stdout)

            show = _run_cli(["--post-apply-verification-plan", "latest"], cwd, env)
            self.assertEqual(show.returncode, 0, show.stderr)
            self.assertIn("POST-APPLY VERIFICATION PLAN", show.stdout)
            self.assertIn("VERIFICATION COMMANDS (MANUAL ONLY)", show.stdout)

            report = _run_cli(["--post-apply-verification-report", "latest"], cwd, env)
            self.assertEqual(report.returncode, 0, report.stderr)
            self.assertIn("POST-APPLY VERIFICATION REPORT", report.stdout)
            self.assertIn("Overall status      : PENDING", report.stdout)

            report_saved = _run_cli(
                ["--post-apply-verification-report", "latest", "--save-report"],
                cwd,
                env,
            )
            self.assertEqual(report_saved.returncode, 0, report_saved.stderr)
            self.assertIn("Markdown report", report_saved.stdout)

            plan_id = database.list_post_apply_verification_plans(conn, limit=1)[0]["id"]
            status = _run_cli(
                ["--set-post-apply-verification-status", str(plan_id), "deferred"],
                cwd,
                env,
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("status -> deferred", status.stdout)
            self.assertEqual(_count(conn, "command_results"), 0)
            self.assertEqual(_count(conn, "loops"), 0)
            self.assertEqual(_count(conn, "external_agent_jobs"), 0)


def _save_application_attempt_with_targets(conn, target_files):
    return database.save_loop_improvement_patch_application_attempt(
        conn,
        "2026-06-29T00:00:00",
        1,
        1,
        1,
        1,
        "applied",
        True,
        True,
        True,
        len(target_files),
        _json_list(target_files),
        _json_list([]),
        _json_list(["seeded test attempt"]),
        _json_list(["manual post-apply verification"]),
        False,
        False,
        False,
        False,
        False,
    )


def _json_list(items):
    import json

    return json.dumps(items, sort_keys=True)


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
