#!/usr/bin/env python3
"""Loopback-only, no-content usage capture proxy for Ollama / LM Studio."""
import argparse
import datetime as dt
import fcntl
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import time
import uuid

DEFAULT_EVENTS = Path.home() / "Library/Application Support/TokenBar/events.jsonl"

def append_event(event, path=DEFAULT_EVENTS):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lockfd = os.open(str(path) + ".lock", os.O_WRONLY | os.O_CREAT, 0o600)
    with os.fdopen(lockfd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as stream:
            stream.write(json.dumps(event, separators=(",", ":"), allow_nan=False) + "\n")
            stream.flush()

def count(value):
    return max(0, int(value or 0))

class UsageCapture:
    """Incrementally parses response envelopes; never retains prompt/response text."""
    def __init__(self, provider, model="unknown"):
        self.provider, self.model = provider, str(model)[:200]
        self.usage = None
        self.speed = None
        self.buffer = b""
    def envelope(self, data):
        if not isinstance(data, dict):
            return
        self.model = str(data.get("model", self.model))[:200]
        if "eval_count" in data or "prompt_eval_count" in data:
            self.usage = (count(data.get("prompt_eval_count")), count(data.get("eval_count")), 0)
            duration = data.get("eval_duration", 0)
            if isinstance(duration, (float, int)) and duration > 0:
                self.speed = self.usage[1] / (duration / 1e9)
        usage = data.get("usage")
        if isinstance(usage, dict):
            input_count = count(usage.get("prompt_tokens", usage.get("input_tokens")))
            cached = count((usage.get("prompt_tokens_details") or {}).get("cached_tokens"))
            self.usage = (input_count, count(usage.get("completion_tokens", usage.get("output_tokens"))), cached)
    def feed(self, chunk):
        self.buffer += chunk
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            self.line(line)
        if len(self.buffer) > 8 * 1024 * 1024:
            self.buffer = b""  # bounded memory, oversized envelope cannot be measured
    def line(self, line):
        line = line.strip()
        if line.startswith(b"data:"):
            line = line[5:].strip()
        try:
            self.envelope(json.loads(line))
        except (ValueError, TypeError, OverflowError):
            pass
    def finish(self):
        self.line(self.buffer)
        self.buffer = b""
        if self.usage is None:
            return None
        incoming, outgoing, cached = self.usage
        event = dict(id=str(uuid.uuid4()), provider=self.provider, model=self.model,
                     timestamp=dt.datetime.now(dt.timezone.utc).isoformat(),
                     inputTokens=incoming, outputTokens=outgoing, cachedTokens=cached)
        if self.speed is not None:
            event["tokensPerSecond"] = self.speed
        return event

class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *args):
        pass  # request URLs and contents are deliberately not logged
    def do_GET(self):
        self.forward()
    def do_POST(self):
        self.forward()
    def forward(self):
        if self.headers.get("Origin") or not self.path.startswith("/") or self.path.startswith("//"):
            self.send_error(403); return
        if self.headers.get("Transfer-Encoding"):
            self.send_error(411, "Use Content-Length"); return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 <= size <= 32 * 1024 * 1024:
                self.send_error(413); return
            body = self.rfile.read(size)
            data = json.loads(body) if body else {}
        except (ValueError, TypeError):
            self.send_error(400); return
        capture = UsageCapture(self.server.provider, data.get("model", "unknown") if isinstance(data, dict) else "unknown")
        # Ask OpenAI-compatible streaming endpoints to include their final usage frame.
        if isinstance(data, dict) and data.get("stream") and self.path.split("?", 1)[0] in ("/v1/chat/completions", "/v1/completions"):
            data["stream_options"] = {**(data.get("stream_options") or {}), "include_usage": True}
            body = json.dumps(data).encode()
        connection = http.client.HTTPConnection("127.0.0.1", self.server.upstream_port, timeout=600)
        excluded = {"host", "content-length", "connection", "transfer-encoding", "accept-encoding"}
        headers = {k: v for k, v in self.headers.items() if k.lower() not in excluded}
        headers["Content-Length"] = str(len(body))
        headers["Accept-Encoding"] = "identity"
        sent_headers = False
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in {"content-length", "transfer-encoding", "connection"}:
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            sent_headers = True
            while True:
                chunk = response.read1(65536)
                if not chunk:
                    break
                if 200 <= response.status < 300:
                    capture.feed(chunk)
                self.wfile.write(chunk)
                self.wfile.flush()
            if 200 <= response.status < 300:
                event = capture.finish()
                if event:
                    append_event(event, self.server.events)
        except (OSError, http.client.HTTPException):
            if not sent_headers:
                self.send_error(502, "Local model server unavailable")
        finally:
            self.close_connection = True
            connection.close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["ollama", "lmstudio"], required=True)
    parser.add_argument("--port", type=int)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    args = parser.parse_args()
    args.port = args.port or (11435 if args.provider == "ollama" else 1235)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ProxyHandler)
    server.provider, server.events = args.provider, args.events
    server.upstream_port = 11434 if args.provider == "ollama" else 1234
    print(f"TokenBar capture: http://127.0.0.1:{args.port} → {args.provider} loopback:{server.upstream_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
