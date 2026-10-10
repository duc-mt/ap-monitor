"""
Pure analysis of a time-ordered series of WiFi readings: which access point
the client was on, for how long, how strong the signal was, where it
dropped below a usable level, and when it switched APs.

Deliberately free of I/O and of any dependency on where the readings came
from: it accepts anything with the WiFi sample attribute names (a
WifiMetrics, a WalkTestSampleOut, a test stub), so the same code analyses a
walk-test session and a window of the always-on poll.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from app.models.wifi_analysis import (
    ApChange,
    ApSegment,
    ApUsage,
    SignalAnalysis,
    SignalPoint,
    SignalSummary,
    WeakStretch,
)

DEFAULT_WEAK_THRESHOLD_DBM = -70
DEFAULT_MAX_POINTS = 1200


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _is_connected(sample: Any) -> bool:
    state = getattr(sample, "interface_state", None)
    if state == "connected":
        return True
    # An adapter that could not name the state ("unknown") but did read a
    # signal is, for analysis purposes, associated.
    return state in (None, "unknown") and getattr(sample, "rssi_dbm", None) is not None


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


class _Seg:
    def __init__(self, sample: Any, t: datetime):
        self.bssid = getattr(sample, "bssid", None)
        self.ssid = getattr(sample, "ssid", None)
        self.start_t = self.end_t = t
        self.start = self.end = sample.timestamp
        self.rssis: list[int] = []
        self.channels: Counter = Counter()
        self.bands: Counter = Counter()
        self.count = 0
        self.last_rssi: int | None = None
        self.first_rssi: int | None = None
        self.add(sample, t)

    def add(self, sample: Any, t: datetime) -> None:
        self.end_t, self.end = t, sample.timestamp
        self.count += 1
        rssi = getattr(sample, "rssi_dbm", None)
        if rssi is not None:
            self.rssis.append(rssi)
            self.last_rssi = rssi
            if self.first_rssi is None:
                self.first_rssi = rssi
        if getattr(sample, "channel", None) is not None:
            self.channels[sample.channel] += 1
        if getattr(sample, "band", None):
            self.bands[sample.band] += 1
        if self.ssid is None:
            self.ssid = getattr(sample, "ssid", None)

    def duration(self) -> float:
        return round((self.end_t - self.start_t).total_seconds(), 2)

    def to_model(self) -> ApSegment:
        return ApSegment(
            bssid=self.bssid,
            ssid=self.ssid,
            band=self.bands.most_common(1)[0][0] if self.bands else None,
            channel=self.channels.most_common(1)[0][0] if self.channels else None,
            start=self.start,
            end=self.end,
            duration_seconds=self.duration(),
            sample_count=self.count,
            rssi_min=min(self.rssis) if self.rssis else None,
            rssi_avg=_avg(self.rssis),
            rssi_max=max(self.rssis) if self.rssis else None,
        )


def analyze(
    samples: Iterable[Any],
    *,
    weak_threshold_dbm: int = DEFAULT_WEAK_THRESHOLD_DBM,
    max_points: int = DEFAULT_MAX_POINTS,
) -> SignalAnalysis:
    ordered = sorted(((_parse(s.timestamp), s) for s in samples), key=lambda x: x[0])
    summary = SignalSummary(weak_threshold_dbm=weak_threshold_dbm)
    if not ordered:
        return SignalAnalysis(
            summary=summary,
            aps=[],
            segments=[],
            ap_changes=[],
            weak_stretches=[],
            points=[],
        )

    segs: list[_Seg] = []
    gap_before: list[bool] = []  # True if a disconnected sample preceded segs[i]
    cur: _Seg | None = None
    gap = False
    boundary_idx: set = set()
    point_models: list[SignalPoint] = []

    weak: list[WeakStretch] = []
    weak_run: list[tuple] = []  # (t, sample)

    def flush_weak() -> None:
        if len(weak_run) >= 2:
            ts = [t for t, _ in weak_run]
            rs = [s.rssi_dbm for _, s in weak_run]
            weak.append(
                WeakStretch(
                    start=weak_run[0][1].timestamp,
                    end=weak_run[-1][1].timestamp,
                    duration_seconds=round((ts[-1] - ts[0]).total_seconds(), 2),
                    sample_count=len(weak_run),
                    min_rssi_dbm=min(rs),
                    bssid=getattr(weak_run[0][1], "bssid", None),
                )
            )
        weak_run.clear()

    connected_rssis: list[int] = []
    snrs: list[float] = []
    rates: list[float] = []
    connected_count = 0
    weak_count = 0
    rssi_count = 0

    for i, (t, s) in enumerate(ordered):
        connected = _is_connected(s)
        point_models.append(
            SignalPoint(
                t=s.timestamp,
                rssi=getattr(s, "rssi_dbm", None),
                snr=getattr(s, "snr_db", None),
                bssid=getattr(s, "bssid", None),
                channel=getattr(s, "channel", None),
                rate=getattr(s, "tx_bitrate_mbps", None),
                connected=connected,
            )
        )
        if not connected:
            cur = None
            gap = True
            flush_weak()
            continue

        connected_count += 1
        bssid = getattr(s, "bssid", None)
        # A reading with no BSSID says nothing about which AP: keep it on the
        # current segment rather than splitting (or inventing) one.
        if (
            cur is None
            or (bssid is not None and cur.bssid is not None and bssid != cur.bssid)
            or (bssid is not None and cur.bssid is None)
        ):
            cur = _Seg(s, t)
            segs.append(cur)
            gap_before.append(gap and len(segs) > 1)
            gap = False
            boundary_idx.add(i)
            flush_weak()
        else:
            cur.add(s, t)

        rssi = getattr(s, "rssi_dbm", None)
        if rssi is not None:
            connected_rssis.append(rssi)
            rssi_count += 1
            if rssi < weak_threshold_dbm:
                weak_count += 1
                weak_run.append((t, s))
            else:
                flush_weak()
        if getattr(s, "snr_db", None) is not None:
            snrs.append(s.snr_db)
        if getattr(s, "tx_bitrate_mbps", None):
            rates.append(s.tx_bitrate_mbps)
    flush_weak()

    # AP changes: adjacent segments with two real, different BSSIDs.
    changes: list[ApChange] = []
    for idx in range(1, len(segs)):
        prev, nxt = segs[idx - 1], segs[idx]
        if prev.bssid and nxt.bssid and prev.bssid != nxt.bssid:
            changes.append(
                ApChange(
                    timestamp=nxt.start,
                    ssid=nxt.ssid or prev.ssid,
                    from_bssid=prev.bssid,
                    to_bssid=nxt.bssid,
                    same_ssid=(prev.ssid == nxt.ssid),
                    via_disconnect=gap_before[idx],
                    rssi_before=prev.last_rssi,
                    rssi_after=nxt.first_rssi,
                )
            )

    # Per-AP rollup.
    usage: dict = {}
    for sg in segs:
        u = usage.setdefault(
            sg.bssid,
            {
                "segs": [],
                "rssis": [],
                "secs": 0.0,
                "count": 0,
                "ssid": sg.ssid,
                "ch": Counter(),
                "band": Counter(),
            },
        )
        u["segs"].append(sg)
        u["rssis"].extend(sg.rssis)
        u["secs"] += sg.duration()
        u["count"] += sg.count
        u["ssid"] = u["ssid"] or sg.ssid
        u["ch"].update(sg.channels)
        u["band"].update(sg.bands)
    aps = [
        ApUsage(
            bssid=b,
            ssid=u["ssid"],
            band=u["band"].most_common(1)[0][0] if u["band"] else None,
            channel=u["ch"].most_common(1)[0][0] if u["ch"] else None,
            visits=len(u["segs"]),
            total_seconds=round(u["secs"], 2),
            sample_count=u["count"],
            share_pct=round(u["count"] / connected_count * 100, 1)
            if connected_count
            else 0.0,
            rssi_min=min(u["rssis"]) if u["rssis"] else None,
            rssi_avg=_avg(u["rssis"]),
            rssi_max=max(u["rssis"]) if u["rssis"] else None,
        )
        for b, u in usage.items()
    ]
    aps.sort(key=lambda a: (a.total_seconds, a.sample_count), reverse=True)

    first_t, last_t = ordered[0][0], ordered[-1][0]
    summary = SignalSummary(
        start=ordered[0][1].timestamp,
        end=ordered[-1][1].timestamp,
        duration_seconds=round((last_t - first_t).total_seconds(), 2),
        sample_count=len(ordered),
        connected_sample_count=connected_count,
        rssi_min=min(connected_rssis) if connected_rssis else None,
        rssi_avg=_avg(connected_rssis),
        rssi_max=max(connected_rssis) if connected_rssis else None,
        snr_avg=_avg(snrs),
        tx_rate_avg=_avg(rates),
        weak_threshold_dbm=weak_threshold_dbm,
        pct_samples_weak=round(weak_count / rssi_count * 100, 1)
        if rssi_count
        else None,
        distinct_aps=len({b for b in usage if b is not None}),
        ap_change_count=len(changes),
        bssid_available=(connected_count == 0) or any(b is not None for b in usage),
    )

    # Downsample for charting, always keeping the first sample of every AP
    # segment so the colour changes survive thinning.
    n = len(point_models)
    stride = max(1, math.ceil(n / max_points)) if max_points > 0 else 1
    keep = [
        pm
        for i, pm in enumerate(point_models)
        if i % stride == 0 or i in boundary_idx or i == n - 1
    ]

    return SignalAnalysis(
        summary=summary,
        aps=aps,
        segments=[sg.to_model() for sg in segs],
        ap_changes=changes,
        weak_stretches=weak,
        points=keep,
    )
