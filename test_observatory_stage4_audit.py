import os
import tempfile
import unittest

import database


class ObservatoryStage4AuditTests(unittest.TestCase):
    def test_audit_report_generation_and_stage5_readiness(self):
        import observatory_stage4_audit as stage4

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "stage4_audit.db"))
            self.addCleanup(conn.close)
            report = stage4.ObservatoryStage4AuditEngine(conn).build_report()

            self.assertGreaterEqual(report.total_checks, 10)
            self.assertEqual(
                report.total_checks,
                report.passed_checks + report.warning_checks + report.failed_checks,
            )
            self.assertIn(report.overall_status, ("PASS", "PASS WITH WARNINGS", "FAIL"))
            self.assertIn("ready", report.stage5_readiness)
            self.assertIn("observatory_core", {section.name for section in report.sections})

    def test_section_and_overall_status_aggregation(self):
        import observatory_stage4_audit as stage4

        passing = stage4.Stage4AuditSection(
            name="passing",
            status="PASS",
            checks=[stage4.Stage4AuditCheck("ok", "cat", "PASS", "ok", "", "")],
            summary="ok",
        )
        warning = stage4.Stage4AuditSection(
            name="warning",
            status="WARN",
            checks=[stage4.Stage4AuditCheck("warn", "cat", "WARN", "warn", "", "")],
            summary="warn",
        )
        failing = stage4.Stage4AuditSection(
            name="failing",
            status="FAIL",
            checks=[stage4.Stage4AuditCheck("fail", "cat", "FAIL", "fail", "", "")],
            summary="fail",
        )

        self.assertEqual(stage4.aggregate_overall_status([passing]), "PASS")
        self.assertEqual(
            stage4.aggregate_overall_status([passing, warning]), "PASS WITH WARNINGS")
        self.assertEqual(
            stage4.aggregate_overall_status([passing, warning, failing]), "FAIL")

    def test_audit_persistence_and_markdown_path_safety(self):
        import observatory_stage4_audit as stage4

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "stage4_audit.db"))
            self.addCleanup(conn.close)
            old_reports_dir = stage4.REPORTS_DIR
            stage4.REPORTS_DIR = os.path.join(td, "reports")
            self.addCleanup(setattr, stage4, "REPORTS_DIR", old_reports_dir)

            engine = stage4.ObservatoryStage4AuditEngine(conn)
            report = engine.build_report()
            audit_id = engine.save_audit(report)
            markdown = engine.save_markdown_report(audit_id, report)
            stored = database.get_observatory_stage4_audit(conn, audit_id)

            self.assertEqual(stored["id"], audit_id)
            self.assertTrue(stage4.is_markdown_report_path(markdown.report_path))
            self.assertTrue(os.path.realpath(markdown.report_path).startswith(
                os.path.realpath(stage4.REPORTS_DIR) + os.sep))
            self.assertTrue(os.path.isfile(markdown.report_path))

    def test_audit_does_not_create_loops_jobs_or_command_results(self):
        import observatory_stage4_audit as stage4

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "stage4_audit.db"))
            self.addCleanup(conn.close)
            before = {table: _count(conn, table)
                      for table in ("loops", "external_agent_jobs", "command_results")}

            report = stage4.ObservatoryStage4AuditEngine(conn).build_report()
            stage4.ObservatoryStage4AuditEngine(conn).save_audit(report)

            after = {table: _count(conn, table)
                     for table in ("loops", "external_agent_jobs", "command_results")}
            self.assertEqual(after, before)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


if __name__ == "__main__":
    unittest.main()
