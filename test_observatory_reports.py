import json
import os
import tempfile
import unittest

import database


class ObservatoryReportTests(unittest.TestCase):
    def test_report_generation_from_snapshot_stays_inside_reports_dir(self):
        import observatory_reports

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "obs.db"))
            observatory_reports.REPORTS_DIR = os.path.join(td, "observatory_reports")
            snapshot_id = _snapshot(conn)

            report = observatory_reports.ObservatoryReportGenerator(conn).generate_report(
                snapshot_id)

            base = os.path.realpath(observatory_reports.REPORTS_DIR)
            target = os.path.realpath(report.report_path)
            self.assertTrue(target.startswith(base + os.sep))
            self.assertTrue(os.path.exists(report.report_path))
            self.assertEqual(report.report_format, "markdown")
            self.assertGreater(report.bytes_written, 0)
            with open(report.report_path, "r", encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("# Loop Engineering Observatory Report", content)
            self.assertIn("## Summary", content)
            self.assertIn("- Snapshot ID: 1", content)
            self.assertIn("## Safety Notes", content)

    def test_report_metadata_persists_and_missing_file_regenerates(self):
        import observatory_reports

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "obs.db"))
            observatory_reports.REPORTS_DIR = os.path.join(td, "observatory_reports")
            snapshot_id = _snapshot(conn)
            gen = observatory_reports.ObservatoryReportGenerator(conn)
            first = gen.generate_report(snapshot_id)
            os.remove(first.report_path)

            second = gen.generate_report(snapshot_id)
            stored = database.get_observatory_report(conn, snapshot_id)

            self.assertTrue(os.path.exists(second.report_path))
            self.assertEqual(stored["snapshot_id"], snapshot_id)
            self.assertEqual(stored["report_path"], second.report_path)
            self.assertEqual(len(database.list_observatory_reports(conn)), 2)

    def test_invalid_snapshot_id_fails_clearly(self):
        import observatory_reports

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "obs.db"))
            observatory_reports.REPORTS_DIR = os.path.join(td, "observatory_reports")

            with self.assertRaisesRegex(ValueError, "no observatory snapshot 999"):
                observatory_reports.ObservatoryReportGenerator(conn).generate_report(999)

    def test_report_generation_only_adds_report_metadata(self):
        import observatory_reports

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "obs.db"))
            observatory_reports.REPORTS_DIR = os.path.join(td, "observatory_reports")
            snapshot_id = _snapshot(conn)
            before_loops = _count(conn, "loops")
            before_commands = _count(conn, "command_results")

            observatory_reports.ObservatoryReportGenerator(conn).generate_report(snapshot_id)

            self.assertEqual(_count(conn, "loops"), before_loops)
            self.assertEqual(_count(conn, "command_results"), before_commands)
            self.assertEqual(_count(conn, "observatory_reports"), 1)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _snapshot(conn):
    summary = {
        "generated_at": "2026-06-27T12:00:00",
        "time_window": {
            "name": "24h",
            "start_at": "2026-06-26T12:00:00",
            "end_at": "2026-06-27T12:00:00",
        },
        "total_loops": 5,
        "approved_loops": 3,
        "failed_loops": 1,
        "blocked_loops": 1,
        "needs_human_loops": 0,
        "paused_external_loops": 1,
        "total_external_jobs": 2,
        "waiting_external_jobs": 1,
        "completed_external_jobs": 0,
        "blocked_external_jobs": 0,
        "failed_external_jobs": 1,
        "total_reports": 4,
        "total_approvals": 2,
        "declined_approvals": 1,
        "quality_gate_failures": 6,
        "stop_condition_triggers": 7,
        "top_loop_types": [
            {"loop_type": "code_build", "count": 4,
             "approval_rate": 75.0, "failure_rate": 25.0}
        ],
        "top_agents": [
            {"agent": "claude", "count": 2, "success_rate": 50.0}
        ],
        "top_workspaces": [
            {"workspace": "default", "loop_count": 5, "blocked_count": 1}
        ],
        "top_failure_reasons": [
            {"stop_reason": "max_retries_reached", "count": 1}
        ],
        "external_job_health": {
            "waiting": 1,
            "stale": 1,
            "needs_attention": 1,
            "archived": 0,
            "cancelled": 0,
        },
        "alerts": [
            {
                "severity": "warning",
                "alert_type": "quality_gate_failures",
                "message": "6 quality gate failure(s)",
                "recommended_action": "python3 main.py --history --limit 10",
                "details_json": "{\"quality_gate_failures\": 6}",
            }
        ],
    }
    return database.save_observatory_snapshot(
        conn,
        summary["generated_at"],
        "24h",
        json.dumps({"window": "24h", "workspace": None}, sort_keys=True),
        json.dumps(summary, sort_keys=True),
        1,
        0,
        1,
    )


if __name__ == "__main__":
    unittest.main()
