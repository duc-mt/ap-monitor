"""Tests for the 'why is the AP info empty' diagnostics and the tri-state
connection reading that stops an unreadable radio being reported as down."""
from __future__ import annotations

import sys
import types

import pytest

from app.monitoring.wifi import diagnostics
from app.monitoring.wifi.models import WifiMetrics, is_connected


def _m(**kw):
    base = dict(timestamp="t", interface="wlan0", interface_state="connected", ssid="Net", bssid="aa:bb")
    base.update(kw)
    return WifiMetrics(**base)


def test_is_connected_is_tri_state():
    assert is_connected(_m()) is True
    assert is_connected(_m(interface_state="disconnected")) is False
    assert is_connected(_m(interface_state="unavailable")) is False
    assert is_connected(_m(interface_state="unknown")) is None     # could not tell - must not read as "down"


def test_a_complete_reading_has_no_issue():
    assert diagnostics.diagnose(_m()) is None
    assert diagnostics.diagnose(_m(interface_state="disconnected", ssid=None, bssid=None)) is None


def test_connected_without_bssid_is_flagged():
    issue = diagnostics.diagnose(_m(bssid=None))
    assert issue.code == "bssid_unavailable"


def test_an_adapter_supplied_issue_wins():
    assert diagnostics.diagnose(_m(interface_state="unknown", issue="location_permission")).code == "location_permission"


@pytest.mark.parametrize("platform,needle", [("darwin", "Location Services"), ("win32", "Location services")])
def test_location_help_is_platform_specific(monkeypatch, platform, needle):
    monkeypatch.setattr(diagnostics.sys, "platform", platform)
    assert needle in diagnostics.issue_for("location_permission").detail


def test_linux_without_the_tools_says_so(monkeypatch):
    monkeypatch.setattr(diagnostics.sys, "platform", "linux")
    monkeypatch.setattr(diagnostics.shutil, "which", lambda name: None)
    assert diagnostics.no_interface_issue().code == "missing_tools"
    monkeypatch.setattr(diagnostics.shutil, "which", lambda name: "/usr/bin/" + name)
    assert diagnostics.no_interface_issue().code == "no_wifi_interface"


@pytest.mark.asyncio
async def test_macos_adapter_flags_hidden_identity_as_location_permission(monkeypatch):
    from app.monitoring.wifi import macos

    fake = types.ModuleType("CoreWLAN")
    fake.kCWInterfaceStateRunning = 4
    fake.kCWPHYMode11ac = 5
    fake.kCWChannelWidth80MHz = 3
    fake.kCWChannelBand5GHz = 2

    class Chan:
        def channelNumber(self): return 149
        def channelWidth(self): return 3
        def channelBand(self): return 2

    class Iface:
        def interfaceName(self): return "en0"
        def powerOn(self): return True
        def interfaceState(self): return 4
        def ssid(self): return None            # what macOS returns without Location permission
        def bssid(self): return None
        def rssiValue(self): return -52
        def noiseMeasurement(self): return -92
        def transmitRate(self): return 866.0
        def activePHYMode(self): return 5
        def wlanChannel(self): return Chan()

    class Client:
        def interfaceWithName_(self, name): return Iface()
        def interface(self): return Iface()

    class CWWiFiClient:
        @staticmethod
        def sharedWiFiClient(): return Client()

    fake.CWWiFiClient = CWWiFiClient
    monkeypatch.setattr(macos, "_load_corewlan", lambda: fake)

    async def no_ip(self, metrics, interface):
        return None
    monkeypatch.setattr(macos.MacOSWifiAdapter, "_apply_ip_info", no_ip)

    m = await macos.MacOSWifiAdapter().get_metrics("en0")
    assert m.interface_state == "connected" and m.rssi_dbm == -52 and m.channel == 149
    assert m.issue == "location_permission"
    assert diagnostics.diagnose(m).code == "location_permission"
