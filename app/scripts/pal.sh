#!/bin/sh
# Build and run the Pal app without Xcode.
#
#   app/scripts/pal.sh          build and run (debug)
#   app/scripts/pal.sh bundle   build a release Pal.app you can keep in /Applications
set -e
cd "$(dirname "$0")/.."

# The newest Command Line Tools SDK expects SwiftUI macro plugins that only ship
# with Xcode. Without Xcode, build against the macOS 26 SDK instead.
CLT=/Library/Developer/CommandLineTools
if [ -z "$SDKROOT" ] && [ "$(xcode-select -p 2>/dev/null)" = "$CLT" ] && [ -d "$CLT/SDKs/MacOSX26.sdk" ]; then
  export SDKROOT="$CLT/SDKs/MacOSX26.sdk"
fi

if [ "$1" != "bundle" ]; then
  exec swift run Pal
fi

swift build -c release
APP=Pal.app
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$(swift build -c release --show-bin-path)/Pal" "$APP/Contents/MacOS/Pal"
swift scripts/make-icon.swift "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Pal</string>
  <key>CFBundleDisplayName</key><string>Pal</string>
  <key>CFBundleIdentifier</key><string>org.openpal.app</string>
  <key>CFBundleExecutable</key><string>Pal</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>26.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
PLIST
codesign --force --sign - "$APP" >/dev/null
echo "Built $(pwd)/$APP"
