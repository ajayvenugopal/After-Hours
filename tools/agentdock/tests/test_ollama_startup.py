import copy
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

from agentdock.cli import (DEFAULT_CONFIG, WorkflowError, ensure_ollama_ready,
                         SESSION_MODELS, track_session_model, cleanup_session_models, main)


def refused():
    error = WorkflowError("Ollama unreachable")
    error.__cause__ = urllib.error.URLError(ConnectionRefusedError("refused"))
    return error


class OllamaStartupTests(unittest.TestCase):
    def test_only_newly_loaded_models_are_unloaded(self):
        token = SESSION_MODELS.set({})
        base = "http://127.0.0.1:11434"
        try:
            with patch("agentdock.cli.urllib.request.urlopen", side_effect=[
                io.BytesIO(b'{"models":[{"name":"existing:latest"}]}'),
                io.BytesIO(b'{"models":[{"name":"existing:latest"}]}'),
                io.BytesIO(b'{"done":true}')
            ]) as request, patch("builtins.print"):
                track_session_model(base, "existing")
                track_session_model(base, "new")
                track_session_model(base, "new")
                cleanup_session_models()
            self.assertEqual(request.call_count, 3)
            self.assertEqual(json.loads(request.call_args.args[0].data),
                             {"model": "new:latest", "keep_alive": 0, "stream": False})
            self.assertEqual(SESSION_MODELS.get(), {})
        finally:
            SESSION_MODELS.reset(token)

    def test_unknown_ownership_and_remote_models_are_not_unloaded(self):
        token = SESSION_MODELS.set({})
        try:
            with patch("agentdock.cli.urllib.request.urlopen", side_effect=OSError("offline")) as request, patch("builtins.print"):
                track_session_model("http://127.0.0.1:11434", "custom")
                track_session_model("http://remote.example:11434", "custom")
                cleanup_session_models()
            self.assertEqual(request.call_count, 1)
        finally:
            SESSION_MODELS.reset(token)

    def test_main_cleans_up_when_chat_exits_or_fails(self):
        for error in (None, WorkflowError("failed")):
            with tempfile.TemporaryDirectory() as directory:
                with patch("agentdock.cli.find_repo", return_value=Path(directory)), patch("agentdock.cli.chat_loop", side_effect=error), patch("agentdock.cli.cleanup_session_models") as cleanup, patch("builtins.print"):
                    if error:
                        with self.assertRaises(SystemExit):
                            main(["chat"])
                    else:
                        main(["chat"])
                cleanup.assert_called_once()

    def test_existing_server_warms_selected_model_without_starting_process(self):
        with patch("agentdock.cli.fetch_ollama_models", return_value=["custom:latest"]), patch("agentdock.cli.subprocess.Popen") as start, patch("agentdock.cli.urllib.request.urlopen", return_value=io.BytesIO(b'{"done":true}')) as request, patch("builtins.print"):
            ensure_ollama_ready(Path("/tmp"), DEFAULT_CONFIG, "ollama_chat/custom")
        start.assert_not_called()
        self.assertEqual(json.loads(request.call_args.args[0].data)["model"], "custom")

    def test_missing_model_never_downloads(self):
        with patch("agentdock.cli.fetch_ollama_models", return_value=[]), patch("agentdock.cli.subprocess.Popen") as start, patch("agentdock.cli.urllib.request.urlopen") as request:
            with self.assertRaisesRegex(WorkflowError, "ollama pull custom"):
                ensure_ollama_ready(Path("/tmp"), DEFAULT_CONFIG, "custom")
        start.assert_not_called()
        request.assert_not_called()

    def test_refused_local_server_starts_and_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            process = MagicMock()
            process.poll.return_value = None
            with patch("agentdock.cli.fetch_ollama_models", side_effect=[refused(), ["custom"]]), patch("agentdock.cli.shutil.which", return_value="/bin/ollama"), patch("agentdock.cli.subprocess.Popen", return_value=process) as start, patch("agentdock.cli.threading.Thread"), patch("builtins.print"):
                ensure_ollama_ready(Path(directory), DEFAULT_CONFIG, "custom", warm=False)
            self.assertEqual(start.call_args.args[0], ["/bin/ollama", "serve"])
            self.assertEqual(start.call_args.kwargs["env"]["OLLAMA_HOST"], DEFAULT_CONFIG["ollama_base_url"])
            process.terminate.assert_not_called()

    def test_remote_failure_does_not_start_local_server(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["ollama_base_url"] = "http://remote.example:11434"
        with patch("agentdock.cli.fetch_ollama_models", side_effect=refused()), patch("agentdock.cli.subprocess.Popen") as start:
            with self.assertRaisesRegex(WorkflowError, "local HTTP endpoint"):
                ensure_ollama_ready(Path("/tmp"), config, "custom")
        start.assert_not_called()

    def test_load_error_is_actionable(self):
        with patch("agentdock.cli.fetch_ollama_models", return_value=["custom"]), patch("agentdock.cli.urllib.request.urlopen", return_value=io.BytesIO(b'{"error":"not enough memory"}')), patch("builtins.print"):
            with self.assertRaisesRegex(WorkflowError, "not enough memory"):
                ensure_ollama_ready(Path("/tmp"), DEFAULT_CONFIG, "custom")

    def test_loading_notice_once_per_session_but_readiness_still_checked(self):
        from agentdock.cli import SESSION_READY
        token = SESSION_READY.set(set())
        try:
            with patch('agentdock.cli.fetch_ollama_models', return_value=['custom:latest']) as check, patch(
                    'agentdock.cli.urllib.request.urlopen', side_effect=lambda *a, **k: io.BytesIO(b'{"done":true}')) as request, patch(
                    'agentdock.cli.status') as status, patch('agentdock.cli.success') as success, patch(
                    'agentdock.cli.ElapsedTimer') as timer:
                ensure_ollama_ready(Path('/tmp'), DEFAULT_CONFIG, 'custom')
                ensure_ollama_ready(Path('/tmp'), DEFAULT_CONFIG, 'ollama_chat/custom:latest')
            self.assertEqual(check.call_count, 2)
            self.assertEqual(request.call_count, 2)
            status.assert_called_once()
            success.assert_called_once()
            timer.assert_called_once()
        finally:
            SESSION_READY.reset(token)

    def test_failed_warmup_does_not_suppress_retry_notice(self):
        from agentdock.cli import SESSION_READY
        token = SESSION_READY.set(set())
        try:
            with patch('agentdock.cli.fetch_ollama_models', return_value=['custom']), patch(
                    'agentdock.cli.urllib.request.urlopen', side_effect=[io.BytesIO(b'{"error":"failed"}'), io.BytesIO(b'{"done":true}')]), patch(
                    'agentdock.cli.status') as status, patch('agentdock.cli.success'), patch('agentdock.cli.ElapsedTimer'):
                with self.assertRaises(WorkflowError):
                    ensure_ollama_ready(Path('/tmp'), DEFAULT_CONFIG, 'custom')
                ensure_ollama_ready(Path('/tmp'), DEFAULT_CONFIG, 'custom')
            self.assertEqual(status.call_count, 2)
        finally:
            SESSION_READY.reset(token)
