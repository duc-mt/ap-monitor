"""
==============================================================================
Module Name:   wifi_scan.py
Description:   Source module wifi_scan.py.
Author:        Mai Tan Duc <ducmai.network@gmail.com>
Created:       2026-10-10
Version:       1.0.0
License:       MIT
==============================================================================
Usage:         python3 wifi_scan.py [options]
Notes:         Requires Python 3.8+
==============================================================================
"""

from __future__ import annotations

from pydantic import BaseModel


class NeighborNetwork(BaseModel):
    ssid: str | None = None
    # None on macOS - system_profiler's "Other Local Wi-Fi Networks" block
    # doesn't expose a BSSID for neighboring networks, only for the one
    # you're actually connected to. This is an honest platform limitation,
    # not a parsing gap: Linux's `iw scan` output gives a real BSSID here.
    bssid: str | None = None
    phy_mode: str | None = None
    channel: int | None = None
    channel_width_mhz: int | None = None
    band: str | None = None
    security: str | None = None
    rssi_dbm: int | None = None
    is_co_channel: bool = False


class EnvironmentScanResult(BaseModel):
    timestamp: str
    interface: str
    connected_channel: int | None = None
    connected_band: str | None = None
    neighbors: list[NeighborNetwork]
