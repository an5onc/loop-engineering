import os
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


class GovernanceEvidenceExportTests(unittest.TestCase):
    def setUp(self):
        import governance_evidence_export as evidence
        self.evidence = evidence
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "ev.db"))
        self.addCleanup(self.conn.close)
        self.registry = registry_mod.ProjectRegistry(self.conn)
        self.policies = policies_mod.GovernancePolicyRegistry(self.conn)
        self.secret = "SUPER_SECRET_TOKEN_99"
        self.a = os.path.join(self.td.name, "a"); os.makedirs(self.a)
        with open(os.path.join(self.a, "secret.env"), "w") as fh:
            fh.write(f"KEY={self.secret}\n")
        self.registry.register_project(
            "alpha", self.a, protected_paths=["secret.env"])
        self.policies.ensure_default_policy()
        eval_mod.GovernanceEvaluationEngine(self.conn).evaluate()
        self._old = self.evidence.EXPORTS_DIR
        self.evidence.EXPORTS_DIR = os.path.join(self.td.name, "exports")
        self.addCleanup(setattr, self.evidence, "EXPORTS_DIR", self._old)

    def test_export_creates_packet(self):
        exporter = self.evidence.GovernanceEvidenceExporter(self.conn)
        export = exporter.export()
        self.assertGreater(export.id, 0)
        self.assertTrue(self.evidence.is_export_path(export.report_path))
        self.assertTrue(os.path.exists(export.report_path))
        self.assertTrue(os.path.realpath(export.report_path).startswith(
            os.path.realpath(self.evidence.EXPORTS_DIR) + os.sep))

    def test_export_excludes_secrets(self):
        exporter = self.evidence.GovernanceEvidenceExporter(self.conn)
        export = exporter.export()
        with open(export.report_path) as fh:
            content = fh.read()
        self.assertNotIn(self.secret, content)
        self.assertIn("Governance Evidence", content)
        self.assertIn("Safety", content)

    def test_export_has_expected_sections(self):
        exporter = self.evidence.GovernanceEvidenceExporter(self.conn)
        export = exporter.export()
        with open(export.report_path) as fh:
            content = fh.read()
        for heading in ("Policies", "Evaluation", "Waivers", "Review", "Fleet"):
            self.assertIn(heading, content)

    def test_persistence_and_listing(self):
        exporter = self.evidence.GovernanceEvidenceExporter(self.conn)
        export = exporter.export()
        self.assertEqual(
            database.list_governance_evidence_exports(self.conn)[0]["id"],
            export.id)

    def test_no_side_effect_tables(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        self.evidence.GovernanceEvidenceExporter(self.conn).export()
        self.assertEqual({t: _count(self.conn, t) for t in before}, before)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        _run_cli(["--register-project", "alpha", "--root", self.a], cwd, env)
        _run_cli(["--create-governance-policy", "--default"], cwd, env)
        _run_cli(["--evaluate-governance-policies"], cwd, env)

        exp = _run_cli(["--export-governance-evidence"], cwd, env)
        self.assertEqual(exp.returncode, 0, exp.stderr)
        self.assertIn("GOVERNANCE EVIDENCE EXPORT", exp.stdout)

        lst = _run_cli(["--governance-evidence-exports"], cwd, env)
        self.assertEqual(lst.returncode, 0, lst.stderr)

        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
