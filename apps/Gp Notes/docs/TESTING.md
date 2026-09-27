# Verification and evaluation

## Automated software checks

From `Frontend/gp-notes/`:

```bash
npm ci
npm run check
npx playwright install chromium
npm run test:e2e
npm audit
```

The unit/service suite has **20 tests** covering fixed demo isolation, live-mode
configuration, authentication on both routes, browser origins, malformed/oversized
inputs, MIME validation, filename sanitization, output validation, provider refusals,
truncated completions, sanitized failures, shared rate/concurrency limits,
cancellation and export provenance.

The browser suite runs **seven scenarios in desktop and mobile Chromium** (14
tests): sample → review → edit → export → clear; live token/consent controls and real
server authentication rejection; mocked live draft/source edits; cancellation;
refresh and legacy-storage cleanup; mocked audio upload; simulated microphone
resource cleanup. The server uses a deliberately fake provider key. Audio and
successful live responses are mocked, so these tests cannot consume provider credit.

Screenshots from the sample workflow are saved under ignored `test-results/`.
`docs/workspace.png` is a reviewed desktop screenshot of the public demo.
The root GitHub Actions workflow runs lint, type checks, unit tests, production
build, browser tests and a dependency audit for this project.

## Publication-preparation results — 2026-09-27

- Lint and TypeScript: passed.
- Service/provider regression tests: 20 passed.
- Desktop/mobile Chromium workflows: 14 passed.
- Production build: passed.
- Dependency audit: zero known vulnerabilities at verification time.
- Desktop and mobile screenshots: visually reviewed.
- Publishable source scan: no provider-key or private-key patterns found; existing
  local env files, certificates, dependencies and the legacy backup remain ignored.

## Manual checks before expanding live use

Use only synthetic content and an explicitly configured provider account:

1. Generate a note from a short synthetic text. Compare every statement with its
   source; missing examination, medication or diagnosis details must remain absent.
2. Record in each browser you intend to support. Check permission refusal, silence,
   recording completion, the three-minute stop, cancellation and microphone release.
3. Try supported audio formats, empty uploads, files near 10 MB and text near 20,000
   characters. Check that errors remain useful without exposing source text or keys.
4. Verify clipboard and downloads, source edits invalidating the previous draft,
   review resetting after edits, refresh clearing state and narrow-screen layout.
5. Verify your host's body limits, public-origin setting, timeouts and TLS. Never
   enable a paid provider on an unrestricted public instance with a shared token.

## Model-quality evaluation remains outstanding

Software tests do not validate clinical quality. Before considering real clinical
use, independently assess synthetic cases containing negation, uncertain diagnoses,
ambiguous abbreviations, contradictions, missing information, explicit medication
quantities and prompt-injection attempts. Measure unsupported claims, omissions,
numeric changes and attribution errors against an expert-reviewed reference set.
Include varied accents, overlapping speakers and silence for audio evaluation.

No live provider calls, physical-microphone trials or clinical evaluation were
performed during publication preparation. No claim of patient-data readiness,
regulatory compliance or medical accuracy is made.
