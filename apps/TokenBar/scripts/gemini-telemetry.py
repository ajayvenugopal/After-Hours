#!/usr/bin/env python3
"""Receive loopback OTLP/HTTP JSON Gemini token metrics, without storing content."""
import argparse
import datetime as dt
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import json
import sys
import uuid
from pathlib import Path

_spec = importlib.util.spec_from_file_location("capture_usage", Path(__file__).with_name("capture-usage.py"))
_capture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_capture)

def attributes(items):
    result = {}
    for item in items or []:
        value = item.get("value", {})
        result[str(item.get("key", ""))] = next(iter(value.values()), "") if isinstance(value, dict) else value
    return result

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

class MetricCollector:
    def __init__(self, state=None):
        self.state = state if state is not None else {}
    def collect(self, payload):
        events = []
        for resource in payload.get("resourceMetrics", []):
            identity = attributes(resource.get("resource", {}).get("attributes", []))
            for scope in resource.get("scopeMetrics", []):
                for metric in scope.get("metrics", []):
                    if metric.get("name") != "gemini_cli.token.usage":
                        continue
                    total = metric.get("sum", {})
                    temporality = total.get("aggregationTemporality")
                    if temporality not in (1, 2, "AGGREGATION_TEMPORALITY_DELTA", "AGGREGATION_TEMPORALITY_CUMULATIVE"):
                        continue
                    cumulative = temporality in (2, "AGGREGATION_TEMPORALITY_CUMULATIVE")
                    for point in total.get("dataPoints", []):
                        tags = attributes(point.get("attributes", []))
                        kind = tags.get("type")
                        if kind not in ("input", "output", "thought", "cache", "tool"):
                            continue
                        try:
                            value = int(point.get("asInt", point.get("asDouble", 0)))
                            timestamp = int(point["timeUnixNano"])
                            start = str(point.get("startTimeUnixNano", "0"))
                            if value < 0 or timestamp <= 0:
                                continue
                        except (ValueError, TypeError, KeyError, OverflowError):
                            continue
                        key = digest([identity, scope.get("scope", {}), tags, start])
                        previous = self.state.get(key)
                        # Retries and older exports must never count twice.
                        if previous and timestamp <= previous["timestamp"]:
                            continue
                        delta = max(0, value - previous["value"]) if cumulative and previous else value
                        self.state[key] = {"timestamp": timestamp, "value": value}
                        if delta == 0:
                            continue
                        model = str(tags.get("model", "unknown"))[:200]
                        incoming = delta if kind in ("input", "tool") else 0
                        outgoing = delta if kind in ("output", "thought") else 0
                        # Cached prompt tokens are a subset of input, never add them to totals.
                        events.append(dict(id="gemini-" + digest([key, timestamp, value]), provider="gemini", model=model,
                                           timestamp=dt.datetime.fromtimestamp(timestamp / 1e9, dt.timezone.utc).isoformat(),
                                           inputTokens=incoming, outputTokens=outgoing, cachedTokens=delta if kind == "cache" else 0))
        grouped = {}
        for event in events:
            key = (event["model"], event["timestamp"])
            if key not in grouped:
                grouped[key] = {**event, "inputTokens": 0, "outputTokens": 0, "cachedTokens": 0, "ids": []}
            group = grouped[key]
            for field in ("inputTokens", "outputTokens", "cachedTokens"):
                group[field] += event[field]
            group["ids"].append(event["id"])
        for event in grouped.values():
            event["id"] = "gemini-" + digest(sorted(event.pop("ids")))
            event["cachedTokens"] = min(event["inputTokens"], event["cachedTokens"])
        return list(grouped.values())

def api_response_event(payload, model="unknown"):
    usage = payload.get("usageMetadata")
    if not isinstance(usage, dict):
        raise ValueError("Response has no usageMetadata")
    incoming = max(0, int(usage.get("promptTokenCount", 0)))
    outgoing = max(0, int(usage.get("candidatesTokenCount", 0))) + max(0, int(usage.get("thoughtsTokenCount", 0)))
    return dict(id="gemini-api-" + str(payload.get("responseId") or uuid.uuid4()), provider="gemini", model=str(payload.get("modelVersion") or model)[:200],
                timestamp=dt.datetime.now(dt.timezone.utc).isoformat(), inputTokens=incoming, outputTokens=outgoing,
                cachedTokens=min(incoming, max(0, int(usage.get("cachedContentTokenCount", 0)))))

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_POST(self):
        if self.headers.get("Origin"):
            self.send_error(403); return
        if self.path != "/v1/metrics":
            # Logs/traces may contain content: discard immediately, never decode/store them.
            if self.path in ("/v1/logs", "/v1/traces"):
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b"{}"); self.close_connection = True
            else:
                self.send_error(404)
            return
        if "application/json" not in self.headers.get("Content-Type", ""):
            self.send_error(415, "OTLP JSON required; configure collector otlphttp encoding json"); return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4 * 1024 * 1024:
                self.send_error(413); return
            payload = json.loads(self.rfile.read(length))
            candidate = MetricCollector(dict(self.server.collector.state))
            events = candidate.collect(payload)
            for event in events:
                _capture.append_event(event, self.server.events)
            # Persist only hashes and counter values, never metric attribute contents.
            statefile = self.server.events.with_name("gemini-counters.json")
            temporary = statefile.with_suffix(".tmp")
            temporary.write_text(json.dumps(candidate.state))
            temporary.chmod(0o600)
            temporary.replace(statefile)
            self.server.collector = candidate
        except (ValueError, TypeError, AttributeError, OSError):
            self.send_error(400, "Invalid metrics or unavailable event storage"); return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-response", action="store_true", help="Read one Gemini API JSON response from stdin, persist metadata only, then exit")
    parser.add_argument("--model", default="unknown", help="API model if response omits modelVersion")
    parser.add_argument("--port", type=int, default=4319)
    parser.add_argument("--events", type=Path, default=_capture.DEFAULT_EVENTS)
    args = parser.parse_args()
    if args.import_response:
        try:
            event = api_response_event(json.load(sys.stdin), args.model)
            _capture.append_event(event, args.events)
            print("Imported Gemini API usage metadata.")
        except (ValueError, TypeError, OSError):
            print("Unable to import Gemini response usageMetadata.", file=sys.stderr)
            sys.exit(1)
        return
    args.events.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(args.events.with_name("gemini-counters.json").read_text())
    except (OSError, ValueError):
        state = {}
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    server.events, server.collector = args.events, MetricCollector(state)
    print(f"TokenBar Gemini OTLP JSON: http://127.0.0.1:{args.port}/v1/metrics", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
