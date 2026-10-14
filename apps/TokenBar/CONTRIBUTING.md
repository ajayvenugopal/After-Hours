# Contributing

Build on macOS with Swift 5.9+ and Xcode Command Line Tools. Python 3 is needed for bridge/capture tests.

```sh
swift test
python3 -m unittest discover -s Tests/BridgeTests -v
bash scripts/build.sh
```

The macOS CI workflow runs the same checks. Its first remote run still needs to succeed after the repository is published.

## Project layout

- `Sources/UsageCore/`: quota parsing, account transport, reset checks, and local history.
- `Sources/TokenBar/`: menu bar, SwiftUI views, notifications, and integration controls.
- `scripts/`: app packaging and Python bridges/capture helpers.
- `Tests/`: Swift and Python tests with synthetic data.
- `Resources/`: app metadata and icon artwork.

Keep account reads independent of history scans, preserve stale-data indicators, and stop UI timers while the panel is closed. Add a focused regression test when fixing parsing or transport failures.

## Reporting an issue

Include your macOS version, provider, what happened, and steps to reproduce. Review screenshots and logs for private data first. Do not attach credentials or full conversation/session files.

To make a clean source archive for a standalone repository:

```sh
python3 scripts/package-source.py
```

The archive is written to `dist/TokenBar-source.tar.gz`. It excludes build outputs, caches, and local agent configuration. Publish the extracted project contents as the repository root so GitHub discovers its workflow.
