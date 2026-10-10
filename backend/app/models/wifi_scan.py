"""
Models for the on-demand "Scan Environment" feature. Never populated by
the background monitoring loop - only by an explicit, user-triggered scan
(see app.monitoring.wifi.scan_environment).
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class NeighborNetwork(BaseModel):
    ssid: Optional[str] = None
    # None on macOS - system_profiler's "Other Local Wi-Fi Networks" block
    # doesn't expose a BSSID for neighboring networks, only for the one
    # you're actually connected to. This is an honest platform limitation,
    # not a parsing gap: Linux's `iw scan` output gives a real BSSID here.
    bssid: Optional[str] = None
    phy_mode: Optional[str] = None
    channel: Optional[int] = None
    channel_width_mhz: Optional[int] = None
    band: Optional[str] = None
    security: Optional[str] = None
    rssi_dbm: Optional[int] = None
    is_co_channel: bool = False


class EnvironmentScanResult(BaseModel):
    timestamp: str
    interface: str
    connected_channel: Optional[int] = None
    connected_band: Optional[str] = None
    neighbors: List[NeighborNetwork]
