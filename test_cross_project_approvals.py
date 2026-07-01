import os
import subprocess
import sys
import tempfile
import unittest

import database
import multi_project_registry as registry_mod
import cross_project_planner as planner_mod


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _run_cli(args, cwd, env):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


class CrossProjectApprovalTests(unittest.TestCase):
    def setUp(self):
        import cross_project_approvals as approvals
        self.approvals = approvals
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "ap.db"))
        self.addCleanup(self.conn.close)
        self.registry = registry_mod.ProjectRegistry(self.conn)
        self.a = os.path.join(self.td.name, "a"); os.makedirs(self.a)
        self.registry.register_project("alpha", self.a)
        self.plan = planner_mod.CrossProjectPlanner(self.conn).plan_work("work")

    def test_request_approval_pending(self):
        gate = self.approvals.CrossProjectApprovalGate(self.conn)
        approval = gate.request_approval(self.plan.id)
        self.assertEqual(approval.status, "pending")
        self.assertEqual(approval.plan_id, self.plan.id)
        self.assertFalse(gate.is_usable(approval))

    def test_request_invalid_plan_fails(self):
        gate = self.approvals.CrossProjectApprovalGate(self.conn)
        with self.assertRaises(ValueError):
            gate.request_approval(99999)

    def test_approve_makes_usable(self):
        gate = self.approvals.CrossProjectApprovalGate(self.conn)
        approval = gate.request_approval(self.plan.id)
        approved = gate.set_status(approval.id, "approved", decided_by="tester")
        self.assertEqual(approved.status, "approved")
        self.assertTrue(gate.is_usable(approved))

    def test_rejected_not_usable(self):
        gate = self.approvals.CrossProjectApprovalGate(self.conn)
        approval = gate.request_approval(self.plan.id)
        rejected = gate.set_status(approval.id, "rejected")
        self.assertFalse(gate.is_usable(rejected))

    def test_invalid_status_rejected(self):
        gate = self.approvals.CrossProjectApprovalGate(self.conn)
        approval = gate.request_approval(self.plan.id)
        with self.assertRaises(ValueError):
            gate.set_status(approval.id, "yes")

    def test_persistence_and_listing(self):
        gate = self.approvals.CrossProjectApprovalGate(self.conn)
        approval = gate.request_approval(self.plan.id)
        self.assertGreater(approval.id, 0)
        reloaded = gate.get_approval(approval.id)
        self.assertEqual(reloaded.plan_id, self.plan.id)
        self.assertEqual(
            database.list_cross_project_approvals(self.conn)[0]["id"], approval.id)

    def test_no_side_effect_tables(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        gate = self.approvals.CrossProjectApprovalGate(self.conn)
        approval = gate.request_approval(self.plan.id)
        gate.set_status(approval.id, "approved")
        self.assertEqual({t: _count(self.conn, t) for t in before}, before)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        _run_cli(["--register-project", "alpha", "--root", self.a], cwd, env)
        _run_cli(["--plan-cross-project-work", "work"], cwd, env)

        req = _run_cli(["--request-cross-project-approval", "latest"], cwd, env)
        self.assertEqual(req.returncode, 0, req.stderr)

        lst = _run_cli(["--cross-project-approvals"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)

        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        aid = database.list_cross_project_approvals(conn)[0]["id"]
        show = _run_cli(["--cross-project-approval", str(aid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)

        decide = _run_cli(
            ["--set-cross-project-approval", str(aid), "approved"], cwd, env)
        self.assertEqual(decide.returncode, 0, decide.stderr)

        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
