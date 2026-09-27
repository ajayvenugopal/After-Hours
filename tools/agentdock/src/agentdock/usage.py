"""Read provider-reported usage, never infer tokens from response length."""
import json
import re


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
