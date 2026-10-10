from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

WalkTestStatus = Literal["recording", "stopped"]


class WalkTestCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    site: Optional[str] = Field(default=None, max_length=100)
    area: Optional[str] = Field(default=None, max_length=100)
    interface: str
    target_ids: List[int] = Field(default_factory=list)


class WalkTestOut(BaseModel):
    id: int
    name: str
    site: Optional[str] = None
    area: Optional[str] = None
    interface: str
    target_ids: List[int]
    status: WalkTestStatus
    started_at: str
    ended_at: Optional[str] = None
    sample_count: int = 0


class WalkTestSampleOut(BaseModel):
    id: int
    walk_test_id: int
    timestamp: str

    interface_state: Optional[str] = None
    ssid: Optional[str] = None
    bssid: Optional[str] = None
    frequency_mhz: Optional[int] = None
    channel: Optional[int] = None
    band: Optional[str] = None
    rssi_dbm: Optional[int] = None
    signal_pct: Optional[int] = None
    noise_floor_dbm: Optional[int] = None
    snr_db: Optional[int] = None
    phy_mode: Optional[str] = None
    channel_width_mhz: Optional[int] = None
    mcs_index: Optional[int] = None
    tx_bitrate_mbps: Optional[float] = None
    rx_bitrate_mbps: Optional[float] = None
    phy_rate_mbps: Optional[float] = None

    # None across all three when the session had no target_ids selected -
    # walk-test mode never requires internet connectivity to run.
    latency_ms: Optional[float] = None
    packet_loss_pct: Optional[float] = None
    reachable: Optional[bool] = None
