#!/usr/bin/env bash
# Launch LocWarp with administrator privileges.
#
# Why: iOS 17+ devices require pymobiledevice3 to create a utun (TUN/TAP)
# interface for the RemoteServiceDiscovery (RSD) tunnel. Creating utun
# interfaces on macOS requires root privileges (or a signed app with the
# com.apple.developer.networking.networkextension entitlement, which we
# don't have). Without admin, device connection fails with "無法建立裝置
# 通道". This wrapper uses osascript to prompt the user for their admin
# password (just like installers do), then re-launches LocWarp with sudo.
#
# Double-click this .command file, or run it from Terminal.

set -e

APP="/Applications/LocWarp.app"
EXE="$APP/Contents/MacOS/LocWarp"

if [ ! -x "$EXE" ]; then
    osascript -e 'display dialog "LocWarp not found at /Applications/LocWarp.app. Install it first." buttons {"OK"} default button 1 with icon stop'
    exit 1
fi

# Run the actual binary directly (not via `open`) so admin privileges
# propagate to the LocWarp process. `open -a` would launch via launchd,
# which strips root and runs the app as the user.
#
# osascript's `do shell script` runs without a TTY, so `nohup` fails
# with "Inappropriate ioctl for device". Instead we just redirect the
# three stdio streams and background with `&` — that's enough to
# detach the child from the (already TTY-less) parent shell.
# --no-sandbox: Electron 20+ refuses to run as root by default. The Chromium
# sandbox can't drop privileges from root, so it errors out. We're explicitly
# running as root for utun anyway, so this is intentional.
osascript <<EOF
do shell script "'$EXE' --no-sandbox </dev/null >/tmp/locwarp-stdout.log 2>/tmp/locwarp-stderr.log &" with administrator privileges with prompt "LocWarp needs administrator privileges to talk to iOS 17+ devices over USB."
EOF
