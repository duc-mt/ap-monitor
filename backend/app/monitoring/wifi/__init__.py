"""
==============================================================================
Module Name:   __init__.py
Description:   Source module __init__.py.
Author:        Mai Tan Duc <ducmai.network@gmail.com>
Created:       2026-10-10
Version:       1.0.0
License:       MIT
==============================================================================
Usage:         python3 __init__.py [options]
Notes:         Requires Python 3.8+
==============================================================================
"""

from here - never reach into `.linux`/`.macos`/`.windows` directly, so a
further platform can be added without touching any call site.

A short-TTL cache sits in front of `get_metrics()`, mirroring the same
pattern `network_info.py` already uses for SSID lookups: a monitoring tick
every ~5s doesn't need a fresh subprocess/CoreWLAN round-trip every single
time, and walk-test mode's much faster 500ms sampling interval (Stage 11)
would otherwise spawn `iw`/`nmcli` far more often than the underlying
radio state actually changes.
"""

from __future__ import annotations

import sys
import time
from datetime import UTC
from typing import Dict, List, Optional, Tuple

from app.models.wifi_scan import EnvironmentScanResult
from app.monitoring.wifi.base import WifiAdapter
from app.monitoring.wifi.models import WifiInterfaceInfo, WifiMetrics

_CACHE_TTL_SECONDS = 2.0


def _build_adapter() -> WifiAdapter:
    if sys.platform == "darwin":
        from app.monitoring.wifi.macos import MacOSWifiAdapter

        return MacOSWifiAdapter()
    if sys.platform.startswith("linux"):
        from app.monitoring.wifi.linux import LinuxWifiAdapter

        return LinuxWifiAdapter()
    if sys.platform == "win32":
        from app.monitoring.wifi.windows import WindowsWifiAdapter

        return WindowsWifiAdapter()
    raise RuntimeError(
        f"No WiFi adapter for platform: {sys.platform!r} (Linux, macOS and Windows only)"
    )


_adapter: WifiAdapter | None = None
_metrics_cache: dict[str, tuple[float, WifiMetrics]] = {}


def _get_adapter() -> WifiAdapter:
    global _adapter
    if _adapter is None:
        _adapter = _build_adapter()
    return _adapter


async def list_wifi_interfaces() -> list[WifiInterfaceInfo]:
    return await _get_adapter().list_interfaces()


async def get_active_wifi_interface() -> str | None:
    return await _get_adapter().get_active_interface()


async def get_wifi_metrics(
    interface: str | None = None, *, use_cache: bool = True
) -> WifiMetrics:
    """
    A metrics snapshot for `interface`, or the currently active WiFi
    interface (Auto mode) when `interface` is None.

    Raises RuntimeError if no interface is given and none is active -
    callers in Auto mode should treat that as "no WiFi connection to
    monitor right now" rather than a crash.
    """
    target = interface if interface is not None else await get_active_wifi_interface()
    if target is None:
        raise RuntimeError(
            "No active WiFi interface found (Auto mode) and none specified."
        )

    if use_cache:
        cached = _metrics_cache.get(target)
        if cached is not None and (time.monotonic() - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

    metrics = await _get_adapter().get_metrics(target)
    _metrics_cache[target] = (time.monotonic(), metrics)
    return metrics


def get_adapter_issue() -> str | None:
    """A machine-readable reason the adapter could not read the radio at all
    (e.g. "location_permission" on Windows), if it knows one. Lets the status
    endpoint say *why* there is no interface instead of just "none found"."""
    try:
        return getattr(_get_adapter(), "last_issue", None)
    except RuntimeError:
        return None


def reset_cache() -> None:
    """Test isolation hook, same purpose as network_info.reset_cache()."""
    _metrics_cache.clear()


async def scan_environment(interface: str | None = None) -> EnvironmentScanResult:
    """
    The on-demand "Scan Environment" feature. Never called from the
    background monitoring loop or a walk-test session - only in direct
    response to a user action (an API call from the Settings/RF-tools UI).

    Gets a *fresh* reading of the current connection (use_cache=False,
    since this is a rare, deliberate action where staleness would be
    actively misleading) so the co-channel-interference comparison below
    is against genuinely current data, then filters the adapter's own
    connection out of the neighbor list and flags anything sharing its
    channel.
    """
    from datetime import datetime, timezone

    target = interface if interface is not None else await get_active_wifi_interface()
    if target is None:
        raise RuntimeError(
            "No active WiFi interface found (Auto mode) and none specified."
        )

    current = await get_wifi_metrics(target, use_cache=False)
    raw_neighbors = await _get_adapter().scan_neighbors(target)
    neighbors = [
        n for n in raw_neighbors if current.bssid is None or n.bssid != current.bssid
    ]
    for n in neighbors:
        n.is_co_channel = current.channel is not None and n.channel == current.channel

    return EnvironmentScanResult(
        timestamp=datetime.now(UTC).isoformat(),
        interface=target,
        connected_channel=current.channel,
        connected_band=current.band,
        neighbors=neighbors,
    )


def _set_adapter_for_testing(adapter: WifiAdapter | None) -> None:
    """Test-only seam: inject a fake adapter instead of picking one from
    sys.platform, so adapter-selection logic itself can be exercised
    without needing to run on both a real Linux box and a real Mac."""
    global _adapter
    _adapter = adapter
