"""
Walk-test session lifecycle: start/stop, plus the dense (default 500ms)
background sampling loop for whichever session is currently recording.

Supports exactly one recording session at a time, system-wide. Walk-test
mode is inherently a single-person, walk-around-the-site activity - the
spec's workflow describes one interface and one set of targets per
session, with no mention of running several at once, so this keeps the
lifecycle (and its state) simple rather than building out multi-session
bookkeeping nothing asks for.

Latency is intentionally NOT re-checked fresh on every 500ms sample tick:
a real ping (even with a short timeout) can't complete fast enough to fit
that budget without a real result yet, and a walk-test explicitly must
not require internet connectivity to run at all. Instead, a separate,
slower ping loop (once per second, and only if the session has at least
one target_id) updates the session's "most recent result", and each fast
sample tick just reads whatever that currently is - possibly up to ~1s
stale relative to the WiFi reading taken in the same row, which is an
honest tradeoff given the two measurements fundamentally can't share a
timescale here.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

import aiosqlite

from app.database import targets_repo, walk_tests_repo
from app.models.walk_test import WalkTestCreate, WalkTestOut
from app.monitoring import wifi
from app.monitoring.pinger import run_check
from app.services import roaming_service
from app.services.settings_service import get_settings

logger = logging.getLogger("ap_monitor.walk_test")


@dataclass
class _ActiveSession:
    walk_test_id: int
    interface: str
    target_ids: List[int]
    sample_task: Optional[asyncio.Task] = None
    ping_task: Optional[asyncio.Task] = None
    latest_latency_ms: Optional[float] = None
    latest_packet_loss_pct: Optional[float] = None
    latest_reachable: Optional[bool] = None


_active: Optional[_ActiveSession] = None


async def start_session(conn: aiosqlite.Connection, data: WalkTestCreate) -> WalkTestOut:
    global _active
    if _active is not None:
        raise RuntimeError(
            f"A walk-test session (id={_active.walk_test_id}) is already recording - stop it first."
        )

    result = await walk_tests_repo.create_walk_test(
        conn, name=data.name, site=data.site, area=data.area,
        interface=data.interface, target_ids=data.target_ids,
    )

    session = _ActiveSession(walk_test_id=result.id, interface=data.interface, target_ids=data.target_ids)
    session.sample_task = asyncio.create_task(_sample_loop(conn, session), name=f"walk-test-sample-{result.id}")
    if data.target_ids:
        session.ping_task = asyncio.create_task(_ping_loop(conn, session), name=f"walk-test-ping-{result.id}")
    _active = session
    logger.info("Walk-test session %s ('%s') started on %s", result.id, data.name, data.interface)
    return result


async def stop_session(conn: aiosqlite.Connection, walk_test_id: int) -> WalkTestOut:
    global _active
    if _active is None or _active.walk_test_id != walk_test_id:
        existing = await walk_tests_repo.get_walk_test(conn, walk_test_id)
        if existing is None:
            raise ValueError(f"No walk-test session with id={walk_test_id}")
        if existing.status == "stopped":
            return existing  # already stopped - idempotent, not an error
        raise RuntimeError(f"Walk-test session id={walk_test_id} is not the currently active session.")

    session = _active
    _active = None
    await _cancel_session_tasks(session)

    result = await walk_tests_repo.stop_walk_test(conn, walk_test_id)
    logger.info("Walk-test session %s stopped (%d sample(s))", walk_test_id, result.sample_count if result else 0)
    return result


async def _cancel_session_tasks(session: _ActiveSession) -> None:
    tasks = [t for t in (session.sample_task, session.ping_task) if t is not None]
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _sample_loop(conn: aiosqlite.Connection, session: _ActiveSession) -> None:
    try:
        while True:
            settings = await get_settings(conn)
            metrics = None
            try:
                # use_cache=False: the background loop's 2s TTL cache would
                # return byte-identical readings across several consecutive
                # 500ms ticks, which would defeat the entire point of dense
                # walk-test sampling as someone physically moves around.
                metrics = await wifi.get_wifi_metrics(session.interface, use_cache=False)
            except RuntimeError:
                pass  # no active WiFi association right now - record what we can (nothing WiFi-related)
            except Exception:
                logger.exception("Walk-test %s: error reading WiFi metrics", session.walk_test_id)

            if metrics is not None:
                # Walking is exactly when roams happen, and this loop sees the
                # radio every ~500ms versus the background poll's several
                # seconds - so it feeds the same roam detector. Same state
                # machine, same two-consecutive-readings confirmation.
                try:
                    await roaming_service.evaluate(conn, metrics)
                except Exception:  # pragma: no cover - never let roam bookkeeping end a recording
                    logger.exception("Walk-test %s: roam evaluation failed", session.walk_test_id)

            sample = {"timestamp": datetime.now(timezone.utc).isoformat()}
            if metrics is not None:
                sample.update({
                    "interface_state": metrics.interface_state, "ssid": metrics.ssid, "bssid": metrics.bssid,
                    "frequency_mhz": metrics.frequency_mhz, "channel": metrics.channel, "band": metrics.band,
                    "rssi_dbm": metrics.rssi_dbm, "signal_pct": metrics.signal_pct,
                    "noise_floor_dbm": metrics.noise_floor_dbm, "snr_db": metrics.snr_db,
                    "phy_mode": metrics.phy_mode, "channel_width_mhz": metrics.channel_width_mhz,
                    "mcs_index": metrics.mcs_index, "tx_bitrate_mbps": metrics.tx_bitrate_mbps,
                    "rx_bitrate_mbps": metrics.rx_bitrate_mbps, "phy_rate_mbps": metrics.phy_rate_mbps,
                })
            sample["latency_ms"] = session.latest_latency_ms
            sample["packet_loss_pct"] = session.latest_packet_loss_pct
            sample["reachable"] = session.latest_reachable

            await walk_tests_repo.insert_sample(conn, session.walk_test_id, sample)
            await asyncio.sleep(settings.walk_test_sample_interval_ms / 1000)
    except asyncio.CancelledError:
        raise


async def _ping_loop(conn: aiosqlite.Connection, session: _ActiveSession) -> None:
    """Checks a single representative target (the first of target_ids) once
    per second. Deliberately not all of them in rotation or in parallel -
    walk-test's primary purpose is RF-layer characterization; latency here
    is contextual, not the point, and this keeps the loop simple and fast.
    """
    all_targets = await targets_repo.list_targets(conn)
    target = next((t for t in all_targets if t.id in session.target_ids), None)
    if target is None:
        return
    try:
        while True:
            settings = await get_settings(conn)
            try:
                result = await run_check(
                    host=target.host, protocol=target.protocol, port=target.port,
                    count=1, timeout=min(1.0, settings.ping_timeout_seconds),
                )
                session.latest_latency_ms = result.avg_latency_ms
                session.latest_packet_loss_pct = result.loss_pct
                session.latest_reachable = result.succeeded > 0
            except Exception:
                logger.exception("Walk-test %s: ping check against %s failed", session.walk_test_id, target.host)
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        raise


def is_recording() -> bool:
    return _active is not None


def active_walk_test_id() -> Optional[int]:
    return _active.walk_test_id if _active is not None else None


async def cancel_all() -> None:
    """Called from MonitoringManager.stop() / app shutdown, so a restart
    doesn't leave a walk-test's tasks running against a closing connection.
    Deliberately does NOT mark the session 'stopped' in the database - an
    interrupted-by-shutdown session should still read as 'recording' (and
    therefore resumable/visible as such) rather than silently appearing
    cleanly finished."""
    global _active
    if _active is None:
        return
    session = _active
    _active = None
    await _cancel_session_tasks(session)


def reset_state() -> None:
    """Used by tests."""
    global _active
    _active = None
