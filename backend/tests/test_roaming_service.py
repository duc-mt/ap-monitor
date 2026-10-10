"""
Tests for the roaming detection state machine. No WiFi adapter mocking is
needed here - roaming_service.evaluate() takes a plain WifiMetrics reading
as input, so these tests just hand it a scripted sequence of readings and
check the resulting states and recorded roam_events rows against a real
(temp, per-test) database via the `db` fixture.
"""

from __future__ import annotations

import pytest

from app.database import roam_events_repo
from app.monitoring.wifi.models import WifiMetrics
from app.services import roaming_service


def _reading(bssid, *, ssid="HomeNet", state="connected", ipv4=None, rssi=-50):
    return WifiMetrics(
        timestamp="2026-01-01T00:00:00+00:00",
        interface="wlan0",
        interface_state=state,
        ssid=ssid,
        bssid=bssid,
        ipv4_addresses=ipv4,
        rssi_dbm=rssi,
    )


@pytest.mark.asyncio
async def test_single_flicker_is_not_recorded_as_a_roam(db):
    await roaming_service.evaluate(db, _reading("AA:AA"))
    await roaming_service.evaluate(db, _reading("BB:BB"))  # candidate
    state = await roaming_service.evaluate(db, _reading("AA:AA"))  # reverts - a flicker

    assert state == "connected"
    events = await roam_events_repo.list_roam_events(db)
    assert events == []


@pytest.mark.asyncio
async def test_bssid_change_held_for_two_ticks_is_confirmed(db):
    await roaming_service.evaluate(db, _reading("AA:AA", rssi=-40))
    s1 = await roaming_service.evaluate(db, _reading("BB:BB", rssi=-60))  # candidate
    s2 = await roaming_service.evaluate(db, _reading("BB:BB", rssi=-58))  # confirmed

    assert s1 == "roam_candidate"
    assert s2 == "roaming"

    events = await roam_events_repo.list_roam_events(db)
    assert len(events) == 1
    event = events[0]
    assert event.previous_bssid == "AA:AA"
    assert event.new_bssid == "BB:BB"
    assert event.previous_rssi_dbm == -40
    assert (
        event.new_rssi_dbm == -60
    )  # the *candidate* reading's RSSI, not the confirming tick's
    assert event.ssid == "HomeNet"
    # No probe targets are configured in this fixture, so the interruption
    # watch has nothing to measure: it must say so ("unknown" confidence) and
    # leave the verdict fields unset - never default them to 0/False.
    assert event.classification is None
    assert event.confidence == "unknown"
    assert event.success is None


@pytest.mark.asyncio
async def test_state_lifecycle_after_confirmation(db):
    await roaming_service.evaluate(db, _reading("AA:AA"))
    await roaming_service.evaluate(db, _reading("BB:BB"))  # candidate
    await roaming_service.evaluate(db, _reading("BB:BB"))  # -> roaming
    s3 = await roaming_service.evaluate(db, _reading("BB:BB"))  # -> stabilizing
    s4 = await roaming_service.evaluate(db, _reading("BB:BB"))  # -> connected

    assert s3 == "stabilizing"
    assert s4 == "connected"


@pytest.mark.asyncio
async def test_different_ssid_is_a_fresh_connection_not_a_roam(db):
    await roaming_service.evaluate(db, _reading("AA:AA", ssid="HomeNet"))
    state = await roaming_service.evaluate(db, _reading("CC:CC", ssid="CoffeeShop"))

    assert state == "connected"
    assert await roam_events_repo.list_roam_events(db) == []


@pytest.mark.asyncio
async def test_disconnect_then_reconnect_is_not_a_roam(db):
    await roaming_service.evaluate(db, _reading("AA:AA"))
    disconnected = await roaming_service.evaluate(
        db, _reading(None, state="disconnected")
    )
    reconnected = await roaming_service.evaluate(db, _reading("AA:AA"))

    assert disconnected == "disconnected"
    assert reconnected == "connected"
    assert await roam_events_repo.list_roam_events(db) == []


@pytest.mark.asyncio
async def test_scanning_state_maps_to_connecting(db):
    state = await roaming_service.evaluate(db, _reading(None, state="scanning"))
    assert state == "connecting"


@pytest.mark.asyncio
async def test_ip_change_is_flagged_on_the_roam_event(db):
    await roaming_service.evaluate(db, _reading("AA:AA", ipv4=["192.168.1.42"]))
    await roaming_service.evaluate(db, _reading("BB:BB", ipv4=["192.168.2.17"]))
    await roaming_service.evaluate(db, _reading("BB:BB", ipv4=["192.168.2.17"]))

    events = await roam_events_repo.list_roam_events(db)
    assert events[0].ip_changed is True
    assert events[0].previous_ipv4 == ["192.168.1.42"]
    assert events[0].new_ipv4 == ["192.168.2.17"]


@pytest.mark.asyncio
async def test_two_consecutive_genuine_roams_each_recorded_once(db):
    await roaming_service.evaluate(db, _reading("AA:AA"))
    await roaming_service.evaluate(db, _reading("BB:BB"))
    await roaming_service.evaluate(db, _reading("BB:BB"))  # confirmed A->B
    await roaming_service.evaluate(db, _reading("BB:BB"))
    await roaming_service.evaluate(db, _reading("BB:BB"))
    await roaming_service.evaluate(db, _reading("CC:CC"))
    await roaming_service.evaluate(db, _reading("CC:CC"))  # confirmed B->C

    events = await roam_events_repo.list_roam_events(db)
    assert len(events) == 2
    pairs = {(e.previous_bssid, e.new_bssid) for e in events}
    assert pairs == {("AA:AA", "BB:BB"), ("BB:BB", "CC:CC")}


@pytest.mark.asyncio
async def test_readings_without_a_bssid_never_create_or_confirm_a_roam(db):
    """macOS/Windows withhold the BSSID without Location permission, and some
    drivers drop it for a tick mid-roam. None is "no information", not a new AP:
    two Nones in a row must not be confirmed as a roam to AP None."""
    await roaming_service.evaluate(db, _reading("AA:AA"))
    await roaming_service.evaluate(db, _reading(None))
    state = await roaming_service.evaluate(db, _reading(None))
    assert state == "connected"
    assert await roam_events_repo.list_roam_events(db) == []


@pytest.mark.asyncio
async def test_a_missing_bssid_does_not_hide_a_real_roam_that_follows(db):
    await roaming_service.evaluate(db, _reading("AA:AA"))
    await roaming_service.evaluate(db, _reading(None))
    await roaming_service.evaluate(db, _reading("BB:BB"))
    await roaming_service.evaluate(db, _reading("BB:BB"))
    (event,) = await roam_events_repo.list_roam_events(db)
    assert (event.previous_bssid, event.new_bssid) == ("AA:AA", "BB:BB")
