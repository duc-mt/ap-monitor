"""
Tests for the Linux WiFi adapter. Every case mocks `asyncio.create_subprocess_exec`
with real captured-shape nmcli/iw output, the same convention test_pinger.py
uses for `ping` - no real network device or root privileges needed.
"""

from __future__ import annotations

import asyncio

import pytest

from app.monitoring.wifi.linux import LinuxWifiAdapter

NMCLI_DEVICE_STATUS = (
    "wlan0:wifi:connected\neth0:ethernet:connected\nlo:loopback:unmanaged\n"
)
NMCLI_SHOW_CONNECTED = (
    "GENERAL.STATE:100 (connected)\n"
    "IP4.ADDRESS[1]:192.168.1.42/24\n"
    "IP4.GATEWAY:192.168.1.1\n"
    "IP4.DNS[1]:1.1.1.1\n"
    "IP4.DNS[2]:8.8.8.8\n"
    "IP6.ADDRESS[1]:fe80::abcd:1234:5678:9abc/64\n"
)
NMCLI_WIFI_LIST = (
    "yes:MyHomeWifi:AA\\:BB\\:CC\\:DD\\:EE\\:FF:36:5180 MHz:72\n"
    "no:Neighbor:11\\:22\\:33\\:44\\:55\\:66:6:2437 MHz:40\n"
)
IW_LINK = (
    "Connected to aa:bb:cc:dd:ee:ff (on wlan0)\n"
    "\tSSID: MyHomeWifi\n"
    "\tfreq: 5180\n"
    "\tsignal: -55 dBm\n"
    "\ttx bitrate: 866.7 MBit/s VHT-MCS 9 80MHz short GI\n"
    "\trx bitrate: 780.0 MBit/s VHT-MCS 8 80MHz\n"
)
IW_SURVEY = (
    "Survey data from wlan0\n"
    "\tfrequency:\t\t\t2412 MHz\n"
    "\tnoise:\t\t\t\t-89 dBm\n"
    "Survey data from wlan0\n"
    "\tfrequency:\t\t\t5180 MHz [in use]\n"
    "\tnoise:\t\t\t\t-92 dBm\n"
)


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


def _responder(table: dict):
    async def fake_exec(*cmd, **kwargs):
        if cmd not in table:
            raise AssertionError(f"Unexpected command: {cmd}")
        return FakeProc(table[cmd])

    return fake_exec


HAPPY_PATH_RESPONSES = {
    ("nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"): NMCLI_DEVICE_STATUS,
    (
        "nmcli",
        "-t",
        "-f",
        "GENERAL.STATE,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS,IP6.ADDRESS",
        "device",
        "show",
        "wlan0",
    ): NMCLI_SHOW_CONNECTED,
    (
        "nmcli",
        "-t",
        "-f",
        "active,ssid,bssid,chan,freq,signal",
        "dev",
        "wifi",
        "list",
        "ifname",
        "wlan0",
        "--rescan",
        "no",
    ): NMCLI_WIFI_LIST,
    ("iw", "dev", "wlan0", "link"): IW_LINK,
    ("iw", "dev", "wlan0", "survey", "dump"): IW_SURVEY,
}


@pytest.mark.asyncio
async def test_list_interfaces_filters_to_wifi_devices_only(monkeypatch):
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", _responder(HAPPY_PATH_RESPONSES)
    )
    interfaces = await LinuxWifiAdapter().list_interfaces()
    assert [i.name for i in interfaces] == ["wlan0"]
    assert interfaces[0].state == "connected"
    assert interfaces[0].is_active is True


@pytest.mark.asyncio
async def test_get_active_interface_returns_connected_device(monkeypatch):
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", _responder(HAPPY_PATH_RESPONSES)
    )
    assert await LinuxWifiAdapter().get_active_interface() == "wlan0"


@pytest.mark.asyncio
async def test_get_metrics_combines_nmcli_and_iw_correctly(monkeypatch):
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", _responder(HAPPY_PATH_RESPONSES)
    )
    m = await LinuxWifiAdapter().get_metrics("wlan0")

    assert m.ssid == "MyHomeWifi"
    assert m.bssid == "AA:BB:CC:DD:EE:FF"  # nmcli's '\:' escaping correctly undone
    assert m.channel == 36
    assert m.frequency_mhz == 5180
    assert m.band == "5GHz"
    assert m.signal_pct == 72
    assert m.rssi_dbm == -55
    assert m.tx_bitrate_mbps == 866.7
    assert m.rx_bitrate_mbps == 780.0
    assert m.mcs_index == 9
    assert m.phy_mode == "802.11ac"
    assert m.channel_width_mhz == 80
    # Must match the [in use] survey entry (5180 MHz), not the other one.
    assert m.noise_floor_dbm == -92
    assert m.snr_db == -55 - (-92)
    assert m.ipv4_addresses == ["192.168.1.42"]
    assert m.ipv6_addresses == ["fe80::abcd:1234:5678:9abc"]
    assert m.gateway == "192.168.1.1"
    assert m.dns_servers == ["1.1.1.1", "8.8.8.8"]


@pytest.mark.asyncio
async def test_disconnected_interface_reports_none_not_zero(monkeypatch):
    """The spec is explicit: unavailable must never become 0 or an empty
    default - a disconnected interface should read as None throughout, not
    as a fabricated 0 dBm / 0% reading."""
    responses = {
        (
            "nmcli",
            "-t",
            "-f",
            "GENERAL.STATE,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS,IP6.ADDRESS",
            "device",
            "show",
            "wlan0",
        ): "GENERAL.STATE:20 (disconnected)\n",
        (
            "nmcli",
            "-t",
            "-f",
            "active,ssid,bssid,chan,freq,signal",
            "dev",
            "wifi",
            "list",
            "ifname",
            "wlan0",
            "--rescan",
            "no",
        ): "",
        ("iw", "dev", "wlan0", "link"): "Not connected.\n",
        ("iw", "dev", "wlan0", "survey", "dump"): "",
    }
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _responder(responses))
    m = await LinuxWifiAdapter().get_metrics("wlan0")

    assert m.interface_state == "disconnected"
    assert m.ssid is None and m.bssid is None
    assert m.rssi_dbm is None and m.noise_floor_dbm is None and m.snr_db is None
    assert m.ipv4_addresses is None and m.gateway is None


@pytest.mark.asyncio
async def test_missing_iw_binary_degrades_gracefully(monkeypatch):
    """`iw` missing (FileNotFoundError) should only blank out the fields iw
    alone provides - nmcli-sourced fields must still populate."""

    async def fake_exec(*cmd, **kwargs):
        if cmd[0] == "iw":
            raise FileNotFoundError("iw: command not found")
        if "show" in cmd:
            return FakeProc("GENERAL.STATE:100 (connected)\n")
        return FakeProc("yes:MyWifi:AA\\:BB\\:CC\\:DD\\:EE\\:FF:6:2437 MHz:80\n")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    m = await LinuxWifiAdapter().get_metrics("wlan0")

    assert m.ssid == "MyWifi"
    assert m.channel == 6
    assert m.band == "2.4GHz"
    assert m.rssi_dbm is None
    assert m.mcs_index is None
    assert m.channel_width_mhz is None


@pytest.mark.asyncio
async def test_missing_noise_floor_leaves_snr_none(monkeypatch):
    """Most consumer WiFi drivers don't report noise via `iw survey dump` -
    SNR must stay None rather than being estimated, per the spec."""
    responses = dict(HAPPY_PATH_RESPONSES)
    responses[("iw", "dev", "wlan0", "survey", "dump")] = ""  # driver reports nothing
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _responder(responses))
    m = await LinuxWifiAdapter().get_metrics("wlan0")

    assert m.rssi_dbm == -55  # still available from `iw link`
    assert m.noise_floor_dbm is None
    assert m.snr_db is None


IW_SCAN_SAMPLE = """BSS aa:bb:cc:dd:ee:ff(on wlan0)
	freq: 2437
	capability: ESS Privacy ShortSlotTime (0x0411)
	signal: -45.00 dBm
	SSID: NeighborNet1
	DS Parameter set: channel 6
	RSN:	 * Version: 1
	HT capabilities:
		Capabilities: 0x1234
	HT operation:
		 * primary channel: 6
BSS 11:22:33:44:55:66(on wlan0)
	freq: 5180
	capability: ESS ShortSlotTime (0x0401)
	signal: -60.00 dBm
	SSID: OpenGuestNet
	VHT capabilities:
		VHT Capabilities (0x0f8059b2)
	VHT operation:
		 * channel width: 80MHz
"""


@pytest.mark.asyncio
async def test_scan_neighbors_parses_multiple_bss_blocks(monkeypatch):
    async def fake_exec(*cmd, **kwargs):
        assert cmd[:3] == ("iw", "dev", "wlan0")
        return FakeProc(IW_SCAN_SAMPLE)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    neighbors = await LinuxWifiAdapter().scan_neighbors("wlan0")

    assert len(neighbors) == 2
    assert neighbors[0].ssid == "NeighborNet1"
    assert neighbors[0].bssid == "AA:BB:CC:DD:EE:FF"
    assert neighbors[0].channel == 6
    assert neighbors[0].phy_mode == "802.11n"
    assert neighbors[0].security == "WPA2/WPA3"
    assert neighbors[1].ssid == "OpenGuestNet"
    assert neighbors[1].channel_width_mhz == 80
    assert neighbors[1].security == "Open"


@pytest.mark.asyncio
async def test_scan_neighbors_falls_back_to_dump_without_scan_privilege(monkeypatch):
    """`iw scan` (active) failing (e.g. no CAP_NET_ADMIN) should fall back
    to `iw scan dump` (passive, cached results) rather than giving up."""
    calls = []

    async def fake_exec(*cmd, **kwargs):
        calls.append(cmd)
        if cmd[-1] == "scan":
            return FakeProc("", returncode=1)  # permission denied
        return FakeProc(IW_SCAN_SAMPLE)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    neighbors = await LinuxWifiAdapter().scan_neighbors("wlan0")

    assert len(neighbors) == 2
    assert calls[0][-1] == "scan"
    assert calls[1][-2:] == ("scan", "dump")


@pytest.mark.asyncio
async def test_scan_neighbors_returns_empty_list_when_both_fail(monkeypatch):
    async def fake_exec(*cmd, **kwargs):
        return FakeProc("", returncode=1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    neighbors = await LinuxWifiAdapter().scan_neighbors("wlan0")
    assert neighbors == []


@pytest.mark.asyncio
async def test_get_metrics_never_triggers_a_scan(monkeypatch):
    """Regression guard for the spec's "normal monitoring must not scan
    surrounding networks" rule. get_metrics() runs every poll (and every
    500ms in walk-test mode), so it must never issue an active `iw scan`,
    and its `nmcli dev wifi list` must carry an explicit `--rescan no` -
    nmcli's default (auto) would request a fresh scan whenever the last
    one is >30s old."""
    executed = []

    async def recording_exec(*cmd, **kwargs):
        executed.append(cmd)
        return FakeProc(HAPPY_PATH_RESPONSES[cmd])

    monkeypatch.setattr(asyncio, "create_subprocess_exec", recording_exec)
    await LinuxWifiAdapter().get_metrics("wlan0")

    assert executed, "expected get_metrics to run at least one command"
    for cmd in executed:
        if cmd[0] == "iw":
            assert "scan" not in cmd, f"get_metrics ran an iw scan: {cmd}"
        assert cmd[0] != "system_profiler"
        if cmd[0] == "nmcli" and "wifi" in cmd and "list" in cmd:
            i = cmd.index("--rescan")
            assert cmd[i + 1] == "no", (
                f"nmcli wifi list must pass --rescan no, got: {cmd}"
            )
