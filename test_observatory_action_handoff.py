import json
import os
import tempfile
import unittest

import database


class ObservatoryActionHandoffTests(unittest.TestCase):
    def test_dry_run_handoff_does_not_create_loop_job_or_command_result(self):
        import observatory_action_handoff

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "handoff.db"))
            self.addCleanup(conn.close)
            action_id = _action(conn)
            before_loops = _count(conn, "loops")
            before_jobs = _count(conn, "external_agent_jobs")
            before_commands = _count(conn, "command_results")

            handoff = observatory_action_handoff.ObservatoryActionHandoffEngine(
                conn).create_handoff(action_id)

            self.assertEqual(handoff.handoff_type, "dry_run_plan")
            self.assertEqual(handoff.status, "DRY_RUN")
            self.assertEqual(_count(conn, "loops"), before_loops)
            self.assertEqual(_count(conn, "external_agent_jobs"), before_jobs)
            self.assertEqual(_count(conn, "command_results"), before_commands)

    def test_generated_task_includes_action_metadata(self):
        import observatory_action_handoff

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "handoff.db"))
            self.addCleanup(conn.close)
            action_id = _action(conn)

            handoff = observatory_action_handoff.ObservatoryActionHandoffEngine(
                conn).create_handoff(action_id, handoff_type="loop_task",
                                     target_loop_type="code_review",
                                     target_workspace="default")

            self.assertIn("Investigate and remediate", handoff.generated_task)
            self.assertIn("Fix quality gate failures", handoff.generated_task)
            self.assertIn("Quality gate failures repeat", handoff.generated_task)
            self.assertIn("Relevant loops: [44, 45]", handoff.generated_task)
            self.assertEqual(handoff.target_loop_type, "code_review")
            self.assertEqual(handoff.target_workspace, "default")
            self.assertEqual(handoff.status, "DRY_RUN")

    def test_loop_and_external_creation_require_confirmation(self):
        import observatory_action_handoff

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "handoff.db"))
            self.addCleanup(conn.close)
            action_id = _action(conn)
            engine = observatory_action_handoff.ObservatoryActionHandoffEngine(conn)

            loop_handoff = engine.create_handoff(action_id, handoff_type="loop_task")
            ext_handoff = engine.create_handoff(
                action_id, handoff_type="external_agent_job", external_coder="codex")

            self.assertEqual(loop_handoff.status, "DRY_RUN")
            self.assertEqual(ext_handoff.status, "DRY_RUN")
            self.assertEqual(_count(conn, "loops"), 0)
            self.assertEqual(_count(conn, "external_agent_jobs"), 0)

    def test_handoff_persistence_and_events(self):
        import observatory_action_handoff

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "handoff.db"))
            self.addCleanup(conn.close)
            action_id = _action(conn)

            handoff = observatory_action_handoff.ObservatoryActionHandoffEngine(
                conn).create_handoff(action_id)
            stored = database.get_observatory_action_handoff(conn, handoff.id)
            events = database.get_observatory_action_handoff_events(conn, handoff.id)

            self.assertEqual(stored["id"], handoff.id)
            self.assertEqual(len(database.list_observatory_action_handoffs(conn)), 1)
            self.assertTrue(any(e["event_type"] == "created" for e in events))

    def test_confirmed_creation_metadata_records_created_ids(self):
        import observatory_action_handoff

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "handoff.db"))
            self.addCleanup(conn.close)
            action_id = _action(conn)
            engine = observatory_action_handoff.ObservatoryActionHandoffEngine(conn)

            loop_handoff = engine.create_handoff(
                action_id, handoff_type="loop_task", confirm_create_loop=True,
                created_loop_id=12)
            ext_handoff = engine.create_handoff(
                action_id, handoff_type="external_agent_job",
                confirm_create_external_job=True, created_external_job_id=34)

            self.assertEqual(loop_handoff.status, "LOOP_CREATED")
            self.assertFalse(conn.execute(
                "SELECT dry_run FROM observatory_action_handoffs WHERE id=?",
                (loop_handoff.id,)).fetchone()["dry_run"])
            self.assertEqual(loop_handoff.created_loop_id, 12)
            self.assertEqual(ext_handoff.status, "EXTERNAL_JOB_CREATED")
            self.assertEqual(ext_handoff.created_external_job_id, 34)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _action(conn):
    return database.save_observatory_action_item(
        conn,
        1,
        1,
        "Fix quality gate failures",
        "testing",
        "high",
        "open",
        "python3 main.py --observatory-failures --category quality_gate_failed",
        "Quality gate failures repeat.",
        "Review failing gates manually.",
        json.dumps([44, 45], sort_keys=True),
        json.dumps([9], sort_keys=True),
        "medium",
        "medium",
        "",
    )


if __name__ == "__main__":
    unittest.main()
