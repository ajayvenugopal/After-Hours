import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentdock.cli import ensure_aider, make_diff, changed_files, WorkflowError
from agentdock.file_diff import BASELINE, snapshot


class LocalSetupTests(unittest.TestCase):
    def test_aider_existing_install_is_reused(self):
        with patch("agentdock.cli.aider_executable", return_value="/bin/aider"), patch("agentdock.cli.run_logged") as run:
            self.assertEqual(ensure_aider(Path("/tmp")), "/bin/aider")
        run.assert_not_called()

    def test_managed_aider_install_uses_isolated_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            with patch("agentdock.cli.aider_executable", side_effect=[None, "/managed/aider"]), patch("agentdock.cli.shutil.which", return_value="/bin/uv"), patch("agentdock.cli.run_logged") as run, patch("builtins.print"):
                run.return_value.returncode = 0
                self.assertEqual(ensure_aider(repo), "/managed/aider")
            args = run.call_args.args[0]
            self.assertEqual(args, ["/bin/uv", "tool", "install", "--python", "python3.12", "--with", "pip", "aider-chat"])
            self.assertTrue(run.call_args.kwargs["env"]["UV_TOOL_DIR"].startswith(directory))

    def test_install_failure_does_not_start_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("agentdock.cli.aider_executable", return_value=None), patch("agentdock.cli.shutil.which", return_value="/bin/uv"), patch("agentdock.cli.run_logged") as run, patch("builtins.print"):
                run.return_value.returncode = 1
                run.return_value.stdout = "network unavailable"
                with self.assertRaisesRegex(WorkflowError, "network unavailable"):
                    ensure_aider(Path(directory))

    def test_no_git_diff_tracks_changes_against_task_start(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "index.html").write_text("before\n")
            (repo / "old.txt").write_text("removed\n")
            token = BASELINE.set(snapshot(repo))
            try:
                (repo / "index.html").write_text("after\n")
                (repo / "new.txt").write_text("added\n")
                (repo / "old.txt").unlink()
                diff = make_diff(repo)
                self.assertIn("-before", diff)
                self.assertIn("+after", diff)
                self.assertIn("+added", diff)
                self.assertIn("-removed", diff)
                self.assertEqual(changed_files(repo), ["index.html", "new.txt"])
                self.assertFalse((repo / ".git").exists())
            finally:
                BASELINE.reset(token)
