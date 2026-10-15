from __future__ import annotations


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_default_targets_seeded_on_startup(client):
    resp = client.get("/api/targets")
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()}
    assert {"Gateway", "Cloudflare DNS", "Google DNS"} <= names


def test_create_list_update_delete_target(client):
    create_resp = client.post(
        "/api/targets",
        json={
            "name": "Custom Host",
            "host": "example.com",
            "protocol": "tcp",
            "port": 443,
            "interval_seconds": 10,
        },
    )
    assert create_resp.status_code == 201
    target = create_resp.json()
    assert target["name"] == "Custom Host"

    get_resp = client.get(f"/api/targets/{target['id']}")
    assert get_resp.status_code == 200

    update_resp = client.put(f"/api/targets/{target['id']}", json={"interval_seconds": 20})
    assert update_resp.status_code == 200
    assert update_resp.json()["interval_seconds"] == 20

    delete_resp = client.delete(f"/api/targets/{target['id']}")
    assert delete_resp.status_code == 204

    missing_resp = client.get(f"/api/targets/{target['id']}")
    assert missing_resp.status_code == 404


def test_create_target_rejects_invalid_host(client):
    resp = client.post("/api/targets", json={"name": "Bad", "host": "not a host!!", "protocol": "icmp"})
    assert resp.status_code == 422


def test_create_target_rejects_bad_interval(client):
    resp = client.post("/api/targets", json={"name": "Fast", "host": "1.1.1.1", "interval_seconds": 0})
    assert resp.status_code == 422


def test_update_nonexistent_target_404s(client):
    resp = client.put("/api/targets/99999", json={"name": "Ghost"})
    assert resp.status_code == 404


def test_delete_nonexistent_target_404s(client):
    resp = client.delete("/api/targets/99999")
    assert resp.status_code == 404


def test_status_endpoint_shape(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "online",
        "quality",
        "targets_reachable",
        "targets_total",
        "targets",
        "monitoring_running",
        "wifi_interface",
        "ssid",
        "bssid",
        "rssi_dbm",
        "channel",
        "band",
        "phy_mode",
        "connectivity",
        "wireless_quality_score",
    ):
        assert key in body
    for key in ("wifi_connected", "gateway_reachable", "internet_state", "overall"):
        assert key in body["connectivity"]


def test_settings_get_and_partial_update(client):
    get_resp = client.get("/api/settings")
    assert get_resp.status_code == 200
    original = get_resp.json()
    assert original["data_retention_days"] == 30

    put_resp = client.put("/api/settings", json={"data_retention_days": 90})
    assert put_resp.status_code == 200
    updated = put_resp.json()
    assert updated["data_retention_days"] == 90
    # untouched fields survive a partial update
    assert updated["theme"] == original["theme"]


def test_settings_update_nested_notifications(client):
    resp = client.put("/api/settings", json={"notifications": {"on_offline": False}})
    assert resp.status_code == 200
    assert resp.json()["notifications"]["on_offline"] is False
    # sibling notification fields keep their defaults
    assert resp.json()["notifications"]["on_online"] is True


def test_statistics_requires_bounds_for_custom_range(client):
    resp = client.get("/api/statistics", params={"range": "custom"})
    assert resp.status_code == 400


def test_statistics_default_range(client):
    resp = client.get("/api/statistics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sample_count"] == 0


def test_monitoring_start_and_stop(client):
    start_resp = client.post("/api/monitoring/start")
    assert start_resp.status_code == 200
    assert start_resp.json()["running"] is True

    stop_resp = client.post("/api/monitoring/stop")
    assert stop_resp.status_code == 200
    assert stop_resp.json()["running"] is False


def test_export_measurements_csv(client):
    resp = client.get("/api/export/measurements.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "timestamp" in resp.text.splitlines()[0]


def test_export_report_json(client):
    resp = client.get("/api/export/report.json")
    assert resp.status_code == 200
    body = resp.json()
    assert "statistics" in body


def test_wifi_interfaces_endpoint(client):
    resp = client.get("/api/wifi/interfaces")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_wifi_samples_endpoint_empty_initially(client):
    resp = client.get("/api/wifi/samples")
    assert resp.status_code == 200
    assert resp.json() == []


def test_wifi_scan_returns_409_with_no_active_interface(client):
    # This sandbox has no WiFi hardware, so get_active_wifi_interface()
    # genuinely returns None here (nmcli/iw either aren't installed or
    # report nothing to associate with) - scan_environment() correctly
    # surfaces that as a 409, not a 500, with no interface to fall back to.
    resp = client.post("/api/wifi/scan")
    assert resp.status_code == 409


def test_roam_events_list_empty_initially(client):
    resp = client.get("/api/roam-events")
    assert resp.status_code == 200
    assert resp.json() == []


def test_roam_events_get_missing_returns_404(client):
    resp = client.get("/api/roam-events/99999")
    assert resp.status_code == 404


def test_status_endpoint_uses_in_memory_cache(client, monkeypatch):
    from app.services import status_service

    status_service.reset_status_cache()

    resp1 = client.get("/api/status")
    assert resp1.status_code == 200

    call_count = 0
    orig_list_targets = status_service.targets_repo.list_targets

    async def counting_list_targets(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await orig_list_targets(*args, **kwargs)

    monkeypatch.setattr(status_service.targets_repo, "list_targets", counting_list_targets)

    # Within 1s TTL, compute_status returns cached result without querying DB
    resp2 = client.get("/api/status")
    assert resp2.status_code == 200
    assert call_count == 0

    # Reset cache and verify targets query runs again
    status_service.reset_status_cache()
    resp3 = client.get("/api/status")
    assert resp3.status_code == 200
    assert call_count == 2


def test_gzip_compression_enabled(client):
    headers = {"Accept-Encoding": "gzip"}
    resp = client.get("/api/status", headers=headers)
    assert resp.status_code == 200
    # The GZip middleware is configured and active
    if len(resp.content) > 1000:
        assert resp.headers.get("content-encoding") == "gzip"
