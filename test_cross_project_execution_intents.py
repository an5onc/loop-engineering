import os
import subprocess
import sys
import tempfile
import unittest

import database


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _run_cli(args, cwd, env):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


class CrossProjectExecutionIntentTests(unittest.TestCase):
    def setUp(self):
        import cross_project_execution_intents as intents
        self.intents = intents
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.conn = database.init_db(os.path.join(self.td.name, "i.db"))
        self.addCleanup(self.conn.close)

    def test_create_manual_intent(self):
        registry = self.intents.CrossProjectExecutionIntentRegistry(self.conn)
        intent = registry.create_intent(
            "manual", 0, "Manual execution planning", "operator",
            summary={"goal": "review"}, details={"projects": ["alpha"]})
        self.assertEqual(intent.source_type, "manual")
        self.assertEqual(intent.source_id, 0)
        self.assertEqual(intent.status, "draft")
        self.assertEqual(intent.owner, "operator")
        self.assertEqual(intent.summary["goal"], "review")

    def test_non_manual_requires_positive_source_id(self):
        registry = self.intents.CrossProjectExecutionIntentRegistry(self.conn)
        with self.assertRaises(ValueError):
            registry.create_intent("cross_project_plan", 0, "x", "operator")

    def test_invalid_source_type_rejected(self):
        registry = self.intents.CrossProjectExecutionIntentRegistry(self.conn)
        with self.assertRaises(ValueError):
            registry.create_intent("shell", 1, "x", "operator")

    def test_title_and_owner_required(self):
        registry = self.intents.CrossProjectExecutionIntentRegistry(self.conn)
        with self.assertRaises(ValueError):
            registry.create_intent("manual", 0, "", "operator")
        with self.assertRaises(ValueError):
            registry.create_intent("manual", 0, "x", "")

    def test_persistence_listing_and_status(self):
        registry = self.intents.CrossProjectExecutionIntentRegistry(self.conn)
        intent = registry.create_intent("manual", 0, "x", "operator")
        self.assertGreater(intent.id, 0)
        self.assertEqual(registry.get_intent(intent.id).title, "x")
        self.assertEqual(registry.list_intents()[0]["id"], intent.id)
        ready = registry.set_status(intent.id, "ready")
        self.assertEqual(ready.status, "ready")
        with self.assertRaises(ValueError):
            registry.set_status(intent.id, "approved")
        self.assertTrue(database.list_cross_project_execution_intent_events(
            self.conn, intent.id))

    def test_no_side_effect_tables(self):
        before = {t: _count(self.conn, t)
                  for t in ("loops", "external_agent_jobs", "command_results")}
        self.intents.CrossProjectExecutionIntentRegistry(self.conn).create_intent(
            "manual", 0, "x", "operator")
        self.assertEqual({t: _count(self.conn, t) for t in before}, before)

    def test_cli_invalid_ollama(self):
        db_path = os.path.join(self.td.name, "cli.db")
        env = dict(os.environ)
        env["LOOP_DB_FILE"] = db_path
        env["OLLAMA_HOST"] = "http://127.0.0.1:9"
        cwd = os.path.dirname(os.path.abspath(__file__))
        create = _run_cli([
            "--create-cross-project-execution-intent",
            "--source-type", "manual", "--source-id", "0",
            "--title", "Manual execution planning smoke",
            "--owner", "operator"], cwd, env)
        self.assertEqual(create.returncode, 0, create.stderr)
        self.assertIn("EXECUTION INTENT", create.stdout.upper())
        listing = _run_cli(["--cross-project-execution-intents"], cwd, env)
        self.assertEqual(listing.returncode, 0, listing.stderr)
        conn = database.init_db(db_path)
        self.addCleanup(conn.close)
        iid = database.list_cross_project_execution_intents(conn)[0]["id"]
        show = _run_cli(["--cross-project-execution-intent", str(iid)], cwd, env)
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertEqual(_count(conn, "loops"), 0)
        self.assertEqual(_count(conn, "command_results"), 0)
        self.assertEqual(_count(conn, "external_agent_jobs"), 0)


if __name__ == "__main__":
    unittest.main()
