import os
import tempfile
import unittest

import database
from test_cross_project_execution_sessions import _count
from test_cross_project_execution_windows import _seed_orchestration_run


class MultiRunSessionTests(unittest.TestCase):
    def setUp(self):
        import multi_run_sessions as sessions
        self.sessions_mod = sessions
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "mrs.db"))
        self.addCleanup(self.conn.close)
        self.manager = sessions.MultiRunSessionManager(self.conn)

    def test_create_session_persists_one_row(self):
        session = self.manager.create_session("fleet upgrade", created_by="anson")
        self.assertEqual(session.status, "defined")
        self.assertEqual(session.title, "fleet upgrade")
        self.assertEqual(_count(self.conn, "multi_run_sessions"), 1)
        self.assertEqual(_count(self.conn, "cross_project_execution_attempts"), 0)
        self.assertEqual(_count(self.conn, "loops"), 0)
        self.assertEqual(_count(self.conn, "command_results"), 0)
        self.assertEqual(_count(self.conn, "external_agent_jobs"), 0)

    def test_create_session_requires_title(self):
        with self.assertRaises(ValueError):
            self.manager.create_session("  ")

    def test_list_and_inspect_sessions(self):
        self.assertEqual(self.manager.list_sessions(), [])
        self.assertIsNone(self.manager.get_session(999))
        a = self.manager.create_session("a")
        b = self.manager.create_session("b")
        listed = self.manager.list_sessions()
        self.assertEqual([s.id for s in listed], [b.id, a.id])

    def test_add_run_activates_session(self):
        session = self.manager.create_session("s")
        run_id = _seed_orchestration_run(self.conn)
        member = self.manager.add_run(session.id, run_id)
        self.assertEqual(member.status, "active")
        self.assertEqual(self.manager.get_session(session.id).status, "active")

    def test_membership_fail_closed_rules(self):
        session = self.manager.create_session("s")
        run_id = _seed_orchestration_run(self.conn)
        self.manager.add_run(session.id, run_id)
        with self.assertRaises(ValueError):
            self.manager.add_run(session.id, run_id)
        with self.assertRaises(ValueError):
            self.manager.add_run(session.id, 999)
        with self.assertRaises(ValueError):
            self.manager.add_run(999, run_id)
        other = self.manager.create_session("other")
        with self.assertRaises(ValueError):
            self.manager.add_run(other.id, run_id)

    def test_closed_session_is_immutable(self):
        session = self.manager.create_session("s")
        run_id = _seed_orchestration_run(self.conn)
        self.manager.add_run(session.id, run_id)
        self.manager.close_session(session.id)
        run2 = _seed_orchestration_run(self.conn)
        with self.assertRaises(ValueError):
            self.manager.add_run(session.id, run2)
        with self.assertRaises(ValueError):
            self.manager.remove_run(session.id, run_id)
        with self.assertRaises(ValueError):
            self.manager.close_session(session.id)

    def test_remove_run_keeps_underlying_run(self):
        session = self.manager.create_session("s")
        run_id = _seed_orchestration_run(self.conn)
        self.manager.add_run(session.id, run_id)
        removed = self.manager.remove_run(session.id, run_id)
        self.assertEqual(removed.status, "removed")
        self.assertIsNotNone(
            database.get_cross_project_orchestration_run(self.conn, run_id))
        other = self.manager.create_session("other")
        self.manager.add_run(other.id, run_id)

    def test_refresh_status_derives_blocked_and_completed(self):
        session = self.manager.create_session("s")
        blocked_run = _seed_orchestration_run(self.conn, status="blocked")
        self.manager.add_run(session.id, blocked_run)
        self.assertEqual(self.manager.get_session(session.id).status, "blocked")
        database.update_cross_project_orchestration_run_status(
            self.conn, blocked_run, "succeeded")
        self.manager.refresh_status(session.id)
        self.assertEqual(self.manager.get_session(session.id).status, "completed")


class MultiRunSessionGateTests(unittest.TestCase):
    def setUp(self):
        import multi_run_session_gates as gates
        import multi_run_sessions as sessions
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "mrg.db"))
        self.addCleanup(self.conn.close)
        self.sessions = sessions.MultiRunSessionManager(self.conn)
        self.gates = gates.MultiRunSessionGateManager(self.conn)
        self.session = self.sessions.create_session("s")

    def test_define_and_approve_gate(self):
        gate = self.gates.define_gate(self.session.id, "release window")
        self.assertEqual(gate.status, "defined")
        approved = self.gates.approve_gate(gate.id)
        self.assertEqual(approved.status, "approved")
        found = self.gates.approved_gate_for_session(self.session.id)
        self.assertEqual(found.id, gate.id)
        self.assertEqual(_count(self.conn, "cross_project_execution_confirmations"), 0)
        self.assertEqual(_count(self.conn, "cross_project_execution_snapshots"), 0)
        self.assertEqual(_count(self.conn, "cross_project_execution_attempts"), 0)

    def test_gate_requires_existing_session_and_label(self):
        with self.assertRaises(ValueError):
            self.gates.define_gate(999, "x")
        with self.assertRaises(ValueError):
            self.gates.define_gate(self.session.id, " ")

    def test_gate_linked_ids_must_exist(self):
        with self.assertRaises(ValueError):
            self.gates.define_gate(self.session.id, "g", window_ids=[999])
        with self.assertRaises(ValueError):
            self.gates.define_gate(self.session.id, "g", retry_policy_ids=[999])

    def test_revoked_gate_is_not_approved(self):
        gate = self.gates.define_gate(self.session.id, "g")
        self.gates.approve_gate(gate.id)
        self.gates.revoke_gate(gate.id)
        self.assertIsNone(self.gates.approved_gate_for_session(self.session.id))
        with self.assertRaises(ValueError):
            self.gates.approve_gate(gate.id)


if __name__ == "__main__":
    unittest.main()
