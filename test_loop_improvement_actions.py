import json
import os
import tempfile
import unittest

import database
import loop_improvement_review


class LoopImprovementActionTests(unittest.TestCase):
    def test_create_actions_from_review_and_prevent_duplicates(self):
        import loop_improvement_actions

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "actions.db"))
            self.addCleanup(conn.close)
            review_id, proposal_ids = _review(conn)
            engine = loop_improvement_actions.LoopImprovementActionEngine(conn)

            first = engine.create_actions_from_review(review_id)
            second = engine.create_actions_from_review(review_id)
            actions = database.list_loop_improvement_action_items(conn, status=None)

            self.assertEqual(first.created_count, 2)
            self.assertEqual(first.skipped_duplicates, 0)
            self.assertEqual(second.created_count, 0)
            self.assertEqual(second.skipped_duplicates, 2)
            self.assertEqual(len(actions), 2)
            self.assertEqual(
                {a["source_proposal_id"] for a in actions},
                {proposal_ids["accepted"], proposal_ids["high_deferred"]},
            )
            statuses = [
                e["event_type"]
                for action in actions
                for e in database.get_loop_improvement_action_events(conn, action["id"])
            ]
            self.assertIn("created", statuses)
            self.assertIn("duplicate_skipped", statuses)

    def test_filters_by_priority_and_target_type(self):
        import loop_improvement_actions

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "actions.db"))
            self.addCleanup(conn.close)
            review_id, proposal_ids = _review(conn)
            engine = loop_improvement_actions.LoopImprovementActionEngine(conn)

            high = engine.create_actions_from_review(review_id, priority="high")
            quality = engine.create_actions_from_review(review_id, target_type="quality_gate")
            actions = database.list_loop_improvement_action_items(conn, status=None)

            self.assertEqual(high.created_count, 1)
            self.assertEqual(quality.created_count, 1)
            self.assertEqual(
                {a["source_proposal_id"] for a in actions},
                {proposal_ids["accepted"], proposal_ids["high_deferred"]},
            )

    def test_include_deferred_and_rejected_flags(self):
        import loop_improvement_actions

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "actions.db"))
            self.addCleanup(conn.close)
            review_id, proposal_ids = _review(conn)
            engine = loop_improvement_actions.LoopImprovementActionEngine(conn)

            batch = engine.create_actions_from_review(
                review_id, include_deferred=True, include_rejected=True)
            actions = database.list_loop_improvement_action_items(conn, status=None)

            self.assertEqual(batch.created_count, 4)
            self.assertEqual(
                {a["source_proposal_id"] for a in actions},
                set(proposal_ids.values()),
            )

    def test_list_status_update_notes_and_events(self):
        import loop_improvement_actions

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "actions.db"))
            self.addCleanup(conn.close)
            review_id, _ = _review(conn)
            engine = loop_improvement_actions.LoopImprovementActionEngine(conn)
            batch = engine.create_actions_from_review(review_id)
            action_id = batch.actions[0].id

            open_queue = engine.list_actions(status="open")
            in_progress = engine.update_status(action_id, "in_progress")
            completed = engine.update_status(action_id, "completed")
            noted = engine.update_notes(action_id, "verification note")
            viewed = engine.get_action(action_id)
            events = database.get_loop_improvement_action_events(conn, action_id)

            self.assertEqual(len(open_queue), 2)
            self.assertEqual(in_progress.status, "in_progress")
            self.assertEqual(completed.status, "completed")
            self.assertTrue(completed.completed_at)
            self.assertEqual(noted.notes, "verification note")
            self.assertEqual(viewed.id, action_id)
            self.assertIn("status_changed", [e["event_type"] for e in events])
            self.assertIn("notes_updated", [e["event_type"] for e in events])
            self.assertIn("viewed", [e["event_type"] for e in events])

    def test_batch_persistence_and_markdown_path_safety(self):
        import loop_improvement_actions

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "actions.db"))
            self.addCleanup(conn.close)
            loop_improvement_actions.REPORTS_DIR = os.path.join(td, "action_reports")
            review_id, _ = _review(conn)
            engine = loop_improvement_actions.LoopImprovementActionEngine(conn)

            batch = engine.create_actions_from_review(review_id)
            md = engine.save_markdown_report()

            self.assertEqual(database.get_loop_improvement_action_batch(conn, batch.id)["id"],
                             batch.id)
            self.assertEqual(len(database.list_loop_improvement_action_batches(conn)), 1)
            self.assertTrue(os.path.exists(md.report_path))
            base = os.path.realpath(loop_improvement_actions.REPORTS_DIR)
            self.assertTrue(os.path.realpath(md.report_path).startswith(base + os.sep))
            self.assertEqual(
                database.list_loop_improvement_action_markdown_reports(conn)[0]["report_format"],
                "markdown",
            )

    def test_action_conversion_does_not_create_loops_commands_jobs_or_apply_proposals(self):
        import loop_improvement_actions

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "actions.db"))
            self.addCleanup(conn.close)
            review_id, proposal_ids = _review(conn)
            before_loops = _count(conn, "loops")
            before_commands = _count(conn, "command_results")
            before_jobs = _count(conn, "external_agent_jobs")
            engine = loop_improvement_actions.LoopImprovementActionEngine(conn)

            engine.create_actions_from_review(review_id)

            self.assertEqual(_count(conn, "loops"), before_loops)
            self.assertEqual(_count(conn, "command_results"), before_commands)
            self.assertEqual(_count(conn, "external_agent_jobs"), before_jobs)
            for proposal_id in proposal_ids.values():
                self.assertEqual(
                    database.get_loop_improvement_proposal(conn, proposal_id)["status"],
                    "proposed",
                )


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _review(conn):
    plan_id = database.save_loop_improvement_plan(
        conn,
        "2026-06-29T12:00:00",
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
    accepted = _proposal(conn, plan_id, "quality_gate", "medium", "proposed")
    high_deferred = _proposal(conn, plan_id, "external_agent_flow", "high", "proposed")
    low_deferred = _proposal(conn, plan_id, "documentation", "low", "proposed")
    rejected = _proposal(conn, plan_id, "testing", "urgent", "proposed")
    items = [
        _review_item(accepted, plan_id, "quality_gate", "medium", "proposed", "accept"),
        _review_item(high_deferred, plan_id, "external_agent_flow", "high", "proposed", "defer"),
        _review_item(low_deferred, plan_id, "documentation", "low", "deferred", "defer"),
        _review_item(rejected, plan_id, "testing", "urgent", "rejected", "reject"),
    ]
    review_id = database.save_loop_improvement_review(
        conn,
        "2026-06-29T12:01:00",
        "{}",
        "target_type",
        len(items),
        json.dumps([loop_improvement_review.item_to_dict(i) for i in items], sort_keys=True),
        "[]",
        "[]",
        "[]",
    )
    return review_id, {
        "accepted": accepted,
        "high_deferred": high_deferred,
        "low_deferred": low_deferred,
        "rejected": rejected,
    }


def _proposal(conn, plan_id, target_type, priority, status):
    return database.save_loop_improvement_proposal(
        conn,
        plan_id,
        target_type,
        f"{target_type}_target",
        f"{target_type} proposal",
        f"{target_type} problem",
        json.dumps([f"{target_type} evidence"], sort_keys=True),
        f"Improve {target_type}",
        f"Better {target_type}",
        "medium" if priority in ("urgent", "high") else "low",
        "low",
        priority,
        json.dumps([101], sort_keys=True),
        json.dumps([201], sort_keys=True),
        json.dumps([301], sort_keys=True),
        status,
    )


def _review_item(proposal_id, plan_id, target_type, priority, status, decision):
    return loop_improvement_review.LoopImprovementReviewItem(
        proposal_id=proposal_id,
        plan_id=plan_id,
        target_type=target_type,
        target_name=f"{target_type}_target",
        title=f"{target_type} proposal",
        priority=priority,
        status=status,
        risk_level="medium" if priority in ("urgent", "high") else "low",
        effort_level="low",
        affected_loop_ids=[101],
        affected_action_ids=[201],
        affected_remediation_plan_ids=[301],
        problem_summary=f"{target_type} problem",
        proposed_change=f"Improve {target_type}",
        expected_benefit=f"Better {target_type}",
        review_score=100,
        recommended_decision=decision,
        suggested_next_command=f"python3 main.py --loop-improvement-proposal {proposal_id}",
    )


if __name__ == "__main__":
    unittest.main()
