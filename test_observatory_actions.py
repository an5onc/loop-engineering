import json
import os
import tempfile
import unittest

import database


class ObservatoryActionTests(unittest.TestCase):
    def test_create_actions_from_remediation_plan_and_skip_duplicates(self):
        import observatory_actions

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "actions.db"))
            self.addCleanup(conn.close)
            plan_id = _remediation_plan(conn)
            engine = observatory_actions.ObservatoryActionEngine(conn)

            first = engine.create_actions_from_plan(plan_id)
            second = engine.create_actions_from_plan(plan_id)
            queue = engine.list_actions(status=None)

            self.assertEqual(first["created"], 2)
            self.assertEqual(first["skipped"], 0)
            self.assertEqual(second["created"], 0)
            self.assertEqual(second["skipped"], 2)
            self.assertEqual(queue.total_actions, 2)
            self.assertEqual(queue.open_actions, 2)
            events = database.get_observatory_action_events(conn, queue.actions[0].id)
            self.assertTrue(any(e["event_type"] == "created" for e in events))

    def test_list_actions_by_status_priority_and_category(self):
        import observatory_actions

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "actions.db"))
            self.addCleanup(conn.close)
            plan_id = _remediation_plan(conn)
            engine = observatory_actions.ObservatoryActionEngine(conn)
            engine.create_actions_from_plan(plan_id)

            self.assertEqual(engine.list_actions(status="open").total_actions, 2)
            self.assertEqual(engine.list_actions(priority="high").total_actions, 1)
            self.assertEqual(engine.list_actions(category="safety").total_actions, 1)

    def test_status_and_notes_updates_persist_events(self):
        import observatory_actions

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "actions.db"))
            self.addCleanup(conn.close)
            plan_id = _remediation_plan(conn)
            engine = observatory_actions.ObservatoryActionEngine(conn)
            engine.create_actions_from_plan(plan_id)
            action_id = engine.list_actions(status="open").actions[0].id

            updated = engine.update_status(action_id, "in_progress")
            noted = engine.update_notes(action_id, "Reviewed and queued manually")

            self.assertEqual(updated.status, "in_progress")
            self.assertEqual(noted.notes, "Reviewed and queued manually")
            events = database.get_observatory_action_events(conn, action_id)
            self.assertTrue(any(e["event_type"] == "status_changed" for e in events))
            self.assertTrue(any(e["event_type"] == "notes_updated" for e in events))

    def test_action_report_path_safety(self):
        import observatory_actions

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "actions.db"))
            self.addCleanup(conn.close)
            observatory_actions.REPORTS_DIR = os.path.join(td, "action_reports")
            plan_id = _remediation_plan(conn)
            engine = observatory_actions.ObservatoryActionEngine(conn)
            engine.create_actions_from_plan(plan_id)

            report = engine.save_markdown_report()

            self.assertTrue(os.path.exists(report.report_path))
            base = os.path.realpath(observatory_actions.REPORTS_DIR)
            self.assertTrue(os.path.realpath(report.report_path).startswith(base + os.sep))
            self.assertEqual(_count(conn, "observatory_action_markdown_reports"), 1)

    def test_action_queue_does_not_create_loops_or_command_results(self):
        import observatory_actions

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "actions.db"))
            self.addCleanup(conn.close)
            plan_id = _remediation_plan(conn)
            before_loops = _count(conn, "loops")
            before_commands = _count(conn, "command_results")
            engine = observatory_actions.ObservatoryActionEngine(conn)

            engine.create_actions_from_plan(plan_id)
            action = engine.list_actions(status="open").actions[0]
            engine.update_status(action.id, "completed")
            engine.update_notes(action.id, "Do not execute: python3 -c 'print(1)'")

            self.assertEqual(_count(conn, "loops"), before_loops)
            self.assertEqual(_count(conn, "command_results"), before_commands)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _remediation_plan(conn):
    items = [
        {
            "id": 1,
            "priority": "high",
            "category": "testing",
            "title": "Fix quality gate failures",
            "problem_summary": "Quality gate failures repeat.",
            "evidence": "count=4",
            "affected_loop_ids": [44, 45],
            "affected_job_ids": [],
            "recommended_action": "Review failing gates.",
            "suggested_command": "python3 main.py --observatory-failures --category quality_gate_failed",
            "expected_impact": "Reduce blocked loops.",
            "risk_level": "medium",
            "effort_level": "medium",
            "status": "proposed",
        },
        {
            "id": 2,
            "priority": "urgent",
            "category": "safety",
            "title": "Investigate critical safety alert",
            "problem_summary": "Critical observatory alert exists.",
            "evidence": "critical_alert_count=1",
            "affected_loop_ids": [],
            "affected_job_ids": [9],
            "recommended_action": "Run external health review.",
            "suggested_command": "python3 main.py --external-health",
            "expected_impact": "Reduce safety risk.",
            "risk_level": "high",
            "effort_level": "medium",
            "status": "proposed",
        },
    ]
    return database.save_observatory_remediation_plan(
        conn,
        "2026-06-27T12:00:00",
        "failure_drilldown",
        7,
        json.dumps({"source": "test"}, sort_keys=True),
        json.dumps({"summary": "test plan", "next_steps": []}, sort_keys=True),
        json.dumps(items, sort_keys=True),
        2,
        1,
        1,
        0,
        0,
    )


if __name__ == "__main__":
    unittest.main()
