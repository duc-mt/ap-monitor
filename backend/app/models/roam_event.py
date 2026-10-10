"""
Models for a confirmed roam event (see app.services.roaming_service) and
the roaming state machine's state vocabulary.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel

# The seven states from the spec. Modeled as a Literal, matching
# app.models.status.ConnectivityState's style rather than an enum.Enum.
RoamingState = Literal[
    "unknown",
    "disconnected",
    "connecting",
    "connected",
    "roam_candidate",  # a new BSSID was just seen once - not yet confirmed, could be a flicker
    "roaming",         # the same new BSSID held for a second reading - confirmed, event just recorded
    "stabilizing",      # one more matching tick before calling it fully settled
]

RoamClassification = Literal["excellent", "good", "fair", "poor", "failed"]
RoamConfidence = Literal["high", "medium", "low", "unknown"]


class RoamEventCreate(BaseModel):
    timestamp: str
    interface: str
    ssid: Optional[str] = None

    previous_bssid: Optional[str] = None
    new_bssid: Optional[str] = None
    previous_frequency_mhz: Optional[int] = None
    new_frequency_mhz: Optional[int] = None
    previous_channel: Optional[int] = None
    new_channel: Optional[int] = None
    previous_band: Optional[str] = None
    new_band: Optional[str] = None
    previous_phy_mode: Optional[str] = None
    new_phy_mode: Optional[str] = None
    previous_channel_width_mhz: Optional[int] = None
    new_channel_width_mhz: Optional[int] = None
    previous_mcs_index: Optional[int] = None
    new_mcs_index: Optional[int] = None
    previous_rssi_dbm: Optional[int] = None
    new_rssi_dbm: Optional[int] = None

    ip_changed: bool = False
    previous_ipv4: Optional[List[str]] = None
    new_ipv4: Optional[List[str]] = None


class RoamEventOut(RoamEventCreate):
    id: int

    # Stage 10 fields - None until the interruption-measurement and
    # classification logic fills them in.
    gateway_interruption_ms: Optional[float] = None
    internet_interruption_ms: Optional[float] = None
    packet_loss_during_pct: Optional[float] = None
    peak_latency_ms: Optional[float] = None
    success: Optional[bool] = None
    classification: Optional[RoamClassification] = None
    confidence: Optional[RoamConfidence] = None
