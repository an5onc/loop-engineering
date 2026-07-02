import os
import tempfile
import unittest

import database
from test_cross_project_restoration_targets import seed_blocked_run


class CrossProjectRestorationOutcomeTests(unittest.TestCase):
    def setUp(self):
        import cross_project_gated_restoration as gated
        import cross_project_restoration_outcomes as outcomes
        import cross_project_restoration_previews as previews
        self.outcomes = outcomes
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "oc.db"))
        self.addCleanup(self.conn.close)
        self.seed = seed_blocked_run(self.conn, self.td.name)
        self.binder = outcomes.CrossProjectRestorationOutcomeBinder(self.conn)
        self.previews = previews.CrossProjectRestorationPreviewBinder(self.conn)
        self.engine = gated.CrossProjectGatedRestorationEngine(self.conn)

    def test_record_requires_completed_restoration(self):
        with self.assertRaises(ValueError):
            self.binder.record(self.seed["run"].id, self.seed["step"].id)

    def test_record_yields_rolled_back_outcome(self):
        self.previews.preview(self.seed["run"].id, self.seed["step"].step_id)
        restoration = self.engine.restore(
            self.seed["run"].id, self.seed["step"].step_id, confirm_restore=True)
        result = self.binder.record(self.seed["run"].id, self.seed["step"].id)
        self.assertEqual(result.status, "rolled_back")
        self.assertEqual(result.rollback_id, restoration.rollback_id)
        outcome = database.get_cross_project_execution_outcome(
            self.conn, result.outcome_id)
        self.assertEqual(outcome["status"], "rolled_back")
        self.assertEqual(outcome["rollback_restore_id"], restoration.restore_id)

    def test_record_is_idempotent_for_same_restoration(self):
        from test_cross_project_execution_sessions import _count
        self.previews.preview(self.seed["run"].id, self.seed["step"].step_id)
        self.engine.restore(
            self.seed["run"].id, self.seed["step"].step_id, confirm_restore=True)
        first = self.binder.record(self.seed["run"].id, self.seed["step"].id)
        second = self.binder.record(self.seed["run"].id, self.seed["step"].id)
        self.assertEqual(first.id, second.id)
        self.assertEqual(_count(self.conn, "cross_project_restoration_outcomes"), 1)
        self.assertEqual(_count(self.conn, "cross_project_execution_outcomes"), 1)


if __name__ == "__main__":
    unittest.main()
