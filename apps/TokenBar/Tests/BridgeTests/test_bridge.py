import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


bridge = module('bridge', 'claude-bridge.py')
installer = module('installer', 'install-claude-bridge.py')


class BridgeTests(unittest.TestCase):
    def test_only_usage_is_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            bridge.write_snapshot({'rate_limits': {'five_hour': {'used_percentage': 42}},
                                   'context_window': {'context_window_size': 200000},
                                   'transcript_path': '/private/conversation', 'session_id': 'secret'}, path)
            result = json.loads((path / 'claude-usage.json').read_text())
            self.assertEqual(set(result), {'rate_limits', 'context_window', 'updated_at'})
            self.assertEqual((path / 'claude-usage.json').stat().st_mode & 0o777, 0o600)

    def test_reinstall_and_uninstall_preserve_existing_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            settings = home / '.claude/settings.json'
            settings.parent.mkdir()
            original = {'theme': 'dark', 'statusLine': {'type': 'command', 'command': 'echo hello', 'padding': 2}}
            settings.write_text(json.dumps(original))
            installer.install(home)
            installer.install(home)
            installer.install(home, uninstall=True)
            self.assertEqual(json.loads(settings.read_text()), original)

    def test_uninstall_preserves_subsequent_user_change(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            installer.install(home)
            settings = home / '.claude/settings.json'
            changed = {'statusLine': {'type': 'command', 'command': 'echo new'}}
            settings.write_text(json.dumps(changed))
            installer.install(home, uninstall=True)
            self.assertEqual(json.loads(settings.read_text()), changed)

    def test_malformed_settings_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            settings = home / '.claude/settings.json'
            settings.parent.mkdir()
            settings.write_text('{bad')
            with self.assertRaises(ValueError):
                installer.install(home)
            self.assertEqual(settings.read_text(), '{bad')
