from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiosqlite

from app.database.connection import write_transaction
from app.monitoring.wifi.models import WifiMetrics

_COLUMNS = (
    "timestamp",
    "interface",
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
    "ipv4_addresses",
    "ipv6_addresses",
    "gateway",
    "dns_servers",
)


def _row_to_metrics(row: aiosqlite.Row) -> WifiMetrics:
    def _json_or_none(value):
        return json.loads(value) if value is not None else None

    return WifiMetrics(
        timestamp=row["timestamp"],
        interface=row["interface"],
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
        ipv4_addresses=_json_or_none(row["ipv4_addresses"]),
        ipv6_addresses=_json_or_none(row["ipv6_addresses"]),
        gateway=row["gateway"],
        dns_servers=_json_or_none(row["dns_servers"]),
    )


async def insert_sample(conn: aiosqlite.Connection, m: WifiMetrics) -> int:
    values = (
        m.timestamp,
        m.interface,
        m.interface_state,
        m.ssid,
        m.bssid,
        m.frequency_mhz,
        m.channel,
        m.band,
        m.rssi_dbm,
        m.signal_pct,
        m.noise_floor_dbm,
        m.snr_db,
        m.phy_mode,
        m.channel_width_mhz,
        m.mcs_index,
        m.tx_bitrate_mbps,
        m.rx_bitrate_mbps,
        m.phy_rate_mbps,
        json.dumps(m.ipv4_addresses) if m.ipv4_addresses is not None else None,
        json.dumps(m.ipv6_addresses) if m.ipv6_addresses is not None else None,
        m.gateway,
        json.dumps(m.dns_servers) if m.dns_servers is not None else None,
    )
    placeholders = ", ".join("?" for _ in _COLUMNS)
    async with write_transaction() as tx:
        cursor = await tx.execute(
            f"INSERT INTO wifi_samples ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
            values,
        )
    return cursor.lastrowid


async def latest_sample(
    conn: aiosqlite.Connection, interface: str
) -> Optional[WifiMetrics]:
    async with conn.execute(
        "SELECT * FROM wifi_samples WHERE interface = ? ORDER BY timestamp DESC LIMIT 1",
        (interface,),
    ) as cursor:
        row = await cursor.fetchone()
    return _row_to_metrics(row) if row else None


async def list_samples(
    conn: aiosqlite.Connection,
    *,
    interface: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 1000,
) -> list[WifiMetrics]:
    query = "SELECT * FROM wifi_samples WHERE 1=1"
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
    return [_row_to_metrics(r) for r in rows]


async def delete_older_than(conn: aiosqlite.Connection, retention_days: int) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    async with write_transaction() as tx:
        cursor = await tx.execute(
            "DELETE FROM wifi_samples WHERE timestamp < ?", (cutoff,)
        )
    return cursor.rowcount
