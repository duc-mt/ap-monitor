"""
==============================================================================
Module Name:   network_info.py
Description:   Source module network_info.py.
Author:        Mai Tan Duc <ducmai.network@gmail.com>
Created:       2026-10-10
Version:       1.0.0
License:       MIT
==============================================================================
Usage:         python3 network_info.py [options]
Notes:         Requires Python 3.8+
==============================================================================
"""

from __future__ import annotations

import asyncio
import re

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
    except (TimeoutError, FileNotFoundError, OSError):
        return ""


async def get_default_gateway_macos() -> str | None:
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


def parse_default_gateway_windows(output: str) -> str | None:
    """The gateway of the lowest-metric IPv4 default route in `route print -4`
    output. Rows are `Network Destination, Netmask, Gateway, Interface,
    Metric`; a default route has 0.0.0.0 for both destination and netmask.
    "On-link" gateways (no IPv4 next hop) deliberately do not match."""
    rows = [(int(metric), gw) for gw, metric in _ROUTE_ROW.findall(output)]
    return min(rows)[1] if rows else None


async def get_default_gateway_windows() -> str | None:
    return parse_default_gateway_windows(await _run("route", "print", "-4"))
