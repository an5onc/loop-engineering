import os
import subprocess
import sys
import tempfile
import unittest

import database
import multi_project_registry as registry_mod
import multi_project_governance_policies as policies_mod


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _run_cli(args, cwd, env):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


class GovernanceEvaluationTests(unittest.TestCase):
    def setUp(self):
        import multi_project_governance_evaluation as evaluation
        self.evaluation = evaluation
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "e.db"))
        self.addCleanup(self.conn.close)
        self.registry = registry_mod.ProjectRegistry(self.conn)
        self.policies = policies_mod.GovernancePolicyRegistry(self.conn)
        self.a = os.path.join(self.td.name, "a"); os.makedirs(self.a)

    def _policy(self, rules, key="p"):
        return self.policies.create_policy(key, rules, name=key)

    def test_healthy_project_passes(self):
        self.registry.register_project("alpha", self.a)
        self._policy(["not_stale"])
        report = self.evaluation.GovernanceEvaluationEngine(self.conn).evaluate()
        self.assertEqual(report.overall_status, "PASS")
        self.assertEqual(report.failed_findings, 0)
        self.assertTrue(report.findings)

    def test_missing_root_fails(self):
        import shutil
        self.registry.register_project("alpha", self.a)
        shutil.rmtree(self.a)
        self._policy(["not_stale"])
        report = self.evaluation.GovernanceEvaluationEngine(self.conn).evaluate()
        self.assertEqual(report.overall_status, "FAIL")
        self.assertEqual(report.failed_findings, 1)

    def test_fleet_rule_evaluated_once(self):
        self.registry.register_project("alpha", self.a)
        self._policy(["audit_recency"])   # fleet scope, warn, no audits yet
        report = self.evaluation.GovernanceEvaluationEngine(self.conn).evaluate()
        fleet = [f for f in report.findings if f["subject"] == "fleet"]
        self.assertEqual(len(fleet), 1)
        self.assertEqual(report.warning_findings, 1)

    def test_active_waiver_suppresses(self):
        import shutil, datetime
        self.registry.register_project("alpha", self.a)
        shutil.rmtree(self.a)
        policy = self._policy(["not_stale"])
        sig = f"{policy.policy_key}::not_stale::alpha"
        future = (datetime.datetime.now()
                  + datetime.timedelta(days=1)).isoformat(timespec="seconds")
        database.save_governance_waiver(
            self.conn, sig, policy.policy_key, "not_stale", "alpha", "temp",
            "owner", future, "active", None, None)
        report = self.evaluation.GovernanceEvaluationEngine(self.conn).evaluate()
        self.assertEqual(report.waived_findings, 1)
        self.assertEqual(report.failed_findings, 0)
        self.assertIn(report.overall_status, {"PASS", "PASS_WITH_WARNINGS"})

    def test_expired_waiver_does_not_suppress(self):
        import shutil, datetime
        self.registry.register_project("alpha", self.a)
        shutil.rmtree(self.a)
        policy = self._policy(["not_stale"])
        sig = f"{policy.policy_key}::not_stale::alpha"
        past = (datetime.datetime.now()
                - datetime.timedelta(days=1)).isoformat(timespec="seconds")
        database.save_governance_waiver(
            self.conn, sig, policy.policy_key, "not_stale", "alpha", "temp",
            "owner", past, "active", None, None)
        report = self.evaluation.GovernanceEvaluationEngine(self.conn).evaluate()
        self.assertEqual(report.waived_findings, 0)
        self.assertEqual(report.failed_findings, 1)

    def test_malformed_expiry_waiver_does_not_suppress(self):
        import shutil
        self.registry.register_project("alpha", self.a)
        shutil.rmtree(self.a)
        policy = self._policy(["not_stale"])
        sig = f"{policy.policy_key}::not_stale::alpha"
        database.save_governance_waiver(
            self.conn, sig, policy.policy_key, "not_stale", "alpha", "temp",
            "owner", "not-a-date", "active", None, None)
        report = self.evaluation.GovernanceEvaluationEngine(self.conn).evaluate()
        self.assertEqual(report.waived_findings, 0)
        self.assertEqual(report.failed_findings, 1)

    def test_revoked_waiver_does_not_suppress(self):
        import shutil
        self.registry.register_project("alpha", self.a)
        shutil.rmtree(self.a)
        policy = self._policy(["not_stale"])
        sig = f"{policy.policy_key}::not_stale::alpha"
        database.save_governance_waiver(
            self.conn, sig, policy.policy_key, "not_stale", "alpha", "temp",
            "owner", None, "revoked", None, None)
        report = self.evaluation.GovernanceEvaluationEngine(self.conn).evaluate()
        self.assertEqual(report.waived_findings, 0)
        self.assertEqual(report.failed_findings, 1)

    def test_inactive_policy_skipped(self):
        self.registry.register_project("alpha", self.a)
        p = self._policy(["not_stale"])
        self.policies.set_status(p.id, "inactive")
        report = self.evaluation.GovernanceEvaluationEngine(self.conn).evaluate()
        self.assertEqual(report.total_findings, 0)

    def test_persistence_and_findings(self):
        self.registry.register_project("alpha", self.a)
        self._policy(["not_stale"])
        engine = self.evaluation.GovernanceEvaluationEngine(self.conn)
        report = engine.evaluate()
        self.assertGreater(report.id, 0)
        stored = engine.get_evaluation(report.id)
        self.assertEqual(stored.total_findings, report.total_findings)
        findings = database.list_governance_policy_findings(self.conn, report.id)
        self.assertEqual(len(findings), report.total_findings)

    def test_report_path_safety(self):
        self.registry.register_project("alpha", self.a)
        self._policy(["not_stale"])
        engine = self.evaluation.GovernanceEvaluationEngine(self.conn)
        old = self.evaluation.REPORTS_DIR
        self.evaluation.REPORTS_DIR = os.path.join(self.td.name, "reports")
        self.addCleanup(setattr, self.evaluation, "REPORTS_DIR", old)
        report = engine.evaluate()
        md = engine.save_markdown_report(report.id)
        self.assertTrue(self.evaluation.is_report_path(md.report_path))
        self.assertTrue(os.path.realpath(md.report_path).startswith(
            os.path.realpath(self.evaluation.REPORTS_DIR) + os.sep))

    def test_no_side_effect_tables(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        self.registry.register_project("alpha", self.a)
        self._policy(["not_stale"])
        self.evaluation.GovernanceEvaluationEngine(self.conn).evaluate()
        self.assertEqual({t: _count(self.conn, t) for t in before}, before)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        _run_cli(["--register-project", "alpha", "--root", self.a], cwd, env)
        _run_cli(["--create-governance-policy", "--default"], cwd, env)

        ev = _run_cli(["--evaluate-governance-policies", "--save-report"], cwd, env)
        self.assertEqual(ev.returncode, 0, ev.stderr)
        self.assertIn("GOVERNANCE POLICY EVALUATION", ev.stdout)

        lst = _run_cli(["--governance-evaluations"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)

        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        eid = database.list_governance_policy_evaluations(conn)[0]["id"]
        show = _run_cli(["--governance-evaluation", str(eid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)

        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
