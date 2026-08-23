#!/bin/zsh
# Keep the local SipPilot stack available for one signed-in macOS user.
# launchd starts this script after login; each child is restarted if it exits.

set -u

project_root="${SIPPILOT_PROJECT_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
log_directory="$HOME/Library/Logs/SipPilot"
python_executable="$project_root/.venv-macos/bin/python"

mkdir -p "$log_directory"

if [[ ! -x "$python_executable" ]]; then
  print -u2 "SipPilot cannot start: missing $python_executable"
  print -u2 "Create the local runtime with: /usr/local/bin/python3.13 -m venv .venv-macos"
  exit 1
fi

export DATABASE_URL="sqlite+aiosqlite:////${project_root#/}/var/demo/demo.db"
export MEDIA_STORAGE_DIR="$project_root/var/demo/media"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

run_forever() {
  local name="$1"
  shift
  local log_file="$log_directory/macos-${name}.log"
  local child_pid=""

  stop_child() {
    [[ -n "$child_pid" ]] && kill "$child_pid" 2>/dev/null || true
    exit 0
  }
  trap stop_child TERM INT

  while true; do
    print "[$(date '+%Y-%m-%d %H:%M:%S')] starting $name" >> "$log_file"
    "$@" >> "$log_file" 2>&1 &
    child_pid=$!
    wait "$child_pid"
    local exit_code=$?
    child_pid=""
    print "[$(date '+%Y-%m-%d %H:%M:%S')] $name stopped (exit $exit_code); restarting in 2 seconds" >> "$log_file"
    sleep 2
  done
}

child_wrappers=()

cleanup() {
  trap - TERM INT EXIT
  for child_wrapper in "${child_wrappers[@]}"; do
    kill "$child_wrapper" 2>/dev/null || true
  done
}

trap cleanup TERM INT EXIT

cd "$project_root"
run_forever edge-api "$python_executable" -m uvicorn app.main:create_app --factory --app-dir apps/edge-api --host 127.0.0.1 --port 8000 &
child_wrappers+=($!)
sleep 1
run_forever kiosk npm run dev --workspace @smart-drink/kiosk-web -- --host 127.0.0.1 --port 5173 &
child_wrappers+=($!)
run_forever kds npm run dev --workspace @smart-drink/kitchen-display-web -- --host 127.0.0.1 --port 5174 &
child_wrappers+=($!)
run_forever admin npm run dev --workspace @smart-drink/admin-web -- --host 127.0.0.1 --port 5175 &
child_wrappers+=($!)

# Keep the launchd-owned parent alive. Each wrapper above independently restarts
# its own service, so this parent does not need to exit when a child is replaced.
while true; do
  sleep 3600
done
