"""
Console-less entry point: `python -m app.serve` (or `pythonw -m app.serve`).

Why this exists instead of `python -m uvicorn app.main:app`: on Windows the
autostart task runs under pythonw.exe so no console window appears, and
pythonw has no stdout/stderr (both are None). uvicorn's logging calls
`.isatty()` on them during startup and crashes. Giving the process a log file
to write to first avoids that, and gives a service that has no terminal a log
to read. When a real console is attached nothing here changes anything.

Host, port and data directory come from the same environment variables as
every other way of starting the app (AP_MONITOR_HOST / _PORT / _DATA_DIR).
"""

from __future__ import annotations

import sys


def _ensure_streams() -> None:
    if sys.stdout is not None and sys.stderr is not None:
        return
    from app.config import DATA_DIR

    log_path = DATA_DIR / "logs" / "ap-monitor.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stream = open(log_path, "a", buffering=1, encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def main() -> None:
    _ensure_streams()
    import uvicorn

    from app.config import API_HOST, API_PORT

    uvicorn.run("app.main:app", host=API_HOST, port=API_PORT)


if __name__ == "__main__":
    main()
