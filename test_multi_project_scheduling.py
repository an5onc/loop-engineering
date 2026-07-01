import os
import subprocess
import sys
import tempfile
import unittest

import database
import multi_project_registry as registry_mod
import cross_project_planner as planner_mod
import cross_project_approvals as approvals_mod


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _run_cli(args, cwd, env):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


class MultiProjectSchedulingTests(unittest.TestCase):
    def setUp(self):
        import multi_project_scheduling as scheduling
        self.scheduling = scheduling
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "s.db"))
        self.addCleanup(self.conn.close)
        self.registry = registry_mod.ProjectRegistry(self.conn)
        self.a = os.path.join(self.td.name, "a"); os.makedirs(self.a)
        self.registry.register_project("alpha", self.a)
        self.plan = planner_mod.CrossProjectPlanner(self.conn).plan_work("work")
        self.gate = approvals_mod.CrossProjectApprovalGate(self.conn)

    def _approved(self):
        approval = self.gate.request_approval(self.plan.id)
        return self.gate.set_status(approval.id, "approved")

    def test_schedule_with_approval(self):
        approval = self._approved()
        scheduler = self.scheduling.MultiProjectScheduler(self.conn)
        schedule = scheduler.schedule_plan(self.plan.id, approval.id, "manual")
        self.assertEqual(schedule.status, "active")
        self.assertEqual(schedule.window, "manual")

    def test_fail_closed_pending(self):
        approval = self.gate.request_approval(self.plan.id)
        scheduler = self.scheduling.MultiProjectScheduler(self.conn)
        with self.assertRaises(ValueError):
            scheduler.schedule_plan(self.plan.id, approval.id, "manual")

    def test_fail_closed_rejected(self):
        approval = self.gate.request_approval(self.plan.id)
        self.gate.set_status(approval.id, "rejected")
        scheduler = self.scheduling.MultiProjectScheduler(self.conn)
        with self.assertRaises(ValueError):
            scheduler.schedule_plan(self.plan.id, approval.id, "manual")

    def test_fail_closed_mismatched_plan(self):
        other = planner_mod.CrossProjectPlanner(self.conn).plan_work("other")
        approval = self._approved()
        scheduler = self.scheduling.MultiProjectScheduler(self.conn)
        with self.assertRaises(ValueError):
            scheduler.schedule_plan(other.id, approval.id, "manual")

    def test_set_status_valid_and_invalid(self):
        approval = self._approved()
        scheduler = self.scheduling.MultiProjectScheduler(self.conn)
        schedule = scheduler.schedule_plan(self.plan.id, approval.id, "manual")
        paused = scheduler.set_status(schedule.id, "paused")
        self.assertEqual(paused.status, "paused")
        with self.assertRaises(ValueError):
            scheduler.set_status(schedule.id, "running")

    def test_persistence_and_events(self):
        approval = self._approved()
        scheduler = self.scheduling.MultiProjectScheduler(self.conn)
        schedule = scheduler.schedule_plan(self.plan.id, approval.id, "manual")
        self.assertGreater(schedule.id, 0)
        self.assertEqual(
            database.list_multi_project_schedules(self.conn)[0]["id"], schedule.id)
        self.assertTrue(
            database.list_multi_project_schedule_events(self.conn, schedule.id))

    def test_no_side_effect_tables(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        approval = self._approved()
        scheduler = self.scheduling.MultiProjectScheduler(self.conn)
        s = scheduler.schedule_plan(self.plan.id, approval.id, "manual")
        scheduler.set_status(s.id, "completed")
        self.assertEqual({t: _count(self.conn, t) for t in before}, before)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        _run_cli(["--register-project", "alpha", "--root", self.a], cwd, env)
        _run_cli(["--plan-cross-project-work", "work"], cwd, env)
        _run_cli(["--request-cross-project-approval", "latest"], cwd, env)
        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        aid = database.list_cross_project_approvals(conn)[0]["id"]
        _run_cli(["--set-cross-project-approval", str(aid), "approved"], cwd, env)

        sched = _run_cli(
            ["--schedule-cross-project-plan", "latest", "--approval", "latest",
             "--window", "manual"], cwd, env)
        self.assertEqual(sched.returncode, 0, sched.stderr)

        lst = _run_cli(["--multi-project-schedules"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)

        sid = database.list_multi_project_schedules(conn)[0]["id"]
        show = _run_cli(["--multi-project-schedule", str(sid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)

        status = _run_cli(
            ["--set-multi-project-schedule-status", str(sid), "completed"], cwd, env)
        self.assertEqual(status.returncode, 0, status.stderr)

        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
