import io
import os
import unittest
from unittest.mock import patch

from agentdock.chat_input import ChatInput


class ChatInputTests(unittest.TestCase):
    def test_plain_input_does_not_repeat_status(self):
        reader = ChatInput()
        reader.session = None
        with patch('builtins.input', return_value='hello') as read:
            self.assertEqual(reader.read('CHAT · local · 139 tokens', []), 'hello')
        read.assert_called_once_with('  ❯ ')

    def test_real_renderer_shows_footer_below_input_and_clears_on_submit(self):
        from prompt_toolkit import PromptSession
        from prompt_toolkit.input.defaults import create_pipe_input
        from prompt_toolkit.output.vt100 import Vt100_Output
        from prompt_toolkit.data_structures import Size
        import threading

        visible = threading.Event()
        class Capture(io.StringIO):
            def flush(self):
                if '139 tokens' in self.getvalue():
                    visible.set()

        output = Capture()
        class TerminalOutput(Vt100_Output):
            def get_rows_below_cursor_position(self):
                return 12

        with create_pipe_input() as pipe:
            reader = ChatInput.__new__(ChatInput)
            reader.session = PromptSession(input=pipe, output=TerminalOutput(
                output, get_size=lambda: Size(rows=12, columns=60), enable_cpr=False),
                reserve_space_for_menu=0)
            def submit():
                visible.wait(3)
                pipe.send_text('hello\n')
            thread = threading.Thread(target=submit)
            thread.start()
            try:
                answer = reader.read('CHAT · local · 139 tokens', ['/chat', '/build'])
            finally:
                thread.join(4)
        self.assertTrue(visible.is_set())
        self.assertEqual(answer, 'hello')
        rendered = output.getvalue()
        self.assertLess(rendered.index('❯'), rendered.index('139 tokens'))
        self.assertIn('\x1b[J', rendered[rendered.index('139 tokens'):])
        self.assertNotIn('\x1b[?1049h', rendered)

    def test_running_footer_reserves_bottom_row_and_restores_after_error(self):
        from agentdock.chat_input import RunningFooter
        import signal
        output = io.StringIO()
        previous = signal.getsignal(signal.SIGWINCH)
        with patch('sys.stdout', output), patch('shutil.get_terminal_size', return_value=os.terminal_size((80, 24))):
            with self.assertRaises(RuntimeError):
                with RunningFooter('CHAT · local · 139 tokens'):
                    self.assertIn('\x1b[1;23r', output.getvalue())
                    self.assertIn('\x1b[24;1H\x1b[2KCHAT', output.getvalue())
                    self.assertTrue(output.getvalue().endswith('\x1b8'))
                    self.assertNotIn('\x1b[23;1H', output.getvalue())
                    raise RuntimeError('provider failed')
        self.assertTrue(output.getvalue().endswith('\x1b[r\x1b8'))
        self.assertEqual(signal.getsignal(signal.SIGWINCH), previous)
        self.assertNotIn('\x1b[?1049h', output.getvalue())

    def test_running_footer_handles_resize_and_plain_output(self):
        from agentdock.chat_input import RunningFooter
        output = io.StringIO()
        with patch('sys.stdout', output):
            with RunningFooter('status', enabled=False):
                pass
        self.assertEqual(output.getvalue(), '')
        with patch('sys.stdout', output), patch('shutil.get_terminal_size', return_value=os.terminal_size((40, 12))):
            with RunningFooter('BUILD · 120 tokens') as footer:
                with patch('shutil.get_terminal_size', return_value=os.terminal_size((30, 8))):
                    footer.resize(0, None)
                    self.assertIn('\x1b[1;7r\x1b[8;1H', output.getvalue())
                    self.assertTrue(output.getvalue().endswith('\x1b8'))
                    self.assertNotIn('\x1b[7;1H', output.getvalue())

    def test_real_input_renderer_uses_same_background_as_conversation(self):
        import re
        import threading
        from prompt_toolkit import PromptSession
        from prompt_toolkit.input.defaults import create_pipe_input
        from prompt_toolkit.data_structures import Size
        from agentdock.terminal_output import WorkspaceOutput
        from agentdock import screen, ui

        class TerminalOutput(WorkspaceOutput):
            def get_rows_below_cursor_position(self):
                return 12

        for environment, expected in [
            ({'TERM': 'xterm-256color', 'COLORTERM': 'truecolor'}, '48;2;16;18;25'),
            ({'TERM': 'xterm-256color'}, '48;5;233'),
        ]:
            with self.subTest(environment=environment), patch.dict('os.environ', environment, clear=True), patch.object(
                    screen, '_active', object()), patch.object(ui, 'theme', 'violet'), create_pipe_input() as pipe:
                visible = threading.Event()

                class Capture(io.StringIO):
                    def flush(self):
                        if 'CHAT' in self.getvalue():
                            visible.set()

                output = Capture()
                reader = ChatInput.__new__(ChatInput)
                reader.session = PromptSession(input=pipe, output=TerminalOutput(
                    output, get_size=lambda: Size(rows=12, columns=80), enable_cpr=False),
                    reserve_space_for_menu=0)

                def submit():
                    visible.wait(3)
                    pipe.send_text('hello\n')

                thread = threading.Thread(target=submit)
                thread.start()
                try:
                    reader.read('CHAT · local', [])
                finally:
                    thread.join(4)
                self.assertTrue(visible.is_set())
                backgrounds = re.findall(r'48;(?:2;\d+;\d+;\d+|5;\d+)', output.getvalue())
                self.assertEqual(set(backgrounds), {expected})
