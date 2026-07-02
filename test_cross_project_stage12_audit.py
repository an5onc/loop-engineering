import os
import tempfile
import unittest

import database


class CrossProjectStage12AuditTests(unittest.TestCase):
    def setUp(self):
        import cross_project_stage12_audit as audit
        self.audit = audit
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "s12.db"))
        self.addCleanup(self.conn.close)
        self.engine = audit.CrossProjectStage12AuditEngine(self.conn)

    def test_audit_passes_and_reports_stage13_readiness(self):
        report = self.engine.build_report()
        self.assertEqual(report.overall_status, "PASS")
        self.assertTrue(report.stage13_readiness["ready"])
        self.assertEqual(report.stage13_readiness["theme"],
                         self.audit.STAGE13_THEME)
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["stage11_runtime_reused"], "PASS")
        self.assertEqual(names["windows_fail_closed"], "PASS")
        self.assertEqual(names["no_allowlist_expansion"], "PASS")

    def test_audit_fails_when_required_table_missing(self):
        self.conn.execute("DROP TABLE cross_project_execution_windows")
        self.conn.commit()
        report = self.engine.build_report()
        self.assertEqual(report.overall_status, "FAIL")
        self.assertFalse(report.stage13_readiness["ready"])

    def test_audit_fails_on_allowlist_expansion(self):
        import terminal
        original = terminal.ALLOWED_FAMILIES
        terminal.ALLOWED_FAMILIES = original | {"curl"}
        self.addCleanup(setattr, terminal, "ALLOWED_FAMILIES", original)
        report = self.engine.build_report()
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["no_allowlist_expansion"], "FAIL")

    def test_audit_saves_and_writes_markdown(self):
        report = self.engine.build_report()
        audit_id = self.engine.save_audit(report)
        path = self.engine.save_markdown_report(audit_id, report)
        self.addCleanup(os.remove, path)
        base = os.path.realpath(self.audit.REPORTS_DIR)
        self.assertTrue(os.path.realpath(path).startswith(base + os.sep))
        rows = database.list_cross_project_stage12_audits(self.conn)
        self.assertEqual(rows[0]["id"], audit_id)
        with open(path, encoding="utf-8") as fh:
            self.assertIn("Stage 13 ready: True", fh.read())


if __name__ == "__main__":
    unittest.main()
