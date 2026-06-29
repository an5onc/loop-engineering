import os
import subprocess
import sys
import tempfile
import unittest

import database
import loop_improvement_patch_application
from test_loop_improvement_patch_application import _seed_approved_approval


class LoopImprovementRollbackSnapshotTests(unittest.TestCase):
    def test_snapshot_captures_allowed_target_files_without_applying_changes(self):
        import loop_improvement_rollback_snapshot as rollback

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "rollback.db"))
            self.addCleanup(conn.close)
            _write_target_files(td)
            old_root = rollback.PROJECT_ROOT
            rollback.PROJECT_ROOT = td
            self.addCleanup(setattr, rollback, "PROJECT_ROOT", old_root)
            attempt_id = _seed_application_attempt(conn)

            snapshot = rollback.LoopImprovementRollbackSnapshotEngine(
                conn).create_snapshot(attempt_id)

            self.assertEqual(snapshot.application_attempt_id, attempt_id)
            self.assertEqual(snapshot.status, "snapshot_created")
            self.assertEqual(snapshot.total_files, 2)
            self.assertEqual(snapshot.captured_files, 2)
            self.assertFalse(snapshot.applies_changes)
            self.assertFalse(snapshot.restores_files)
            self.assertFalse(snapshot.executes_commands)
            self.assertFalse(snapshot.commits_changes)
            self.assertIn("stop_conditions.py", snapshot.target_files)
            self.assertIn("loop_engine.py", snapshot.target_files)
            self.assertTrue(all(f.content_sha256 for f in snapshot.files))
            self.assertTrue(all(f.content_base64 for f in snapshot.files))
            self.assertIn("allowlisted target files",
                          " ".join(snapshot.safety_notes).lower())
            with open(os.path.join(td, "stop_conditions.py"), encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "original stop\n")

    def test_snapshot_blocks_protected_or_escaping_target_file(self):
        import loop_improvement_rollback_snapshot as rollback

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "rollback.db"))
            self.addCleanup(conn.close)
            old_root = rollback.PROJECT_ROOT
            rollback.PROJECT_ROOT = td
            self.addCleanup(setattr, rollback, "PROJECT_ROOT", old_root)
            attempt = loop_improvement_patch_application.LoopImprovementPatchApplicationAttempt(
                generated_at="2026-06-29T12:00:00",
                approval_id=1,
                validation_id=1,
                patch_proposal_id=1,
                application_plan_id=1,
                status="blocked_rollback_required",
                approval_confirmed=True,
                rollback_snapshot_required=True,
                rollback_snapshot_present=False,
                total_target_files=1,
                target_files=["../.env"],
            )
            attempt_id = loop_improvement_patch_application.LoopImprovementPatchApplicationEngine(
                conn).save_application_attempt(attempt)

            with self.assertRaisesRegex(ValueError, "outside the allowed relative workspace"):
                rollback.LoopImprovementRollbackSnapshotEngine(
                    conn).create_snapshot(attempt_id)

    def test_snapshot_persistence_report_and_restore_preview(self):
        import loop_improvement_rollback_snapshot as rollback

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "rollback.db"))
            self.addCleanup(conn.close)
            _write_target_files(td)
            old_root = rollback.PROJECT_ROOT
            old_reports = rollback.REPORTS_DIR
            rollback.PROJECT_ROOT = td
            rollback.REPORTS_DIR = os.path.join(td, "reports")
            self.addCleanup(setattr, rollback, "PROJECT_ROOT", old_root)
            self.addCleanup(setattr, rollback, "REPORTS_DIR", old_reports)
            attempt_id = _seed_application_attempt(conn)
            engine = rollback.LoopImprovementRollbackSnapshotEngine(conn)

            snapshot = engine.create_snapshot(attempt_id)
            snapshot_id = engine.save_snapshot(snapshot)
            preview = engine.preview_restore(snapshot_id)
            markdown = engine.save_markdown_report(snapshot_id, snapshot)
            stored = database.get_loop_improvement_rollback_snapshot(conn, snapshot_id)
            stored_snapshot = rollback.snapshot_from_row(stored)
            rows = database.list_loop_improvement_rollback_snapshots(conn, 5)
            files = database.list_loop_improvement_rollback_snapshot_files(
                conn, snapshot_id)
            events = database.get_loop_improvement_rollback_snapshot_events(
                conn, snapshot_id)

            self.assertEqual(stored["id"], snapshot_id)
            self.assertEqual(stored_snapshot.captured_files, 2)
            self.assertEqual(rows[0]["id"], snapshot_id)
            self.assertEqual(len(files), 2)
            self.assertIn("created", [e["event_type"] for e in events])
            self.assertIn("restore_previewed", [e["event_type"] for e in events])
            self.assertEqual(preview.status, "restore_preview")
            self.assertFalse(preview.restores_files)
            self.assertEqual(preview.total_files, 2)
            self.assertTrue(rollback.is_markdown_report_path(markdown.report_path))
            self.assertTrue(os.path.realpath(markdown.report_path).startswith(
                os.path.realpath(rollback.REPORTS_DIR) + os.sep))
            self.assertEqual(
                database.get_loop_improvement_rollback_snapshot_markdown_report(
                    conn, snapshot_id)["report_format"],
                "markdown",
            )

    def test_snapshot_does_not_mutate_runtime_or_application_attempt(self):
        import loop_improvement_rollback_snapshot as rollback

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "rollback.db"))
            self.addCleanup(conn.close)
            _write_target_files(td)
            old_root = rollback.PROJECT_ROOT
            rollback.PROJECT_ROOT = td
            self.addCleanup(setattr, rollback, "PROJECT_ROOT", old_root)
            attempt_id = _seed_application_attempt(conn)
            before_counts = {
                table: _count(conn, table)
                for table in (
                    "loops",
                    "external_agent_jobs",
                    "command_results",
                    "loop_improvement_patch_application_attempts",
                    "loop_improvement_patch_approvals",
                )
            }
            before_attempt = database.get_loop_improvement_patch_application_attempt(
                conn, attempt_id)

            snapshot = rollback.LoopImprovementRollbackSnapshotEngine(
                conn).create_snapshot(attempt_id)
            rollback.LoopImprovementRollbackSnapshotEngine(conn).save_snapshot(snapshot)

            after_counts = {table: _count(conn, table) for table in before_counts}
            self.assertEqual(after_counts, before_counts)
            after_attempt = database.get_loop_improvement_patch_application_attempt(
                conn, attempt_id)
            self.assertEqual(after_attempt["status"], before_attempt["status"])
            self.assertEqual(after_attempt["target_files_json"],
                             before_attempt["target_files_json"])

    def test_cli_snapshot_list_show_and_restore_preview_use_temp_database(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "rollback.db")
            conn = database.init_db(db_path)
            self.addCleanup(conn.close)
            _seed_application_attempt(conn)
            env = dict(os.environ)
            env["LOOP_DB_FILE"] = db_path
            env["ROLLBACK_PROJECT_ROOT"] = os.getcwd()
            env["OLLAMA_HOST"] = "http://127.0.0.1:9"

            create = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--create-loop-improvement-rollback-snapshot",
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
            self.assertIn("LOOP IMPROVEMENT ROLLBACK SNAPSHOT", create.stdout)
            self.assertIn("Status              : snapshot_created", create.stdout)
            self.assertIn("Applies changes     : False", create.stdout)

            listing = subprocess.run(
                [sys.executable, "main.py", "--loop-improvement-rollback-snapshots"],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertIn("status=snapshot_created", listing.stdout)
            self.assertIn("restores_files=False", listing.stdout)

            show = subprocess.run(
                [sys.executable, "main.py", "--loop-improvement-rollback-snapshot", "latest"],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(show.returncode, 0, show.stderr)
            self.assertIn("SNAPSHOT FILES", show.stdout)

            preview = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--preview-loop-improvement-rollback-restore",
                    "latest",
                ],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertIn("LOOP IMPROVEMENT ROLLBACK RESTORE PREVIEW", preview.stdout)
            self.assertIn("Restores files      : False", preview.stdout)


def _seed_application_attempt(conn):
    approval_id = _seed_approved_approval(conn)
    engine = loop_improvement_patch_application.LoopImprovementPatchApplicationEngine(
        conn)
    attempt = engine.create_application_attempt(approval_id)
    return engine.save_application_attempt(attempt)


def _write_target_files(root):
    with open(os.path.join(root, "stop_conditions.py"), "w", encoding="utf-8") as fh:
        fh.write("original stop\n")
    with open(os.path.join(root, "loop_engine.py"), "w", encoding="utf-8") as fh:
        fh.write("original loop\n")


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


if __name__ == "__main__":
    unittest.main()
