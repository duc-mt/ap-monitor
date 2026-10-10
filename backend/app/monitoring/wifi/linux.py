"""
Linux WiFi adapter.

Two tools, two different jobs - neither one alone gives the full metric
set the spec asks for:

- `nmcli` gives us interface discovery, connection/IP state, and enough of
  the associated-AP row (SSID/BSSID/channel/frequency/signal%) to identify
  what we're connected to. It does NOT expose RSSI in dBm, noise floor,
  PHY mode, channel width, or MCS index.
- `iw` gives us the RF-layer detail nmcli doesn't: signal in dBm, tx/rx
  bitrate, MCS index, and channel width, parsed out of `iw dev <if> link`.
  Noise floor (needed for a real SNR) comes from `iw dev <if> survey dump`
  when the driver reports it at all - many don't, in which case it and
  the derived SNR both correctly stay None rather than being guessed at.

Both commands run as plain argv lists (no `shell=True`) with a strict
timeout, exactly like `pinger.py`'s subprocess calls. Neither triggers a
scan: `iw ... link`/`survey dump` and `nmcli ... show` all read state
NetworkManager/the kernel already have. `nmcli dev wifi list` is the one
that needs care: its documented default is `--rescan auto`, which REQUESTS
A FRESH SCAN whenever the last one is more than ~30s old - polled every
few seconds (or every 500ms in walk-test mode) that would quietly turn
into repeated active scans while associated, with the off-channel time and
latency spikes the spec's "normal monitoring must not scan surrounding
networks" rule exists to prevent. So it is always invoked with an explicit
`--rescan no`, which reads only NetworkManager's existing scan results.
(An earlier revision of this docstring claimed omitting the flag was
equivalent to "no rescan" - it isn't, which is why this is spelled out.)
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC

from app.models.wifi_scan import NeighborNetwork
from app.monitoring.wifi.base import WifiAdapter
from app.monitoring.wifi.models import (
    WifiInterfaceInfo,
    WifiMetrics,
    band_from_frequency,
    channel_from_frequency,
)

logger = logging.getLogger("ap_monitor.wifi.linux")

_TIMEOUT_SECONDS = 2.0

# NetworkManager's device states -> our normalized InterfaceState vocabulary.
_STATE_MAP = {
    "connected": "connected",
    "connecting": "connecting",
    "disconnected": "disconnected",
    "unavailable": "unavailable",
    "unmanaged": "unknown",
    "deactivating": "disconnected",
}

_MCS_PHY_PREFIX = {
    "HE": "802.11ax",
    "VHT": "802.11ac",
    "HT": "802.11n",
}


async def _run(cmd: list[str], timeout: float = _TIMEOUT_SECONDS) -> str | None:
    """Argv-list subprocess exec with a strict timeout - never `shell=True`.

    Returns None on any failure (binary missing, timeout, non-zero exit)
    rather than raising, so a single unavailable tool degrades one metric
    group instead of aborting the whole snapshot.
    """
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


def _split_nmcli_terse(line: str) -> list[str]:
    """nmcli -t output escapes a literal ':' inside a field as '\\:' (this
    matters for BSSIDs, which are colon-separated themselves) - split on any
    ':' not preceded by a backslash, then unescape."""
    return [p.replace("\\:", ":") for p in re.split(r"(?<!\\):", line)]


async def _list_wifi_devices(interface: str | None = None) -> list[list[str]]:
    fields = "DEVICE,TYPE,STATE"
    out = await _run(["nmcli", "-t", "-f", fields, "device", "status"])
    if out is None:
        return []
    rows = [_split_nmcli_terse(line) for line in out.strip().splitlines() if line]
    rows = [r for r in rows if len(r) >= 3 and r[1] == "wifi"]
    if interface is not None:
        rows = [r for r in rows if r[0] == interface]
    return rows


class LinuxWifiAdapter(WifiAdapter):
    async def list_interfaces(self) -> list[WifiInterfaceInfo]:
        rows = await _list_wifi_devices()
        return [
            WifiInterfaceInfo(
                name=device,
                state=_STATE_MAP.get(state, "unknown"),
                is_active=(state == "connected"),
            )
            for device, _type, state in rows
        ]

    async def get_active_interface(self) -> str | None:
        rows = await _list_wifi_devices()
        for device, _type, state in rows:
            if state == "connected":
                return device
        return None

    async def get_metrics(self, interface: str) -> WifiMetrics:
        from datetime import datetime

        metrics = WifiMetrics(
            timestamp=datetime.now(UTC).isoformat(),
            interface=interface,
            interface_state="unknown",
        )

        # The three data sources are independent - run them concurrently so
        # a slow/missing one doesn't serialize onto the total tick latency.
        show_out, ap_out, link_out, survey_out = await asyncio.gather(
            _run(
                [
                    "nmcli",
                    "-t",
                    "-f",
                    "GENERAL.STATE,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS,IP6.ADDRESS",
                    "device",
                    "show",
                    interface,
                ]
            ),
            # --rescan no is load-bearing, not cosmetic: nmcli's default
            # (auto) requests a fresh scan when the last is >30s old - see
            # the module docstring.
            _run(
                [
                    "nmcli",
                    "-t",
                    "-f",
                    "active,ssid,bssid,chan,freq,signal",
                    "dev",
                    "wifi",
                    "list",
                    "ifname",
                    interface,
                    "--rescan",
                    "no",
                ]
            ),
            _run(["iw", "dev", interface, "link"]),
            _run(["iw", "dev", interface, "survey", "dump"]),
        )

        _apply_nmcli_show(metrics, show_out)
        _apply_nmcli_wifi_list(metrics, ap_out)
        _apply_iw_link(metrics, link_out)
        _apply_iw_survey(metrics, survey_out, metrics.frequency_mhz)

        metrics.band = band_from_frequency(metrics.frequency_mhz)
        metrics.compute_snr()
        return metrics

    async def scan_neighbors(self, interface: str) -> list[NeighborNetwork]:
        # `iw scan` actively triggers a fresh scan (needs CAP_NET_ADMIN,
        # which is why the systemd unit grants it alongside CAP_NET_RAW -
        # see packaging/systemd/ap-monitor.service). If that's not
        # available, fall back to `scan dump`, which only reads whatever is
        # already in the kernel's scan cache (no special privilege needed,
        # but the results may be stale or entirely absent if nothing has
        # scanned recently).
        out = await _run(["iw", "dev", interface, "scan"], timeout=15.0)
        if out is None:
            out = await _run(["iw", "dev", interface, "scan", "dump"])
        if out is None:
            return []
        return _parse_iw_scan(out)


def _apply_nmcli_show(metrics: WifiMetrics, out: str | None) -> None:
    if out is None:
        return
    ipv4: list[str] = []
    ipv6: list[str] = []
    dns: list[str] = []
    for line in out.strip().splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if key == "GENERAL.STATE":
            # e.g. "100 (connected)"
            m = re.search(r"\((\w+)\)", value)
            if m:
                metrics.interface_state = _STATE_MAP.get(m.group(1), "unknown")
        elif key.startswith("IP4.ADDRESS") and value:
            ipv4.append(value.split("/")[0])
        elif key == "IP4.GATEWAY" and value:
            metrics.gateway = value
        elif key.startswith("IP4.DNS") and value:
            dns.append(value)
        elif key.startswith("IP6.ADDRESS") and value:
            ipv6.append(value.split("/")[0])
    if ipv4:
        metrics.ipv4_addresses = ipv4
    if ipv6:
        metrics.ipv6_addresses = ipv6
    if dns:
        metrics.dns_servers = dns


def _apply_nmcli_wifi_list(metrics: WifiMetrics, out: str | None) -> None:
    if out is None:
        return
    for line in out.strip().splitlines():
        parts = _split_nmcli_terse(line)
        if len(parts) < 6 or parts[0] != "yes":
            continue
        _active, ssid, bssid, chan, freq, signal = parts[:6]
        metrics.ssid = ssid or None
        metrics.bssid = bssid or None
        if chan.isdigit():
            metrics.channel = int(chan)
        freq_match = re.match(r"(\d+)", freq)
        if freq_match:
            metrics.frequency_mhz = int(freq_match.group(1))
        if signal.isdigit():
            metrics.signal_pct = int(signal)
        return  # only one row can be the active connection


def _apply_iw_link(metrics: WifiMetrics, out: str | None) -> None:
    if out is None:
        return
    if out.strip().startswith("Not connected"):
        return

    m = re.search(r"signal:\s*(-?\d+)\s*dBm", out)
    if m:
        metrics.rssi_dbm = int(m.group(1))

    for label, attr in (
        ("tx bitrate", "tx_bitrate_mbps"),
        ("rx bitrate", "rx_bitrate_mbps"),
    ):
        line_match = re.search(rf"{label}:\s*([\d.]+)\s*MBit/s(.*)", out)
        if not line_match:
            continue
        setattr(metrics, attr, float(line_match.group(1)))
        rest = line_match.group(2)

        # e.g. " VHT-MCS 9 80MHz short GI" / " HE-MCS 11 160MHz" / " MCS 7"
        mcs_match = re.search(r"(HE|VHT|HT)?-?MCS\s+(\d+)", rest)
        if mcs_match and metrics.mcs_index is None:
            metrics.mcs_index = int(mcs_match.group(2))
            prefix = mcs_match.group(1)
            if prefix and metrics.phy_mode is None:
                metrics.phy_mode = _MCS_PHY_PREFIX.get(prefix)

        width_match = re.search(r"(\d+)MHz", rest)
        if width_match and metrics.channel_width_mhz is None:
            metrics.channel_width_mhz = int(width_match.group(1))


def _apply_iw_survey(
    metrics: WifiMetrics, out: str | None, frequency_mhz: int | None
) -> None:
    """Noise floor, when the driver reports it at all - most consumer WiFi
    chipsets don't expose this via `iw survey dump`, so a None result here
    (and therefore no SNR) is the common case, not a bug."""
    if out is None or frequency_mhz is None:
        return
    blocks = re.split(r"\n(?=\tfrequency:)", out)
    for block in blocks:
        freq_match = re.search(r"frequency:\s*(\d+)\s*MHz", block)
        if not freq_match or int(freq_match.group(1)) != frequency_mhz:
            continue
        noise_match = re.search(r"noise:\s*(-?\d+)\s*dBm", block)
        if noise_match:
            metrics.noise_floor_dbm = int(noise_match.group(1))
        return


def _parse_iw_scan(out: str) -> list[NeighborNetwork]:
    """
    Parses `iw scan`/`iw scan dump` output into a neighbor list. `iw`'s
    scan output format has genuine variation across driver/kernel versions
    (which optional capability blocks appear, in what order), so this is a
    best-effort parse: every field falls back to None rather than guessing
    when a particular block isn't present, exactly like every other reading
    in this app.
    """
    text = out.removeprefix("BSS ")
    neighbors: list[NeighborNetwork] = []
    for block in re.split(r"\nBSS ", text):
        n = _parse_bss_block(block)
        if n is not None:
            neighbors.append(n)
    return neighbors


def _parse_bss_block(block: str) -> NeighborNetwork | None:
    bssid_match = re.match(r"([0-9a-fA-F:]{17})", block)
    if not bssid_match:
        return None
    bssid = bssid_match.group(1).upper()

    ssid_match = re.search(r"\n\tSSID:\s*(.*)", block)
    ssid = ssid_match.group(1).strip() or None if ssid_match else None

    freq_match = re.search(r"\n\tfreq:\s*(\d+)", block)
    freq = int(freq_match.group(1)) if freq_match else None

    channel_match = re.search(r"DS Parameter set:\s*channel\s*(\d+)", block)
    channel = (
        int(channel_match.group(1)) if channel_match else channel_from_frequency(freq)
    )

    signal_match = re.search(r"\n\tsignal:\s*(-?[\d.]+)\s*dBm", block)
    rssi = round(float(signal_match.group(1))) if signal_match else None

    # PHY mode: presence of each capability block, from newest to oldest -
    # a network only ever advertises the highest standard it supports, but
    # scan output typically includes every block up to that level, so
    # checking newest-first picks the right one.
    if re.search(r"\n\tHE capabilities", block) or re.search(
        r"\n\tHE operation", block
    ):
        phy_mode = "802.11ax"
    elif re.search(r"\n\tVHT capabilities", block) or re.search(
        r"\n\tVHT operation", block
    ):
        phy_mode = "802.11ac"
    elif re.search(r"\n\tHT capabilities", block) or re.search(
        r"\n\tHT operation", block
    ):
        phy_mode = "802.11n"
    elif freq is not None and 2400 <= freq <= 2495:
        phy_mode = "802.11g"
    elif freq is not None:
        phy_mode = "802.11a"
    else:
        phy_mode = None

    # Channel width: only confidently determined for VHT/HE-capable networks
    # whose operation block states it explicitly; left None otherwise rather
    # than assuming the common (but not universal) 20MHz default.
    width_match = re.search(r"channel width:\s*(\d+)\s*MHz", block, re.IGNORECASE)
    channel_width_mhz = int(width_match.group(1)) if width_match else None

    if re.search(r"\n\tRSN:", block):
        security = "WPA2/WPA3"
    elif re.search(r"\n\tWPA:", block):
        security = "WPA"
    elif re.search(r"capability:.*Privacy", block):
        security = "WEP"
    else:
        security = "Open"

    return NeighborNetwork(
        ssid=ssid,
        bssid=bssid,
        phy_mode=phy_mode,
        channel=channel,
        channel_width_mhz=channel_width_mhz,
        band=band_from_frequency(freq),
        security=security,
        rssi_dbm=rssi,
    )
