#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
swift build -c release
BIN_DIR="$(swift build -c release --show-bin-path)"
APP="dist/TokenBar.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN_DIR/TokenBar" "$APP/Contents/MacOS/TokenBar"
cp Resources/Info.plist "$APP/Contents/Info.plist"
cp Resources/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
cp LICENSE "$APP/Contents/Resources/LICENSE"
cp README.md "$APP/Contents/Resources/README.md"
cp scripts/claude-bridge.py scripts/install-claude-bridge.py scripts/capture-usage.py scripts/gemini-telemetry.py "$APP/Contents/Resources/"
cp docs/INTEGRATIONS.md "$APP/Contents/Resources/INTEGRATIONS.md"
mkdir -p "$APP/Contents/Resources/docs"
cp docs/*.md "$APP/Contents/Resources/docs/"
if [ -f docs/otel-collector.yaml ]; then cp docs/otel-collector.yaml "$APP/Contents/Resources/"; fi
codesign --force --sign - "$APP"
printf 'Built %s/%s\n' "$PWD" "$APP"
