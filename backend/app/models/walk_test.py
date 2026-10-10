from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

WalkTestStatus = Literal["recording", "stopped"]


class WalkTestCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    site: str | None = Field(default=None, max_length=100)
    area: str | None = Field(default=None, max_length=100)
    interface: str
    target_ids: list[int] = Field(default_factory=list)


class WalkTestOut(BaseModel):
    id: int
    name: str
    site: str | None = None
    area: str | None = None
    interface: str
    target_ids: list[int]
    status: WalkTestStatus
    started_at: str
    ended_at: str | None = None
    sample_count: int = 0


class WalkTestSampleOut(BaseModel):
    id: int
    walk_test_id: int
    timestamp: str

    interface_state: str | None = None
    ssid: str | None = None
    bssid: str | None = None
    frequency_mhz: int | None = None
    channel: int | None = None
    band: str | None = None
    rssi_dbm: int | None = None
    signal_pct: int | None = None
    noise_floor_dbm: int | None = None
    snr_db: int | None = None
    phy_mode: str | None = None
    channel_width_mhz: int | None = None
    mcs_index: int | None = None
    tx_bitrate_mbps: float | None = None
    rx_bitrate_mbps: float | None = None
    phy_rate_mbps: float | None = None

    # None across all three when the session had no target_ids selected -
    # walk-test mode never requires internet connectivity to run.
    latency_ms: float | None = None
    packet_loss_pct: float | None = None
    reachable: bool | None = None
