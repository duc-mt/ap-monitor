"""
Two related but distinct things live here:

- classify(): the simple, pre-existing latency/packet-loss -> Quality
  ("excellent"/"good"/"fair"/"poor"/"unknown") classifier, unchanged from
  Internet Monitor. Still used for the quick status badge.

- compute_wireless_quality_score() (Stage 12): the spec's separate 0-100
  "client experience" score, built from RSSI, latency, packet loss, and
  jitter, minus penalties for recent disconnects and failed roams. Per the
  spec's explicit rule, a component with no data right now (most commonly
  RSSI - not every platform/driver/moment has one) is left OUT of the
  average entirely rather than counted as a 0, so an otherwise-healthy
  connection is never penalized just because one optional reading happened
  to be unavailable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import aiosqlite

from app.database import measurements_repo, roam_events_repo, wifi_samples_repo
from app.models.settings import AppSettings, ClassificationThresholds
from app.models.status import Quality


def classify(
    latency_ms: Optional[float],
    packet_loss_pct: Optional[float],
    thresholds: ClassificationThresholds,
) -> Quality:
    # Caller is responsible for reporting "offline" based on overall
    # reachability; this function only classifies quality when we have an
    # actual latency reading to classify.
    if latency_ms is None or packet_loss_pct is None:
        return "unknown"
    if (
        latency_ms < thresholds.excellent_latency_ms
        and packet_loss_pct < thresholds.excellent_packet_loss_pct
    ):
        return "excellent"
    if (
        latency_ms < thresholds.good_latency_ms
        and packet_loss_pct < thresholds.good_packet_loss_pct
    ):
        return "good"
    if (
        latency_ms < thresholds.fair_latency_ms
        or packet_loss_pct < thresholds.fair_packet_loss_pct
    ):
        return "fair"
    return "poor"


def _linear_score(value: float, zero_at: float, hundred_at: float) -> float:
    """Linear interpolation where `hundred_at` maps to 100 and `zero_at`
    maps to 0, clamped to [0, 100]. The two reference points can be given
    in either numeric order - e.g. latency uses hundred_at < zero_at, since
    lower is better there, while RSSI uses hundred_at > zero_at."""
    if hundred_at == zero_at:
        return 100.0
    t = (value - zero_at) / (hundred_at - zero_at)
    return max(0.0, min(100.0, t * 100))


def _rssi_subscore(rssi_dbm: Optional[int]) -> Optional[float]:
    if rssi_dbm is None:
        return None
    return _linear_score(rssi_dbm, zero_at=-85, hundred_at=-50)


def _latency_subscore(avg_latency_ms: Optional[float]) -> Optional[float]:
    if avg_latency_ms is None:
        return None
    return _linear_score(avg_latency_ms, zero_at=250, hundred_at=20)


def _packet_loss_subscore(avg_loss_pct: Optional[float]) -> Optional[float]:
    if avg_loss_pct is None:
        return None
    return _linear_score(avg_loss_pct, zero_at=10, hundred_at=0)


def _jitter_subscore(avg_jitter_ms: Optional[float]) -> Optional[float]:
    if avg_jitter_ms is None:
        return None
    return _linear_score(avg_jitter_ms, zero_at=60, hundred_at=5)


async def _count_recent_disconnects(
    conn: aiosqlite.Connection, interface: str, window_start: str
) -> int:
    """Counts transitions *into* a non-connected state, not samples spent
    disconnected - "how many times did it drop" rather than "for how long",
    which is what "disconnects" means as a discrete, countable event."""
    samples = await wifi_samples_repo.list_samples(
        conn, interface=interface, start=window_start, limit=10000
    )
    samples = list(
        reversed(samples)
    )  # list_samples is newest-first; need chronological order
    return sum(
        1
        for prev, curr in zip(samples, samples[1:])
        if prev.interface_state == "connected" and curr.interface_state != "connected"
    )


async def _count_recent_failed_roams(
    conn: aiosqlite.Connection, interface: str, window_start: str
) -> int:
    events = await roam_events_repo.list_roam_events(
        conn, interface=interface, start=window_start, limit=1000
    )
    return sum(1 for e in events if e.success is False)


async def compute_wireless_quality_score(
    conn: aiosqlite.Connection,
    interface: str,
    settings: AppSettings,
) -> Optional[int]:
    """
    Returns None only when there is genuinely nothing to compute from yet
    (no WiFi sample and no connectivity data at all) - a fresh install
    should read as "no score yet", never a fabricated number.
    """
    now = datetime.now(timezone.utc)
    window_start = (
        now - timedelta(minutes=settings.wireless_quality_window_minutes)
    ).isoformat()
    now_iso = now.isoformat()

    latest_sample = await wifi_samples_repo.latest_sample(conn, interface)
    rssi = latest_sample.rssi_dbm if latest_sample else None

    latencies = await measurements_repo.latencies_in_range(
        conn, target_id=None, start=window_start, end=now_iso
    )
    agg = await measurements_repo.aggregate_in_range(
        conn, target_id=None, start=window_start, end=now_iso
    )
    avg_latency = (sum(latencies) / len(latencies)) if latencies else None
    avg_loss = agg.get("avg_packet_loss")
    avg_jitter = agg.get("avg_jitter")

    subscores: Dict[str, Optional[float]] = {
        "rssi": _rssi_subscore(rssi),
        "latency": _latency_subscore(avg_latency),
        "packet_loss": _packet_loss_subscore(avg_loss),
        "jitter": _jitter_subscore(avg_jitter),
    }
    available = [v for v in subscores.values() if v is not None]
    if not available:
        return None

    base_score = sum(available) / len(available)

    disconnects = await _count_recent_disconnects(conn, interface, window_start)
    failed_roams = await _count_recent_failed_roams(conn, interface, window_start)
    # Capped so a single very noisy window can't single-handedly drive the
    # score to a meaningless negative-then-clamped-to-zero every time.
    penalty = min(40, disconnects * 10) + min(45, failed_roams * 15)

    return round(max(0.0, base_score - penalty))
