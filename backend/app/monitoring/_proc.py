"""
Small subprocess helpers shared by every module that shells out.

On Windows, a process started without a console (a scheduled task, a
service, pythonw.exe) pops up a visible console window for every child it
spawns unless CREATE_NO_WINDOW is passed - so a monitor that runs `ping` and
`netsh` every few seconds would flash windows constantly. `NO_WINDOW` is an
empty dict everywhere else, so call sites can always splat it.
"""

from __future__ import annotations

import sys
from typing import Any, Dict

_CREATE_NO_WINDOW = 0x08000000

NO_WINDOW: Dict[str, Any] = (
    {"creationflags": _CREATE_NO_WINDOW} if sys.platform == "win32" else {}
)


def oem_encoding() -> str:
    """Console tools on Windows (netsh, ipconfig, ping) write in the OEM
    code page, not UTF-8; decoding with the wrong one garbles non-ASCII
    SSIDs. Falls back to UTF-8 anywhere that can't be determined."""
    if sys.platform == "win32":
        try:
            import ctypes

            return f"cp{ctypes.windll.kernel32.GetOEMCP()}"  # type: ignore[attr-defined]
        except Exception:
            return "utf-8"
    return "utf-8"


def decode_output(data: bytes) -> str:
    enc = oem_encoding()
    try:
        return data.decode(enc, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")
