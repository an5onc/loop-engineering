import datetime
import os
import tempfile
import unittest

import database
from test_cross_project_execution_windows import _seed_orchestration_run


class WindowEvaluationTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_window_checks as checks
        import cross_project_execution_windows as windows
        self.checks = checks
        self.window_cls = windows.CrossProjectExecutionWindow
        self.now = datetime.datetime(2026, 7, 1, 12, 0, 0)

    def _window(self, status, starts_at="", ends_at=""):
        return self.window_cls(
            id=1, run_id=1, label="w", status=status,
            starts_at=starts_at, ends_at=ends_at)

    def test_missing_window(self):
        status, _ = self.checks._evaluate(None, self.now)
        self.assertEqual(status, "missing")

    def test_defined_window_is_closed(self):
        status, _ = self.checks._evaluate(self._window("defined"), self.now)
        self.assertEqual(status, "closed")

    def test_closed_window_is_closed(self):
        status, _ = self.checks._evaluate(self._window("closed"), self.now)
        self.assertEqual(status, "closed")

    def test_open_window_no_bounds_is_open(self):
        status, _ = self.checks._evaluate(self._window("open"), self.now)
        self.assertEqual(status, "open")

    def test_open_window_before_start_is_not_started(self):
        status, _ = self.checks._evaluate(
            self._window("open", starts_at="2026-07-01T13:00:00"), self.now)
        self.assertEqual(status, "not_started")

    def test_open_window_after_end_is_expired(self):
        status, _ = self.checks._evaluate(
            self._window("open", ends_at="2026-07-01T11:00:00"), self.now)
        self.assertEqual(status, "expired")

    def test_open_window_within_bounds_is_open(self):
        status, _ = self.checks._evaluate(
            self._window("open", starts_at="2026-07-01T10:00:00",
                         ends_at="2026-07-01T18:00:00"), self.now)
        self.assertEqual(status, "open")


class WindowCheckerTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_window_checks as checks
        import cross_project_execution_window_controls as controls
        import cross_project_execution_windows as windows
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "chk.db"))
        self.addCleanup(self.conn.close)
        self.run_id = _seed_orchestration_run(self.conn)
        self.manager = windows.CrossProjectExecutionWindowManager(self.conn)
        self.gate = controls.CrossProjectExecutionWindowControlGate(self.conn)
        self.checker = checks.CrossProjectExecutionWindowChecker(self.conn)

    def test_check_requires_existing_run(self):
        with self.assertRaises(ValueError):
            self.checker.check(999)

    def test_check_with_no_window_records_missing(self):
        check = self.checker.check(self.run_id)
        self.assertEqual(check.status, "missing")
        self.assertIsNone(check.window_id)
        rows = database.list_cross_project_execution_window_checks(
            self.conn, run_id=self.run_id)
        self.assertEqual(len(rows), 1)

    def test_check_prefers_open_window(self):
        stale = self.manager.define_window(self.run_id, "stale")
        self.gate.open_window(stale.id)
        self.gate.close_window(stale.id)
        active = self.manager.define_window(self.run_id, "active")
        self.gate.open_window(active.id)
        check = self.checker.check(self.run_id, run_step_id=7)
        self.assertEqual(check.status, "open")
        self.assertEqual(check.window_id, active.id)
        self.assertEqual(check.run_step_id, 7)

    def test_check_records_closed_when_no_open_window(self):
        window = self.manager.define_window(self.run_id, "pending")
        check = self.checker.check(self.run_id)
        self.assertEqual(check.status, "closed")
        self.assertEqual(check.window_id, window.id)


if __name__ == "__main__":
    unittest.main()
