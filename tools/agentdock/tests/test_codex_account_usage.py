import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agentdock.usage import read_codex_usage, usage_lines, UsageError
from agentdock.cli import chat_loop, DEFAULT_CONFIG, CHAT_COMMANDS


class UsageTests(unittest.TestCase):
    def test_windows_and_unknowns(self):
        lines = '\n'.join(usage_lines({'rateLimits': {'primary': {
            'usedPercent': 25, 'windowDurationMins': 300, 'resetsAt': 1900000000},
            'secondary': {'usedPercent': 100, 'windowDurationMins': 10080}}}))
        self.assertIn('5-hour: 75% remaining', lines)
        self.assertIn('7-day: 0% remaining', lines)
        self.assertIn('reset time unavailable', lines)
        self.assertIn('unavailable', '\n'.join(usage_lines({'rateLimits': {}})))

    def test_multiple_buckets_and_terminal_sanitization(self):
        lines = '\n'.join(usage_lines({'rateLimitsByLimitId': {
            'codex': {'planType': 'pro', 'credits': {'balance': '15'}},
            'other': {'limitName': '\x1b\nother', 'primary': {'usedPercent': 10}}}}))
        self.assertIn('pro plan', lines)
        self.assertIn('Credits remaining: 15', lines)
        self.assertIn('90% remaining', lines)
        self.assertNotIn('\x1b', lines)

    def fake(self, code, timeout=2):
        real_popen = subprocess.Popen
        processes = []
        def start(*args, **kwargs):
            process = real_popen([sys.executable, '-u', '-c', code], **kwargs)
            processes.append(process)
            return process
        try:
            with tempfile.TemporaryDirectory() as directory, patch('agentdock.usage.shutil.which', return_value='codex'), patch('agentdock.usage.subprocess.Popen', side_effect=start):
                return read_codex_usage(Path(directory), None, timeout)
        finally:
            for process in processes:
                self.assertIsNotNone(process.poll())
                self.assertTrue(process.stdout.closed)

    def test_handshake_notifications_and_cleanup(self):
        result = self.fake('''import json,sys,time
assert json.loads(input())['method'] == 'initialize'
print(json.dumps({'id':1,'result':{}}), flush=True)
assert json.loads(input())['method'] == 'initialized'
assert json.loads(input())['method'] == 'account/rateLimits/read'
print(json.dumps({'method':'notification'}), flush=True)
print(json.dumps({'id':2,'result':{'rateLimits':{}}}), flush=True)
time.sleep(20)
''')
        self.assertEqual(result, {'rateLimits': {}})

    def test_timeout_exit_and_rpc_error(self):
        for code in ["import time; time.sleep(20)", "pass", "import json; input(); print(json.dumps({'id':1,'error':{'message':'secret'}}), flush=True)"]:
            with self.assertRaises(UsageError) as error:
                self.fake(code, timeout=.2)
            self.assertNotIn('secret', str(error.exception))

    def test_command_does_not_call_model(self):
        with tempfile.TemporaryDirectory() as directory, patch('agentdock.cli.read_codex_usage', return_value={'rateLimits': {}}) as read, patch('agentdock.cli.run_chat_agent') as model, patch('sys.stdout', new_callable=io.StringIO) as output:
            chat_loop(Path(directory), DEFAULT_CONFIG, None, '/usage')
            read.assert_called_once()
            model.assert_not_called()
            self.assertIn('CODEX USAGE', output.getvalue())
            self.assertIn('/usage', CHAT_COMMANDS)
