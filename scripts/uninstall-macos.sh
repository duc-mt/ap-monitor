#!/usr/bin/env bash
# ==============================================================================
# Script Name:   uninstall-macos.sh
# Description:   Uninstall AP Monitor LaunchAgent on macOS.
# Author:        Mai Tan Duc <ducmai.network@gmail.com>
# Created:       2026-10-10
# Version:       1.0.0
# License:       MIT
# ==============================================================================
# Usage:         ./scripts/uninstall-macos.sh [--purge]
# Notes:         --purge removes stored history and configuration.
# ==============================================================================
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is for macOS only - see scripts/uninstall.sh for Linux." >&2
  exit 1
fi

INSTALL_DIR="$HOME/Library/Application Support/ap-monitor"
DATA_DIR="$INSTALL_DIR/data"
PLIST_FILE="$HOME/Library/LaunchAgents/com.ap-monitor.agent.plist"
PURGE=false

for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=true ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

echo "==> Unloading LaunchAgent"
launchctl unload "$PLIST_FILE" 2>/dev/null || true

echo "==> Removing LaunchAgent definition"
rm -f "$PLIST_FILE"

echo "==> Removing CLI wrapper"
rm -f /usr/local/bin/ap-monitor "$HOME/.local/bin/ap-monitor" 2>/dev/null || true

if [[ "$PURGE" == true ]]; then
  echo "==> --purge passed: removing everything, including $DATA_DIR"
  rm -rf "$INSTALL_DIR"
else
  echo "==> Removing installed app files, leaving $DATA_DIR in place (pass --purge to remove it too)"
  find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 ! -name data -exec rm -rf {} +
fi

echo "Uninstalled."
