"""
Windows WiFi adapter.

Everything comes from two built-in tools, so nothing needs installing and
no admin rights are required:

- `netsh wlan show interfaces` - the connected AP: state, SSID, BSSID, band,
  channel, radio type (802.11ac/ax/...), link rates and signal quality.
- `netsh wlan show networks mode=bssid` - every BSSID the adapter can hear,
  used only by the on-demand "Scan Environment" action. Unlike macOS this
  gives real neighbor BSSIDs, so on Windows the scan is more useful.
- `ipconfig` - IPv4 address and default gateway (what roam detection uses to
  notice an IP change), cached briefly because it is not radio state.

Things a reader should know before trusting the numbers:

1. **RSSI is derived.** netsh reports signal *quality* as a percentage, not
   dBm. Microsoft documents the mapping (WLAN_SIGNAL_QUALITY: 0 = -100 dBm,
   100 = -50 dBm, linear in between), which is what `rssi_from_quality`
   applies. It is accurate to about the 2 dB the percentage can resolve and
   cannot show anything stronger than -50 dBm. Noise floor and SNR are not
   exposed at all, so they stay None.
2. **Language.** netsh prints localized labels. English labels are matched
   exactly; for other languages a structural fallback recovers the fields
   whose *values* are recognizable (MAC addresses, "92%", "5 GHz") and the
   fixed order netsh prints them in. It is best-effort - see
   `parse_interfaces`.
3. **Location permission.** Recent Windows 11 builds refuse to show WLAN
   details unless Location services are on, printing a message instead. That
   is detected and reported as the `location_permission` issue rather than
   being mistaken for "no WiFi".

No call here triggers a scan: `show interfaces`/`show networks` read what
the WLAN service already has. Each command is a plain argv list (no shell).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.models.wifi_scan import NeighborNetwork
from app.monitoring._proc import NO_WINDOW, decode_output
from app.monitoring.wifi.base import WifiAdapter
from app.monitoring.wifi.models import WifiInterfaceInfo, WifiMetrics

logger = logging.getLogger("ap_monitor.wifi.windows")

_TIMEOUT_SECONDS = 4.0
_SCAN_TIMEOUT_SECONDS = 15.0
_IP_CACHE_TTL_SECONDS = 5.0

_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$")
_PCT_RE = re.compile(r"^(\d{1,3})\s*%$")
_BAND_RE = re.compile(r"^(\d(?:\.\d)?)\s*GHz$", re.IGNORECASE)
_INT_RE = re.compile(r"^\d{1,3}$")
_FLOAT_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_PAIR_RE = re.compile(r"^\s*([^:]+?)\s*:\s*(.*?)\s*$")

_STATE_MAP = {
    "connected": "connected",
    "disconnected": "disconnected",
    "disconnecting": "disconnected",
    "connecting": "connecting",
    "associating": "connecting",
    "authenticating": "connecting",
    "discovering": "connecting",
}


def rssi_from_quality(percent: int) -> int:
    """Microsoft's documented WLAN_SIGNAL_QUALITY -> dBm mapping."""
    return round(max(0, min(100, percent)) / 2 - 100)


def _norm_band(value: str) -> Optional[str]:
    m = _BAND_RE.match(value.strip())
    return f"{m.group(1)}GHz" if m else None


def _frequency(channel: Optional[int], band: Optional[str]) -> Optional[int]:
    if channel is None or band is None:
        return None
    if band == "2.4GHz":
        return 2484 if channel == 14 else 2407 + 5 * channel
    if band == "5GHz":
        return 5000 + 5 * channel
    if band == "6GHz":
        return 5950 + 5 * channel
    return None


def _band_from_channel(channel: Optional[int]) -> Optional[str]:
    """Only used when netsh printed no Band line (older builds). 6GHz channel
    numbers overlap the other bands, so this can only tell 2.4 from 5."""
    if channel is None:
        return None
    if 1 <= channel <= 14:
        return "2.4GHz"
    if 32 <= channel <= 177:
        return "5GHz"
    return None


def _is_location_blocked(text: str) -> bool:
    low = text.lower()
    return "location permission" in low or "ms-settings:privacy-location" in low


# ---------------------------------------------------------------------------
# Parsing (pure functions - exercised directly by the unit tests)
# ---------------------------------------------------------------------------
def _pairs(text: str, *, keep_empty: bool = False) -> List[Tuple[str, str]]:
    """`key : value` lines in order. Empty values are dropped unless asked
    for: a hidden network is printed as a bare `SSID 2 :`, and losing that
    line would let it inherit the previous network's name."""
    out: List[Tuple[str, str]] = []
    for line in text.splitlines():
        m = _PAIR_RE.match(line)
        if m and (keep_empty or m.group(2) != ""):
            out.append((m.group(1), m.group(2)))
    return out


def _split_blocks(pairs: List[Tuple[str, str]]) -> List[List[Tuple[str, str]]]:
    """One block per interface: a new block begins whenever a key repeats."""
    blocks: List[List[Tuple[str, str]]] = []
    seen: set = set()
    cur: List[Tuple[str, str]] = []
    for key, value in pairs:
        k = key.lower()
        if k in seen and cur:
            blocks.append(cur)
            cur, seen = [], set()
        seen.add(k)
        cur.append((key, value))
    if cur:
        blocks.append(cur)
    return blocks


def _parse_block(block: List[Tuple[str, str]]) -> Optional[Dict[str, object]]:
    by_key = {k.lower(): v for k, v in block}
    info: Dict[str, object] = {}

    # --- English labels (authoritative when present) ---------------------
    info["name"] = by_key.get("name")
    state_raw = by_key.get("state")
    info["bssid"] = by_key.get("ap bssid") or by_key.get("bssid")
    info["ssid"] = by_key.get("ssid")
    info["radio"] = by_key.get("radio type")
    info["band"] = _norm_band(by_key["band"]) if "band" in by_key else None
    chan = by_key.get("channel")
    info["channel"] = int(chan) if chan and chan.strip().isdigit() else None
    sig = by_key.get("signal")
    pm = _PCT_RE.match(sig.strip()) if sig else None
    info["signal"] = int(pm.group(1)) if pm else None
    for label, field in (("receive rate (mbps)", "rx"), ("transmit rate (mbps)", "tx")):
        raw = by_key.get(label)
        info[field] = (
            float(raw.replace(",", "."))
            if raw and _FLOAT_RE.match(raw.strip())
            else None
        )

    recognised = state_raw is not None
    state = _STATE_MAP.get((state_raw or "").strip().lower())

    # --- Language-independent fallback -----------------------------------
    # Used when the labels were not English. Relies only on what a value
    # looks like (MAC, "NN%", "N GHz") and netsh's fixed line order, in which
    # SSID is the line immediately before the AP BSSID.
    if not recognised:
        macs = [(i, v) for i, (_, v) in enumerate(block) if _MAC_RE.match(v.strip())]
        if len(macs) >= 2:  # [adapter MAC, AP BSSID]
            idx, info["bssid"] = macs[1]
            if idx > 0:
                info["ssid"] = block[idx - 1][1]
            for _, v in block[idx + 1 :]:
                if info["band"] is None and _norm_band(v):
                    info["band"] = _norm_band(v)
                elif (
                    info["band"] is not None
                    and info["channel"] is None
                    and _INT_RE.match(v.strip())
                ):
                    info["channel"] = int(v.strip())
        for _, v in block:
            pm = _PCT_RE.match(v.strip())
            if pm:
                info["signal"] = int(pm.group(1))
            if v.strip().startswith("802.11"):
                info["radio"] = v.strip()
        if info["bssid"] and info["signal"] is not None:
            state = "connected"
        elif block:
            state = "disconnected"
        info["name"] = info["name"] or block[0][1]

    if info["name"] is None and state is None:
        return None
    info["state"] = state or "unknown"
    return info


def parse_interfaces(text: str) -> List[Dict[str, object]]:
    """Parse `netsh wlan show interfaces` into one dict per interface."""
    out = []
    for block in _split_blocks(_pairs(text)):
        parsed = _parse_block(block)
        if parsed is not None and parsed.get("name"):
            out.append(parsed)
    return out


def metrics_from_interface(info: Dict[str, object], interface: str) -> WifiMetrics:
    metrics = WifiMetrics(
        timestamp=datetime.now(timezone.utc).isoformat(),
        interface=interface,
        interface_state=str(info.get("state") or "unknown"),
    )
    if metrics.interface_state != "connected":
        return metrics
    ssid, bssid = info.get("ssid"), info.get("bssid")
    metrics.ssid = str(ssid) if ssid else None
    metrics.bssid = str(bssid).lower().replace("-", ":") if bssid else None
    metrics.channel = info.get("channel")  # type: ignore[assignment]
    band = info.get("band") or _band_from_channel(metrics.channel)  # type: ignore[arg-type]
    metrics.band = band  # type: ignore[assignment]
    metrics.frequency_mhz = _frequency(metrics.channel, metrics.band)
    radio = info.get("radio")
    metrics.phy_mode = str(radio) if radio else None
    sig = info.get("signal")
    if sig is not None:
        metrics.signal_pct = int(sig)  # type: ignore[arg-type]
        metrics.rssi_dbm = rssi_from_quality(int(sig))  # type: ignore[arg-type]
    metrics.rx_bitrate_mbps = info.get("rx")  # type: ignore[assignment]
    metrics.tx_bitrate_mbps = info.get("tx")  # type: ignore[assignment]
    return metrics


def parse_networks(text: str) -> List[NeighborNetwork]:
    """Parse `netsh wlan show networks mode=bssid` into one entry per BSSID."""
    pairs = _pairs(text, keep_empty=True)
    out: List[NeighborNetwork] = []
    ssid: Optional[str] = None
    security: Optional[str] = None
    cur: Optional[NeighborNetwork] = None
    prev_was_band = False

    def flush() -> None:
        nonlocal cur
        if cur is not None:
            if cur.band is None:
                cur.band = _band_from_channel(cur.channel)
            out.append(cur)
        cur = None

    for key, value in pairs:
        k, v = key.lower(), value.strip()
        if re.match(r"^ssid\s+\d+$", k):
            flush()
            ssid, security = (v or None), None
            continue
        if not v:
            continue
        if re.match(r"^bssid\s+\d+$", k) or (
            cur is None and _MAC_RE.match(v) and not k.startswith("physical")
        ):
            flush()
            cur = NeighborNetwork(
                ssid=ssid, bssid=v.lower().replace("-", ":"), security=security
            )
            prev_was_band = False
            continue
        if cur is None:
            if k == "authentication":
                security = v
            continue
        pm = _PCT_RE.match(v)
        if pm and (k == "signal" or cur.rssi_dbm is None):
            cur.rssi_dbm = rssi_from_quality(int(pm.group(1)))
        elif k == "radio type" or v.startswith("802.11"):
            cur.phy_mode = v
        elif _norm_band(v):
            cur.band = _norm_band(v)
            prev_was_band = True
            continue
        elif k == "channel" and _INT_RE.match(v):
            cur.channel = int(v)
        elif prev_was_band and cur.channel is None and _INT_RE.match(v):
            cur.channel = int(v)
        prev_was_band = False
    flush()
    return out


def parse_ipconfig(
    text: str, interface: str
) -> Tuple[Optional[List[str]], Optional[str]]:
    """(IPv4 addresses, default gateway) for `interface` from plain
    `ipconfig` output. Sections are found by the adapter name in the
    (unindented) header line, which is not localized; within a section the
    values are classified by shape - IPv4 address, then subnet mask (starts
    with 255.), then default gateway - in the order ipconfig prints them."""
    wanted = interface.strip().lower()
    in_section = False
    values: List[str] = []
    for line in text.splitlines():
        if line and not line[0].isspace():
            header = line.strip().rstrip(":").strip().lower()
            in_section = header == wanted or header.endswith(" " + wanted)
            continue
        if not in_section:
            continue
        stripped = line.strip()
        value = stripped.split(" : ", 1)[1].strip() if " : " in stripped else stripped
        if _IPV4_RE.match(value):
            values.append(value)
    if not values:
        return None, None
    address = values[0]
    gateway: Optional[str] = None
    if len(values) >= 3 and values[1].startswith("255."):
        gateway = values[2]
    return [address], gateway


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------
async def _run(cmd: List[str], timeout: float = _TIMEOUT_SECONDS) -> Optional[str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **NO_WINDOW,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return decode_output(stdout)
    except asyncio.TimeoutError:
        logger.warning("%s timed out", cmd[0])
    except (FileNotFoundError, OSError) as exc:
        logger.warning("could not run %s: %s", cmd[0], exc)
    return None


class WindowsWifiAdapter(WifiAdapter):
    def __init__(self) -> None:
        # Set when the last read failed for a reason the user can fix; read by
        # wifi.get_adapter_issue() so "no interface" can say *why*.
        self.last_issue: Optional[str] = None
        self._ip_cache: Dict[str, Tuple[float, Optional[List[str]], Optional[str]]] = {}

    async def _read_interfaces(self) -> Optional[List[Dict[str, object]]]:
        out = await _run(["netsh", "wlan", "show", "interfaces"])
        if out is None:
            self.last_issue = "adapter_error"
            return None
        if _is_location_blocked(out):
            self.last_issue = "location_permission"
            return None
        self.last_issue = None
        return parse_interfaces(out)

    async def list_interfaces(self) -> List[WifiInterfaceInfo]:
        infos = await self._read_interfaces() or []
        return [
            WifiInterfaceInfo(
                name=str(i["name"]),
                state=str(i["state"]),
                is_active=i["state"] == "connected",
            )
            for i in infos
        ]

    async def get_active_interface(self) -> Optional[str]:
        infos = await self._read_interfaces()
        if not infos:
            return None
        connected = next((i for i in infos if i["state"] == "connected"), None)
        return str((connected or infos[0])["name"])

    async def get_metrics(self, interface: str) -> WifiMetrics:
        infos = await self._read_interfaces()
        if infos is None:
            metrics = WifiMetrics(
                timestamp=datetime.now(timezone.utc).isoformat(),
                interface=interface,
                interface_state="unknown",
                issue=self.last_issue,
            )
            return metrics
        match = next(
            (i for i in infos if str(i["name"]).lower() == interface.lower()), None
        )
        if match is None:
            return WifiMetrics(
                timestamp=datetime.now(timezone.utc).isoformat(),
                interface=interface,
                interface_state="unavailable",
            )
        metrics = metrics_from_interface(match, interface)
        if metrics.interface_state == "connected":
            await self._apply_ip_info(metrics, interface)
        return metrics

    async def _apply_ip_info(self, metrics: WifiMetrics, interface: str) -> None:
        cached = self._ip_cache.get(interface)
        if (
            cached is not None
            and (time.monotonic() - cached[0]) < _IP_CACHE_TTL_SECONDS
        ):
            metrics.ipv4_addresses, metrics.gateway = cached[1], cached[2]
            return
        out = await _run(["ipconfig"])
        addrs, gateway = parse_ipconfig(out, interface) if out else (None, None)
        self._ip_cache[interface] = (time.monotonic(), addrs, gateway)
        metrics.ipv4_addresses, metrics.gateway = addrs, gateway

    async def scan_neighbors(self, interface: str) -> List[NeighborNetwork]:
        out = await _run(
            ["netsh", "wlan", "show", "networks", "mode=bssid"],
            timeout=_SCAN_TIMEOUT_SECONDS,
        )
        if not out or _is_location_blocked(out):
            return []
        return parse_networks(out)
