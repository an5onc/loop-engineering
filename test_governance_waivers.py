import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import database
import multi_project_registry as registry_mod
import multi_project_governance_policies as policies_mod
import multi_project_governance_evaluation as eval_mod


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _run_cli(args, cwd, env):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


class GovernanceWaiverTests(unittest.TestCase):
    def setUp(self):
        import governance_waivers as waivers
        self.waivers = waivers
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "w.db"))
        self.addCleanup(self.conn.close)
        self.registry = registry_mod.ProjectRegistry(self.conn)
        self.policies = policies_mod.GovernancePolicyRegistry(self.conn)
        self.a = os.path.join(self.td.name, "a"); os.makedirs(self.a)

    def _failing_finding(self):
        self.registry.register_project("alpha", self.a)
        shutil.rmtree(self.a)
        self.policies.create_policy("p", ["not_stale"])
        ev = eval_mod.GovernanceEvaluationEngine(self.conn).evaluate()
        findings = database.list_governance_policy_findings(self.conn, ev.id)
        return ev, findings[0]

    def test_create_from_finding(self):
        ev, finding = self._failing_finding()
        gate = self.waivers.GovernanceWaiverRegistry(self.conn)
        waiver = gate.create_from_finding(
            finding["id"], reason="temp", owner="me", expiry_days=30)
        self.assertEqual(waiver.status, "active")
        self.assertEqual(waiver.signature, finding["signature"])
        self.assertEqual(waiver.owner, "me")
        self.assertTrue(waiver.expiry)
        self.assertTrue(gate.is_active(waiver))

    def test_create_unknown_finding_fails(self):
        gate = self.waivers.GovernanceWaiverRegistry(self.conn)
        with self.assertRaises(ValueError):
            gate.create_from_finding(9999, reason="x", owner="y")

    def test_no_expiry_is_active(self):
        ev, finding = self._failing_finding()
        gate = self.waivers.GovernanceWaiverRegistry(self.conn)
        waiver = gate.create_from_finding(finding["id"], reason="x", owner="y")
        self.assertIsNone(waiver.expiry)
        self.assertTrue(gate.is_active(waiver))

    def test_revoke_stops_active(self):
        ev, finding = self._failing_finding()
        gate = self.waivers.GovernanceWaiverRegistry(self.conn)
        waiver = gate.create_from_finding(finding["id"], reason="x", owner="y")
        revoked = gate.set_status(waiver.id, "revoked")
        self.assertFalse(gate.is_active(revoked))

    def test_invalid_status_rejected(self):
        ev, finding = self._failing_finding()
        gate = self.waivers.GovernanceWaiverRegistry(self.conn)
        waiver = gate.create_from_finding(finding["id"], reason="x", owner="y")
        with self.assertRaises(ValueError):
            gate.set_status(waiver.id, "approved")

    def test_expired_waiver_not_active(self):
        ev, finding = self._failing_finding()
        gate = self.waivers.GovernanceWaiverRegistry(self.conn)
        waiver = gate.create_from_finding(
            finding["id"], reason="x", owner="y", expiry_days=-1)
        self.assertFalse(gate.is_active(gate.get_waiver(waiver.id)))

    def test_waiver_suppresses_on_reevaluation(self):
        ev, finding = self._failing_finding()
        gate = self.waivers.GovernanceWaiverRegistry(self.conn)
        gate.create_from_finding(finding["id"], reason="x", owner="y",
                                 expiry_days=30)
        report = eval_mod.GovernanceEvaluationEngine(self.conn).evaluate()
        self.assertEqual(report.waived_findings, 1)
        self.assertEqual(report.failed_findings, 0)

    def test_expired_waiver_does_not_suppress_on_reevaluation(self):
        ev, finding = self._failing_finding()
        gate = self.waivers.GovernanceWaiverRegistry(self.conn)
        gate.create_from_finding(finding["id"], reason="x", owner="y",
                                 expiry_days=-1)
        report = eval_mod.GovernanceEvaluationEngine(self.conn).evaluate()
        self.assertEqual(report.waived_findings, 0)
        self.assertEqual(report.failed_findings, 1)

    def test_persistence_and_listing(self):
        ev, finding = self._failing_finding()
        gate = self.waivers.GovernanceWaiverRegistry(self.conn)
        waiver = gate.create_from_finding(finding["id"], reason="x", owner="y")
        self.assertGreater(waiver.id, 0)
        self.assertEqual(
            database.list_governance_waivers(self.conn)[0]["id"], waiver.id)

    def test_no_side_effect_tables(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        ev, finding = self._failing_finding()
        gate = self.waivers.GovernanceWaiverRegistry(self.conn)
        w = gate.create_from_finding(finding["id"], reason="x", owner="y")
        gate.set_status(w.id, "revoked")
        self.assertEqual({t: _count(self.conn, t) for t in before}, before)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        _run_cli(["--register-project", "alpha", "--root", self.a], cwd, env)
        shutil.rmtree(self.a)
        _run_cli(["--create-governance-policy", "np", "--rules", "not_stale"],
                 cwd, env)
        _run_cli(["--evaluate-governance-policies"], cwd, env)
        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        eid = database.list_governance_policy_evaluations(conn)[0]["id"]
        fid = database.list_governance_policy_findings(conn, eid)[0]["id"]

        create = _run_cli(
            ["--create-governance-waiver", str(fid), "--reason", "temp",
             "--owner", "me", "--expiry-days", "30"], cwd, env)
        self.assertEqual(create.returncode, 0, create.stderr)

        lst = _run_cli(["--governance-waivers"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)

        wid = database.list_governance_waivers(conn)[0]["id"]
        setst = _run_cli(
            ["--set-governance-waiver-status", str(wid), "revoked"], cwd, env)
        self.assertEqual(setst.returncode, 0, setst.stderr)

        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
