import os
import subprocess
import sys
import tempfile
import unittest

import database
import loop_improvement_patch_dry_run
import loop_improvement_patch_proposals
from test_loop_improvement_patch_dry_run import _build_patch_proposal


class LoopImprovementPatchApprovalTests(unittest.TestCase):
    def test_approval_request_from_passing_dry_run_starts_pending(self):
        import loop_improvement_patch_approval as approval

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "patch_approval.db"))
            self.addCleanup(conn.close)
            validation_id = _seed_passing_validation(conn)

            request = approval.LoopImprovementPatchApprovalEngine(
                conn).create_approval_request(validation_id)

            self.assertEqual(request.validation_id, validation_id)
            self.assertEqual(request.status, "pending")
            self.assertTrue(request.approval_required)
            self.assertFalse(request.approved)
            self.assertFalse(request.applies_changes)
            self.assertFalse(request.generates_patch)
            self.assertFalse(request.executes_commands)
            self.assertFalse(request.auto_approved)
            self.assertIn("human approval", " ".join(request.required_controls).lower())
            self.assertIn("pending", request.approval_summary.lower())

    def test_approval_request_blocks_failed_dry_run_validation(self):
        import loop_improvement_patch_approval as approval

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "patch_approval.db"))
            self.addCleanup(conn.close)
            validation_id = _seed_failed_validation(conn)

            with self.assertRaisesRegex(ValueError, "not ready for human approval"):
                approval.LoopImprovementPatchApprovalEngine(
                    conn).create_approval_request(validation_id)

    def test_persistence_status_update_and_report_path_safety(self):
        import loop_improvement_patch_approval as approval

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "patch_approval.db"))
            self.addCleanup(conn.close)
            old_reports_dir = approval.REPORTS_DIR
            approval.REPORTS_DIR = os.path.join(td, "reports")
            self.addCleanup(setattr, approval, "REPORTS_DIR", old_reports_dir)
            validation_id = _seed_passing_validation(conn)
            engine = approval.LoopImprovementPatchApprovalEngine(conn)

            request = engine.create_approval_request(validation_id)
            request_id = engine.save_approval_request(request)
            updated = engine.update_approval_status(
                request_id, "approved", operator="human", notes="reviewed manually")
            markdown = engine.save_markdown_report(request_id, updated)
            stored = database.get_loop_improvement_patch_approval(conn, request_id)
            stored_request = approval.approval_from_row(stored)
            rows = database.list_loop_improvement_patch_approvals(conn, 5)
            events = database.get_loop_improvement_patch_approval_events(
                conn, request_id)

            self.assertEqual(stored["id"], request_id)
            self.assertEqual(stored_request.status, "approved")
            self.assertTrue(stored_request.approved)
            self.assertFalse(stored_request.applies_changes)
            self.assertEqual(rows[0]["id"], request_id)
            self.assertIn("created", [e["event_type"] for e in events])
            self.assertIn("status_updated", [e["event_type"] for e in events])
            self.assertTrue(approval.is_markdown_report_path(markdown.report_path))
            self.assertTrue(os.path.realpath(markdown.report_path).startswith(
                os.path.realpath(approval.REPORTS_DIR) + os.sep))
            self.assertEqual(
                database.get_loop_improvement_patch_approval_markdown_report(
                    conn, request_id)["report_format"],
                "markdown",
            )

    def test_approval_does_not_mutate_runtime_or_validation_records(self):
        import loop_improvement_patch_approval as approval

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "patch_approval.db"))
            self.addCleanup(conn.close)
            validation_id = _seed_passing_validation(conn)
            before_counts = {
                table: _count(conn, table)
                for table in (
                    "loops",
                    "external_agent_jobs",
                    "command_results",
                    "loop_improvement_patch_dry_run_validations",
                    "loop_improvement_patch_proposals",
                )
            }
            before_validation = database.get_loop_improvement_patch_dry_run_validation(
                conn, validation_id)

            request = approval.LoopImprovementPatchApprovalEngine(
                conn).create_approval_request(validation_id)
            request_id = approval.LoopImprovementPatchApprovalEngine(
                conn).save_approval_request(request)
            approval.LoopImprovementPatchApprovalEngine(conn).update_approval_status(
                request_id, "approved", operator="human", notes="metadata only")

            after_counts = {table: _count(conn, table) for table in before_counts}
            self.assertEqual(after_counts, before_counts)
            after_validation = database.get_loop_improvement_patch_dry_run_validation(
                conn, validation_id)
            self.assertEqual(after_validation["overall_status"],
                             before_validation["overall_status"])
            self.assertEqual(after_validation["checks_json"],
                             before_validation["checks_json"])

    def test_cli_request_list_show_and_status_use_temp_database(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "patch_approval.db")
            conn = database.init_db(db_path)
            self.addCleanup(conn.close)
            _seed_passing_validation(conn)
            env = dict(os.environ)
            env["LOOP_DB_FILE"] = db_path
            env["OLLAMA_HOST"] = "http://127.0.0.1:9"

            create = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--request-loop-improvement-patch-approval",
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
            self.assertIn("LOOP IMPROVEMENT PATCH APPROVAL", create.stdout)
            self.assertIn("Status              : pending", create.stdout)
            self.assertIn("Applies changes     : False", create.stdout)

            update = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--set-loop-improvement-patch-approval-status",
                    "latest",
                    "approved",
                    "human approval recorded",
                ],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(update.returncode, 0, update.stderr)
            self.assertIn("status -> approved", update.stdout)
            self.assertIn("No patch was applied.", update.stdout)

            listing = subprocess.run(
                [sys.executable, "main.py", "--loop-improvement-patch-approvals"],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertIn("status=approved", listing.stdout)
            self.assertIn("applies_changes=False", listing.stdout)

            show = subprocess.run(
                [sys.executable, "main.py", "--loop-improvement-patch-approval", "latest"],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(show.returncode, 0, show.stderr)
            self.assertIn("REQUIRED CONTROLS", show.stdout)
            self.assertIn("No changes are applied by approval recording.", show.stdout)


def _seed_passing_validation(conn):
    proposal = _build_patch_proposal(conn)
    proposal_id = loop_improvement_patch_proposals.LoopImprovementPatchProposalGenerator(
        conn).save_proposal(proposal)
    result = loop_improvement_patch_dry_run.LoopImprovementPatchDryRunValidator(
        conn).validate_patch_proposal(proposal_id)
    return loop_improvement_patch_dry_run.LoopImprovementPatchDryRunValidator(
        conn).save_validation(result)


def _seed_failed_validation(conn):
    proposal = _build_patch_proposal(conn)
    proposal.target_files = ["../.env"]
    proposal.items[0].target_file = "../.env"
    proposal_id = loop_improvement_patch_proposals.LoopImprovementPatchProposalGenerator(
        conn).save_proposal(proposal)
    result = loop_improvement_patch_dry_run.LoopImprovementPatchDryRunValidator(
        conn).validate_patch_proposal(proposal_id)
    return loop_improvement_patch_dry_run.LoopImprovementPatchDryRunValidator(
        conn).save_validation(result)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


if __name__ == "__main__":
    unittest.main()
