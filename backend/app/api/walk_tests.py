from __future__ import annotations

import csv
import io
import re

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api.deps import get_db
from app.database import walk_tests_repo
from app.models.walk_test import WalkTestCreate, WalkTestOut, WalkTestSampleOut
from app.models.wifi_analysis import SignalAnalysis
from app.services import ap_analysis_service, walk_test_service

router = APIRouter(prefix="/api/walk-tests", tags=["walk-tests"])


@router.post("", response_model=WalkTestOut, status_code=201)
async def start_walk_test(data: WalkTestCreate, db: aiosqlite.Connection = Depends(get_db)):
    try:
        return await walk_test_service.start_session(db, data)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{walk_test_id}/stop", response_model=WalkTestOut)
async def stop_walk_test(walk_test_id: int, db: aiosqlite.Connection = Depends(get_db)):
    try:
        return await walk_test_service.stop_session(db, walk_test_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("", response_model=list[WalkTestOut])
async def list_walk_tests(db: aiosqlite.Connection = Depends(get_db)):
    return await walk_tests_repo.list_walk_tests(db)


@router.get("/{walk_test_id}", response_model=WalkTestOut)
async def get_walk_test(walk_test_id: int, db: aiosqlite.Connection = Depends(get_db)):
    result = await walk_tests_repo.get_walk_test(db, walk_test_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No walk-test session with id={walk_test_id}")
    return result


@router.get("/{walk_test_id}/samples", response_model=list[WalkTestSampleOut])
async def list_walk_test_samples(walk_test_id: int, db: aiosqlite.Connection = Depends(get_db)):
    result = await walk_tests_repo.get_walk_test(db, walk_test_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No walk-test session with id={walk_test_id}")
    return await walk_tests_repo.list_samples(db, walk_test_id)


@router.get("/{walk_test_id}/analysis", response_model=SignalAnalysis)
async def analyze_walk_test(
    walk_test_id: int,
    weak_threshold_dbm: int = Query(ap_analysis_service.DEFAULT_WEAK_THRESHOLD_DBM, ge=-100, le=-30),
    max_points: int = Query(ap_analysis_service.DEFAULT_MAX_POINTS, ge=50, le=5000),
    db: aiosqlite.Connection = Depends(get_db),
):
    """The walk-test *result*: per-AP breakdown, signal timeline, AP changes
    and weak-signal stretches computed from the recorded samples."""
    if await walk_tests_repo.get_walk_test(db, walk_test_id) is None:
        raise HTTPException(status_code=404, detail="Walk test not found")
    samples = await walk_tests_repo.list_samples(db, walk_test_id)
    return ap_analysis_service.analyze(samples, weak_threshold_dbm=weak_threshold_dbm, max_points=max_points)


_CSV_COLUMNS = (
    "timestamp", "interface_state", "ssid", "bssid", "band", "channel", "frequency_mhz", "rssi_dbm", "signal_pct",
    "noise_floor_dbm", "snr_db", "phy_mode", "channel_width_mhz", "mcs_index", "tx_bitrate_mbps",
    "rx_bitrate_mbps", "latency_ms", "packet_loss_pct", "reachable",
)


@router.get("/{walk_test_id}/export")
async def export_walk_test(walk_test_id: int, db: aiosqlite.Connection = Depends(get_db)):
    """Every recorded sample as CSV, for Excel or a heat-map tool."""
    session = await walk_tests_repo.get_walk_test(db, walk_test_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Walk test not found")
    samples = await walk_tests_repo.list_samples(db, walk_test_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_CSV_COLUMNS)
    for smp in samples:
        writer.writerow(["" if getattr(smp, c) is None else getattr(smp, c) for c in _CSV_COLUMNS])
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", session.name).strip("-") or "walk-test"
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="walk-test-{walk_test_id}-{safe}.csv"'},
    )


@router.delete("/{walk_test_id}", status_code=204)
async def delete_walk_test(walk_test_id: int, db: aiosqlite.Connection = Depends(get_db)):
    if walk_test_service.active_walk_test_id() == walk_test_id:
        raise HTTPException(status_code=409, detail="Stop the session before deleting it.")
    deleted = await walk_tests_repo.delete_walk_test(db, walk_test_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No walk-test session with id={walk_test_id}")
