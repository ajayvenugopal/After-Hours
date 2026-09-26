import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentdock.cli import ensure_state
from agentdock.file_diff import is_tool_artifact


class StateMigrationTests(unittest.TestCase):
    def test_preserves_settings_logs_and_old_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            old = repo / ".ai-task"
            (old / "tools").mkdir(parents=True)
            (old / "config.json").write_text('{"theme": "amber"}')
            (old / "worker.log").write_text("history")
            (old / "tools" / "marker").write_text("preserved")
            with patch("builtins.print"):
                state = ensure_state(repo)
            self.assertEqual(state.name, ".agentdock")
            self.assertFalse(old.exists())
            self.assertEqual(json.loads((state / "config.json").read_text()), {"theme": "amber"})
            self.assertEqual((state / "worker.log").read_text(), "history")
            self.assertEqual((state / "legacy-tools" / "marker").read_text(), "preserved")
            self.assertFalse((state / "tools").exists())
            self.assertEqual(ensure_state(repo), state)

    def test_existing_new_state_does_not_merge_or_delete_old_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            state = ensure_state(repo)
            old = repo / ".ai-task"
            old.mkdir()
            (old / "worker.log").write_text("keep")
            self.assertEqual(ensure_state(repo), state)
            self.assertTrue((old / "worker.log").exists())

    def test_both_names_are_excluded_from_patches(self):
        for name in (".agentdock/config.json", ".ai-task/config.json"):
            self.assertTrue(is_tool_artifact(name))
