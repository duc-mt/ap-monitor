"""Tests for the AP/signal analysis that backs the dashboard timeline and
the Walk Test results page, plus the endpoints that expose it."""
from __future__ import annotations

from types import SimpleNamespace as N

import pytest

from app.api import walk_tests as walk_tests_api
from app.api import wifi as wifi_api
from app.database import walk_tests_repo, wifi_samples_repo
from app.monitoring.wifi.models import WifiMetrics
from app.services.ap_analysis_service import analyze


def smp(sec, bssid, rssi, state="connected", ssid="Net", channel=36, band="5GHz"):
    return N(
        timestamp=f"2026-01-01T00:00:{sec:02d}+00:00", interface_state=state, ssid=ssid, bssid=bssid,
        rssi_dbm=rssi, snr_db=30, channel=channel, band=band, tx_bitrate_mbps=300.0,
    )


WALK = [
    smp(0, "A", -50), smp(1, "A", -55), smp(2, "A", -72), smp(3, "A", -75), smp(4, "A", -74),
    smp(5, "B", -60, channel=6, band="2.4GHz"), smp(6, "B", -58, channel=6, band="2.4GHz"),
]


def test_empty_input_gives_an_empty_but_valid_analysis():
    a = analyze([])
    assert a.summary.sample_count == 0 and a.segments == [] and a.points == []
    assert a.summary.rssi_avg is None and a.summary.pct_samples_weak is None


def test_segments_aps_and_changes():
    a = analyze(WALK)
    assert [(s.bssid, s.sample_count, s.duration_seconds) for s in a.segments] == [("A", 5, 4.0), ("B", 2, 1.0)]
    assert a.segments[1].channel == 6 and a.segments[1].band == "2.4GHz"
    assert a.summary.distinct_aps == 2 and a.summary.ap_change_count == 1
    (change,) = a.ap_changes
    assert (change.from_bssid, change.to_bssid, change.same_ssid, change.via_disconnect) == ("A", "B", True, False)
    assert (change.rssi_before, change.rssi_after) == (-74, -60)
    assert [(u.bssid, u.visits, u.share_pct) for u in a.aps] == [("A", 1, 71.4), ("B", 1, 28.6)]


def test_summary_and_weak_stretches():
    a = analyze(WALK, weak_threshold_dbm=-70)
    assert (a.summary.rssi_min, a.summary.rssi_max) == (-75, -50)
    assert a.summary.pct_samples_weak == pytest.approx(42.9, abs=0.1)
    (weak,) = a.weak_stretches
    assert weak.sample_count == 3 and weak.min_rssi_dbm == -75 and weak.bssid == "A"
    assert weak.duration_seconds == 2.0


def test_a_single_weak_sample_is_not_a_stretch():
    a = analyze([smp(0, "A", -50), smp(1, "A", -80), smp(2, "A", -50)])
    assert a.weak_stretches == [] and a.summary.pct_samples_weak == pytest.approx(33.3, abs=0.1)


def test_disconnect_ends_a_segment_and_marks_reconnect_as_a_new_visit():
    data = [smp(0, "A", -50), smp(1, "A", -52), smp(2, None, None, state="disconnected"), smp(3, "A", -51)]
    a = analyze(data)
    assert [s.sample_count for s in a.segments] == [2, 1]
    assert a.summary.ap_change_count == 0          # same AP before and after is a reconnect, not a roam
    assert a.aps[0].visits == 2
    assert a.summary.connected_sample_count == 3 and a.summary.sample_count == 4
    assert [p.connected for p in a.points] == [True, True, False, True]


def test_disconnect_between_two_different_aps_is_flagged():
    data = [smp(0, "A", -50), smp(1, None, None, state="disconnected"), smp(2, "B", -55)]
    (change,) = analyze(data).ap_changes
    assert change.via_disconnect is True


def test_readings_without_a_bssid_never_invent_an_ap_change():
    data = [smp(0, "A", -50), smp(1, None, -52), smp(2, "A", -51)]
    a = analyze(data)
    assert len(a.segments) == 1 and a.summary.ap_change_count == 0


def test_hidden_bssid_is_reported_as_unavailable():
    a = analyze([smp(0, None, -50), smp(1, None, -52)])
    assert a.summary.bssid_available is False
    assert a.summary.distinct_aps == 0 and a.summary.ap_change_count == 0
    assert a.segments[0].bssid is None and a.summary.rssi_avg == -51.0


def test_unknown_state_with_a_signal_still_counts_as_connected():
    a = analyze([smp(0, "A", -50, state="unknown"), smp(1, "A", -52, state=None)])
    assert a.summary.connected_sample_count == 2


def test_input_order_does_not_matter():
    assert analyze(list(reversed(WALK))).summary == analyze(WALK).summary


def test_downsampling_keeps_ap_boundaries():
    data = [smp(i % 60, "A", -50) for i in range(0, 50)] + [smp(i % 60, "B", -50) for i in range(50, 60)]
    # same-minute timestamps are fine; only order matters here
    a = analyze(data, max_points=10)
    assert len(a.points) < 25
    assert {"A", "B"} <= {p.bssid for p in a.points}
    first_b = next(i for i, p in enumerate(a.points) if p.bssid == "B")
    assert a.points[first_b].t == data[50].timestamp   # the boundary sample survived thinning


# ---------------------------------------------------------------------------
# Endpoints (called directly with a real temp database)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_walk_test_analysis_and_csv_export(db):
    wt = await walk_tests_repo.create_walk_test(
        db, name="Floor 2 / east wing", site="HQ", area=None, interface="wlan0", target_ids=[],
    )
    for s in WALK:
        await walk_tests_repo.insert_sample(db, wt.id, {
            "timestamp": s.timestamp, "interface_state": s.interface_state, "ssid": s.ssid, "bssid": s.bssid,
            "channel": s.channel, "band": s.band, "rssi_dbm": s.rssi_dbm, "snr_db": s.snr_db,
            "tx_bitrate_mbps": s.tx_bitrate_mbps,
        })

    result = await walk_tests_api.analyze_walk_test(wt.id, weak_threshold_dbm=-70, max_points=1200, db=db)
    assert result.summary.sample_count == 7 and result.summary.ap_change_count == 1

    resp = await walk_tests_api.export_walk_test(wt.id, db=db)
    lines = resp.body.decode().strip().splitlines()
    assert lines[0].startswith("timestamp,interface_state,ssid,bssid")
    assert len(lines) == 8 and ",A," in lines[1]
    disposition = resp.headers["content-disposition"]
    assert f"walk-test-{wt.id}-Floor-2-east-wing.csv" in disposition   # filename is sanitised


@pytest.mark.asyncio
async def test_unknown_walk_test_is_404(db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await walk_tests_api.analyze_walk_test(999, weak_threshold_dbm=-70, max_points=100, db=db)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException):
        await walk_tests_api.export_walk_test(999, db=db)


@pytest.mark.asyncio
async def test_wifi_analysis_endpoint_uses_the_latest_interface_and_window(db):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    for i, bssid in enumerate(["A", "A", "B"]):
        await wifi_samples_repo.insert_sample(db, WifiMetrics(
            timestamp=(now - timedelta(minutes=2 - i)).isoformat(), interface="wlan0", interface_state="connected",
            ssid="Net", bssid=bssid, rssi_dbm=-55, channel=36, band="5GHz",
        ))
    await wifi_samples_repo.insert_sample(db, WifiMetrics(      # outside a 5 minute window
        timestamp=(now - timedelta(hours=3)).isoformat(), interface="wlan0", interface_state="connected",
        ssid="Net", bssid="OLD", rssi_dbm=-90,
    ))
    out = await wifi_api.wifi_analysis(minutes=5, interface=None, weak_threshold_dbm=-70, max_points=1200, db=db)
    assert out.summary.sample_count == 3 and out.summary.ap_change_count == 1
    assert {u.bssid for u in out.aps} == {"A", "B"}


@pytest.mark.asyncio
async def test_wifi_analysis_endpoint_with_no_data_is_empty(db):
    out = await wifi_api.wifi_analysis(minutes=60, interface=None, weak_threshold_dbm=-70, max_points=100, db=db)
    assert out.summary.sample_count == 0
