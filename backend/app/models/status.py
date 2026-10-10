from __future__ import annotations

from typing import List, Literal, Optional

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
    wifi_connected: Optional[bool] = None
    gateway_reachable: Optional[bool] = None
    internet_state: Optional[Literal["unavailable", "degraded", "available"]] = None
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
    latency_ms: Optional[float]
    packet_loss: Optional[float]
    last_checked: Optional[str]


class StatusResponse(BaseModel):
    online: bool
    quality: Quality
    latency_ms: Optional[float]
    packet_loss: Optional[float]
    jitter_ms: Optional[float]
    monitoring_uptime_seconds: float
    targets_reachable: int
    targets_total: int
    targets: List[TargetStatus]
    monitoring_running: bool

    # WiFi fields (Stage 12) - from the most recent app.monitoring.wifi
    # reading for the active interface, all None when there's no active
    # WiFi association (or no WiFi adapter at all) rather than fabricated.
    wifi_interface: Optional[str] = None
    ssid: Optional[str] = None
    bssid: Optional[str] = None
    rssi_dbm: Optional[int] = None
    channel: Optional[int] = None
    band: Optional[str] = None
    phy_mode: Optional[str] = None
    channel_width_mhz: Optional[int] = None
    snr_db: Optional[int] = None
    noise_floor_dbm: Optional[int] = None
    tx_bitrate_mbps: Optional[float] = None
    wifi_issue: Optional[WifiIssue] = None
    # sys.platform of the host running the backend ("linux" | "darwin" |
    # "win32"). The UI uses it for platform-specific hints (e.g. Windows
    # reports signal quality %, so its dBm figure is derived).
    platform: str = ""

    connectivity: ConnectivityStatus = Field(default_factory=ConnectivityStatus)
    wireless_quality_score: Optional[int] = None


class StatisticsResponse(BaseModel):
    range_start: str
    range_end: str
    target_id: Optional[int]
    sample_count: int
    avg_latency_ms: Optional[float]
    min_latency_ms: Optional[float]
    max_latency_ms: Optional[float]
    median_latency_ms: Optional[float]
    p95_latency_ms: Optional[float]
    packet_loss_pct: Optional[float]
    avg_jitter_ms: Optional[float]
    monitoring_duration_seconds: float
