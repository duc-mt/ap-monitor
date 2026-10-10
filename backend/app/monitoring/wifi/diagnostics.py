"""
Turns "the WiFi fields are empty" into an explanation the user can act on.

The failure this exists for: on macOS and Windows the OS withholds the SSID
and BSSID from any process that lacks Location permission. Everything still
"works" - pings succeed, RSSI may even read fine - but the connected AP is
blank and roaming can never be detected, with no error anywhere. A monitor
that silently shows nothing is indistinguishable from a broken one, so every
such case is surfaced as a WifiIssue in /api/status.
"""
from __future__ import annotations

import shutil
import sys
from typing import Optional

from app.models.status import WifiIssue
from app.monitoring.wifi.models import WifiMetrics

_LOCATION_HELP = {
    "darwin": (
        "macOS hides the SSID and BSSID from any process without Location Services "
        "permission. Open System Settings > Privacy & Security > Location Services, "
        "turn it on, and allow the app that launches the backend (Terminal, iTerm or "
        "your IDE). Restart the backend afterwards. Until then AP changes and roaming "
        "cannot be detected."
    ),
    "win32": (
        "Windows can withhold WiFi details until Location is enabled. Open Settings > "
        "Privacy & security > Location, turn on Location services and 'Let desktop apps "
        "access your location', then restart the backend. Until then AP changes and "
        "roaming cannot be detected."
    ),
}


def _location_help() -> str:
    return _LOCATION_HELP.get(
        sys.platform,
        "The OS did not report the connected access point's address. Without it AP "
        "changes and roaming cannot be detected.",
    )


def issue_for(code: str) -> WifiIssue:
    if code == "location_permission":
        return WifiIssue(code=code, title="WiFi details are hidden by the OS", detail=_location_help())
    if code == "bssid_unavailable":
        if sys.platform in _LOCATION_HELP:
            return WifiIssue(code=code, title="Connected AP address (BSSID) not reported", detail=_location_help())
        return WifiIssue(
            code=code, title="Connected AP address (BSSID) not reported",
            detail=(
                "NetworkManager/iw did not report the BSSID of the connected access point, so "
                "AP changes and roaming cannot be detected. Check that the adapter is managed "
                "by NetworkManager and that `iw dev <interface> link` shows a BSSID."
            ),
        )
    if code == "missing_tools":
        return WifiIssue(
            code=code, title="Required WiFi tools are not installed",
            detail="AP Monitor needs `nmcli` (NetworkManager) and `iw` on Linux. Install them, e.g. "
                   "`sudo apt install network-manager iw`, then restart the backend.",
        )
    if code == "no_wifi_interface":
        return WifiIssue(
            code=code, title="No active WiFi connection found",
            detail="AP Monitor reads the WiFi adapter's association. Make sure WiFi is turned on and "
                   "connected to a network (a wired-only connection is not monitored).",
        )
    return WifiIssue(
        code="adapter_error", title="Could not read the WiFi adapter",
        detail="The platform WiFi tool failed unexpectedly. Check the backend log for details.",
    )


def diagnose(metrics: WifiMetrics) -> Optional[WifiIssue]:
    """The issue (if any) explaining incomplete fields in a successful reading."""
    if metrics.issue:
        return issue_for(metrics.issue)
    if metrics.interface_state == "connected" and metrics.bssid is None:
        return issue_for("bssid_unavailable")
    return None


def no_interface_issue() -> WifiIssue:
    """The issue for 'no active WiFi interface at all', checking first
    whether the cause is simply that the Linux tooling is missing."""
    if sys.platform.startswith("linux") and (shutil.which("nmcli") is None or shutil.which("iw") is None):
        return issue_for("missing_tools")
    return issue_for("no_wifi_interface")
