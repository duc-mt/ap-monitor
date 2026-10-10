"""
Tests for app.monitoring.wifi.scan_environment - the platform-independent
orchestration on top of each adapter's scan_neighbors(): excluding the
currently-connected network from its own neighbor list, and flagging
co-channel interference against the live connection.
"""

from __future__ import annotations

from typing import List, Optional

import pytest

from app.models.wifi_scan import NeighborNetwork
from app.monitoring import wifi
from app.monitoring.wifi.base import WifiAdapter
from app.monitoring.wifi.models import WifiInterfaceInfo, WifiMetrics


class _FakeAdapter(WifiAdapter):
    def __init__(self, current: WifiMetrics, neighbors: List[NeighborNetwork]):
        self._current = current
        self._neighbors = neighbors

    async def list_interfaces(self) -> List[WifiInterfaceInfo]:
        return [
            WifiInterfaceInfo(
                name=self._current.interface, state="connected", is_active=True
            )
        ]

    async def get_active_interface(self) -> Optional[str]:
        return self._current.interface

    async def get_metrics(self, interface: str) -> WifiMetrics:
        return self._current

    async def scan_neighbors(self, interface: str) -> List[NeighborNetwork]:
        return self._neighbors


@pytest.fixture(autouse=True)
def _reset_wifi_module():
    wifi.reset_cache()
    yield
    wifi._set_adapter_for_testing(None)
    wifi.reset_cache()


@pytest.mark.asyncio
async def test_own_bssid_is_excluded_from_neighbor_list():
    current = WifiMetrics(
        timestamp="t",
        interface="wlan0",
        interface_state="connected",
        bssid="AA:AA:AA:AA:AA:AA",
        channel=6,
    )
    neighbors = [
        NeighborNetwork(
            ssid="Me", bssid="AA:AA:AA:AA:AA:AA", channel=6
        ),  # this is us, on a Linux-style scan
        NeighborNetwork(ssid="Neighbor", bssid="BB:BB:BB:BB:BB:BB", channel=11),
    ]
    wifi._set_adapter_for_testing(_FakeAdapter(current, neighbors))

    result = await wifi.scan_environment("wlan0")

    assert [n.ssid for n in result.neighbors] == ["Neighbor"]


@pytest.mark.asyncio
async def test_co_channel_neighbors_are_flagged():
    current = WifiMetrics(
        timestamp="t",
        interface="wlan0",
        interface_state="connected",
        bssid="AA:AA:AA:AA:AA:AA",
        channel=6,
        band="2.4GHz",
    )
    neighbors = [
        NeighborNetwork(ssid="SameChannel", bssid="BB:BB", channel=6),
        NeighborNetwork(ssid="DifferentChannel", bssid="CC:CC", channel=11),
    ]
    wifi._set_adapter_for_testing(_FakeAdapter(current, neighbors))

    result = await wifi.scan_environment("wlan0")

    same = next(n for n in result.neighbors if n.ssid == "SameChannel")
    different = next(n for n in result.neighbors if n.ssid == "DifferentChannel")
    assert same.is_co_channel is True
    assert different.is_co_channel is False
    assert result.connected_channel == 6
    assert result.connected_band == "2.4GHz"


@pytest.mark.asyncio
async def test_unknown_bssid_source_keeps_all_neighbors():
    """On macOS, neighbor BSSIDs are always None (a real platform
    limitation, see NeighborNetwork.bssid) - self-exclusion by BSSID simply
    can't apply there, so nothing should be dropped on that basis."""
    current = WifiMetrics(
        timestamp="t",
        interface="en0",
        interface_state="connected",
        bssid="AA:AA:AA:AA:AA:AA",
        channel=36,
    )
    neighbors = [
        NeighborNetwork(ssid="Neighbor1", bssid=None, channel=36),
        NeighborNetwork(ssid="Neighbor2", bssid=None, channel=44),
    ]
    wifi._set_adapter_for_testing(_FakeAdapter(current, neighbors))

    result = await wifi.scan_environment("en0")

    assert {n.ssid for n in result.neighbors} == {"Neighbor1", "Neighbor2"}
    assert (
        next(n for n in result.neighbors if n.ssid == "Neighbor1").is_co_channel is True
    )


@pytest.mark.asyncio
async def test_no_active_interface_raises_runtime_error():
    class _NoWifiAdapter(_FakeAdapter):
        async def get_active_interface(self) -> Optional[str]:
            return None

    wifi._set_adapter_for_testing(
        _NoWifiAdapter(
            WifiMetrics(
                timestamp="t", interface="wlan0", interface_state="disconnected"
            ),
            [],
        )
    )

    with pytest.raises(RuntimeError):
        await wifi.scan_environment()
