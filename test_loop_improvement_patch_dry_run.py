import os
import subprocess
import sys
import tempfile
import unittest

import database
import loop_improvement_patch_proposals
from test_loop_improvement_patch_proposals import _seed_application_plan


class LoopImprovementPatchDryRunTests(unittest.TestCase):
    def test_dry_run_validation_passes_for_safe_metadata_only_proposal(self):
        import loop_improvement_patch_dry_run as dry_run

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "patch_dry_run.db"))
            self.addCleanup(conn.close)
            proposal_id = _seed_patch_proposal(conn)

            result = dry_run.LoopImprovementPatchDryRunValidator(
                conn).validate_patch_proposal(proposal_id)

            self.assertEqual(result.patch_proposal_id, proposal_id)
            self.assertEqual(result.overall_status, "PASS")
            self.assertEqual(result.total_checks, 8)
            self.assertEqual(result.failed_checks, 0)
            self.assertTrue(result.ready_for_human_approval)
            self.assertFalse(result.generates_patch)
            self.assertFalse(result.applies_changes)
            self.assertFalse(result.executes_commands)
            self.assertFalse(result.reads_file_contents)
            self.assertIn("dry-run", " ".join(result.safety_notes).lower())
            self.assertIn("human approval",
                          " ".join(result.required_next_controls).lower())
            self.assertTrue(any(check.name == "target_file_allowlist"
                                and check.status == "PASS"
                                for check in result.checks))

    def test_dry_run_validation_blocks_unsafe_target_path(self):
        import loop_improvement_patch_dry_run as dry_run

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "patch_dry_run.db"))
            self.addCleanup(conn.close)
            proposal = _build_patch_proposal(conn)
            proposal.target_files = ["../.env"]
            proposal.items[0].target_file = "../.env"
            proposal_id = loop_improvement_patch_proposals.LoopImprovementPatchProposalGenerator(
                conn).save_proposal(proposal)

            result = dry_run.LoopImprovementPatchDryRunValidator(
                conn).validate_patch_proposal(proposal_id)

            self.assertEqual(result.overall_status, "FAIL")
            self.assertGreater(result.failed_checks, 0)
            self.assertFalse(result.ready_for_human_approval)
            self.assertIn("target file is outside the allowed relative workspace",
                          " ".join(result.blockers).lower())

    def test_dry_run_persistence_and_report_path_safety(self):
        import loop_improvement_patch_dry_run as dry_run

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "patch_dry_run.db"))
            self.addCleanup(conn.close)
            old_reports_dir = dry_run.REPORTS_DIR
            dry_run.REPORTS_DIR = os.path.join(td, "reports")
            self.addCleanup(setattr, dry_run, "REPORTS_DIR", old_reports_dir)
            proposal_id = _seed_patch_proposal(conn)
            engine = dry_run.LoopImprovementPatchDryRunValidator(conn)

            result = engine.validate_patch_proposal(proposal_id)
            validation_id = engine.save_validation(result)
            markdown = engine.save_markdown_report(validation_id, result)
            stored = database.get_loop_improvement_patch_dry_run_validation(
                conn, validation_id)
            stored_result = dry_run.validation_from_row(stored)
            rows = database.list_loop_improvement_patch_dry_run_validations(conn, 5)
            events = database.get_loop_improvement_patch_dry_run_validation_events(
                conn, validation_id)
            checks = database.list_loop_improvement_patch_dry_run_checks(
                conn, validation_id)

            self.assertEqual(stored["id"], validation_id)
            self.assertEqual(stored_result.patch_proposal_id, proposal_id)
            self.assertEqual(rows[0]["id"], validation_id)
            self.assertEqual(len(events), 1)
            self.assertEqual(len(checks), result.total_checks)
            self.assertTrue(dry_run.is_markdown_report_path(markdown.report_path))
            self.assertTrue(os.path.realpath(markdown.report_path).startswith(
                os.path.realpath(dry_run.REPORTS_DIR) + os.sep))
            self.assertEqual(
                database.get_loop_improvement_patch_dry_run_markdown_report(
                    conn, validation_id)["report_format"],
                "markdown",
            )

    def test_dry_run_does_not_mutate_runtime_or_patch_proposal(self):
        import loop_improvement_patch_dry_run as dry_run

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "patch_dry_run.db"))
            self.addCleanup(conn.close)
            proposal_id = _seed_patch_proposal(conn)
            before_counts = {
                table: _count(conn, table)
                for table in (
                    "loops",
                    "external_agent_jobs",
                    "command_results",
                    "loop_improvement_patch_proposals",
                    "loop_improvement_patch_proposal_items",
                )
            }
            before_proposal = database.get_loop_improvement_patch_proposal(
                conn, proposal_id)

            result = dry_run.LoopImprovementPatchDryRunValidator(
                conn).validate_patch_proposal(proposal_id)
            dry_run.LoopImprovementPatchDryRunValidator(conn).save_validation(result)

            after_counts = {table: _count(conn, table) for table in before_counts}
            self.assertEqual(after_counts, before_counts)
            after_proposal = database.get_loop_improvement_patch_proposal(
                conn, proposal_id)
            self.assertEqual(after_proposal["status"], before_proposal["status"])
            self.assertEqual(after_proposal["items_json"], before_proposal["items_json"])

    def test_cli_validate_list_and_show_use_temp_database(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "patch_dry_run.db")
            conn = database.init_db(db_path)
            self.addCleanup(conn.close)
            _seed_patch_proposal(conn)
            env = dict(os.environ)
            env["LOOP_DB_FILE"] = db_path
            env["OLLAMA_HOST"] = "http://127.0.0.1:9"

            create = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--validate-loop-improvement-patch-proposal",
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
            self.assertIn("LOOP IMPROVEMENT PATCH DRY-RUN VALIDATION", create.stdout)
            self.assertIn("Overall status      : PASS", create.stdout)
            self.assertIn("Generates patch     : False", create.stdout)

            listing = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--loop-improvement-patch-dry-runs",
                ],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertIn("status=PASS", listing.stdout)
            self.assertIn("generates_patch=False", listing.stdout)

            show = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--loop-improvement-patch-dry-run",
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
            self.assertIn("CHECKS", show.stdout)
            self.assertIn("No source file contents are read.", show.stdout)


def _build_patch_proposal(conn):
    application_plan_id = _seed_application_plan(conn)
    return loop_improvement_patch_proposals.LoopImprovementPatchProposalGenerator(
        conn).build_proposal(application_plan_id)


def _seed_patch_proposal(conn):
    proposal = _build_patch_proposal(conn)
    return loop_improvement_patch_proposals.LoopImprovementPatchProposalGenerator(
        conn).save_proposal(proposal)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


if __name__ == "__main__":
    unittest.main()
