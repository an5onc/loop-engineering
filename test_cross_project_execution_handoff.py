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


class CrossProjectExecutionHandoffTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_dry_run as dry
        import cross_project_execution_approvals as approvals
        import cross_project_execution_handoff as handoff
        self.dry = dry
        self.approvals = approvals
        self.handoff = handoff
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "h.db"))
        self.addCleanup(self.conn.close)
        self.root = os.path.join(self.td.name, "alpha"); os.makedirs(self.root)
        self.secret = "STAGE9_SECRET_VALUE"
        with open(os.path.join(self.root, "secret.env"), "w") as fh:
            fh.write(self.secret)
        self.plan = _make_plan(self.conn, self.root)
        self.dry_run = self.dry.CrossProjectExecutionDryRunValidator(
            self.conn).validate(self.plan.id)
        gate = self.approvals.CrossProjectExecutionApprovalGate(self.conn)
        pending = gate.request_approval(self.plan.id, self.dry_run.id)
        self.approval = gate.set_status(pending.id, "approved", decided_by="t")
        self.old_dir = self.handoff.PACKETS_DIR
        self.handoff.PACKETS_DIR = os.path.join(self.td.name, "packets")
        self.addCleanup(setattr, self.handoff, "PACKETS_DIR", self.old_dir)

    def test_create_handoff_packet_with_approved_approval(self):
        packet = self.handoff.CrossProjectExecutionHandoffBuilder(
            self.conn).create_handoff(self.plan.id, self.approval.id)
        self.assertEqual(packet.status, "created")
        self.assertTrue(self.handoff.is_packet_path(packet.packet_path))
        self.assertTrue(os.path.exists(packet.packet_path))

    def test_packet_excludes_protected_contents_and_db_snapshot(self):
        packet = self.handoff.CrossProjectExecutionHandoffBuilder(
            self.conn).create_handoff(self.plan.id, self.approval.id)
        with open(packet.packet_path, encoding="utf-8") as fh:
            content = fh.read()
        self.assertNotIn(self.secret, content)
        self.assertNotIn("sqlite", content.lower())
        self.assertIn("Advisory Commands", content)
        self.assertIn("Do not execute automatically", content)

    def test_pending_or_mismatched_approval_fails_closed(self):
        gate = self.approvals.CrossProjectExecutionApprovalGate(self.conn)
        pending = gate.request_approval(self.plan.id, self.dry_run.id)
        builder = self.handoff.CrossProjectExecutionHandoffBuilder(self.conn)
        with self.assertRaises(ValueError):
            builder.create_handoff(self.plan.id, pending.id)
        with self.assertRaises(ValueError):
            builder.create_handoff(self.plan.id + 1, self.approval.id)

    def test_handoff_requires_latest_dry_run(self):
        self.dry.CrossProjectExecutionDryRunValidator(self.conn).validate(
            self.plan.id)
        with self.assertRaises(ValueError):
            self.handoff.CrossProjectExecutionHandoffBuilder(
                self.conn).create_handoff(self.plan.id, self.approval.id)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        _run_cli(["--register-project", "alpha", "--root", self.root], cwd, env)
        _run_cli([
            "--create-cross-project-execution-intent", "--source-type", "manual",
            "--source-id", "0", "--title", "x", "--owner", "operator"], cwd, env)
        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        iid = database.list_cross_project_execution_intents(conn)[0]["id"]
        _run_cli(["--cross-project-execution-readiness", str(iid)], cwd, env)
        rid = database.list_cross_project_execution_readiness_reports(conn)[0]["id"]
        _run_cli([
            "--plan-cross-project-execution", str(iid), "--readiness", str(rid)],
            cwd, env)
        pid = database.list_cross_project_execution_plans(conn)[0]["id"]
        _run_cli(["--propose-cross-project-execution-commands", str(pid)], cwd, env)
        _run_cli(["--dry-run-cross-project-execution", str(pid)], cwd, env)
        did = database.list_cross_project_execution_dry_runs(conn)[0]["id"]
        _run_cli([
            "--request-cross-project-execution-approval", str(pid),
            "--dry-run", str(did)], cwd, env)
        aid = database.list_cross_project_execution_approval_requests(conn)[0]["id"]
        _run_cli([
            "--set-cross-project-execution-approval", str(aid), "approved"],
            cwd, env)
        ho = _run_cli([
            "--handoff-cross-project-execution", str(pid), "--approval", str(aid)],
            cwd, env)
        self.assertEqual(ho.returncode, 0, ho.stderr)
        lst = _run_cli(["--cross-project-execution-handoffs"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)
        hid = database.list_cross_project_execution_handoffs(conn)[0]["id"]
        show = _run_cli(["--cross-project-execution-handoff", str(hid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
