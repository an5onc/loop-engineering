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


class CrossProjectHandoffTests(unittest.TestCase):
    def setUp(self):
        import cross_project_handoff as handoff
        self.handoff = handoff
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "h.db"))
        self.addCleanup(self.conn.close)
        self.registry = registry_mod.ProjectRegistry(self.conn)
        self.a = os.path.join(self.td.name, "a"); os.makedirs(self.a)
        # A protected file with a secret that must never appear in a packet.
        self.secret = "TOPSECRET_TOKEN_42"
        with open(os.path.join(self.a, "secret.env"), "w") as fh:
            fh.write(f"KEY={self.secret}\n")
        self.registry.register_project(
            "alpha", self.a, protected_paths=["secret.env"])
        self.plan = planner_mod.CrossProjectPlanner(self.conn).plan_work("work")
        self.gate = approvals_mod.CrossProjectApprovalGate(self.conn)
        self._old_dir = self.handoff.PACKETS_DIR
        self.handoff.PACKETS_DIR = os.path.join(self.td.name, "packets")
        self.addCleanup(setattr, self.handoff, "PACKETS_DIR", self._old_dir)

    def _approved(self):
        approval = self.gate.request_approval(self.plan.id)
        return self.gate.set_status(approval.id, "approved", decided_by="t")

    def test_create_handoff_with_approval(self):
        approval = self._approved()
        builder = self.handoff.CrossProjectHandoffBuilder(self.conn)
        packet = builder.create_handoff(self.plan.id, approval.id)
        self.assertEqual(packet.status, "created")
        self.assertTrue(self.handoff.is_packet_path(packet.report_path))
        self.assertTrue(os.path.exists(packet.report_path))
        self.assertTrue(os.path.realpath(packet.report_path).startswith(
            os.path.realpath(self.handoff.PACKETS_DIR) + os.sep))

    def test_packet_excludes_protected_contents(self):
        approval = self._approved()
        builder = self.handoff.CrossProjectHandoffBuilder(self.conn)
        packet = builder.create_handoff(self.plan.id, approval.id)
        with open(packet.report_path) as fh:
            content = fh.read()
        self.assertNotIn(self.secret, content)
        self.assertIn("secret.env", content)   # name only
        self.assertIn("Completion Response JSON", content)
        self.assertIn("Non-Goals", content)
        self.assertIn("Verification", content)

    def test_fail_closed_pending_approval(self):
        approval = self.gate.request_approval(self.plan.id)
        builder = self.handoff.CrossProjectHandoffBuilder(self.conn)
        with self.assertRaises(ValueError):
            builder.create_handoff(self.plan.id, approval.id)

    def test_fail_closed_rejected_approval(self):
        approval = self.gate.request_approval(self.plan.id)
        self.gate.set_status(approval.id, "rejected")
        builder = self.handoff.CrossProjectHandoffBuilder(self.conn)
        with self.assertRaises(ValueError):
            builder.create_handoff(self.plan.id, approval.id)

    def test_fail_closed_mismatched_plan(self):
        other_plan = planner_mod.CrossProjectPlanner(self.conn).plan_work("other")
        approval = self._approved()  # approval references self.plan
        builder = self.handoff.CrossProjectHandoffBuilder(self.conn)
        with self.assertRaises(ValueError):
            builder.create_handoff(other_plan.id, approval.id)

    def test_fail_closed_missing_approval(self):
        builder = self.handoff.CrossProjectHandoffBuilder(self.conn)
        with self.assertRaises(ValueError):
            builder.create_handoff(self.plan.id, 99999)

    def test_persistence_and_listing(self):
        approval = self._approved()
        builder = self.handoff.CrossProjectHandoffBuilder(self.conn)
        packet = builder.create_handoff(self.plan.id, approval.id)
        self.assertGreater(packet.id, 0)
        self.assertEqual(
            database.list_cross_project_handoffs(self.conn)[0]["id"], packet.id)
        self.assertTrue(
            database.list_cross_project_handoff_events(self.conn, packet.id))

    def test_no_side_effect_tables(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        approval = self._approved()
        builder = self.handoff.CrossProjectHandoffBuilder(self.conn)
        builder.create_handoff(self.plan.id, approval.id)
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

        ho = _run_cli(
            ["--handoff-cross-project-plan", "latest", "--approval", "latest"],
            cwd, env)
        self.assertEqual(ho.returncode, 0, ho.stderr)

        lst = _run_cli(["--cross-project-handoffs"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)

        hid = database.list_cross_project_handoffs(conn)[0]["id"]
        show = _run_cli(["--cross-project-handoff", str(hid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)

        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
