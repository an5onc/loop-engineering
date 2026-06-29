import json
import os
import subprocess
import sys
import tempfile
import unittest

import database


class LoopImprovementApplicationPlannerTests(unittest.TestCase):
    def test_application_plan_from_action_metadata(self):
        import loop_improvement_application_planner as planner

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "application_plans.db"))
            self.addCleanup(conn.close)
            ids = _seed_pipeline(conn)

            plan = planner.LoopImprovementApplicationPlanner(conn).build_plan(
                source_type="action", source_id=ids["action_id"])

            self.assertEqual(plan.source_type, "action")
            self.assertEqual(plan.source_id, ids["action_id"])
            self.assertEqual(plan.source_action_id, ids["action_id"])
            self.assertEqual(plan.status, "planned")
            self.assertEqual(plan.total_items, 1)
            self.assertFalse(plan.generates_patch)
            self.assertFalse(plan.applies_changes)
            item = plan.items[0]
            self.assertEqual(item.target_type, "quality_gate")
            self.assertIn("stop_conditions.py", item.target_files)
            self.assertIn("loop_engine.py", item.target_files)
            self.assertIn("Require stronger reviewer consistency evidence",
                          item.patch_intent_summary)
            self.assertIn("human approval", " ".join(plan.required_approvals).lower())
            self.assertIn("rollback snapshot", " ".join(plan.rollback_requirements).lower())
            self.assertIn("dry-run", " ".join(plan.safety_notes).lower())

    def test_application_plan_from_handoff_review_uses_safe_handoff_items(self):
        import loop_improvement_application_planner as planner

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "application_plans.db"))
            self.addCleanup(conn.close)
            ids = _seed_pipeline(conn)
            review_id = _handoff_review(conn, ids)

            plan = planner.LoopImprovementApplicationPlanner(conn).build_plan(
                source_type="handoff_review", source_id=review_id)

            self.assertEqual(plan.source_type, "handoff_review")
            self.assertEqual(plan.source_id, review_id)
            self.assertEqual(plan.total_items, 1)
            self.assertEqual(plan.items[0].source_handoff_id, ids["handoff_id"])
            self.assertEqual(plan.items[0].target_name, "reviewer_consistency")
            self.assertIn("python3 main.py --loop-improvement-handoff",
                          plan.recommended_next_commands[0])

    def test_persistence_list_show_and_markdown_path_safety(self):
        import loop_improvement_application_planner as planner

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "application_plans.db"))
            self.addCleanup(conn.close)
            old_reports_dir = planner.REPORTS_DIR
            planner.REPORTS_DIR = os.path.join(td, "reports")
            self.addCleanup(setattr, planner, "REPORTS_DIR", old_reports_dir)
            ids = _seed_pipeline(conn)
            engine = planner.LoopImprovementApplicationPlanner(conn)

            plan = engine.build_plan(source_type="action", source_id=ids["action_id"])
            plan_id = engine.save_plan(plan)
            markdown = engine.save_markdown_report(plan_id, plan)
            stored = database.get_loop_improvement_application_plan(conn, plan_id)
            stored_plan = planner.plan_from_row(stored)
            rows = database.list_loop_improvement_application_plans(conn, 5)
            events = database.get_loop_improvement_application_plan_events(conn, plan_id)
            items = database.list_loop_improvement_application_plan_items(conn, plan_id)

            self.assertEqual(stored["id"], plan_id)
            self.assertEqual(stored_plan.total_items, 1)
            self.assertEqual(rows[0]["id"], plan_id)
            self.assertEqual(len(events), 1)
            self.assertEqual(len(items), 1)
            self.assertTrue(planner.is_markdown_report_path(markdown.report_path))
            self.assertTrue(os.path.realpath(markdown.report_path).startswith(
                os.path.realpath(planner.REPORTS_DIR) + os.sep))
            self.assertEqual(
                database.get_loop_improvement_application_plan_markdown_report(
                    conn, plan_id)["report_format"],
                "markdown",
            )

    def test_application_planning_does_not_mutate_runtime_or_improvement_records(self):
        import loop_improvement_application_planner as planner

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "application_plans.db"))
            self.addCleanup(conn.close)
            ids = _seed_pipeline(conn)
            before_counts = {
                table: _count(conn, table)
                for table in (
                    "loops",
                    "external_agent_jobs",
                    "command_results",
                    "loop_improvement_proposals",
                    "loop_improvement_action_items",
                    "loop_improvement_handoffs",
                )
            }
            before_proposal = database.get_loop_improvement_proposal(
                conn, ids["proposal_id"])["status"]
            before_action = database.get_loop_improvement_action_item(
                conn, ids["action_id"])["status"]
            before_handoff = database.get_loop_improvement_handoff(
                conn, ids["handoff_id"])["status"]

            plan = planner.LoopImprovementApplicationPlanner(conn).build_plan(
                source_type="action", source_id=ids["action_id"])
            planner.LoopImprovementApplicationPlanner(conn).save_plan(plan)

            after_counts = {
                table: _count(conn, table)
                for table in before_counts
            }
            self.assertEqual(after_counts, before_counts)
            self.assertEqual(
                database.get_loop_improvement_proposal(conn, ids["proposal_id"])["status"],
                before_proposal,
            )
            self.assertEqual(
                database.get_loop_improvement_action_item(conn, ids["action_id"])["status"],
                before_action,
            )
            self.assertEqual(
                database.get_loop_improvement_handoff(conn, ids["handoff_id"])["status"],
                before_handoff,
            )

    def test_cli_plan_list_and_show_use_temp_database(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "application_plans.db")
            conn = database.init_db(db_path)
            self.addCleanup(conn.close)
            _seed_pipeline(conn)
            env = dict(os.environ)
            env["LOOP_DB_FILE"] = db_path
            env["OLLAMA_HOST"] = "http://127.0.0.1:9"

            create = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--plan-loop-improvement-application",
                    "latest",
                    "--source-type",
                    "action",
                ],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(create.returncode, 0, create.stderr)
            self.assertIn("LOOP IMPROVEMENT APPLICATION PLAN", create.stdout)
            self.assertIn("Generates patch     : False", create.stdout)
            self.assertIn("Applies changes     : False", create.stdout)

            listing = subprocess.run(
                [sys.executable, "main.py", "--loop-improvement-application-plans"],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertIn("generates_patch=False", listing.stdout)
            self.assertIn("applies_changes=False", listing.stdout)

            show = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--loop-improvement-application-plan",
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
            self.assertIn("REQUIRED APPROVALS", show.stdout)
            self.assertIn("No patches are generated.", show.stdout)


def _seed_pipeline(conn):
    plan_id = database.save_loop_improvement_plan(
        conn,
        "2026-06-29T12:00:00",
        "action_review",
        1,
        "{}",
        json.dumps({"summary": "application planner seed"}, sort_keys=True),
        "[]",
        1,
        0,
        1,
        0,
        0,
    )
    proposal_id = database.save_loop_improvement_proposal(
        conn,
        plan_id,
        "quality_gate",
        "reviewer_consistency",
        "Tighten reviewer consistency",
        "Reviewer inconsistency can allow unsafe approvals.",
        "[]",
        "Require stronger reviewer consistency evidence.",
        "Safer automated review loops.",
        "medium",
        "low",
        "high",
        "[]",
        "[]",
        "[]",
        "accepted",
    )
    review_id = database.save_loop_improvement_review(
        conn,
        "2026-06-29T12:01:00",
        "{}",
        "target_type",
        1,
        "[]",
        "[]",
        "[]",
        "[]",
    )
    action_id = database.save_loop_improvement_action_item(
        conn,
        review_id,
        proposal_id,
        plan_id,
        "quality_gate",
        "reviewer_consistency",
        "Tighten reviewer consistency",
        "high",
        "open",
        "medium",
        "low",
        "Reviewer inconsistency can allow unsafe approvals.",
        "Require stronger reviewer consistency evidence.",
        "Safer automated review loops.",
        "convert_to_action",
        f"python3 main.py --loop-improvement-proposal {proposal_id}",
        "[]",
        "[]",
        "[]",
        "operator approved planning",
    )
    handoff_id = database.save_loop_improvement_handoff(
        conn,
        action_id,
        review_id,
        proposal_id,
        plan_id,
        "implementation_packet",
        "Implement a safe quality gate improvement.",
        "quality_gate_update",
        "quality_gate",
        "reviewer_consistency",
        "code_build",
        "default",
        "codex",
        f"python3 main.py --handoff-loop-improvement-action {action_id}",
        json.dumps(["safe"], sort_keys=True),
        "PACKET_CREATED",
        dry_run=True,
        packet_path="/tmp/loop_improvement_handoff_packets/packet.md",
    )
    return {
        "plan_id": plan_id,
        "proposal_id": proposal_id,
        "review_id": review_id,
        "action_id": action_id,
        "handoff_id": handoff_id,
    }


def _handoff_review(conn, ids):
    item = {
        "handoff_id": ids["handoff_id"],
        "action_id": ids["action_id"],
        "source_review_id": ids["review_id"],
        "source_proposal_id": ids["proposal_id"],
        "source_plan_id": ids["plan_id"],
        "handoff_type": "implementation_packet",
        "status": "PACKET_CREATED",
        "implementation_scope": "quality_gate_update",
        "target_type": "quality_gate",
        "target_name": "reviewer_consistency",
        "target_loop_type": "code_build",
        "target_workspace": "default",
        "external_coder": "codex",
        "created_loop_id": None,
        "created_external_job_id": None,
        "packet_path": "/tmp/loop_improvement_handoff_packets/packet.md",
        "generated_task_preview": "Implement a safe quality gate improvement.",
        "safety_notes": ["safe"],
        "review_status": "safe_packet",
        "review_score": 50,
        "risk_level": "low",
        "rationale": "implementation packet path is confined",
        "recommended_decision": "approve_for_manual_execution",
        "recommended_next_command": (
            f"python3 main.py --loop-improvement-handoff {ids['handoff_id']}"
        ),
        "created_at": "2026-06-29T12:02:00",
    }
    return database.save_loop_improvement_handoff_review(
        conn,
        "2026-06-29T12:03:00",
        "{}",
        "status",
        1,
        "[]",
        json.dumps([item], sort_keys=True),
        "[]",
        "[]",
    )


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


if __name__ == "__main__":
    unittest.main()
