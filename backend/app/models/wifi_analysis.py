"""
Response shapes for signal/AP analysis - the "which AP was I on, how strong
was it, and where did it get weak" view that both the Dashboard timeline and
the Walk Test results page are built from. One shape serves both because a
walk-test session and a window of the always-on WiFi poll are the same kind
of data: a time-ordered series of WiFi readings.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class SignalPoint(BaseModel):
    t: str  # ISO timestamp
    rssi: Optional[int] = None
    snr: Optional[int] = None
    bssid: Optional[str] = None
    channel: Optional[int] = None
    rate: Optional[float] = None  # tx bitrate, Mbps
    connected: bool = True


class ApSegment(BaseModel):
    """One unbroken stretch on a single access point."""

    bssid: Optional[str] = None
    ssid: Optional[str] = None
    band: Optional[str] = None
    channel: Optional[int] = None
    start: str
    end: str
    duration_seconds: float
    sample_count: int
    rssi_min: Optional[int] = None
    rssi_avg: Optional[float] = None
    rssi_max: Optional[int] = None


class ApUsage(BaseModel):
    """A per-AP rollup of every segment on that BSSID."""

    bssid: Optional[str] = None
    ssid: Optional[str] = None
    band: Optional[str] = None
    channel: Optional[int] = None
    visits: int
    total_seconds: float
    sample_count: int
    share_pct: float  # share of connected samples
    rssi_min: Optional[int] = None
    rssi_avg: Optional[float] = None
    rssi_max: Optional[int] = None


class ApChange(BaseModel):
    """A switch from one BSSID to another between adjacent segments."""

    timestamp: str
    ssid: Optional[str] = None
    from_bssid: str
    to_bssid: str
    same_ssid: bool
    via_disconnect: bool  # a disconnected gap sat between the two APs
    rssi_before: Optional[int] = None
    rssi_after: Optional[int] = None


class WeakStretch(BaseModel):
    start: str
    end: str
    duration_seconds: float
    sample_count: int
    min_rssi_dbm: int
    bssid: Optional[str] = None


class SignalSummary(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None
    duration_seconds: float = 0.0
    sample_count: int = 0
    connected_sample_count: int = 0
    rssi_min: Optional[int] = None
    rssi_avg: Optional[float] = None
    rssi_max: Optional[int] = None
    snr_avg: Optional[float] = None
    tx_rate_avg: Optional[float] = None
    weak_threshold_dbm: int = -70
    pct_samples_weak: Optional[float] = None
    distinct_aps: int = 0
    ap_change_count: int = 0
    # False when connected samples carry no BSSID at all (OS privacy gating):
    # the AP breakdown below is then meaningless and the UI must say why.
    bssid_available: bool = True


class SignalAnalysis(BaseModel):
    summary: SignalSummary
    aps: List[ApUsage]
    segments: List[ApSegment]
    ap_changes: List[ApChange]
    weak_stretches: List[WeakStretch]
    points: List[SignalPoint]
