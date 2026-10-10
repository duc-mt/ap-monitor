"""HTTP-level checks for the AP-facing endpoints (routing, validation, shape)."""
from __future__ import annotations


def test_status_reports_platform_and_a_wifi_issue_when_there_is_no_interface(client):
    body = client.get("/api/status").json()
    assert body["platform"] in ("linux", "darwin", "win32")
    # The test host has no usable WiFi adapter, so the dashboard must be told why
    # rather than being left blank. Which reason depends on whether nmcli/iw exist.
    assert body["wifi_issue"]["code"] in ("missing_tools", "no_wifi_interface", "location_permission")
    assert body["wifi_issue"]["title"] and body["wifi_issue"]["detail"]
    for field in ("channel_width_mhz", "snr_db", "noise_floor_dbm", "tx_bitrate_mbps"):
        assert field in body


def test_wifi_analysis_route_validates_and_returns_an_empty_shape(client):
    ok = client.get("/api/wifi/analysis", params={"minutes": 30})
    assert ok.status_code == 200
    body = ok.json()
    assert body["summary"]["sample_count"] == 0 and body["points"] == [] and body["aps"] == []
    assert client.get("/api/wifi/analysis", params={"minutes": 0}).status_code == 422
    assert client.get("/api/wifi/analysis", params={"weak_threshold_dbm": -10}).status_code == 422


def test_walk_test_analysis_and_export_404_for_unknown_session(client):
    assert client.get("/api/walk-tests/12345/analysis").status_code == 404
    assert client.get("/api/walk-tests/12345/export").status_code == 404
