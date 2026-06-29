import json
import os
import tempfile
import unittest

import database


class ObservatoryRemediationTests(unittest.TestCase):
    def test_remediation_from_snapshot(self):
        import observatory_remediation

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "remediation.db"))
            self.addCleanup(conn.close)
            snapshot_id = _snapshot(conn)

            plan = observatory_remediation.ObservatoryRemediationEngine(conn).build_plan(
                source_type="snapshot", source_id=snapshot_id)

            self.assertEqual(plan.source_type, "snapshot")
            self.assertEqual(plan.source_id, snapshot_id)
            self.assertGreaterEqual(plan.total_items, 1)
            self.assertTrue(any(i.category == "external_agent_health"
                                for i in plan.items))
            self.assertTrue(all(i.suggested_command.startswith("python3 main.py ")
                                for i in plan.items))

    def test_remediation_from_trend_report(self):
        import observatory_remediation

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "remediation.db"))
            self.addCleanup(conn.close)
            trend_id = _trend_report(conn)

            plan = observatory_remediation.ObservatoryRemediationEngine(conn).build_plan(
                source_type="trend", source_id=trend_id)

            self.assertEqual(plan.source_type, "trend")
            self.assertTrue(any(i.category == "reliability" for i in plan.items))
            self.assertTrue(any(i.priority == "high" for i in plan.items))

    def test_remediation_from_failure_drilldown(self):
        import observatory_remediation

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "remediation.db"))
            self.addCleanup(conn.close)
            drilldown_id = _failure_drilldown(conn)

            plan = observatory_remediation.ObservatoryRemediationEngine(conn).build_plan(
                source_type="failure_drilldown", source_id=drilldown_id)

            self.assertEqual(plan.source_type, "failure_drilldown")
            self.assertTrue(any(i.category == "testing" for i in plan.items))
            self.assertTrue(any(44 in i.affected_loop_ids for i in plan.items))

    def test_priority_and_category_filtering(self):
        import observatory_remediation

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "remediation.db"))
            self.addCleanup(conn.close)
            _snapshot(conn)
            _trend_report(conn)
            drilldown_id = _failure_drilldown(conn)
            engine = observatory_remediation.ObservatoryRemediationEngine(conn)

            high = engine.build_plan(source_type="failure_drilldown",
                                     source_id=drilldown_id, priority="high")
            safety = engine.build_plan(source_type="snapshot",
                                       source_id=1, category="external_agent_health")

            self.assertTrue(high.items)
            self.assertTrue(all(i.priority == "high" for i in high.items))
            self.assertTrue(safety.items)
            self.assertTrue(all(i.category == "external_agent_health"
                                for i in safety.items))

    def test_plan_persistence_and_markdown_path_safety(self):
        import observatory_remediation

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "remediation.db"))
            self.addCleanup(conn.close)
            observatory_remediation.REPORTS_DIR = os.path.join(td, "remediation_reports")
            snapshot_id = _snapshot(conn)
            engine = observatory_remediation.ObservatoryRemediationEngine(conn)
            plan = engine.build_plan(source_type="snapshot", source_id=snapshot_id)
            plan_id = engine.save_plan(plan, {"source": "snapshot"})
            md = engine.save_markdown_report(plan_id, plan)

            stored = database.get_observatory_remediation_plan(conn, plan_id)
            self.assertEqual(stored["id"], plan_id)
            self.assertEqual(len(database.list_observatory_remediation_plans(conn)), 1)
            self.assertTrue(os.path.exists(md.report_path))
            base = os.path.realpath(observatory_remediation.REPORTS_DIR)
            self.assertTrue(os.path.realpath(md.report_path).startswith(base + os.sep))

    def test_remediation_generation_only_adds_metadata(self):
        import observatory_remediation

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "remediation.db"))
            self.addCleanup(conn.close)
            observatory_remediation.REPORTS_DIR = os.path.join(td, "remediation_reports")
            snapshot_id = _snapshot(conn)
            before_loops = _count(conn, "loops")
            before_commands = _count(conn, "command_results")
            engine = observatory_remediation.ObservatoryRemediationEngine(conn)

            plan = engine.build_plan(source_type="snapshot", source_id=snapshot_id)
            plan_id = engine.save_plan(plan, {"source": "snapshot"})
            engine.save_markdown_report(plan_id, plan)

            self.assertEqual(_count(conn, "loops"), before_loops)
            self.assertEqual(_count(conn, "command_results"), before_commands)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _snapshot(conn):
    summary = {
        "generated_at": "2026-06-27T12:00:00",
        "time_window": {"name": "all", "start_at": None, "end_at": "2026-06-27T12:00:00"},
        "blocked_loops": 6,
        "waiting_external_jobs": 3,
        "quality_gate_failures": 8,
        "declined_approvals": 2,
        "alerts": [
            {
                "severity": "critical",
                "alert_type": "health_critical_issues",
                "message": "critical external job health events exist",
                "recommended_action": "python3 main.py --external-health",
                "details_json": "{}",
            }
        ],
    }
    return database.save_observatory_snapshot(
        conn,
        summary["generated_at"],
        "all",
        json.dumps({"window": "all"}, sort_keys=True),
        json.dumps(summary, sort_keys=True),
        1,
        1,
        0,
    )


def _trend_report(conn):
    trends = [
        {
            "metric_name": "blocked_loops",
            "points": [],
            "first_value": 2,
            "last_value": 7,
            "delta": 5,
            "percent_change": 250.0,
            "direction": "up",
            "interpretation": "negative: worsening",
        }
    ]
    return database.save_observatory_trend_report(
        conn,
        "2026-06-27T12:00:00",
        2,
        1,
        2,
        json.dumps({"limit": 10}, sort_keys=True),
        json.dumps(trends, sort_keys=True),
        json.dumps(["blocked loops increased"], sort_keys=True),
        json.dumps(["python3 main.py --observatory-failures"], sort_keys=True),
    )


def _failure_drilldown(conn):
    items = [
        {
            "loop_id": 44,
            "created_at": "2026-06-27T12:00:00",
            "task_preview": "fix tests",
            "loop_type": "test_fix",
            "workspace_name": "default",
            "status": "BLOCKED",
            "stop_reason": "quality_gate_failed",
            "failure_category": "quality_gate_failed",
            "root_cause_hint": "failed quality gate: files_written",
            "agent_role": "reviewer",
            "agent_name": "reviewer",
            "model": "llama",
            "failed_quality_gates": ["files_written"],
            "triggered_stop_conditions": [],
            "external_job_status": "",
            "report_path": "reports/loop_44.md",
            "recommended_action": "python3 main.py --report 44",
        }
    ]
    clusters = [
        {
            "cluster_key": "quality_gate_failed",
            "cluster_type": "category",
            "count": 4,
            "loop_ids": [44, 45, 46, 47],
            "representative_reason": "failed quality gate: files_written",
            "recommended_action": "python3 main.py --observatory-failures --category quality_gate_failed",
        }
    ]
    return database.save_observatory_failure_drilldown(
        conn,
        "2026-06-27T12:00:00",
        json.dumps({"cluster_by": "category"}, sort_keys=True),
        "category",
        4,
        json.dumps(items, sort_keys=True),
        json.dumps(clusters, sort_keys=True),
        json.dumps(["python3 main.py --report 44"], sort_keys=True),
    )


if __name__ == "__main__":
    unittest.main()
