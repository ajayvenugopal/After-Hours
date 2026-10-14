#!/bin/bash
# Build a universal, ad-hoc signed preview disk image. No signing credentials needed.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$(uname -s)" != Darwin ]; then
    echo 'DMG packaging requires macOS.' >&2
    exit 1
fi
bash scripts/build.sh --universal
VERSION=$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' Resources/Info.plist)
DMG="dist/TokenBar-${VERSION}-universal.dmg"
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/tokenbar-dmg.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT
codesign --verify --strict dist/TokenBar.app
lipo dist/TokenBar.app/Contents/MacOS/TokenBar -verify_arch arm64 x86_64
ditto dist/TokenBar.app "$STAGE/TokenBar.app"
ln -s /Applications "$STAGE/Applications"
cat > "$STAGE/Install.txt" <<'TXT'
TokenBar for macOS 13+ (Apple silicon and Intel)

1. Drag TokenBar.app to Applications.
2. Eject this disk image and open TokenBar from Applications.
3. Click the TokenBar icon in the menu bar.

This preview is ad-hoc signed, not Developer ID signed or notarized.
If macOS blocks it, try launching once, then use System Settings >
Privacy & Security > Open Anyway. Only override for a download you trust.

Codex: sign in with the installed Codex app or CLI.
Claude and optional local/Gemini integrations: see the README.

https://github.com/ajayvenugopal/After-Hours/tree/main/apps/TokenBar
TXT
hdiutil create -volname "TokenBar ${VERSION}" -srcfolder "$STAGE" -format UDZO -ov "$DMG"
hdiutil verify "$DMG"
(cd dist && shasum -a 256 "$(basename "$DMG")") > "${DMG}.sha256"
printf 'Packaged %s/%s\n' "$PWD" "$DMG"
