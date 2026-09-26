import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentdock.cli import (DEFAULT_CONFIG, WorkflowError, chat_loop, ensure_state,
                         load_config, resolved_workflow, setup_workflow, workflow)


class WorkflowSetupTests(unittest.TestCase):
    def test_same_provider_can_have_distinct_stage_models(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["stage_models"] = {"planning": "plan-model", "review": "review-model", "coding": None}
        result = resolved_workflow(config)
        self.assertEqual(result["agents"][result["workflow"]["planner_agent"]]["model"], "plan-model")
        self.assertEqual(result["agents"][result["workflow"]["reviewer_agent"]]["model"], "review-model")
        self.assertIsNone(config["agents"]["codex"]["model"])

    def test_cloud_coding_is_rejected_before_execution(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["workflow"]["worker_agent"] = "codex"
        with self.assertRaises(WorkflowError):
            resolved_workflow(config)

    def test_setup_persists_choices_without_modifying_chat_models(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            ensure_state(repo)
            config = load_config(repo)
            with patch("builtins.input", side_effect=["claude", "plan-model", "local", "qwen-custom", "codex", "review-model", "y"]), patch("builtins.print"):
                setup_workflow(repo, config)
            saved = load_config(repo)
            self.assertEqual(saved["workflow"]["planner_agent"], "claude")
            self.assertEqual(saved["stage_models"]["coding"], "ollama_chat/qwen-custom")
            self.assertEqual(saved["chat_mode"], "build")
            self.assertIsNone(saved["agents"]["claude"]["model"])

    def test_cancelled_setup_does_not_save_partial_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            ensure_state(repo)
            config = load_config(repo)
            with patch("builtins.input", side_effect=["claude", KeyboardInterrupt]), patch("builtins.print"):
                with self.assertRaises(KeyboardInterrupt):
                    setup_workflow(repo, config)
            self.assertEqual(config, DEFAULT_CONFIG)
            self.assertEqual(load_config(repo), DEFAULT_CONFIG)

    def test_build_mode_routes_plain_messages_without_chat_call(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["chat_mode"] = "build"
        with patch("agentdock.cli.workflow") as run, patch("agentdock.cli.run_chat_agent") as chat:
            chat_loop(Path("/tmp"), config, "local", "Build retry handling")
        run.assert_called_once()
        self.assertEqual(run.call_args.args[1], "Build retry handling")
        chat.assert_not_called()

    def test_workflow_handoffs_are_sequential_and_local_fixes_follow_review(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            events = []

            def paid(repo, config, name, prompt, destination, log, **kwargs):
                if destination.name == "PLAN.md":
                    events.append("plan")
                    destination.write_text("Implement retry\nGRADLE_COMMAND: ./gradlew test\n")
                else:
                    events.append("review")
                    destination.write_text("Add a timeout test")

            def worker(*args, **kwargs):
                self.assertEqual(args[1]["agents"][kwargs["agent_name"]]["backend"], "aider_ollama")
                events.append("local")

            def gradle(repo, argv, output, log):
                events.append("test")
                output.write_text("Tests passed")
                return True

            with patch("agentdock.cli.run_paid_agent", side_effect=paid), patch("agentdock.cli.run_aider", side_effect=worker), patch("agentdock.cli.run_gradle", side_effect=gradle), patch("agentdock.cli.changed_files", return_value=[]), patch("agentdock.cli.make_diff", side_effect=["diff", "updated diff", "updated diff"]), patch("agentdock.cli.worker_edit_files", return_value=[]), patch("builtins.print"):
                workflow(repo, "Build retries", copy.deepcopy(DEFAULT_CONFIG), skip_doctor=True)
            self.assertEqual(events, ["plan", "local", "test", "review", "local", "test"])
