from __future__ import annotations

from app.models.settings import ClassificationThresholds
from app.services.quality_service import classify

T = ClassificationThresholds()


def test_classify_excellent():
    assert classify(10, 0, T) == "excellent"


def test_classify_good():
    assert classify(45, 1.5, T) == "good"


def test_classify_fair_by_latency():
    assert classify(80, 0, T) == "fair"


def test_classify_fair_by_loss():
    assert classify(200, 3, T) == "fair"


def test_classify_poor():
    assert classify(500, 10, T) == "poor"


def test_classify_unknown_without_data():
    assert classify(None, None, T) == "unknown"


def test_classify_respects_custom_thresholds():
    custom = ClassificationThresholds(
        excellent_latency_ms=500, excellent_packet_loss_pct=50
    )
    assert classify(400, 10, custom) == "excellent"


# --------------------------------------------------------------------------
# compute_wireless_quality_score (Stage 12) - against the real db fixture,
# exercising the actual repo layer rather than mocking it.
# --------------------------------------------------------------------------
from datetime import datetime, timedelta, timezone

import pytest

from app.database import (
    measurements_repo,
    roam_events_repo,
    targets_repo,
    wifi_samples_repo,
)
from app.models.measurement import MeasurementCreate
from app.models.roam_event import RoamEventCreate
from app.models.settings import AppSettings
from app.models.target import TargetCreate
from app.monitoring.wifi.models import WifiMetrics
from app.services import quality_service

NOW = datetime.now(timezone.utc)


def _wifi_sample(rssi=-50, state="connected", minutes_ago=0):
    return WifiMetrics(
        timestamp=(NOW - timedelta(minutes=minutes_ago)).isoformat(),
        interface="wlan0",
        interface_state=state,
        rssi_dbm=rssi,
    )


@pytest.mark.asyncio
async def test_score_is_high_when_everything_is_healthy(db):
    target = await targets_repo.create_target(
        db, TargetCreate(name="DNS", host="1.1.1.1")
    )
    await measurements_repo.insert_measurement(
        db,
        MeasurementCreate(
            target_id=target.id,
            timestamp=NOW.isoformat(),
            latency_ms=10.0,
            packet_loss=0.0,
            jitter_ms=2.0,
            success=True,
        ),
    )
    await wifi_samples_repo.insert_sample(db, _wifi_sample(rssi=-45))

    score = await quality_service.compute_wireless_quality_score(
        db, "wlan0", AppSettings()
    )
    assert score is not None and score >= 90


@pytest.mark.asyncio
async def test_missing_rssi_does_not_lower_an_otherwise_healthy_score(db):
    """The spec's explicit rule: an optional metric being unsupported must
    never reduce the score - it comes out of the average entirely."""
    target = await targets_repo.create_target(
        db, TargetCreate(name="DNS", host="1.1.1.1")
    )
    await measurements_repo.insert_measurement(
        db,
        MeasurementCreate(
            target_id=target.id,
            timestamp=NOW.isoformat(),
            latency_ms=10.0,
            packet_loss=0.0,
            jitter_ms=2.0,
            success=True,
        ),
    )
    # No wifi_samples row inserted at all - RSSI is genuinely unavailable.

    score = await quality_service.compute_wireless_quality_score(
        db, "wlan0", AppSettings()
    )
    assert score is not None and score >= 90


@pytest.mark.asyncio
async def test_no_data_at_all_returns_none_not_zero(db):
    score = await quality_service.compute_wireless_quality_score(
        db, "wlan0", AppSettings()
    )
    assert score is None


@pytest.mark.asyncio
async def test_recent_disconnects_reduce_the_score(db):
    target = await targets_repo.create_target(
        db, TargetCreate(name="DNS", host="1.1.1.1")
    )
    await measurements_repo.insert_measurement(
        db,
        MeasurementCreate(
            target_id=target.id,
            timestamp=NOW.isoformat(),
            latency_ms=10.0,
            packet_loss=0.0,
            jitter_ms=2.0,
            success=True,
        ),
    )
    # Two disconnect transitions: connected -> disconnected -> connected -> disconnected
    for minutes_ago, state in [
        (4, "connected"),
        (3, "disconnected"),
        (2, "connected"),
        (1, "disconnected"),
    ]:
        await wifi_samples_repo.insert_sample(
            db, _wifi_sample(state=state, minutes_ago=minutes_ago)
        )
    await wifi_samples_repo.insert_sample(db, _wifi_sample(rssi=-45, minutes_ago=0))

    settings = AppSettings(wireless_quality_window_minutes=30)
    score = await quality_service.compute_wireless_quality_score(db, "wlan0", settings)
    assert score is not None
    assert score < 95, "two recent disconnects should visibly reduce the score"


@pytest.mark.asyncio
async def test_recent_failed_roams_reduce_the_score(db):
    target = await targets_repo.create_target(
        db, TargetCreate(name="DNS", host="1.1.1.1")
    )
    await measurements_repo.insert_measurement(
        db,
        MeasurementCreate(
            target_id=target.id,
            timestamp=NOW.isoformat(),
            latency_ms=10.0,
            packet_loss=0.0,
            jitter_ms=2.0,
            success=True,
        ),
    )
    await wifi_samples_repo.insert_sample(db, _wifi_sample(rssi=-45))
    event = await roam_events_repo.create_roam_event(
        db,
        RoamEventCreate(
            timestamp=NOW.isoformat(),
            interface="wlan0",
            ssid="Home",
            previous_bssid="AA:AA",
            new_bssid="BB:BB",
        ),
    )
    await roam_events_repo.update_interruption_result(
        db,
        event.id,
        gateway_interruption_ms=None,
        internet_interruption_ms=None,
        packet_loss_during_pct=None,
        peak_latency_ms=None,
        success=False,
        classification="failed",
        confidence="high",
    )

    score = await quality_service.compute_wireless_quality_score(
        db, "wlan0", AppSettings()
    )
    assert score is not None and score <= 85, (
        "a recent failed roam should visibly reduce the score"
    )


@pytest.mark.asyncio
async def test_old_disconnects_outside_the_window_are_not_counted(db):
    target = await targets_repo.create_target(
        db, TargetCreate(name="DNS", host="1.1.1.1")
    )
    await measurements_repo.insert_measurement(
        db,
        MeasurementCreate(
            target_id=target.id,
            timestamp=NOW.isoformat(),
            latency_ms=10.0,
            packet_loss=0.0,
            jitter_ms=2.0,
            success=True,
        ),
    )
    # A disconnect from 90 minutes ago - well outside a 30-minute window.
    await wifi_samples_repo.insert_sample(
        db, _wifi_sample(state="connected", minutes_ago=95)
    )
    await wifi_samples_repo.insert_sample(
        db, _wifi_sample(state="disconnected", minutes_ago=90)
    )
    await wifi_samples_repo.insert_sample(
        db, _wifi_sample(state="connected", minutes_ago=85)
    )
    await wifi_samples_repo.insert_sample(db, _wifi_sample(rssi=-45, minutes_ago=0))

    score = await quality_service.compute_wireless_quality_score(
        db, "wlan0", AppSettings(wireless_quality_window_minutes=30)
    )
    assert score is not None and score >= 90
