import json
import tempfile
import unittest
from pathlib import Path

from agentdock.cli import ensure_state
from agentdock.file_diff import is_tool_artifact


class StateDirectoryTests(unittest.TestCase):
    def test_creates_agentdock_state_with_default_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            state = ensure_state(repo)
            self.assertEqual(state.name, ".agentdock")
            self.assertTrue((state / "config.json").exists())
            self.assertEqual(json.loads((state / "config.json").read_text())["version"], 2)
            self.assertEqual(ensure_state(repo), state)

    def test_agentdock_state_is_excluded_from_patches(self):
        self.assertTrue(is_tool_artifact(".agentdock/config.json"))
        self.assertTrue(is_tool_artifact("nested/.agentdock/worker.log"))
        self.assertTrue(is_tool_artifact(".aider.chat.history.md"))
