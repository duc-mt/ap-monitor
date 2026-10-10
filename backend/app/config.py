"""
Application-wide configuration.

Two layers of configuration exist deliberately:

1. Environment/deploy-time config (this module) - where the SQLite file
   lives, which host/port uvicorn binds to, log level. These rarely change
   and are fine as environment variables with sensible defaults.

2. User-tunable settings (app.services.settings_service.AppSettings) - things
   like thresholds and notification preferences that live in the `settings`
   table so they can be changed from the dashboard without restarting the
   service or touching the filesystem.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _default_data_dir() -> Path:
    """
    Per-platform user data directory:
      - Windows: %LOCALAPPDATA%\\ap-monitor
      - Linux/macOS: follow the XDG base directory spec so the app behaves
        whether it is run as a systemd service (running as its own
        unprivileged user, with XDG_DATA_HOME pointed at /var/lib/ap-monitor
        by the unit file) or run manually by a developer out of a checkout.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ap-monitor"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "ap-monitor"
    return Path.home() / ".local" / "share" / "ap-monitor"


DATA_DIR = Path(os.environ.get("AP_MONITOR_DATA_DIR", _default_data_dir()))
DATABASE_PATH = DATA_DIR / "ap-monitor.db"

# The API must never be reachable off the local machine by default.
API_HOST = os.environ.get("AP_MONITOR_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("AP_MONITOR_PORT", "8766"))

# Origins the dashboard may be served from during development (vite dev
# server). The production build is served by FastAPI itself from the same
# origin, so no CORS entry is needed for it.
DEV_CORS_ORIGINS = [
    "http://127.0.0.1:5174",
    "http://localhost:5174",
]

LOG_LEVEL = os.environ.get("AP_MONITOR_LOG_LEVEL", "INFO")

# Absolute floor on how often any target may be checked, regardless of what
# a user requests in Settings/Targets. Protects against fat-fingering a
# 0-second interval and flooding the network.
MIN_INTERVAL_SECONDS = 1

# Built frontend, if present, is mounted at "/" by app.main.
FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
