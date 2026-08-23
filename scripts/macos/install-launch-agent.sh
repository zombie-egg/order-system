#!/bin/zsh
# Install or refresh the per-user macOS service that keeps the whole local stack running.

set -eu

project_root="$(cd "$(dirname "$0")/../.." && pwd)"
template="$project_root/scripts/macos/com.sippilot.local.plist.template"
plist="$HOME/Library/LaunchAgents/com.sippilot.local.plist"
label="com.sippilot.local"
user_id="$(id -u)"
launch_root="$HOME/sippilot-local"
launcher_root="$HOME/.local/sippilot-launcher"
log_root="$HOME/Library/Logs/SipPilot"

mkdir -p "$HOME/Library/LaunchAgents" "$log_root" "$launcher_root"
ln -sfn "$project_root" "$launch_root"
cp "$project_root/scripts/macos/keep-services.sh" "$launcher_root/keep-services.sh"
chmod +x "$launcher_root/keep-services.sh"
escaped_root="${launch_root//\/\\}"
escaped_root="${escaped_root//&/\\&}"
escaped_root="${escaped_root//|/\\|}"
escaped_launcher_root="${launcher_root//\/\\}"
escaped_launcher_root="${escaped_launcher_root//&/\\&}"
escaped_launcher_root="${escaped_launcher_root//|/\\|}"
escaped_log_root="${log_root//\/\\}"
escaped_log_root="${escaped_log_root//&/\\&}"
escaped_log_root="${escaped_log_root//|/\\|}"

launchctl bootout "gui/$user_id/$label" 2>/dev/null || true
sed -e "s|__LAUNCH_ROOT__|$escaped_root|g" \
    -e "s|__LAUNCHER_ROOT__|$escaped_launcher_root|g" \
    -e "s|__LOG_ROOT__|$escaped_log_root|g" \
    "$template" > "$plist"
plutil -lint "$plist"
if ! launchctl bootstrap "gui/$user_id" "$plist" 2>/dev/null; then
  # When it was already loaded, refresh the existing per-user job instead.
  launchctl kickstart -k "gui/$user_id/$label"
else
  launchctl kickstart -k "gui/$user_id/$label"
fi

print "SipPilot auto-start installed. It will run after every macOS login."
print "Kiosk: http://127.0.0.1:5173"
print "KDS:   http://127.0.0.1:5174"
print "Admin: http://127.0.0.1:5175"
