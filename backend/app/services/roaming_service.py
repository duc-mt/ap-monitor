"""
==============================================================================
Module Name:   roaming_service.py
Description:   Source module roaming_service.py.
Author:        Mai Tan Duc <ducmai.network@gmail.com>
Created:       2026-10-10
Version:       1.0.0
License:       MIT
==============================================================================
Usage:         python3 roaming_service.py [options]
Notes:         Requires Python 3.8+
==============================================================================
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiosqlite

from app.database import roam_events_repo
from app.models.roam_event import RoamEventCreate, RoamingState
from app.monitoring.wifi.models import WifiMetrics
from app.services import roam_interruption_service

logger = logging.getLogger("ap_monitor.roaming")

_CONNECTING_STATES = {"connecting", "scanning"}


@dataclass
class _InterfaceRoamState:
    state: RoamingState = "unknown"
    # The most recent reading while genuinely stable on one BSSID - this is
    # what "previous" means in a recorded roam event, kept fresh on every
    # matching tick so it's always the freshest pre-roam reading available.
    stable_reading: WifiMetrics | None = None
    # The first reading that showed a *candidate* new BSSID, held until a
    # second consecutive matching reading confirms it (or a different
    # reading replaces/clears it).
    candidate_reading: WifiMetrics | None = None


_states: dict[str, _InterfaceRoamState] = {}


async def evaluate(conn: aiosqlite.Connection, reading: WifiMetrics) -> RoamingState:
    """Advance the state machine for `reading.interface` by one tick, and
    persist a roam_events row if this reading confirms a roam. Returns the
    interface's resulting state."""
    st = _states.setdefault(reading.interface, _InterfaceRoamState())

    if reading.interface_state != "connected":
        st.state = (
            "connecting"
            if reading.interface_state in _CONNECTING_STATES
            else "disconnected"
        )
        st.candidate_reading = None
        return st.state

    if reading.bssid is None:
        # The adapter could not report a BSSID (the OS withholds it without
        # Location permission, or a transient gap mid-roam). That is "no
        # information", not "a different AP": comparing None with a real
        # BSSID would fabricate a roam, and two Nones in a row would
        # confirm it.
        return st.state

    if st.stable_reading is None or st.stable_reading.ssid != reading.ssid:
        # First-ever reading on this interface, or a different network
        # entirely - establish a fresh baseline. Not a roam.
        st.state = "connected"
        st.stable_reading = reading
        st.candidate_reading = None
        return st.state

    if reading.bssid == st.stable_reading.bssid:
        # Still on the same AP. If we just confirmed a roam in a previous
        # tick, walk through one more settle step before calling it fully
        # steady again; otherwise stay connected.
        if st.state == "roaming":
            st.state = "stabilizing"
        else:
            st.state = "connected"
        st.stable_reading = reading  # keep the pre-roam baseline maximally fresh
        st.candidate_reading = None
        return st.state

    # BSSID differs from the stable baseline.
    if st.candidate_reading is not None and st.candidate_reading.bssid == reading.bssid:
        # Same new BSSID two ticks running - confirmed, not a flicker. Record
        # using the *candidate* reading as "new" (the first sighting of the
        # new BSSID, one poll interval closer to the actual transition) even
        # though this current, confirming `reading` is what becomes the
        # ongoing stable baseline for future comparisons below.
        await _record_roam(conn, previous=st.stable_reading, new=st.candidate_reading)
        st.state = "roaming"
        st.stable_reading = reading
        st.candidate_reading = None
    else:
        # First sighting of this (possibly yet another) new BSSID - hold as
        # a candidate rather than recording immediately.
        st.state = "roam_candidate"
        st.candidate_reading = reading

    return st.state


async def _record_roam(
    conn: aiosqlite.Connection, *, previous: WifiMetrics, new: WifiMetrics
) -> None:
    ip_changed = (previous.ipv4_addresses or []) != (new.ipv4_addresses or [])
    event = await roam_events_repo.create_roam_event(
        conn,
        RoamEventCreate(
            timestamp=new.timestamp,
            interface=new.interface,
            ssid=new.ssid,
            previous_bssid=previous.bssid,
            new_bssid=new.bssid,
            previous_frequency_mhz=previous.frequency_mhz,
            new_frequency_mhz=new.frequency_mhz,
            previous_channel=previous.channel,
            new_channel=new.channel,
            previous_band=previous.band,
            new_band=new.band,
            previous_phy_mode=previous.phy_mode,
            new_phy_mode=new.phy_mode,
            previous_channel_width_mhz=previous.channel_width_mhz,
            new_channel_width_mhz=new.channel_width_mhz,
            previous_mcs_index=previous.mcs_index,
            new_mcs_index=new.mcs_index,
            previous_rssi_dbm=previous.rssi_dbm,
            new_rssi_dbm=new.rssi_dbm,
            ip_changed=ip_changed,
            previous_ipv4=previous.ipv4_addresses,
            new_ipv4=new.ipv4_addresses,
        ),
    )
    logger.info(
        "Roam confirmed on %s: %s -> %s (SSID %r, event id=%s)",
        new.interface,
        previous.bssid,
        new.bssid,
        new.ssid,
        event.id,
    )
    # Stage 10: measure how disruptive this roam actually was. Fire-and-
    # forget - start_watch spawns its own task and returns immediately, so
    # a roam confirmation never blocks on up to roam_watch_timeout_seconds
    # of connectivity watching.
    await roam_interruption_service.start_watch(conn, event)


def get_state(interface: str) -> RoamingState:
    st = _states.get(interface)
    return st.state if st is not None else "unknown"


def reset_state() -> None:
    """Used by tests."""
    _states.clear()
