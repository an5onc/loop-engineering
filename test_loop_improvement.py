import json
import os
import tempfile
import unittest

import database
import observatory_action_review
import observatory_drilldown
import observatory_remediation


class LoopImprovementTests(unittest.TestCase):
    def test_improvement_plan_from_action_review(self):
        import loop_improvement

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "improvements.db"))
            self.addCleanup(conn.close)
            review_id = _action_review(conn)

            plan = loop_improvement.LoopImprovementEngine(conn).build_plan(
                source_type="action_review", source_id=review_id)

            self.assertEqual(plan.source_type, "action_review")
            self.assertEqual(plan.source_id, review_id)
            self.assertGreaterEqual(plan.total_proposals, 3)
            targets = {p.target_type for p in plan.proposals}
            self.assertIn("quality_gate", targets)
            self.assertIn("external_agent_flow", targets)
            self.assertIn("documentation", targets)
            self.assertGreaterEqual(plan.high_count, 2)

    def test_improvement_plan_from_remediation_and_failure_drilldown(self):
        import loop_improvement

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "improvements.db"))
            self.addCleanup(conn.close)
            drilldown_id = _failure_drilldown(conn)
            remediation_id = _remediation_plan(conn, drilldown_id)
            engine = loop_improvement.LoopImprovementEngine(conn)

            remediation_plan = engine.build_plan(
                source_type="remediation_plan", source_id=remediation_id)
            failure_plan = engine.build_plan(
                source_type="failure_drilldown", source_id=drilldown_id)

            self.assertEqual(remediation_plan.source_type, "remediation_plan")
            self.assertIn("quality_gate", {p.target_type for p in remediation_plan.proposals})
            self.assertEqual(failure_plan.source_type, "failure_drilldown")
            self.assertIn("quality_gate", {p.target_type for p in failure_plan.proposals})

    def test_default_source_prefers_latest_action_review(self):
        import loop_improvement

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "improvements.db"))
            self.addCleanup(conn.close)
            _failure_drilldown(conn)
            _remediation_plan(conn, None)
            review_id = _action_review(conn)

            plan = loop_improvement.LoopImprovementEngine(conn).build_plan()

            self.assertEqual(plan.source_type, "action_review")
            self.assertEqual(plan.source_id, review_id)

    def test_filtering_persistence_status_and_markdown_path_safety(self):
        import loop_improvement

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "improvements.db"))
            self.addCleanup(conn.close)
            loop_improvement.REPORTS_DIR = os.path.join(td, "improvement_reports")
            review_id = _action_review(conn)
            engine = loop_improvement.LoopImprovementEngine(conn)

            plan = engine.build_plan(
                source_type="action_review",
                source_id=review_id,
                priority="high",
                target_type="quality_gate",
            )
            plan_id = engine.save_plan(plan, {"priority": "high", "target_type": "quality_gate"})
            report = engine.save_markdown_report(plan_id, plan)
            proposals = database.list_loop_improvement_proposals(
                conn, priority="high", target_type="quality_gate")
            database.update_loop_improvement_proposal_status(conn, proposals[0]["id"], "accepted")
            stored_proposal = database.get_loop_improvement_proposal(conn, proposals[0]["id"])

            self.assertEqual(plan.total_proposals, 1)
            self.assertEqual(database.get_loop_improvement_plan(conn, plan_id)["id"], plan_id)
            self.assertEqual(stored_proposal["status"], "accepted")
            self.assertTrue(os.path.exists(report.report_path))
            base = os.path.realpath(loop_improvement.REPORTS_DIR)
            self.assertTrue(os.path.realpath(report.report_path).startswith(base + os.sep))
            self.assertEqual(
                database.get_loop_improvement_markdown_report(conn, plan_id)["report_format"],
                "markdown",
            )

    def test_improvements_do_not_create_loops_commands_or_external_jobs(self):
        import loop_improvement

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "improvements.db"))
            self.addCleanup(conn.close)
            loop_improvement.REPORTS_DIR = os.path.join(td, "improvement_reports")
            review_id = _action_review(conn)
            before_loops = _count(conn, "loops")
            before_commands = _count(conn, "command_results")
            before_jobs = _count(conn, "external_agent_jobs")
            engine = loop_improvement.LoopImprovementEngine(conn)

            plan = engine.build_plan(source_type="action_review", source_id=review_id)
            plan_id = engine.save_plan(plan, {})
            engine.save_markdown_report(plan_id, plan)

            self.assertEqual(_count(conn, "loops"), before_loops)
            self.assertEqual(_count(conn, "command_results"), before_commands)
            self.assertEqual(_count(conn, "external_agent_jobs"), before_jobs)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _action_review(conn):
    items = [
        observatory_action_review.ObservatoryActionReviewItem(
            action_id=1,
            source_plan_id=1,
            title="Fix repeated quality gate failures",
            category="testing",
            priority="high",
            status="open",
            risk_level="medium",
            effort_level="medium",
            affected_loop_ids=[101, 102],
            suggested_command="python3 main.py --observatory-failures --category quality_gate_failed",
            problem_summary="Repeated quality gate failures are blocking loops.",
            recommended_action="Tune the failing quality gate and its evidence.",
        ),
        observatory_action_review.ObservatoryActionReviewItem(
            action_id=2,
            source_plan_id=1,
            title="Review waiting external jobs",
            category="external_agent_queue",
            priority="high",
            status="open",
            risk_level="medium",
            effort_level="low",
            affected_loop_ids=[201],
            suggested_command="python3 main.py --external-health",
            problem_summary="External jobs are waiting too long.",
            recommended_action="Improve the external handoff flow.",
        ),
        observatory_action_review.ObservatoryActionReviewItem(
            action_id=3,
            source_plan_id=1,
            title="Document cleanup workflow",
            category="documentation",
            priority="low",
            status="open",
            risk_level="low",
            effort_level="low",
            affected_loop_ids=[],
            suggested_command="python3 main.py --reports",
            problem_summary="Documentation should explain the cleanup command.",
            recommended_action="Update README examples.",
        ),
    ]
    return database.save_observatory_action_review(
        conn,
        "2026-06-28T21:00:00",
        "{}",
        "category",
        len(items),
        json.dumps([observatory_action_review.item_to_dict(i) for i in items], sort_keys=True),
        "[]",
        "[]",
        "[]",
    )


def _remediation_plan(conn, source_id):
    item = observatory_remediation.RemediationPlanItem(
        id=1,
        priority="high",
        category="testing",
        title="Fix repeated quality gate failures",
        problem_summary="Quality gate failures recur in Stage 4 metadata.",
        evidence="count=3 loop_ids=[301, 302, 303]",
        affected_loop_ids=[301, 302, 303],
        recommended_action="Review the quality gate criteria.",
        suggested_command="python3 main.py --observatory-failures --category quality_gate_failed",
        expected_impact="Reduce blocked loops.",
        risk_level="medium",
        effort_level="medium",
    )
    return database.save_observatory_remediation_plan(
        conn,
        "2026-06-28T21:01:00",
        "failure_drilldown",
        source_id,
        "{}",
        json.dumps({"summary": "remediation", "next_steps": []}, sort_keys=True),
        json.dumps([observatory_remediation.item_to_dict(item)], sort_keys=True),
        1,
        0,
        1,
        0,
        0,
    )


def _failure_drilldown(conn):
    item = observatory_drilldown.FailureDrilldownItem(
        loop_id=401,
        created_at="2026-06-28T21:02:00",
        task_preview="fix tests",
        loop_type="test_fix",
        workspace_name="default",
        status="FAILED",
        stop_reason="quality gate failed",
        failure_category="quality_gate_failed",
        root_cause_hint="failed quality gate: files_written",
        agent_role="reviewer",
        agent_name="reviewer",
        model="local",
        failed_quality_gates=["files_written"],
        recommended_action="python3 main.py --report 401",
    )
    cluster = observatory_drilldown.FailureCluster(
        cluster_key="quality_gate_failed",
        cluster_type="category",
        count=1,
        loop_ids=[401],
        representative_reason="failed quality gate: files_written",
        recommended_action="python3 main.py --report 401",
    )
    return database.save_observatory_failure_drilldown(
        conn,
        "2026-06-28T21:02:00",
        "{}",
        "category",
        1,
        json.dumps([observatory_drilldown.item_to_dict(item)], sort_keys=True),
        json.dumps([observatory_drilldown.cluster_to_dict(cluster)], sort_keys=True),
        "[]",
    )


if __name__ == "__main__":
    unittest.main()
