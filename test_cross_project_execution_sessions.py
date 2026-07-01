import os
import subprocess
import sys
import tempfile
import unittest

import database
from test_cross_project_execution_dry_run import _make_plan


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _run_cli(args, cwd, env):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def _seed_stage9_handoff(conn, root, packets_dir):
    import cross_project_execution_approvals as approvals
    import cross_project_execution_dry_run as dry
    import cross_project_execution_handoff as handoff

    old_dir = handoff.PACKETS_DIR
    handoff.PACKETS_DIR = packets_dir
    plan = _make_plan(conn, root)
    dry_run = dry.CrossProjectExecutionDryRunValidator(conn).validate(plan.id)
    gate = approvals.CrossProjectExecutionApprovalGate(conn)
    pending = gate.request_approval(plan.id, dry_run.id)
    approval = gate.set_status(pending.id, "approved", decided_by="test")
    packet = handoff.CrossProjectExecutionHandoffBuilder(conn).create_handoff(
        plan.id, approval.id)
    handoff.PACKETS_DIR = old_dir
    return plan, dry_run, approval, packet


class CrossProjectExecutionSessionTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_sessions as sessions
        self.sessions = sessions
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "s.db"))
        self.addCleanup(self.conn.close)
        self.root = os.path.join(self.td.name, "alpha")
        os.makedirs(self.root)
        self.plan, self.dry_run, self.approval, self.packet = _seed_stage9_handoff(
            self.conn, self.root, os.path.join(self.td.name, "packets"))

    def test_prepare_session_from_stage9_handoff(self):
        session = self.sessions.CrossProjectExecutionSessionManager(
            self.conn).prepare(self.plan.id, self.approval.id)
        self.assertEqual(session.status, "prepared")
        self.assertEqual(session.plan_id, self.plan.id)
        self.assertEqual(session.approval_id, self.approval.id)
        self.assertEqual(session.dry_run_id, self.dry_run.id)
        self.assertEqual(session.handoff_id, self.packet.id)
        self.assertTrue(session.eligible_steps)
        self.assertIn("resolve execution scope", session.required_next_controls[0])

    def test_prepare_rejects_unapproved_or_stale_approval(self):
        import cross_project_execution_approvals as approvals
        import cross_project_execution_dry_run as dry

        gate = approvals.CrossProjectExecutionApprovalGate(self.conn)
        pending = gate.request_approval(self.plan.id, self.dry_run.id)
        mgr = self.sessions.CrossProjectExecutionSessionManager(self.conn)
        with self.assertRaises(ValueError):
            mgr.prepare(self.plan.id, pending.id)
        dry.CrossProjectExecutionDryRunValidator(self.conn).validate(self.plan.id)
        with self.assertRaises(ValueError):
            mgr.prepare(self.plan.id, self.approval.id)

    def test_cli_invalid_ollama_and_no_core_side_effects(self):
        db_path = os.path.join(self.td.name, "cli.db")
        root = os.path.join(self.td.name, "cli_root")
        os.makedirs(root)
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        _run_cli(["--register-project", "alpha", "--root", root], cwd, env)
        _run_cli([
            "--create-cross-project-execution-intent", "--source-type", "manual",
            "--source-id", "0", "--title", "x", "--owner", "operator"], cwd, env)
        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        iid = database.list_cross_project_execution_intents(conn)[0]["id"]
        _run_cli(["--cross-project-execution-readiness", str(iid)], cwd, env)
        rid = database.list_cross_project_execution_readiness_reports(conn)[0]["id"]
        _run_cli(["--plan-cross-project-execution", str(iid), "--readiness", str(rid)],
                 cwd, env)
        pid = database.list_cross_project_execution_plans(conn)[0]["id"]
        _run_cli(["--propose-cross-project-execution-commands", str(pid)], cwd, env)
        _run_cli(["--dry-run-cross-project-execution", str(pid)], cwd, env)
        did = database.list_cross_project_execution_dry_runs(conn)[0]["id"]
        _run_cli(["--request-cross-project-execution-approval", str(pid),
                  "--dry-run", str(did)], cwd, env)
        aid = database.list_cross_project_execution_approval_requests(conn)[0]["id"]
        _run_cli(["--set-cross-project-execution-approval", str(aid), "approved"],
                 cwd, env)
        _run_cli(["--handoff-cross-project-execution", str(pid), "--approval", str(aid)],
                 cwd, env)
        prep = _run_cli(["--prepare-cross-project-execution", str(pid), "--approval",
                         str(aid)], cwd, env)
        self.assertEqual(prep.returncode, 0, prep.stderr)
        listing = _run_cli(["--cross-project-execution-sessions"], cwd, env)
        self.assertEqual(listing.returncode, 0, listing.stderr)
        sid = database.list_cross_project_execution_sessions(conn)[0]["id"]
        show = _run_cli(["--cross-project-execution-session", str(sid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
