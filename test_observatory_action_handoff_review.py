import json
import os
import tempfile
import unittest

import database


class ObservatoryActionHandoffReviewTests(unittest.TestCase):
    def test_classifies_dry_run_and_confirmed_handoffs(self):
        import observatory_action_handoff_review as review

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "handoff_review.db"))
            self.addCleanup(conn.close)
            action_id = _action(conn)
            dry_id = _handoff(conn, action_id, "dry_run_plan", "DRY_RUN", dry_run=True)
            loop_id = _handoff(
                conn, action_id, "loop_task", "LOOP_CREATED",
                created_loop_id=12, dry_run=False)
            ext_id = _handoff(
                conn, action_id, "external_agent_job", "EXTERNAL_JOB_CREATED",
                created_external_job_id=34, dry_run=False)

            report = review.ActionHandoffReviewEngine(conn).build_report(limit=10)
            by_id = {item.handoff_id: item for item in report.items}

            self.assertEqual(by_id[dry_id].review_status, "safe_dry_run")
            self.assertEqual(by_id[loop_id].review_status, "confirmed_loop_created")
            self.assertEqual(by_id[ext_id].review_status, "confirmed_external_job_created")

    def test_classifies_missing_task_and_unsafe_command_as_suspicious(self):
        import observatory_action_handoff_review as review

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "handoff_review.db"))
            self.addCleanup(conn.close)
            action_id = _action(conn)
            empty_id = _handoff(conn, action_id, "dry_run_plan", "DRY_RUN",
                                generated_task="")
            unsafe_id = _handoff(
                conn, action_id, "dry_run_plan", "DRY_RUN",
                suggested_command="python3 main.py --handoff-observatory-action 1; rm -rf /")

            report = review.ActionHandoffReviewEngine(conn).build_report(limit=10)
            by_id = {item.handoff_id: item for item in report.items}

            self.assertEqual(by_id[empty_id].review_status, "suspicious")
            self.assertEqual(by_id[unsafe_id].review_status, "suspicious")

    def test_grouping_filtering_persistence_and_markdown(self):
        import observatory_action_handoff_review as review

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "handoff_review.db"))
            self.addCleanup(conn.close)
            old_reports_dir = review.REPORTS_DIR
            review.REPORTS_DIR = os.path.join(td, "reports")
            self.addCleanup(setattr, review, "REPORTS_DIR", old_reports_dir)
            action_id = _action(conn)
            _handoff(conn, action_id, "dry_run_plan", "DRY_RUN", dry_run=True)
            _handoff(conn, action_id, "external_agent_job", "DRY_RUN", dry_run=True)

            engine = review.ActionHandoffReviewEngine(conn)
            report = engine.build_report(handoff_type="external_agent_job",
                                         group_by="type", limit=10)
            review_id = engine.save_review(report, group_by="type")
            md = engine.save_markdown_report(review_id, report)
            stored = database.get_observatory_action_handoff_review(conn, review_id)

            self.assertEqual(report.total_handoffs_reviewed, 1)
            self.assertEqual(report.groups[0].group_type, "type")
            self.assertEqual(stored["id"], review_id)
            self.assertTrue(review.is_markdown_report_path(md.report_path))
            self.assertTrue(os.path.realpath(md.report_path).startswith(
                os.path.realpath(review.REPORTS_DIR) + os.sep))
            self.assertTrue(os.path.isfile(md.report_path))

    def test_review_does_not_create_loops_jobs_or_command_results(self):
        import observatory_action_handoff_review as review

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "handoff_review.db"))
            self.addCleanup(conn.close)
            action_id = _action(conn)
            _handoff(conn, action_id, "dry_run_plan", "DRY_RUN", dry_run=True)
            before = {table: _count(conn, table)
                      for table in ("loops", "external_agent_jobs", "command_results")}

            report = review.ActionHandoffReviewEngine(conn).build_report(limit=10)
            review.ActionHandoffReviewEngine(conn).save_review(report)

            after = {table: _count(conn, table)
                     for table in ("loops", "external_agent_jobs", "command_results")}
            self.assertEqual(after, before)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _action(conn):
    return database.save_observatory_action_item(
        conn,
        1,
        1,
        "Review handoff safety",
        "safety",
        "high",
        "open",
        "python3 main.py --observatory-action-handoff-review",
        "Handoffs need review.",
        "Inspect handoff metadata.",
        json.dumps([1], sort_keys=True),
        json.dumps([], sort_keys=True),
        "medium",
        "low",
        "",
    )


def _handoff(conn, action_id, handoff_type, status, generated_task=None,
             target_workspace="default", external_coder="codex",
             suggested_command=None, created_loop_id=None,
             created_external_job_id=None, dry_run=True):
    task = ("Investigate and remediate the following Loop Engineering issue."
            if generated_task is None else generated_task)
    command = (suggested_command if suggested_command is not None
               else f"python3 main.py --handoff-observatory-action {action_id}")
    return database.save_observatory_action_handoff(
        conn,
        action_id,
        handoff_type,
        task,
        "code_build",
        target_workspace,
        external_coder,
        command,
        json.dumps(["No command execution."], sort_keys=True),
        status,
        created_loop_id=created_loop_id,
        created_external_job_id=created_external_job_id,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    unittest.main()
