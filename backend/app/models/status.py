from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Quality = Literal["excellent", "good", "fair", "poor", "offline", "unknown"]

# The eight states the spec asks the app to distinguish. Modeled as a flat
# Literal (matching Quality's own style) rather than three separate
# booleans, because the states form a natural ladder rather than an
# independent 2x2x2 combination - see connectivity_service._derive_overall
# for exactly how a given reading resolves to one of these.
ConnectivityState = Literal[
    "unknown",
    "wifi_disconnected",
    "wifi_connected",  # associated, but no probe targets configured/answered yet
    "gateway_unavailable",
    "gateway_available",  # gateway reachable, but no external targets configured/answered yet
    "internet_unavailable",
    "degraded",  # some, but not all, external targets reachable
    "internet_available",
]


class ConnectivityStatus(BaseModel):
    wifi_connected: bool | None = None
    gateway_reachable: bool | None = None
    internet_state: Literal["unavailable", "degraded", "available"] | None = None
    overall: ConnectivityState = "unknown"


class WifiIssue(BaseModel):
    """Why the WiFi/AP half of the dashboard is empty or incomplete, in words
    a user can act on. Absent (None) when everything the adapter can read was
    read - see app/monitoring/wifi/diagnostics.py."""

    code: str
    title: str
    detail: str


class TargetStatus(BaseModel):
    target_id: int
    name: str
    host: str
    reachable: bool
    latency_ms: float | None
    packet_loss: float | None
    last_checked: str | None


class StatusResponse(BaseModel):
    online: bool
    quality: Quality
    latency_ms: float | None
    packet_loss: float | None
    jitter_ms: float | None
    monitoring_uptime_seconds: float
    targets_reachable: int
    targets_total: int
    targets: list[TargetStatus]
    monitoring_running: bool

    # WiFi fields (Stage 12) - from the most recent app.monitoring.wifi
    # reading for the active interface, all None when there's no active
    # WiFi association (or no WiFi adapter at all) rather than fabricated.
    wifi_interface: str | None = None
    ssid: str | None = None
    bssid: str | None = None
    rssi_dbm: int | None = None
    channel: int | None = None
    band: str | None = None
    phy_mode: str | None = None
    channel_width_mhz: int | None = None
    snr_db: int | None = None
    noise_floor_dbm: int | None = None
    tx_bitrate_mbps: float | None = None
    wifi_issue: WifiIssue | None = None
    # sys.platform of the host running the backend ("linux" | "darwin" |
    # "win32"). The UI uses it for platform-specific hints (e.g. Windows
    # reports signal quality %, so its dBm figure is derived).
    platform: str = ""

    connectivity: ConnectivityStatus = Field(default_factory=ConnectivityStatus)
    wireless_quality_score: int | None = None


class StatisticsResponse(BaseModel):
    range_start: str
    range_end: str
    target_id: int | None
    sample_count: int
    avg_latency_ms: float | None
    min_latency_ms: float | None
    max_latency_ms: float | None
    median_latency_ms: float | None
    p95_latency_ms: float | None
    packet_loss_pct: float | None
    avg_jitter_ms: float | None
    monitoring_duration_seconds: float
