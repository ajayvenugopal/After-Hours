import { timingSafeEqual } from "node:crypto";
import {
  MAX_AUDIO,
  MAX_TEXT,
  SAMPLE_NOTE,
  SAMPLE_TEXT,
  isNote,
  type Note,
} from "./notes";

export class RequestError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export type Provider = {
  normalize: (text: string, signal: AbortSignal) => Promise<Note>;
  transcribe: (file: File, signal: AbortSignal) => Promise<string>;
};
export type Configuration = {
  enabled: boolean;
  token: string;
  providerKey: string;
};
export function configuration(): Configuration {
  return {
    enabled: process.env.GP_NOTES_LIVE_ENABLED === "true",
    token: process.env.GP_NOTES_ACCESS_TOKEN || "",
    providerKey: process.env.OPENAI_API_KEY || "",
  };
}
export function liveReady(config: Configuration): boolean {
  return config.enabled && config.token.length >= 32 && !!config.providerKey;
}
function json(value: unknown, status = 200) {
  return Response.json(value, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      ...(status === 429 ? { "Retry-After": "60" } : {}),
    },
  });
}
async function readBounded(
  request: Request,
  maximum: number,
): Promise<Uint8Array> {
  const length = request.headers.get("content-length");
  if (length && Number(length) > maximum)
    throw new RequestError(413, "Input exceeds the size limit.");
  const reader = request.body?.getReader();
  if (!reader) throw new RequestError(400, "Request body is required.");
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maximum) {
        await reader.cancel();
        throw new RequestError(413, "Input exceeds the size limit.");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}
const audioTypes: Record<string, string> = {
  "audio/webm": "webm",
  "video/webm": "webm",
  "audio/mp4": "mp4",
  "video/mp4": "mp4",
  "audio/mpeg": "mp3",
  "audio/mp3": "mp3",
  "audio/wav": "wav",
  "audio/x-wav": "wav",
  "audio/x-m4a": "m4a",
};

// A shared, bounded process-wide budget for both live routes; no client IP trust.
export type Budget = { starts: number[]; active: number };
export function createService(
  provider: Provider,
  getConfig = configuration,
  now = Date.now,
  budget: Budget = { starts: [], active: 0 },
) {
  function authorize(request: Request) {
    const config = getConfig();
    if (!liveReady(config))
      throw new RequestError(
        503,
        "Live mode is not configured. Try the sample consultation.",
      );
    const authorization = request.headers.get("authorization") || "";
    const supplied = Buffer.from(
      authorization.startsWith("Bearer ") ? authorization.slice(7) : "",
    );
    const expected = Buffer.from(config.token);
    if (
      supplied.length !== expected.length ||
      !timingSafeEqual(supplied, expected)
    )
      throw new RequestError(401, "Enter a valid workspace access token.");
    budget.starts = budget.starts.filter((time) => now() - time < 60_000);
    if (budget.starts.length >= 10 || budget.active >= 2)
      throw new RequestError(
        429,
        "Workspace limit reached. Wait a minute and try again.",
      );
    budget.starts.push(now());
    budget.active++;
  }
  return async function handle(
    request: Request,
    kind: "text" | "audio",
  ): Promise<Response> {
    let reserved = false;
    try {
      const origin = request.headers.get("origin");
      const requestUrl = new URL(request.url);
      // Next.js may use an internal hostname in request.url. Host is the
      // browser-facing authority; an explicit origin supports reverse proxies.
      const expectedOrigin =
        process.env.GP_NOTES_ORIGIN ||
        `${requestUrl.protocol}//${request.headers.get("host") || requestUrl.host}`;
      if (origin && origin !== expectedOrigin)
        throw new RequestError(403, "Cross-origin requests are not allowed.");
      const contentType = request.headers.get("content-type") || "";
      // Only a fixed fixture is publicly available. No arbitrary demo input is processed.
      if (
        kind === "text" &&
        request.headers.get("x-gp-notes-demo") === "true"
      ) {
        return json({
          note: SAMPLE_NOTE,
          transcription: SAMPLE_TEXT,
          source: "sample",
        });
      }
      authorize(request);
      reserved = true;
      const signal = AbortSignal.any([
        request.signal,
        AbortSignal.timeout(90_000),
      ]);
      let text: string;
      if (kind === "text") {
        if (!contentType.startsWith("application/json"))
          throw new RequestError(415, "Send JSON with a text field.");
        const raw = await readBounded(request, MAX_TEXT * 4 + 1024);
        let body;
        try {
          body = JSON.parse(new TextDecoder().decode(raw));
        } catch {
          throw new RequestError(400, "Invalid JSON body.");
        }
        if (!body || typeof body.text !== "string")
          throw new RequestError(400, "A text field is required.");
        text = body.text.trim();
      } else {
        if (!contentType.startsWith("multipart/form-data"))
          throw new RequestError(415, "Send an audio file as form data.");
        const raw = await readBounded(request, MAX_AUDIO + 65_536);
        let form;
        try {
          form = await new Response(raw as BodyInit, {
            headers: { "Content-Type": contentType },
          }).formData();
        } catch {
          throw new RequestError(400, "Invalid audio upload.");
        }
        const file = form.get("audio");
        if (!(file instanceof File) || !file.size)
          throw new RequestError(400, "A non-empty audio file is required.");
        if (file.size > MAX_AUDIO)
          throw new RequestError(413, "Audio must be 10 MB or smaller.");
        const type = file.type.split(";")[0].toLowerCase();
        if (!Object.hasOwn(audioTypes, type))
          throw new RequestError(415, "Use WebM, MP4/M4A, MP3, or WAV audio.");
        // Do not send user-supplied filenames to the provider.
        text = (
          await provider.transcribe(
            new File([file], `recording.${audioTypes[type]}`, { type }),
            signal,
          )
        ).trim();
      }
      if (!text || text.length > MAX_TEXT)
        throw new RequestError(
          400,
          `Input must contain 1–${MAX_TEXT.toLocaleString("en")} characters.`,
        );
      const note = await provider.normalize(text, signal);
      if (!isNote(note))
        throw new RequestError(
          502,
          "The provider returned an invalid draft. Try again.",
        );
      return json({ note, transcription: text, source: "live" });
    } catch (error) {
      if (error instanceof RequestError)
        return json({ error: error.message }, error.status);
      // Never log request bodies, tokens, transcripts, or upstream errors.
      if (
        request.signal.aborted ||
        (error instanceof Error &&
          ["AbortError", "TimeoutError", "APIUserAbortError"].includes(
            error.name,
          ))
      ) {
        return json(
          {
            error: "The request was cancelled or timed out. Please try again.",
          },
          504,
        );
      }
      return json(
        {
          error:
            "The provider could not process this request. Check the server configuration or try again later.",
        },
        502,
      );
    } finally {
      if (reserved) budget.active--;
    }
  };
}
