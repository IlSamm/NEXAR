#!/bin/bash
# Compila NEXAR.app (Apple Silicon + Intel) e la impacchetta in build/NEXAR-Mac.zip. Gira su GitHub (macOS).
#   bash mac/build.sh 1.0.40
set -euo pipefail
VERSION="${1:-0.0.0}"
VERSION="${VERSION#v}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/build"
APP="$OUT/NEXAR.app"
rm -rf "$OUT"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

for arch in arm64 x86_64; do
  swiftc -O -target "$arch-apple-macos13.0" "$ROOT/mac/NEXAR.swift" -o "$OUT/NEXAR-$arch"
done
lipo -create "$OUT/NEXAR-arm64" "$OUT/NEXAR-x86_64" -output "$APP/Contents/MacOS/NEXAR"

ICONSET="$OUT/AppIcon.iconset"; mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$ROOT/web/icon-512.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2)); sips -z $d $d "$ROOT/web/icon-512.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>NEXAR</string>
  <key>CFBundleDisplayName</key><string>NEXAR</string>
  <key>CFBundleIdentifier</key><string>com.ilsamm.nexar</string>
  <key>CFBundleExecutable</key><string>NEXAR</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.utilities</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>NEXAR</string>
  <key>NSLocalNetworkUsageDescription</key><string>Serve per accendere il PC quando il Mac è nella stessa rete di casa.</string>
</dict></plist>
PLIST

codesign --force --deep --sign - "$APP"
"$APP/Contents/MacOS/NEXAR" --selftest
(cd "$OUT" && ditto -c -k --keepParent NEXAR.app NEXAR-Mac.zip && shasum -a 256 NEXAR-Mac.zip > NEXAR-Mac.zip.sha256)
echo "Pronto: $OUT/NEXAR-Mac.zip"
