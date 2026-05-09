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
# We background the launch with `&` and `disown` so the osascript dialog
# can dismiss without keeping a Terminal window open. nohup + redirect
# output to a log so the parent shell can exit cleanly.
osascript <<EOF
do shell script "nohup '$EXE' >/tmp/locwarp-stdout.log 2>/tmp/locwarp-stderr.log &" with administrator privileges with prompt "LocWarp needs administrator privileges to talk to iOS 17+ devices over USB."
EOF
