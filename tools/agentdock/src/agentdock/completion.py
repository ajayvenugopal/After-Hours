"""Fast, local command suggestions shared by both terminal input adapters."""
import os
import sys


def suggestions(config, commands, before_cursor):
    """Return (replacement, description) pairs for the entire input prefix."""
    if not before_cursor.startswith('/'):
        return []
    if ' ' not in before_cursor:
        return [(name, description) for name, description in commands.items()
                if name.startswith(before_cursor)]
    command, prefix = before_cursor.split(' ', 1)
    options = {
        '/agent': list(config['agents']),
        '/theme': ['violet', 'amber', 'mono'],
        '/mode': ['chat', 'build'],
        '/output': ['compact', 'raw'],
        '/workflow': ['setup'],
        '/usage': ['codex'],
    }
    if command == '/model':
        models = sorted({str(agent['model']) for agent in config['agents'].values()
                         if agent.get('model')})
        if prefix.startswith('set '):
            return [(f'/model set {model}', 'Use configured model') for model in models
                    if model.startswith(prefix[4:])]
        options[command] = ['reset', 'default', 'set'] + models
    return [(f'{command} {value}', commands.get(command, ''))
            for value in options.get(command, []) if value.startswith(prefix)]


def command_completer(config, commands, words=()):
    from prompt_toolkit.completion import Completer, Completion

    class CommandCompleter(Completer):
        def get_completions(self, document, complete_event):
            if document.text_after_cursor:
                return
            prefix = document.text_before_cursor
            candidates = suggestions(config, commands, prefix)
            # Retain predefined model suggestions offered by the existing launcher.
            if prefix.startswith('/model '):
                seen = {value for value, _ in candidates}
                candidates += [(word, commands.get('/model', 'Use model')) for word in words
                               if word.startswith(prefix) and word not in seen]
            for value, description in candidates:
                yield Completion(value, start_position=-len(prefix), display_meta=description)

    return CommandCompleter()


def create_session(config, commands):
    """Keep scripts and minimal source checkouts on the standard input path."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()) or os.environ.get('TERM') == 'dumb':
        return None
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import InMemoryHistory
    except ImportError:
        return None
    return PromptSession(completer=command_completer(config, commands), complete_while_typing=True,
                         history=InMemoryHistory(), reserve_space_for_menu=8,
                         enable_history_search=False)


def read_message(session, prompt):
    if session is None:
        return input(prompt)
    from prompt_toolkit.formatted_text import ANSI
    from prompt_toolkit.output import ColorDepth
    from . import ui
    # readline's nonprinting markers are not part of the ANSI prompt format.
    depth = ColorDepth.DEPTH_1_BIT if 'NO_COLOR' in os.environ or ui.theme == 'mono' else None
    return session.prompt(ANSI(prompt.replace('\001', '').replace('\002', '')),
                          color_depth=depth)
