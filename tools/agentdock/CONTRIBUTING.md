# Contributing to AgentDock

AgentDock is an early-stage Python terminal application. Keep changes focused and
include regression tests for changed behavior. Python 3.9 or newer is required;
macOS and Linux are the intended development environments.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m unittest discover -s tests -v
```

Tests mock provider invocations; do not call paid providers or download local
models in automated tests. Use temporary directories for filesystem tests.
Never include real tokens, chat histories or repository source from private projects.

## Before submitting

- Run the complete test suite and the release archive check below.
- Update README instructions when commands or behavior change.
- Preserve user edits and state. No automatic commits, resets, pushes or PRs.
- Keep planning, implementation and review in separate provider invocations.
- Preserve plain output for redirected streams and `NO_COLOR` users.

## Build and inspect a release

```bash
python -m pip install build twine
python -m build
python scripts/check_release.py
python -m twine check dist/*
```

`check_release.py` checks the wheel and source archive for required files and private/generated artifacts. It is not a complete secret scanner.
Inspect the actual files you intend to publish as well.

Before publishing, verify the MIT license is included, set the release version, read
[SECURITY.md](SECURITY.md), and update [CHANGELOG.md](CHANGELOG.md). Confirm that the
distribution name is available in your target registry; local installation does
not reserve it. Do not upload this working directory as an unfiltered ZIP.

This project does not automatically publish packages or create releases.
