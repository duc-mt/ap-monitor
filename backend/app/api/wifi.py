from __future__ import annotations

from datetime import UTC, datetime, timedelta

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_db
from app.database import wifi_samples_repo
from app.models.wifi_analysis import SignalAnalysis
from app.models.wifi_scan import EnvironmentScanResult
from app.monitoring import wifi
from app.monitoring.wifi.models import WifiInterfaceInfo, WifiMetrics
from app.services import ap_analysis_service

router = APIRouter(prefix="/api/wifi", tags=["wifi"])


@router.get("/interfaces", response_model=list[WifiInterfaceInfo])
async def list_interfaces():
    return await wifi.list_wifi_interfaces()


@router.get("/samples", response_model=list[WifiMetrics])
async def list_samples(
    interface: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 1000,
    db: aiosqlite.Connection = Depends(get_db),
):
    """History of periodic WiFi metric polls - for charting RSSI/channel/etc.
    over time. Defaults to every interface if none is given."""
    return await wifi_samples_repo.list_samples(
        db, interface=interface, start=start, end=end, limit=limit
    )


@router.get("/analysis", response_model=SignalAnalysis)
async def wifi_analysis(
    minutes: int = Query(60, ge=1, le=10080, description="Look-back window."),
    interface: str | None = None,
    weak_threshold_dbm: int = Query(
        ap_analysis_service.DEFAULT_WEAK_THRESHOLD_DBM, ge=-100, le=-30
    ),
    max_points: int = Query(ap_analysis_service.DEFAULT_MAX_POINTS, ge=50, le=5000),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Which access point(s) the client was on over the last `minutes`, how
    strong the signal was, where it went weak, and when it switched APs.
    Backs the dashboard's AP timeline. Defaults to the interface that was
    sampled most recently."""
    if interface is None:
        latest = await wifi_samples_repo.list_samples(db, limit=1)
        interface = latest[0].interface if latest else None
    samples: list = []
    if interface is not None:
        start = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
        samples = await wifi_samples_repo.list_samples(
            db, interface=interface, start=start, limit=50000
        )
    return ap_analysis_service.analyze(
        samples, weak_threshold_dbm=weak_threshold_dbm, max_points=max_points
    )


@router.post("/scan", response_model=EnvironmentScanResult)
async def scan_environment(
    interface: str | None = None, db: aiosqlite.Connection = Depends(get_db)
):
    """
    The on-demand "Scan Environment" action - never called on a timer
    anywhere in the app. Actively scans for surrounding networks
    (`iw scan` on Linux, `system_profiler SPAirPortDataType` on macOS,
    `netsh wlan show networks mode=bssid` on Windows - the only place the app
    runs any of those) and flags any
    neighbor sharing the current connection's channel.
    """
    try:
        return await wifi.scan_environment(interface)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
