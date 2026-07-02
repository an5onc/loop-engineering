import json
import os
import tempfile
import unittest

import database


class CrossProjectStage14AuditTests(unittest.TestCase):
    def setUp(self):
        import cross_project_stage14_audit as audit
        self.audit = audit
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "s14.db"))
        self.addCleanup(self.conn.close)
        self.engine = audit.CrossProjectStage14AuditEngine(self.conn)

    def test_audit_passes_and_reports_stage15_readiness(self):
        report = self.engine.build_report()
        self.assertEqual(report.overall_status, "PASS")
        self.assertTrue(report.stage15_readiness["ready"])
        self.assertEqual(report.stage15_readiness["theme"],
                         self.audit.STAGE15_THEME)
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["runtime_audit"], "PASS")
        self.assertEqual(names["no_new_executor"], "PASS")

    def test_audit_fails_when_required_table_missing(self):
        self.conn.execute("DROP TABLE multi_run_recovery_reports")
        self.conn.commit()
        report = self.engine.build_report()
        self.assertEqual(report.overall_status, "FAIL")
        self.assertFalse(report.stage15_readiness["ready"])

    def test_fabricated_session_advancement_fails(self):
        session_id = database.save_multi_run_session(
            self.conn, "s", "active", "op", None, "")
        database.save_multi_run_session_advancement(
            self.conn, session_id, 1, 1, None, 999, 1, "executed", "",
            json.dumps([]))
        report = self.engine.build_report()
        self.assertEqual(report.overall_status, "FAIL")
        self.assertFalse(report.stage15_readiness["ready"])

    def test_allowlist_drift_fails(self):
        import terminal
        original = terminal.ALLOWED_FAMILIES
        terminal.ALLOWED_FAMILIES = original | {"curl"}
        self.addCleanup(setattr, terminal, "ALLOWED_FAMILIES", original)
        report = self.engine.build_report()
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["no_allowlist_expansion"], "FAIL")

    def test_missing_dynamic_table_degrades_to_blocked(self):
        self.conn.execute("DROP TABLE multi_run_session_members")
        self.conn.commit()
        report = self.engine.build_report()
        self.assertEqual(report.overall_status, "BLOCKED")
        self.assertFalse(report.stage15_readiness["ready"])

    def test_audit_saves_and_writes_markdown(self):
        report = self.engine.build_report()
        audit_id = self.engine.save_audit(report)
        path = self.engine.save_markdown_report(audit_id, report)
        self.addCleanup(os.remove, path)
        base = os.path.realpath(self.audit.REPORTS_DIR)
        self.assertTrue(os.path.realpath(path).startswith(base + os.sep))
        rows = database.list_cross_project_stage14_audits(self.conn)
        self.assertEqual(rows[0]["id"], audit_id)
        with open(path, encoding="utf-8") as fh:
            self.assertIn("Stage 15 ready: True", fh.read())


if __name__ == "__main__":
    unittest.main()
