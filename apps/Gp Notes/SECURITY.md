# Security and data boundaries

Gp Notes is a synthetic-data documentation experiment, not a product validated for
patient care. Publishing its source does not establish clinical, privacy or
regulatory readiness. Do not use actual patient information.

## Data handling

Sample mode returns a bundled fixture without provider requests. Live mode sends
audio to OpenAI for transcription and text for note generation. The provider key
stays server-side. The workspace token is held in browser memory and sent in an
Authorization header.

The app does not write consultation content to files, databases, browser storage
or logs. Refresh or Clear session discards app state. The old prototype's three
localStorage keys are removed on mount. This is not guaranteed secure memory
erasure. Clipboard contents and downloaded files persist outside the app.
Browser extensions, hosting infrastructure, operating systems and the provider
have separate data handling. Disabling response storage does not guarantee zero
provider retention.

There is no end-to-end encryption feature: the server and provider process
plaintext. Use HTTPS for transport.

## Controls

- Live processing requires explicit opt-in, a provider key and a workspace token
  of at least 32 characters. No bundled token grants access.
- Authentication precedes input parsing/provider calls, with timing-safe token
  comparison for equal-length values and browser origin checks.
- Streamed bodies have size bounds even without Content-Length; text/audio have
  separate limits and accepted MIME types.
- Both routes share a per-process budget of 10 requests/minute and two active
  requests. Invalid authenticated requests also consume budget.
- Provider retries are disabled; processing has a 90-second cancellation deadline.
  Cancellation may not prevent charges for work already submitted.
- Strict output schema plus runtime validation; refusals, incomplete output and
  malformed responses are rejected.
- No-store API responses and sanitized errors. Headers prohibit embedding and
  sniffing and disable camera/geolocation access.

## Limitations

One shared token is not multi-user authentication. Limits reset on restart and
are not coordinated across machines. MIME labels are client declarations; the
provider still must decode the media. Slow uploads and unauthenticated traffic
need ingress limits/timeouts. Restrict live deployments and add appropriate
identity, distributed quotas and infrastructure logging controls before expanding use.

Models can omit, invent or misattribute information despite prompts and schemas.
Review checkboxes do not establish medical safety. Recording and transcription
vary with codecs, browsers, silence, accents and overlapping speech. Medical
quality, regulatory suitability and accessibility have not been independently
audited. Tests check software behavior, not clinical correctness.

## Reporting

Report minimal synthetic reproductions to the repository owner. Never include
credentials, patient information, transcripts or recordings in public issues.
Revoke exposed credentials at their issuing service and replace local values.
