import os
import tempfile
import unittest

import database


class CrossProjectOrchestrationAuditTests(unittest.TestCase):
    def test_audit_passes_empty_state_and_detects_missing_snapshot_bypass(self):
        import cross_project_orchestration_audit as audit
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        conn = database.init_db(os.path.join(td.name, "a.db"))
        self.addCleanup(conn.close)
        engine = audit.CrossProjectOrchestrationAuditEngine(conn)
        report = engine.build_report()
        self.assertEqual(report.overall_status, "PASS")
        conn.execute(
            "INSERT INTO cross_project_orchestration_step_advancements "
            "(run_id, run_step_id, orchestration_step_id, confirmation_id, "
            "snapshot_id, attempt_id, status, safety_notes_json) "
            "VALUES (1,1,1,1,NULL,1,'executed','[]')")
        conn.commit()
        report = engine.build_report()
        self.assertEqual(report.overall_status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
