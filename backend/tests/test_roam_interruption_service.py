"""
Tests for app.services.roam_interruption_service.

_finalize/_classify_ms/_estimate_confidence are pure enough to test
directly with hand-built _Watch/_Sample objects - no need to actually run
the real-time polling loop (_run_watch sleeps for whole seconds at a time,
which would make for a slow, flaky test for no real benefit). The one
integration-style case worth covering against the real `db` fixture is
start_watch()'s immediate "nothing to measure" path, since that one skips
the background task entirely.
"""
from __future__ import annotations

import pytest

from app.database import roam_events_repo, targets_repo
from app.models.roam_event import RoamEventCreate
from app.models.settings import AppSettingsUpdate, NotificationPreferences
from app.models.target import TargetCreate
from app.services import notification_service, roam_interruption_service, settings_service
from app.services.roam_interruption_service import _classify_ms, _estimate_confidence, _finalize, _Sample, _Watch


def _make_watch(**kwargs) -> _Watch:
    """In production, _Watch's interface/ssid/new_bssid are required
    fields (start_watch copies them off the roam event). This helper just
    fills in throwaway values so tests that only care about the
    interruption/classification math don't each have to repeat them."""
    kwargs.setdefault("interface", "wlan0")
    kwargs.setdefault("ssid", "HomeNet")
    kwargs.setdefault("new_bssid", "BB:BB:BB:BB:BB:BB")
    return _Watch(**kwargs)


@pytest.fixture(autouse=True)
def sent_notifications(monkeypatch):
    """_finalize can fire a real desktop notification for a poor/failed
    roam - capture them instead, both so no test here ever depends on (or
    pops up) a real notify-send/osascript, and so tests can assert on what
    would have been sent."""
    sent = []

    async def fake_send(title, message, **kwargs):
        sent.append({"title": title, "message": message, **kwargs})

    monkeypatch.setattr(notification_service, "send", fake_send)
    return sent


class TestClassifyMs:
    @pytest.mark.parametrize("ms,expected", [
        (0, "excellent"), (49.9, "excellent"),
        (50, "good"), (149.9, "good"),
        (150, "fair"), (299.9, "fair"),
        (300, "poor"), (5000, "poor"),
    ])
    def test_boundaries(self, ms, expected):
        assert _classify_ms(ms) == expected


class TestEstimateConfidence:
    @pytest.mark.parametrize("total,expected", [
        (0, "unknown"), (1, "low"), (2, "medium"), (3, "medium"), (4, "high"), (20, "high"),
    ])
    def test_thresholds(self, total, expected):
        assert _estimate_confidence(total) == expected


@pytest.mark.asyncio
async def test_zero_packet_loss_classifies_by_peak_latency_not_duration(db, monkeypatch):
    """The headline behavior documented at the top of the module: a clean
    (no failed pings) roam is judged on the latency spike, not on how long
    it took to gather data - a fast, lossless roam should be able to read
    as 'excellent' even if the polling loop itself took a while to notice."""
    captured = {}
    async def fake_update(conn, event_id, **kwargs):
        captured.update(kwargs)
    monkeypatch.setattr(roam_events_repo, "update_interruption_result", fake_update)

    w = _make_watch(event_id=1, gateway_target_id=1, external_target_ids=[2], start_monotonic=0, timeout_seconds=30)
    w.gateway_interruption_ms = 4000.0  # would be "poor" if used for classification
    w.internet_interruption_ms = 4200.0
    w.samples = [
        _Sample(is_gateway=True, success=True, latency_ms=9.0),
        _Sample(is_gateway=False, success=True, latency_ms=35.0),
    ]
    await _finalize(db, w, timed_out=False)

    assert captured["packet_loss_during_pct"] == 0.0
    assert captured["peak_latency_ms"] == 35.0
    assert captured["classification"] == "excellent"  # by latency (35ms), not duration (4200ms)
    assert captured["success"] is True


@pytest.mark.asyncio
async def test_timeout_is_always_classified_failed(db, monkeypatch):
    captured = {}
    async def fake_update(conn, event_id, **kwargs):
        captured.update(kwargs)
    monkeypatch.setattr(roam_events_repo, "update_interruption_result", fake_update)

    w = _make_watch(event_id=2, gateway_target_id=1, external_target_ids=[2], start_monotonic=0, timeout_seconds=30)
    w.gateway_interruption_ms = 500.0
    w.internet_interruption_ms = None  # never recovered
    w.samples = [_Sample(is_gateway=True, success=True, latency_ms=10.0)]
    await _finalize(db, w, timed_out=True)

    assert captured["success"] is False
    assert captured["classification"] == "failed"


@pytest.mark.asyncio
async def test_nonzero_packet_loss_classifies_by_duration(db, monkeypatch):
    captured = {}
    async def fake_update(conn, event_id, **kwargs):
        captured.update(kwargs)
    monkeypatch.setattr(roam_events_repo, "update_interruption_result", fake_update)

    w = _make_watch(event_id=3, gateway_target_id=None, external_target_ids=[2], start_monotonic=0, timeout_seconds=30)
    w.internet_interruption_ms = 80.0  # "good" band
    w.samples = [
        _Sample(is_gateway=False, success=False, latency_ms=None),
        _Sample(is_gateway=False, success=True, latency_ms=20.0),
        _Sample(is_gateway=False, success=True, latency_ms=25.0),
    ]
    await _finalize(db, w, timed_out=False)

    assert captured["packet_loss_during_pct"] == pytest.approx(33.3, abs=0.1)
    assert captured["classification"] == "good"  # duration-based (80ms), latency (25ms) not used
    assert captured["confidence"] == "medium"


@pytest.mark.asyncio
async def test_sparse_clean_sample_is_low_confidence_but_still_classified(db, monkeypatch):
    captured = {}
    async def fake_update(conn, event_id, **kwargs):
        captured.update(kwargs)
    monkeypatch.setattr(roam_events_repo, "update_interruption_result", fake_update)

    w = _make_watch(event_id=4, gateway_target_id=1, external_target_ids=[], start_monotonic=0, timeout_seconds=30)
    w.gateway_interruption_ms = 6000.0
    w.samples = [_Sample(is_gateway=True, success=True, latency_ms=12.0)]
    await _finalize(db, w, timed_out=False)

    assert captured["confidence"] == "low"
    assert captured["classification"] == "excellent"  # the one real signal we have is a clean 12ms ping


@pytest.mark.asyncio
async def test_no_probe_targets_configured_marks_unknown_immediately(db):
    """start_watch's early-exit path: nothing to measure against, so it
    should update the row once with confidence='unknown' and everything
    else None, without spawning any background task."""
    event = await roam_events_repo.create_roam_event(db, RoamEventCreate(
        timestamp="2026-01-01T00:00:00+00:00", interface="wlan0", ssid="Home",
        previous_bssid="AA:AA", new_bssid="BB:BB",
    ))

    await roam_interruption_service.start_watch(db, event)

    updated = await roam_events_repo.get_roam_event(db, event.id)
    assert updated.confidence == "unknown"
    assert updated.classification is None
    assert updated.success is None
    assert roam_interruption_service.active_watch_count() == 0


@pytest.mark.asyncio
async def test_watch_is_tracked_while_targets_exist(db):
    """With a probe target configured, start_watch should spawn and track a
    real background task rather than resolving immediately."""
    await targets_repo.create_target(db, TargetCreate(name="Gateway", host="192.168.1.1", is_gateway=True))
    event = await roam_events_repo.create_roam_event(db, RoamEventCreate(
        timestamp="2026-01-01T00:00:00+00:00", interface="wlan0", ssid="Home",
        previous_bssid="AA:AA", new_bssid="BB:BB",
    ))

    await roam_interruption_service.start_watch(db, event)
    assert roam_interruption_service.active_watch_count() == 1

    await roam_interruption_service.cancel_all()
    assert roam_interruption_service.active_watch_count() == 0


async def _noop_update(conn, event_id, **kwargs):
    return None


@pytest.mark.asyncio
async def test_poor_roam_sends_a_notification(db, monkeypatch, sent_notifications):
    monkeypatch.setattr(roam_events_repo, "update_interruption_result", _noop_update)

    w = _make_watch(event_id=10, gateway_target_id=None, external_target_ids=[2], start_monotonic=0, timeout_seconds=30)
    w.internet_interruption_ms = 5000.0  # ping-interval-bounded gap -> "poor"
    w.samples = [
        _Sample(is_gateway=False, success=False, latency_ms=None),
        _Sample(is_gateway=False, success=True, latency_ms=20.0),
    ]
    await _finalize(db, w, timed_out=False)

    assert len(sent_notifications) == 1
    assert sent_notifications[0]["title"] == "Poor roam"
    assert sent_notifications[0]["urgency"] == "normal"
    assert "BB:BB:BB:BB:BB:BB" in sent_notifications[0]["message"]
    assert "HomeNet" in sent_notifications[0]["message"]


@pytest.mark.asyncio
async def test_failed_roam_sends_a_critical_notification(db, monkeypatch, sent_notifications):
    monkeypatch.setattr(roam_events_repo, "update_interruption_result", _noop_update)

    w = _make_watch(event_id=11, gateway_target_id=1, external_target_ids=[2], start_monotonic=0, timeout_seconds=30)
    w.samples = [_Sample(is_gateway=True, success=False, latency_ms=None)]
    await _finalize(db, w, timed_out=True)

    assert len(sent_notifications) == 1
    assert sent_notifications[0]["title"] == "Roam failed"
    assert sent_notifications[0]["urgency"] == "critical"


@pytest.mark.asyncio
@pytest.mark.parametrize("peak_latency_ms", [10.0, 100.0, 200.0])  # excellent / good / fair
async def test_acceptable_roams_do_not_notify(db, monkeypatch, sent_notifications, peak_latency_ms):
    monkeypatch.setattr(roam_events_repo, "update_interruption_result", _noop_update)

    w = _make_watch(event_id=12, gateway_target_id=None, external_target_ids=[2], start_monotonic=0, timeout_seconds=30)
    w.internet_interruption_ms = 1000.0
    w.samples = [_Sample(is_gateway=False, success=True, latency_ms=peak_latency_ms)]
    await _finalize(db, w, timed_out=False)

    assert sent_notifications == []


@pytest.mark.asyncio
async def test_on_poor_roam_setting_suppresses_the_notification(db, monkeypatch, sent_notifications):
    monkeypatch.setattr(roam_events_repo, "update_interruption_result", _noop_update)
    await settings_service.update_settings(
        db, AppSettingsUpdate(notifications=NotificationPreferences(on_poor_roam=False))
    )

    w = _make_watch(event_id=13, gateway_target_id=1, external_target_ids=[], start_monotonic=0, timeout_seconds=30)
    w.samples = [_Sample(is_gateway=True, success=False, latency_ms=None)]
    await _finalize(db, w, timed_out=True)  # would be "failed" -> would notify if enabled

    assert sent_notifications == []
