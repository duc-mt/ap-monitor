from __future__ import annotations

import json

import aiosqlite

from app.database.connection import write_transaction
from app.models.roam_event import RoamEventCreate, RoamEventOut

_INSERT_COLUMNS = (
    "timestamp",
    "interface",
    "ssid",
    "previous_bssid",
    "new_bssid",
    "previous_frequency_mhz",
    "new_frequency_mhz",
    "previous_channel",
    "new_channel",
    "previous_band",
    "new_band",
    "previous_phy_mode",
    "new_phy_mode",
    "previous_channel_width_mhz",
    "new_channel_width_mhz",
    "previous_mcs_index",
    "new_mcs_index",
    "previous_rssi_dbm",
    "new_rssi_dbm",
    "ip_changed",
    "previous_ipv4",
    "new_ipv4",
)


def _row_to_event(row: aiosqlite.Row) -> RoamEventOut:
    def _json_or_none(value):
        return json.loads(value) if value is not None else None

    return RoamEventOut(
        id=row["id"],
        timestamp=row["timestamp"],
        interface=row["interface"],
        ssid=row["ssid"],
        previous_bssid=row["previous_bssid"],
        new_bssid=row["new_bssid"],
        previous_frequency_mhz=row["previous_frequency_mhz"],
        new_frequency_mhz=row["new_frequency_mhz"],
        previous_channel=row["previous_channel"],
        new_channel=row["new_channel"],
        previous_band=row["previous_band"],
        new_band=row["new_band"],
        previous_phy_mode=row["previous_phy_mode"],
        new_phy_mode=row["new_phy_mode"],
        previous_channel_width_mhz=row["previous_channel_width_mhz"],
        new_channel_width_mhz=row["new_channel_width_mhz"],
        previous_mcs_index=row["previous_mcs_index"],
        new_mcs_index=row["new_mcs_index"],
        previous_rssi_dbm=row["previous_rssi_dbm"],
        new_rssi_dbm=row["new_rssi_dbm"],
        ip_changed=bool(row["ip_changed"]),
        previous_ipv4=_json_or_none(row["previous_ipv4"]),
        new_ipv4=_json_or_none(row["new_ipv4"]),
        gateway_interruption_ms=row["gateway_interruption_ms"],
        internet_interruption_ms=row["internet_interruption_ms"],
        packet_loss_during_pct=row["packet_loss_during_pct"],
        peak_latency_ms=row["peak_latency_ms"],
        success=(bool(row["success"]) if row["success"] is not None else None),
        classification=row["classification"],
        confidence=row["confidence"],
    )


async def create_roam_event(
    conn: aiosqlite.Connection, data: RoamEventCreate
) -> RoamEventOut:
    values = (
        data.timestamp,
        data.interface,
        data.ssid,
        data.previous_bssid,
        data.new_bssid,
        data.previous_frequency_mhz,
        data.new_frequency_mhz,
        data.previous_channel,
        data.new_channel,
        data.previous_band,
        data.new_band,
        data.previous_phy_mode,
        data.new_phy_mode,
        data.previous_channel_width_mhz,
        data.new_channel_width_mhz,
        data.previous_mcs_index,
        data.new_mcs_index,
        data.previous_rssi_dbm,
        data.new_rssi_dbm,
        int(data.ip_changed),
        json.dumps(data.previous_ipv4) if data.previous_ipv4 is not None else None,
        json.dumps(data.new_ipv4) if data.new_ipv4 is not None else None,
    )
    placeholders = ", ".join("?" for _ in _INSERT_COLUMNS)
    async with write_transaction() as tx:
        cursor = await tx.execute(
            f"INSERT INTO roam_events ({', '.join(_INSERT_COLUMNS)}) VALUES ({placeholders})",
            values,
        )
        row_id = cursor.lastrowid
        async with tx.execute(
            "SELECT * FROM roam_events WHERE id = ?", (row_id,)
        ) as read_cursor:
            row = await read_cursor.fetchone()
    return _row_to_event(row)


async def get_roam_event(
    conn: aiosqlite.Connection, event_id: int
) -> RoamEventOut | None:
    async with conn.execute(
        "SELECT * FROM roam_events WHERE id = ?", (event_id,)
    ) as cursor:
        row = await cursor.fetchone()
    return _row_to_event(row) if row else None


async def update_interruption_result(
    conn: aiosqlite.Connection,
    event_id: int,
    *,
    gateway_interruption_ms: float | None,
    internet_interruption_ms: float | None,
    packet_loss_during_pct: float | None,
    peak_latency_ms: float | None,
    success: bool | None,
    classification: str | None,
    confidence: str | None,
) -> None:
    """Fills in the Stage-10 columns on an already-created roam event, once
    the interruption watch (app.services.roam_interruption_service) has
    finished observing it. Every argument stays nullable end to end - a
    field left None here means "not determined", never a fabricated 0."""
    async with write_transaction() as tx:
        await tx.execute(
            """
            UPDATE roam_events SET
                gateway_interruption_ms = ?, internet_interruption_ms = ?,
                packet_loss_during_pct = ?, peak_latency_ms = ?,
                success = ?, classification = ?, confidence = ?
            WHERE id = ?
            """,
            (
                gateway_interruption_ms,
                internet_interruption_ms,
                packet_loss_during_pct,
                peak_latency_ms,
                (int(success) if success is not None else None),
                classification,
                confidence,
                event_id,
            ),
        )


async def list_roam_events(
    conn: aiosqlite.Connection,
    *,
    interface: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 200,
) -> list[RoamEventOut]:
    query = "SELECT * FROM roam_events WHERE 1=1"
    params: list = []
    if interface is not None:
        query += " AND interface = ?"
        params.append(interface)
    if start is not None:
        query += " AND timestamp >= ?"
        params.append(start)
    if end is not None:
        query += " AND timestamp <= ?"
        params.append(end)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    async with conn.execute(query, params) as cursor:
        rows = await cursor.fetchall()
    return [_row_to_event(r) for r in rows]


async def delete_older_than(conn: aiosqlite.Connection, retention_days: int) -> int:
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    async with write_transaction() as tx:
        cursor = await tx.execute(
            "DELETE FROM roam_events WHERE timestamp < ?", (cutoff,)
        )
    return cursor.rowcount
