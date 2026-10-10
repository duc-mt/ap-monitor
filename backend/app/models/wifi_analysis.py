"""
==============================================================================
Module Name:   wifi_analysis.py
Description:   Source module wifi_analysis.py.
Author:        Mai Tan Duc <ducmai.network@gmail.com>
Created:       2026-10-10
Version:       1.0.0
License:       MIT
==============================================================================
Usage:         python3 wifi_analysis.py [options]
Notes:         Requires Python 3.8+
==============================================================================
"""

from __future__ import annotations

from pydantic import BaseModel


class SignalPoint(BaseModel):
    t: str  # ISO timestamp
    rssi: int | None = None
    snr: int | None = None
    bssid: str | None = None
    channel: int | None = None
    rate: float | None = None  # tx bitrate, Mbps
    connected: bool = True


class ApSegment(BaseModel):
    """One unbroken stretch on a single access point."""

    bssid: str | None = None
    ssid: str | None = None
    band: str | None = None
    channel: int | None = None
    start: str
    end: str
    duration_seconds: float
    sample_count: int
    rssi_min: int | None = None
    rssi_avg: float | None = None
    rssi_max: int | None = None


class ApUsage(BaseModel):
    """A per-AP rollup of every segment on that BSSID."""

    bssid: str | None = None
    ssid: str | None = None
    band: str | None = None
    channel: int | None = None
    visits: int
    total_seconds: float
    sample_count: int
    share_pct: float  # share of connected samples
    rssi_min: int | None = None
    rssi_avg: float | None = None
    rssi_max: int | None = None


class ApChange(BaseModel):
    """A switch from one BSSID to another between adjacent segments."""

    timestamp: str
    ssid: str | None = None
    from_bssid: str
    to_bssid: str
    same_ssid: bool
    via_disconnect: bool  # a disconnected gap sat between the two APs
    rssi_before: int | None = None
    rssi_after: int | None = None


class WeakStretch(BaseModel):
    start: str
    end: str
    duration_seconds: float
    sample_count: int
    min_rssi_dbm: int
    bssid: str | None = None


class SignalSummary(BaseModel):
    start: str | None = None
    end: str | None = None
    duration_seconds: float = 0.0
    sample_count: int = 0
    connected_sample_count: int = 0
    rssi_min: int | None = None
    rssi_avg: float | None = None
    rssi_max: int | None = None
    snr_avg: float | None = None
    tx_rate_avg: float | None = None
    weak_threshold_dbm: int = -70
    pct_samples_weak: float | None = None
    distinct_aps: int = 0
    ap_change_count: int = 0
    # False when connected samples carry no BSSID at all (OS privacy gating):
    # the AP breakdown below is then meaningless and the UI must say why.
    bssid_available: bool = True


class SignalAnalysis(BaseModel):
    summary: SignalSummary
    aps: list[ApUsage]
    segments: list[ApSegment]
    ap_changes: list[ApChange]
    weak_stretches: list[WeakStretch]
    points: list[SignalPoint]
