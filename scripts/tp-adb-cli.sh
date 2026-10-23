#!/usr/bin/env bash
set -euo pipefail

export ADB_LIBUSB=0
URI="content://com.blawhi3929bd.tunnelpilot.debug.cli"
PKG="com.blawhi3929bd.tunnelpilot.debug"
ACTIVITY="$PKG/com.blawhi3929bd.tunnelpilot.MainActivity"

ensure_adb() {
  if ! adb get-state >/dev/null 2>&1; then
    adb kill-server >/dev/null 2>&1 || true
    ADB_LIBUSB=0 adb start-server >/dev/null 2>&1
    sleep 1
  fi
  if ! adb get-state >/dev/null 2>&1; then
    echo "Error: no Android device reachable via ADB (ADB_LIBUSB=0)" >&2
    exit 2
  fi
}

ensure_app_started() {
  if [[ -z "$(adb shell pidof "$PKG" 2>/dev/null || true)" ]]; then
    if ! adb shell pm path "$PKG" >/dev/null 2>&1; then
      echo "Error: package $PKG is not installed on the device" >&2
      exit 2
    fi
    adb shell am start -W -n "$ACTIVITY" >/dev/null 2>&1 || true
  fi
}

call_cli() {
  local method="$1"
  local arg="${2:-}"
  ensure_adb
  ensure_app_started

  local output
  if [[ -n "$arg" ]]; then
    if ! output="$(adb shell content call --uri "$URI" --method "$method" --arg "$arg" 2>&1)"; then
      echo "$output" >&2
      exit 2
    fi
  else
    if ! output="$(adb shell content call --uri "$URI" --method "$method" 2>&1)"; then
      echo "$output" >&2
      exit 2
    fi
  fi

  echo "$output"

  if [[ "$output" == *"Could not find provider"* ]] || [[ "$output" == *"SecurityException"* ]]; then
    exit 2
  fi

  if [[ "$output" == *"ok=false"* ]]; then
    if [[ "$output" == *"Control plane"* ]] || [[ "$output" == *"Failed to connect"* ]] || [[ "$output" == *"Cleartext"* ]] || [[ "$output" == *"timed out"* ]]; then
      exit 3
    fi
    exit 1
  fi
}

cmd="${1:-status}"
shift || true

case "$cmd" in
  install)
    ensure_adb
    adb install -r "${1:-app/build/outputs/apk/debug/app-debug.apk}"
    adb reverse tcp:8000 tcp:8000 || true
    ;;
  status)
    call_cli "status"
    ;;
  servers|check-servers|check_servers)
    call_cli "check_servers"
    ;;
  probe-http|probe_http)
    call_cli "probe_http" "${1:?Usage: $0 probe-http <url>}"
    ;;
  set-url|set_url)
    call_cli "set_url" "${1:?Usage: $0 set-url <url>}"
    ;;
  provision)
    call_cli "provision" "${1:-}"
    ;;
  rotate-key|rotate_key|rotate)
    call_cli "rotate_key"
    ;;
  migrate-server|migrate_server|migrate)
    call_cli "migrate_server" "${1:?Usage: $0 migrate-server <server_id>}"
    ;;
  select-server|select_server)
    call_cli "select_server" "${1:-auto}"
    ;;
  select-region|select_region)
    call_cli "select_region" "${1:-auto}"
    ;;
  connect)
    call_cli "connect"
    ;;
  disconnect)
    call_cli "disconnect"
    ;;
  set-mode|set_routing_mode)
    call_cli "set_routing_mode" "${1:?Usage: $0 set-mode ALL_APPS|SELECTED_APPS}"
    ;;
  set-apps|set_selected_apps)
    call_cli "set_selected_apps" "${1:-}"
    ;;
  apply-routing|apply_routing)
    call_cli "apply_routing"
    ;;
  revoke|clear-config|clear_config)
    call_cli "revoke" "${1:-}"
    ;;
  reset-identity|reset_identity)
    call_cli "reset_identity" "${1:-}"
    ;;
  help|-h|--help)
    cat <<EOF
Usage: $0 <command> [arg]

Exit codes:
  0  Success (ok=true)
  1  Application/validation error (ok=false)
  2  ADB / device / provider error
  3  Network / Control Plane communication error

Commands:
  install [apk_path]             Install debug APK (auto-fixing ADB_LIBUSB=0) and set adb reverse tcp:8000
  status                         Show current VPN, routing, and provisioning status
  servers                        Query Control Plane /v1/servers health and capacity from the phone
  set-url <url>                  Update Control Plane URL
  select-server <server_id|auto> Set preferred server ID for initial provisioning
  select-region <region|auto>    Set preferred region for initial provisioning
  provision [url]                Provision device (optionally setting Control Plane URL first)
  migrate-server <server_id>     Explicitly migrate provisioned device to another server
  rotate-key                     Generate a new WireGuard keypair and rotate it on the server
  connect                        Connect the WireGuard VPN tunnel
  disconnect                     Disconnect the WireGuard VPN tunnel
  set-mode <ALL_APPS|SELECTED_APPS>
                                 Switch routing mode
  set-apps <pkg1,pkg2,...>       Set comma-separated package list for SELECTED_APPS mode
  apply-routing                  Reconnect tunnel if active to apply routing changes
  revoke [force_local]           Revoke device on server and clear local config/keys
  reset-identity [force_local]   Revoke old identity, generate a new device_id, and clear keys
EOF
    ;;
  *)
    echo "Unknown command: $cmd (run '$0 --help' for usage)" >&2
    exit 1
    ;;
esac
