"""create_app() — FastAPI factory with ordered lifespan and security middleware.

Produces an app equivalent to main.app with:
  - Container on app.state.container
  - CORS allowlist from config.CORS_ORIGINS
  - CSP middleware (strict/dev/phone) from config.CSP_MODE
  - All routers mounted in the same order as main.py

Lifespan ordering: ensure_dirs FIRST → load_state → watchdog LAST.

main.py's own lifespan blocks (darwin tunnel-helper handshake, detailed
shutdown) remain in place as the process entry. create_app() is used by
tests and the future cutover; the full lifespan port is a dedicated follow-up.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from bootstrap.container import Container


# ── CORS ──────────────────────────────────────────────────────────────────────
# Mirrored from config.CORS_ORIGINS (with optional LOCWARP_LAN_ORIGIN).
# We import the list rather than re-declaring it so both apps stay in sync.
def _build_cors_origins() -> list[str]:
    from config import CORS_ORIGINS
    return list(CORS_ORIGINS)


# ── CSP constants (verbatim from main.py:970-1002) ────────────────────────────

_CSP_STRICT = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "object-src 'none'; base-uri 'self'"
)
_CSP_DEV = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' http://localhost:5173 http://127.0.0.1:5173; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "connect-src 'self' ws://localhost:5173 ws://127.0.0.1:5173 http://localhost:5173 http://127.0.0.1:5173; "
    "object-src 'none'; base-uri 'self'"
)

# Route-specific CSP for the /phone LAN page served to a real phone over WiFi.
_CSP_PHONE = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://unpkg.com; "
    "img-src 'self' data: blob: https://*.tile.openstreetmap.org https://*.tile.osm.org; "
    "connect-src 'self'; "
    "object-src 'none'; base-uri 'self'"
)

# Paths that get the phone-specific CSP (exact path match).
_PHONE_CSP_PATHS = frozenset({"/phone"})


class _CspMiddleware(BaseHTTPMiddleware):
    """CSP middleware — reads config.CSP_MODE at dispatch time so monkeypatching
    the config module affects responses (same semantics as main.py)."""

    async def dispatch(self, request: Request, call_next):
        import config as _cfg
        response = await call_next(request)
        if request.url.path in _PHONE_CSP_PATHS:
            policy = _CSP_PHONE
        elif _cfg.CSP_MODE == "strict":
            policy = _CSP_STRICT
        else:
            policy = _CSP_DEV
        response.headers["Content-Security-Policy"] = policy
        return response


# ── Router imports ─────────────────────────────────────────────────────────────

def _mount_routers(app: FastAPI) -> None:
    """Mount all API routers in the same order as main.py:1019-1039."""
    from api.device import router as device_router
    from api.location import router as location_router
    from api.route import router as route_router
    from api.geocode import router as geocode_router
    from api.system import router as system_router
    from api.bookmarks import router as bookmarks_router
    from api.recent import router as recent_router
    from api.websocket import router as ws_router
    from api.phone_control import router as phone_router
    from api.cloud_sync import router as cloud_sync_router

    app.include_router(device_router)
    app.include_router(location_router)
    app.include_router(route_router)
    app.include_router(geocode_router)
    app.include_router(system_router)
    app.include_router(bookmarks_router)
    app.include_router(recent_router)
    app.include_router(ws_router)
    app.include_router(phone_router)
    app.include_router(cloud_sync_router)


# ── create_app ─────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """Build and return a fully configured FastAPI application.

    Lifespan ordering:
      1. ensure_dirs FIRST (DATA_DIR exists before anything writes)
      2. load_state (bookmark/route managers, settings)
      3. watchdog LAST (starts after state is ready)

    The darwin tunnel-helper handshake and detailed shutdown sequence remain
    in main.py's own lifespan — porting those blocks is deferred (high risk,
    dedicated follow-up). main.py keeps running its own app as the process
    entry so nothing that imports main.app breaks.
    """
    container = Container()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 1. Ensure DATA_DIR exists before any write.
        from config import DATA_DIR
        DATA_DIR.mkdir(exist_ok=True)

        # 2. Wire: load persisted state (bookmark/route managers, settings).
        from main import app_state
        await app_state.load_state()

        # 3. Watchdog LAST: start after state is fully loaded.
        from main import _usbmux_presence_watchdog
        watchdog_task = asyncio.create_task(_usbmux_presence_watchdog())
        try:
            yield
        finally:
            watchdog_task.cancel()
            try:
                await watchdog_task
            except Exception:
                pass

    app = FastAPI(
        title="LocWarp",
        version="0.1.0",
        description="iOS Virtual Location Simulator",
        lifespan=lifespan,
    )
    app.state.container = container

    # CORS — use the shared allowlist from config (same as main.app).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_build_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # CSP — behavior-identical to main.py's @app.middleware("http") block.
    app.add_middleware(_CspMiddleware)

    _mount_routers(app)

    return app
