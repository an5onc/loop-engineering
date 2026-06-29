import json
import os
import tempfile
import unittest

import database


class ObservatoryTests(unittest.TestCase):
    def test_builds_summary_with_filters_and_alerts(self):
        import observatory

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "obs.db"))
            _loop(conn, "APPROVED", "reviewer_approved", "code_build", "default")
            _loop(conn, "FAILED", "command_failed", "test_fix", "default")
            blocked_id = _loop(conn, "BLOCKED", "resume_workspace_violation",
                               "code_build", "prod")
            paused_id = _loop(conn, "PAUSED_EXTERNAL_AGENT", "needs_external_agent",
                              "code_build", "prod")
            conn.execute(
                "INSERT INTO external_agent_jobs "
                "(loop_id, external_agent_name, status, workspace_name, created_at, archived) "
                "VALUES (?, 'claude', 'WAITING_FOR_EXTERNAL_AGENT', 'prod', "
                "datetime('now', '-2 days'), 0)",
                (paused_id,),
            )
            conn.execute(
                "INSERT INTO external_agent_jobs "
                "(id, loop_id, external_agent_name, status, workspace_name, created_at, archived) "
                "VALUES (99, ?, 'claude', 'WAITING_FOR_EXTERNAL_AGENT', 'prod', "
                "datetime('now', '-2 days'), 1)",
                (paused_id,),
            )
            conn.execute(
                "INSERT INTO external_job_health_events "
                "(job_id, loop_id, severity, issue_type, message) "
                "VALUES (99, ?, 'critical', 'protected_content_risk', 'archived fixture')",
                (paused_id,),
            )
            conn.execute(
                "INSERT INTO run_reports (loop_id, report_path, report_format, content_hash, bytes_written) "
                "VALUES (?, 'reports/x.md', 'markdown', 'h', 10)",
                (blocked_id,),
            )
            conn.execute(
                "INSERT INTO approval_events (loop_id, attempt_number, gate_name, action_type, "
                "risk_level, decision, approved, summary) VALUES "
                "(?, 0, 'gate', 'git_commit', 'high', 'declined', 0, 'no')",
                (blocked_id,),
            )
            conn.execute(
                "INSERT INTO quality_gate_results (loop_id, gate_name, passed, required, severity, message) "
                "VALUES (?, 'external_agent_changes_within_workspace', 0, 1, 'error', 'blocked')",
                (blocked_id,),
            )
            conn.execute(
                "INSERT INTO stop_condition_results (loop_id, condition_name, triggered, severity, message) "
                "VALUES (?, 'resume_workspace_violation', 1, 'critical', 'blocked')",
                (blocked_id,),
            )
            conn.commit()

            summary = observatory.ObservatoryEngine(conn).build_summary(
                window="all", workspace="prod")
            self.assertEqual(summary.total_loops, 2)
            self.assertEqual(summary.blocked_loops, 1)
            self.assertEqual(summary.paused_external_loops, 1)
            self.assertEqual(summary.waiting_external_jobs, 1)
            self.assertEqual(summary.external_job_health["waiting"], 1)
            self.assertEqual(summary.external_job_health["archived"], 1)
            self.assertEqual(summary.declined_approvals, 1)
            self.assertEqual(summary.quality_gate_failures, 1)
            self.assertEqual(summary.stop_condition_triggers, 1)
            self.assertEqual(summary.top_workspaces[0]["workspace"], "prod")
            self.assertTrue(any(a.alert_type == "stale_external_jobs"
                                for a in summary.alerts))
            self.assertFalse(any(a.alert_type == "health_critical_issues"
                                 for a in summary.alerts))

    def test_snapshots_persist_summary_json(self):
        import observatory

        with tempfile.TemporaryDirectory() as td:
            conn = database.init_db(os.path.join(td, "obs.db"))
            _loop(conn, "APPROVED", "reviewer_approved", "prompt_design", "default")
            engine = observatory.ObservatoryEngine(conn)
            summary = engine.build_summary(window="all")
            snapshot_id = database.save_observatory_snapshot(
                conn, summary.generated_at, summary.time_window.name,
                json.dumps({"workspace": None}),
                json.dumps(observatory.summary_to_dict(summary)),
                len(summary.alerts),
                sum(1 for a in summary.alerts if a.severity == "critical"),
                sum(1 for a in summary.alerts if a.severity == "warning"),
            )
            stored = database.get_observatory_snapshot(conn, snapshot_id)
            self.assertEqual(stored["id"], snapshot_id)
            self.assertEqual(json.loads(stored["summary_json"])["total_loops"], 1)
            self.assertEqual(len(database.list_observatory_snapshots(conn)), 1)


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
