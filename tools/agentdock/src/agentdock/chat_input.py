"""Inline input and a reserved status row during agent execution."""
import os
import sys

from . import ui, screen


class ChatInput:
    def __init__(self):
        self.session = None
        if sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get('TERM') not in {'', 'dumb'}:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.layout import Dimension, FormattedTextControl, HSplit, Window
            from .terminal_output import WorkspaceOutput

            class DockPromptSession(PromptSession):
                def _create_layout(self):
                    layout = super()._create_layout()
                    # Let the input and footer sit at the bottom of the
                    # available terminal while keeping earlier output above.
                    layout.container.children.insert(0, Window(
                        FormattedTextControl(''), height=Dimension(weight=1),
                        style='class:workspace-background'))
                    return layout

            # The renderer owns escape sequences; bypass the painted stream,
            # whose reset/newline rewriting would interfere with cursor tracking.
            output = WorkspaceOutput.from_pty(getattr(sys.stdout, 'stream', sys.stdout), term=os.environ.get('TERM'))
            self.session = DockPromptSession(output=output, reserve_space_for_menu=0)

    def read(self, status, words):
        if self.session is None:
            return input('  ❯ ')
        from prompt_toolkit.completion import WordCompleter
        from prompt_toolkit.styles import Style
        from prompt_toolkit.output import ColorDepth

        plain = 'NO_COLOR' in os.environ or ui.theme == 'mono'
        background, foreground, background_escape, _ = screen.workspace_palette()
        # Match the ANSI colors used by Screen and PaintedStream. The toolkit
        # defaults to 256 colors even when our workspace uses true color.
        if plain:
            color_depth = ColorDepth.DEPTH_1_BIT
        elif '48;2;' in background_escape:
            color_depth = ColorDepth.DEPTH_24_BIT
        elif '48;5;' in background_escape:
            color_depth = ColorDepth.DEPTH_8_BIT
        else:
            color_depth = ColorDepth.DEPTH_4_BIT
        base_style = f'bg:{background} {foreground}' if screen.workspace_background() else ''
        palette = {} if plain else {
            '': base_style,
            'workspace-background': base_style,
            'bottom-toolbar': 'noreverse ' + base_style,
            'prompt': '#c4b5fd' if ui.theme == 'violet' else 'ansiyellow',
        }
        return self.session.prompt(
            [('class:prompt', '  ❯ ')],
            bottom_toolbar=lambda: [('class:bottom-toolbar', status)],
            completer=WordCompleter(words, sentence=True),
            complete_while_typing=False,
            style=Style.from_dict(palette),
            color_depth=color_depth,
        )

    def running(self, status):
        """Keep the status row visible while synchronous agent code owns stdout."""
        return RunningFooter(status, enabled=self.session is not None)


class RunningFooter:
    def __init__(self, status, *, enabled=True):
        self.status = status
        self.enabled = enabled
        self.active = False

    def __enter__(self):
        if not self.enabled:
            return self
        import signal
        self.stream = getattr(sys.stdout, 'stream', sys.stdout)
        self.previous_resize = signal.getsignal(signal.SIGWINCH)
        signal.signal(signal.SIGWINCH, self.resize)
        self.resize()
        return self

    def resize(self, *_):
        import shutil
        from .activity import plain_text
        columns, rows = shutil.get_terminal_size((80, 24))
        # Leave at least two output rows; tiny terminals use ordinary output.
        self.stream.write('\x1b7' + screen.workspace_background() + '\x1b[r')
        if rows >= 3:
            label = plain_text(self.status).replace('\n', ' ')
            label = ui.wrap_cells(label, max(1, columns - 1))[0]
            self.stream.write(f'\x1b[1;{rows - 1}r\x1b[{rows};1H\x1b[2K' + label)
            self.active = True
        else:
            self.active = False
        self.stream.write('\x1b8')
        self.stream.flush()

    def __exit__(self, kind, value, traceback):
        if not self.enabled:
            return
        import shutil
        import signal
        try:
            rows = shutil.get_terminal_size((80, 24)).lines
            self.stream.write('\x1b7')
            if self.active:
                self.stream.write(f'\x1b[{rows};1H\x1b[2K')
            self.stream.write('\x1b[r\x1b8')
            self.stream.flush()
        finally:
            signal.signal(signal.SIGWINCH, self.previous_resize)
