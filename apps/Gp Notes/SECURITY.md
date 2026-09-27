# Security and data boundaries

Gp Notes is a synthetic-data documentation experiment, not a product approved or
validated for patient care. Publishing the source does not establish clinical,
privacy or regulatory readiness.

## Data flow

Sample mode returns a bundled synthetic fixture and makes no provider requests.
Live mode sends audio to OpenAI for transcription, then text for note generation;
typed input goes directly to note generation. The OpenAI API key remains server-side.
The workspace token is held in browser memory and sent in an Authorization header.

The application does not write consultation data to a database, files, browser
storage or logs. Browser state disappears on refresh or Clear session. The old
prototype's three localStorage keys are removed on mount. This is not a secure
memory-erasure guarantee. Clipboard contents and downloaded files persist outside
the app. Browser extensions, operating systems, hosting infrastructure and the
provider have their own data handling. Provider retention is not controlled by this
app; disabling response storage is not a zero-retention guarantee.

There is no end-to-end encryption feature. Use HTTPS for network transport. The
server and provider process plaintext content. Do not use actual patient information.

## Implemented controls

- Live processing is disabled unless explicitly enabled with a provider key and a
  workspace access token of at least 32 characters. No bundled live credentials.
- Authentication runs before input parsing or provider requests. Token comparison
  is timing-safe for equal-length values; browser cross-origin calls are rejected.
- Streamed bodies are bounded, including requests without Content-Length. Text
  and uploaded audio have separate size limits and accepted content types.
- One process shares a 10-request/minute budget and a two-request concurrency cap
  across both live routes. Invalid authenticated requests consume budget too.
- Provider retries are disabled; requests carry cancellation and a 90-second
  processing deadline. Cancelling a request may not prevent charges already incurred.
- Generated output must match the strict schema and pass runtime validation.
  Refusals, incomplete completions and malformed responses fail closed.
- API responses use no-store. Error messages omit upstream exception details.
  Security headers disable embedding, sniffing, camera and geolocation access.

## Remaining limitations

A shared token is not multi-user authentication. Limits reset on restart and are
not coordinated between machines. MIME types are client declarations, not proof
of file contents; the transcription provider must decode/validate the media.
Request-body buffering, slow uploads and unauthenticated traffic also need ingress
limits and timeouts. Use a restricted single-instance environment for live trials;
add real authentication, distributed quotas and logging controls before broader use.

LLMs can omit, misattribute or invent content despite prompts and schemas. A review
checkbox does not establish clinical safety. Browser recording and transcription
can fail, particularly for silence, overlapping speech, accents or unsupported codecs.
Clinical quality, regulatory suitability and accessibility have not been independently
audited. Tests verify software behavior, not medical correctness.

## Reporting

Do not post credentials, recordings, transcripts or patient information in public
issues. Report a minimal synthetic reproduction to the repository owner. If a
credential is exposed, revoke it at its issuing service and replace the local value.
