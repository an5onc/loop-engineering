import os
import subprocess
import sys
import tempfile
import unittest

import database
import loop_improvement_application_planner
from test_loop_improvement_application_planner import _seed_pipeline


class LoopImprovementPatchProposalTests(unittest.TestCase):
    def test_patch_proposal_from_application_plan_metadata(self):
        import loop_improvement_patch_proposals as patcher

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "patch_proposals.db"))
            self.addCleanup(conn.close)
            application_plan_id = _seed_application_plan(conn)

            proposal = patcher.LoopImprovementPatchProposalGenerator(
                conn).build_proposal(application_plan_id)

            self.assertEqual(proposal.application_plan_id, application_plan_id)
            self.assertEqual(proposal.status, "proposed")
            self.assertEqual(proposal.total_plan_items, 1)
            self.assertEqual(proposal.total_target_files, 2)
            self.assertIn("stop_conditions.py", proposal.target_files)
            self.assertIn("loop_engine.py", proposal.target_files)
            self.assertFalse(proposal.generates_unified_diff)
            self.assertFalse(proposal.writes_patch_file)
            self.assertFalse(proposal.applies_changes)
            self.assertFalse(proposal.reads_file_contents)
            self.assertIn("metadata-only", " ".join(proposal.safety_notes).lower())
            self.assertIn("human approval", " ".join(proposal.required_approvals).lower())
            self.assertIn("rollback snapshot", " ".join(proposal.rollback_requirements).lower())
            self.assertIn("dry-run validator",
                          " ".join(proposal.recommended_next_commands).lower())
            self.assertEqual(len(proposal.items), 2)
            self.assertEqual(
                sorted(item.target_file for item in proposal.items),
                ["loop_engine.py", "stop_conditions.py"],
            )
            self.assertTrue(all(item.proposed_edit_kind == "metadata_intent"
                                for item in proposal.items))

    def test_patch_proposal_persistence_and_report_path_safety(self):
        import loop_improvement_patch_proposals as patcher

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "patch_proposals.db"))
            self.addCleanup(conn.close)
            old_reports_dir = patcher.REPORTS_DIR
            patcher.REPORTS_DIR = os.path.join(td, "reports")
            self.addCleanup(setattr, patcher, "REPORTS_DIR", old_reports_dir)
            application_plan_id = _seed_application_plan(conn)
            engine = patcher.LoopImprovementPatchProposalGenerator(conn)

            proposal = engine.build_proposal(application_plan_id)
            proposal_id = engine.save_proposal(proposal)
            markdown = engine.save_markdown_report(proposal_id, proposal)
            stored = database.get_loop_improvement_patch_proposal(conn, proposal_id)
            stored_proposal = patcher.proposal_from_row(stored)
            rows = database.list_loop_improvement_patch_proposals(conn, 5)
            events = database.get_loop_improvement_patch_proposal_events(
                conn, proposal_id)
            items = database.list_loop_improvement_patch_proposal_items(
                conn, proposal_id)

            self.assertEqual(stored["id"], proposal_id)
            self.assertEqual(stored_proposal.total_target_files, 2)
            self.assertEqual(rows[0]["id"], proposal_id)
            self.assertEqual(len(events), 1)
            self.assertEqual(len(items), 2)
            self.assertTrue(patcher.is_markdown_report_path(markdown.report_path))
            self.assertTrue(os.path.realpath(markdown.report_path).startswith(
                os.path.realpath(patcher.REPORTS_DIR) + os.sep))
            self.assertEqual(
                database.get_loop_improvement_patch_proposal_markdown_report(
                    conn, proposal_id)["report_format"],
                "markdown",
            )

    def test_patch_proposal_does_not_mutate_runtime_or_application_plan(self):
        import loop_improvement_patch_proposals as patcher

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "patch_proposals.db"))
            self.addCleanup(conn.close)
            application_plan_id = _seed_application_plan(conn)
            before_counts = {
                table: _count(conn, table)
                for table in (
                    "loops",
                    "external_agent_jobs",
                    "command_results",
                    "loop_improvement_application_plans",
                    "loop_improvement_application_plan_items",
                )
            }
            before_plan = database.get_loop_improvement_application_plan(
                conn, application_plan_id)

            proposal = patcher.LoopImprovementPatchProposalGenerator(
                conn).build_proposal(application_plan_id)
            patcher.LoopImprovementPatchProposalGenerator(conn).save_proposal(proposal)

            after_counts = {table: _count(conn, table) for table in before_counts}
            self.assertEqual(after_counts, before_counts)
            after_plan = database.get_loop_improvement_application_plan(
                conn, application_plan_id)
            self.assertEqual(after_plan["status"], before_plan["status"])
            self.assertEqual(after_plan["items_json"], before_plan["items_json"])

    def test_cli_generate_list_and_show_use_temp_database(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "patch_proposals.db")
            conn = database.init_db(db_path)
            self.addCleanup(conn.close)
            _seed_application_plan(conn)
            env = dict(os.environ)
            env["LOOP_DB_FILE"] = db_path
            env["OLLAMA_HOST"] = "http://127.0.0.1:9"

            create = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--generate-loop-improvement-patch-proposal",
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
            self.assertIn("LOOP IMPROVEMENT PATCH PROPOSAL", create.stdout)
            self.assertIn("Generates unified diff : False", create.stdout)
            self.assertIn("Applies changes        : False", create.stdout)

            listing = subprocess.run(
                [sys.executable, "main.py", "--loop-improvement-patch-proposals"],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertIn("generates_unified_diff=False", listing.stdout)
            self.assertIn("applies_changes=False", listing.stdout)

            show = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--loop-improvement-patch-proposal",
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
            self.assertIn("METADATA-ONLY PATCH INTENT", show.stdout)
            self.assertIn("No source file contents are read.", show.stdout)


def _seed_application_plan(conn):
    ids = _seed_pipeline(conn)
    engine = loop_improvement_application_planner.LoopImprovementApplicationPlanner(conn)
    plan = engine.build_plan(source_type="action", source_id=ids["action_id"])
    return engine.save_plan(plan)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


if __name__ == "__main__":
    unittest.main()
