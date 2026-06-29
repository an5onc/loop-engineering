import json
import os
import tempfile
import unittest

import database


class LoopImprovementStage5AuditTests(unittest.TestCase):
    def test_audit_report_generation_and_stage6_readiness(self):
        import loop_improvement_stage5_audit as stage5

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "stage5_audit.db"))
            self.addCleanup(conn.close)
            _seed_full_pipeline(conn, td)

            report = stage5.LoopImprovementStage5AuditEngine(conn).build_report()

            self.assertGreaterEqual(report.total_checks, 30)
            self.assertEqual(
                report.total_checks,
                report.passed_checks + report.warning_checks + report.failed_checks,
            )
            self.assertEqual(report.overall_status, "PASS")
            self.assertEqual(report.stage6_readiness["ready_text"], "yes")
            self.assertIn(
                "approval",
                " ".join(report.stage6_readiness["required_safety_controls"]).lower(),
            )
            self.assertEqual(
                {
                    "improvement_engine",
                    "proposal_review",
                    "action_conversion",
                    "implementation_handoff",
                    "handoff_review",
                    "safety_baseline",
                    "stage6_readiness",
                },
                {section.name for section in report.sections},
            )

    def test_section_and_overall_status_aggregation(self):
        import loop_improvement_stage5_audit as stage5

        passing = stage5.Stage5AuditSection(
            name="passing",
            status="PASS",
            checks=[stage5.Stage5AuditCheck("ok", "cat", "PASS", "ok", "", "")],
            summary="ok",
        )
        warning = stage5.Stage5AuditSection(
            name="warning",
            status="WARN",
            checks=[stage5.Stage5AuditCheck("warn", "cat", "WARN", "warn", "", "")],
            summary="warn",
        )
        failing = stage5.Stage5AuditSection(
            name="failing",
            status="FAIL",
            checks=[stage5.Stage5AuditCheck("fail", "cat", "FAIL", "fail", "", "")],
            summary="fail",
        )

        self.assertEqual(stage5.aggregate_overall_status([passing]), "PASS")
        self.assertEqual(
            stage5.aggregate_overall_status([passing, warning]),
            "PASS WITH WARNINGS",
        )
        self.assertEqual(
            stage5.aggregate_overall_status([passing, warning, failing]), "FAIL")

    def test_stage6_readiness_blocks_on_failed_safety_check(self):
        import loop_improvement_stage5_audit as stage5

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "stage5_audit.db"))
            self.addCleanup(conn.close)
            _seed_full_pipeline(conn, td)
            conn.execute(
                "UPDATE loop_improvement_proposals SET status='auto_applied'")
            conn.commit()

            report = stage5.LoopImprovementStage5AuditEngine(conn).build_report()

            self.assertEqual(report.overall_status, "FAIL")
            self.assertEqual(report.stage6_readiness["ready_text"], "no")
            self.assertTrue(report.stage6_readiness["blockers"])

    def test_audit_persistence_and_markdown_path_safety(self):
        import loop_improvement_stage5_audit as stage5

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "stage5_audit.db"))
            self.addCleanup(conn.close)
            _seed_full_pipeline(conn, td)
            old_reports_dir = stage5.REPORTS_DIR
            stage5.REPORTS_DIR = os.path.join(td, "reports")
            self.addCleanup(setattr, stage5, "REPORTS_DIR", old_reports_dir)

            engine = stage5.LoopImprovementStage5AuditEngine(conn)
            report = engine.build_report()
            audit_id = engine.save_audit(report)
            markdown = engine.save_markdown_report(audit_id, report)
            stored = database.get_loop_improvement_stage5_audit(conn, audit_id)
            stored_report = stage5.report_from_row(stored)

            self.assertEqual(stored["id"], audit_id)
            self.assertEqual(stored_report.overall_status, report.overall_status)
            self.assertTrue(stage5.is_markdown_report_path(markdown.report_path))
            self.assertTrue(os.path.realpath(markdown.report_path).startswith(
                os.path.realpath(stage5.REPORTS_DIR) + os.sep))
            self.assertTrue(os.path.isfile(markdown.report_path))
            self.assertEqual(
                database.get_loop_improvement_stage5_audit_markdown_report(
                    conn, audit_id)["report_format"],
                "markdown",
            )

    def test_audit_does_not_create_or_mutate_runtime_or_improvement_records(self):
        import loop_improvement_stage5_audit as stage5

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "stage5_audit.db"))
            self.addCleanup(conn.close)
            ids = _seed_full_pipeline(conn, td)
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
            before_status = database.get_loop_improvement_proposal(
                conn, ids["proposal_id"])["status"]
            before_action_status = database.get_loop_improvement_action_item(
                conn, ids["action_id"])["status"]
            before_handoff_status = database.get_loop_improvement_handoff(
                conn, ids["handoff_id"])["status"]

            report = stage5.LoopImprovementStage5AuditEngine(conn).build_report()
            stage5.LoopImprovementStage5AuditEngine(conn).save_audit(report)

            after_counts = {
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
            self.assertEqual(after_counts, before_counts)
            self.assertEqual(
                database.get_loop_improvement_proposal(conn, ids["proposal_id"])["status"],
                before_status,
            )
            self.assertEqual(
                database.get_loop_improvement_action_item(conn, ids["action_id"])["status"],
                before_action_status,
            )
            self.assertEqual(
                database.get_loop_improvement_handoff(conn, ids["handoff_id"])["status"],
                before_handoff_status,
            )


def _seed_full_pipeline(conn, tmpdir):
    plan_id = database.save_loop_improvement_plan(
        conn,
        "2026-06-29T12:00:00",
        "action_review",
        1,
        "{}",
        json.dumps({"summary": "stage 5 audit seed"}, sort_keys=True),
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
        "proposed",
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
        "",
    )
    database.save_loop_improvement_action_batch(
        conn,
        review_id,
        "2026-06-29T12:02:00",
        "{}",
        1,
        1,
        0,
        json.dumps([action_id]),
    )
    database.save_loop_improvement_action_event(
        conn, action_id, "created", None, "open", "{}")
    packet_dir = os.path.join(tmpdir, "loop_improvement_handoff_packets")
    os.makedirs(packet_dir, exist_ok=True)
    packet_path = os.path.realpath(os.path.join(packet_dir, "packet.md"))
    with open(packet_path, "w", encoding="utf-8") as fh:
        fh.write("packet metadata")
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
        packet_path=packet_path,
    )
    database.save_loop_improvement_handoff_event(
        conn, handoff_id, action_id, "created", "{}")
    database.save_loop_improvement_handoff_packet(
        conn, handoff_id, action_id, packet_path, "markdown", "abc", 15)
    database.save_loop_improvement_handoff_review(
        conn,
        "2026-06-29T12:03:00",
        "{}",
        "status",
        1,
        "[]",
        "[]",
        "[]",
        "[]",
    )
    return {
        "plan_id": plan_id,
        "proposal_id": proposal_id,
        "review_id": review_id,
        "action_id": action_id,
        "handoff_id": handoff_id,
    }


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


if __name__ == "__main__":
    unittest.main()
