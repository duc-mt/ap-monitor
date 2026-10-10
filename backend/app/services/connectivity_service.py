"""
==============================================================================
Module Name:   connectivity_service.py
Description:   Source module connectivity_service.py.
Author:        Mai Tan Duc <ducmai.network@gmail.com>
Created:       2026-10-10
Version:       1.0.0
License:       MIT
==============================================================================
Usage:         python3 connectivity_service.py [options]
Notes:         Requires Python 3.8+
==============================================================================
"""

from __future__ import annotations

import logging

import aiosqlite

from app.database import measurements_repo, targets_repo
from app.models.settings import AppSettings
from app.models.status import ConnectivityState, ConnectivityStatus
from app.services import notification_service

logger = logging.getLogger("ap_monitor.connectivity")

_previous_state: ConnectivityState | None = None

# States in which the app is meaningfully "not working" - used to decide
# when to fire the offline-style notification (any transition into one of
# these from outside this set) versus the restored-style one (the reverse).
_BROKEN_STATES = {"wifi_disconnected", "gateway_unavailable", "internet_unavailable"}


async def compute_status(
    conn: aiosqlite.Connection,
    settings: AppSettings,
    *,
    wifi_connected: bool | None = None,
) -> ConnectivityStatus:
    """
    The pure computation behind evaluate() below, with no side effects -
    safe to call as often as you like (e.g. from a GET /api/status handler
    on every poll) without touching notification state. evaluate() is the
    only thing that should ever follow a call to this with a transition
    check; reuse this function directly anywhere that just needs the
    current reading.
    """
    targets = await targets_repo.list_targets(conn, enabled_only=True)
    latest = await measurements_repo.latest_measurements_all(conn)
    latest_by_target = {m.target_id: m for m in latest}

    gateway_target = next((t for t in targets if t.is_gateway), None)
    external_targets = [t for t in targets if not t.is_gateway]

    gateway_reachable: bool | None = None
    if gateway_target is not None:
        m = latest_by_target.get(gateway_target.id)
        gateway_reachable = m.success if m is not None else None

    internet_state = _derive_internet_state(
        external_targets, latest_by_target, settings.internet_quorum
    )

    overall = _derive_overall(
        wifi_connected=wifi_connected,
        has_gateway_target=gateway_target is not None,
        gateway_reachable=gateway_reachable,
        internet_state=internet_state,
    )

    return ConnectivityStatus(
        wifi_connected=wifi_connected,
        gateway_reachable=gateway_reachable,
        internet_state=internet_state,
        overall=overall,
    )


async def evaluate(
    conn: aiosqlite.Connection,
    settings: AppSettings,
    *,
    wifi_connected: bool | None = None,
) -> ConnectivityStatus:
    """
    Computes the status (see compute_status() above) AND fires a
    notification on a meaningful transition, updating the module's
    transition-tracking state. This is the stateful half - only ever call
    this from the one place meant to own that state (the scheduler's
    per-tick loop). Every other caller (status_service, tests, anything
    read-only) should call compute_status() directly instead.

    `wifi_connected` is optional and defaults to None ("unknown/not
    supplied") rather than being read from app.monitoring.wifi in here
    directly - passed in by the caller so this module stays trivially
    testable without mocking an entire OS-specific WiFi adapter. A caller
    that never passes wifi_connected still gets correct gateway/internet-
    based states; only the WiFi-specific state ("wifi_disconnected")
    requires the caller to actually supply a reading.
    """
    global _previous_state

    status = await compute_status(conn, settings, wifi_connected=wifi_connected)

    await _maybe_notify(status.overall, settings)
    _previous_state = status.overall

    return status


def _derive_internet_state(
    external_targets, latest_by_target, quorum: str
) -> str | None:
    with_data = [t for t in external_targets if t.id in latest_by_target]
    if not with_data:
        return None  # no external targets configured, or none checked yet

    succeeded = sum(1 for t in with_data if latest_by_target[t.id].success)
    total = len(with_data)

    if quorum == "all":
        return "available" if succeeded == total else "unavailable"

    # quorum == "any" (default): one working target is enough to call the
    # internet reachable at all; anything less than all of them succeeding
    # is "degraded" rather than fully "available".
    if succeeded == 0:
        return "unavailable"
    if succeeded < total:
        return "degraded"
    return "available"


def _derive_overall(
    *,
    wifi_connected: bool | None,
    has_gateway_target: bool,
    gateway_reachable: bool | None,
    internet_state: str | None,
) -> ConnectivityState:
    # Only an explicit False short-circuits to "WiFi disconnected" - None
    # ("we don't know", e.g. no WiFi reading supplied, or the host is on
    # ethernet with no active WiFi association at all) must never be
    # reported as a false "disconnected"; it falls through to gateway/
    # internet reasoning below, which stands on its own ping data.
    if wifi_connected is False:
        return "wifi_disconnected"

    if has_gateway_target and gateway_reachable is False:
        return "gateway_unavailable"

    if internet_state is None:
        # No external targets configured/answered yet - report the most
        # specific thing we *do* know rather than falling all the way to
        # "unknown".
        if has_gateway_target and gateway_reachable:
            return "gateway_available"
        if wifi_connected:
            return "wifi_connected"
        return "unknown"

    return {
        "unavailable": "internet_unavailable",
        "degraded": "degraded",
        "available": "internet_available",
    }[internet_state]


async def _maybe_notify(overall: ConnectivityState, settings: AppSettings) -> None:
    global _previous_state
    if _previous_state is None or overall == _previous_state:
        return

    was_broken = _previous_state in _BROKEN_STATES
    is_broken = overall in _BROKEN_STATES

    if is_broken and not was_broken:
        if settings.notifications.on_offline:
            await notification_service.send(
                "Connectivity lost",
                _describe(overall),
                urgency="critical",
                key="connectivity_state",
            )
    elif overall == "internet_available" and _previous_state != "internet_available":
        if settings.notifications.on_online:
            await notification_service.send(
                "Connectivity restored",
                "Internet access is fully available again.",
                urgency="normal",
                key="connectivity_state",
            )
    elif overall == "degraded" and _previous_state == "internet_available":
        if settings.notifications.on_degraded:
            await notification_service.send(
                "Connectivity degraded",
                "Some monitored targets have stopped responding.",
                urgency="normal",
                key="connectivity_state",
            )


def _describe(state: ConnectivityState) -> str:
    return {
        "wifi_disconnected": "The WiFi connection was lost.",
        "gateway_unavailable": "The local gateway stopped responding.",
        "internet_unavailable": "All monitored external targets stopped responding.",
    }.get(state, "Connectivity state changed.")


def reset_state() -> None:
    """Used by tests."""
    global _previous_state
    _previous_state = None
