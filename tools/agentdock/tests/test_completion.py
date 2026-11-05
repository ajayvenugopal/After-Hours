import copy
import unittest
from unittest.mock import patch

from agentdock.cli import CHAT_COMMANDS, DEFAULT_CONFIG, configure_readline
from agentdock.completion import suggestions, create_session, read_message, command_completer


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.config = copy.deepcopy(DEFAULT_CONFIG)

    def values(self, text):
        return [value for value, _ in suggestions(self.config, CHAT_COMMANDS, text)]

    def test_native_launchers_have_descriptions(self):
        items = dict(suggestions(self.config, CHAT_COMMANDS, '/'))
        self.assertIn('native', items['/codex'].lower())
        self.assertIn('/claude', items)
        self.assertEqual(self.values('/cla'), ['/claude'])

    def test_arguments_and_no_prose_completion(self):
        self.assertEqual(self.values('/theme a'), ['/theme amber'])
        self.assertEqual(self.values('/mode b'), ['/mode build'])
        self.assertEqual(self.values('/output r'), ['/output raw'])
        self.assertEqual(self.values('explain /cla'), [])
        self.assertEqual(self.values('/build '), [])

    def test_live_config_and_model_set(self):
        self.config['agents']['custom'] = {'model': 'custom-model'}
        self.assertEqual(self.values('/agent cus'), ['/agent custom'])
        self.assertEqual(self.values('/model set cus'), ['/model set custom-model'])

    def test_readline_replaces_only_current_word(self):
        with patch('agentdock.cli.readline') as readline:
            configure_readline(self.config)
            complete = readline.set_completer.call_args.args[0]
            readline.get_line_buffer.return_value = '/model set cu'
            readline.get_endidx.return_value = 13
            readline.get_begidx.return_value = 11
            self.config['agents']['custom'] = {'model': 'custom-model'}
            self.assertEqual(complete('cu', 0), 'custom-model')
            self.assertIsNone(complete('cu', 1))

    def test_redirected_input_uses_builtin(self):
        with patch('sys.stdin.isatty', return_value=False):
            self.assertIsNone(create_session(self.config, CHAT_COMMANDS))
        with patch('builtins.input', return_value='/help') as read:
            self.assertEqual(read_message(None, '> '), '/help')
            read.assert_called_once_with('> ')

    def test_live_menu_has_descriptions_and_retains_model_catalog(self):
        from prompt_toolkit.document import Document
        from prompt_toolkit.completion import CompleteEvent
        completer = command_completer(self.config, CHAT_COMMANDS, ['/model catalog-model'])
        commands = list(completer.get_completions(Document('/cla'), CompleteEvent()))
        self.assertEqual([item.text for item in commands], ['/claude'])
        self.assertTrue(commands[0].display_meta_text)
        models = list(completer.get_completions(Document('/model cat'), CompleteEvent()))
        self.assertEqual([item.text for item in models], ['/model catalog-model'])
        self.assertEqual(list(completer.get_completions(Document('ordinary text'), CompleteEvent())), [])
        self.assertEqual(list(completer.get_completions(Document('/agent trailing', cursor_position=3), CompleteEvent())), [])
