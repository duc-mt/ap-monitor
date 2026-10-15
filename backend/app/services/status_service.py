from __future__ import annotations

import sys
import time
from datetime import datetime, timezone

UTC = timezone.utc

import aiosqlite

from app.database import measurements_repo, targets_repo
from app.models.status import StatusResponse, TargetStatus, WifiIssue
from app.monitoring import wifi
from app.monitoring.wifi import diagnostics
from app.monitoring.wifi.models import is_connected
from app.services import connectivity_service, quality_service
from app.services.settings_service import get_settings

_STATUS_CACHE_TTL = 1.0  # seconds
_last_status: StatusResponse | None = None
_last_status_at: float = 0.0


def reset_status_cache() -> None:
    """Used by tests for isolation."""
    global _last_status, _last_status_at
    _last_status = None
    _last_status_at = 0.0


async def compute_status(
    conn: aiosqlite.Connection,
    *,
    monitoring_started_at: datetime | None,
    monitoring_running: bool,
) -> StatusResponse:
    global _last_status, _last_status_at
    now_mono = time.monotonic()
    if _last_status is not None and (now_mono - _last_status_at) < _STATUS_CACHE_TTL:
        return _last_status

    settings = await get_settings(conn)
    targets = await targets_repo.list_targets(conn, enabled_only=True)
    latest_by_target = {m.target_id: m for m in await measurements_repo.latest_measurements_all(conn)}

    target_statuses: list[TargetStatus] = []
    reachable_count = 0
    have_any_measurement = bool(latest_by_target)

    headline_latencies: list[float] = []
    headline_losses: list[float] = []

    for t in targets:
        m = latest_by_target.get(t.id)
        reachable = bool(m and m.success)
        if reachable:
            reachable_count += 1
        target_statuses.append(
            TargetStatus(
                target_id=t.id,
                name=t.name,
                host=t.host,
                reachable=reachable,
                latency_ms=m.latency_ms if m else None,
                packet_loss=m.packet_loss if m else None,
                last_checked=m.timestamp if m else None,
            )
        )
        if not t.is_gateway and m is not None:
            if m.latency_ms is not None:
                headline_latencies.append(m.latency_ms)
            headline_losses.append(m.packet_loss)

    # Assume online until we have evidence otherwise (avoids a false
    # "Offline" flash during the first few seconds after startup).
    online = True if not have_any_measurement else reachable_count > 0

    avg_latency = round(sum(headline_latencies) / len(headline_latencies), 2) if headline_latencies else None
    avg_loss = round(sum(headline_losses) / len(headline_losses), 2) if headline_losses else None
    jitter_values = [m.jitter_ms for m in latest_by_target.values() if m.jitter_ms is not None]
    avg_jitter = round(sum(jitter_values) / len(jitter_values), 2) if jitter_values else None

    quality = (
        "offline"
        if (have_any_measurement and not online)
        else quality_service.classify(avg_latency, avg_loss, settings.classification)
    )

    uptime = 0.0
    if monitoring_running and monitoring_started_at is not None:
        uptime = (datetime.now(UTC) - monitoring_started_at).total_seconds()

    # WiFi fields: best-effort, and every one of them stays None together
    # when there's no active WiFi interface at all - a fresh reading is
    # used (use_cache defaults to True here, which is fine: this is a
    # once-per-poll dashboard read, not a tight measurement loop, so the
    # normal 2s cache is exactly the right tradeoff, unlike walk-test mode).
    wifi_interface = ssid = bssid = band = phy_mode = None
    rssi_dbm = channel = channel_width_mhz = snr_db = noise_floor_dbm = tx_bitrate_mbps = None
    wifi_issue: WifiIssue | None = None
    # None = genuinely unknown (an unexpected adapter error, or an adapter
    # that could not tell); False = a real "no active WiFi interface"
    # reading, matching exactly how scheduler._wifi_loop treats the same
    # RuntimeError from get_wifi_metrics.
    wifi_connected: bool | None = None
    try:
        active_iface = await wifi.get_active_wifi_interface()
        if active_iface is None:
            wifi_connected = False
            adapter_issue = wifi.get_adapter_issue()
            wifi_issue = diagnostics.issue_for(adapter_issue) if adapter_issue else diagnostics.no_interface_issue()
        else:
            metrics = await wifi.get_wifi_metrics(active_iface)
            wifi_interface = metrics.interface
            ssid, bssid, band, phy_mode = (
                metrics.ssid,
                metrics.bssid,
                metrics.band,
                metrics.phy_mode,
            )
            rssi_dbm, channel = metrics.rssi_dbm, metrics.channel
            channel_width_mhz, snr_db = metrics.channel_width_mhz, metrics.snr_db
            noise_floor_dbm, tx_bitrate_mbps = (
                metrics.noise_floor_dbm,
                metrics.tx_bitrate_mbps,
            )
            wifi_connected = is_connected(metrics)
            wifi_issue = diagnostics.diagnose(metrics)
    except Exception:
        # status is best-effort; a WiFi read failure shouldn't break the
        # whole endpoint - but it must not be silent either.
        wifi_issue = diagnostics.issue_for("adapter_error")

    # Read-only: compute_status() never fires notifications or touches
    # transition state, unlike the scheduler's own call to evaluate() -
    # see connectivity_service's module docstring for why that split exists.
    connectivity = await connectivity_service.compute_status(conn, settings, wifi_connected=wifi_connected)

    wireless_quality_score = None
    if wifi_interface is not None:
        wireless_quality_score = await quality_service.compute_wireless_quality_score(conn, wifi_interface, settings)

    result = StatusResponse(
        online=online,
        quality=quality,
        latency_ms=avg_latency,
        packet_loss=avg_loss,
        jitter_ms=avg_jitter,
        monitoring_uptime_seconds=uptime,
        targets_reachable=reachable_count,
        targets_total=len(targets),
        targets=target_statuses,
        monitoring_running=monitoring_running,
        wifi_interface=wifi_interface,
        ssid=ssid,
        bssid=bssid,
        rssi_dbm=rssi_dbm,
        channel=channel,
        band=band,
        phy_mode=phy_mode,
        channel_width_mhz=channel_width_mhz,
        snr_db=snr_db,
        noise_floor_dbm=noise_floor_dbm,
        tx_bitrate_mbps=tx_bitrate_mbps,
        wifi_issue=wifi_issue,
        platform=sys.platform,
        connectivity=connectivity,
        wireless_quality_score=wireless_quality_score,
    )
    _last_status = result
    _last_status_at = now_mono
    return result
