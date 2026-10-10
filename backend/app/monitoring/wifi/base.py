"""
==============================================================================
Module Name:   base.py
Description:   Source module base.py.
Author:        Mai Tan Duc <ducmai.network@gmail.com>
Created:       2026-10-10
Version:       1.0.0
License:       MIT
==============================================================================
Usage:         python3 base.py [options]
Notes:         Requires Python 3.8+
==============================================================================
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.wifi_scan import NeighborNetwork
from app.monitoring.wifi.models import WifiInterfaceInfo, WifiMetrics


class WifiAdapter(ABC):
    @abstractmethod
    async def list_interfaces(self) -> list[WifiInterfaceInfo]:
        """Every WiFi-capable interface on the system, connected or not."""

    @abstractmethod
    async def get_active_interface(self) -> str | None:
        """The interface name currently carrying the active WiFi connection, if any."""

    @abstractmethod
    async def get_metrics(self, interface: str) -> WifiMetrics:
        """
        A single point-in-time snapshot for the given interface.

        Must never trigger a network scan (no `system_profiler` here, no
        `iw dev scan`) - this runs once per monitoring tick and has to stay
        fast and non-disruptive to the existing WiFi association. On-demand
        neighbor scanning is a separate, explicitly user-triggered code path
        (scan_neighbors, below), not something this method ever does on its
        own.
        """

    @abstractmethod
    async def scan_neighbors(self, interface: str) -> list[NeighborNetwork]:
        """
        Actively scans for surrounding networks. Only ever called from the
        explicit, user-triggered "Scan Environment" action - never from the
        background monitoring loop, never on a timer. May return an empty
        list (no permission to scan, no neighbors found, or the platform's
        scan command isn't available) rather than raising, since "found
        nothing" and "couldn't check" are both legitimate, non-fatal
        outcomes for an on-demand tool like this.
        """
