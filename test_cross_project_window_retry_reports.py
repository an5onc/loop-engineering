import json
import os
import tempfile
import unittest

import database
from test_cross_project_execution_windows import _seed_orchestration_run


class CrossProjectWindowRetryReportTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_window_controls as controls
        import cross_project_execution_windows as windows
        import cross_project_window_retry_reports as reports
        self.reports = reports
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "rep.db"))
        self.addCleanup(self.conn.close)
        self.run_id = _seed_orchestration_run(self.conn)
        self.run_step_id = database.save_cross_project_orchestration_run_step(
            self.conn, self.run_id, 11, 21, 31, "alpha", 1, "pending")
        self.windows = windows.CrossProjectExecutionWindowManager(self.conn)
        self.gate = controls.CrossProjectExecutionWindowControlGate(self.conn)
        self.builder = reports.CrossProjectWindowRetryReportBuilder(self.conn)

    def test_report_requires_existing_run(self):
        with self.assertRaises(ValueError):
            self.builder.build_report(999)

    def test_report_collects_windows_and_advancements(self):
        window = self.windows.define_window(self.run_id, "w")
        self.gate.open_window(window.id)
        database.save_cross_project_gated_advancement(
            self.conn, self.run_id, self.run_step_id, 11, window.id, 1, None,
            1, 1, 1, 1, 1, "executed", json.dumps([]))
        report = self.builder.build_report(self.run_id)
        self.assertEqual(report.run_id, self.run_id)
        self.assertEqual(len(report.windows), 1)
        self.assertEqual(len(report.advancements), 1)
        self.assertIn("window status open", report.summary)

    def test_markdown_report_written_inside_reports_dir(self):
        window = self.windows.define_window(self.run_id, "w")
        self.gate.open_window(window.id)
        report = self.builder.build_report(self.run_id)
        report_id = self.builder.save_report(report)
        path = self.builder.save_markdown_report(report_id, report)
        self.addCleanup(os.remove, path)
        base = os.path.realpath(self.reports.REPORTS_DIR)
        self.assertTrue(os.path.realpath(path).startswith(base + os.sep))
        row = self.conn.execute(
            "SELECT * FROM cross_project_window_retry_markdown_reports "
            "WHERE report_id=?", (report_id,)).fetchone()
        self.assertEqual(row["report_path"], path)
        self.assertTrue(row["content_hash"])
        self.assertGreater(row["bytes_written"], 0)
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("Cross-Project Window & Retry Report", content)


if __name__ == "__main__":
    unittest.main()
