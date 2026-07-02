import os
import subprocess
import tempfile
import unittest


class AgentHandoffTests(unittest.TestCase):
    def test_build_handoff_contains_clone_resume_and_verification_commands(self):
        import agent_handoff

        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            content = agent_handoff.build_handoff(td)

            self.assertIn("git clone", content)
            self.assertIn("git pull --ff-only", content)
            self.assertIn("python3 -m py_compile *.py", content)
            self.assertIn("python3 audit_hotfix.py", content)
            self.assertIn("Do not commit runtime artifacts", content)
            self.assertIn("Multi-Project Operations", content)
            self.assertIn("--plan-cross-project-work", content)
            self.assertIn("Governance & Fleet Reporting", content)
            self.assertIn("--evaluate-governance-policies", content)
            self.assertIn("Execution Windows & Retry Policy (Stage 12)", content)
            self.assertIn("--define-execution-window", content)
            self.assertIn("--request-orchestration-retry", content)
            self.assertIn("Operator Rollback Restoration (Stage 13)", content)
            self.assertIn("--restore-orchestration-step", content)
            self.assertIn("--confirm-restore", content)

    def test_check_requires_runtime_artifacts_ignored(self):
        import agent_handoff

        with tempfile.TemporaryDirectory() as td:
            _init_repo(td, gitignore="__pycache__/\n")

            result = agent_handoff.check_handoff_system(td)

            self.assertFalse(result.ok)
            self.assertIn("loop_engineering.db", "\n".join(result.errors))
            self.assertIn("reports/", "\n".join(result.errors))

    def test_write_handoff_creates_portable_markdown(self):
        import agent_handoff

        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            target = os.path.join(td, "HANDOFF.md")

            written = agent_handoff.write_handoff(td, target)

            self.assertEqual(written, target)
            self.assertTrue(os.path.exists(target))
            with open(target, "r", encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("# Loop Engineering Agent Handoff", content)
            self.assertNotIn("/Users/ansoncordeiro", content)


def _init_repo(path, gitignore=None):
    _run(["git", "init", "-b", "main"], path)
    _run(["git", "config", "user.email", "test@example.com"], path)
    _run(["git", "config", "user.name", "Test Agent"], path)
    _run(["git", "remote", "add", "origin", "https://github.com/example/repo.git"], path)
    with open(os.path.join(path, ".gitignore"), "w", encoding="utf-8") as fh:
        fh.write(gitignore if gitignore is not None else (
            "__pycache__/\n"
            "loop_engineering.db\n"
            "reports/\n"
            "external_agent_jobs/\n"
            "external_agent_handoffs/\n"
            "loop_improvement_reports/\n"
            "loop_improvement_review_reports/\n"
        ))
    with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("# Test\n")
    _run(["git", "add", ".gitignore", "README.md"], path)
    _run(["git", "commit", "-m", "init"], path)


def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


if __name__ == "__main__":
    unittest.main()
