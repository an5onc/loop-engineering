import os
import tempfile
import unittest

import database


class CrossProjectStage13AuditTests(unittest.TestCase):
    def setUp(self):
        import cross_project_stage13_audit as audit
        self.audit = audit
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "s13.db"))
        self.addCleanup(self.conn.close)
        self.engine = audit.CrossProjectStage13AuditEngine(self.conn)

    def test_audit_passes_and_reports_stage14_readiness(self):
        report = self.engine.build_report()
        self.assertEqual(report.overall_status, "PASS")
        self.assertTrue(report.stage14_readiness["ready"])
        self.assertEqual(report.stage14_readiness["theme"],
                         self.audit.STAGE14_THEME)
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["restores_delegate_to_stage10"], "PASS")
        self.assertEqual(names["preview_before_restore"], "PASS")
        self.assertEqual(names["no_allowlist_expansion"], "PASS")

    def test_audit_fails_when_required_table_missing(self):
        self.conn.execute("DROP TABLE cross_project_restoration_statuses")
        self.conn.commit()
        report = self.engine.build_report()
        self.assertEqual(report.overall_status, "FAIL")
        self.assertFalse(report.stage14_readiness["ready"])

    def test_audit_blocks_when_dynamic_check_table_missing(self):
        self.conn.execute("DROP TABLE cross_project_restoration_targets")
        self.conn.commit()
        report = self.engine.build_report()
        self.assertEqual(report.overall_status, "BLOCKED")
        self.assertFalse(report.stage14_readiness["ready"])

    def test_audit_fails_on_fabricated_restore(self):
        database.save_cross_project_orchestration_step_rollback(
            self.conn, 1, 1, 1, 1, 999, "restored", "fabricated")
        report = self.engine.build_report()
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["restores_delegate_to_stage10"], "FAIL")

    def test_audit_fails_on_allowlist_expansion(self):
        import terminal
        original = terminal.ALLOWED_FAMILIES
        terminal.ALLOWED_FAMILIES = original | {"curl"}
        self.addCleanup(setattr, terminal, "ALLOWED_FAMILIES", original)
        report = self.engine.build_report()
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["no_allowlist_expansion"], "FAIL")

    def test_refused_retry_request_does_not_satisfy_reopen_audit(self):
        from test_cross_project_restoration_targets import seed_blocked_run
        seed = seed_blocked_run(self.conn, self.td.name, advance=False)
        database.save_cross_project_orchestration_step_rollback(
            self.conn, seed["run"].id, seed["step"].id,
            seed["step"].orchestration_step_id, seed["snapshot"].id, 1,
            "restored", "restored for test")
        database.save_cross_project_orchestration_retry_request(
            self.conn, seed["run"].id, seed["step"].id,
            seed["step"].orchestration_step_id, 1, 2, "refused", "test",
            "not authorized")
        report = self.engine.build_report()
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["restored_steps_not_auto_reopened"], "FAIL")

    def test_audit_saves_and_writes_markdown(self):
        report = self.engine.build_report()
        audit_id = self.engine.save_audit(report)
        path = self.engine.save_markdown_report(audit_id, report)
        self.addCleanup(os.remove, path)
        base = os.path.realpath(self.audit.REPORTS_DIR)
        self.assertTrue(os.path.realpath(path).startswith(base + os.sep))
        rows = database.list_cross_project_stage13_audits(self.conn)
        self.assertEqual(rows[0]["id"], audit_id)
        with open(path, encoding="utf-8") as fh:
            self.assertIn("Stage 14 ready: True", fh.read())


if __name__ == "__main__":
    unittest.main()
