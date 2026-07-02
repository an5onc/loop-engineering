import os
import tempfile
import unittest

import database
from test_cross_project_restoration_targets import seed_blocked_run


class CrossProjectRestorationAuditTests(unittest.TestCase):
    def setUp(self):
        import cross_project_restoration_audit as audit
        self.audit = audit
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "ra.db"))
        self.addCleanup(self.conn.close)
        self.engine = audit.CrossProjectRestorationAuditEngine(self.conn)

    def test_clean_metadata_passes(self):
        report = self.engine.build_report()
        self.assertEqual(report.overall_status, "PASS")

    def test_full_lifecycle_passes(self):
        import cross_project_gated_restoration as gated
        import cross_project_restoration_previews as previews
        seed = seed_blocked_run(self.conn, self.td.name)
        previews.CrossProjectRestorationPreviewBinder(self.conn).preview(
            seed["run"].id, seed["step"].step_id)
        gated.CrossProjectGatedRestorationEngine(self.conn).restore(
            seed["run"].id, seed["step"].step_id, confirm_restore=True)
        report = self.engine.build_report()
        self.assertEqual(report.overall_status, "PASS")

    def test_fabricated_restore_fails(self):
        database.save_cross_project_orchestration_step_rollback(
            self.conn, 1, 1, 1, 1, 999, "restored", "fabricated")
        report = self.engine.build_report()
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(
            names["restored_rollbacks_reference_real_restores"], "FAIL")
        self.assertEqual(names["previews_precede_restores"], "FAIL")
        self.assertEqual(report.overall_status, "FAIL")

    def test_reopened_step_without_retry_request_fails(self):
        seed = seed_blocked_run(self.conn, self.td.name, advance=False)
        database.save_cross_project_orchestration_step_rollback(
            self.conn, seed["run"].id, seed["step"].id,
            seed["step"].orchestration_step_id, seed["snapshot"].id, 1,
            "restored", "restored for test")
        report = self.engine.build_report()
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["restored_steps_not_auto_reopened"], "FAIL")

    def test_refused_retry_request_does_not_authorize_reopened_step(self):
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

    def test_integrity_mismatch_is_warn_not_fail(self):
        database.save_cross_project_restoration_integrity_check(
            self.conn, 1, 1, 1, 1, 1, "2026-07-01T12:00:00", 1, 0, 1, 0,
            "mismatch", "[]")
        report = self.engine.build_report()
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["integrity_mismatches_surfaced"], "WARN")
        self.assertEqual(report.overall_status, "PASS")

    def test_audit_saves_and_writes_markdown(self):
        report = self.engine.build_report()
        audit_id = self.engine.save_audit(report)
        path = self.engine.save_markdown_report(audit_id, report)
        self.addCleanup(os.remove, path)
        base = os.path.realpath(self.audit.REPORTS_DIR)
        self.assertTrue(os.path.realpath(path).startswith(base + os.sep))
        rows = database.list_cross_project_restoration_audits(self.conn)
        self.assertEqual(rows[0]["id"], audit_id)


if __name__ == "__main__":
    unittest.main()
