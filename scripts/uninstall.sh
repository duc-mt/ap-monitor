#!/usr/bin/env bash
# ==============================================================================
# Script Name:   uninstall.sh
# Description:   Uninstall AP Monitor systemd service on Linux.
# Author:        Mai Tan Duc <ducmai.network@gmail.com>
# Created:       2026-10-10
# Version:       1.0.0
# License:       MIT
# ==============================================================================
# Usage:         sudo ./scripts/uninstall.sh [--purge]
# Notes:         --purge removes stored history and configuration.
# ==============================================================================
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "This script must be run as root (try: sudo $0)" >&2
  exit 1
fi

INSTALL_DIR=/opt/ap-monitor
DATA_DIR=/var/lib/ap-monitor
SERVICE_USER=ap-monitor
SERVICE_FILE=/etc/systemd/system/ap-monitor.service
PURGE=false

for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=true ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

echo "==> Stopping and disabling service"
systemctl stop ap-monitor.service 2>/dev/null || true
systemctl disable ap-monitor.service 2>/dev/null || true

echo "==> Removing systemd unit"
rm -f "$SERVICE_FILE"
systemctl daemon-reload

echo "==> Removing CLI wrapper"
rm -f /usr/local/bin/ap-monitor

echo "==> Removing installed files"
rm -rf "$INSTALL_DIR"

if [[ "$PURGE" == true ]]; then
  echo "==> --purge passed: removing $DATA_DIR (all history and settings)"
  rm -rf "$DATA_DIR"
else
  echo "==> Leaving $DATA_DIR in place (pass --purge to remove it too)"
fi

echo "==> Removing service user/group"
if id "$SERVICE_USER" >/dev/null 2>&1; then
  userdel "$SERVICE_USER" 2>/dev/null || true
fi

echo "Uninstalled."
