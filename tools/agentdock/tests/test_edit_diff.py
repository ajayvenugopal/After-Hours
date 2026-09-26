import io
import unittest
from unittest.mock import patch

from agentdock.file_diff import diff_snapshots
from agentdock import ui


class EditDiffTests(unittest.TestCase):
    def test_step_diff_only_shows_changes_since_step_started(self):
        before = {"index.html": "old\n", "untouched.txt": "user changes\n"}
        after = {"index.html": "new\n", "untouched.txt": "user changes\n", "new.txt": "created"}
        diff = diff_snapshots(before, after)
        self.assertIn("-old\n+new\n", diff)
        self.assertNotIn("untouched.txt", diff)
        self.assertIn("+created\n\\ No newline", diff)

    def test_deleted_file_is_shown(self):
        diff = diff_snapshots({"old.txt": "gone\n"}, {})
        self.assertIn("+++ /dev/null", diff)
        self.assertIn("-gone", diff)

    def test_tty_changes_are_red_and_green(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True
        output = Terminal()
        with patch("sys.stdout", output), patch.dict("os.environ", {"TERM": "xterm"}, clear=True), patch.object(ui, "theme", "violet"):
            ui.show_diff("--- a/file\n+++ b/file\n-old\n+new\n")
        self.assertIn("\033[31m-old", output.getvalue())
        self.assertIn("\033[32m+new", output.getvalue())

    def test_redirected_diff_is_plain_and_bounded(self):
        output = io.StringIO()
        with patch("sys.stdout", output):
            ui.show_diff("-old\n+new\n context\n", limit=2)
        self.assertNotIn("\033", output.getvalue())
        self.assertIn("1 more lines", output.getvalue())
