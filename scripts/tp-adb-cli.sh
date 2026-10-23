#!/usr/bin/env bash
set -euo pipefail

export ADB_LIBUSB=0
URI="content://com.blawhi3929bd.tunnelpilot.debug.cli"

ensure_adb() {
  if ! adb get-state >/dev/null 2>&1; then
    adb kill-server >/dev/null 2>&1 || true
    ADB_LIBUSB=0 adb start-server >/dev/null 2>&1
    sleep 1
  fi
}

call_cli() {
  local method="$1"
  local arg="${2:-}"
  ensure_adb
  if [[ -z "$(adb shell pidof com.blawhi3929bd.tunnelpilot.debug 2>/dev/null || true)" ]]; then
    adb shell am start -W -n com.blawhi3929bd.tunnelpilot.debug/com.blawhi3929bd.tunnelpilot.MainActivity >/dev/null 2>&1 || true
  fi
  if [[ -n "$arg" ]]; then
    adb shell content call --uri "$URI" --method "$method" --arg "$arg"
  else
    adb shell content call --uri "$URI" --method "$method"
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
  set-url|set_url)
    call_cli "set_url" "${1:?Usage: $0 set-url <url>}"
    ;;
  provision)
    call_cli "provision" "${1:-}"
    ;;
  rotate-key|rotate_key|rotate)
    call_cli "rotate_key"
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
    call_cli "revoke"
    ;;
  reset-identity|reset_identity)
    call_cli "reset_identity"
    ;;
  servers|check-servers|check_servers)
    call_cli "check_servers"
    ;;
  help|-h|--help)
    cat <<EOF
Usage: $0 <command> [arg]

Commands:
  install [apk_path]             Install debug APK (auto-fixing ADB_LIBUSB=0) and set adb reverse tcp:8000
  status                         Show current VPN, routing, and provisioning status
  servers                        Query Control Plane /v1/servers health and capacity from the phone
  set-url <url>                  Update Control Plane URL
  provision [url]                Provision device (optionally setting Control Plane URL first)
  rotate-key                     Generate a new WireGuard keypair and rotate it on the server
  connect                        Connect the WireGuard VPN tunnel
  disconnect                     Disconnect the WireGuard VPN tunnel
  set-mode <ALL_APPS|SELECTED_APPS>
                                 Switch routing mode
  set-apps <pkg1,pkg2,...>       Set comma-separated package list for SELECTED_APPS mode
  apply-routing                  Reconnect tunnel if active to apply routing changes
  revoke                         Revoke device on server and clear local config/keys
  reset-identity                 Revoke old identity, generate a new device_id, and clear keys
EOF
    ;;
  *)
    echo "Unknown command: $cmd (run '$0 --help' for usage)" >&2
    exit 1
    ;;
esac
