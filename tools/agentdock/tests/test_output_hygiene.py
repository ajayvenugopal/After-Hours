import copy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentdock.cli import DEFAULT_CONFIG, changed_files, make_diff, planner_prompt, run_aider, review_prompt
from agentdock.file_diff import snapshot


class OutputHygieneTests(unittest.TestCase):
    def test_no_git_snapshot_ignores_tooling_histories(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "index.html").write_text("page")
            (repo / ".aider.chat.history.md").write_text("transcript")
            (repo / ".agentdock").mkdir()
            (repo / ".agentdock" / "dependency.py").write_text("tool")
            self.assertEqual(list(snapshot(repo)), ["index.html"])
            self.assertNotIn("transcript", make_diff(repo))

    def test_git_diff_excludes_tracked_and_untracked_tool_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            def git(*args):
                return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
            git("init")
            (repo / "index.html").write_text("old\n")
            (repo / ".aider.chat.history.md").write_text("old transcript\n")
            (repo / ".agentdock").mkdir()
            (repo / ".agentdock" / "worker.log").write_text("old log\n")
            git("add", ".")
            git("-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-m", "baseline")
            (repo / "index.html").write_text("new\n")
            (repo / ".aider.chat.history.md").write_text("new transcript\n")
            (repo / ".agentdock" / "worker.log").write_text("new log\n")
            (repo / ".aider.input.history").write_text("input")
            diff = make_diff(repo)
            self.assertIn("index.html", diff)
            self.assertNotIn(".aider", diff)
            self.assertNotIn(".agentdock", diff)
            self.assertEqual(changed_files(repo), ["index.html"])

    def test_aider_histories_are_redirected_and_excluded_from_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            with patch("agentdock.cli.ensure_ollama_ready"), patch("agentdock.cli.ensure_aider", return_value="aider"), patch("agentdock.cli.run_logged") as run:
                run.return_value.returncode = 0
                run_aider(repo, copy.deepcopy(DEFAULT_CONFIG), repo / "prompt", [],
                          ["index.html", ".aider.chat.history.md"], repo / "log")
            argv = run.call_args.args[0]
            self.assertIn("--no-show-release-notes", argv)
            self.assertEqual(argv[argv.index("--chat-history-file") + 1], str(repo / ".agentdock/aider-chat-history.md"))
            self.assertNotIn(".aider.chat.history.md", argv)

    def test_prompts_exclude_tooling_and_do_not_claim_tests_passed(self):
        self.assertIn("Filtered project text-file inventory", planner_prompt("build", ["index.html"]))
        prompt = review_prompt("task", "plan", "diff", "NOT RUN")
        self.assertNotIn("passing test output", prompt)
        self.assertIn("NOT RUN means no tests passed", prompt)
