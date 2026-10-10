from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from app.config import MIN_INTERVAL_SECONDS
from app.database import measurements_repo, targets_repo, wifi_samples_repo
from app.models.measurement import MeasurementCreate
from app.models.settings import AppSettings
from app.models.target import TargetOut
from app.monitoring import wifi
from app.monitoring.wifi.models import is_connected
from app.monitoring.pinger import PingBatchResult, run_check
from app.services import connectivity_service, notification_service, roam_interruption_service, roaming_service
from app.services.settings_service import get_settings

logger = logging.getLogger("ap_monitor.scheduler")

_INITIAL_CLEANUP_DELAY = 60
_CLEANUP_INTERVAL = 3600


class MonitoringManager:
    """
    Owns one asyncio task per enabled target, plus a shared task for
    retention cleanup. Connectivity evaluation (which touches shared global
    state) is serialized behind a lock so two target loops finishing at the
    same moment can't race each other.

    NOTE (Stage 6): the sleep-gap heuristic and outage/threshold tracking
    that lived here in Internet Monitor were removed along with the
    `outages` table - that feature was specific to IM's binary online/offline
    + outage-span model, which AP Monitor replaces with a richer connectivity
    state model and roam-event log (Stages 8-10). The sleep-gap *technique*
    itself (a wall-clock gap between ticks means the process was suspended,
    not that connectivity was actually lost) is still valuable and worth
    reintroducing once there's a real event log to write it into.

    NOTE (Stage 9): a separate WiFi-polling task runs alongside the
    per-target ping loops, on its own interval (settings.wifi_poll_interval_seconds)
    independent of any target's check interval - continuing to sample WiFi
    state even if every ping target is disabled is exactly what the spec
    means by "continue collecting local WiFi data when the Internet is
    unavailable". The most recent reading is cached on the instance
    (self._wifi_connected) so each target loop's connectivity_service call
    can use it without every target polling WiFi itself.
    """

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._wifi_task: Optional[asyncio.Task] = None
        self._wifi_connected: Optional[bool] = None
        self._running = False
        self._started_at: Optional[datetime] = None
        self._start_stop_lock = asyncio.Lock()
        self._eval_lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def started_at(self) -> Optional[datetime]:
        return self._started_at

    async def start(self, conn: aiosqlite.Connection) -> None:
        async with self._start_stop_lock:
            if self._running:
                return
            self._running = True
            self._started_at = datetime.now(timezone.utc)
            targets = await targets_repo.list_targets(conn, enabled_only=True)
            for target in targets:
                self._spawn(conn, target)
            self._cleanup_task = asyncio.create_task(self._cleanup_loop(conn), name="retention-cleanup")
            self._wifi_task = asyncio.create_task(self._wifi_loop(conn), name="wifi-poll")
            logger.info("Monitoring started with %d target(s)", len(targets))

    async def stop(self) -> None:
        async with self._start_stop_lock:
            if not self._running:
                return
            self._running = False
            tasks = list(self._tasks.values())
            if self._cleanup_task:
                tasks.append(self._cleanup_task)
            if self._wifi_task:
                tasks.append(self._wifi_task)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._tasks.clear()
            self._cleanup_task = None
            self._wifi_task = None
            await roam_interruption_service.cancel_all()
            logger.info("Monitoring stopped")

    async def reload_target(self, conn: aiosqlite.Connection, target_id: int) -> None:
        """Call after a target is created/updated/deleted so the running
        set of loops reflects the change without a full restart."""
        existing = self._tasks.pop(target_id, None)
        if existing:
            existing.cancel()
        if not self._running:
            return
        target = await targets_repo.get_target(conn, target_id)
        if target and target.enabled:
            self._spawn(conn, target)

    def _spawn(self, conn: aiosqlite.Connection, target: TargetOut) -> None:
        task = asyncio.create_task(self._monitor_loop(conn, target), name=f"monitor-{target.id}")
        self._tasks[target.id] = task

    async def _monitor_loop(self, conn: aiosqlite.Connection, target: TargetOut) -> None:
        current = target
        while True:
            try:
                settings = await get_settings(conn)
                result = await run_check(
                    host=current.host, protocol=current.protocol, port=current.port,
                    count=settings.pings_per_check, timeout=settings.ping_timeout_seconds,
                )
                await measurements_repo.insert_measurement(conn, MeasurementCreate(
                    target_id=current.id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    latency_ms=result.avg_latency_ms,
                    packet_loss=result.loss_pct,
                    jitter_ms=result.jitter_ms,
                    success=result.success,
                    error=result.error,
                ))
                await self._check_thresholds(current, result, settings)
                async with self._eval_lock:
                    await connectivity_service.evaluate(conn, settings, wifi_connected=self._wifi_connected)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - defensive: one bad check must not kill the loop
                logger.exception("Unexpected error monitoring target %s (%s)", current.name, current.host)

            fresh = await targets_repo.get_target(conn, current.id)
            if fresh is None or not fresh.enabled:
                self._tasks.pop(current.id, None)
                return
            current = fresh
            await asyncio.sleep(max(MIN_INTERVAL_SECONDS, current.interval_seconds))

    async def _check_thresholds(
        self, target: TargetOut, result: PingBatchResult, settings: AppSettings
    ) -> None:
        cooldown = settings.notifications.cooldown_seconds
        if (
            result.avg_latency_ms is not None
            and result.avg_latency_ms > settings.latency_warning_threshold_ms
            and settings.notifications.on_latency_threshold
        ):
            await notification_service.send(
                f"High latency: {target.name}",
                f"{result.avg_latency_ms:.0f} ms (threshold {settings.latency_warning_threshold_ms:.0f} ms)",
                key=f"latency:{target.id}", cooldown_seconds=cooldown,
            )
        if result.loss_pct > settings.packet_loss_warning_threshold_pct and settings.notifications.on_packet_loss_threshold:
            await notification_service.send(
                f"Packet loss: {target.name}",
                f"{result.loss_pct:.0f}% loss (threshold {settings.packet_loss_warning_threshold_pct:.0f}%)",
                key=f"loss:{target.id}", cooldown_seconds=cooldown,
            )

    async def _cleanup_loop(self, conn: aiosqlite.Connection) -> None:
        try:
            await asyncio.sleep(_INITIAL_CLEANUP_DELAY)
            while True:
                settings = await get_settings(conn)
                deleted = await measurements_repo.delete_older_than(conn, settings.data_retention_days)
                if deleted:
                    logger.info("Retention cleanup removed %d measurement row(s)", deleted)
                wifi_deleted = await wifi_samples_repo.delete_older_than(conn, settings.data_retention_days)
                if wifi_deleted:
                    logger.info("Retention cleanup removed %d wifi sample row(s)", wifi_deleted)
                await asyncio.sleep(_CLEANUP_INTERVAL)
        except asyncio.CancelledError:
            raise

    async def _wifi_loop(self, conn: aiosqlite.Connection) -> None:
        """Independent of every ping target's loop and interval - this
        keeps sampling WiFi state (and checking for roams) even if every
        target is disabled or the internet is fully unreachable."""
        try:
            while True:
                settings = await get_settings(conn)
                try:
                    metrics = await wifi.get_wifi_metrics()
                except RuntimeError:
                    # No active WiFi interface right now - a real reading,
                    # not a failure to check: this app is specifically about
                    # WiFi, so "no WiFi association" correctly means
                    # disconnected even on a host that also has ethernet.
                    self._wifi_connected = False
                except Exception:  # pragma: no cover - defensive: one bad poll must not kill the loop
                    logger.exception("Unexpected error polling WiFi metrics")
                    self._wifi_connected = None  # genuinely unknown, not "disconnected"
                else:
                    self._wifi_connected = is_connected(metrics)
                    await wifi_samples_repo.insert_sample(conn, metrics)
                    await roaming_service.evaluate(conn, metrics)
                await asyncio.sleep(max(MIN_INTERVAL_SECONDS, settings.wifi_poll_interval_seconds))
        except asyncio.CancelledError:
            raise


manager = MonitoringManager()
