from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import (
    export,
    health,
    measurements,
    monitoring,
    roam_events,
    settings,
    statistics,
    status,
    targets,
)
from app.api import (
    walk_tests as walk_tests_api,
)
from app.api import (
    wifi as wifi_api,
)
from app.config import DEV_CORS_ORIGINS, FRONTEND_DIST_DIR
from app.database.connection import close_db, init_db
from app.database.targets_repo import seed_default_targets
from app.monitoring.scheduler import manager
from app.services import walk_test_service
from app.services.notification_service import notifier_available

logging.basicConfig(
    level=os.environ.get("AP_MONITOR_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("ap_monitor")

# Set AP_MONITOR_AUTOSTART=0 to boot the API without immediately
# spawning monitoring loops - used by the test suite and by `--no-autostart`.
AUTOSTART = os.environ.get("AP_MONITOR_AUTOSTART", "1") != "0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = await init_db()
    await seed_default_targets(conn)
    if not notifier_available():
        logger.info(
            "No desktop notification tool found - notifications will be logged only"
        )
    if AUTOSTART:
        await manager.start(conn)
    yield
    await manager.stop()
    # A walk-test session is independent of MonitoringManager's own
    # start/stop (e.g. calling POST /api/monitoring/stop must not kill an
    # in-progress recording), but it still owns background tasks that must
    # not outlive the database connection they're using - clean those up
    # specifically at full app shutdown, not as part of manager.stop().
    await walk_test_service.cancel_all()
    await close_db()


app = FastAPI(title="AP Monitor", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    health.router,
    status.router,
    targets.router,
    measurements.router,
    statistics.router,
    settings.router,
    monitoring.router,
    export.router,
    wifi_api.router,
    walk_tests_api.router,
    roam_events.router,
):
    app.include_router(router)


def safe_static_file(root: Path, requested: str) -> Path | None:
    """The file under `root` that `requested` names, or None. Resolves the
    path first so `..` segments (raw or percent-encoded) cannot climb out of
    the built-frontend directory and read arbitrary files."""
    if not requested:
        return None
    root = root.resolve()
    candidate = (root / requested).resolve()
    if candidate.is_file() and candidate.is_relative_to(root):
        return candidate
    return None


if FRONTEND_DIST_DIR.is_dir():
    assets_dir = FRONTEND_DIST_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        candidate = safe_static_file(FRONTEND_DIST_DIR, full_path)
        if candidate is not None:
            return FileResponse(candidate)
        # Any other path is a client-side route (/roaming, /walk-test/3, ...):
        # hand the single-page app its entry point so deep links and refreshes work.
        return FileResponse(FRONTEND_DIST_DIR / "index.html")
else:

    @app.get("/", include_in_schema=False)
    async def frontend_not_built():
        return {
            "message": "Frontend build not found. Run the frontend build (see README) or use the API directly.",
            "api_docs": "/docs",
        }
