import importlib.util
import json
from pathlib import Path
import unittest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
capture = load("capture-usage")
gemini = load("gemini-telemetry")

def metrics(values, end=2000000000, start=1000000000, temporality=2):
    return {"resourceMetrics": [{"resource": {"attributes": [{"key": "session.id", "value": {"stringValue": "test-session"}}]}, "scopeMetrics": [{"metrics": [{"name": "gemini_cli.token.usage", "sum": {"aggregationTemporality": temporality, "dataPoints": [{"asInt": str(value), "timeUnixNano": str(end), "startTimeUnixNano": str(start), "attributes": [{"key": "model", "value": {"stringValue": "gemini-test"}}, {"key": "type", "value": {"stringValue": kind}}]} for kind, value in values.items()]}}]}]}]}

class IntegrationTests(unittest.TestCase):
    def test_ollama_split_stream_final_usage_and_speed(self):
        parser = capture.UsageCapture("ollama")
        payload = b'{"model":"local","response":"PRIVATE"}\n{"done":true,"prompt_eval_count":100,"eval_count":20,"eval_duration":2000000000}\n'
        for offset in range(0, len(payload), 7):
            parser.feed(payload[offset:offset + 7])
        event = parser.finish()
        self.assertEqual(event["inputTokens"], 100)
        self.assertEqual(event["tokensPerSecond"], 10)
        self.assertNotIn("PRIVATE", json.dumps(event))
    def test_sse_cache_is_subset_and_final_usage(self):
        parser = capture.UsageCapture("lmstudio", "test")
        parser.feed(b'data: {"choices":[{"delta":{"content":"SECRET"}}]}\n\ndata: {"usage":{"prompt_tokens":100,"completion_tokens":30,"prompt_tokens_details":{"cached_tokens":40}}}\n\ndata: [DONE]\n')
        event = parser.finish()
        self.assertEqual((event["inputTokens"], event["outputTokens"], event["cachedTokens"]), (100, 30, 40))
        self.assertNotIn("SECRET", json.dumps(event))
    def test_missing_usage_is_not_fabricated(self):
        parser = capture.UsageCapture("ollama")
        parser.feed(b'{"done":true}')
        self.assertIsNone(parser.finish())
    def test_cumulative_metrics_retry_increment_and_restart(self):
        collector = gemini.MetricCollector()
        first = collector.collect(metrics({"input": 100, "cache": 40, "output": 20, "thought": 5}))[0]
        self.assertEqual((first["inputTokens"], first["cachedTokens"], first["outputTokens"]), (100, 40, 25))
        self.assertEqual(collector.collect(metrics({"input": 100, "cache": 40, "output": 20, "thought": 5})), [])
        restarted = gemini.MetricCollector(json.loads(json.dumps(collector.state)))
        later = restarted.collect(metrics({"input": 130, "cache": 50, "output": 25, "thought": 5}, end=3000000000))[0]
        self.assertEqual((later["inputTokens"], later["cachedTokens"], later["outputTokens"]), (30, 10, 5))
        self.assertNotIn("test-session", json.dumps(collector.state))
    def test_delta_metrics_and_new_counter_epoch(self):
        collector = gemini.MetricCollector()
        self.assertEqual(collector.collect(metrics({"input": 10}, temporality=1))[0]["inputTokens"], 10)
        self.assertEqual(collector.collect(metrics({"input": 7}, end=3000000000, temporality=1))[0]["inputTokens"], 7)
        self.assertEqual(collector.collect(metrics({"input": 3}, end=4000000000, start=3500000000))[0]["inputTokens"], 3)
    def test_gemini_api_usage_only(self):
        event = gemini.api_response_event({"responseId": "one", "modelVersion": "gemini", "candidates": ["PRIVATE"], "usageMetadata": {"promptTokenCount": 100, "cachedContentTokenCount": 40, "candidatesTokenCount": 10, "thoughtsTokenCount": 7}})
        self.assertEqual((event["inputTokens"], event["outputTokens"], event["cachedTokens"]), (100, 17, 40))
        self.assertNotIn("PRIVATE", json.dumps(event))

if __name__ == "__main__":
    unittest.main()
