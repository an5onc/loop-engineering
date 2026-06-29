import os
import subprocess
import sys
import tempfile
import unittest

import database
import loop_improvement_patch_approval
from test_loop_improvement_patch_approval import _seed_passing_validation


class LoopImprovementPatchApplicationTests(unittest.TestCase):
    def test_application_attempt_from_approved_request_blocks_until_rollback_snapshot(self):
        import loop_improvement_patch_application as application

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "patch_application.db"))
            self.addCleanup(conn.close)
            approval_id = _seed_approved_approval(conn)

            attempt = application.LoopImprovementPatchApplicationEngine(
                conn).create_application_attempt(approval_id)

            self.assertEqual(attempt.approval_id, approval_id)
            self.assertEqual(attempt.status, "blocked_rollback_required")
            self.assertTrue(attempt.approval_confirmed)
            self.assertTrue(attempt.rollback_snapshot_required)
            self.assertFalse(attempt.rollback_snapshot_present)
            self.assertFalse(attempt.applies_changes)
            self.assertFalse(attempt.writes_files)
            self.assertFalse(attempt.executes_commands)
            self.assertFalse(attempt.commits_changes)
            self.assertFalse(attempt.generates_patch)
            self.assertEqual(attempt.total_target_files, 2)
            self.assertIn("stop_conditions.py", attempt.target_files)
            self.assertIn("loop_engine.py", attempt.target_files)
            self.assertIn("rollback snapshot required",
                          " ".join(attempt.blockers).lower())
            self.assertIn("fail closed", " ".join(attempt.safety_notes).lower())

    def test_application_attempt_requires_approved_request(self):
        import loop_improvement_patch_application as application

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "patch_application.db"))
            self.addCleanup(conn.close)
            validation_id = _seed_passing_validation(conn)
            engine = loop_improvement_patch_approval.LoopImprovementPatchApprovalEngine(
                conn)
            request = engine.create_approval_request(validation_id)
            approval_id = engine.save_approval_request(request)

            with self.assertRaisesRegex(ValueError, "not approved"):
                application.LoopImprovementPatchApplicationEngine(
                    conn).create_application_attempt(approval_id)

    def test_persistence_and_report_path_safety(self):
        import loop_improvement_patch_application as application

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "patch_application.db"))
            self.addCleanup(conn.close)
            old_reports_dir = application.REPORTS_DIR
            application.REPORTS_DIR = os.path.join(td, "reports")
            self.addCleanup(setattr, application, "REPORTS_DIR", old_reports_dir)
            approval_id = _seed_approved_approval(conn)
            engine = application.LoopImprovementPatchApplicationEngine(conn)

            attempt = engine.create_application_attempt(approval_id)
            attempt_id = engine.save_application_attempt(attempt)
            markdown = engine.save_markdown_report(attempt_id, attempt)
            stored = database.get_loop_improvement_patch_application_attempt(
                conn, attempt_id)
            stored_attempt = application.application_attempt_from_row(stored)
            rows = database.list_loop_improvement_patch_application_attempts(conn, 5)
            events = database.get_loop_improvement_patch_application_attempt_events(
                conn, attempt_id)

            self.assertEqual(stored["id"], attempt_id)
            self.assertEqual(stored_attempt.status, "blocked_rollback_required")
            self.assertEqual(rows[0]["id"], attempt_id)
            self.assertEqual(len(events), 1)
            self.assertTrue(application.is_markdown_report_path(markdown.report_path))
            self.assertTrue(os.path.realpath(markdown.report_path).startswith(
                os.path.realpath(application.REPORTS_DIR) + os.sep))
            self.assertEqual(
                database.get_loop_improvement_patch_application_markdown_report(
                    conn, attempt_id)["report_format"],
                "markdown",
            )

    def test_application_attempt_does_not_mutate_runtime_or_approval_records(self):
        import loop_improvement_patch_application as application

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "patch_application.db"))
            self.addCleanup(conn.close)
            approval_id = _seed_approved_approval(conn)
            before_counts = {
                table: _count(conn, table)
                for table in (
                    "loops",
                    "external_agent_jobs",
                    "command_results",
                    "loop_improvement_patch_approvals",
                    "loop_improvement_patch_dry_run_validations",
                    "loop_improvement_patch_proposals",
                )
            }
            before_approval = database.get_loop_improvement_patch_approval(
                conn, approval_id)

            attempt = application.LoopImprovementPatchApplicationEngine(
                conn).create_application_attempt(approval_id)
            application.LoopImprovementPatchApplicationEngine(
                conn).save_application_attempt(attempt)

            after_counts = {table: _count(conn, table) for table in before_counts}
            self.assertEqual(after_counts, before_counts)
            after_approval = database.get_loop_improvement_patch_approval(
                conn, approval_id)
            self.assertEqual(after_approval["status"], before_approval["status"])
            self.assertEqual(after_approval["decision_notes"],
                             before_approval["decision_notes"])

    def test_cli_attempt_list_and_show_use_temp_database(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "patch_application.db")
            conn = database.init_db(db_path)
            self.addCleanup(conn.close)
            _seed_approved_approval(conn)
            env = dict(os.environ)
            env["LOOP_DB_FILE"] = db_path
            env["OLLAMA_HOST"] = "http://127.0.0.1:9"

            create = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--attempt-loop-improvement-patch-application",
                    "latest",
                ],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(create.returncode, 0, create.stderr)
            self.assertIn("LOOP IMPROVEMENT PATCH APPLICATION ATTEMPT", create.stdout)
            self.assertIn("Status              : blocked_rollback_required", create.stdout)
            self.assertIn("Applies changes     : False", create.stdout)

            listing = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--loop-improvement-patch-application-attempts",
                ],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertIn("status=blocked_rollback_required", listing.stdout)
            self.assertIn("applies_changes=False", listing.stdout)

            show = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--loop-improvement-patch-application-attempt",
                    "latest",
                ],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(show.returncode, 0, show.stderr)
            self.assertIn("BLOCKERS", show.stdout)
            self.assertIn("No file writes occur before rollback snapshots.", show.stdout)


def _seed_approved_approval(conn):
    validation_id = _seed_passing_validation(conn)
    engine = loop_improvement_patch_approval.LoopImprovementPatchApprovalEngine(conn)
    request = engine.create_approval_request(validation_id)
    approval_id = engine.save_approval_request(request)
    engine.update_approval_status(
        approval_id, "approved", operator="human", notes="approved for guarded apply")
    return approval_id


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


if __name__ == "__main__":
    unittest.main()
