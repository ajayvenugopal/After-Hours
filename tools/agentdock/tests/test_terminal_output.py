import io
import unittest
from unittest.mock import patch

from prompt_toolkit.data_structures import Size
from agentdock.terminal_output import WorkspaceOutput
from agentdock import screen, ui


class TerminalOutputTests(unittest.TestCase):
    def test_renderer_resets_and_erases_keep_workspace_background(self):
        for environment, expected in [
            ({'TERM': 'xterm-256color'}, '\x1b[48;5;233m'),
            ({'TERM': 'xterm-256color', 'COLORTERM': 'truecolor'}, '\x1b[48;2;16;18;25m'),
            ({'TERM': 'xterm'}, '\x1b[40m'),
        ]:
            with self.subTest(environment=environment), patch.dict('os.environ', environment, clear=True), patch.object(
                    screen, '_active', object()), patch.object(ui, 'theme', 'violet'):
                stream = io.StringIO()
                output = WorkspaceOutput(stream, get_size=lambda: Size(rows=97, columns=486))
                output.reset_attributes()
                output.erase_down()
                output.erase_end_of_line()
                output.flush()
                self.assertEqual(stream.getvalue(), '\x1b[0m' + expected + expected + '\x1b[J' + expected + '\x1b[K')

    def test_panel_only_and_plain_modes_do_not_force_background(self):
        for active, theme in [(None, 'violet'), (object(), 'mono')]:
            with patch.object(screen, '_active', active), patch.object(ui, 'theme', theme):
                stream = io.StringIO()
                output = WorkspaceOutput(stream, get_size=lambda: Size(rows=24, columns=80))
                output.reset_attributes()
                output.erase_down()
                output.flush()
                self.assertEqual(stream.getvalue(), '\x1b[0m\x1b[J')
