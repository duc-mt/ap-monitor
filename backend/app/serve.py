# -*- coding: utf-8 -*-
"""
==============================================================================
Module Name:   serve.py
Description:   Console-less service entry point for AP Monitor backend.
Author:        Mai Tan Duc <ducmai.network@gmail.com>
Created:       2026-10-10
Version:       1.0.0
License:       MIT
==============================================================================

Console-less entry point: `python -m app.serve` (or `pythonw -m app.serve`).
Provides logging redirect for Windows pythonw.exe execution.
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
