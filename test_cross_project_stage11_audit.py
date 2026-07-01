import os
import tempfile
import unittest

import database


class CrossProjectStage11AuditTests(unittest.TestCase):
    def test_stage11_audit_reports_stage12_readiness(self):
        import cross_project_stage11_audit as audit
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        conn = database.init_db(os.path.join(td.name, "s11.db"))
        self.addCleanup(conn.close)
        report = audit.CrossProjectStage11AuditEngine(conn).build_report()
        self.assertEqual(report.overall_status, "PASS")
        self.assertTrue(report.stage12_readiness["ready"])


if __name__ == "__main__":
    unittest.main()
