import os
import tempfile
import unittest

import database


class ObservatoryDrilldownTests(unittest.TestCase):
    def test_classifies_quality_gate_failure(self):
        import observatory_drilldown

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "drilldown.db"))
            self.addCleanup(conn.close)
            loop_id = _loop(conn, "BLOCKED", "quality_gate_failed",
                            "code_build", "default")
            conn.execute(
                "INSERT INTO quality_gate_results "
                "(loop_id, attempt_number, gate_name, passed, required, severity, message) "
                "VALUES (?, 1, 'external_agent_changes_within_workspace', 0, 1, "
                "'error', 'blocked')",
                (loop_id,),
            )
            conn.commit()

            report = observatory_drilldown.ObservatoryDrilldownEngine(conn).build_report()

            self.assertEqual(report.total_failures, 1)
            self.assertEqual(report.items[0].failure_category, "quality_gate_failed")
            self.assertEqual(report.items[0].failed_quality_gates,
                             ["external_agent_changes_within_workspace"])

    def test_classifies_stop_condition_and_command_failure(self):
        import observatory_drilldown

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "drilldown.db"))
            self.addCleanup(conn.close)
            stop_id = _loop(conn, "FAILED", "max_retries_reached",
                            "test_fix", "default")
            conn.execute(
                "INSERT INTO stop_condition_results "
                "(loop_id, attempt_number, condition_name, triggered, severity, message) "
                "VALUES (?, 1, 'max_retries_reached', 1, 'error', 'stopped')",
                (stop_id,),
            )
            cmd_id = _loop(conn, "FAILED", "command_failed",
                           "test_fix", "default")
            conn.execute(
                "INSERT INTO command_results "
                "(loop_id, attempt_number, command, allowed, exit_code, stdout, stderr, "
                "duration_seconds, timed_out) VALUES "
                "(?, 1, 'python3 workspace/test_x.py', 1, 1, '', 'failed', 0.1, 0)",
                (cmd_id,),
            )
            conn.commit()

            report = observatory_drilldown.ObservatoryDrilldownEngine(conn).build_report(
                limit=10)
            by_id = {item.loop_id: item for item in report.items}

            self.assertEqual(by_id[stop_id].failure_category, "stop_condition_triggered")
            self.assertEqual(by_id[stop_id].triggered_stop_conditions,
                             ["max_retries_reached"])
            self.assertEqual(by_id[cmd_id].failure_category, "command_failed")

    def test_clusters_by_category_workspace_and_quality_gate(self):
        import observatory_drilldown

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "drilldown.db"))
            self.addCleanup(conn.close)
            loop_a = _loop(conn, "BLOCKED", "gate", "code_build", "alpha")
            loop_b = _loop(conn, "BLOCKED", "gate", "code_build", "beta")
            for loop_id in (loop_a, loop_b):
                conn.execute(
                    "INSERT INTO quality_gate_results "
                    "(loop_id, attempt_number, gate_name, passed, required, severity, message) "
                    "VALUES (?, 1, 'workspace_safe', 0, 1, 'error', 'blocked')",
                    (loop_id,),
                )
            conn.commit()
            engine = observatory_drilldown.ObservatoryDrilldownEngine(conn)

            category = engine.build_report(cluster_by="category")
            workspace = engine.build_report(cluster_by="workspace")
            gate = engine.build_report(cluster_by="quality_gate")

            self.assertEqual(category.clusters[0].cluster_key, "quality_gate_failed")
            self.assertEqual(category.clusters[0].count, 2)
            self.assertEqual({c.cluster_key for c in workspace.clusters},
                             {"alpha", "beta"})
            self.assertEqual(gate.clusters[0].cluster_key, "workspace_safe")

    def test_persistence_and_markdown_path_safety(self):
        import observatory_drilldown

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "drilldown.db"))
            self.addCleanup(conn.close)
            observatory_drilldown.REPORTS_DIR = os.path.join(td, "failure_reports")
            _loop(conn, "BLOCKED", "approval_declined", "code_build", "default")
            engine = observatory_drilldown.ObservatoryDrilldownEngine(conn)
            report = engine.build_report()
            drilldown_id = engine.save_drilldown(report, cluster_by="category")
            md = engine.save_markdown_report(drilldown_id, report)

            stored = database.get_observatory_failure_drilldown(conn, drilldown_id)
            self.assertEqual(stored["id"], drilldown_id)
            self.assertEqual(len(database.list_observatory_failure_drilldowns(conn)), 1)
            self.assertTrue(os.path.exists(md.report_path))
            base = os.path.realpath(observatory_drilldown.REPORTS_DIR)
            self.assertTrue(os.path.realpath(md.report_path).startswith(base + os.sep))
            self.assertEqual(_count(conn, "observatory_failure_markdown_reports"), 1)

    def test_drilldown_generation_only_adds_drilldown_metadata(self):
        import observatory_drilldown

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "drilldown.db"))
            self.addCleanup(conn.close)
            observatory_drilldown.REPORTS_DIR = os.path.join(td, "failure_reports")
            _loop(conn, "FAILED", "command_failed", "test_fix", "default")
            before_loops = _count(conn, "loops")
            before_commands = _count(conn, "command_results")
            engine = observatory_drilldown.ObservatoryDrilldownEngine(conn)

            report = engine.build_report()
            drilldown_id = engine.save_drilldown(report, cluster_by="category")
            engine.save_markdown_report(drilldown_id, report)

            self.assertEqual(_count(conn, "loops"), before_loops)
            self.assertEqual(_count(conn, "command_results"), before_commands)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _loop(conn, status, stop_reason, loop_type, workspace):
    loop_id = database.insert_loop(
        conn,
        f"{loop_type} {status}",
        "supervisor",
        "coder",
        "reviewer",
        loop_type=loop_type,
        loop_version="1.0",
        workspace_name=workspace,
        workspace_root=os.getcwd(),
    )
    database.finish_loop(conn, loop_id, status, stop_reason, 0, 0.0)
    return loop_id


if __name__ == "__main__":
    unittest.main()
