import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from agentdock.cli import DEFAULT_CONFIG, chat_loop


class ChatModeTests(unittest.TestCase):
    def test_startup_chat_switches_and_direct_build(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config['chat_mode'] = 'build'  # Even a previously saved build session starts in chat.
        messages = ['hello', '/build', 'make a page', '/chat', 'explain',
                    '/build fix the page', 'thanks', '/mode build', 'add tests', '/mode chat', 'bye', '/exit']
        with patch('builtins.input', side_effect=messages), patch('builtins.print'), patch(
                'agentdock.cli.configure_readline'), patch('agentdock.cli.workflow') as build, patch(
                'agentdock.cli.run_chat_agent', return_value='answer') as chat, patch('agentdock.cli.save_config') as save:
            chat_loop(Path('/tmp'), config, None, None)
        self.assertEqual([call.args[1] for call in build.call_args_list], ['make a page', 'fix the page', 'add tests'])
        self.assertEqual(chat.call_count, 4)
        self.assertTrue(all(call.args[2] == 'local' for call in chat.call_args_list))
        self.assertEqual(chat.call_args_list[0].args[3], 'hello')
        self.assertNotIn('make a page', chat.call_args_list[1].args[3])
        self.assertEqual(config['chat_mode'], 'chat')
        save.assert_not_called()

    def test_explicit_agent_is_respected(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        with patch('builtins.input', side_effect=['hello', '/exit']), patch('builtins.print'), patch(
                'agentdock.cli.configure_readline'), patch('agentdock.cli.run_chat_agent', return_value='answer') as chat:
            chat_loop(Path('/tmp'), config, 'codex', None)
        self.assertEqual(chat.call_args.args[2], 'codex')

    def test_usage_is_shown_on_next_prompt_and_build_sums_invocations(self):
        from agentdock.cli import CURRENT_USAGE
        config = copy.deepcopy(DEFAULT_CONFIG)
        prompts = []
        messages = iter(['hello', '/build', 'make a page', '/exit'])

        def read(prompt):
            prompts.append(prompt)
            return next(messages)

        def chat(*args):
            CURRENT_USAGE.get()['chat'] = (139, False)
            return 'Hello'

        def build(*args):
            CURRENT_USAGE.get()['planner'] = (100, False)
            CURRENT_USAGE.get()['worker'] = (200, True)

        with patch('agentdock.cli.ChatInput.read', side_effect=lambda status, words: read(status)), patch('builtins.print'), patch(
                'agentdock.cli.configure_readline'), patch('agentdock.cli.run_chat_agent', side_effect=chat), patch(
                'agentdock.cli.workflow', side_effect=build):
            chat_loop(Path('/tmp'), config, None, None)
        self.assertNotIn('tokens', prompts[0])
        self.assertIn('CHAT · local · 139 tokens', prompts[1])
        self.assertNotIn('tokens', prompts[2])
        self.assertIn('BUILD · ≈300 tokens', prompts[3])
        self.assertIsNone(CURRENT_USAGE.get())
