#!/usr/bin/env bash
# Install AP Monitor for the current macOS user via a LaunchAgent - see
# packaging/launchd/com.ap-monitor.agent.plist for why this is a per-user
# LaunchAgent rather than a system-wide LaunchDaemon.
#
# Deliberately requires NO sudo/root at any point: everything lives under
# ~/Library/Application Support/ap-monitor, matching the LaunchAgent's own
# per-user model. Contrast with scripts/install.sh (Linux), which needs
# root for useradd/systemd/CAP_NET_RAW.
#
# Usage: ./scripts/install-macos.sh [--enable]
#   --enable   also load the LaunchAgent immediately (launchctl load).
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is for macOS only - see scripts/install.sh for Linux." >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="$HOME/Library/Application Support/ap-monitor"
DATA_DIR="$INSTALL_DIR/data"
LOG_DIR="$INSTALL_DIR/logs"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$PLIST_DIR/com.ap-monitor.agent.plist"
ENABLE_NOW=false

for arg in "$@"; do
  case "$arg" in
    --enable) ENABLE_NOW=true ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

echo "==> Checking for required tools"
command -v python3 >/dev/null || { echo "python3 is required (install Xcode Command Line Tools or python.org)" >&2; exit 1; }
echo "    python3 found ($(python3 -c 'import sys; print(sys.version_info[:2])'))"
if ! command -v nmcli >/dev/null 2>&1; then :; fi  # nmcli is Linux-only; nothing to check here
if command -v system_profiler >/dev/null 2>&1; then
  echo "    system_profiler found (used only by the on-demand Scan Environment feature)"
fi

echo "==> Creating directories"
mkdir -p "$INSTALL_DIR/backend" "$DATA_DIR" "$LOG_DIR" "$PLIST_DIR"

echo "==> Copying backend"
rsync -a --delete "$ROOT_DIR/backend/app" "$INSTALL_DIR/backend/"
cp "$ROOT_DIR/backend/requirements.txt" "$INSTALL_DIR/backend/"

if [[ -d "$ROOT_DIR/frontend/dist" ]]; then
  echo "==> Copying pre-built frontend"
  rsync -a --delete "$ROOT_DIR/frontend/dist" "$INSTALL_DIR/frontend-dist"
  mkdir -p "$INSTALL_DIR/frontend"
  rm -rf "$INSTALL_DIR/frontend/dist"
  mv "$INSTALL_DIR/frontend-dist" "$INSTALL_DIR/frontend/dist"
else
  echo "==> No frontend/dist found - run 'npm run build' in frontend/ first if you want the dashboard UI."
  echo "    The API will still work; visit /docs for the interactive API reference."
fi

echo "==> Creating virtual environment (this pulls in pyobjc-framework-CoreWLAN, macOS-only)"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/backend/requirements.txt" -q
"$INSTALL_DIR/venv/bin/pip" install uvicorn -q
"$INSTALL_DIR/venv/bin/pip" install "$ROOT_DIR/cli" -q

echo "==> Installing CLI wrapper"
if ln -sf "$INSTALL_DIR/venv/bin/ap-monitor" /usr/local/bin/ap-monitor 2>/dev/null; then
  echo "    linked to /usr/local/bin/ap-monitor"
else
  mkdir -p "$HOME/.local/bin"
  ln -sf "$INSTALL_DIR/venv/bin/ap-monitor" "$HOME/.local/bin/ap-monitor"
  echo "    /usr/local/bin isn't writable without sudo - linked to ~/.local/bin/ap-monitor instead."
  echo "    Add this to your shell profile if it isn't already on your PATH:"
  echo "      export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

echo "==> Installing LaunchAgent"
sed -e "s|{{INSTALL_DIR}}|$INSTALL_DIR|g" -e "s|{{DATA_DIR}}|$DATA_DIR|g" \
  "$ROOT_DIR/packaging/launchd/com.ap-monitor.agent.plist" > "$PLIST_FILE"

echo
echo "Installed. Next steps:"
echo "  launchctl load -w \"$PLIST_FILE\"    # start now and on every login"
echo "  launchctl list | grep ap-monitor"
echo "  ap-monitor status"
echo
echo "WiFi details: macOS hides the SSID and BSSID from any process without"
echo "Location Services permission (System Settings > Privacy & Security >"
echo "Location Services). RSSI, channel and the rest work without it, but"
echo "roaming cannot be detected until it is granted. macOS may not prompt for"
echo "a background Python process by itself - the dashboard shows a banner"
echo "explaining the state, and README.md describes what to do if the launcher"
echo "isn't listed there."
echo

if [[ "$ENABLE_NOW" == true ]]; then
  echo "==> --enable passed: loading the LaunchAgent now"
  launchctl load -w "$PLIST_FILE"
  launchctl list | grep ap-monitor || true
fi
