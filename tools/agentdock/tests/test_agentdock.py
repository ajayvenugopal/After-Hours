import unittest
from unittest.mock import patch

from agentdock.cli import agentdock_main, build_parser


class AgentDockTests(unittest.TestCase):
    def test_fullscreen_default_and_opt_out(self):
        parser = build_parser("agentdock")
        self.assertTrue(parser.parse_args(["chat"]).fullscreen)
        self.assertFalse(parser.parse_args(["chat", "--no-fullscreen"]).fullscreen)
        self.assertTrue(parser.parse_args(["chat", "--fullscreen"]).fullscreen)

    def test_panel_only_option_opens_chat(self):
        with patch("sys.argv", ["agentdock", "--no-fullscreen"]), patch("agentdock.cli.main") as main:
            agentdock_main()
        main.assert_called_once_with(["chat", "--no-fullscreen"], prog="agentdock")

    def test_new_command_opens_chat_by_default(self):
        with patch("sys.argv", ["agentdock"]), patch("agentdock.cli.main") as main:
            agentdock_main()
        main.assert_called_once_with(["chat"], prog="agentdock")

    def test_new_command_accepts_agent_selection(self):
        with patch("sys.argv", ["agentdock", "--agent", "local"]), patch("agentdock.cli.main") as main:
            agentdock_main()
        main.assert_called_once_with(["chat", "--agent", "local"], prog="agentdock")

    def test_subcommands_pass_through(self):
        with patch("sys.argv", ["agentdock", "watch"]), patch("agentdock.cli.main") as main:
            agentdock_main()
        main.assert_called_once_with(["watch"], prog="agentdock")
        self.assertIn("agentdock", build_parser("agentdock").format_help())
