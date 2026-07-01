import os
import subprocess
import sys
import tempfile
import unittest

import database
import multi_project_registry as registry_mod
from test_cross_project_execution_dry_run import _make_plan


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _run_cli(args, cwd, env):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


class CrossProjectExecutionApprovalTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_dry_run as dry
        import cross_project_execution_approvals as approvals
        self.dry = dry
        self.approvals = approvals
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "a.db"))
        self.addCleanup(self.conn.close)
        self.root = os.path.join(self.td.name, "alpha"); os.makedirs(self.root)
        self.plan = _make_plan(self.conn, self.root)
        self.dry_run = self.dry.CrossProjectExecutionDryRunValidator(
            self.conn).validate(self.plan.id)

    def test_request_approval_from_passed_dry_run(self):
        gate = self.approvals.CrossProjectExecutionApprovalGate(self.conn)
        approval = gate.request_approval(self.plan.id, self.dry_run.id)
        self.assertEqual(approval.plan_id, self.plan.id)
        self.assertEqual(approval.dry_run_id, self.dry_run.id)
        self.assertEqual(approval.status, "pending")
        self.assertFalse(gate.is_usable(approval))

    def test_approve_makes_usable(self):
        gate = self.approvals.CrossProjectExecutionApprovalGate(self.conn)
        approval = gate.request_approval(self.plan.id, self.dry_run.id)
        approved = gate.set_status(approval.id, "approved", decided_by="tester")
        self.assertTrue(gate.is_usable(approved))

    def test_request_blocked_dry_run_fails(self):
        import cross_project_execution_intents as intents
        import cross_project_execution_readiness as readiness
        import cross_project_execution_plans as plans
        root = os.path.join(self.td.name, "beta"); os.makedirs(root)
        registry_mod.ProjectRegistry(self.conn).register_project("beta", root)
        intent = intents.CrossProjectExecutionIntentRegistry(self.conn).create_intent(
            "manual", 0, "blocked", "owner")
        ready = readiness.CrossProjectExecutionReadinessResolver(self.conn).resolve(
            intent.id)
        plan = plans.CrossProjectExecutionPlanBuilder(self.conn).build_plan(
            intent.id, ready.id)
        dry_run = self.dry.CrossProjectExecutionDryRunValidator(self.conn).validate(
            plan.id)
        with self.assertRaises(ValueError):
            self.approvals.CrossProjectExecutionApprovalGate(
                self.conn).request_approval(plan.id, dry_run.id)

    def test_mismatched_dry_run_fails(self):
        gate = self.approvals.CrossProjectExecutionApprovalGate(self.conn)
        with self.assertRaises(ValueError):
            gate.request_approval(self.plan.id + 1, self.dry_run.id)

    def test_approval_requires_latest_dry_run(self):
        newer = self.dry.CrossProjectExecutionDryRunValidator(
            self.conn).validate(self.plan.id)
        self.assertNotEqual(newer.id, self.dry_run.id)
        with self.assertRaises(ValueError):
            self.approvals.CrossProjectExecutionApprovalGate(
                self.conn).request_approval(self.plan.id, self.dry_run.id)

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
        req = _run_cli([
            "--request-cross-project-execution-approval", str(pid),
            "--dry-run", str(did)], cwd, env)
        self.assertEqual(req.returncode, 0, req.stderr)
        aid = database.list_cross_project_execution_approval_requests(conn)[0]["id"]
        setst = _run_cli([
            "--set-cross-project-execution-approval", str(aid), "approved"],
            cwd, env)
        self.assertEqual(setst.returncode, 0, setst.stderr)
        show = _run_cli(["--cross-project-execution-approval", str(aid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
