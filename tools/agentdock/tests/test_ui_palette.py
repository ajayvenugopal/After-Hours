import io
import unittest
from unittest.mock import patch

from agentdock import ui


class Terminal(io.StringIO):
    def isatty(self):
        return True


class PaletteTests(unittest.TestCase):
    def test_panel_background_is_reset_on_every_line(self):
        output = Terminal()
        with patch("sys.stdout", output), patch.dict("os.environ", {"TERM": "xterm-256color", "COLORTERM": "truecolor"}, clear=True), patch.object(ui, "theme", "violet"):
            ui.panel("WORKSPACE", ["sample project"])
            print("outside")
        lines = output.getvalue().splitlines()
        for line in lines:
            if line and line != "outside":
                self.assertTrue(line.startswith("\033[48;2;16;18;25m"))
                self.assertTrue(line.endswith("\033[0m"))
        self.assertEqual(lines[-1], "outside")
        self.assertNotIn("\033]", output.getvalue())

    def test_panel_background_respects_plain_output(self):
        for theme, env, stream in [
            ("mono", {"TERM": "xterm"}, Terminal()),
            ("violet", {"TERM": "xterm", "NO_COLOR": ""}, Terminal()),
            ("violet", {"TERM": "dumb"}, Terminal()),
            ("violet", {"TERM": "xterm"}, io.StringIO()),
        ]:
            with patch("sys.stdout", stream), patch.dict("os.environ", env, clear=True), patch.object(ui, "theme", theme):
                self.assertEqual(ui.panel_line("plain"), "plain")

    def test_banner_colors_in_truecolor_terminal(self):
        with patch.dict("os.environ", {"TERM": "xterm-256color", "COLORTERM": "truecolor"}, clear=True), patch.object(ui, "theme", "violet"):
            for style, color in [("accent", "196;181;253"), ("muted", "170;166;187"), ("bold", "245;243;255")]:
                self.assertIn("38;2;" + color, ui.styled("text", style, Terminal()))

    def test_terminal_fallbacks(self):
        for term, code in [("xterm-256color", "38;5;183"), ("xterm", "95")]:
            with patch.dict("os.environ", {"TERM": term}, clear=True), patch.object(ui, "theme", "violet"):
                self.assertEqual(ui.styled("text", stream=Terminal()), f"\033[{code}mtext\033[0m")

    def test_no_color_and_redirected_output_remain_plain(self):
        with patch.dict("os.environ", {"TERM": "xterm-256color", "COLORTERM": "truecolor", "NO_COLOR": ""}, clear=True):
            self.assertEqual(ui.styled("text", stream=Terminal()), "text")
        self.assertEqual(ui.styled("text", stream=io.StringIO()), "text")
