# TokenBar capture integrations

These helpers run with Python 3 and write metadata to `~/Library/Application Support/TokenBar/events.jsonl`. They never persist prompts, generated text, API keys, email addresses, or conversation IDs. Model names and token counts are retained. Stop a helper with Control-C; app-launched helpers stop with the app. No helper changes provider settings automatically. These are **observed usage totals**, not account quota or reset APIs.

Commands below run from `apps/TokenBar`. In an installed app, replace `scripts/` with `/Applications/TokenBar.app/Contents/Resources/` (or your app's actual location).

## Ollama and LM Studio

Start one or both proxies:

```sh
python3 scripts/capture-usage.py --provider ollama
python3 scripts/capture-usage.py --provider lmstudio
```

| Provider | Configure your client's base URL | Actual server |
| --- | --- | --- |
| Ollama native API | `http://127.0.0.1:11435` | `127.0.0.1:11434` |
| Ollama OpenAI API | `http://127.0.0.1:11435/v1` | `127.0.0.1:11434` |
| LM Studio OpenAI API | `http://127.0.0.1:1235/v1` | `127.0.0.1:1234` |

The app's capture buttons launch these same helpers. You must point your inference client at the capture URL; simply starting a helper does not monitor requests made directly to the model server. Both proxies bind only to IPv4 loopback and forward only to their fixed local server. Browser cross-origin requests are rejected. Non-browser SDK clients are supported. Stop capture after restoring your client's original base URL.

The proxy forwards JSON and streaming NDJSON/SSE without persisting response content. Ollama final `prompt_eval_count`, `eval_count`, and `eval_duration` provide tokens and generation speed. OpenAI-compatible `usage` frames provide token counts; streaming chat/completion requests automatically request `stream_options.include_usage`. Servers must support this option. If no usage frame arrives, no fabricated record is created. Disconnects before final usage are not counted. LM Studio's own chat interface does not necessarily call this proxy. Other native LM Studio API formats, compressed requests, and chunked request bodies are not supported. Proxy metadata reads support responses up to 8 MB per envelope.

Local model costs are left unknown: electricity and hardware costs are not inferred from tokens. See [Ollama chat API](https://docs.ollama.com/api/chat) and [LM Studio OpenAI compatibility](https://lmstudio.ai/docs/developer/openai-compat/chat-completions).

## Gemini CLI telemetry

Start the receiver:

```sh
python3 scripts/gemini-telemetry.py
```

It accepts **OTLP/HTTP JSON metrics** at `http://127.0.0.1:4319/v1/metrics`. It does not decode OTLP protobuf or gRPC. For reliable Gemini CLI compatibility, use an installed OpenTelemetry Collector to convert transport formats. Save the following as `tokenbar-otel.yaml`:

```yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 127.0.0.1:4318
exporters:
  otlp_http/tokenbar:
    endpoint: http://127.0.0.1:4319
    encoding: json
    compression: none
service:
  pipelines:
    metrics:
      receivers: [otlp]
      exporters: [otlp_http/tokenbar]
```

Run your installed collector (for example, `otelcol --config tokenbar-otel.yaml`). Older collector versions call the exporter `otlphttp` rather than `otlp_http`; use the name supported by your version. TokenBar does not install the collector.

Launch Gemini in another terminal with:

```sh
GEMINI_TELEMETRY_ENABLED=true \
GEMINI_TELEMETRY_TARGET=local \
GEMINI_TELEMETRY_USE_COLLECTOR=true \
GEMINI_TELEMETRY_OTLP_PROTOCOL=http \
GEMINI_TELEMETRY_OTLP_ENDPOINT=http://127.0.0.1:4318 \
GEMINI_TELEMETRY_LOG_PROMPTS=false \
GEMINI_TELEMETRY_TRACES_ENABLED=false \
gemini
```

Only `gemini_cli.token.usage` metrics are converted. Counter deltas are stored once; duplicate and older exports are ignored. Counter state survives receiver restarts in `gemini-counters.json`, containing only hashed identities, timestamps, and counts. The first cumulative export includes usage since that CLI counter started, timestamped at export time. Session resources and counter start times distinguish resets. Output includes thought tokens; input includes tool-prompt tokens; cached tokens are a subset of input. Cache metrics must arrive in the same export/timestamp group as input to retain the cache breakdown. Logs/traces are not forwarded by this collector configuration. Quota limits and reset times are not provided by these metrics.

References: [Gemini telemetry settings and metrics](https://geminicli.com/docs/cli/telemetry/), [Gemini usage field mapping](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/telemetry/types.ts), [OpenTelemetry HTTP exporter JSON encoding](https://github.com/open-telemetry/opentelemetry-collector/blob/main/exporter/otlphttpexporter/README.md).

## Gemini API response capture

For your own API client, pass a complete non-streaming response JSON into:

```sh
python3 scripts/gemini-telemetry.py --import-response --model gemini-model-name < response.json
```

Only `usageMetadata` token counts, model version, and response ID are converted. Generated candidates are discarded. This does not call the API, require an API key, or monitor other applications. `promptTokenCount` includes cached input; output adds candidate and thought tokens. Response IDs allow TokenBar's ledger to deduplicate repeated imports. A response without an ID receives a new random ID, so import it only once. Cost and account quotas are unknown. See [Gemini GenerateContent API](https://ai.google.dev/api/generate-content#UsageMetadata).

## Validation and privacy

Run `python3 -m unittest discover -s Tests/BridgeTests -v` for streaming parser, cache arithmetic, counter retry/restart, API response sanitization, and import deduplication tests. Helpers offer `--events /path/to/test-events.jsonl` to keep integration checks out of your real history. All listeners bind to `127.0.0.1`; event writes use file locking. Request bodies exist only in memory while forwarding or parsing. These helpers do not monitor unrelated traffic or scrape provider credentials.
