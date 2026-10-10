"""
Watches connectivity after a confirmed roam and fills in the "Estimated
Connectivity Interruption" fields on its roam_events row: gateway/internet
interruption duration, packet loss and peak latency observed during the
transition, a success flag, and a classification/confidence verdict.

READ THIS BEFORE CHANGING THE CLASSIFICATION THRESHOLDS: the spec's bands
(Excellent <50ms, Good 50-150ms, Fair 150-300ms, Poor >=300ms, Failed) are
genuinely millisecond-scale - finer than this app's ping-interval-driven
measurement can usually resolve. With ping targets checking every ~5s by
default, a real gap of "some failed pings, then a success" can only ever
be bounded to whole ping-interval resolution (seconds, not milliseconds),
which is why a roam with any actual failed ping will realistically land in
"poor" or "failed" almost every time - that is an honest reflection of
measurement resolution, not a bug. To give the finer bands a real chance
of firing, this file classifies by *peak_latency_ms* instead of duration
whenever every ping during the watch window actually succeeded (packet
loss 0%) - a ping RTT spiking from a normal ~15ms to 180ms right after a
roam *is* a genuine millisecond-precision signal of a brief, sub-ping-
interval disruption (exactly what a fast 802.11r/k/v roam looks like: no
dropped packets, just a momentary latency bump), even though nothing
literally timed out. `confidence` exists precisely to flag how much to
trust either kind of estimate; a caller should never read `classification`
without also showing `confidence` next to it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import aiosqlite

from app.database import measurements_repo, roam_events_repo, targets_repo
from app.models.roam_event import RoamClassification, RoamConfidence, RoamEventOut
from app.services import notification_service
from app.services.settings_service import get_settings

logger = logging.getLogger("ap_monitor.roam_interruption")

_POLL_INTERVAL_SECONDS = 1.0


@dataclass
class _Sample:
    is_gateway: bool
    success: bool
    latency_ms: float | None


@dataclass
class _Watch:
    event_id: int
    interface: str
    ssid: str | None
    new_bssid: str | None
    gateway_target_id: int | None
    external_target_ids: list[int]
    start_monotonic: float
    timeout_seconds: int
    gateway_interruption_ms: float | None = None
    internet_interruption_ms: float | None = None
    seen_measurement_ids: set = field(default_factory=set)
    samples: list[_Sample] = field(default_factory=list)


_active_watches: dict[int, _Watch] = {}


async def start_watch(conn: aiosqlite.Connection, event: RoamEventOut) -> None:
    """Call once, right after a roam event is created. Spawns a background
    task and returns immediately - never awaited inline by the caller, since
    a full watch can take up to roam_watch_timeout_seconds."""
    targets = await targets_repo.list_targets(conn, enabled_only=True)
    gateway_target = next((t for t in targets if t.is_gateway), None)
    external_targets = [t for t in targets if not t.is_gateway]

    if gateway_target is None and not external_targets:
        # Nothing to measure against - say so plainly rather than guessing.
        await roam_events_repo.update_interruption_result(
            conn,
            event.id,
            gateway_interruption_ms=None,
            internet_interruption_ms=None,
            packet_loss_during_pct=None,
            peak_latency_ms=None,
            success=None,
            classification=None,
            confidence="unknown",
        )
        return

    settings = await get_settings(conn)
    watch = _Watch(
        event_id=event.id,
        interface=event.interface,
        ssid=event.ssid,
        new_bssid=event.new_bssid,
        gateway_target_id=gateway_target.id if gateway_target else None,
        external_target_ids=[t.id for t in external_targets],
        start_monotonic=time.monotonic(),
        timeout_seconds=settings.roam_watch_timeout_seconds,
    )
    _active_watches[event.id] = watch

    task = asyncio.create_task(
        _run_watch(conn, watch, event.timestamp), name=f"roam-watch-{event.id}"
    )
    task.add_done_callback(lambda _t: _active_watches.pop(event.id, None))


async def _run_watch(
    conn: aiosqlite.Connection, watch: _Watch, roam_timestamp: str
) -> None:
    try:
        while True:
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            elapsed_ms = (time.monotonic() - watch.start_monotonic) * 1000

            recent = await measurements_repo.list_measurements(
                conn, start=roam_timestamp, limit=500
            )
            for m in recent:
                if m.id in watch.seen_measurement_ids:
                    continue
                watch.seen_measurement_ids.add(m.id)
                is_gateway = m.target_id == watch.gateway_target_id
                if not is_gateway and m.target_id not in watch.external_target_ids:
                    continue  # a target that isn't part of this roam's connectivity picture
                watch.samples.append(
                    _Sample(
                        is_gateway=is_gateway,
                        success=m.success,
                        latency_ms=m.latency_ms,
                    )
                )
                if m.success:
                    if is_gateway and watch.gateway_interruption_ms is None:
                        watch.gateway_interruption_ms = elapsed_ms
                    if not is_gateway and watch.internet_interruption_ms is None:
                        watch.internet_interruption_ms = elapsed_ms

            gateway_done = (
                watch.gateway_target_id is None
                or watch.gateway_interruption_ms is not None
            )
            internet_done = (
                not watch.external_target_ids
                or watch.internet_interruption_ms is not None
            )
            if gateway_done and internet_done:
                await _finalize(conn, watch, timed_out=False)
                return
            if elapsed_ms >= watch.timeout_seconds * 1000:
                await _finalize(conn, watch, timed_out=True)
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "Roam interruption watch for event %s failed unexpectedly", watch.event_id
        )


async def _finalize(
    conn: aiosqlite.Connection, watch: _Watch, *, timed_out: bool
) -> None:
    total = len(watch.samples)
    failed = sum(1 for s in watch.samples if not s.success)
    packet_loss_during_pct = round(100 * failed / total, 1) if total else None
    latencies = [s.latency_ms for s in watch.samples if s.latency_ms is not None]
    peak_latency_ms = max(latencies) if latencies else None

    success = not timed_out

    primary_ms = (
        watch.internet_interruption_ms
        if watch.external_target_ids
        else watch.gateway_interruption_ms
    )

    classification: RoamClassification | None
    if not success:
        classification = "failed"
    elif packet_loss_during_pct == 0 and peak_latency_ms is not None:
        # Nothing actually failed - classify by the latency spike itself,
        # a genuine millisecond-precision signal (see module docstring).
        classification = _classify_ms(peak_latency_ms)
    elif primary_ms is not None:
        classification = _classify_ms(primary_ms)
    else:
        classification = None

    confidence = _estimate_confidence(total)

    await roam_events_repo.update_interruption_result(
        conn,
        watch.event_id,
        gateway_interruption_ms=watch.gateway_interruption_ms,
        internet_interruption_ms=watch.internet_interruption_ms,
        packet_loss_during_pct=packet_loss_during_pct,
        peak_latency_ms=peak_latency_ms,
        success=success,
        classification=classification,
        confidence=confidence,
    )
    logger.info(
        "Roam event %s interruption result: success=%s classification=%s confidence=%s (%d sample(s))",
        watch.event_id,
        success,
        classification,
        confidence,
        total,
    )

    if classification in ("poor", "failed"):
        settings = await get_settings(conn)
        if settings.notifications.on_poor_roam:
            ap_label = f" ({watch.new_bssid})" if watch.new_bssid else ""
            await notification_service.send(
                "Poor roam" if classification == "poor" else "Roam failed",
                f"Roaming to a new access point{ap_label} on {watch.ssid or watch.interface} "
                f"was classified as {classification}.",
                urgency=("critical" if classification == "failed" else "normal"),
                key=f"roam-{classification}",
                cooldown_seconds=settings.notifications.cooldown_seconds,
            )


def _classify_ms(ms: float) -> RoamClassification:
    if ms < 50:
        return "excellent"
    if ms < 150:
        return "good"
    if ms < 300:
        return "fair"
    return "poor"


def _estimate_confidence(total_samples: int) -> RoamConfidence:
    """A deliberately simple, honest proxy: more corroborating measurements
    during the watch window means a tighter bound on the estimate above.
    This does NOT attempt to model ping-interval-vs-interruption-size
    precisely - see the module docstring for why that's not achievable
    here, and why confidence exists at all."""
    if total_samples == 0:
        return "unknown"
    if total_samples == 1:
        return "low"
    if total_samples <= 3:
        return "medium"
    return "high"


def active_watch_count() -> int:
    """Used by tests and shutdown bookkeeping."""
    return len(_active_watches)


async def cancel_all() -> None:
    """Called from MonitoringManager.stop() so a shutdown doesn't leave
    watch tasks running against a connection that's about to close."""
    tasks = list(asyncio.all_tasks())
    watch_tasks = [t for t in tasks if t.get_name().startswith("roam-watch-")]
    for t in watch_tasks:
        t.cancel()
    if watch_tasks:
        await asyncio.gather(*watch_tasks, return_exceptions=True)
    _active_watches.clear()


def reset_state() -> None:
    """Used by tests."""
    _active_watches.clear()
