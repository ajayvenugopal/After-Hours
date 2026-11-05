"""Regression coverage for nested Codex tool output wrappers."""

import json
import unittest
from server import readable_output


class OutputTests(unittest.TestCase):
    def test_nested_process_output(self):
        result = [
            {
                "type": "input_text",
                "text": json.dumps(
                    {"chunk_id": "example", "output": "Tests passed\n", "exit_code": 0}
                ),
            }
        ]
        self.assertEqual(readable_output(result), "Tests passed\n")

    def test_plain_output(self):
        self.assertEqual(readable_output("hello"), "hello")

    def test_stdout_and_stderr(self):
        self.assertEqual(
            readable_output({"stdout": "out", "stderr": "err"}), "out\nerr"
        )

    def test_unknown_metadata_is_not_rendered(self):
        self.assertEqual(
            readable_output({"private_metadata": "example"}), "Tool completed."
        )
