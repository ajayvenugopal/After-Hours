import io
import unittest
from unittest.mock import patch

from agentdock import screen, ui


class Terminal(io.StringIO):
    def isatty(self):
        return True


class ScreenTests(unittest.TestCase):
    def test_restores_screen_and_streams_on_error(self):
        output, errors = Terminal(), Terminal()
        with patch("sys.stdout", output), patch("sys.stderr", errors), patch("sys.stdin", Terminal()), patch.dict("os.environ", {"TERM": "xterm-256color"}, clear=True), patch.object(ui, "theme", "violet"):
            with self.assertRaises(RuntimeError):
                with screen.fullscreen(True):
                    self.assertIn("\033[0m\033[48;5;233m", screen.paint_prompt("prompt\033[0m"))
                    print("hello\033[0m world")
                    raise RuntimeError("test")
            import sys
            self.assertIs(sys.stdout, output)
            self.assertIs(sys.stderr, errors)
        self.assertNotIn("\033[?1049", output.getvalue())
        self.assertNotIn("\033[2J", output.getvalue())
        self.assertIn("\033[0m\033[48;5;233m", output.getvalue())
        self.assertTrue(output.getvalue().endswith("\033[0m\033[?25h"))
        self.assertNotIn("\033]", output.getvalue())

    def test_plain_and_disabled_modes_do_not_take_over(self):
        for enabled, env, theme, output in [
            (False, {"TERM": "xterm"}, "violet", Terminal()),
            (True, {"TERM": "dumb"}, "violet", Terminal()),
            (True, {"TERM": "xterm", "NO_COLOR": ""}, "violet", Terminal()),
            (True, {"TERM": "xterm"}, "mono", Terminal()),
            (True, {"TERM": "xterm"}, "violet", io.StringIO()),
        ]:
            with patch("sys.stdout", output), patch("sys.stdin", Terminal()), patch.dict("os.environ", env, clear=True), patch.object(ui, "theme", theme):
                with screen.fullscreen(enabled):
                    print("hello")
            self.assertEqual(output.getvalue(), "hello\n")

    def test_native_view_suspends_background(self):
        output = Terminal()
        with patch("sys.stdout", output), patch("sys.stderr", Terminal()), patch("sys.stdin", Terminal()), patch.dict("os.environ", {"TERM": "xterm"}, clear=True), patch.object(ui, "theme", "violet"):
            with screen.fullscreen(True):
                with screen.suspend():
                    import sys
                    self.assertIs(sys.stdout, output)
                    self.assertEqual(screen.paint_prompt("native"), "native")
                self.assertTrue(screen.paint_prompt("chat").startswith(screen._active.base))
        self.assertNotIn("\033[?1049", output.getvalue())
        self.assertEqual(output.getvalue().count("\033[0m\033[?25h"), 2)

    def test_long_output_keeps_every_line_and_paints_blank_lines(self):
        output = Terminal()
        stream = screen.PaintedStream(output, "\033[40m")
        for index in range(200):
            text = f"line {index}\033[0m\n\n"
            self.assertEqual(stream.write(text), len(text))
        expected = "".join(
            f"line {index}\033[0m\033[40m\033[K\n\033[40m\033[K\033[K\n\033[40m\033[K"
            for index in range(200)
        )
        self.assertEqual(output.getvalue(), expected)
