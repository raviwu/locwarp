"""System utility endpoints — open files / folders for the user."""

import logging
import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from api.deps import get_device_manager, get_helper_client

router = APIRouter(prefix="/api/system", tags=["system"])

logger = logging.getLogger(__name__)


def _open_native(path: Path) -> None:
    """Open a file or folder with the OS default application.

    On Windows, when the calling process owns the foreground, a freshly
    spawned Explorer window opens *behind* it (Windows foreground lock).
    Call AllowSetForegroundWindow(ASFW_ANY) so the new Explorer process
    can claim foreground itself, then launch via Explorer directly so the
    window genuinely comes to front instead of just blinking in the
    taskbar.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            ASFW_ANY = -1
            ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
        except Exception:
            logger.debug("AllowSetForegroundWindow failed; explorer may open behind", exc_info=True)
        if path.is_dir():
            # explorer.exe with a folder path foregrounds the window reliably,
            # whereas os.startfile sometimes does not.
            subprocess.Popen(["explorer.exe", str(path)])
        else:
            os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


@router.post("/open-log")
async def open_log():
    """Open backend.log in the OS default text editor (Notepad on Windows)
    so the user can copy it for bug reports. Falls back to opening the
    log folder if the file is missing."""
    log_dir = Path.home() / ".locwarp" / "logs"
    log_file = log_dir / "backend.log"
    target = log_file if log_file.exists() else log_dir
    if not target.exists():
        log_dir.mkdir(parents=True, exist_ok=True)
        target = log_dir
    try:
        _open_native(target)
    except Exception as exc:
        logger.exception("Failed to open log path %s", target)
        raise HTTPException(status_code=500, detail={"code": "open_log_failed",
                                                     "message": f"無法開啟 log:{exc}"})
    return {"status": "opened", "path": str(target)}


@router.post("/open-log-folder")
async def open_log_folder():
    """Open the ~/.locwarp/logs folder in the file manager."""
    log_dir = Path.home() / ".locwarp" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        _open_native(log_dir)
    except Exception as exc:
        logger.exception("Failed to open log folder %s", log_dir)
        raise HTTPException(status_code=500, detail={"code": "open_log_failed",
                                                     "message": f"無法開啟資料夾:{exc}"})
    return {"status": "opened", "path": str(log_dir)}


@router.post("/shutdown")
async def shutdown():
    """Gracefully stop the backend process.

    Called by the Electron frontend on app quit so the user-level Electron
    process can terminate the root-elevated backend without needing sudo.
    """
    import signal
    logger.info("Shutdown requested via /api/system/shutdown")
    os.kill(os.getpid(), signal.SIGTERM)
    return {"status": "shutting_down"}


# Fixed inland probe coordinate for the offline-geo health check. Times Square,
# NYC — far from any ocean band so a healthy resolver always returns a real
# country/timezone. The value is irrelevant beyond "resolver returns non-empty".
_GEO_PROBE_LAT = 40.7580
_GEO_PROBE_LNG = -73.9855


def _resolve_version() -> str:
    """Backend version string for the info payload. Reads config.VERSION /
    config.APP_VERSION if present; falls back to '0.0.0' so /info never 500s
    on a missing constant."""
    import config
    for attr in ("VERSION", "APP_VERSION"):
        val = getattr(config, attr, None)
        if isinstance(val, str) and val:
            return val
    return "0.0.0"


@router.get("/info")
async def system_info(
    device_manager=Depends(get_device_manager),
    helper_client=Depends(get_helper_client),
):
    """Expose the otherwise restart-only health states so they are queryable
    live: tunnel-helper aliveness, per-device {ios, ddi_mounted}, and whether
    the offline geo resolver is functioning. Never 500s on a probe failure —
    each probe degrades to a falsy field.
    """
    # helper aliveness: derived (no stored handshake flag). If not connected,
    # skip ping entirely. If connected, a successful ping confirms aliveness.
    helper_alive = False
    try:
        if helper_client is not None and helper_client.is_connected:
            await helper_client.ping()
            helper_alive = True
    except Exception:
        logger.debug("helper ping failed during /info probe", exc_info=True)
        helper_alive = False

    # offline geo: request-time probe; resolve() never raises by contract, but
    # we still guard so a stubbed/broken resolver can never 500 the response.
    offline_geo_ok = False
    try:
        import services.geo_offline as geo_offline
        cc, tz, _city, _region = geo_offline.resolve(_GEO_PROBE_LAT, _GEO_PROBE_LNG)
        offline_geo_ok = bool(cc or tz)
    except Exception:
        logger.debug("offline geo probe failed during /info", exc_info=True)
        offline_geo_ok = False

    # per-device: read the live _connections map (each conn carries the stored
    # ddi_mounted flag set in _ensure_personalized_ddi_mounted).
    devices = []
    for udid, conn in dict(device_manager._connections).items():
        devices.append({
            "udid": udid,
            "ios": getattr(conn, "ios_version", "0.0"),
            "ddi_mounted": bool(getattr(conn, "ddi_mounted", False)),
            "connection_type": getattr(conn, "connection_type", "USB"),
        })

    return {
        "version": _resolve_version(),
        "helper_alive": helper_alive,
        "offline_geo_ok": offline_geo_ok,
        "devices": devices,
    }
