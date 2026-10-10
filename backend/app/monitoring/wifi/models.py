"""
Data model for a single WiFi metrics snapshot.

Every field below is genuinely optional: different OSes, drivers, and
chipsets expose different subsets of this data, and this module never
fabricates a value it can't actually read. `None` means "the platform or
driver did not report this" - it must never be silently turned into `0`
or an empty string, since both are meaningfully different from
"unavailable" (0 dBm RSSI and 0% signal are both real, if unlikely,
readings; a genuinely empty DNS server list is different from "we
couldn't determine the DNS servers").
"""

from __future__ import annotations

from dataclasses import dataclass

# Normalized across platforms - each adapter maps its own native
# interface-state vocabulary onto this small set rather than leaking
# platform-specific state names (NetworkManager's numeric+string states,
# CoreWLAN's CWInterfaceState enum, etc.) up to the rest of the app.
InterfaceState = str  # one of: connected, disconnected, connecting,
# scanning, disabled, unavailable, unknown


@dataclass
class WifiInterfaceInfo:
    """A WiFi-capable network interface, before any metrics are read from it."""

    name: str
    state: InterfaceState
    is_active: bool  # True if this interface is the one currently carrying traffic


@dataclass
class WifiMetrics:
    """A single point-in-time snapshot for one interface."""

    timestamp: str  # ISO 8601, UTC
    interface: str
    interface_state: InterfaceState

    ssid: str | None = None
    bssid: str | None = None

    frequency_mhz: int | None = None
    channel: int | None = None
    band: str | None = None  # "2.4GHz" | "5GHz" | "6GHz" | "Unknown"

    rssi_dbm: int | None = None
    signal_pct: int | None = None
    noise_floor_dbm: int | None = None
    snr_db: int | None = None  # exactly rssi_dbm - noise_floor_dbm; never estimated

    phy_mode: str | None = None  # e.g. "802.11ac"
    channel_width_mhz: int | None = None  # 20 / 40 / 80 / 160
    mcs_index: int | None = None

    tx_bitrate_mbps: float | None = None
    rx_bitrate_mbps: float | None = None
    # Only populated when a platform reports a single generic link rate and
    # can't tell tx/rx apart (e.g. nmcli's one "RATE" column on Linux when
    # `iw` isn't available) - never a duplicate of tx_bitrate_mbps.
    phy_rate_mbps: float | None = None

    ipv4_addresses: list[str] | None = None
    ipv6_addresses: list[str] | None = None
    gateway: str | None = None
    dns_servers: list[str] | None = None

    # Machine-readable reason an adapter could not give a full reading
    # (e.g. "location_permission" when the OS hides SSID/BSSID without
    # Location access). Never persisted; used to explain empty fields in the
    # UI instead of leaving them silently blank. See wifi/diagnostics.py.
    issue: str | None = None

    def compute_snr(self) -> None:
        """Fill snr_db from rssi/noise - only when both are real readings."""
        if self.rssi_dbm is not None and self.noise_floor_dbm is not None:
            self.snr_db = self.rssi_dbm - self.noise_floor_dbm


def is_connected(metrics: WifiMetrics) -> bool | None:
    """True/False for a definite reading, None when the adapter could not
    tell ("unknown"). Callers must not turn None into False: a monitor that
    cannot read the radio must say so, not claim the WiFi is down."""
    if metrics.interface_state == "connected":
        return True
    if metrics.interface_state == "unknown":
        return None
    return False


def band_from_frequency(freq_mhz: int | None) -> str | None:
    """Shared by every adapter so band classification is identical across platforms."""
    if freq_mhz is None:
        return None
    if 2400 <= freq_mhz <= 2495:
        return "2.4GHz"
    if 5150 <= freq_mhz <= 5895:
        return "5GHz"
    if 5925 <= freq_mhz <= 7125:
        return "6GHz"
    return "Unknown"


def channel_from_frequency(freq_mhz: int | None) -> int | None:
    """Standard WiFi channel-numbering formulas, used wherever a scan result
    doesn't state its channel directly (e.g. Linux `iw scan` output, which
    only prints a legacy 'DS Parameter set: channel N' line on 2.4GHz)."""
    if freq_mhz is None:
        return None
    if 2412 <= freq_mhz <= 2484:
        if freq_mhz == 2484:
            return 14
        return (freq_mhz - 2407) // 5
    if 5000 <= freq_mhz <= 5895:
        return (freq_mhz - 5000) // 5
    if 5925 <= freq_mhz <= 7125:
        return (freq_mhz - 5950) // 5
    return None


def channel_from_frequency(freq_mhz: int | None) -> int | None:
    """Standard channel-numbering formulas, used when a scan result gives a
    frequency but not an explicit channel number (common for 5GHz/6GHz
    entries in `iw scan` output)."""
    if freq_mhz is None:
        return None
    if freq_mhz == 2484:
        return 14
    if 2412 <= freq_mhz <= 2472:
        return (freq_mhz - 2407) // 5
    if 5955 <= freq_mhz <= 7115:
        return (freq_mhz - 5950) // 5
    if 5160 <= freq_mhz <= 5885:
        return (freq_mhz - 5000) // 5
    return None


@dataclass
class NeighborNetwork:
    """One network seen during an on-demand environment scan (Stage 11).
    Never populated from the background monitoring loop - only from an
    explicit, user-triggered scan_environment() call."""

    ssid: str | None = None
    bssid: str | None = None
    channel: int | None = None
    band: str | None = None
    channel_width_mhz: int | None = None
    phy_mode: str | None = None
    security: str | None = None
    rssi_dbm: int | None = None
    # Filled in by app.monitoring.wifi.compute_co_channel_overlap() after the
    # scan, by comparing against the *current* connection - never set by an
    # adapter itself, which has no opinion on what "current" means.
    is_co_channel: bool = False
