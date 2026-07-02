import datetime
import os
import tempfile
import unittest

import database
from test_cross_project_execution_sessions import _count


def _seed_orchestration_run(conn, status="running"):
    now = datetime.datetime.now().isoformat(timespec="seconds")
    return database.save_cross_project_orchestration_run(
        conn, 1, 1, now, status, 1, 0, 0, "seeded run for window tests")


class CrossProjectExecutionWindowTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_windows as windows
        self.windows = windows
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "w.db"))
        self.addCleanup(self.conn.close)
        self.run_id = _seed_orchestration_run(self.conn)
        self.manager = windows.CrossProjectExecutionWindowManager(self.conn)

    def test_define_window_starts_defined_and_records_event(self):
        window = self.manager.define_window(self.run_id, "maintenance")
        self.assertEqual(window.status, "defined")
        self.assertEqual(window.run_id, self.run_id)
        self.assertEqual(window.label, "maintenance")
        events = database.list_cross_project_execution_window_events(
            self.conn, window_id=window.id)
        self.assertEqual([row["event_type"] for row in events], ["defined"])
        self.assertEqual(_count(self.conn, "cross_project_execution_attempts"), 0)

    def test_define_window_requires_existing_run(self):
        with self.assertRaises(ValueError):
            self.manager.define_window(999, "maintenance")

    def test_define_window_requires_label(self):
        with self.assertRaises(ValueError):
            self.manager.define_window(self.run_id, "  ")

    def test_define_window_rejects_bad_timestamps(self):
        with self.assertRaises(ValueError):
            self.manager.define_window(self.run_id, "w", starts_at="not-a-time")
        with self.assertRaises(ValueError):
            self.manager.define_window(
                self.run_id, "w", starts_at="2026-07-01T10:00:00",
                ends_at="2026-07-01T09:00:00")

    def test_define_window_accepts_time_bounds(self):
        window = self.manager.define_window(
            self.run_id, "bounded", starts_at="2026-07-01T10:00:00",
            ends_at="2026-07-01T18:00:00")
        self.assertEqual(window.starts_at, "2026-07-01T10:00:00")
        self.assertEqual(window.ends_at, "2026-07-01T18:00:00")
        listed = self.manager.list_windows(run_id=self.run_id)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].id, window.id)


if __name__ == "__main__":
    unittest.main()
