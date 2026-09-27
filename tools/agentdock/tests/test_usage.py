import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from agentdock.usage import TokenUsage
from agentdock.progress import ElapsedTimer
from agentdock.activity import read_activities, activity_metrics
from agentdock.cli import run_logged, run_claude, WorkflowError


class UsageTests(unittest.TestCase):
    def parse(self, provider, text):
        updates = []
        usage = TokenUsage(provider, lambda *values: updates.append(values))
        for character in text:
            usage.feed(character)
        usage.finish()
        return updates

    def test_codex_fragmented_count(self):
        self.assertEqual(self.parse('codex', 'response\ntokens used\n12,345'), [(12345, False)])
        self.assertEqual(self.parse('codex', 'tokens used\nunknown\n123'), [])

    def test_aider_sums_calls_and_marks_rounded_counts(self):
        self.assertEqual(self.parse('aider', 'Tokens: 1.2k sent, 35 received.\nTokens: 400 sent, 10 received.\n'),
                         [(1235, True), (1645, True)])

    def test_claude_usage_counts_cache_and_ignores_bad_records(self):
        event = dict(type='result', usage=dict(input_tokens=100, output_tokens=20,
                     cache_read_input_tokens=300, cache_creation_input_tokens=50))
        self.assertEqual(self.parse('claude', json.dumps(event)), [(470, False)])
        for usage in ({}, None, {'input_tokens': '100', 'output_tokens': 20}):
            self.assertEqual(self.parse('claude', json.dumps(dict(type='result', usage=usage))), [])

    def test_prompt_shows_tokens_without_extra_summary(self):
        from agentdock.cli import DEFAULT_CONFIG, agent_status
        import copy
        config = copy.deepcopy(DEFAULT_CONFIG)
        self.assertIn('CHAT · local · 139 tokens', agent_status(config, 'local', (139, False)))
        config['chat_mode'] = 'build'
        self.assertIn('BUILD · ≈1,234 tokens', agent_status(config, 'local', (1234, True)))
        self.assertNotIn('tokens', agent_status(config, 'local'))

    def test_capture_persists_tokens_and_preserves_response(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            output = io.StringIO()
            # Simulate Aider output while using a real child process.
            with patch('sys.stdout', output), patch('agentdock.cli.TokenUsage',
                    side_effect=lambda provider, update: TokenUsage('aider', update)):
                result = run_logged([sys.executable, '-c', "print('Tokens: 100 sent, 20 received.')"],
                                    repo, repo / 'worker.log', agent_name='local')
            self.assertEqual(result.stdout, 'Tokens: 100 sent, 20 received.\n')
            record = read_activities(repo)[0]
            self.assertEqual(record['tokens'], 120)
            self.assertIn('120 tokens', activity_metrics(record))
            self.assertNotIn('tokens', output.getvalue())

    def test_claude_response_is_extracted_and_errors_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            destination = repo / 'response.md'
            for is_error in (False, True):
                payload = json.dumps(dict(type='result', result='Hello', is_error=is_error))
                with patch('agentdock.cli.run_logged', return_value=CompletedProcess([], 0, payload)) as run:
                    if is_error:
                        with self.assertRaises(WorkflowError):
                            run_claude(repo, 'prompt', destination, None, repo / 'log')
                    else:
                        run_claude(repo, 'prompt', destination, None, repo / 'log')
                        self.assertEqual(destination.read_text(), 'Hello\n')
                        self.assertIn('json', run.call_args.args[0])

    def test_ollama_counts_input_and_output_without_double_counting_cache(self):
        self.assertEqual(self.parse('ollama', 'prompt eval count: 100 token(s)\nprompt eval cached: 50 token(s)\neval count: 25 token(s)\n'), [(125, False)])

    def test_claude_model_totals_include_nested_agents(self):
        event = dict(type='result', usage=dict(input_tokens=1, output_tokens=2),
                     modelUsage={'model': dict(inputTokens=100, outputTokens=20, cacheReadInputTokens=30)})
        self.assertEqual(self.parse('claude', json.dumps(event)), [(150, False)])

    def test_local_chat_removes_metrics_from_answer(self):
        import copy
        from agentdock.cli import DEFAULT_CONFIG, run_chat_agent
        response = '\x1b[?25l⠋\n\x1b[0mHello\n\n  total duration: 1s\n  prompt eval count: 100 token(s)\n  eval count: 25 token(s)\n  eval rate: 25 tokens/s\n\x1b[?25h'
        with tempfile.TemporaryDirectory() as directory, patch('agentdock.cli.ensure_ollama_ready'), patch(
                'agentdock.cli.run_logged', return_value=CompletedProcess([], 0, response)) as run:
            answer = run_chat_agent(Path(directory), copy.deepcopy(DEFAULT_CONFIG), 'local', 'hi')
        self.assertEqual(answer, 'Hello')
        self.assertIn('--verbose', run.call_args.args[0])
