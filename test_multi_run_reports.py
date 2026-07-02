import os
import tempfile
import unittest

import database
from test_cross_project_restoration_targets import seed_blocked_run


class MultiRunSessionReportTests(unittest.TestCase):
    def setUp(self):
        import multi_run_reports as reports
        import multi_run_session_gates as gates
        import multi_run_sessions as sessions
        self.reports_mod = reports
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "mr.db"))
        self.addCleanup(self.conn.close)
        self.sessions = sessions.MultiRunSessionManager(self.conn)
        self.gates = gates.MultiRunSessionGateManager(self.conn)
        self.builder = reports.MultiRunSessionReportBuilder(self.conn)

    def test_report_requires_existing_session(self):
        with self.assertRaises(ValueError):
            self.builder.build_report(999)

    def test_report_renders_for_empty_session(self):
        session = self.sessions.create_session("s")
        report = self.builder.build_report(session.id)
        self.assertEqual(report.overall_status, "empty")
        self.assertEqual(report.members, [])
        markdown = self.builder.render_markdown(report)
        self.assertIn("Multi-Run Session Report", markdown)

    def test_report_collects_members_gates_and_recovery(self):
        seed = seed_blocked_run(self.conn, self.td.name)
        session = self.sessions.create_session("s")
        self.sessions.add_run(session.id, seed["run"].id)
        gate = self.gates.define_gate(session.id, "g")
        self.gates.approve_gate(gate.id)
        report = self.builder.build_report(session.id)
        self.assertEqual(len(report.members), 1)
        self.assertEqual(len(report.gates), 1)
        self.assertEqual(len(report.recovery), 1)
        self.assertEqual(report.overall_status, "needs_restoration")

    def test_report_contains_no_protected_markers(self):
        seed = seed_blocked_run(self.conn, self.td.name)
        session = self.sessions.create_session("s")
        self.sessions.add_run(session.id, seed["run"].id)
        report = self.builder.build_report(session.id)
        self.builder.save_report(report)
        row = database.list_multi_run_session_reports(
            self.conn, session_id=session.id)[0]
        blob = " ".join(str(row[k] or "") for k in row.keys())
        for marker in ("PRIVATE KEY", "-----BEGIN", "id_rsa"):
            self.assertNotIn(marker, blob)

    def test_markdown_saved_inside_reports_dir(self):
        session = self.sessions.create_session("s")
        report = self.builder.build_report(session.id)
        report_id = self.builder.save_report(report)
        path = self.builder.save_markdown_report(report_id, report)
        self.addCleanup(os.remove, path)
        base = os.path.realpath(self.reports_mod.REPORTS_DIR)
        self.assertTrue(os.path.realpath(path).startswith(base + os.sep))
        row = self.conn.execute(
            "SELECT * FROM multi_run_session_markdown_reports "
            "WHERE report_id=?", (report_id,)).fetchone()
        self.assertEqual(row["report_path"], path)
        self.assertGreater(row["bytes_written"], 0)


if __name__ == "__main__":
    unittest.main()
