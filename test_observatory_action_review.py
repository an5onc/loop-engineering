import json
import os
import tempfile
import unittest

import database


class ObservatoryActionReviewTests(unittest.TestCase):
    def test_scores_by_priority_and_category(self):
        import observatory_action_review

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "review.db"))
            self.addCleanup(conn.close)
            safety_id = _action(conn, "urgent", "safety", "open", "high", "medium")
            _action(conn, "low", "documentation", "open", "low", "low")

            report = observatory_action_review.ObservatoryActionReviewEngine(conn).build_report(
                status="open")

            self.assertEqual(report.top_actions[0].action_id, safety_id)
            self.assertGreater(report.top_actions[0].review_score,
                               report.top_actions[1].review_score)
            self.assertIn("safety", report.top_actions[0].rationale)

    def test_completed_and_dismissed_rank_lower_when_included(self):
        import observatory_action_review

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "review.db"))
            self.addCleanup(conn.close)
            open_id = _action(conn, "high", "reliability", "open", "medium", "low")
            completed_id = _action(conn, "urgent", "safety", "completed", "high", "medium")

            report = observatory_action_review.ObservatoryActionReviewEngine(conn).build_report(
                status=None)
            scores = {item.action_id: item.review_score for item in report.top_actions}

            self.assertGreater(scores[open_id], scores[completed_id])

    def test_group_by_category_priority_status_and_risk(self):
        import observatory_action_review

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "review.db"))
            self.addCleanup(conn.close)
            _action(conn, "high", "testing", "open", "medium", "medium")
            _action(conn, "low", "documentation", "blocked", "low", "low")
            engine = observatory_action_review.ObservatoryActionReviewEngine(conn)

            self.assertEqual(engine.build_report(group_by="category").groups[0].group_type,
                             "category")
            self.assertEqual(engine.build_report(group_by="priority").groups[0].group_type,
                             "priority")
            self.assertEqual(engine.build_report(status=None, group_by="status").groups[0].group_type,
                             "status")
            self.assertEqual(engine.build_report(group_by="risk").groups[0].group_type,
                             "risk")

    def test_review_persistence_and_markdown_path_safety(self):
        import observatory_action_review

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "review.db"))
            self.addCleanup(conn.close)
            observatory_action_review.REPORTS_DIR = os.path.join(td, "review_reports")
            _action(conn, "high", "testing", "open", "medium", "medium")
            engine = observatory_action_review.ObservatoryActionReviewEngine(conn)
            report = engine.build_report()
            review_id = engine.save_review(report, group_by="category")
            md = engine.save_markdown_report(review_id, report)

            stored = database.get_observatory_action_review(conn, review_id)
            self.assertEqual(stored["id"], review_id)
            self.assertEqual(len(database.list_observatory_action_reviews(conn)), 1)
            self.assertTrue(os.path.exists(md.report_path))
            base = os.path.realpath(observatory_action_review.REPORTS_DIR)
            self.assertTrue(os.path.realpath(md.report_path).startswith(base + os.sep))

    def test_review_does_not_create_loops_or_command_results(self):
        import observatory_action_review

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "review.db"))
            self.addCleanup(conn.close)
            observatory_action_review.REPORTS_DIR = os.path.join(td, "review_reports")
            _action(conn, "high", "testing", "open", "medium", "medium",
                    command="python3 -c 'print(1)'")
            before_loops = _count(conn, "loops")
            before_commands = _count(conn, "command_results")
            engine = observatory_action_review.ObservatoryActionReviewEngine(conn)

            report = engine.build_report()
            review_id = engine.save_review(report, group_by="category")
            engine.save_markdown_report(review_id, report)

            self.assertEqual(_count(conn, "loops"), before_loops)
            self.assertEqual(_count(conn, "command_results"), before_commands)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _action(conn, priority, category, status, risk, effort,
            command="python3 main.py --observatory-actions"):
    return database.save_observatory_action_item(
        conn,
        1,
        _count(conn, "observatory_action_items") + 1,
        f"{category} action",
        category,
        priority,
        status,
        command,
        f"{category} problem",
        "Review manually",
        json.dumps([10, 11], sort_keys=True),
        json.dumps([3], sort_keys=True),
        risk,
        effort,
        "",
    )


if __name__ == "__main__":
    unittest.main()
