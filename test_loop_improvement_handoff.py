import json
import os
import tempfile
import unittest

import database
import loop_improvement_review


class LoopImprovementHandoffTests(unittest.TestCase):
    def test_dry_run_handoff_does_not_create_loop_job_or_command_result(self):
        import loop_improvement_handoff

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "handoff.db"))
            self.addCleanup(conn.close)
            action_id = _action(conn, target_type="quality_gate")
            before_loops = _count(conn, "loops")
            before_jobs = _count(conn, "external_agent_jobs")
            before_commands = _count(conn, "command_results")

            handoff = loop_improvement_handoff.LoopImprovementHandoffEngine(
                conn).create_handoff(action_id)

            self.assertEqual(handoff.handoff_type, "dry_run_plan")
            self.assertEqual(handoff.status, "DRY_RUN")
            self.assertTrue(handoff.dry_run)
            self.assertEqual(_count(conn, "loops"), before_loops)
            self.assertEqual(_count(conn, "external_agent_jobs"), before_jobs)
            self.assertEqual(_count(conn, "command_results"), before_commands)

    def test_generated_task_includes_action_metadata_and_scope(self):
        import loop_improvement_handoff

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "handoff.db"))
            self.addCleanup(conn.close)
            action_id = _action(conn, target_type="quality_gate",
                                target_name="reviewer_gate")

            handoff = loop_improvement_handoff.LoopImprovementHandoffEngine(
                conn).create_handoff(action_id, handoff_type="loop_task",
                                     target_loop_type="code_review",
                                     target_workspace="loop-engineering")

            self.assertEqual(handoff.implementation_scope, "quality_gate_update")
            self.assertIn("Implement a safe Loop Engineering improvement",
                          handoff.generated_task)
            self.assertIn("quality_gate", handoff.generated_task)
            self.assertIn("reviewer_gate", handoff.generated_task)
            self.assertIn("Quality gate failures repeat", handoff.generated_task)
            self.assertIn("Tighten reviewer consistency gate", handoff.generated_task)
            self.assertIn("preserve approval/workspace/command protections",
                          handoff.generated_task)
            self.assertEqual(handoff.target_loop_type, "code_review")
            self.assertEqual(handoff.target_workspace, "loop-engineering")
            self.assertEqual(handoff.status, "DRY_RUN")

    def test_implementation_scope_mapping(self):
        import loop_improvement_handoff

        mapping = {
            "safety_policy": "safety_policy_update",
            "quality_gate": "quality_gate_update",
            "stop_condition": "stop_condition_update",
            "prompt": "prompt_contract_update",
            "agent_definition": "agent_definition_update",
            "loop_definition": "loop_definition_update",
            "external_agent_flow": "external_agent_flow_update",
            "documentation": "documentation_update",
            "testing": "testing_update",
            "observatory_flow": "observability_update",
            "unknown": "unknown",
        }
        for target_type, expected in mapping.items():
            self.assertEqual(loop_improvement_handoff.infer_implementation_scope(target_type),
                             expected)

    def test_implementation_packet_creates_safe_packet_and_metadata(self):
        import loop_improvement_handoff

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "handoff.db"))
            self.addCleanup(conn.close)
            loop_improvement_handoff.PACKETS_DIR = os.path.join(td, "packets")
            action_id = _action(conn, target_type="documentation")

            handoff = loop_improvement_handoff.LoopImprovementHandoffEngine(
                conn).create_handoff(action_id, handoff_type="implementation_packet")
            packet = database.get_loop_improvement_handoff_packet(conn, handoff.id)

            self.assertEqual(handoff.handoff_type, "implementation_packet")
            self.assertEqual(handoff.status, "PACKET_CREATED")
            self.assertTrue(os.path.exists(handoff.packet_path))
            base = os.path.realpath(loop_improvement_handoff.PACKETS_DIR)
            self.assertTrue(os.path.realpath(handoff.packet_path).startswith(base + os.sep))
            self.assertEqual(packet["packet_format"], "markdown")
            with open(handoff.packet_path, encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("## Safety Constraints", content)
            self.assertIn("Suggested Manual Commands", content)

    def test_creation_requires_confirmation_and_records_created_ids(self):
        import loop_improvement_handoff

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "handoff.db"))
            self.addCleanup(conn.close)
            action_id = _action(conn, target_type="external_agent_flow")
            engine = loop_improvement_handoff.LoopImprovementHandoffEngine(conn)

            loop_dry = engine.create_handoff(action_id, handoff_type="loop_task")
            ext_dry = engine.create_handoff(
                action_id, handoff_type="external_agent_job", external_coder="codex")
            loop_confirmed = engine.create_handoff(
                action_id, handoff_type="loop_task", confirm_create_loop=True,
                created_loop_id=12)
            ext_confirmed = engine.create_handoff(
                action_id, handoff_type="external_agent_job",
                confirm_create_external_job=True, created_external_job_id=34)

            self.assertEqual(loop_dry.status, "DRY_RUN")
            self.assertEqual(ext_dry.status, "DRY_RUN")
            self.assertEqual(loop_confirmed.status, "LOOP_CREATED")
            self.assertFalse(loop_confirmed.dry_run)
            self.assertEqual(loop_confirmed.created_loop_id, 12)
            self.assertEqual(ext_confirmed.status, "EXTERNAL_JOB_CREATED")
            self.assertEqual(ext_confirmed.created_external_job_id, 34)

    def test_handoff_persistence_events_and_list_show_cli_helpers(self):
        import loop_improvement_handoff
        import main

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "handoff.db"))
            self.addCleanup(conn.close)
            action_id = _action(conn, target_type="testing")
            engine = loop_improvement_handoff.LoopImprovementHandoffEngine(conn)

            handoff = engine.create_handoff(action_id)
            stored = database.get_loop_improvement_handoff(conn, handoff.id)
            events = database.get_loop_improvement_handoff_events(conn, handoff.id)
            original_init_db = main.database.init_db
            main.database.init_db = lambda: conn
            self.addCleanup(setattr, main.database, "init_db", original_init_db)

            list_code = main._cmd_loop_improvement_handoffs([])
            show_code = main._cmd_loop_improvement_handoff(["latest"])

            self.assertEqual(stored["id"], handoff.id)
            self.assertEqual(len(database.list_loop_improvement_handoffs(conn)), 1)
            self.assertTrue(any(e["event_type"] == "created" for e in events))
            self.assertEqual(list_code, 0)
            self.assertEqual(show_code, 0)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _action(conn, target_type="quality_gate", target_name=None):
    plan_id = database.save_loop_improvement_plan(
        conn,
        "2026-06-29T13:00:00",
        "action_review",
        1,
        "{}",
        json.dumps({"summary": "test", "next_steps": []}, sort_keys=True),
        "[]",
        0,
        0,
        0,
        0,
        0,
    )
    proposal_id = database.save_loop_improvement_proposal(
        conn,
        plan_id,
        target_type,
        target_name or f"{target_type}_target",
        f"{target_type} proposal",
        "Quality gate failures repeat.",
        json.dumps([f"{target_type} evidence"], sort_keys=True),
        "Tighten reviewer consistency gate.",
        "Fewer unsafe approvals.",
        "medium",
        "low",
        "high",
        json.dumps([101], sort_keys=True),
        json.dumps([201], sort_keys=True),
        json.dumps([301], sort_keys=True),
        "proposed",
    )
    item = loop_improvement_review.LoopImprovementReviewItem(
        proposal_id=proposal_id,
        plan_id=plan_id,
        target_type=target_type,
        target_name=target_name or f"{target_type}_target",
        title=f"{target_type} proposal",
        priority="high",
        status="proposed",
        risk_level="medium",
        effort_level="low",
        affected_loop_ids=[101],
        affected_action_ids=[201],
        affected_remediation_plan_ids=[301],
        problem_summary="Quality gate failures repeat.",
        proposed_change="Tighten reviewer consistency gate.",
        expected_benefit="Fewer unsafe approvals.",
        review_score=100,
        recommended_decision="accept",
        suggested_next_command=f"python3 main.py --loop-improvement-proposal {proposal_id}",
    )
    review_id = database.save_loop_improvement_review(
        conn,
        "2026-06-29T13:01:00",
        "{}",
        "target_type",
        1,
        json.dumps([loop_improvement_review.item_to_dict(item)], sort_keys=True),
        "[]",
        "[]",
        "[]",
    )
    batch_id = database.save_loop_improvement_action_item(
        conn,
        review_id,
        proposal_id,
        plan_id,
        target_type,
        target_name or f"{target_type}_target",
        f"{target_type} proposal",
        "high",
        "open",
        "medium",
        "low",
        "Quality gate failures repeat.",
        "Tighten reviewer consistency gate.",
        "Fewer unsafe approvals.",
        "accept",
        f"python3 main.py --loop-improvement-proposal {proposal_id}",
        json.dumps([101], sort_keys=True),
        json.dumps([201], sort_keys=True),
        json.dumps([301], sort_keys=True),
        "Operator note.",
    )
    return batch_id


if __name__ == "__main__":
    unittest.main()
