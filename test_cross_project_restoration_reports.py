import os
import tempfile
import unittest

import database
from test_cross_project_restoration_targets import seed_blocked_run


class CrossProjectRestorationReportTests(unittest.TestCase):
    def setUp(self):
        import cross_project_gated_restoration as gated
        import cross_project_restoration_previews as previews
        import cross_project_restoration_reports as reports
        self.reports = reports
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "rr.db"))
        self.addCleanup(self.conn.close)
        self.seed = seed_blocked_run(self.conn, self.td.name)
        self.previews = previews.CrossProjectRestorationPreviewBinder(self.conn)
        self.engine = gated.CrossProjectGatedRestorationEngine(self.conn)
        self.builder = reports.CrossProjectRestorationReportBuilder(self.conn)

    def test_report_requires_existing_run(self):
        with self.assertRaises(ValueError):
            self.builder.build_report(999)

    def test_report_collects_lifecycle_records(self):
        self.previews.preview(self.seed["run"].id, self.seed["step"].step_id)
        self.engine.restore(self.seed["run"].id, self.seed["step"].step_id,
                            confirm_restore=True)
        report = self.builder.build_report(self.seed["run"].id)
        self.assertEqual(report.run_id, self.seed["run"].id)
        self.assertEqual(len(report.rollbacks), 2)
        self.assertIn("1 restoration(s)", report.summary)
        self.assertIn("request an authorized retry", report.next_action)

    def test_markdown_report_written_inside_reports_dir(self):
        report = self.builder.build_report(self.seed["run"].id)
        report_id = self.builder.save_report(report)
        path = self.builder.save_markdown_report(report_id, report)
        self.addCleanup(os.remove, path)
        base = os.path.realpath(self.reports.REPORTS_DIR)
        self.assertTrue(os.path.realpath(path).startswith(base + os.sep))
        row = self.conn.execute(
            "SELECT * FROM cross_project_restoration_markdown_reports "
            "WHERE report_id=?", (report_id,)).fetchone()
        self.assertEqual(row["report_path"], path)
        self.assertGreater(row["bytes_written"], 0)
        with open(path, encoding="utf-8") as fh:
            self.assertIn("Cross-Project Restoration Report", fh.read())


if __name__ == "__main__":
    unittest.main()
