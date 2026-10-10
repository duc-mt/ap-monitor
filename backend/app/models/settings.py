from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ClassificationThresholds(BaseModel):
    """
    Boundaries for the quality classifier. Never hard-coded into the UI -
    the UI reads these back from /api/settings and renders whatever it is
    given, so changing a number here changes the dashboard immediately.
    """
    excellent_latency_ms: float = 30
    excellent_packet_loss_pct: float = 1
    good_latency_ms: float = 60
    good_packet_loss_pct: float = 2
    fair_latency_ms: float = 100
    fair_packet_loss_pct: float = 5


class NotificationPreferences(BaseModel):
    on_offline: bool = True
    on_online: bool = True
    on_degraded: bool = True
    on_latency_threshold: bool = True
    on_packet_loss_threshold: bool = True
    on_poor_roam: bool = True
    cooldown_seconds: int = Field(default=60, ge=0, le=3600)


class AppSettings(BaseModel):
    # Monitoring
    ping_timeout_seconds: float = Field(default=2.0, ge=0.2, le=30)
    pings_per_check: int = Field(
        default=3, ge=1, le=10,
        description="Number of echo/connect attempts per check ('retries' in the UI)."
    )
    default_target_interval_seconds: int = Field(default=5, ge=1, le=3600)
    wifi_poll_interval_seconds: int = Field(
        default=5, ge=1, le=300,
        description="How often the background loop polls WiFi metrics and checks for roaming (Stage 9)."
    )
    roam_watch_timeout_seconds: int = Field(
        default=30, ge=5, le=300,
        description=(
            "How long (Stage 10) to keep watching connectivity after a confirmed roam before giving "
            "up and marking it 'failed'. Also bounds how stale the 'Estimated Connectivity "
            "Interruption' can be - this is a ping-interval-limited estimate, never exact radio-layer timing."
        ),
    )
    walk_test_sample_interval_ms: int = Field(
        default=500, ge=100, le=5000,
        description="How often a recording walk-test session samples WiFi metrics (Stage 11)."
    )
    wireless_quality_window_minutes: int = Field(
        default=30, ge=5, le=1440,
        description=(
            "Lookback window (Stage 12) the 0-100 Wireless Quality Score uses for its "
            "latency/packet-loss/jitter averages and its disconnect/failed-roam penalty counts. "
            "The RSSI component always uses the single latest reading instead, since averaging "
            "signal strength over a long window would mask a drop that just happened."
        ),
    )

    # Alert thresholds (separate from the quality classifier - these drive
    # desktop notifications specifically).
    latency_warning_threshold_ms: float = 150
    packet_loss_warning_threshold_pct: float = 5

    # Connectivity state model (Stage 8): how many enabled non-gateway
    # targets must succeed for the headline state to read "available"
    # rather than "degraded". "any" (default) treats one working target as
    # enough to call the internet up at all, with anything less than all of
    # them succeeding reported as "degraded" rather than fully available;
    # "all" is stricter and folds that same partial-failure case into
    # "unavailable" instead - see connectivity_service._derive_overall.
    internet_quorum: Literal["any", "all"] = "any"

    notifications: NotificationPreferences = Field(default_factory=NotificationPreferences)
    classification: ClassificationThresholds = Field(default_factory=ClassificationThresholds)

    # Data lifecycle
    data_retention_days: int = Field(default=30, ge=1, le=3650)

    # Presentation / misc
    start_on_boot: bool = False
    theme: Literal["light", "dark", "system"] = "system"
    language: str = "en"


class AppSettingsUpdate(BaseModel):
    """All fields optional so PUT /api/settings can be a partial patch."""
    ping_timeout_seconds: Optional[float] = Field(default=None, ge=0.2, le=30)
    pings_per_check: Optional[int] = Field(default=None, ge=1, le=10)
    default_target_interval_seconds: Optional[int] = Field(default=None, ge=1, le=3600)
    wifi_poll_interval_seconds: Optional[int] = Field(default=None, ge=1, le=300)
    roam_watch_timeout_seconds: Optional[int] = Field(default=None, ge=5, le=300)
    walk_test_sample_interval_ms: Optional[int] = Field(default=None, ge=100, le=5000)
    wireless_quality_window_minutes: Optional[int] = Field(default=None, ge=5, le=1440)
    latency_warning_threshold_ms: Optional[float] = None
    packet_loss_warning_threshold_pct: Optional[float] = None
    internet_quorum: Optional[Literal["any", "all"]] = None
    notifications: Optional[NotificationPreferences] = None
    classification: Optional[ClassificationThresholds] = None
    data_retention_days: Optional[int] = Field(default=None, ge=1, le=3650)
    start_on_boot: Optional[bool] = None
    theme: Optional[Literal["light", "dark", "system"]] = None
    language: Optional[str] = None
