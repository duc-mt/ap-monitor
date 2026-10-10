from __future__ import annotations

from typing import List, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_db
from app.database import roam_events_repo
from app.models.roam_event import RoamEventOut

router = APIRouter(prefix="/api/roam-events", tags=["roam-events"])


@router.get("", response_model=List[RoamEventOut])
async def list_roam_events(
    interface: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 200,
    db: aiosqlite.Connection = Depends(get_db),
):
    return await roam_events_repo.list_roam_events(
        db, interface=interface, start=start, end=end, limit=limit
    )


@router.get("/{event_id}", response_model=RoamEventOut)
async def get_roam_event(event_id: int, db: aiosqlite.Connection = Depends(get_db)):
    result = await roam_events_repo.get_roam_event(db, event_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No roam event with id={event_id}")
    return result
