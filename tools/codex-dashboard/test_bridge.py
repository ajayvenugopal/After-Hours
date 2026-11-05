import unittest
from bridge import Bridge


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.b = Bridge()
        self.sent = []
        self.b.write = self.sent.append

    def request(self, method, params=None):
        self.b.requests["7"] = {"id": 7, "method": method, "params": params or {}}

    def test_approve_once(self):
        self.request("item/commandExecution/requestApproval")
        self.b.answer("7", "accept")
        self.assertEqual(self.sent, [{"id": 7, "result": {"decision": "accept"}}])
        with self.assertRaises(ValueError):
            self.b.answer("7", "accept")

    def test_decline(self):
        self.request("item/fileChange/requestApproval")
        self.b.answer("7", "decline")
        self.assertEqual(self.sent[0]["result"], {"decision": "decline"})

    def test_disallowed_decision(self):
        self.request(
            "item/commandExecution/requestApproval", {"availableDecisions": ["cancel"]}
        )
        with self.assertRaises(ValueError):
            self.b.answer("7", "accept")
        self.assertEqual(self.sent, [])

    def test_permission_scope(self):
        self.request(
            "item/permissions/requestApproval",
            {"permissions": {"network": {"enabled": True}}},
        )
        self.b.answer("7", "accept")
        self.assertEqual(
            self.sent[0]["result"],
            {"permissions": {"network": {"enabled": True}}, "scope": "turn"},
        )

    def test_questions(self):
        self.request("item/tool/requestUserInput", {"questions": [{"id": "choice"}]})
        with self.assertRaises(ValueError):
            self.b.answer("7", {})
        self.b.answer("7", {"choice": "Yes"})
        self.assertEqual(
            self.sent[0]["result"], {"answers": {"choice": {"answers": ["Yes"]}}}
        )

    def test_unsupported_never_approves(self):
        self.request("unknown")
        with self.assertRaises(ValueError):
            self.b.answer("7", "accept")
        self.assertEqual(self.sent, [])

    def test_active_steers(self):
        self.b.connect = lambda: None
        self.b.attach = lambda _: {"turns": [{"id": "turn1", "status": "inProgress"}]}
        calls = []
        self.b.call = lambda m, p: calls.append((m, p)) or {}
        self.b.reply("thread1", "hello")
        self.assertEqual(calls[0][0], "turn/steer")
        self.assertEqual(calls[0][1]["expectedTurnId"], "turn1")

    def test_idle_starts(self):
        self.b.connect = lambda: None
        self.b.attach = lambda _: {"turns": []}
        calls = []
        self.b.call = lambda m, p: calls.append((m, p)) or {}
        self.b.reply("thread1", "hello")
        self.assertEqual(calls[0][0], "turn/start")


class DiscoveryTests(unittest.TestCase):
    def test_missing_rollout_does_not_hide_valid_threads(self):
        b = Bridge()
        b.last_discovery = float("-inf")
        b.call = lambda *args: {"data": ["missing", "valid"], "nextCursor": None}
        seen = []

        def attach(identifier):
            if identifier == "missing":
                raise RuntimeError("no rollout found for thread id missing")
            seen.append(identifier)

        b.attach = attach
        b.discover()
        self.assertEqual(seen, ["valid"])


if __name__ == "__main__":
    unittest.main()
