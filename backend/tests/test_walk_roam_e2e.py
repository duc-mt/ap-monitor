"""
==============================================================================
Module Name:   test_walk_roam_e2e.py
Description:   Source module test_walk_roam_e2e.py.
Author:        Mai Tan Duc <ducmai.network@gmail.com>
Created:       2026-10-10
Version:       1.0.0
License:       MIT
==============================================================================
Usage:         python3 test_walk_roam_e2e.py [options]
Notes:         Requires Python 3.8+
==============================================================================
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from app.monitoring import wifi
from app.monitoring.wifi.models import WifiMetrics

AP_A = "aa:aa:aa:aa:aa:01"
AP_B = "aa:aa:aa:aa:aa:02"


def _walk(monkeypatch, *, hide_bssid: bool = False):
    """Simulated radio: weakening signal on AP A for 8 readings, then AP B."""
    state = {"n": 0}

    async def fake_metrics(interface=None, *, use_cache=True):
        state["n"] += 1
        n = state["n"]
        on_b = n > 8
        bssid = None if hide_bssid else (AP_B if on_b else AP_A)
        return WifiMetrics(
            timestamp=datetime.now(UTC).isoformat(),
            interface="wlan0",
            interface_state="connected",
            ssid="Corp",
            bssid=bssid,
            rssi_dbm=-55 if on_b else -60 - 3 * n,
            snr_db=30,
            channel=6 if on_b else 36,
            band="2.4GHz" if on_b else "5GHz",
            tx_bitrate_mbps=300.0,
        )

    monkeypatch.setattr(wifi, "get_wifi_metrics", fake_metrics)
    return state


def _record_walk(client, until_samples: int = 14) -> int:
    assert (
        client.put(
            "/api/settings", json={"walk_test_sample_interval_ms": 100}
        ).status_code
        == 200
    )
    started = client.post(
        "/api/walk-tests",
        json={
            "name": "East wing",
            "site": "HQ",
            "area": None,
            "interface": "wlan0",
            "target_ids": [],
        },
    )
    assert started.status_code == 201, started.text
    walk_id = started.json()["id"]
    deadline = time.time() + 10
    while time.time() < deadline:
        if (
            client.get(f"/api/walk-tests/{walk_id}").json()["sample_count"]
            >= until_samples
        ):
            break
        time.sleep(0.1)
    assert client.post(f"/api/walk-tests/{walk_id}/stop").status_code == 200
    return walk_id


def test_walking_between_two_aps_shows_up_in_the_result_and_as_a_roam(
    client, monkeypatch
):
    _walk(monkeypatch)
    walk_id = _record_walk(client)

    analysis = client.get(
        f"/api/walk-tests/{walk_id}/analysis", params={"weak_threshold_dbm": -70}
    ).json()
    summary = analysis["summary"]
    assert summary["bssid_available"] is True
    assert summary["distinct_aps"] == 2 and summary["ap_change_count"] == 1
    assert [s["bssid"] for s in analysis["segments"]] == [AP_A, AP_B]
    (change,) = analysis["ap_changes"]
    assert (change["from_bssid"], change["to_bssid"], change["same_ssid"]) == (
        AP_A,
        AP_B,
        True,
    )
    assert analysis["weak_stretches"], "the signal weakened on AP A before the handover"
    assert analysis["weak_stretches"][0]["bssid"] == AP_A
    assert summary["rssi_min"] < -70 <= -55 <= summary["rssi_max"]

    # The same walk must also reach the Roaming page: the walk-test sampler feeds the roam detector.
    roams = client.get("/api/roam-events").json()
    assert len(roams) == 1
    assert (roams[0]["previous_bssid"], roams[0]["new_bssid"]) == (AP_A, AP_B)
    assert (roams[0]["previous_channel"], roams[0]["new_channel"]) == (36, 6)

    csv_text = client.get(f"/api/walk-tests/{walk_id}/export").text.strip().splitlines()
    assert len(csv_text) == summary["sample_count"] + 1
    assert any(AP_A in line for line in csv_text) and any(
        AP_B in line for line in csv_text
    )


def test_a_hidden_bssid_walk_still_records_signal_but_says_aps_are_unavailable(
    client, monkeypatch
):
    _walk(monkeypatch, hide_bssid=True)
    walk_id = _record_walk(client, until_samples=10)

    analysis = client.get(f"/api/walk-tests/{walk_id}/analysis").json()
    assert analysis["summary"]["bssid_available"] is False
    assert (
        analysis["summary"]["rssi_min"] is not None
        and analysis["summary"]["connected_sample_count"] >= 10
    )
    assert analysis["summary"]["ap_change_count"] == 0
    assert (
        client.get("/api/roam-events").json() == []
    )  # no BSSID, so no fabricated roam
