"""Read provider-reported response tokens and live Codex account quotas."""
import json
import math
import os
import re
import selectors
import shutil
import subprocess
import time
from datetime import datetime


def token_label(total, approximate=False, finished=False):
    if total is None:
        return "tokens unavailable" if finished else "tokens pending"
    return f"{'≈' if approximate else ''}{total:,} tokens"


class TokenUsage:
    def __init__(self, provider, update):
        self.provider = provider
        self.update = update
        self.pending = ""
        self.total = None
        self.approximate = False
        self.codex_count_next = False
        self.ollama_counts = {}

    def feed(self, text):
        self.pending += text
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            self.line(line)

    def finish(self):
        if self.pending:
            self.line(self.pending)
        self.pending = ""

    def line(self, line):
        line = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line).strip()
        total = None
        if self.provider == "codex":
            if self.codex_count_next and re.fullmatch(r"[\d,]+", line):
                total = int(line.replace(",", ""))
            self.codex_count_next = line == "tokens used"
        elif self.provider == "aider":
            match = re.match(r"^Tokens: ([\d,.]+[kKmM]?) sent, ([\d,.]+[kKmM]?) received\.", line)
            if match:
                values = match.groups()
                self.approximate |= any(value[-1].lower() in "km" for value in values)
                def count(value):
                    scale = {"k": 1000, "m": 1000000}.get(value[-1].lower(), 1)
                    return round(float((value[:-1] if scale != 1 else value).replace(",", "")) * scale)
                total = (self.total or 0) + sum(count(value) for value in values)
        elif self.provider == "ollama":
            match = re.fullmatch(r"(prompt eval count|eval count):\s+(\d+) token\(s\)", line)
            if match:
                self.ollama_counts[match[1]] = int(match[2])
                if len(self.ollama_counts) == 2:
                    total = sum(self.ollama_counts.values())
        elif self.provider == "claude":
            try:
                event = json.loads(line)
            except ValueError:
                return
            if not isinstance(event, dict) or event.get("type") != "result":
                return
            usage = event.get("usage")
            fields = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
            if isinstance(usage, dict) and all(type(usage.get(key)) is int and usage[key] >= 0 for key in fields[:2]):
                counts = [usage.get(key, 0) for key in fields]
                if all(type(value) is int and value >= 0 for value in counts):
                    total = sum(counts)
            # Per-model totals also include Claude's nested subagent requests.
            models = event.get("modelUsage")
            if isinstance(models, dict) and models:
                fields = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")
                counts = [item.get(key, 0) for item in models.values() if isinstance(item, dict) for key in fields]
                if len(counts) == len(models) * len(fields) and all(
                        isinstance(item, dict) and all(key in item for key in fields[:2])
                        for item in models.values()) and all(type(value) is int and value >= 0 for value in counts):
                    total = sum(counts)
        if total is not None:
            self.total = total
            self.update(total, self.approximate)




class UsageError(Exception):
    pass


def read_codex_usage(repo, env, timeout=15):
    if not shutil.which('codex'):
        raise UsageError('Codex is not installed or not on PATH. Install Codex and run codex login.')
    process = subprocess.Popen(['codex', 'app-server'], cwd=repo, env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + timeout
    pending = b''
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)

            def send(message):
                process.stdin.write((json.dumps(message) + '\n').encode())
                process.stdin.flush()

            def receive(request_id):
                nonlocal pending
                while True:
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        try:
                            message = json.loads(line)
                        except (ValueError, UnicodeError):
                            continue
                        if not isinstance(message, dict) or message.get('id') != request_id:
                            continue
                        if 'error' in message:
                            raise UsageError('Codex could not read account limits. Check codex login, your connection, and update Codex if needed. ChatGPT limits are unavailable for API-key-only accounts.')
                        result = message.get('result')
                        if not isinstance(result, dict):
                            raise UsageError('Codex returned an invalid usage response. Try updating Codex.')
                        return result
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise UsageError('Codex usage request timed out. Check your connection and retry /usage.')
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        raise UsageError('Codex usage service exited. Check codex login and update Codex if needed.')
                    pending += chunk
                    if len(pending) > 2_000_000:
                        raise UsageError('Codex returned an oversized usage response.')

            send({'id': 1, 'method': 'initialize', 'params': {
                'clientInfo': {'name': 'agentdock', 'title': 'AgentDock', 'version': '0.1.0'}}})
            receive(1)
            send({'method': 'initialized'})
            send({'id': 2, 'method': 'account/rateLimits/read'})
            return receive(2)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        process.stdin.close()
        process.stdout.close()


def safe_text(value):
    return ''.join(c for c in str(value) if c.isprintable())[:160]


def usage_lines(payload):
    lines = ['Codex account limits · live snapshot', 'Shared across Codex sessions; not just this AgentDock chat.', '']
    buckets = payload.get('rateLimitsByLimitId')
    if not isinstance(buckets, dict) or not buckets:
        buckets = {'codex': payload.get('rateLimits')}
    for key, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        label = safe_text(bucket.get('limitName') or bucket.get('limitId') or key)
        plan = bucket.get('planType')
        lines.append(label + (f' · {safe_text(plan)} plan' if plan else ''))
        shown = False
        for name in ('primary', 'secondary'):
            window = bucket.get(name)
            if not isinstance(window, dict):
                continue
            used = window.get('usedPercent')
            if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used):
                continue
            minutes = window.get('windowDurationMins')
            duration = name.capitalize()
            if isinstance(minutes, int) and minutes > 0:
                duration = (f'{minutes // 1440}-day' if minutes % 1440 == 0 else
                            f'{minutes // 60}-hour' if minutes % 60 == 0 else f'{minutes}-minute')
            reset = 'reset time unavailable'
            if isinstance(window.get('resetsAt'), (int, float)):
                try:
                    reset = 'resets ' + datetime.fromtimestamp(window['resetsAt']).astimezone().strftime('%d %b %H:%M %Z')
                except (ValueError, OverflowError, OSError):
                    pass
            lines.append(f'  {duration}: {max(0, 100 - used):g}% remaining · {used:g}% used · {reset}')
            shown = True
        if not shown:
            lines.append('  Usage windows unavailable; this does not mean zero usage.')
        if bucket.get('rateLimitReachedType'):
            lines.append('  Limit reached: ' + safe_text(bucket['rateLimitReachedType']).replace('_', ' '))
        if bucket.get('spendControlReached') is True:
            lines.append('  Spend control limit reached')
        credits = bucket.get('credits')
        if isinstance(credits, dict):
            if credits.get('unlimited'):
                lines.append('  Credits: unlimited')
            elif credits.get('balance') is not None:
                lines.append('  Credits remaining: ' + safe_text(credits['balance']))
    if payload.get('ordinaryUsageAllowed') is False:
        lines.append('Included usage is currently unavailable for this account.')
    return lines
