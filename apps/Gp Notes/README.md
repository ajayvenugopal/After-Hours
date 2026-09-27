# Gp Notes

**From conversation to a considered draft.**

A documentation lab for turning synthetic consultation notes into editable SOAP
drafts. Keep the source beside the draft, correct the wording, and review before
copying or downloading. Part of [Afterhours](../../README.md).

**Open-source demo / experimental live mode.** This is not a clinical record system,
diagnostic tool, or validated medical product.

![Gp Notes workspace](docs/workspace.png)

## Try the sample

Requires Node.js 22.18+ and npm. From the Afterhours checkout:

```bash
cd "apps/Gp Notes/Frontend/gp-notes"
npm ci
npm run dev
```

Open http://localhost:3000 and choose **Explore sample draft**. No credentials or
paid request is needed. The demo returns a fixed, labeled synthetic example; it
does not pretend to generate an AI response to arbitrary text.

Compare the source with Subjective, Objective, Assessment and Plan. Edit any
section, check the review box, then copy or download a text file. Editing resets
review. Clear session discards the inputs, draft and workspace token.

## Features

- Responsive source-and-draft workspace with editable SOAP sections.
- Fixed synthetic demo with no provider calls.
- Opt-in live text processing, up to 20,000 characters.
- Live recording up to three minutes; uploads up to 10 MB in WebM, MP4/M4A, MP3 or WAV.
- Review-before-export, with source and sample/live provenance in the exported text.
- Session-only application state: no database, analytics, consultation logging or
  new browser-storage persistence.

## Enable live mode

From the application directory, copy `.env.example` to `.env.local` and generate
an access token with `openssl rand -hex 32`. Configure:

```dotenv
GP_NOTES_LIVE_ENABLED=true
OPENAI_API_KEY=your-provider-key
GP_NOTES_ACCESS_TOKEN=your-own-random-token-at-least-32-characters
OPENAI_NOTE_MODEL=gpt-4o-mini
OPENAI_TRANSCRIPTION_MODEL=whisper-1
```

Restart the app, select **Live workspace**, enter the workspace token (not your
OpenAI API key), and acknowledge the synthetic-data/provider-processing notice.
Provider calls may incur charges. Never prefix credentials with `NEXT_PUBLIC_`.
Local provider credentials alone do not enable live mode.

Recording requires microphone permission and localhost or HTTPS. Use
`npm run dev:https` for local HTTPS, or upload audio when recording is unavailable.

The note model must support strict JSON Schema through Chat Completions. The audio
model must support file transcription returning `text`. Account access may vary.
Provider interface references: [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
and [speech-to-text](https://developers.openai.com/api/docs/guides/speech-to-text).

## Architecture

```text
Browser sample request → fixed synthetic draft
Browser text/audio + workspace token → Next.js API
  → configuration/authentication/origin checks
  → size bounds and shared process request limits
  → transcription for audio → structured note generation → runtime validation
Browser memory → compare source → edit → review → copy or download
```

The model is instructed to preserve negations, uncertainty, quantities and
attribution; missing sections remain “Not documented.” Review notes flag source
ambiguities, not treatment suggestions. Schema validation checks structure, not
clinical correctness.

## Verification

From `Frontend/gp-notes/`:

```bash
npm run check
npx playwright install chromium
npm run test:e2e
npm audit
```

`check` runs lint, types, service/provider tests and a production build. Browser
tests launch that build on port 3107 and use synthetic fixtures and mocked live
responses. No paid provider requests are made by tests. See [testing notes](docs/TESTING.md)
for coverage and the outstanding live/model evaluation.

## Hosting

For a public showcase, leave live mode disabled. Use a Node-capable Next.js host
with project root `apps/Gp Notes/Frontend/gp-notes`, install with `npm ci`, build
with `npm run build`, and start with `npm start`. There is no separate backend or
static-export configuration.

Live mode is for restricted synthetic-data experiments. Its one shared workspace
token and per-process limits (10 requests/minute, two active requests) are not
multi-user authentication or distributed abuse controls. Use HTTPS, access
restrictions, ingress body limits/timeouts, provider spend limits, and a shared
limiter if running multiple workers. Hosts may impose lower upload or timeout limits.

Browser Origin must match the public Host/protocol. Behind a reverse proxy, set
`GP_NOTES_ORIGIN=https://your-host.example` to the exact public origin, without a
trailing slash. Read [SECURITY.md](SECURITY.md) before enabling live mode.

## Layout

```text
Gp Notes/
├── README.md, SECURITY.md, CHANGELOG.md
├── docs/
└── Frontend/gp-notes/
    ├── app/             # workspace and thin API route adapters
    ├── lib/notes.ts     # types, fixture and export format
    ├── lib/service.ts   # authentication, validation and request limits
    ├── lib/provider.ts  # isolated OpenAI adapter
    ├── tests/           # service/provider regression tests
    └── e2e/             # desktop/mobile browser tests
```

Old `/login` and `/results` links redirect to the workspace. The superseded Express
spike remains only in the maintainer's ignored `.legacy-prototype/` backup.

## License

[MIT](../../LICENSE). Dependencies retain their own licenses and providers their
own terms. Keep credentials and consultation content out of commits and issues.
