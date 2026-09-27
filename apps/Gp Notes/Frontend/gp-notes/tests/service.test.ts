import assert from "node:assert/strict";
import { test } from "node:test";
import {
  createService,
  RequestError,
  type Configuration,
  type Provider,
} from "../lib/service";
import {
  MAX_AUDIO,
  MAX_TEXT,
  SAMPLE_NOTE,
  SAMPLE_TEXT,
  exportNote,
} from "../lib/notes";
const config: Configuration = {
  enabled: true,
  token: "test-only-workspace-token-32-characters",
  providerKey: "test-only-provider-key",
};
const good: Provider = {
  normalize: async () => structuredClone(SAMPLE_NOTE),
  transcribe: async () => SAMPLE_TEXT,
};
function request(
  body: unknown = { text: SAMPLE_TEXT },
  headers: Record<string, string> = {},
) {
  return new Request("http://localhost/api/normalize-note", {
    method: "POST",
    headers: {
      authorization: `Bearer ${config.token}`,
      "content-type": "application/json",
      ...headers,
    },
    body: JSON.stringify(body),
  });
}
function audio(
  file = new File(["synthetic audio"], "private-patient-name.webm", {
    type: "audio/webm",
  }),
) {
  const form = new FormData();
  form.append("audio", file);
  return new Request("http://localhost/api/transcribe", {
    method: "POST",
    headers: { authorization: `Bearer ${config.token}` },
    body: form,
  });
}
function service(provider = good, options = config) {
  return createService(provider, () => options);
}
test("public sample never calls a provider and cannot process arbitrary user text", async () => {
  const fail = async () => {
    throw new Error("must not call");
  };
  const response = await service(
    { normalize: fail, transcribe: fail },
    { ...config, enabled: false },
  )(request({ text: "private input" }, { "x-gp-notes-demo": "true" }), "text");
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    note: SAMPLE_NOTE,
    transcription: SAMPLE_TEXT,
    source: "sample",
  });
  assert.equal(response.headers.get("cache-control"), "no-store");
});
test("live mode fails closed unless all configuration is present", async () => {
  for (const options of [
    { ...config, enabled: false },
    { ...config, token: "short" },
    { ...config, providerKey: "" },
  ])
    assert.equal((await service(good, options)(request(), "text")).status, 503);
});
test("both routes require correct access token before reading input", async () => {
  for (const kind of ["text", "audio"] as const)
    for (const authorization of [
      "",
      "Bearer invalid",
      `Bearer ${"x".repeat(config.token.length)}`,
    ])
      assert.equal(
        (await service()(request({}, { authorization }), kind)).status,
        401,
      );
});
test("cross-origin requests are rejected, including samples", async () => {
  assert.equal(
    (
      await service()(
        request(
          {},
          { origin: "https://attacker.example", "x-gp-notes-demo": "true" },
        ),
        "text",
      )
    ).status,
    403,
  );
});
test("text validation rejects malformed, missing, blank, oversized and wrong content type", async () => {
  for (const body of [
    null,
    {},
    { text: 42 },
    { text: "   " },
    { text: "x".repeat(MAX_TEXT + 1) },
  ])
    assert.equal((await service()(request(body), "text")).status, 400);
  assert.equal(
    (await service()(request({}, { "content-type": "text/plain" }), "text"))
      .status,
    415,
  );
  const invalid = new Request("http://localhost/api/normalize-note", {
    method: "POST",
    headers: {
      authorization: `Bearer ${config.token}`,
      "content-type": "application/json",
    },
    body: "{",
  });
  assert.equal((await service()(invalid, "text")).status, 400);
});
test("streamed payload limits are enforced without Content-Length", async () => {
  assert.equal(
    (
      await service()(
        request({ text: "x".repeat(MAX_TEXT * 4 + 1024) }),
        "text",
      )
    ).status,
    413,
  );
});
test("valid text produces a validated draft and trims input", async () => {
  let seen = "";
  const response = await service({
    ...good,
    normalize: async (text) => {
      seen = text;
      return SAMPLE_NOTE;
    },
  })(request({ text: "  Synthetic consultation  " }), "text");
  assert.equal(response.status, 200);
  assert.equal(seen, "Synthetic consultation");
  assert.equal((await response.json()).source, "live");
});
test("audio preserves format, removes identifying filename and normalizes transcript", async () => {
  let filename = "";
  let format = "";
  const response = await service({
    ...good,
    transcribe: async (file) => {
      filename = file.name;
      format = file.type;
      return SAMPLE_TEXT;
    },
  })(
    audio(new File(["audio"], "patient-name.m4a", { type: "audio/mp4" })),
    "audio",
  );
  assert.equal(response.status, 200);
  assert.equal(filename, "recording.mp4");
  assert.equal(format, "audio/mp4");
});
test("audio rejects empty files, unsupported formats and files larger than 10MB", async () => {
  for (const [file, status] of [
    [new File([], "empty.webm", { type: "audio/webm" }), 400],
    [new File(["text"], "fake.webm", { type: "text/plain" }), 415],
    [new File(["text"], "fake.webm", { type: "constructor" }), 415],
    [
      new File([new Uint8Array(MAX_AUDIO + 1)], "large.webm", {
        type: "audio/webm",
      }),
      413,
    ],
  ] as const)
    assert.equal((await service()(audio(file), "audio")).status, status);
});
test("upstream errors do not leak credentials or content", async () => {
  const response = await service({
    ...good,
    normalize: async () => {
      throw new Error("SECRET_PROVIDER_KEY and private consultation");
    },
  })(request(), "text");
  assert.equal(response.status, 502);
  assert.doesNotMatch(await response.text(), /SECRET|private consultation/);
});
test("invalid generated structures are rejected", async () => {
  const response = await service({
    ...good,
    normalize: async () =>
      ({ ...SAMPLE_NOTE, plan: 42 }) as unknown as typeof SAMPLE_NOTE,
  })(request(), "text");
  assert.equal(response.status, 502);
});
test("non-clinical input and refusals preserve actionable errors", async () => {
  const response = await service({
    ...good,
    normalize: async () => {
      throw new RequestError(422, "No clinical documentation was identified.");
    },
  })(request(), "text");
  assert.equal(response.status, 422);
});
test("both routes share request budget; budget expires after one minute", async () => {
  let now = 1000;
  const handle = createService(
    good,
    () => config,
    () => now,
  );
  for (let i = 0; i < 10; i++)
    assert.equal((await handle(request(), "text")).status, 200);
  const limited = await handle(audio(), "audio");
  assert.equal(limited.status, 429);
  assert.equal(limited.headers.get("retry-after"), "60");
  now += 60_000;
  assert.equal((await handle(request(), "text")).status, 200);
});
test("concurrency is bounded and failed requests release their slots", async () => {
  let finish: (() => void) | undefined;
  const waiting = new Promise<void>((resolve) => {
    finish = resolve;
  });
  const handle = service({
    ...good,
    normalize: async () => {
      await waiting;
      throw new Error("upstream");
    },
  });
  const a = handle(request(), "text");
  const b = handle(request(), "text");
  assert.equal((await handle(request(), "text")).status, 429);
  finish!();
  await Promise.all([a, b]);
  assert.equal((await handle(request(), "text")).status, 502);
});
test("request cancellation reaches provider and returns a sanitized timeout", async () => {
  const controller = new AbortController();
  const req = new Request(request(), { signal: controller.signal });
  const response = service({
    ...good,
    normalize: async (_text, signal) => {
      controller.abort();
      signal.throwIfAborted();
      return SAMPLE_NOTE;
    },
  })(req, "text");
  assert.equal((await response).status, 504);
});
test("export includes provenance, edits and source", () => {
  const exported = exportNote({
    note: { ...SAMPLE_NOTE, plan: "Manually corrected." },
    transcription: SAMPLE_TEXT,
    source: "sample",
  });
  assert.match(exported, /SYNTHETIC SAMPLE/);
  assert.match(exported, /Manually corrected/);
  assert.match(exported, /Source transcript/);
});
test("same-origin browser requests use the public Host rather than an internal Next URL", async () => {
  assert.equal(
    (
      await service()(
        request(
          {},
          {
            host: "127.0.0.1",
            origin: "http://127.0.0.1",
            "x-gp-notes-demo": "true",
          },
        ),
        "text",
      )
    ).status,
    200,
  );
});
