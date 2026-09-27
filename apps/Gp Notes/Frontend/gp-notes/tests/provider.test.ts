import assert from "node:assert/strict";
import { test } from "node:test";
import OpenAI from "openai";
import { createProvider } from "../lib/provider";
import { SAMPLE_NOTE, SAMPLE_TEXT } from "../lib/notes";
function provider(
  message: Record<string, unknown>,
  finish = "stop",
  inspect?: (body: Record<string, unknown>) => void,
) {
  return createProvider(
    () =>
      new OpenAI({
        apiKey: "synthetic-test-key",
        maxRetries: 0,
        fetch: async (_url, init) => {
          inspect?.(JSON.parse(String(init?.body)));
          return Response.json({
            choices: [{ finish_reason: finish, message }],
          });
        },
      }),
  );
}
test("provider sends strict extraction schema, disables response storage and validates result", async () => {
  let sent: Record<string, unknown> = {};
  const result = await provider(
    { content: JSON.stringify({ isMedical: true, ...SAMPLE_NOTE }) },
    "stop",
    (body) => {
      sent = body;
    },
  ).normalize(SAMPLE_TEXT, new AbortController().signal);
  assert.deepEqual(result, SAMPLE_NOTE);
  assert.equal(sent.store, false);
  const format = sent.response_format as {
    json_schema: { strict: boolean; schema: { additionalProperties: boolean } };
  };
  assert.equal(format.json_schema.strict, true);
  assert.equal(format.json_schema.schema.additionalProperties, false);
  assert.match(JSON.stringify(sent.messages), /Do not invent diagnoses/);
});
test("provider rejects refusals, truncated completions, malformed JSON and invalid schema", async () => {
  for (const [message, finish] of [
    [{ refusal: "refused" }, "stop"],
    [
      { content: JSON.stringify({ isMedical: true, ...SAMPLE_NOTE }) },
      "length",
    ],
    [{ content: "not json" }, "stop"],
    [
      {
        content: JSON.stringify({ isMedical: true, subjective: "incomplete" }),
      },
      "stop",
    ],
  ] as const)
    await assert.rejects(
      provider(message, finish).normalize(
        SAMPLE_TEXT,
        new AbortController().signal,
      ),
    );
});
test("provider rejects non-clinical input without returning an invented note", async () => {
  await assert.rejects(
    provider({
      content: JSON.stringify({ isMedical: false, ...SAMPLE_NOTE }),
    }).normalize("shopping list", new AbortController().signal),
    /No clinical documentation/,
  );
});
