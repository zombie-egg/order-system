#!/bin/zsh
set -eu

label="com.sippilot.local"
plist="$HOME/Library/LaunchAgents/$label.plist"
launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
[[ -f "$plist" ]] && mv "$plist" "$plist.disabled"
print "SipPilot auto-start has been stopped. The plist was retained as $plist.disabled"
