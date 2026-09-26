import sys
import io
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agentdock.activity import Activity, dashboard, read_activities
from agentdock.cli import WorkflowError, main, run_logged


class ActivityTests(unittest.TestCase):
    def test_terminal_output_streams_before_process_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            gate = repo / "visible"

            class Terminal(io.StringIO):
                def write(self, value):
                    result = super().write(value)
                    if "working" in self.getvalue():
                        gate.touch()
                    return result

            terminal = Terminal()
            script = "import pathlib,sys,time; print('working',flush=True)\nwhile not pathlib.Path(sys.argv[1]).exists(): time.sleep(.02)\nprint('finished')"
            with patch("sys.stdout", terminal):
                result = run_logged([sys.executable, "-c", script, str(gate)], repo,
                                    repo / "worker.log", timeout=3, stream_output=True)
            self.assertEqual(result.stdout, "working\nfinished\n")
            self.assertEqual(terminal.getvalue(), result.stdout)
            self.assertIn(result.stdout, (repo / "worker.log").read_text())

    def test_watch_does_not_create_project_state(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            with patch("agentdock.cli.find_repo", return_value=repo):
                main(["watch", "--once"])
            self.assertEqual(list(repo.iterdir()), [])

    def test_output_is_available_before_process_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            gate = state / "continue"
            results = []
            script = "import pathlib, sys, time; print('working', flush=True)\nwhile not pathlib.Path(sys.argv[1]).exists(): time.sleep(.02)\nprint('done')"
            thread = threading.Thread(target=lambda: results.append(run_logged(
                [sys.executable, "-c", script, str(gate)], state, state / "worker.log",
                agent_name="kotlin", timeout=5,
            )))
            thread.start()
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    records = read_activities(state)
                    if records and "working" in records[0]["text"]:
                        break
                    time.sleep(.02)
                self.assertTrue(thread.is_alive())
                self.assertEqual(records[0]["status"], "running")
                self.assertIn("working", records[0]["text"])
            finally:
                gate.touch()
                thread.join(6)
            self.assertFalse(thread.is_alive())
            self.assertEqual(results[0].stdout, "working\ndone\n")
            self.assertEqual(read_activities(state)[0]["status"], "completed")

    def test_timeout_keeps_partial_output_and_status(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with self.assertRaises(WorkflowError):
                run_logged([sys.executable, "-c", "import time; print('started', flush=True); time.sleep(20)"],
                           state, state / "worker.log", timeout=1, agent_name="worker")
            record = read_activities(state)[0]
            self.assertEqual(record["status"], "timed out")
            self.assertIn("started", record["text"])

    def test_stdin_and_failure_code_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            result = run_logged([sys.executable, "-c", "import sys; print(sys.stdin.read()); sys.exit(2)"],
                                state, state / "chat.log", input_text="hello", agent_name="custom")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "hello\n")
            self.assertEqual(read_activities(state)[0]["status"], "failed")

    def test_view_is_read_only_and_sanitizes_terminal_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            activity = Activity(state, "agent", "test")
            activity.write(b"\x1b[31mhello\x1b[0m\x1b]0;bad title\x07")
            activity.finish("completed", 0)
            before = activity.path.read_bytes()
            with patch("builtins.print") as output:
                dashboard(state, ["agent"], once=True)
            self.assertEqual(before, activity.path.read_bytes())
            self.assertIn("hello", output.call_args.args[0])
            self.assertNotIn("\x1b", output.call_args.args[0])
            self.assertNotIn("bad title", output.call_args.args[0])

    def test_concurrent_invocations_have_distinct_journals(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            first = Activity(state, "agent", "test")
            second = Activity(state, "agent", "test")
            first.finish("completed", 0)
            second.finish("failed", 1)
            self.assertEqual(len(read_activities(state)), 2)

    def test_missing_executable_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with self.assertRaises(WorkflowError):
                run_logged([str(state / "missing")], state, state / "worker.log")
            self.assertEqual(read_activities(state)[0]["status"], "failed")
