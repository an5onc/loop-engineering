import json
import os
import tempfile
import unittest

import database


class ObservatoryTrendTests(unittest.TestCase):
    def test_trend_calculation_with_two_snapshots_and_percent_change(self):
        import observatory_trends

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "trends.db"))
            self.addCleanup(conn.close)
            _snapshot(conn, "2026-06-27T10:00:00", blocked_loops=2,
                      approved_loops=4, alert_count=1)
            _snapshot(conn, "2026-06-27T11:00:00", blocked_loops=5,
                      approved_loops=8, alert_count=3)

            report = observatory_trends.ObservatoryTrendEngine(conn).build_report()
            by_metric = {t.metric_name: t for t in report.trends}

            blocked = by_metric["blocked_loops"]
            self.assertEqual(report.snapshot_count, 2)
            self.assertEqual(blocked.first_value, 2)
            self.assertEqual(blocked.last_value, 5)
            self.assertEqual(blocked.delta, 3)
            self.assertEqual(blocked.percent_change, 150.0)
            self.assertEqual(blocked.direction, "up")
            self.assertIn("negative", blocked.interpretation)
            self.assertTrue(any("blocked loops increased" in a for a in report.alerts))

    def test_insufficient_data_behavior(self):
        import observatory_trends

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "trends.db"))
            self.addCleanup(conn.close)
            _snapshot(conn, "2026-06-27T10:00:00", blocked_loops=2)

            report = observatory_trends.ObservatoryTrendEngine(conn).build_report()

            self.assertEqual(report.snapshot_count, 1)
            self.assertTrue(all(t.direction == "insufficient_data"
                                for t in report.trends))
            self.assertTrue(any("not enough snapshots" in a for a in report.alerts))

    def test_metric_filter_behavior(self):
        import observatory_trends

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "trends.db"))
            self.addCleanup(conn.close)
            _snapshot(conn, "2026-06-27T10:00:00", blocked_loops=2,
                      approved_loops=4)
            _snapshot(conn, "2026-06-27T11:00:00", blocked_loops=5,
                      approved_loops=8)

            report = observatory_trends.ObservatoryTrendEngine(conn).build_report(
                metric="blocked_loops")

            self.assertEqual([t.metric_name for t in report.trends], ["blocked_loops"])

    def test_trend_report_persistence_and_markdown_path_safety(self):
        import observatory_trends

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "trends.db"))
            self.addCleanup(conn.close)
            observatory_trends.REPORTS_DIR = os.path.join(td, "trend_reports")
            _snapshot(conn, "2026-06-27T10:00:00", blocked_loops=2)
            _snapshot(conn, "2026-06-27T11:00:00", blocked_loops=5)
            engine = observatory_trends.ObservatoryTrendEngine(conn)

            report = engine.build_report()
            report_id = engine.save_trend_report(report, {"limit": 10})
            md = engine.save_markdown_report(report_id, report)
            stored = database.get_observatory_trend_report(conn, report_id)

            self.assertEqual(stored["id"], report_id)
            self.assertEqual(len(database.list_observatory_trend_reports(conn)), 1)
            self.assertTrue(os.path.exists(md.report_path))
            base = os.path.realpath(observatory_trends.REPORTS_DIR)
            self.assertTrue(os.path.realpath(md.report_path).startswith(base + os.sep))
            self.assertEqual(_count(conn, "observatory_trend_markdown_reports"), 1)

    def test_trend_generation_only_adds_trend_metadata(self):
        import observatory_trends

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "trends.db"))
            self.addCleanup(conn.close)
            observatory_trends.REPORTS_DIR = os.path.join(td, "trend_reports")
            _snapshot(conn, "2026-06-27T10:00:00", blocked_loops=2)
            _snapshot(conn, "2026-06-27T11:00:00", blocked_loops=5)
            before_loops = _count(conn, "loops")
            before_commands = _count(conn, "command_results")
            engine = observatory_trends.ObservatoryTrendEngine(conn)

            report = engine.build_report()
            report_id = engine.save_trend_report(report, {"limit": 10})
            engine.save_markdown_report(report_id, report)

            self.assertEqual(_count(conn, "loops"), before_loops)
            self.assertEqual(_count(conn, "command_results"), before_commands)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _snapshot(conn, generated_at, **overrides):
    summary = {
        "generated_at": generated_at,
        "time_window": {"name": "all", "start_at": None, "end_at": generated_at},
        "total_loops": 10,
        "approved_loops": overrides.get("approved_loops", 4),
        "failed_loops": overrides.get("failed_loops", 1),
        "blocked_loops": overrides.get("blocked_loops", 2),
        "needs_human_loops": overrides.get("needs_human_loops", 0),
        "paused_external_loops": overrides.get("paused_external_loops", 0),
        "total_external_jobs": overrides.get("total_external_jobs", 3),
        "waiting_external_jobs": overrides.get("waiting_external_jobs", 1),
        "blocked_external_jobs": overrides.get("blocked_external_jobs", 0),
        "failed_external_jobs": overrides.get("failed_external_jobs", 0),
        "total_reports": overrides.get("total_reports", 5),
        "total_approvals": overrides.get("total_approvals", 3),
        "declined_approvals": overrides.get("declined_approvals", 1),
        "quality_gate_failures": overrides.get("quality_gate_failures", 2),
        "stop_condition_triggers": overrides.get("stop_condition_triggers", 3),
        "top_failure_reasons": [],
        "top_loop_types": [],
        "top_agents": [],
        "top_workspaces": [],
        "external_job_health": {},
        "alerts": [],
    }
    return database.save_observatory_snapshot(
        conn,
        generated_at,
        "all",
        json.dumps({"window": "all", "workspace": None}, sort_keys=True),
        json.dumps(summary, sort_keys=True),
        overrides.get("alert_count", 0),
        overrides.get("critical_alert_count", 0),
        overrides.get("warning_alert_count", 0),
    )


if __name__ == "__main__":
    unittest.main()
