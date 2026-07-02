import os
import tempfile
import unittest

import database
from test_cross_project_execution_windows import _seed_orchestration_run


class CrossProjectExecutionWindowControlTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_window_controls as controls
        import cross_project_execution_windows as windows
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "wc.db"))
        self.addCleanup(self.conn.close)
        self.run_id = _seed_orchestration_run(self.conn)
        self.manager = windows.CrossProjectExecutionWindowManager(self.conn)
        self.gate = controls.CrossProjectExecutionWindowControlGate(self.conn)
        self.window = self.manager.define_window(self.run_id, "maintenance")

    def test_open_then_close_records_events(self):
        opened = self.gate.open_window(self.window.id, opened_by="anson")
        self.assertEqual(opened.status, "open")
        self.assertEqual(opened.opened_by, "anson")
        self.assertTrue(opened.opened_at)
        closed = self.gate.close_window(self.window.id, closed_by="anson")
        self.assertEqual(closed.status, "closed")
        self.assertTrue(closed.closed_at)
        events = database.list_cross_project_execution_window_events(
            self.conn, window_id=self.window.id)
        self.assertEqual([row["event_type"] for row in events],
                         ["defined", "opened", "closed"])

    def test_closed_window_cannot_reopen(self):
        self.gate.open_window(self.window.id)
        self.gate.close_window(self.window.id)
        with self.assertRaises(ValueError):
            self.gate.open_window(self.window.id)

    def test_defined_window_cannot_close(self):
        with self.assertRaises(ValueError):
            self.gate.close_window(self.window.id)

    def test_open_requires_defined_window(self):
        with self.assertRaises(ValueError):
            self.gate.open_window(999)
        self.gate.open_window(self.window.id)
        with self.assertRaises(ValueError):
            self.gate.open_window(self.window.id)


if __name__ == "__main__":
    unittest.main()
