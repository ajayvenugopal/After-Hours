import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentdock.cli import run_codex


class CodexFlagTests(unittest.TestCase):
    def test_skip_git_flag_is_never_duplicated(self):
        for inspect in (True, False):
            for skip in (True, False):
                with self.subTest(inspect=inspect, skip=skip), tempfile.TemporaryDirectory() as directory:
                    repo = Path(directory)
                    output = repo / "response.md"
                    output.write_text("No actionable findings.")
                    with patch("agentdock.cli.run_logged") as run:
                        run.return_value.returncode = 0
                        run_codex(repo, "Review", output, None, repo / "log",
                                  inspect_repo=inspect, skip_git_repo_check=skip)
                    argv = run.call_args.args[0]
                    self.assertEqual(argv.count("--skip-git-repo-check"), int(skip or not inspect))
                    self.assertEqual(argv.count("--ignore-rules"), int(not inspect))
