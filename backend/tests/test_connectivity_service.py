from __future__ import annotations

from datetime import datetime, timezone

UTC = timezone.utc

import pytest
from app.database import measurements_repo, targets_repo
from app.models.measurement import MeasurementCreate
from app.models.settings import AppSettings
from app.models.target import TargetCreate
from app.services import connectivity_service, notification_service


async def _measure(db, target_id, *, success: bool):
    await measurements_repo.insert_measurement(
        db,
        MeasurementCreate(
            target_id=target_id,
            timestamp=datetime.now(UTC).isoformat(),
            latency_ms=10.0 if success else None,
            packet_loss=0.0 if success else 100.0,
            jitter_ms=None,
            success=success,
        ),
    )


def _capture_sends(monkeypatch):
    sent = []

    async def fake_send(title, message, **kwargs):
        sent.append(title)

    monkeypatch.setattr(notification_service, "send", fake_send)
    return sent


@pytest.mark.asyncio
async def test_first_evaluation_does_not_notify(db, monkeypatch):
    sent = _capture_sends(monkeypatch)
    target = await targets_repo.create_target(
        db, TargetCreate(name="DNS", host="1.1.1.1")
    )
    await _measure(db, target.id, success=True)

    status = await connectivity_service.evaluate(db, AppSettings())
    assert status.overall == "internet_available"
    assert sent == []


@pytest.mark.asyncio
async def test_transition_to_internet_unavailable_notifies(db, monkeypatch):
    sent = _capture_sends(monkeypatch)
    target = await targets_repo.create_target(
        db, TargetCreate(name="DNS", host="1.1.1.1")
    )

    await _measure(db, target.id, success=True)
    await connectivity_service.evaluate(db, AppSettings())  # baseline: available

    await _measure(db, target.id, success=False)
    status = await connectivity_service.evaluate(db, AppSettings())

    assert status.overall == "internet_unavailable"
    assert any("lost" in t.lower() for t in sent)


@pytest.mark.asyncio
async def test_transition_back_to_available_notifies(db, monkeypatch):
    sent = _capture_sends(monkeypatch)
    target = await targets_repo.create_target(
        db, TargetCreate(name="DNS", host="1.1.1.1")
    )

    await _measure(db, target.id, success=False)
    await connectivity_service.evaluate(db, AppSettings())  # baseline: unavailable

    await _measure(db, target.id, success=True)
    status = await connectivity_service.evaluate(db, AppSettings())

    assert status.overall == "internet_available"
    assert any("restored" in t.lower() for t in sent)


@pytest.mark.asyncio
async def test_respects_disabled_notification_preference(db, monkeypatch):
    sent = _capture_sends(monkeypatch)
    target = await targets_repo.create_target(
        db, TargetCreate(name="DNS", host="1.1.1.1")
    )
    settings = AppSettings()
    settings.notifications.on_offline = False

    await _measure(db, target.id, success=True)
    await connectivity_service.evaluate(db, settings)

    await _measure(db, target.id, success=False)
    await connectivity_service.evaluate(db, settings)

    assert sent == []


@pytest.mark.asyncio
async def test_gateway_unavailable_takes_precedence_over_internet_state(db):
    gateway = await targets_repo.create_target(
        db, TargetCreate(name="Gateway", host="192.168.1.1", is_gateway=True)
    )
    dns = await targets_repo.create_target(db, TargetCreate(name="DNS", host="1.1.1.1"))
    await _measure(db, gateway.id, success=False)  # LAN is down
    await _measure(db, dns.id, success=True)  # yet somehow DNS still answers

    status = await connectivity_service.evaluate(db, AppSettings())
    assert status.overall == "gateway_unavailable"
    assert status.gateway_reachable is False


@pytest.mark.asyncio
async def test_gateway_available_with_no_external_targets_configured(db):
    gateway = await targets_repo.create_target(
        db, TargetCreate(name="Gateway", host="192.168.1.1", is_gateway=True)
    )
    await _measure(db, gateway.id, success=True)

    status = await connectivity_service.evaluate(db, AppSettings())
    assert status.overall == "gateway_available"
    assert status.internet_state is None


@pytest.mark.asyncio
async def test_any_quorum_reports_degraded_on_partial_failure(db):
    cloudflare = await targets_repo.create_target(
        db, TargetCreate(name="Cloudflare", host="1.1.1.1")
    )
    google = await targets_repo.create_target(
        db, TargetCreate(name="Google", host="8.8.8.8")
    )
    await _measure(db, cloudflare.id, success=True)
    await _measure(db, google.id, success=False)

    settings = AppSettings(internet_quorum="any")
    status = await connectivity_service.evaluate(db, settings)
    assert status.internet_state == "degraded"
    assert status.overall == "degraded"


@pytest.mark.asyncio
async def test_all_quorum_treats_partial_failure_as_unavailable(db):
    cloudflare = await targets_repo.create_target(
        db, TargetCreate(name="Cloudflare", host="1.1.1.1")
    )
    google = await targets_repo.create_target(
        db, TargetCreate(name="Google", host="8.8.8.8")
    )
    await _measure(db, cloudflare.id, success=True)
    await _measure(db, google.id, success=False)

    settings = AppSettings(internet_quorum="all")
    status = await connectivity_service.evaluate(db, settings)
    assert status.internet_state == "unavailable"
    assert status.overall == "internet_unavailable"


@pytest.mark.asyncio
async def test_wifi_disconnected_overrides_healthy_targets(db):
    target = await targets_repo.create_target(
        db, TargetCreate(name="DNS", host="1.1.1.1")
    )
    await _measure(db, target.id, success=True)

    status = await connectivity_service.evaluate(
        db, AppSettings(), wifi_connected=False
    )
    assert status.overall == "wifi_disconnected"
    assert status.wifi_connected is False


@pytest.mark.asyncio
async def test_wifi_connected_none_does_not_mask_internet_state(db):
    """The default (no wifi_connected argument at all) must fall through to
    ping-based reasoning, not silently become 'wifi_disconnected' - this is
    what keeps every pre-Stage-9 caller (and every other test in this file)
    correct without needing to pass a WiFi reading."""
    target = await targets_repo.create_target(
        db, TargetCreate(name="DNS", host="1.1.1.1")
    )
    await _measure(db, target.id, success=True)

    status = await connectivity_service.evaluate(db, AppSettings())
    assert status.wifi_connected is None
    assert status.overall == "internet_available"


@pytest.mark.asyncio
async def test_no_data_at_all_is_unknown_not_a_fabricated_state(db):
    status = await connectivity_service.evaluate(db, AppSettings())
    assert status.overall == "unknown"
    assert status.gateway_reachable is None
    assert status.internet_state is None


@pytest.mark.asyncio
async def test_degraded_transition_notifies_when_enabled(db, monkeypatch):
    sent = _capture_sends(monkeypatch)
    cloudflare = await targets_repo.create_target(
        db, TargetCreate(name="Cloudflare", host="1.1.1.1")
    )
    google = await targets_repo.create_target(
        db, TargetCreate(name="Google", host="8.8.8.8")
    )

    await _measure(db, cloudflare.id, success=True)
    await _measure(db, google.id, success=True)
    await connectivity_service.evaluate(db, AppSettings())  # baseline: available

    await _measure(db, google.id, success=False)
    status = await connectivity_service.evaluate(db, AppSettings())

    assert status.overall == "degraded"
    assert any("degraded" in t.lower() for t in sent)


@pytest.mark.asyncio
async def test_compute_status_never_notifies_even_across_a_real_transition(
    db, monkeypatch
):
    """The entire point of the Stage 12 split: compute_status() must be
    safe to call from a read-only endpoint (e.g. on every dashboard poll)
    without ever firing a notification, even when the underlying data
    genuinely transitions from healthy to broken between calls."""
    sent = _capture_sends(monkeypatch)
    target = await targets_repo.create_target(
        db, TargetCreate(name="DNS", host="1.1.1.1")
    )

    await _measure(db, target.id, success=True)
    status = await connectivity_service.compute_status(db, AppSettings())
    assert status.overall == "internet_available"

    await _measure(db, target.id, success=False)
    status = await connectivity_service.compute_status(db, AppSettings())
    assert status.overall == "internet_unavailable"

    assert sent == [], (
        "compute_status() must never send a notification, transition or not"
    )


@pytest.mark.asyncio
async def test_compute_status_does_not_disturb_evaluate_s_transition_tracking(
    db, monkeypatch
):
    """Repeatedly calling compute_status() (as a status endpoint would,
    polled far more often than the scheduler's own tick) must not corrupt
    the module-level state evaluate() uses to detect transitions."""
    sent = _capture_sends(monkeypatch)
    target = await targets_repo.create_target(
        db, TargetCreate(name="DNS", host="1.1.1.1")
    )

    await _measure(db, target.id, success=True)
    await connectivity_service.evaluate(
        db, AppSettings()
    )  # baseline: available, no notification (first ever)

    # Simulate a burst of read-only status polls in between scheduler ticks.
    for _ in range(5):
        await connectivity_service.compute_status(db, AppSettings())

    await _measure(db, target.id, success=False)
    await connectivity_service.evaluate(
        db, AppSettings()
    )  # the real transition evaluate() should catch

    assert sent == ["Connectivity lost"], (
        "the interleaved compute_status() polls should not have consumed or confused "
        "evaluate()'s transition tracking"
    )
