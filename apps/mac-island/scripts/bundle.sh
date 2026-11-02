#!/usr/bin/env bash
# Builds "Moloko Island.app" into apps/mac-island/build/ (Command Line Tools only, no Xcode).
#   apps/mac-island/scripts/bundle.sh            # version 0.1.0
#   VERSION=0.2.0 BUILD_NUMBER=2 apps/mac-island/scripts/bundle.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$ROOT/../.." && pwd)"
VERSION="${VERSION:-0.1.0}"
BUILD_NUMBER="${BUILD_NUMBER:-1}"
APP_NAME="Moloko Island"
EXECUTABLE="MolokoIsland"
BUNDLE_ID="kz.moloko.island"
ICON_SOURCE="$REPO/apps/web/public/icons/icon-512.png"

APP="$ROOT/build/$APP_NAME.app"
# Assemble and sign outside the repo: when the repo sits in an iCloud-synced folder (Desktop &
# Documents), File Provider tags bundles with FinderInfo and codesign refuses to sign them.
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/moloko-island.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
STAGED_APP="$STAGE/$APP_NAME.app"
WORK="$STAGE/work"

echo "==> swift build -c release"
cd "$ROOT"
swift build -c release
BIN_DIR="$(swift build -c release --show-bin-path)"

echo "==> assembling $APP_NAME.app"
mkdir -p "$STAGED_APP/Contents/MacOS" "$STAGED_APP/Contents/Resources" "$WORK"
cp "$BIN_DIR/$EXECUTABLE" "$STAGED_APP/Contents/MacOS/$EXECUTABLE"
printf 'APPL????' > "$STAGED_APP/Contents/PkgInfo"

cat > "$STAGED_APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>ru</string>
  <key>CFBundleExecutable</key><string>$EXECUTABLE</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$BUILD_NUMBER</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>moloko</string>
  <key>NSLocalNetworkUsageDescription</key><string>Moloko Island подключается к вашему серверу moloko.</string>
  <key>NSMicrophoneUsageDescription</key><string>Чтобы диктовать задачи агентам голосом прямо в островке.</string>
  <key>NSAppTransportSecurity</key>
  <dict>
    <!-- the owner chooses the server; an http:// address on the home network must work -->
    <key>NSAllowsArbitraryLoadsInWebContent</key><true/>
  </dict>
</dict>
</plist>
PLIST
plutil -lint "$STAGED_APP/Contents/Info.plist" >/dev/null

echo "==> icon from apps/web/public/icons/icon-512.png"
ICONSET="$WORK/AppIcon.iconset"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$ICON_SOURCE" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  if [ "$double" -le 512 ]; then
    sips -z "$double" "$double" "$ICON_SOURCE" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
  fi
done
iconutil -c icns "$ICONSET" -o "$STAGED_APP/Contents/Resources/AppIcon.icns"
rm -rf "$WORK"

echo "==> ad-hoc signing"
xattr -cr "$STAGED_APP"
codesign --force --deep --sign - "$STAGED_APP"
codesign --verify --strict --verbose=1 "$STAGED_APP"

mkdir -p "$ROOT/build"
rm -rf "$APP"
ditto "$STAGED_APP" "$APP"

echo "Done: $APP ($VERSION, build $BUILD_NUMBER)"
