import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentdock.cli import (
    DEFAULT_CONFIG,
    WorkflowError,
    build_parser,
    ensure_state,
    extract_plan_paths,
    native_agent_argv,
    print_models,
    set_agent_model,
    load_config,
    ollama_model_name,
    parse_gradle_command,
    review_prompt,
    make_diff,
    chat_loop,
    create_agent_interactively,
)


class ConfigTests(unittest.TestCase):
    def test_default_config_is_created_and_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            ensure_state(repo)
            self.assertEqual(load_config(repo), DEFAULT_CONFIG)

    def test_unknown_config_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            state = ensure_state(repo)
            (state / "config.json").write_text(json.dumps({"surprise": True}))
            with self.assertRaises(WorkflowError):
                load_config(repo)

    def test_invalid_config_value_type_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            state = ensure_state(repo)
            (state / "config.json").write_text(json.dumps({"gradle_command": ["./gradlew", "test"]}))
            with self.assertRaises(WorkflowError):
                load_config(repo)

    def test_agent_config_is_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            state = ensure_state(repo)
            config = DEFAULT_CONFIG | {
                "default_chat_agent": "claude",
                "workflow": {
                    "planner_agent": "codex",
                    "worker_agent": "local",
                    "reviewer_agent": "claude",
                    "debugger_agent": "codex",
                },
            }
            (state / "config.json").write_text(json.dumps(config))

            loaded = load_config(repo)

            self.assertEqual(loaded["default_chat_agent"], "claude")
            self.assertEqual(loaded["workflow"]["reviewer_agent"], "claude")

    def test_old_flat_config_is_migrated_in_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            state = ensure_state(repo)
            (state / "config.json").write_text(
                json.dumps(
                    {
                        "qwen_model": "ollama_chat/custom:latest",
                        "max_repair_attempts": 2,
                        "codex_planner_model": None,
                        "codex_reviewer_model": None,
                        "gradle_command": None,
                        "final_codex_review": True,
                        "ollama_base_url": "http://127.0.0.1:11434",
                    }
                )
            )

            loaded = load_config(repo)

            self.assertEqual(loaded["version"], 2)
            self.assertEqual(loaded["max_repair_attempts"], 2)
            self.assertIn("local", loaded["agents"])

    def test_bool_repair_attempts_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            state = ensure_state(repo)
            (state / "config.json").write_text(json.dumps({"max_repair_attempts": True}))
            with self.assertRaises(WorkflowError):
                load_config(repo)

    def test_unknown_agent_backend_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            state = ensure_state(repo)
            config = json.loads(json.dumps(DEFAULT_CONFIG))
            config["agents"]["bad"] = {
                "backend": "fable",
                "auth": "subscription",
                "model": None,
                "role": "chat",
                "lifetime": "invocation",
                "timeout_seconds": 900,
            }
            (state / "config.json").write_text(json.dumps(config))
            with self.assertRaises(WorkflowError):
                load_config(repo)


class CommandTests(unittest.TestCase):
    def test_plan_gradle_command(self):
        self.assertEqual(
            parse_gradle_command("GRADLE_COMMAND: ./gradlew :app:testDebugUnitTest --stacktrace", None),
            ["./gradlew", ":app:testDebugUnitTest", "--stacktrace"],
        )

    def test_config_overrides_plan(self):
        self.assertEqual(
            parse_gradle_command("GRADLE_COMMAND: ./gradlew test", "./gradlew check"),
            ["./gradlew", "check"],
        )

    def test_non_gradle_command_is_rejected(self):
        with self.assertRaises(WorkflowError):
            parse_gradle_command("GRADLE_COMMAND: rm -rf .", None)

    def test_shell_chaining_is_rejected(self):
        with self.assertRaises(WorkflowError):
            parse_gradle_command("GRADLE_COMMAND: ./gradlew test && echo done", None)

    def test_run_subcommand_parses_task(self):
        args = build_parser().parse_args(["run", "Do the thing", "--skip-doctor"])
        self.assertEqual(args.command, "run")
        self.assertEqual(args.task, "Do the thing")
        self.assertTrue(args.skip_doctor)

    def test_agent_add_subcommand_parses_backend(self):
        args = build_parser().parse_args(
            ["agents", "add", "opus", "--backend", "claude", "--model", "opus", "--default"]
        )
        self.assertEqual(args.agents_command, "add")
        self.assertEqual(args.backend, "claude")
        self.assertTrue(args.default)

    def test_print_models_includes_default_agent_marker(self):
        with patch("builtins.print") as mocked_print:
            print_models(DEFAULT_CONFIG)
        output = "\n".join(call.args[0] for call in mocked_print.call_args_list)
        self.assertIn("local [aider_ollama", output)
        self.assertIn("*", output)

    def test_native_claude_command_uses_model_when_configured(self):
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["agents"]["claude"]["model"] = "sonnet"

        argv = native_agent_argv(Path("/tmp/project"), config, "claude")

        self.assertEqual(argv, ["claude", "--model", "sonnet"])

    def test_native_local_command_uses_aider_without_commits(self):
        argv = native_agent_argv(Path("/tmp/project"), DEFAULT_CONFIG, "local")

        self.assertEqual(argv, ["aider", "--model", "ollama_chat/qwen3-coder:30b-a3b-q4_K_M", "--no-auto-commits", "--no-dirty-commits"])

    def test_set_agent_model_updates_config_file(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            ensure_state(repo)
            config = load_config(repo)

            set_agent_model(repo, config, "codex", "set gpt-5.6-sol", announce=False)

            loaded = load_config(repo)
            self.assertEqual(loaded["agents"]["codex"]["model"], "gpt-5.6-sol")

    def test_set_agent_model_reset_uses_default(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            ensure_state(repo)
            config = load_config(repo)
            config["agents"]["codex"]["model"] = "gpt-5.6-sol"

            set_agent_model(repo, config, "codex", "reset", announce=False)

            loaded = load_config(repo)
            self.assertIsNone(loaded["agents"]["codex"]["model"])


class ChatTests(unittest.TestCase):
    def test_wizard_persists_local_model_and_default(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            ensure_state(repo)
            config = load_config(repo)
            with patch("builtins.input", side_effect=["kotlin", "local", "custom:30b", "y"]), patch("builtins.print"):
                self.assertEqual(create_agent_interactively(repo, config), "kotlin")
            loaded = load_config(repo)
            self.assertEqual(loaded["default_chat_agent"], "kotlin")
            self.assertEqual(loaded["agents"]["kotlin"]["model"], "ollama_chat/custom:30b")

    def test_failed_provider_does_not_exit_or_pollute_context(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            ensure_state(repo)
            with patch("builtins.input", side_effect=["first", "retry", "followup", "/new", "fresh", "/exit"]), patch("builtins.print"), patch("agentdock.cli.configure_readline"), patch("agentdock.cli.run_chat_agent", side_effect=[WorkflowError("offline"), "hello", "next", "done"]) as run:
                chat_loop(repo, load_config(repo), "local", None)
            self.assertEqual(run.call_count, 4)
            self.assertEqual(run.call_args_list[1].args[3], "retry")
            self.assertIn("hello", run.call_args_list[2].args[3])
            self.assertEqual(run.call_args_list[3].args[3], "fresh")

    def test_agent_histories_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            ensure_state(repo)
            with patch("builtins.input", side_effect=["local secret", "/agent codex", "hi", "/agent local", "continue", "/exit"]), patch("builtins.print"), patch("agentdock.cli.configure_readline"), patch("agentdock.cli.run_chat_agent", return_value="answer") as run:
                chat_loop(repo, load_config(repo), "local", None)
            self.assertEqual(run.call_args_list[1].args[3], "hi")
            self.assertIn("local secret", run.call_args_list[2].args[3])


class PromptTests(unittest.TestCase):
    def test_extracts_existing_repo_paths_only(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "app").mkdir()
            (repo / "app" / "build.gradle.kts").write_text("")
            plan = "Change `app/build.gradle.kts`, ignore `missing.kt` and `.agentdock/TASK.md`."
            self.assertEqual(extract_plan_paths(plan, repo), ["app/build.gradle.kts"])

    def test_review_prompt_contains_only_supplied_context(self):
        prompt = review_prompt("TASK", "PLAN", "DIFF", "TEST")
        for marker in ("TASK", "PLAN", "DIFF", "TEST"):
            self.assertIn(marker, prompt)
        self.assertIn("Do not inspect the repository", prompt)

    def test_model_prefix_is_removed_for_ollama_check(self):
        self.assertEqual(
            ollama_model_name("ollama_chat/qwen3-coder:30b-a3b-q4_K_M"),
            "qwen3-coder:30b-a3b-q4_K_M",
        )


class DiffTests(unittest.TestCase):
    def test_diff_includes_untracked_files_but_not_agentdock_state(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            (repo / "tracked.txt").write_text("before\n")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
            (repo / "tracked.txt").write_text("after\n")
            (repo / "new.txt").write_text("new\n")
            (repo / ".agentdock").mkdir()
            (repo / ".agentdock" / "TASK.md").write_text("private state\n")

            diff = make_diff(repo)

            self.assertIn("tracked.txt", diff)
            self.assertIn("new.txt", diff)
            self.assertNotIn("private state", diff)


if __name__ == "__main__":
    unittest.main()
