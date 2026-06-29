import json
import os
import tempfile
import unittest

import database


class LoopImprovementHandoffReviewTests(unittest.TestCase):
    def test_classifies_handoff_statuses(self):
        import loop_improvement_handoff_review

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "review.db"))
            self.addCleanup(conn.close)
            packet_dir = os.path.join(td, "packets")
            loop_improvement_handoff_review.PACKETS_DIR = packet_dir
            action_id = _action(conn)
            safe_packet = os.path.realpath(os.path.join(packet_dir, "packet.md"))
            os.makedirs(packet_dir, exist_ok=True)
            with open(safe_packet, "w", encoding="utf-8") as fh:
                fh.write("packet")
            ids = {
                "dry": _handoff(conn, action_id, "dry_run_plan"),
                "packet": _handoff(conn, action_id, "implementation_packet",
                                   packet_path=safe_packet, status="PACKET_CREATED"),
                "loop": _handoff(conn, action_id, "loop_task", created_loop_id=42,
                                 dry_run=False, status="LOOP_CREATED"),
                "job": _handoff(conn, action_id, "external_agent_job",
                                created_external_job_id=77, dry_run=False,
                                status="EXTERNAL_JOB_CREATED"),
                "missing_task": _handoff(conn, action_id, "dry_run_plan",
                                         generated_task=""),
                "bad_packet": _handoff(conn, action_id, "implementation_packet",
                                       packet_path="/tmp/escaped.md",
                                       status="PACKET_CREATED"),
            }

            report = loop_improvement_handoff_review.LoopImprovementHandoffReviewEngine(
                conn).build_report(status=None)
            statuses = {item.handoff_id: item.review_status for item in report.items}
            decisions = {
                item.handoff_id: item.recommended_decision for item in report.items
            }

            self.assertEqual(statuses[ids["dry"]], "safe_dry_run")
            self.assertEqual(statuses[ids["packet"]], "safe_packet")
            self.assertEqual(statuses[ids["loop"]], "confirmed_loop_created")
            self.assertEqual(statuses[ids["job"]], "confirmed_external_job_created")
            self.assertEqual(statuses[ids["missing_task"]], "suspicious")
            self.assertEqual(statuses[ids["bad_packet"]], "suspicious")
            self.assertEqual(decisions[ids["loop"]], "archive")
            self.assertEqual(decisions[ids["job"]], "archive")

    def test_grouping_filters_persistence_and_markdown_path_safety(self):
        import loop_improvement_handoff_review

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "review.db"))
            self.addCleanup(conn.close)
            loop_improvement_handoff_review.REPORTS_DIR = os.path.join(td, "reports")
            action_id = _action(conn, target_type="quality_gate")
            _handoff(conn, action_id, "dry_run_plan",
                     implementation_scope="quality_gate_update")
            _handoff(conn, action_id, "loop_task",
                     implementation_scope="quality_gate_update")
            engine = loop_improvement_handoff_review.LoopImprovementHandoffReviewEngine(conn)

            by_status = engine.build_report(group_by="status")
            by_type = engine.build_report(group_by="type")
            by_scope = engine.build_report(group_by="implementation_scope")
            by_target = engine.build_report(group_by="target_type")
            filtered = engine.build_report(
                handoff_type="loop_task", implementation_scope="quality_gate_update",
                target_type="quality_gate")
            review_id = engine.save_review(filtered, group_by="status")
            md = engine.save_markdown_report(review_id, filtered)

            self.assertEqual(by_status.groups[0].group_type, "status")
            self.assertEqual(by_type.groups[0].group_type, "type")
            self.assertEqual(by_scope.groups[0].group_type, "implementation_scope")
            self.assertEqual(by_target.groups[0].group_type, "target_type")
            self.assertEqual(filtered.total_handoffs_reviewed, 1)
            self.assertEqual(database.get_loop_improvement_handoff_review(conn, review_id)["id"],
                             review_id)
            self.assertTrue(os.path.exists(md.report_path))
            base = os.path.realpath(loop_improvement_handoff_review.REPORTS_DIR)
            self.assertTrue(os.path.realpath(md.report_path).startswith(base + os.sep))
            self.assertEqual(
                database.get_loop_improvement_handoff_review_markdown_report(
                    conn, review_id)["report_format"],
                "markdown",
            )

    def test_review_does_not_create_loops_jobs_or_command_results(self):
        import loop_improvement_handoff_review

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "review.db"))
            self.addCleanup(conn.close)
            action_id = _action(conn)
            _handoff(conn, action_id, "dry_run_plan")
            before_loops = _count(conn, "loops")
            before_jobs = _count(conn, "external_agent_jobs")
            before_commands = _count(conn, "command_results")

            report = loop_improvement_handoff_review.LoopImprovementHandoffReviewEngine(
                conn).build_report()

            self.assertEqual(report.total_handoffs_reviewed, 1)
            self.assertEqual(_count(conn, "loops"), before_loops)
            self.assertEqual(_count(conn, "external_agent_jobs"), before_jobs)
            self.assertEqual(_count(conn, "command_results"), before_commands)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _action(conn, target_type="quality_gate"):
    return database.save_loop_improvement_action_item(
        conn,
        1,
        1,
        1,
        target_type,
        f"{target_type}_target",
        f"{target_type} action",
        "high",
        "open",
        "medium",
        "low",
        "problem",
        "change",
        "benefit",
        "accept",
        "python3 main.py --loop-improvement-proposal 1",
        "[]",
        "[]",
        "[]",
        "",
    )


def _handoff(conn, action_id, handoff_type, generated_task="task",
             implementation_scope="quality_gate_update", target_type="quality_gate",
             target_workspace="default", external_coder="codex", status="DRY_RUN",
             created_loop_id=None, created_external_job_id=None, dry_run=True,
             packet_path=None, suggested_command=None):
    return database.save_loop_improvement_handoff(
        conn,
        action_id,
        1,
        1,
        1,
        handoff_type,
        generated_task,
        implementation_scope,
        target_type,
        f"{target_type}_target",
        "code_build",
        target_workspace,
        external_coder,
        suggested_command or (
            f"python3 main.py --handoff-loop-improvement-action {action_id}"
        ),
        json.dumps(["safe"], sort_keys=True),
        status,
        created_loop_id=created_loop_id,
        created_external_job_id=created_external_job_id,
        dry_run=dry_run,
        packet_path=packet_path,
    )


if __name__ == "__main__":
    unittest.main()
