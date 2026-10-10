"""
Default-gateway detection, used once each to seed the "Gateway" target the
first time a database is created (see app/database/targets_repo.py) -
never on a recurring basis, so there's no caching here (contrast with
app/monitoring/wifi/, which is polled continuously and does cache).

Gateway lookups per platform: Linux reads /proc/net/route directly (see
app/database/targets_repo.py), macOS uses `route -n get default`, and Windows
uses `route print -4`.
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

from app.monitoring._proc import NO_WINDOW, decode_output

_SUBPROCESS_TIMEOUT = 3.0


async def _run(*args: str, timeout: float = _SUBPROCESS_TIMEOUT) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            **NO_WINDOW,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return decode_output(stdout)
    except (FileNotFoundError, asyncio.TimeoutError, OSError):
        return ""


async def get_default_gateway_macos() -> Optional[str]:
    """
    macOS-only default-gateway lookup via `route -n get default`'s
    "gateway:" field. Used once, to seed the default "Gateway" target the
    first time a database is created (see app/database/targets_repo.py).
    """
    output = await _run("route", "-n", "get", "default")
    m = re.search(r"gateway:\s*(\S+)", output)
    return m.group(1) if m else None


_ROUTE_ROW = re.compile(
    r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d{1,3}(?:\.\d{1,3}){3})\s+\d{1,3}(?:\.\d{1,3}){3}\s+(\d+)\s*$",
    re.MULTILINE,
)


def parse_default_gateway_windows(output: str) -> Optional[str]:
    """The gateway of the lowest-metric IPv4 default route in `route print -4`
    output. Rows are `Network Destination, Netmask, Gateway, Interface,
    Metric`; a default route has 0.0.0.0 for both destination and netmask.
    "On-link" gateways (no IPv4 next hop) deliberately do not match."""
    rows = [(int(metric), gw) for gw, metric in _ROUTE_ROW.findall(output)]
    return min(rows)[1] if rows else None


async def get_default_gateway_windows() -> Optional[str]:
    return parse_default_gateway_windows(await _run("route", "print", "-4"))
