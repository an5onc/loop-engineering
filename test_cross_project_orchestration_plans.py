import os
import subprocess
import sys
import tempfile
import unittest

import database
from test_cross_project_execution_sessions import _count, _seed_stage9_handoff


def _run_cli(args, cwd, env):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def _seed_stage10_scope(conn, root, packets_dir):
    import cross_project_execution_scope as scope
    import cross_project_execution_sessions as sessions

    plan, dry_run, approval, packet = _seed_stage9_handoff(conn, root, packets_dir)
    session = sessions.CrossProjectExecutionSessionManager(conn).prepare(
        plan.id, approval.id)
    checks = scope.CrossProjectExecutionScopeResolver(conn).resolve(session.id)
    return plan, dry_run, approval, packet, session, checks


class CrossProjectOrchestrationPlanTests(unittest.TestCase):
    def setUp(self):
        import cross_project_orchestration_plans as orchestration
        self.orchestration = orchestration
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "o.db"))
        self.addCleanup(self.conn.close)
        self.root = os.path.join(self.td.name, "alpha")
        os.makedirs(self.root)
        self.plan, self.dry_run, self.approval, self.packet, self.session, self.checks = (
            _seed_stage10_scope(
                self.conn, self.root, os.path.join(self.td.name, "packets")))

    def test_build_plan_from_prepared_session_and_scope(self):
        plan = self.orchestration.CrossProjectOrchestrationPlanBuilder(
            self.conn).build_plan(self.session.id)
        self.assertEqual(plan.session_id, self.session.id)
        self.assertEqual(plan.status, "planned")
        self.assertEqual(plan.ready_steps, 1)
        self.assertEqual(plan.blocked_steps, 0)
        self.assertEqual(plan.steps[0].stage10_scope_check_id, self.checks[0].id)
        self.assertEqual(plan.steps[0].status, "ready")
        self.assertEqual(_count(self.conn, "cross_project_execution_attempts"), 0)
        self.assertEqual(_count(self.conn, "command_results"), 0)
        self.assertEqual(_count(self.conn, "external_agent_jobs"), 0)

    def test_plan_requires_resolved_scope(self):
        self.conn.execute(
            "DELETE FROM cross_project_execution_scope_checks WHERE session_id=?",
            (self.session.id,))
        self.conn.commit()
        with self.assertRaises(ValueError):
            self.orchestration.CrossProjectOrchestrationPlanBuilder(
                self.conn).build_plan(self.session.id)

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
        _run_cli(["--prepare-cross-project-execution", str(pid), "--approval", str(aid)],
                 cwd, env)
        sid = database.list_cross_project_execution_sessions(conn)[0]["id"]
        _run_cli(["--resolve-cross-project-execution-scope", str(sid)], cwd, env)
        created = _run_cli(["--plan-cross-project-orchestration", str(sid)], cwd, env)
        self.assertEqual(created.returncode, 0, created.stderr)
        listing = _run_cli(["--cross-project-orchestration-plans"], cwd, env)
        self.assertEqual(listing.returncode, 0, listing.stderr)
        oid = database.list_cross_project_orchestration_plans(conn)[0]["id"]
        shown = _run_cli(["--cross-project-orchestration-plan", str(oid)], cwd, env)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertEqual(_count(conn, "cross_project_execution_attempts"), 0)
        self.assertEqual(_count(conn, "loops"), 0)


if __name__ == "__main__":
    unittest.main()
