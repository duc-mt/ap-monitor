"""
Shared test fixtures.

Two ground rules for this whole suite (per the project brief):
  1. No test may depend on real Internet connectivity.
  2. No test may talk to a real network target - the pinger's subprocess
     and socket calls are monkeypatched wherever a test exercises code
     that would otherwise reach out.

AP_MONITOR_AUTOSTART is forced to "0" before app.main is ever
imported so the FastAPI lifespan never spawns real monitoring loops
against the live internet during API tests.
"""

from __future__ import annotations

import os

os.environ["AP_MONITOR_AUTOSTART"] = "0"

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from app.database import connection as db_connection
from app.monitoring import wifi
from app.monitoring import scheduler as monitoring_scheduler
from app.monitoring.pinger import PingBatchResult
from app.services import (
    connectivity_service,
    notification_service,
    roam_interruption_service,
    roaming_service,
    settings_service,
    walk_test_service,
)


async def _fake_run_check(*, host, protocol, port, count, timeout):
    """Stand-in for app.monitoring.pinger.run_check so that if a test starts
    the real MonitoringManager, it never actually touches the network."""
    return PingBatchResult(
        method=protocol, attempted=count, succeeded=count, latencies=[1.0] * count
    )


async def _fake_get_wifi_metrics(interface=None, *, use_cache=True):
    """Stand-in for app.monitoring.wifi.get_wifi_metrics - same rationale as
    _fake_run_check above: a test that starts the real MonitoringManager
    must not shell out to nmcli/iw or depend on this machine's actual WiFi
    state. 'No active interface' is the deterministic, always-correct
    answer for a CI box with no WiFi adapter at all."""
    raise RuntimeError("No active WiFi interface (test stub)")


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    """A fresh, isolated SQLite database for a single test."""
    db_path = tmp_path / "test.db"
    conn = await db_connection.init_db(db_path)
    settings_service.invalidate_cache()
    connectivity_service.reset_state()
    notification_service.reset_cooldowns()
    roaming_service.reset_state()
    wifi.reset_cache()
    roam_interruption_service.reset_state()
    walk_test_service.reset_state()
    yield conn
    await db_connection.close_db()


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    """A FastAPI TestClient wired to its own temp database, with monitoring
    loops disabled (AUTOSTART=0 set at module import time above)."""
    monkeypatch.setattr(db_connection, "DATABASE_PATH", tmp_path / "client.db")
    monkeypatch.setattr(monitoring_scheduler, "run_check", _fake_run_check)
    monkeypatch.setattr(wifi, "get_wifi_metrics", _fake_get_wifi_metrics)
    settings_service.invalidate_cache()
    connectivity_service.reset_state()
    notification_service.reset_cooldowns()
    roaming_service.reset_state()
    wifi.reset_cache()
    roam_interruption_service.reset_state()
    walk_test_service.reset_state()

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
    # Exiting the context above already ran the app's shutdown (manager.stop()
    # + close_db()) via the lifespan handler.
