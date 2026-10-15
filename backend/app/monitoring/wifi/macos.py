"""
==============================================================================
Module Name:   macos.py
Description:   Source module macos.py.
Author:        Mai Tan Duc <ducmai.network@gmail.com>
Created:       2026-10-10
Version:       1.0.0
License:       MIT
==============================================================================
Usage:         python3 macos.py [options]
Notes:         Requires Python 3.8+
==============================================================================
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone

UTC = timezone.utc

from app.models.wifi_scan import NeighborNetwork
from app.monitoring.wifi.base import WifiAdapter
from app.monitoring.wifi.models import (
    WifiInterfaceInfo,
    WifiMetrics,
    band_from_frequency,
)

logger = logging.getLogger("ap_monitor.wifi.macos")

_TIMEOUT_SECONDS = 2.0
_IP_INFO_CACHE_TTL = 5.0  # seconds
_ip_info_cache: dict[str, tuple[float, list[str] | None, str | None, list[str] | None]] = {}


def reset_ip_cache() -> None:
    """Test isolation hook."""
    _ip_info_cache.clear()


_AIRPORT_BIN = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"

# CWInterfaceState -> our normalized vocabulary. Values match CoreWLAN's
# documented enum ordering (CWInterfaceStateInactive = 0, ... Running = 4);
# named via getattr against the imported module rather than hardcoded ints,
# since relying on undocumented raw values across macOS releases is exactly
# the kind of thing that silently breaks on an OS update.
_STATE_NAME_MAP = {
    "CWInterfaceStateInactive": "disabled",
    "CWInterfaceStateScanning": "scanning",
    "CWInterfaceStateAuthenticating": "connecting",
    "CWInterfaceStateAssociating": "connecting",
    "CWInterfaceStateRunning": "connected",
}

_PHY_MODE_NAME_MAP = {
    "CWPHYMode11a": "802.11a",
    "CWPHYMode11b": "802.11b",
    "CWPHYMode11g": "802.11g",
    "CWPHYMode11n": "802.11n",
    "CWPHYMode11ac": "802.11ac",
    "CWPHYMode11ax": "802.11ax",
}

_CHANNEL_WIDTH_NAME_MAP = {
    "CWChannelWidth20MHz": 20,
    "CWChannelWidth40MHz": 40,
    "CWChannelWidth80MHz": 80,
    "CWChannelWidth160MHz": 160,
}

_CHANNEL_BAND_NAME_MAP = {
    "CWChannelBand2GHz": "2.4GHz",
    "CWChannelBand5GHz": "5GHz",
    "CWChannelBand6GHz": "6GHz",
}


def _load_corewlan():
    """Imported lazily (not at module scope) so this whole module can still
    be *imported* on any platform without pyobjc installed - only calling
    into it requires macOS + pyobjc. Also makes the pyobjc dependency easy
    to mock out in tests via sys.modules, the same way test_pinger.py mocks
    subprocess output instead of needing a real network."""
    import CoreWLAN  # type: ignore

    return CoreWLAN


async def _run(cmd: list[str], timeout: float = _TIMEOUT_SECONDS) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError):
        return None
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return None
    if proc.returncode != 0:
        return None
    return stdout.decode("utf-8", errors="replace")


def _enum_name(corewlan, value, table: dict):
    """Map a CoreWLAN enum int back to a value from the table above (a name
    string for state/PHY-mode/band, an int for channel width), resolving
    each table key against the live module so we never hardcode raw ints."""
    for name, mapped in table.items():
        # pyobjc exports CoreWLAN's enum constants under Apple's C names, which
        # carry a `k` prefix (kCWInterfaceStateRunning, kCWPHYMode11ac, ...).
        # The tables below list them without it, as in Apple's docs.
        constant = f"k{name}"
        if hasattr(corewlan, constant) and getattr(corewlan, constant) == value:
            return mapped
    return None


class MacOSWifiAdapter(WifiAdapter):
    async def list_interfaces(self) -> list[WifiInterfaceInfo]:
        try:
            corewlan = _load_corewlan()
        except ImportError:
            logger.warning(
                "pyobjc/CoreWLAN not available - falling back to `airport -I` (no interface enumeration in that path; assuming en0)."
            )
            return [WifiInterfaceInfo(name="en0", state="unknown", is_active=True)]

        client = corewlan.CWWiFiClient.sharedWiFiClient()
        names = list(client.interfaceNames() or [])
        active = await self.get_active_interface()
        return [WifiInterfaceInfo(name=name, state="unknown", is_active=(name == active)) for name in names]

    async def get_active_interface(self) -> str | None:
        try:
            corewlan = _load_corewlan()
        except ImportError:
            return "en0"  # airport -I has no concept of "which interface"; en0 is the historical default Wi-Fi adapter name.

        client = corewlan.CWWiFiClient.sharedWiFiClient()
        iface = client.interface()
        if iface is None:
            names = list(client.interfaceNames() or [])
            return names[0] if names else None
        return iface.interfaceName()

    async def get_metrics(self, interface: str) -> WifiMetrics:
        metrics = WifiMetrics(
            timestamp=datetime.now(UTC).isoformat(),
            interface=interface,
            interface_state="unknown",
        )
        try:
            corewlan = _load_corewlan()
        except ImportError:
            await self._apply_airport_fallback(metrics)
        else:
            self._apply_corewlan(metrics, corewlan, interface)

        await self._apply_ip_info(metrics, interface)
        metrics.band = metrics.band or band_from_frequency(metrics.frequency_mhz)
        metrics.compute_snr()
        if metrics.interface_state == "connected" and metrics.ssid is None and metrics.bssid is None:
            # Associated (RSSI/channel read fine) yet both identity fields are
            # blank: macOS's Location Services gate, not an unassociated
            # radio. Flag it so the UI can say so instead of showing nothing.
            metrics.issue = "location_permission"
        return metrics

    async def scan_neighbors(self, interface: str) -> list[NeighborNetwork]:
        # The one and only place `system_profiler SPAirPortDataType` is
        # allowed to run - it forces an active scan and can block for
        # several seconds, which is exactly why it's banned from the
        # background monitoring/walk-test loops (see module docstring) but
        # is fine for an explicit, user-triggered action like this one.
        out = await _run(["system_profiler", "SPAirPortDataType"], timeout=15.0)
        if out is None:
            return []
        return _parse_airport_data(out)

    def _apply_corewlan(self, metrics: WifiMetrics, corewlan, interface: str) -> None:
        client = corewlan.CWWiFiClient.sharedWiFiClient()
        iface = client.interfaceWithName_(interface) if hasattr(client, "interfaceWithName_") else client.interface()
        if iface is None:
            metrics.interface_state = "unavailable"
            return

        if iface.powerOn() is False:
            metrics.interface_state = "disabled"
            return

        state_val = iface.interfaceState()
        metrics.interface_state = _enum_name(corewlan, state_val, _STATE_NAME_MAP) or "unknown"
        is_running = metrics.interface_state == "connected"

        # ssid()/bssid() are the two fields Sequoia's Location Services gate -
        # read them regardless of `is_running`, since a location-permission
        # None here is a different failure mode than "not associated" and
        # both are surfaced identically to the caller as None either way.
        metrics.ssid = iface.ssid()
        metrics.bssid = iface.bssid()

        # rssiValue()/noiseMeasurement()/transmitRate() are typed as plain
        # NSInteger/double in CoreWLAN, not Optional - they return 0 when
        # there's no active association, which is indistinguishable from a
        # genuine (if wildly unlikely) 0 dBm/0 Mbps reading. Only trust them
        # while the interface is actually associated.
        if is_running:
            metrics.rssi_dbm = int(iface.rssiValue())
            metrics.noise_floor_dbm = int(iface.noiseMeasurement())
            metrics.tx_bitrate_mbps = float(iface.transmitRate())

            phy_val = iface.activePHYMode()
            metrics.phy_mode = _enum_name(corewlan, phy_val, _PHY_MODE_NAME_MAP)

            channel = iface.wlanChannel()
            if channel is not None:
                metrics.channel = int(channel.channelNumber())
                metrics.channel_width_mhz = _enum_name(corewlan, channel.channelWidth(), _CHANNEL_WIDTH_NAME_MAP)
                metrics.band = _enum_name(corewlan, channel.channelBand(), _CHANNEL_BAND_NAME_MAP)

        # mcs_index has no CoreWLAN accessor - left as None deliberately.

    async def _apply_airport_fallback(self, metrics: WifiMetrics) -> None:
        out = await _run([_AIRPORT_BIN, "-I"])
        if out is None:
            metrics.interface_state = "unavailable"
            return
        fields = {}
        for line in out.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.strip().partition(":")
            fields[key.strip()] = value.strip()

        state = fields.get("state")
        metrics.interface_state = "connected" if state == "running" else ("disabled" if state else "unknown")
        metrics.ssid = fields.get("SSID") or None
        metrics.bssid = fields.get("BSSID") or None
        if "agrCtlRSSI" in fields:
            metrics.rssi_dbm = int(fields["agrCtlRSSI"])
        if "agrCtlNoise" in fields:
            metrics.noise_floor_dbm = int(fields["agrCtlNoise"])
        if "lastTxRate" in fields:
            metrics.tx_bitrate_mbps = float(fields["lastTxRate"])
        if "MCS" in fields and fields["MCS"].isdigit():
            metrics.mcs_index = int(fields["MCS"])
        channel_field = fields.get("channel", "")
        # e.g. "36,80" (channel 36, 80MHz wide) or plain "6"
        chan_match = re.match(r"(\d+)(?:,(\d+))?", channel_field)
        if chan_match:
            metrics.channel = int(chan_match.group(1))
            if chan_match.group(2):
                metrics.channel_width_mhz = int(chan_match.group(2))

    async def _apply_ip_info(self, metrics: WifiMetrics, interface: str) -> None:
        now_mono = time.monotonic()
        cached = _ip_info_cache.get(interface)
        if cached is not None and (now_mono - cached[0]) < _IP_INFO_CACHE_TTL:
            metrics.ipv4_addresses = cached[1]
            metrics.gateway = cached[2]
            metrics.dns_servers = cached[3]
            return

        ip_out, gw_out, dns_out = await asyncio.gather(
            _run(["ipconfig", "getifaddr", interface]),
            _run(["route", "-n", "get", "default"]),
            _run(["scutil", "--dns"]),
        )
        if ip_out:
            metrics.ipv4_addresses = [ip_out.strip()]
        if gw_out:
            m = re.search(r"gateway:\s*(\S+)", gw_out)
            if m:
                metrics.gateway = m.group(1)
        if dns_out:
            # Best-effort: take nameservers from the first resolver block.
            # /etc/resolv.conf-based lookups are known to be unreliable on
            # modern macOS (mDNSResponder doesn't always keep it in sync),
            # which is why this parses `scutil --dns` instead - still only
            # best-effort, since a VPN or split-DNS config can make the
            # "first" block not the one actually in use for the WiFi
            # interface specifically. Leave None rather than guess further.
            servers = re.findall(r"nameserver\[\d+\]\s*:\s*(\S+)", dns_out)
            if servers:
                # Only the servers listed before the first blank line
                # (first resolver entry) to avoid mixing in VPN/other
                # interfaces' resolvers.
                first_block = dns_out.split("\n\n", 1)[0]
                first_servers = re.findall(r"nameserver\[\d+\]\s*:\s*(\S+)", first_block)
                metrics.dns_servers = first_servers or servers

        _ip_info_cache[interface] = (
            now_mono,
            metrics.ipv4_addresses,
            metrics.gateway,
            metrics.dns_servers,
        )


def _parse_airport_data(out: str) -> list[NeighborNetwork]:
    """
    Parses the "Other Local Wi-Fi Networks:" block from
    `system_profiler SPAirPortDataType`'s indentation-based text output.
    Each neighbor is a sub-block keyed by SSID, e.g.:

        Other Local Wi-Fi Networks:
            NeighborNet1:
              PHY Mode: 802.11n
              Channel: 6
              Network Type: Infrastructure
              Security: WPA2 Personal
              Signal / Noise: -70 dBm / -92 dBm

    Known, permanent limitation of this data source (not a parsing gap):
    it never includes a BSSID for neighboring networks, only for the
    currently-connected one - see NeighborNetwork.bssid's docstring.
    """
    lines = out.splitlines()
    header_indent: int | None = None
    header_idx: int | None = None
    for i, line in enumerate(lines):
        if line.strip() == "Other Local Wi-Fi Networks:":
            header_indent = len(line) - len(line.lstrip(" "))
            header_idx = i
            break
    if header_idx is None:
        return []

    neighbors: list[NeighborNetwork] = []
    current: dict | None = None
    current_indent: int | None = None

    for line in lines[header_idx + 1 :]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= header_indent:
            break  # end of the "Other Local Wi-Fi Networks" section entirely

        stripped = line.strip()
        if ":" in stripped and stripped.endswith(":") and (current_indent is None or indent <= current_indent):
            # A new SSID key, one level under the section header.
            if current is not None:
                neighbors.append(_dict_to_neighbor(current))
            current = {"ssid": stripped[:-1].strip()}
            current_indent = indent
            continue

        if current is not None and ":" in stripped:
            key, _, value = stripped.partition(":")
            current[key.strip()] = value.strip()

    if current is not None:
        neighbors.append(_dict_to_neighbor(current))
    return neighbors


def _dict_to_neighbor(fields: dict) -> NeighborNetwork:
    channel_raw = fields.get("Channel", "")
    # e.g. "36 (80MHz)" or plain "6"
    chan_match = re.match(r"(\d+)(?:\s*\((\d+)MHz\))?", channel_raw)
    channel = int(chan_match.group(1)) if chan_match else None
    channel_width_mhz = int(chan_match.group(2)) if chan_match and chan_match.group(2) else None

    signal_noise = fields.get("Signal / Noise", "")
    signal_match = re.match(r"(-?\d+)\s*dBm", signal_noise)
    rssi = int(signal_match.group(1)) if signal_match else None

    band: str | None
    if channel is not None and channel <= 14:
        band = "2.4GHz"
    elif channel is not None:
        band = "5GHz"  # system_profiler doesn't distinguish 5GHz from 6GHz by channel number alone here
    else:
        band = None

    return NeighborNetwork(
        ssid=fields.get("ssid"),
        bssid=None,  # never available for neighbors from this data source
        phy_mode=fields.get("PHY Mode"),
        channel=channel,
        channel_width_mhz=channel_width_mhz,
        band=band,
        security=fields.get("Security"),
        rssi_dbm=rssi,
    )
