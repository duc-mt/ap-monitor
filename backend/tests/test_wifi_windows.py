"""
Tests for the Windows WiFi adapter's parsing and metric mapping.

No Windows machine is used: the parsers are pure functions over `netsh` /
`ipconfig` text, and the adapter tests replace its subprocess runner. The
sample outputs follow the layout of real English-language Windows 10/11
`netsh wlan show interfaces` / `show networks mode=bssid` / `ipconfig`
output. They confirm our code handles that layout, not that every Windows
build prints exactly this - see the note at the top of
app/monitoring/wifi/windows.py.
"""

from __future__ import annotations

import pytest

from app.monitoring.wifi import windows
from app.monitoring.wifi.windows import (
    WindowsWifiAdapter,
    metrics_from_interface,
    parse_interfaces,
    parse_ipconfig,
    parse_networks,
    rssi_from_quality,
)

CONNECTED = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                   : 7b0c1e52-6c2f-4e55-8d0a-1f2f4b5a6c7d
    Physical address       : 3c:58:c2:11:22:33
    Interface type         : Primary
    State                  : connected
    SSID                   : OfficeNet
    AP BSSID               : AA:BB:CC:DD:EE:01
    Band                   : 5 GHz
    Channel                : 36
    Network type           : Infrastructure
    Radio type             : 802.11ac
    Authentication         : WPA2-Personal
    Cipher                 : CCMP
    Connection mode        : Auto Connect
    Receive rate (Mbps)    : 866.7
    Transmit rate (Mbps)   : 780
    Signal                 : 92%
    Profile                : OfficeNet

    Hosted network status  : Not available
"""

DISCONNECTED = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                   : 7b0c1e52-6c2f-4e55-8d0a-1f2f4b5a6c7d
    Physical address       : 3c:58:c2:11:22:33
    Interface type         : Primary
    State                  : disconnected
"""

TWO_INTERFACES = (
    CONNECTED.replace("There is 1 interface", "There are 2 interfaces")
    + """
    Name                   : Wi-Fi 2
    Description            : USB Wireless Adapter
    GUID                   : 11111111-2222-3333-4444-555555555555
    Physical address       : 00:11:22:33:44:55
    Interface type         : Secondary
    State                  : disconnected
"""
)

# Labels translated to a non-English language: only the *values* and the
# order netsh prints them in are recognizable.
LOCALIZED = """
    Ten                    : Wi-Fi
    Mo ta                  : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                   : 7b0c1e52-6c2f-4e55-8d0a-1f2f4b5a6c7d
    Dia chi vat ly         : 3c:58:c2:11:22:33
    Trang thai             : da ket noi
    Ten mang               : QuanLy
    BSSID cua AP           : aa:bb:cc:dd:ee:02
    Bang tan               : 2.4 GHz
    Kenh                   : 6
    Loai mang              : Co so ha tang
    Loai radio             : 802.11n
    Tin hieu               : 70%
"""

LOCATION_BLOCKED = (
    "Network shell commands need location permission to access WLAN information.\n"
    "Turn on Location services on the Settings app (ms-settings:privacy-location).\n"
)

NETWORKS = """
Interface name : Wi-Fi
There are 3 networks currently visible.

SSID 1 : OfficeNet
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP
    BSSID 1                 : aa:bb:cc:dd:ee:01
         Signal             : 92%
         Radio type         : 802.11ac
         Band               : 5 GHz
         Channel            : 36
         Basic rates (Mbps) : 6 12 24
    BSSID 2                 : aa:bb:cc:dd:ee:02
         Signal             : 40%
         Radio type         : 802.11n
         Band               : 2.4 GHz
         Channel            : 6

SSID 2 :
    Network type            : Infrastructure
    Authentication          : Open
    Encryption              : None
    BSSID 1                 : 11:22:33:44:55:66
         Signal             : 20%
         Radio type         : 802.11n
         Band               : 2.4 GHz
         Channel            : 11
"""

IPCONFIG = """
Windows IP Configuration


Ethernet adapter Ethernet:

   Media State . . . . . . . . . . . : Media disconnected
   Connection-specific DNS Suffix  . :

Wireless LAN adapter Wi-Fi:

   Connection-specific DNS Suffix  . : lan
   Link-local IPv6 Address . . . . . : fe80::1c2d:3e4f:5a6b:7c8d%12
   IPv4 Address. . . . . . . . . . . : 192.168.1.42
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : fe80::1%12
                                       192.168.1.1
"""


def test_rssi_from_quality_follows_microsoft_mapping():
    assert rssi_from_quality(0) == -100
    assert rssi_from_quality(100) == -50
    assert rssi_from_quality(50) == -75
    assert rssi_from_quality(92) == -54
    assert (
        rssi_from_quality(150) == -50
    )  # clamped, never a fabricated value above range


def test_parse_connected_interface():
    (info,) = parse_interfaces(CONNECTED)
    assert info["name"] == "Wi-Fi" and info["state"] == "connected"
    m = metrics_from_interface(info, "Wi-Fi")
    assert m.interface_state == "connected"
    assert m.ssid == "OfficeNet"
    assert m.bssid == "aa:bb:cc:dd:ee:01"  # normalised to lower case
    assert (m.band, m.channel, m.frequency_mhz) == ("5GHz", 36, 5180)
    assert m.phy_mode == "802.11ac"
    assert m.signal_pct == 92 and m.rssi_dbm == -54
    assert m.rx_bitrate_mbps == 866.7 and m.tx_bitrate_mbps == 780.0
    assert (
        m.noise_floor_dbm is None and m.snr_db is None
    )  # not exposed on Windows - never invented


def test_parse_disconnected_interface_has_no_ap_fields():
    (info,) = parse_interfaces(DISCONNECTED)
    m = metrics_from_interface(info, "Wi-Fi")
    assert m.interface_state == "disconnected"
    assert m.ssid is None and m.bssid is None and m.rssi_dbm is None


def test_parse_two_interfaces():
    infos = parse_interfaces(TWO_INTERFACES)
    assert [i["name"] for i in infos] == ["Wi-Fi", "Wi-Fi 2"]
    assert [i["state"] for i in infos] == ["connected", "disconnected"]


def test_localized_output_is_recovered_structurally():
    (info,) = parse_interfaces(LOCALIZED)
    m = metrics_from_interface(info, "Wi-Fi")
    assert m.interface_state == "connected"
    assert m.bssid == "aa:bb:cc:dd:ee:02"
    assert m.ssid == "QuanLy"
    assert (m.band, m.channel) == ("2.4GHz", 6)
    assert m.signal_pct == 70 and m.rssi_dbm == -65
    assert m.phy_mode == "802.11n"


def test_band_falls_back_to_channel_when_netsh_prints_no_band():
    text = CONNECTED.replace("    Band                   : 5 GHz\n", "")
    m = metrics_from_interface(parse_interfaces(text)[0], "Wi-Fi")
    assert m.band == "5GHz" and m.channel == 36


def test_parse_networks_yields_one_entry_per_bssid():
    nets = parse_networks(NETWORKS)
    assert [(n.ssid, n.bssid, n.channel, n.band) for n in nets] == [
        ("OfficeNet", "aa:bb:cc:dd:ee:01", 36, "5GHz"),
        ("OfficeNet", "aa:bb:cc:dd:ee:02", 6, "2.4GHz"),
        (None, "11:22:33:44:55:66", 11, "2.4GHz"),  # hidden SSID stays None, not ""
    ]
    assert (
        nets[0].rssi_dbm == -54
        and nets[0].security == "WPA2-Personal"
        and nets[0].phy_mode == "802.11ac"
    )
    assert nets[2].security == "Open"


def test_parse_ipconfig_picks_the_right_adapter_and_ipv4_gateway():
    assert parse_ipconfig(IPCONFIG, "Wi-Fi") == (["192.168.1.42"], "192.168.1.1")
    assert parse_ipconfig(IPCONFIG, "Ethernet") == (None, None)
    assert parse_ipconfig(IPCONFIG, "Missing") == (None, None)


class _FakeRunner:
    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = []

    async def __call__(self, cmd, timeout=0):
        self.calls.append(cmd)
        return self.outputs.get(cmd[0] if cmd[0] != "netsh" else " ".join(cmd[:4]))


@pytest.mark.asyncio
async def test_adapter_reads_metrics_and_caches_ip_info(monkeypatch):
    runner = _FakeRunner(
        {"netsh wlan show interfaces": CONNECTED, "ipconfig": IPCONFIG}
    )
    monkeypatch.setattr(windows, "_run", runner)
    adapter = WindowsWifiAdapter()

    assert await adapter.get_active_interface() == "Wi-Fi"
    m = await adapter.get_metrics("Wi-Fi")
    assert (
        m.bssid == "aa:bb:cc:dd:ee:01"
        and m.gateway == "192.168.1.1"
        and m.ipv4_addresses == ["192.168.1.42"]
    )

    await adapter.get_metrics("Wi-Fi")
    assert (
        sum(1 for c in runner.calls if c[0] == "ipconfig") == 1
    )  # second read served from the 5s cache


@pytest.mark.asyncio
async def test_active_interface_prefers_connected_then_falls_back_to_first(monkeypatch):
    monkeypatch.setattr(
        windows, "_run", _FakeRunner({"netsh wlan show interfaces": TWO_INTERFACES})
    )
    assert await WindowsWifiAdapter().get_active_interface() == "Wi-Fi"
    monkeypatch.setattr(
        windows, "_run", _FakeRunner({"netsh wlan show interfaces": DISCONNECTED})
    )
    assert await WindowsWifiAdapter().get_active_interface() == "Wi-Fi"


@pytest.mark.asyncio
async def test_location_block_is_reported_not_mistaken_for_no_wifi(monkeypatch):
    monkeypatch.setattr(
        windows, "_run", _FakeRunner({"netsh wlan show interfaces": LOCATION_BLOCKED})
    )
    adapter = WindowsWifiAdapter()
    assert await adapter.get_active_interface() is None
    assert adapter.last_issue == "location_permission"
    m = await adapter.get_metrics("Wi-Fi")
    assert m.interface_state == "unknown" and m.issue == "location_permission"


@pytest.mark.asyncio
async def test_scan_neighbors_returns_bssids(monkeypatch):
    monkeypatch.setattr(
        windows, "_run", _FakeRunner({"netsh wlan show networks": NETWORKS})
    )
    nets = await WindowsWifiAdapter().scan_neighbors("Wi-Fi")
    assert len(nets) == 3 and all(n.bssid for n in nets)


@pytest.mark.asyncio
async def test_scan_neighbors_is_empty_when_location_blocked(monkeypatch):
    monkeypatch.setattr(
        windows, "_run", _FakeRunner({"netsh wlan show networks": LOCATION_BLOCKED})
    )
    assert await WindowsWifiAdapter().scan_neighbors("Wi-Fi") == []


def test_win32_dispatch_selects_the_windows_adapter(monkeypatch):
    from app.monitoring import wifi

    monkeypatch.setattr(wifi.sys, "platform", "win32")
    assert isinstance(wifi._build_adapter(), WindowsWifiAdapter)
