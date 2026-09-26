import unittest
import io
from unittest.mock import patch

from agentdock.progress import LocalProgress, ElapsedTimer


class LocalProgressTests(unittest.TestCase):
    def test_timer_formats_elapsed_and_clears_before_progress(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True
        stream = Terminal()
        with patch("agentdock.progress.time.monotonic", return_value=100), patch.dict("os.environ", {"TERM": "xterm"}):
            timer = ElapsedTimer(stream, "local")
        with patch("agentdock.progress.time.monotonic", return_value=165):
            timer.tick()
            self.assertIn("01:05", stream.getvalue())
            timer.write("Applied edit to index.html\n")
            self.assertIn("\r\033[2KApplied edit", stream.getvalue())
            timer.stop()
            self.assertTrue(stream.getvalue().endswith("completed · 01:05\n"))

    def test_redirected_output_uses_infrequent_plain_updates(self):
        stream = io.StringIO()
        with patch("agentdock.progress.time.monotonic", return_value=100):
            timer = ElapsedTimer(stream, "codex")
            timer.tick()
            self.assertEqual(stream.getvalue(), "")
        with patch("agentdock.progress.time.monotonic", return_value=115):
            timer.tick()
            timer.stop()
        self.assertEqual(stream.getvalue(), "[codex] Working… 00:15\n")

    def test_fragmented_narration_and_edit_receipts_without_source_dump(self):
        messages = []
        progress = LocalProgress(messages.append)
        progress.feed("Aider v0.86.2\nI'll cre")
        progress.feed("ate a page.\nindex.html\n```html\nI'll hide this source line\n</html>\n```\nApplied edit to index.html\n")
        progress.finish()
        self.assertEqual(messages, ["I'll create a page.", "Applied edit to index.html"])

    def test_error_without_trailing_newline_is_displayed(self):
        messages = []
        progress = LocalProgress(messages.append)
        progress.feed("Error: edit could not be applied")
        progress.finish()
        self.assertEqual(messages, ["Error: edit could not be applied"])
