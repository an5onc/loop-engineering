import json
import os
import tempfile
import unittest

import database
from test_cross_project_execution_windows import _seed_orchestration_run


class MultiRunSessionAuditTests(unittest.TestCase):
    def setUp(self):
        import multi_run_session_audit as audit
        import multi_run_sessions as sessions
        self.audit = audit
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "sa.db"))
        self.addCleanup(self.conn.close)
        self.sessions = sessions.MultiRunSessionManager(self.conn)
        self.engine = audit.MultiRunSessionAuditEngine(self.conn)

    def _names(self, report):
        return {c.name: c.status for c in report.checks}

    def test_clean_metadata_passes(self):
        report = self.engine.build_report()
        self.assertEqual(report.overall_status, "PASS")
        names = self._names(report)
        self.assertEqual(names["no_forbidden_calls_in_stage14_modules"], "PASS")
        self.assertEqual(names["no_allowlist_expansion"], "PASS")

    def _seed_gated_advancement(self, run_id=1, run_step_id=1, attempt_id=7,
                                status="executed"):
        return database.save_cross_project_gated_advancement(
            self.conn, run_id, run_step_id, 1, 1, 1, None, 1, 1, 1, 1,
            attempt_id, status, json.dumps([]))

    def test_fabricated_advancement_without_stage12_row_fails(self):
        session = self.sessions.create_session("s")
        database.save_multi_run_session_advancement(
            self.conn, session.id, 1, 1, None, 999, 1, "executed", "",
            json.dumps([]))
        report = self.engine.build_report()
        names = self._names(report)
        self.assertEqual(names["advancements_reference_stage12"], "FAIL")
        self.assertEqual(report.overall_status, "FAIL")

    def test_matching_advancement_linkage_passes(self):
        session = self.sessions.create_session("s")
        gated_id = self._seed_gated_advancement()
        database.save_multi_run_session_advancement(
            self.conn, session.id, 1, 1, None, gated_id, 7, "executed", "",
            json.dumps([]))
        report = self.engine.build_report()
        names = self._names(report)
        self.assertEqual(names["advancements_reference_stage12"], "PASS")

    def test_mismatched_advancement_linkage_fails(self):
        session = self.sessions.create_session("s")
        mismatches = {
            "run_id": dict(run_id=2, run_step_id=1, attempt_id=7,
                           status="executed"),
            "run_step_id": dict(run_id=1, run_step_id=2, attempt_id=7,
                                status="executed"),
            "attempt_id": dict(run_id=1, run_step_id=1, attempt_id=8,
                               status="executed"),
            "status": dict(run_id=1, run_step_id=1, attempt_id=7,
                           status="blocked"),
        }
        for field, claimed in mismatches.items():
            with self.subTest(field=field):
                gated_id = self._seed_gated_advancement()
                record_id = database.save_multi_run_session_advancement(
                    self.conn, session.id, claimed["run_id"],
                    claimed["run_step_id"], None, gated_id,
                    claimed["attempt_id"], claimed["status"], "",
                    json.dumps([]))
                report = self.engine.build_report()
                names = self._names(report)
                self.assertEqual(
                    names["advancements_reference_stage12"], "FAIL")
                self.conn.execute(
                    "DELETE FROM multi_run_session_advancements WHERE id=?",
                    (record_id,))
                self.conn.commit()

    def test_refused_advancement_with_attempt_fails(self):
        session = self.sessions.create_session("s")
        database.save_multi_run_session_advancement(
            self.conn, session.id, 1, 1, None, None, 5, "refused", "",
            json.dumps([]))
        report = self.engine.build_report()
        names = self._names(report)
        self.assertEqual(names["refused_advancements_have_no_attempts"], "FAIL")

    def test_duplicate_active_membership_fails(self):
        run_id = _seed_orchestration_run(self.conn)
        a = self.sessions.create_session("a")
        b = self.sessions.create_session("b")
        self.sessions.add_run(a.id, run_id)
        database.save_multi_run_session_member(self.conn, b.id, run_id, "active")
        report = self.engine.build_report()
        names = self._names(report)
        self.assertEqual(names["no_duplicate_active_membership"], "FAIL")

    def test_member_referencing_missing_run_fails(self):
        session = self.sessions.create_session("s")
        database.save_multi_run_session_member(self.conn, session.id, 999,
                                               "active")
        report = self.engine.build_report()
        names = self._names(report)
        self.assertEqual(
            names["members_reference_real_sessions_and_runs"], "FAIL")

    def test_protected_marker_in_report_fails(self):
        session = self.sessions.create_session("s")
        database.save_multi_run_session_report(
            self.conn, session.id, "2026-07-01T12:00:00", "empty",
            "fake PRIVATE KEY content", "", "[]", "[]", "[]", "[]", "[]")
        report = self.engine.build_report()
        names = self._names(report)
        self.assertEqual(names["reports_no_protected_markers"], "FAIL")

    def test_protected_marker_in_readiness_report_fails(self):
        session = self.sessions.create_session("s")
        database.save_multi_run_readiness_report(
            self.conn, session.id, "2026-07-01T12:00:00", "empty",
            "leaked -----BEGIN block", "", "[]", "[]")
        report = self.engine.build_report()
        names = self._names(report)
        self.assertEqual(names["reports_no_protected_markers"], "FAIL")
        self.assertIn("multi_run_readiness_reports",
                      [c.message for c in report.checks
                       if c.name == "reports_no_protected_markers"][0])

    def test_protected_marker_in_planner_report_fails(self):
        session = self.sessions.create_session("s")
        database.save_multi_run_planner_report(
            self.conn, session.id, "2026-07-01T12:00:00", "empty", None, None,
            "leaked id_rsa path", "", "[]", "[]")
        report = self.engine.build_report()
        names = self._names(report)
        self.assertEqual(names["reports_no_protected_markers"], "FAIL")

    def test_protected_marker_in_recovery_report_fails(self):
        session = self.sessions.create_session("s")
        database.save_multi_run_recovery_report(
            self.conn, session.id, "2026-07-01T12:00:00", "blocked",
            "fake PRIVATE KEY content", "", "[]", "[]")
        report = self.engine.build_report()
        names = self._names(report)
        self.assertEqual(names["reports_no_protected_markers"], "FAIL")

    def test_allowlist_expansion_fails(self):
        import terminal
        original = terminal.ALLOWED_FAMILIES
        terminal.ALLOWED_FAMILIES = original | {"curl"}
        self.addCleanup(setattr, terminal, "ALLOWED_FAMILIES", original)
        report = self.engine.build_report()
        names = self._names(report)
        self.assertEqual(names["no_allowlist_expansion"], "FAIL")

    def test_missing_dynamic_table_blocks_not_crashes(self):
        self.conn.execute("DROP TABLE multi_run_session_members")
        self.conn.commit()
        report = self.engine.build_report()
        self.assertEqual(report.overall_status, "BLOCKED")

    def test_audit_saves_and_writes_markdown(self):
        report = self.engine.build_report()
        audit_id = self.engine.save_audit(report)
        path = self.engine.save_markdown_report(audit_id, report)
        self.addCleanup(os.remove, path)
        base = os.path.realpath(self.audit.REPORTS_DIR)
        self.assertTrue(os.path.realpath(path).startswith(base + os.sep))
        rows = database.list_multi_run_session_audits(self.conn)
        self.assertEqual(rows[0]["id"], audit_id)


if __name__ == "__main__":
    unittest.main()
