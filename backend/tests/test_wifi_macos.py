"""
==============================================================================
Module Name:   test_wifi_macos.py
Description:   Source module test_wifi_macos.py.
Author:        Mai Tan Duc <ducmai.network@gmail.com>
Created:       2026-10-10
Version:       1.0.0
License:       MIT
==============================================================================
Usage:         python3 test_wifi_macos.py [options]
Notes:         Requires Python 3.8+
==============================================================================
"""

from __future__ import annotations

import asyncio
import builtins
import sys
import types

import pytest

MODULE_UNDER_TEST = "app.monitoring.wifi.macos"


def _install_fake_corewlan(monkeypatch, *, powered_on=True, running=True):
    """Builds and registers a fake CoreWLAN module in sys.modules for the
    duration of one test, then lets monkeypatch's own teardown remove it."""
    # The constants carry the `k` prefix because that is how the real pyobjc
    # CoreWLAN module exports them (verified against the installed package's
    # _metadata.py). An earlier version of this fake used the un-prefixed
    # names, which matched the code under test but not reality - so every
    # test passed while the real adapter reported every interface as
    # "unknown".
    fake = types.ModuleType("CoreWLAN")

    fake.kCWInterfaceStateInactive = 0
    fake.kCWInterfaceStateScanning = 1
    fake.kCWInterfaceStateAuthenticating = 2
    fake.kCWInterfaceStateAssociating = 3
    fake.kCWInterfaceStateRunning = 4

    fake.kCWPHYMode11a = 1
    fake.kCWPHYMode11b = 2
    fake.kCWPHYMode11g = 3
    fake.kCWPHYMode11n = 4
    fake.kCWPHYMode11ac = 5
    fake.kCWPHYMode11ax = 6

    fake.kCWChannelWidth20MHz = 1
    fake.kCWChannelWidth40MHz = 2
    fake.kCWChannelWidth80MHz = 3
    fake.kCWChannelWidth160MHz = 4

    fake.kCWChannelBand2GHz = 1
    fake.kCWChannelBand5GHz = 2
    fake.kCWChannelBand6GHz = 3

    class FakeChannel:
        def channelNumber(self):
            return 149

        def channelWidth(self):
            return fake.kCWChannelWidth80MHz

        def channelBand(self):
            return fake.kCWChannelBand5GHz

    class FakeInterface:
        def interfaceName(self):
            return "en0"

        def powerOn(self):
            return powered_on

        def interfaceState(self):
            return (
                fake.kCWInterfaceStateRunning
                if running
                else fake.kCWInterfaceStateInactive
            )

        def ssid(self):
            return "MyMacWifi"

        def bssid(self):
            return "de:ad:be:ef:00:01"

        def rssiValue(self):
            return -48

        def noiseMeasurement(self):
            return -90

        def transmitRate(self):
            return 866.7

        def activePHYMode(self):
            return fake.kCWPHYMode11ac

        def wlanChannel(self):
            return FakeChannel()

    class FakeClient:
        def interfaceNames(self):
            return ["en0"]

        def interface(self):
            return FakeInterface()

        def interfaceWithName_(self, name):
            return FakeInterface() if name == "en0" else None

    class FakeCWWiFiClient:
        @staticmethod
        def sharedWiFiClient():
            return FakeClient()

    fake.CWWiFiClient = FakeCWWiFiClient
    monkeypatch.setitem(sys.modules, "CoreWLAN", fake)
    return fake


class FakeProc:
    def __init__(self, out: str, returncode: int = 0):
        self._out = out
        self.returncode = returncode

    async def communicate(self):
        return self._out.encode(), b""

    def kill(self):
        pass

    async def wait(self):
        pass


def _ip_info_responder(ip="10.0.1.55\n", gw="gateway: 10.0.1.1\n", dns=""):
    async def fake_exec(*cmd, **kwargs):
        if cmd[0] == "ipconfig":
            return FakeProc(ip)
        if cmd[0] == "route":
            return FakeProc(gw)
        if cmd[0] == "scutil":
            return FakeProc(dns)
        if cmd[0].endswith("airport"):
            raise AssertionError(
                "airport -I should not be called when CoreWLAN succeeds"
            )
        raise AssertionError(f"Unexpected command: {cmd}")

    return fake_exec


@pytest.mark.asyncio
async def test_corewlan_happy_path_maps_every_enum_correctly(monkeypatch):
    _install_fake_corewlan(monkeypatch)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _ip_info_responder())
    sys.modules.pop(MODULE_UNDER_TEST, None)
    from app.monitoring.wifi.macos import MacOSWifiAdapter

    m = await MacOSWifiAdapter().get_metrics("en0")

    assert m.interface_state == "connected"
    assert m.ssid == "MyMacWifi"
    assert m.bssid == "de:ad:be:ef:00:01"
    assert m.rssi_dbm == -48
    assert m.noise_floor_dbm == -90
    assert m.snr_db == -48 - (-90)
    assert m.tx_bitrate_mbps == 866.7
    assert m.phy_mode == "802.11ac"
    assert m.channel == 149
    assert m.channel_width_mhz == 80
    assert m.band == "5GHz"
    assert (
        m.mcs_index is None
    )  # CoreWLAN has no MCS accessor - must stay None, not guessed
    assert m.ipv4_addresses == ["10.0.1.55"]
    assert m.gateway == "10.0.1.1"


@pytest.mark.asyncio
async def test_powered_off_radio_reports_disabled_not_fabricated_metrics(monkeypatch):
    _install_fake_corewlan(monkeypatch, powered_on=False)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _ip_info_responder())
    sys.modules.pop(MODULE_UNDER_TEST, None)
    from app.monitoring.wifi.macos import MacOSWifiAdapter

    m = await MacOSWifiAdapter().get_metrics("en0")
    assert m.interface_state == "disabled"
    assert m.rssi_dbm is None and m.ssid is None


@pytest.mark.asyncio
async def test_not_associated_does_not_report_zero_rssi(monkeypatch):
    """rssiValue()/noiseMeasurement() are plain (non-Optional) NSInteger
    properties that return 0 when there's no association - the adapter must
    recognize 'not running' and leave these None rather than pass 0 through."""
    _install_fake_corewlan(monkeypatch, powered_on=True, running=False)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _ip_info_responder())
    sys.modules.pop(MODULE_UNDER_TEST, None)
    from app.monitoring.wifi.macos import MacOSWifiAdapter

    m = await MacOSWifiAdapter().get_metrics("en0")
    assert m.interface_state != "connected"
    assert m.rssi_dbm is None
    assert m.noise_floor_dbm is None


@pytest.mark.asyncio
async def test_airport_fallback_used_when_corewlan_unimportable(monkeypatch):
    """Simulates pyobjc not being installed: only the CoreWLAN import itself
    fails, everything else in the interpreter imports normally."""
    monkeypatch.delitem(sys.modules, "CoreWLAN", raising=False)
    real_import = builtins.__import__

    def blocking_import(name, *args, **kwargs):
        if name == "CoreWLAN":
            raise ImportError("No module named 'CoreWLAN'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocking_import)

    airport_output = (
        "     agrCtlRSSI: -58\n"
        "    agrCtlNoise: -91\n"
        "          state: running\n"
        "     lastTxRate: 400\n"
        "          BSSID: 12:34:56:78:9a:bc\n"
        "           SSID: AirportFallbackNet\n"
        "            MCS: 7\n"
        "        channel: 44,80\n"
    )

    async def fake_exec(*cmd, **kwargs):
        if cmd[0].endswith("airport"):
            return FakeProc(airport_output)
        return FakeProc("")  # ipconfig/route/scutil: nothing to report

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    sys.modules.pop(MODULE_UNDER_TEST, None)
    from app.monitoring.wifi.macos import MacOSWifiAdapter

    m = await MacOSWifiAdapter().get_metrics("en0")

    assert m.ssid == "AirportFallbackNet"
    assert m.bssid == "12:34:56:78:9a:bc"
    assert m.rssi_dbm == -58
    assert m.noise_floor_dbm == -91
    assert m.snr_db == -58 - (-91)
    assert m.mcs_index == 7  # only available via this fallback, never via CoreWLAN
    assert m.channel == 44
    assert m.channel_width_mhz == 80
    assert m.tx_bitrate_mbps == 400.0


AIRPORT_DATA_SAMPLE = """Wi-Fi:

      Interfaces:
        en0:
          Current Network Information:
            MyHomeWifi:
              PHY Mode: 802.11ac
              Channel: 36 (80MHz)
              Security: WPA2 Personal
              Signal / Noise: -45 dBm / -92 dBm
          Other Local Wi-Fi Networks:
            NeighborNet1:
              PHY Mode: 802.11n
              Channel: 6
              Network Type: Infrastructure
              Security: WPA2 Personal
              Signal / Noise: -70 dBm / -92 dBm
            NeighborNet2:
              PHY Mode: 802.11ac
              Channel: 36 (80MHz)
              Network Type: Infrastructure
              Security: WPA3 Personal
              Signal / Noise: -65 dBm / -92 dBm
"""


@pytest.mark.asyncio
async def test_scan_neighbors_uses_system_profiler_and_excludes_current_network(
    monkeypatch,
):
    async def fake_exec(*cmd, **kwargs):
        assert cmd == ("system_profiler", "SPAirPortDataType")
        return FakeProc(AIRPORT_DATA_SAMPLE)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    sys.modules.pop(MODULE_UNDER_TEST, None)
    from app.monitoring.wifi.macos import MacOSWifiAdapter

    neighbors = await MacOSWifiAdapter().scan_neighbors("en0")

    assert len(neighbors) == 2  # "MyHomeWifi" (the current network) must not appear
    assert {n.ssid for n in neighbors} == {"NeighborNet1", "NeighborNet2"}
    assert all(
        n.bssid is None for n in neighbors
    )  # never available from this data source
    n2 = next(n for n in neighbors if n.ssid == "NeighborNet2")
    assert n2.channel == 36
    assert n2.channel_width_mhz == 80


@pytest.mark.asyncio
async def test_scan_neighbors_returns_empty_list_when_command_fails(monkeypatch):
    async def fake_exec(*cmd, **kwargs):
        return FakeProc("", returncode=1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    sys.modules.pop(MODULE_UNDER_TEST, None)
    from app.monitoring.wifi.macos import MacOSWifiAdapter

    assert await MacOSWifiAdapter().scan_neighbors("en0") == []


@pytest.mark.asyncio
async def test_get_metrics_never_runs_system_profiler_on_either_path(monkeypatch):
    """Regression guard for the spec's hardest macOS rule: system_profiler
    SPAirPortDataType forces an active scan and can block for seconds, so
    it may only ever run from the explicit on-demand scan_neighbors(), never
    from the per-tick get_metrics() - on the CoreWLAN path OR the airport
    -I fallback path."""
    executed = []

    async def recording_exec(*cmd, **kwargs):
        executed.append(cmd)
        if cmd[0].endswith("airport"):
            return FakeProc(
                "     agrCtlRSSI: -58\n          state: running\n           SSID: X\n"
            )
        return FakeProc("")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", recording_exec)

    # CoreWLAN path
    _install_fake_corewlan(monkeypatch)
    sys.modules.pop(MODULE_UNDER_TEST, None)
    from app.monitoring.wifi.macos import MacOSWifiAdapter

    await MacOSWifiAdapter().get_metrics("en0")

    # airport -I fallback path (pyobjc unavailable)
    monkeypatch.delitem(sys.modules, "CoreWLAN", raising=False)
    real_import = builtins.__import__

    def blocking_import(name, *args, **kwargs):
        if name == "CoreWLAN":
            raise ImportError("No module named 'CoreWLAN'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocking_import)
    sys.modules.pop(MODULE_UNDER_TEST, None)
    from app.monitoring.wifi.macos import MacOSWifiAdapter as FallbackAdapter

    await FallbackAdapter().get_metrics("en0")

    assert executed, "expected at least the ip-info commands to run"
    assert all(cmd[0] != "system_profiler" for cmd in executed), executed
