import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentdock.cli import DEFAULT_CONFIG, WorkflowError, doctor, parse_verification_command, run_verification


class VerificationTests(unittest.TestCase):
    def test_accepts_project_specific_command(self):
        self.assertEqual(parse_verification_command("VERIFY_COMMAND: npm test", DEFAULT_CONFIG), ["npm", "test"])
        self.assertEqual(parse_verification_command("VERIFY_COMMAND: python -m pytest", DEFAULT_CONFIG), ["python", "-m", "pytest"])

    def test_configuration_overrides_plan(self):
        config = dict(DEFAULT_CONFIG, verification_command="npm run check")
        self.assertEqual(parse_verification_command("VERIFY_COMMAND: NONE", config), ["npm", "run", "check"])

    def test_gradle_plan_field_still_works(self):
        self.assertEqual(parse_verification_command("GRADLE_COMMAND: ./gradlew test", DEFAULT_CONFIG), ["./gradlew", "test"])

    def test_missing_command_is_not_reported_as_passing(self):
        with self.assertRaises(WorkflowError):
            parse_verification_command("no verification field", DEFAULT_CONFIG)

    def test_none_records_manual_verification_without_running_process(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            with patch("agentdock.cli.run_gradle") as run, patch("builtins.print"):
                self.assertTrue(run_verification(repo, [], repo / "output.txt", repo / "log"))
            self.assertIn("NOT RUN", (repo / "output.txt").read_text())
            run.assert_not_called()

    def test_doctor_does_not_require_java_gradle_or_git(self):
        with tempfile.TemporaryDirectory() as directory:
            def installed(name):
                return None if name in {"java", "gradle", "git"} else "/bin/" + name
            with patch("agentdock.cli.shutil.which", side_effect=installed), patch("agentdock.cli.fetch_ollama_models", return_value=["qwen3-coder:30b-a3b-q4_K_M"]), patch("builtins.print"):
                self.assertTrue(doctor(Path(directory), DEFAULT_CONFIG))
