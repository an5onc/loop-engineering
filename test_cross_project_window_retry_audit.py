import json
import os
import tempfile
import unittest

import database
from test_cross_project_execution_windows import _seed_orchestration_run


class CrossProjectWindowRetryAuditTests(unittest.TestCase):
    def setUp(self):
        import cross_project_window_retry_audit as audit
        self.audit = audit
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "au.db"))
        self.addCleanup(self.conn.close)
        self.run_id = _seed_orchestration_run(self.conn)
        self.run_step_id = database.save_cross_project_orchestration_run_step(
            self.conn, self.run_id, 11, 21, 31, "alpha", 1, "pending")
        self.engine = audit.CrossProjectWindowRetryAuditEngine(self.conn)

    def _seed_gated(self, window_check_id, confirmation_id=1, attempt_number=1):
        return database.save_cross_project_gated_advancement(
            self.conn, self.run_id, self.run_step_id, 11, 1, window_check_id,
            None, attempt_number, confirmation_id, 1, 1, 1, "executed",
            json.dumps([]))

    def test_clean_metadata_passes(self):
        report = self.engine.build_report()
        self.assertEqual(report.overall_status, "PASS")
        self.assertEqual(report.failed_checks, 0)

    def test_advancement_without_open_check_fails(self):
        check_id = database.save_cross_project_execution_window_check(
            self.conn, self.run_id, self.run_step_id, 1, "closed", "closed",
            "2026-07-01T12:00:00")
        self._seed_gated(check_id)
        report = self.engine.build_report()
        self.assertEqual(report.overall_status, "FAIL")
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["advancements_reference_open_windows"], "FAIL")

    def test_confirmation_reuse_fails(self):
        check_id = database.save_cross_project_execution_window_check(
            self.conn, self.run_id, self.run_step_id, 1, "open", "open",
            "2026-07-01T12:00:00")
        self._seed_gated(check_id, confirmation_id=5, attempt_number=1)
        self._seed_gated(check_id, confirmation_id=5, attempt_number=2)
        report = self.engine.build_report()
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["no_confirmation_reuse"], "FAIL")

    def test_out_of_bounds_policy_fails(self):
        database.save_cross_project_orchestration_retry_policy(
            self.conn, self.run_id, 9, "active", "operator", None)
        report = self.engine.build_report()
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["retry_policies_bounded"], "FAIL")

    def test_reopened_window_fails(self):
        window_id = database.save_cross_project_execution_window(
            self.conn, self.run_id, "w", "open", None, None, None)
        database.save_cross_project_execution_window_event(
            self.conn, window_id, "closed")
        database.save_cross_project_execution_window_event(
            self.conn, window_id, "opened")
        report = self.engine.build_report()
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["no_reopened_windows"], "FAIL")

    def test_audit_saves_and_writes_markdown(self):
        report = self.engine.build_report()
        audit_id = self.engine.save_audit(report)
        path = self.engine.save_markdown_report(audit_id, report)
        self.addCleanup(os.remove, path)
        base = os.path.realpath(self.audit.REPORTS_DIR)
        self.assertTrue(os.path.realpath(path).startswith(base + os.sep))
        rows = database.list_cross_project_window_retry_audits(self.conn)
        self.assertEqual(rows[0]["id"], audit_id)


if __name__ == "__main__":
    unittest.main()
