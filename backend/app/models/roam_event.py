"""
==============================================================================
Module Name:   roam_event.py
Description:   Source module roam_event.py.
Author:        Mai Tan Duc <ducmai.network@gmail.com>
Created:       2026-10-10
Version:       1.0.0
License:       MIT
==============================================================================
Usage:         python3 roam_event.py [options]
Notes:         Requires Python 3.8+
==============================================================================
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# The seven states from the spec. Modeled as a Literal, matching
# app.models.status.ConnectivityState's style rather than an enum.Enum.
RoamingState = Literal[
    "unknown",
    "disconnected",
    "connecting",
    "connected",
    "roam_candidate",  # a new BSSID was just seen once - not yet confirmed, could be a flicker
    "roaming",  # the same new BSSID held for a second reading - confirmed, event just recorded
    "stabilizing",  # one more matching tick before calling it fully settled
]

RoamClassification = Literal["excellent", "good", "fair", "poor", "failed"]
RoamConfidence = Literal["high", "medium", "low", "unknown"]


class RoamEventCreate(BaseModel):
    timestamp: str
    interface: str
    ssid: str | None = None

    previous_bssid: str | None = None
    new_bssid: str | None = None
    previous_frequency_mhz: int | None = None
    new_frequency_mhz: int | None = None
    previous_channel: int | None = None
    new_channel: int | None = None
    previous_band: str | None = None
    new_band: str | None = None
    previous_phy_mode: str | None = None
    new_phy_mode: str | None = None
    previous_channel_width_mhz: int | None = None
    new_channel_width_mhz: int | None = None
    previous_mcs_index: int | None = None
    new_mcs_index: int | None = None
    previous_rssi_dbm: int | None = None
    new_rssi_dbm: int | None = None

    ip_changed: bool = False
    previous_ipv4: list[str] | None = None
    new_ipv4: list[str] | None = None


class RoamEventOut(RoamEventCreate):
    id: int

    # Stage 10 fields - None until the interruption-measurement and
    # classification logic fills them in.
    gateway_interruption_ms: float | None = None
    internet_interruption_ms: float | None = None
    packet_loss_during_pct: float | None = None
    peak_latency_ms: float | None = None
    success: bool | None = None
    classification: RoamClassification | None = None
    confidence: RoamConfidence | None = None
