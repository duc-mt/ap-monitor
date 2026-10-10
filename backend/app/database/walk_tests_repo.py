from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from app.database.connection import write_transaction
from app.models.walk_test import WalkTestOut, WalkTestSampleOut

_SAMPLE_COLUMNS = (
    "walk_test_id",
    "timestamp",
    "interface_state",
    "ssid",
    "bssid",
    "frequency_mhz",
    "channel",
    "band",
    "rssi_dbm",
    "signal_pct",
    "noise_floor_dbm",
    "snr_db",
    "phy_mode",
    "channel_width_mhz",
    "mcs_index",
    "tx_bitrate_mbps",
    "rx_bitrate_mbps",
    "phy_rate_mbps",
    "latency_ms",
    "packet_loss_pct",
    "reachable",
)


async def _row_to_walk_test(
    conn: aiosqlite.Connection, row: aiosqlite.Row
) -> WalkTestOut:
    async with conn.execute(
        "SELECT COUNT(*) AS n FROM walk_test_samples WHERE walk_test_id = ?",
        (row["id"],),
    ) as cursor:
        count_row = await cursor.fetchone()
    return WalkTestOut(
        id=row["id"],
        name=row["name"],
        site=row["site"],
        area=row["area"],
        interface=row["interface"],
        target_ids=json.loads(row["target_ids"]),
        status=row["status"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        sample_count=count_row["n"],
    )


def _row_to_sample(row: aiosqlite.Row) -> WalkTestSampleOut:
    return WalkTestSampleOut(
        id=row["id"],
        walk_test_id=row["walk_test_id"],
        timestamp=row["timestamp"],
        interface_state=row["interface_state"],
        ssid=row["ssid"],
        bssid=row["bssid"],
        frequency_mhz=row["frequency_mhz"],
        channel=row["channel"],
        band=row["band"],
        rssi_dbm=row["rssi_dbm"],
        signal_pct=row["signal_pct"],
        noise_floor_dbm=row["noise_floor_dbm"],
        snr_db=row["snr_db"],
        phy_mode=row["phy_mode"],
        channel_width_mhz=row["channel_width_mhz"],
        mcs_index=row["mcs_index"],
        tx_bitrate_mbps=row["tx_bitrate_mbps"],
        rx_bitrate_mbps=row["rx_bitrate_mbps"],
        phy_rate_mbps=row["phy_rate_mbps"],
        latency_ms=row["latency_ms"],
        packet_loss_pct=row["packet_loss_pct"],
        reachable=(bool(row["reachable"]) if row["reachable"] is not None else None),
    )


async def create_walk_test(
    conn: aiosqlite.Connection,
    *,
    name: str,
    site: Optional[str],
    area: Optional[str],
    interface: str,
    target_ids: list[int],
) -> WalkTestOut:
    started_at = datetime.now(timezone.utc).isoformat()
    async with write_transaction() as tx:
        cursor = await tx.execute(
            "INSERT INTO walk_tests (name, site, area, interface, target_ids, status, started_at) "
            "VALUES (?, ?, ?, ?, ?, 'recording', ?)",
            (name, site, area, interface, json.dumps(target_ids), started_at),
        )
        row_id = cursor.lastrowid
        async with tx.execute(
            "SELECT * FROM walk_tests WHERE id = ?", (row_id,)
        ) as read_cursor:
            row = await read_cursor.fetchone()
    return await _row_to_walk_test(conn, row)


async def stop_walk_test(
    conn: aiosqlite.Connection, walk_test_id: int
) -> Optional[WalkTestOut]:
    ended_at = datetime.now(timezone.utc).isoformat()
    async with write_transaction() as tx:
        await tx.execute(
            "UPDATE walk_tests SET status = 'stopped', ended_at = ? WHERE id = ? AND status = 'recording'",
            (ended_at, walk_test_id),
        )
        async with tx.execute(
            "SELECT * FROM walk_tests WHERE id = ?", (walk_test_id,)
        ) as read_cursor:
            row = await read_cursor.fetchone()
    return await _row_to_walk_test(conn, row) if row else None


async def get_walk_test(
    conn: aiosqlite.Connection, walk_test_id: int
) -> Optional[WalkTestOut]:
    async with conn.execute(
        "SELECT * FROM walk_tests WHERE id = ?", (walk_test_id,)
    ) as cursor:
        row = await cursor.fetchone()
    return await _row_to_walk_test(conn, row) if row else None


async def list_walk_tests(
    conn: aiosqlite.Connection, *, limit: int = 100
) -> list[WalkTestOut]:
    async with conn.execute(
        "SELECT * FROM walk_tests ORDER BY started_at DESC LIMIT ?", (limit,)
    ) as cursor:
        rows = await cursor.fetchall()
    return [await _row_to_walk_test(conn, r) for r in rows]


async def delete_walk_test(conn: aiosqlite.Connection, walk_test_id: int) -> bool:
    async with write_transaction() as tx:
        cursor = await tx.execute(
            "DELETE FROM walk_tests WHERE id = ?", (walk_test_id,)
        )
    return cursor.rowcount > 0


async def insert_sample(
    conn: aiosqlite.Connection, walk_test_id: int, sample: dict
) -> int:
    """`sample` is a plain dict keyed by column name (a WifiMetrics' fields
    plus latency_ms/packet_loss_pct/reachable) - kept as a dict rather than
    a dataclass/model since it's an internal, service-constructed shape
    with no independent identity of its own outside this one insert."""
    values = tuple(
        sample.get(c, walk_test_id if c == "walk_test_id" else None)
        for c in _SAMPLE_COLUMNS
    )
    placeholders = ", ".join("?" for _ in _SAMPLE_COLUMNS)
    async with write_transaction() as tx:
        cursor = await tx.execute(
            f"INSERT INTO walk_test_samples ({', '.join(_SAMPLE_COLUMNS)}) VALUES ({placeholders})",
            values,
        )
    return cursor.lastrowid


async def list_samples(
    conn: aiosqlite.Connection, walk_test_id: int, *, limit: int = 100000
) -> list[WalkTestSampleOut]:
    async with conn.execute(
        "SELECT * FROM walk_test_samples WHERE walk_test_id = ? ORDER BY timestamp ASC LIMIT ?",
        (walk_test_id, limit),
    ) as cursor:
        rows = await cursor.fetchall()
    return [_row_to_sample(r) for r in rows]
