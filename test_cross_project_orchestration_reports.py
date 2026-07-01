import os
import tempfile
import unittest

import database
from test_cross_project_orchestration_plans import _seed_stage10_scope


class CrossProjectOrchestrationReportTests(unittest.TestCase):
    def test_report_persists_markdown_in_guarded_directory(self):
        import cross_project_orchestration_dry_run as dry_run
        import cross_project_orchestration_plans as plans
        import cross_project_orchestration_reports as reports
        import cross_project_orchestration_runs as runs
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        conn = database.init_db(os.path.join(td.name, "rep.db"))
        self.addCleanup(conn.close)
        root = os.path.join(td.name, "alpha")
        os.makedirs(root)
        _, _, _, _, session, _ = _seed_stage10_scope(
            conn, root, os.path.join(td.name, "packets"))
        plan = plans.CrossProjectOrchestrationPlanBuilder(conn).build_plan(session.id)
        d = dry_run.CrossProjectOrchestrationDryRunValidator(conn).validate(plan.id)
        run = runs.CrossProjectOrchestrationRunManager(conn).start(plan.id, d.id)
        old_dir = reports.REPORTS_DIR
        reports.REPORTS_DIR = os.path.join(td.name, "reports")
        self.addCleanup(setattr, reports, "REPORTS_DIR", old_dir)
        engine = reports.CrossProjectOrchestrationReportBuilder(conn)
        report = engine.build_report(run.id)
        rid = engine.save_report(report)
        path = engine.save_markdown_report(rid, report)
        self.assertTrue(path.startswith(os.path.realpath(reports.REPORTS_DIR)))
        self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
