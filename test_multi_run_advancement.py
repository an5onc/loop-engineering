import os
import tempfile
import unittest

import database
from test_cross_project_execution_sessions import _count
from test_cross_project_restoration_targets import seed_blocked_run


class MultiRunSessionAdvancementTests(unittest.TestCase):
    def setUp(self):
        import multi_run_advancement as advancement
        import multi_run_session_gates as gates
        import multi_run_sessions as sessions
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "ma.db"))
        self.addCleanup(self.conn.close)
        self.seed = seed_blocked_run(self.conn, self.td.name,
                                     command_text="pwd", advance=False)
        self.sessions = sessions.MultiRunSessionManager(self.conn)
        self.gates = gates.MultiRunSessionGateManager(self.conn)
        self.engine = advancement.MultiRunSessionAdvancementEngine(self.conn)
        self.session = self.sessions.create_session("s")
        self.sessions.add_run(self.session.id, self.seed["run"].id)

    def _approve_gate(self):
        gate = self.gates.define_gate(self.session.id, "go")
        return self.gates.approve_gate(gate.id)

    def _advance(self, **overrides):
        kwargs = dict(
            session_id=self.session.id, run_id=self.seed["run"].id,
            step_id=self.seed["step"].step_id,
            confirmation_id=self.seed["confirmation"].id,
            snapshot_id=self.seed["snapshot"].id, confirm_execution=True)
        kwargs.update(overrides)
        return self.engine.advance(**kwargs)

    def test_requires_explicit_confirm_execution(self):
        self._approve_gate()
        with self.assertRaises(ValueError):
            self._advance(confirm_execution=False)
        self.assertEqual(_count(self.conn, "cross_project_execution_attempts"), 0)
        self.assertEqual(_count(self.conn, "multi_run_session_advancements"), 0)

    def test_requires_approved_session_gate(self):
        with self.assertRaises(ValueError):
            self._advance()
        gate = self.gates.define_gate(self.session.id, "g")
        with self.assertRaises(ValueError):
            self._advance()
        self.gates.approve_gate(gate.id)
        self.gates.revoke_gate(gate.id)
        with self.assertRaises(ValueError):
            self._advance()
        self.assertEqual(_count(self.conn, "cross_project_execution_attempts"), 0)

    def test_requires_member_run_and_open_session(self):
        self._approve_gate()
        with self.assertRaises(ValueError):
            self._advance(run_id=999)
        with self.assertRaises(ValueError):
            self._advance(session_id=999)
        self.sessions.close_session(self.session.id)
        with self.assertRaises(ValueError):
            self._advance()
        self.assertEqual(_count(self.conn, "cross_project_execution_attempts"), 0)

    def test_advance_delegates_to_stage12_and_records_row(self):
        self._approve_gate()
        result = self._advance()
        self.assertEqual(result.status, "executed")
        self.assertIsNotNone(result.gated_advancement_id)
        gated = database.get_cross_project_gated_advancement(
            self.conn, result.gated_advancement_id)
        self.assertEqual(gated["attempt_id"], result.attempt_id)
        self.assertEqual(_count(self.conn, "cross_project_execution_attempts"), 1)
        self.assertEqual(_count(self.conn, "multi_run_session_advancements"), 1)
        self.assertEqual(_count(self.conn, "command_results"), 0)
        self.assertEqual(_count(self.conn, "external_agent_jobs"), 0)
        self.assertEqual(_count(self.conn, "loops"), 0)

    def test_stage12_refusal_recorded_as_refused_row(self):
        import cross_project_execution_window_controls as controls
        self._approve_gate()
        controls.CrossProjectExecutionWindowControlGate(self.conn).close_window(
            self.seed["window"].id)
        with self.assertRaises(ValueError):
            self._advance()
        rows = database.list_multi_run_session_advancements(
            self.conn, session_id=self.session.id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "refused")
        self.assertIsNone(rows[0]["attempt_id"])
        self.assertIsNone(rows[0]["gated_advancement_id"])
        self.assertEqual(_count(self.conn, "cross_project_execution_attempts"), 0)

    def test_missing_step_refused_and_recorded(self):
        self._approve_gate()
        with self.assertRaises(ValueError):
            self._advance(step_id=999)
        rows = database.list_multi_run_session_advancements(
            self.conn, session_id=self.session.id)
        self.assertEqual(rows[0]["status"], "refused")

    def test_recovery_needed_refuses_before_delegation(self):
        import cross_project_gated_advancement as gated
        self._approve_gate()
        self.conn.execute(
            "UPDATE cross_project_execution_command_proposals SET "
            "command_text='python3 missing_script.py' WHERE id=?",
            (self.seed["proposal_id"],))
        self.conn.commit()
        gated.CrossProjectGatedAdvancementEngine(self.conn).advance(
            self.seed["run"].id, self.seed["step"].step_id,
            self.seed["confirmation"].id, self.seed["snapshot"].id,
            confirm_execution=True)
        with self.assertRaises(ValueError) as ctx:
            self._advance()
        self.assertIn("needs recovery", str(ctx.exception))
        self.assertEqual(_count(self.conn, "cross_project_execution_attempts"), 1)


if __name__ == "__main__":
    unittest.main()
