"""
Tests for app.services.walk_test_service, against the real `db` fixture.
The sample interval is set to the smallest value the settings model allows
(100ms - see AppSettings.walk_test_sample_interval_ms) so these tests don't
have to wait around at the spec's 500ms default.
"""

from __future__ import annotations

import asyncio

import pytest

from app.database import targets_repo, walk_tests_repo
from app.models.settings import AppSettingsUpdate
from app.models.target import TargetCreate
from app.models.walk_test import WalkTestCreate
from app.monitoring import wifi
from app.monitoring.wifi.models import WifiMetrics
from app.services import settings_service, walk_test_service


async def _fast_interval(db, ms=100):
    await settings_service.update_settings(
        db, AppSettingsUpdate(walk_test_sample_interval_ms=ms)
    )


@pytest.mark.asyncio
async def test_start_creates_a_recording_session(db):
    await _fast_interval(db)
    result = await walk_test_service.start_session(
        db,
        WalkTestCreate(
            name="Office walk",
            site="HQ",
            area="2nd floor",
            interface="wlan0",
            target_ids=[],
        ),
    )
    try:
        assert result.status == "recording"
        assert result.name == "Office walk"
        assert walk_test_service.is_recording()
        assert walk_test_service.active_walk_test_id() == result.id
    finally:
        await walk_test_service.stop_session(db, result.id)


@pytest.mark.asyncio
async def test_second_concurrent_session_is_rejected(db):
    await _fast_interval(db)
    first = await walk_test_service.start_session(
        db,
        WalkTestCreate(
            name="First",
            site=None,
            area=None,
            interface="wlan0",
            target_ids=[],
        ),
    )
    try:
        with pytest.raises(RuntimeError):
            await walk_test_service.start_session(
                db,
                WalkTestCreate(
                    name="Second",
                    site=None,
                    area=None,
                    interface="wlan0",
                    target_ids=[],
                ),
            )
    finally:
        await walk_test_service.stop_session(db, first.id)


@pytest.mark.asyncio
async def test_stopping_an_already_stopped_session_is_idempotent(db):
    await _fast_interval(db)
    result = await walk_test_service.start_session(
        db,
        WalkTestCreate(
            name="Walk",
            site=None,
            area=None,
            interface="wlan0",
            target_ids=[],
        ),
    )
    first_stop = await walk_test_service.stop_session(db, result.id)
    second_stop = await walk_test_service.stop_session(db, result.id)
    assert first_stop.status == second_stop.status == "stopped"


@pytest.mark.asyncio
async def test_stopping_a_nonexistent_session_raises(db):
    with pytest.raises(ValueError):
        await walk_test_service.stop_session(db, 999999)


@pytest.mark.asyncio
async def test_sample_loop_writes_wifi_metrics_rows(db, monkeypatch):
    await _fast_interval(db)

    async def fake_get_wifi_metrics(interface, use_cache=True):
        return WifiMetrics(
            timestamp="t",
            interface=interface,
            interface_state="connected",
            ssid="TestNet",
            bssid="AA:AA:AA:AA:AA:AA",
            channel=6,
            rssi_dbm=-52,
        )

    monkeypatch.setattr(wifi, "get_wifi_metrics", fake_get_wifi_metrics)

    result = await walk_test_service.start_session(
        db,
        WalkTestCreate(
            name="Sampling test",
            site=None,
            area=None,
            interface="wlan0",
            target_ids=[],
        ),
    )
    await asyncio.sleep(0.5)  # several 100ms ticks
    stopped = await walk_test_service.stop_session(db, result.id)

    samples = await walk_tests_repo.list_samples(db, result.id)
    assert len(samples) >= 3
    assert stopped.sample_count == len(samples)
    assert samples[0].ssid == "TestNet"
    assert samples[0].rssi_dbm == -52
    # No targets were selected - latency fields must stay None throughout,
    # never fabricated to 0 or some other placeholder.
    assert all(s.latency_ms is None and s.reachable is None for s in samples)


@pytest.mark.asyncio
async def test_sample_loop_survives_no_active_wifi_interface(db, monkeypatch):
    """Walk-test mode must keep sampling (with WiFi fields left None) even
    when there's no active WiFi association, rather than crashing the loop."""

    async def fake_get_wifi_metrics(interface, use_cache=True):
        raise RuntimeError("No active WiFi interface")

    monkeypatch.setattr(wifi, "get_wifi_metrics", fake_get_wifi_metrics)
    await _fast_interval(db)

    result = await walk_test_service.start_session(
        db,
        WalkTestCreate(
            name="No WiFi",
            site=None,
            area=None,
            interface="wlan0",
            target_ids=[],
        ),
    )
    await asyncio.sleep(0.4)
    await walk_test_service.stop_session(db, result.id)

    samples = await walk_tests_repo.list_samples(db, result.id)
    assert len(samples) >= 2
    assert all(s.ssid is None and s.rssi_dbm is None for s in samples)


@pytest.mark.asyncio
async def test_ping_loop_updates_latency_when_targets_selected(db, monkeypatch):
    target = await targets_repo.create_target(
        db, TargetCreate(name="Gateway", host="192.168.1.1")
    )

    async def fake_get_wifi_metrics(interface, use_cache=True):
        return WifiMetrics(
            timestamp="t", interface=interface, interface_state="connected"
        )

    monkeypatch.setattr(wifi, "get_wifi_metrics", fake_get_wifi_metrics)

    class FakePingResult:
        avg_latency_ms = 12.5
        loss_pct = 0.0
        succeeded = 1

    async def fake_run_check(**kwargs):
        return FakePingResult()

    monkeypatch.setattr(walk_test_service, "run_check", fake_run_check)

    await _fast_interval(db)
    result = await walk_test_service.start_session(
        db,
        WalkTestCreate(
            name="With target",
            site=None,
            area=None,
            interface="wlan0",
            target_ids=[target.id],
        ),
    )
    await asyncio.sleep(1.1)  # the ping loop only ticks once per second
    await walk_test_service.stop_session(db, result.id)

    samples = await walk_tests_repo.list_samples(db, result.id)
    assert any(s.latency_ms == 12.5 and s.reachable is True for s in samples)
