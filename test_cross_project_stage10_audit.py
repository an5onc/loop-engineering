import unittest


class CrossProjectStage10AuditTests(unittest.TestCase):
    def test_stage10_audit_reports_stage11_readiness(self):
        import cross_project_stage10_audit as audit
        import database
        import tempfile
        import os
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        conn = database.init_db(os.path.join(td.name, "a.db"))
        self.addCleanup(conn.close)
        report = audit.CrossProjectStage10AuditEngine(conn).build_report()
        self.assertEqual(report.overall_status, "PASS")
        self.assertTrue(report.stage11_readiness["ready"])


if __name__ == "__main__":
    unittest.main()
