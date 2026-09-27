# Verification and evaluation

From `Frontend/gp-notes/`:

```bash
npm ci
npm run check
npx playwright install chromium
npm run test:e2e
npm audit
```

The 20 service/provider tests cover demo isolation, live opt-in, authentication,
origins, malformed/oversized input, audio formats, filename sanitization, output
validation, refusals, truncated responses, sanitized errors, request/concurrency
limits, cancellation and export provenance.

Seven browser scenarios run in desktop and mobile Chromium (14 tests): sample
review/edit/export/clear; token/consent and real server authentication rejection;
mocked live draft/source edits; cancellation; refresh and legacy-storage cleanup;
mocked audio upload; simulated microphone cleanup. A fake provider key and mocked
live responses prevent paid calls. Screenshots are written to ignored
`test-results/`; the reviewed README preview lives at `docs/workspace.png`.

The repository CI runs lint, types, tests, production build, browser tests and a
dependency audit. Automated success does not establish medical accuracy.

## Manual verification before expanding live use

Use synthetic data and an explicitly configured provider account. Compare output
against source for omitted facts, invented findings, changed numbers, uncertainty,
negation and attribution. Check microphone permission denial, silence, cancellation,
the three-minute stop and release of microphone resources on supported browsers.
Verify upload limits, supported codecs, clipboard/download behavior and state reset.
Check the deployment's TLS, public origin, body limits, timeouts and spend limits.

## Model evaluation remains outstanding

An independent expert-reviewed synthetic reference set should cover ambiguous
abbreviations, contradictory statements, missing information, medication quantities,
prompt injection, accents, overlapping speakers and silence. Measure unsupported
claims, omissions, numeric changes and attribution errors.

No live provider calls, physical-microphone trials or clinical evaluation were
performed during publication preparation. Software tests use mocks and fixtures.
No patient-data readiness or regulatory compliance is claimed.
