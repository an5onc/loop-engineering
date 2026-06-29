import json
import os
import tempfile
import unittest

import database


class LoopImprovementReviewTests(unittest.TestCase):
    def test_scores_priority_and_target_type(self):
        import loop_improvement_review

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "review.db"))
            self.addCleanup(conn.close)
            _proposal(conn, priority="urgent", target_type="safety_policy",
                      risk="high", effort="medium", loops=[1, 2, 3])
            _proposal(conn, priority="low", target_type="documentation",
                      risk="low", effort="low")

            report = loop_improvement_review.LoopImprovementReviewEngine(conn).build_report()

            self.assertEqual(report.top_proposals[0].target_type, "safety_policy")
            self.assertGreater(report.top_proposals[0].review_score,
                               report.top_proposals[1].review_score)
            self.assertIn(report.top_proposals[0].recommended_decision,
                          {"accept", "convert_to_action"})

    def test_rejected_and_deferred_rank_lower_when_included(self):
        import loop_improvement_review

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "review.db"))
            self.addCleanup(conn.close)
            open_id = _proposal(conn, priority="high", target_type="quality_gate",
                                status="proposed", risk="medium", effort="low")
            rejected_id = _proposal(conn, priority="urgent", target_type="safety_policy",
                                    status="rejected", risk="high", effort="low")

            report = loop_improvement_review.LoopImprovementReviewEngine(conn).build_report(
                status=None)
            scores = {item.proposal_id: item.review_score for item in report.top_proposals}

            self.assertGreater(scores[open_id], scores[rejected_id])
            self.assertEqual(
                next(i for i in report.top_proposals if i.proposal_id == rejected_id)
                .recommended_decision,
                "reject",
            )

    def test_group_by_target_priority_status_and_risk(self):
        import loop_improvement_review

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "review.db"))
            self.addCleanup(conn.close)
            _proposal(conn, priority="high", target_type="quality_gate",
                      status="proposed", risk="medium", effort="low")
            _proposal(conn, priority="medium", target_type="external_agent_flow",
                      status="deferred", risk="high", effort="high")
            engine = loop_improvement_review.LoopImprovementReviewEngine(conn)

            self.assertEqual(engine.build_report(group_by="target_type").groups[0].group_type,
                             "target_type")
            self.assertEqual(engine.build_report(group_by="priority", status=None).groups[0].group_type,
                             "priority")
            self.assertEqual(engine.build_report(group_by="status", status=None).groups[0].group_type,
                             "status")
            self.assertEqual(engine.build_report(group_by="risk", status=None).groups[0].group_type,
                             "risk")

    def test_review_persistence_and_markdown_path_safety(self):
        import loop_improvement_review

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "review.db"))
            self.addCleanup(conn.close)
            loop_improvement_review.REPORTS_DIR = os.path.join(td, "review_reports")
            _proposal(conn, priority="high", target_type="quality_gate",
                      risk="medium", effort="low")
            engine = loop_improvement_review.LoopImprovementReviewEngine(conn)
            report = engine.build_report(group_by="target_type")

            review_id = engine.save_review(report, group_by="target_type")
            md = engine.save_markdown_report(review_id, report)

            self.assertEqual(database.get_loop_improvement_review(conn, review_id)["id"],
                             review_id)
            self.assertEqual(len(database.list_loop_improvement_reviews(conn)), 1)
            self.assertTrue(os.path.exists(md.report_path))
            base = os.path.realpath(loop_improvement_review.REPORTS_DIR)
            self.assertTrue(os.path.realpath(md.report_path).startswith(base + os.sep))
            self.assertEqual(
                database.get_loop_improvement_review_markdown_report(conn, review_id)
                ["report_format"],
                "markdown",
            )

    def test_review_does_not_create_loops_jobs_commands_or_apply_proposals(self):
        import loop_improvement_review

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "review.db"))
            self.addCleanup(conn.close)
            loop_improvement_review.REPORTS_DIR = os.path.join(td, "review_reports")
            proposal_id = _proposal(conn, priority="high", target_type="quality_gate",
                                    risk="medium", effort="low")
            before_loops = _count(conn, "loops")
            before_jobs = _count(conn, "external_agent_jobs")
            before_commands = _count(conn, "command_results")
            engine = loop_improvement_review.LoopImprovementReviewEngine(conn)

            report = engine.build_report()
            review_id = engine.save_review(report, group_by="target_type")
            engine.save_markdown_report(review_id, report)

            self.assertEqual(_count(conn, "loops"), before_loops)
            self.assertEqual(_count(conn, "external_agent_jobs"), before_jobs)
            self.assertEqual(_count(conn, "command_results"), before_commands)
            self.assertEqual(
                database.get_loop_improvement_proposal(conn, proposal_id)["status"],
                "proposed",
            )

    def test_create_actions_recommendation_is_safe_noop_in_stage_5_1(self):
        import loop_improvement_review
        import main

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "review.db"))
            self.addCleanup(conn.close)
            _proposal(conn, priority="high", target_type="quality_gate",
                      risk="medium", effort="low")
            engine = loop_improvement_review.LoopImprovementReviewEngine(conn)
            review = engine.build_report()
            engine.save_review(review, group_by="target_type")
            before_loops = _count(conn, "loops")
            before_jobs = _count(conn, "external_agent_jobs")
            before_commands = _count(conn, "command_results")
            original_init_db = main.database.init_db
            main.database.init_db = lambda: conn
            self.addCleanup(setattr, main.database, "init_db", original_init_db)

            code = main._cmd_create_loop_improvement_actions(["latest"])

            self.assertEqual(code, 0)
            self.assertEqual(_count(conn, "loops"), before_loops)
            self.assertEqual(_count(conn, "external_agent_jobs"), before_jobs)
            self.assertEqual(_count(conn, "command_results"), before_commands)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _proposal(conn, priority, target_type, status="proposed", risk="low",
              effort="low", loops=None, actions=None, remediation_plans=None):
    if _count(conn, "loop_improvement_plans") == 0:
        database.save_loop_improvement_plan(
            conn,
            "2026-06-29T00:00:00",
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
    plan_id = database.list_loop_improvement_plans(conn, 1)[0]["id"]
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
        risk,
        effort,
        priority,
        json.dumps(loops or [], sort_keys=True),
        json.dumps(actions or [], sort_keys=True),
        json.dumps(remediation_plans or [], sort_keys=True),
        status,
    )


if __name__ == "__main__":
    unittest.main()
