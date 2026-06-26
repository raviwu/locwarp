# Early branch: when run with --tunnel-helper, behave as the elevated
# tunnel helper and skip every backend import (uvicorn, FastAPI, and
# the pymobiledevice3 chain pulled in by core.device_manager) that the
# helper does not use. Keeps the elevated-helper memory footprint and
# attack surface small.
import sys

if "--tunnel-helper" in sys.argv:
    from tunnel_helper_main import run as _tunnel_helper_run

    raise SystemExit(_tunnel_helper_run())

import asyncio
import json
import logging
import os
from datetime import datetime
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from config import API_HOST, API_PORT, DATA_DIR, SETTINGS_FILE, DEFAULT_LOCATION, CORS_ORIGINS, DEFAULT_CSP_MODE
from core.device_manager import DeviceManager
from infra.device.wifi_tunnel import WifiTunnelRegistry
from infra.events.ws_event_publisher import WsEventPublisher
from services.cooldown import CooldownTimer
from services.bookmarks import BookmarkManager
from services.route_store import RouteManager
from services.coord_format import CoordinateFormatter
from services.tunnel_helper_client import TunnelHelperClient, HelperError
from services.geocoding import GeocodingService
from services.route_service import RouteService
from services.gpx_service import GpxService

# Early branch: when run with --self-check, import the whole fragile native
# chain (the PyInstaller metadata-gap history — pyimg4 / apple_compress /
# prompt_toolkit / h3) and exit non-zero on the first failure, then exit
# WITHOUT starting uvicorn. Unlike --tunnel-helper (which runs before any
# backend import to keep the elevated helper small), this branch runs AFTER
# the heavy imports above: reaching here proves `import core.device_manager`
# already pulled the chain in, and run_self_check re-imports it explicitly to
# surface any metadata gap with a precise label + a clean build-log exit code.
if "--self-check" in sys.argv:
    import self_check

    raise SystemExit(self_check.run_self_check())

# Configure logging — console + rotating file.
#
# Log directory resolution:
#   1. ``LOCWARP_LOG_DIR`` env var when set (explicit override for CI,
#      multi-instance dev, packaging tests).
#   2. Default ``~/.locwarp/logs/``.
#
# When running under pytest (``PYTEST_CURRENT_TEST`` set) and no override
# is configured, skip the file handler entirely so tests don't pollute
# the user's real backend log. Tests that explicitly want file logging
# can still opt in via ``LOCWARP_LOG_DIR``.
_log_fmt = "%(asctime)s [%(name)-26s] %(levelname)-8s %(message)s"
_log_override = os.environ.get("LOCWARP_LOG_DIR")
_under_pytest = "PYTEST_CURRENT_TEST" in os.environ or "PYTEST_VERSION" in os.environ
if _log_override:
    _log_dir = Path(_log_override)
    _want_file_handler = True
elif _under_pytest:
    _log_dir = None
    _want_file_handler = False
else:
    _log_dir = Path.home() / ".locwarp" / "logs"
    _want_file_handler = True

_handlers: list[logging.Handler] = [logging.StreamHandler()]
if _want_file_handler and _log_dir is not None:
    try:
        _log_dir.mkdir(parents=True, exist_ok=True)
        _file_handler = RotatingFileHandler(
            _log_dir / "backend.log",
            maxBytes=2 * 1024 * 1024,  # 2 MB
            backupCount=3,
            encoding="utf-8",
        )
        _file_handler.setFormatter(logging.Formatter(_log_fmt))
        _file_handler.setLevel(logging.INFO)
        _handlers.append(_file_handler)
    except Exception:
        pass
logging.basicConfig(level=logging.INFO, format=_log_fmt, handlers=_handlers, force=True)
logger = logging.getLogger("locwarp")


def _tunnel_restart_collaborators() -> dict:
    """Composition-root resolver for infra's attempt_tunnel_restart.

    Called lazily (per restart) by WifiTunnelRegistry so infra imports zero
    api/main modules. main.py is the ONLY ring allowed to import api + infra
    + main, so it owns this wiring. Reads the live globals at call time —
    ``app_state`` is assigned at module bottom, well after construction."""
    from api.websocket import broadcast
    from api.device import _per_tunnel_watchdog

    def _watchdog_factory(udid: str, runner):
        return asyncio.create_task(_per_tunnel_watchdog(udid, runner))

    return {
        "engine_registry": app_state,
        "device_manager": app_state.device_manager,
        "broadcast": broadcast,
        "auto_sync": _auto_sync_new_device_to_primary,
        "watchdog_factory": _watchdog_factory,
    }


class AppState:
    """Central application state — shared across API endpoints."""

    def __init__(self):
        from api.websocket import broadcast as _ws_broadcast
        self.device_manager = DeviceManager(
            event_publisher=WsEventPublisher(broadcast=_ws_broadcast),
            tunnel_registry=WifiTunnelRegistry(
                restart_collaborators=_tunnel_restart_collaborators
            ),
        )
        # Per-udid simulation engines (group mode, max 3). The legacy
        # `simulation_engine` attribute still returns the most-recently-
        # created engine for single-device call sites that have not yet
        # been refactored.
        self.simulation_engines: dict = {}
        self._primary_udid: str | None = None
        self.cooldown_timer = CooldownTimer()
        # Guards create_engine_for_device's check->await->assign and the
        # watchdog pop/promote so two concurrent connects for the same udid
        # cannot both pass the guard and clobber each other's engine.
        self._engines_lock = asyncio.Lock()
        # bookmark_manager / route_manager are constructed lazily in
        # load_state(), which runs INSIDE the FastAPI lifespan AFTER the
        # elevated helper has chowned any root-owned ~/.locwarp/ files
        # back to the user. Touching disk in __init__ raced the helper's
        # migration on first launch and prevented iCloud bookmark sync
        # from being adopted at startup.
        self.bookmark_manager: BookmarkManager | None = None
        self.route_manager: RouteManager | None = None
        # Rotating local backup. Built in load_state (after the managers exist
        # and the helper has chowned ~/.locwarp); driven by a lifespan task.
        self.backup_service = None
        self.coord_formatter = CoordinateFormatter()
        self._last_position = None
        # User-chosen initial map center (persisted between launches). When
        # None, the frontend falls back to a hardcoded default.
        self._initial_map_position: dict | None = None
        # Which bookmark category ids the user has expanded in the panel.
        # None = never set (first-time install); frontend applies the
        # "auto-collapse when total bookmarks > 30" rule. Empty list means
        # explicitly all-collapsed.
        self._bookmark_expanded_categories: list[str] | None = None
        # Which bookmark categories the user has temporarily hidden from the
        # panel. Per-device view preference — persisted in settings.json,
        # never iCloud-synced. None = never set.
        self._bookmark_hidden_categories: list[str] | None = None
        self._sync_folder: str | None = None
        self._cloud_sync_dismissed: bool = False
        # Load sync-related persisted state eagerly (no I/O risk; just reads
        # settings.json). The heavy manager construction is deferred to
        # load_state() which runs inside the FastAPI lifespan.
        self._load_persisted_state()
        # Do NOT construct BookmarkManager / RouteManager here. See load_state().

    async def load_state(self) -> None:
        """Load on-disk state. Must run after the helper has migrated
        any root-owned files back to the user. Idempotent — repeated
        calls rebuild the managers and re-read settings from disk."""
        self._reload_sync_folder()
        self._load_settings()
        from bootstrap.factories import make_bookmark_manager, make_route_manager
        self.bookmark_manager = make_bookmark_manager()
        # NOTE: the geo-enrichment reconciliation sweep (enrich_all) is NO
        # LONGER run here. The first resolve() inside enrich_all loads numpy +
        # timezonefinder + a 2.7MB cities5000.json (~530ms) — far too heavy to
        # sit on the awaited boot critical path. The lifespan defers it (see
        # _deferred_enrich): the heavy DATA LOAD is offloaded to a worker
        # thread (it touches NO store), then the store-MUTATING enrich_all
        # sweep runs back on the single-threaded event loop. Concurrency model:
        # the store + its CRUD ops are unlocked and event-loop-only, so the
        # sweep MUST stay on the loop (not a worker thread) to avoid racing a
        # concurrent add/delete — _store_lock guards only enrich_all's trailing
        # _save and does NOT serialize against the unlocked CRUD ops. enrich_all
        # is idempotent and its _save() fires the bookmarks_changed broadcast so
        # a late geo fill renders without a reload.
        self.route_manager = make_route_manager()

        # Rotating local backup: snapshots both managers' live state to
        # ~/.locwarp/backups on a 5-min cadence (the loop is started in the
        # lifespan). The provider reads each store consistently (bookmark under
        # its _store_lock) and is independent of where the live files reside.
        from bootstrap.factories import make_backup_service

        def _backup_provider():
            return (
                self.bookmark_manager.snapshot_export(),
                self.route_manager.snapshot_export(),
            )

        self.backup_service = make_backup_service(_backup_provider)

    def _reload_sync_folder(self) -> None:
        """Re-read sync_folder + cloud_sync_dismissed from settings.json.

        ``_load_persisted_state`` runs in ``__init__`` — which executes at
        module import time, BEFORE the elevated helper chowns root-owned
        ~/.locwarp/ files back to the user. If settings.json was root-owned
        (an older all-root build, or a prior ``sudo ./start.sh`` dev run),
        that early read fails silently and ``_sync_folder`` latches to None,
        so the cloud-sync toggle shows OFF for the whole session even though
        sync was enabled. ``load_state`` runs AFTER the chown, so re-reading
        here recovers the real value. ``_load_settings`` does not touch
        sync_folder, so this dedicated re-read is required."""
        from services.json_safe import safe_load_json
        data = safe_load_json(SETTINGS_FILE)
        if not isinstance(data, dict):
            return
        sf = data.get("sync_folder")
        if isinstance(sf, str) and sf:
            self._sync_folder = sf
        cdsm = data.get("cloud_sync_dismissed")
        if isinstance(cdsm, bool):
            self._cloud_sync_dismissed = cdsm

    def _load_settings(self):
        from services.json_safe import safe_load_json
        data = safe_load_json(SETTINGS_FILE)
        if not isinstance(data, dict):
            return
        try:
            pos = data.get("last_position")
            if pos:
                self._last_position = pos
            fmt = data.get("coord_format")
            if fmt:
                from models.schemas import CoordinateFormat
                self.coord_formatter.format = CoordinateFormat(fmt)
            imp = data.get("initial_map_position")
            if isinstance(imp, dict) and "lat" in imp and "lng" in imp:
                self._initial_map_position = {"lat": float(imp["lat"]), "lng": float(imp["lng"])}
            bmExp = data.get("bookmark_expanded_categories")
            if isinstance(bmExp, list):
                self._bookmark_expanded_categories = [str(x) for x in bmExp]
            bmHid = data.get("bookmark_hidden_categories")
            if isinstance(bmHid, list):
                self._bookmark_hidden_categories = [str(x) for x in bmHid]
        except (ValueError, KeyError):
            logger.warning("Settings payload field malformed; keeping defaults", exc_info=True)

    def _load_persisted_state(self) -> None:
        """Load sync-folder and cloud_sync_dismissed from settings.json.

        Also handles legacy migration: if the settings contain the old
        ``bookmarks_path`` key (pointing at an iCloud folder), upgrade it
        to ``sync_folder`` and pull the local routes.json into the same
        folder via ``migrate_pair``.

        Safe to call from ``__init__`` — only reads/writes settings.json and
        may move routes.json; does not construct managers or start watchers.
        """
        from services.json_safe import safe_load_json
        data = safe_load_json(SETTINGS_FILE)
        if not isinstance(data, dict):
            return

        sync_folder = data.get("sync_folder")
        if isinstance(sync_folder, str) and sync_folder:
            self._sync_folder = sync_folder

        cdsm = data.get("cloud_sync_dismissed")
        if isinstance(cdsm, bool):
            self._cloud_sync_dismissed = cdsm

        # Legacy migration: upgrade bookmarks_path → sync_folder, and
        # pull the local routes.json into the same folder.
        legacy = data.get("bookmarks_path")
        if (
            self._sync_folder is None
            and isinstance(legacy, str)
            and legacy
        ):
            candidate = Path(legacy).parent
            if candidate.exists():
                try:
                    from services.cloud_sync import migrate_pair
                    import config as _cfg
                    migrate_pair(_cfg.DATA_DIR, candidate)
                    self._sync_folder = str(candidate)
                    # Drop legacy key from on-disk settings.
                    data.pop("bookmarks_path", None)
                    data["sync_folder"] = str(candidate)
                    from services.json_safe import safe_write_json
                    safe_write_json(SETTINGS_FILE, data)
                    logger.info(
                        "AppState: migrated legacy bookmarks_path → "
                        "sync_folder=%s", candidate,
                    )
                except Exception:
                    logger.exception(
                        "AppState: legacy bookmarks_path migration failed; "
                        "keeping legacy setting"
                    )
            else:
                logger.warning(
                    "AppState: legacy bookmarks_path points at missing "
                    "folder %s; deferring migration until cloud drive is "
                    "available",
                    candidate,
                )

    def save_settings(self) -> None:
        from services.json_safe import safe_write_json
        payload = {
            "last_position": self._last_position,
            "coord_format": self.coord_formatter.format.value,
            "initial_map_position": self._initial_map_position,
            "bookmark_expanded_categories": self._bookmark_expanded_categories,
            "bookmark_hidden_categories": self._bookmark_hidden_categories,
            "sync_folder": self._sync_folder,
            "cloud_sync_dismissed": self._cloud_sync_dismissed,
        }
        safe_write_json(SETTINGS_FILE, payload)

    def get_primary_udid(self) -> str | None:
        return self._primary_udid

    def get_initial_map_position(self) -> dict | None:
        return self._initial_map_position

    def set_initial_map_position(self, pos: dict | None) -> None:
        self._initial_map_position = pos
        self.save_settings()

    def get_bookmark_ui_state(self) -> dict:
        return {
            "expanded_categories": self._bookmark_expanded_categories,
            "hidden_categories": self._bookmark_hidden_categories,
        }

    def set_bookmark_ui_state(self, *, expanded: list[str] | None = None,
                              hidden: list[str] | None = None) -> None:
        # Per-field: only touch a field whose value is not None, mirroring the
        # frontend's independent expand/hide persistence.
        if expanded is not None:
            self._bookmark_expanded_categories = list(expanded)
        if hidden is not None:
            self._bookmark_hidden_categories = list(hidden)
        self.save_settings()

    def get_initial_position(self) -> dict:
        if self._last_position:
            return self._last_position
        # Could try IP geolocation here; fallback to default
        return DEFAULT_LOCATION

    def update_last_position(self, lat: float, lng: float):
        self._last_position = {"lat": lat, "lng": lng}

    def restart_bookmark_watcher(self) -> None:
        """Stop and restart the bookmark file-watcher on the current manager.

        Call this after swapping bookmark_manager to a new instance so the
        watcher binds to the new path. The asyncio loop must already be
        running (i.e. called from within a FastAPI async handler) — the
        callback bridges onto it via run_coroutine_threadsafe.
        """
        import asyncio
        from api.websocket import broadcast as _bc

        self.bookmark_manager.stop_watcher()
        loop = asyncio.get_running_loop()

        def _on_change():
            asyncio.run_coroutine_threadsafe(
                _bc("bookmarks_changed", {"reason": "external_update"}), loop
            )

        self.bookmark_manager.start_watcher(_on_change)

    def restart_route_watcher(self) -> None:
        """Re-bind the route watcher to the current routes path.

        Call this after `_sync_folder` changes so the watcher binds to
        the new directory. Mirrors `restart_bookmark_watcher`.
        """
        import asyncio
        from api.websocket import broadcast as _bc

        self.route_manager.stop_watcher()
        loop = asyncio.get_running_loop()

        def _on_change():
            asyncio.run_coroutine_threadsafe(
                _bc("routes_changed", {"reason": "external_update"}), loop
            )

        self.route_manager.start_watcher(_on_change)

    @property
    def simulation_engine(self):
        """Legacy accessor: the most-recently-created engine.
        Prefer get_engine(udid) in new code."""
        if self._primary_udid and self._primary_udid in self.simulation_engines:
            return self.simulation_engines[self._primary_udid]
        return None

    @simulation_engine.setter
    def simulation_engine(self, value):
        """Legacy setter. ONLY `= None` (clear all) is supported. Engines are
        created via create_engine_for_device(udid) and removed via
        remove_engine(udid); there is no per-udid-less assignment path."""
        if value is not None:
            raise TypeError(
                "simulation_engine assignment is clear-only; use "
                "create_engine_for_device(udid) to register an engine"
            )
        self.simulation_engines.clear()
        self._primary_udid = None

    def get_engine(self, udid: str | None):
        """Return the engine for *udid*, or the primary engine if udid is None."""
        if udid is None:
            return self.simulation_engine
        return self.simulation_engines.get(udid)

    async def create_engine_for_device(self, udid: str, force: bool = False):
        """Create a SimulationEngine for the connected device.

        Idempotent: if an engine already exists for this udid, we
        reuse it instead of overwriting. The watchdog sometimes calls
        this every second (e.g. when list_devices()'s udid string
        doesn't byte-match our _connections key due to case / separator
        differences in certain pymobiledevice3 versions). Without this
        guard the re-created engine would wipe current_position back to
        None, so the user teleports successfully but any subsequent
        navigate / loop / multi-stop / random-walk raises "Cannot
        navigate: no current position" because the engine they're
        aiming at is a fresh one that never saw the teleport.

        _engines_lock serializes the check→await→assign so two concurrent
        calls for the same udid cannot both pass the guard.

        When ``force=True`` an existing engine for the udid is dropped
        **inside the lock** before rebuild — replaces the unlocked
        pop()-then-create() two-step at api callsites so a concurrent
        caller cannot race the registry mutation.
        """
        async with self._engines_lock:
            if udid in self.simulation_engines:
                if not force:
                    logger.debug("Simulation engine already exists for %s; preserving current_position", udid)
                    return
                # force: drop the stale engine INSIDE the lock before rebuild so
                # there is no unlocked pop->create window for a concurrent caller.
                self.simulation_engines.pop(udid, None)
            from core.simulation_engine import SimulationEngine
            from api.websocket import broadcast
            from infra.device.location_service_port import LocationServiceDevicePort

            loc_service = await self.device_manager.get_location_service(udid)

            async def event_callback(event_type: str, data: dict):
                # Always tag emissions with udid so the frontend can route per-device.
                if isinstance(data, dict) and "udid" not in data:
                    data = {**data, "udid": udid}
                await broadcast(event_type, data)
                if event_type == "position_update" and "lat" in data:
                    self.update_last_position(data["lat"], data["lng"])

            engine = SimulationEngine(
                loc_service, event_callback,
                device_port=LocationServiceDevicePort(loc_service),
            )
            self.simulation_engines[udid] = engine
            # Keep the existing primary on additional device connects. If no
            # primary is set (e.g. fresh install, first device), this udid
            # becomes primary. Second device plugging in no longer hijacks
            # the map view away from the first device.
            if self._primary_udid is None:
                self._primary_udid = udid

            # DO NOT push any initial location to the device on connect. The
            # engine's current_position stays None until the user explicitly
            # teleports / navigates / picks a bookmark. iPhone's real GPS is
            # left untouched by merely plugging the phone into LocWarp.
            #
            # The map UI still shows a default center (Taipei or the user's
            # `initial_map_position` setting) — that's purely a visual default
            # for the Leaflet view, not a virtual GPS coordinate.

            logger.info("Simulation engine created for device %s (no initial location pushed)", udid)

    async def remove_engine(self, udid: str) -> None:
        """Drop the engine for *udid* and promote a new primary if needed.

        Locked teardown counterpart of create_engine_for_device: acquires
        _engines_lock so a concurrent create_engine_for_device cannot race
        with the pop/promote. Promotes _primary_udid to the next remaining
        udid (or None) only when the removed udid was the primary. No-op for
        an unknown udid.
        """
        async with self._engines_lock:
            self.simulation_engines.pop(udid, None)
            if self._primary_udid == udid:
                self._primary_udid = next(iter(self.simulation_engines.keys()), None)


app_state = AppState()

# Shared elevated-helper client. Lifecycle is owned by the FastAPI
# lifespan below: connect during startup AFTER the helper has chowned
# our state files back to the user, shut down during teardown.
helper_client = TunnelHelperClient()


# ── Lifespan ─────────────────────────────────────────────

async def _auto_sync_new_device_to_primary(new_udid: str) -> None:
    """Delegate to GroupSyncService. Kept as a module-level name because the USB
    presence watchdog calls it directly."""
    from services.group_sync_service import GroupSyncService
    svc = GroupSyncService(engine_registry=app_state, device_manager=app_state.device_manager)
    await svc.auto_sync_new_device_to_primary(new_udid)


async def _usbmux_presence_watchdog():
    """Poll usbmuxd every 2 s for both directions:

    * **Disappearance** — a UDID present in DeviceManager._connections that
      drops off the usbmux list for 2 consecutive polls is treated as USB
      unplug: disconnect, clear simulation_engine, broadcast device_disconnected.
    * **Appearance** — a USB device showing up while we have no active
      connection triggers an auto-connect + engine rebuild, broadcasting
      device_connected when it succeeds. Failed attempts are throttled
      (min 5 s between retries per UDID) so we don't spam connect() while
      the device is still in the "Trust this computer?" dialog.

    WiFi (Network) devices are skipped on both sides — those are covered by
    the WiFi tunnel watchdog. Consecutive-miss debouncing protects against
    usbmuxd re-enumeration hiccups.
    """
    import asyncio
    import time
    from pymobiledevice3.usbmux import list_devices
    from api.websocket import broadcast

    miss_counts: dict[str, int] = {}
    miss_threshold = 3
    last_reconnect_attempt: dict[str, float] = {}
    # Per-udid consecutive failure count. Drives exponential backoff so a
    # device that consistently fails to connect (Trust pending, Windows
    # firewall blocking the RSD loopback, no admin rights, dead USB cable)
    # doesn't get hammered every 5 seconds for the rest of the session and
    # spam the log with hundreds of identical tracebacks. Reset on success
    # OR on disappearance (the user re-plugged after fixing whatever).
    reconnect_failure_count: dict[str, int] = {}
    reconnect_cooldown_base = 5.0  # seconds for first retry
    reconnect_cooldown_max = 300.0  # cap at 5 minutes per UDID

    while True:
        await asyncio.sleep(1.0)
        try:
            dm = app_state.device_manager
            # Build two views: the ORIGINAL-case serials (needed for
            # downstream look-ups into dm._connections /
            # app_state.simulation_engines that use whatever case was
            # originally stored) and a LOWERCASE set used only for the
            # present_usb - connected set difference. Some pymobiledevice3
            # versions return list_devices()'s serial in different casing
            # from what connect() stores, which previously made every
            # tick look like "new device detected" and triggered a
            # (pre-idempotency-fix) engine recreation that wiped the
            # user's teleported current_position.
            connected_original: dict[str, str] = {}  # lowercase → original
            for udid, conn in dm._connections.items():
                if getattr(conn, "connection_type", "USB") == "USB":
                    connected_original[udid.lower()] = udid
            connected = set(connected_original.keys())

            try:
                raw = await list_devices()
            except Exception:
                logger.debug("usbmux list_devices failed in watchdog", exc_info=True)
                continue
            present_usb_original: dict[str, str] = {}  # lowercase → original
            for r in raw:
                if getattr(r, "connection_type", "USB") == "USB":
                    present_usb_original[r.serial.lower()] = r.serial
            present_usb = set(present_usb_original.keys())

            # --- Disappearance detection ---
            # connected / present_usb are lowercase for set math; map
            # back to original-case when touching simulation_engines /
            # _connections so whichever case was stored in those maps
            # is what we use for look-ups.
            lost_now: list[str] = []
            for udid_lc in connected:
                if udid_lc in present_usb:
                    miss_counts.pop(udid_lc, None)
                else:
                    miss_counts[udid_lc] = miss_counts.get(udid_lc, 0) + 1
                    if miss_counts[udid_lc] >= miss_threshold:
                        lost_now.append(connected_original[udid_lc])

            if lost_now:
                logger.warning("usbmux watchdog: device(s) gone → %s", lost_now)
                # If the leader is among the lost devices, capture its
                # snapshot BEFORE we cancel its task so we can hand the
                # in-flight sim off to whichever follower we promote.
                leader_lost = app_state._primary_udid in lost_now
                handoff_snapshot: dict | None = None
                if leader_lost:
                    leader_eng = app_state.simulation_engines.get(app_state._primary_udid)
                    if leader_eng is not None:
                        try:
                            handoff_snapshot = leader_eng.capture_resumable_snapshot()
                            if handoff_snapshot:
                                logger.info(
                                    "watchdog: captured handoff snapshot from leader %s (kind=%s, segment=%d)",
                                    app_state._primary_udid,
                                    handoff_snapshot.get("kind"),
                                    handoff_snapshot.get("segment_index", 0),
                                )
                        except Exception:
                            logger.exception("watchdog: capture_resumable_snapshot failed")

                for udid in lost_now:
                    miss_counts.pop(udid, None)
                    # Signal any simulation in flight (random-walk / loop /
                    # multi-stop) to exit its inner loop cleanly. Without
                    # this, the handler would keep trying to push positions
                    # through the now-dead DVT channel, silently log fake
                    # 'arrived at destination' events, and leave a zombie
                    # task running against a stale engine reference.
                    old_eng = app_state.simulation_engines.get(udid)
                    if old_eng is not None:
                        try:
                            # Mark DISCONNECTED before cancelling the active
                            # task. Otherwise _run_handler's finally block sees
                            # a non-IDLE state and forces it to IDLE, emitting
                            # state_change=idle. In dual-device mode, if the
                            # primary is the one being unplugged, that idle
                            # event slips through the frontend filter (primary
                            # match) and wipes the global routePath / dest so
                            # the surviving device's polyline disappears.
                            from models.schemas import SimulationState as _SS
                            old_eng.state = _SS.DISCONNECTED
                            try:
                                await old_eng._emit("state_change", {"state": old_eng.state.value})
                            except Exception:
                                logger.debug("watchdog: disconnected state_change emit failed", exc_info=True)
                            old_eng._stop_event.set()
                            old_eng._pause_event.set()  # unstick anyone awaiting pause_event
                            active = getattr(old_eng, "_active_task", None)
                            if active is not None and not active.done():
                                active.cancel()
                        except Exception:
                            logger.debug("watchdog: failed to stop old engine %s", udid, exc_info=True)
                    try:
                        await dm.disconnect(udid)
                    except Exception:
                        logger.exception("watchdog: disconnect failed for %s", udid)
                    # Only remove the lost device's engine. The legacy setter
                    # `simulation_engine = None` wipes *all* engines, which
                    # destroys the surviving device's engine in dual mode.
                    # _engines_lock guards the pop+promote so a concurrent
                    # create_engine_for_device cannot race with cleanup.
                    async with app_state._engines_lock:
                        app_state.simulation_engines.pop(udid, None)
                        if app_state._primary_udid == udid:
                            remaining = next(iter(app_state.simulation_engines.keys()), None)
                            app_state._primary_udid = remaining

                # Promote: if the leader was among the lost AND there's
                # a successor still connected AND we captured a usable
                # snapshot, kick off resume_from_snapshot on the new
                # leader so the simulation continues seamlessly from the
                # exact segment / lap / walk-count the old leader had
                # reached. Other surviving devices then re-attach as
                # followers of the new leader (their old follower task,
                # if any, self-terminates on _primary_udid change).
                new_leader = app_state._primary_udid
                if leader_lost and new_leader and handoff_snapshot:
                    new_leader_eng = app_state.simulation_engines.get(new_leader)
                    if new_leader_eng is not None:
                        # The new leader was a follower of the old leader
                        # and was constantly being teleported by that
                        # follower task. _set_position never sets
                        # _stop_event, so we don't need to clear it
                        # before resume_from_snapshot — but we DO need to
                        # ensure the snapshot's teleport-to-current-pos
                        # is the last thing the old follower task can do
                        # before it sees the primary swap and exits.
                        logger.info(
                            "watchdog: promoting %s to leader, resuming sim from snapshot",
                            new_leader,
                        )
                        asyncio.create_task(new_leader_eng.resume_from_snapshot(handoff_snapshot))
                        # Re-attach any remaining devices (besides the
                        # new leader) as followers of the new leader.
                        from services.group_sync_service import GroupSyncService
                        _gs = GroupSyncService(
                            engine_registry=app_state,
                            device_manager=app_state.device_manager,
                        )
                        for other_udid in app_state.simulation_engines.keys():
                            if other_udid == new_leader:
                                continue
                            asyncio.create_task(
                                _gs._follow_primary_positions(other_udid, new_leader)
                            )

                try:
                    await broadcast("device_disconnected", {
                        "udids": lost_now,
                        "reason": "usb_unplugged",
                        # Remaining connected count AFTER cleanup. Frontend
                        # suppresses the full-screen banner when > 0 since
                        # the other device(s) are still usable; only the
                        # affected chip in the sidebar needs updating.
                        "remaining_count": len(dm._connections),
                    })
                except Exception:
                    logger.exception("watchdog: broadcast (disconnected) failed")
                continue  # skip appearance logic this tick

            # --- Appearance (auto-connect up to 3 devices, group mode) ---
            # Auto-connect any USB device not yet connected, up to the multi-
            # device cap. The user environment is assumed to only ever have
            # their own iPhones plugged in.
            MAX_DEVICES = 3
            new_udids_lc = present_usb - connected
            if not new_udids_lc or len(connected) >= MAX_DEVICES:
                continue
            # Map back to the original-case serials from list_devices so
            # downstream dm.connect() sees the format pymobiledevice3
            # itself expects.
            new_udids = [present_usb_original[lc] for lc in new_udids_lc]

            # Reset backoff for any UDID that just disappeared from usbmux —
            # the next time it shows up (re-plug) we want to try immediately,
            # not at the previous slot's accumulated cooldown.
            stale = [u for u in reconnect_failure_count if u not in present_usb_original]
            for u in stale:
                reconnect_failure_count.pop(u, None)
                last_reconnect_attempt.pop(u, None)

            now = time.monotonic()
            for udid in new_udids:
                # Stop trying to auto-connect a device the user has tapped "Don't Trust" on.
                # The user can break the spell by hitting the in-app Re-trust button,
                # which clears this set entry (see api/device.py wifi_repair handler).
                if udid in dm.sticky_user_denied:
                    continue
                if len(dm._connections) >= MAX_DEVICES:
                    break
                fail_count = reconnect_failure_count.get(udid, 0)
                # 5s, 10s, 20s, 40s, 80s, 160s, 300s, 300s ...
                cooldown = min(
                    reconnect_cooldown_base * (2 ** fail_count),
                    reconnect_cooldown_max,
                )
                last = last_reconnect_attempt.get(udid, 0.0)
                if now - last < cooldown:
                    continue
                last_reconnect_attempt[udid] = now
                logger.info(
                    "usbmux watchdog: new USB device %s detected, auto-connecting (fail_count=%d, cooldown=%.0fs)",
                    udid, fail_count, cooldown,
                )
                try:
                    await dm.connect(udid)
                    await app_state.create_engine_for_device(udid)
                    # Broadcast device_connected so the frontend chip row updates.
                    try:
                        devs = await dm.discover_devices()
                        info = next((d for d in devs if d.udid == udid), None)
                        await broadcast("device_connected", {
                            "udid": udid,
                            "name": info.name if info else "",
                            "ios_version": info.ios_version if info else "",
                            "connection_type": info.connection_type if info else "USB",
                        })
                    except Exception:
                        logger.exception("watchdog: broadcast (connected) failed")
                    logger.info("Auto-connect succeeded for %s", udid)
                    last_reconnect_attempt.pop(udid, None)
                    reconnect_failure_count.pop(udid, None)

                    # Auto-sync the new device to the primary device: if the
                    # primary has a virtual position set, teleport the new
                    # device there; if the primary is running a dynamic
                    # simulation (navigate / loop / multi_stop / random_walk),
                    # also replay that action on the new device so both move
                    # together. Dual-device group mode semantics: one marker,
                    # two phones in lockstep.
                    try:
                        await _auto_sync_new_device_to_primary(udid)
                    except Exception:
                        logger.exception("Auto-sync of new device %s to primary failed", udid)
                except Exception:
                    reconnect_failure_count[udid] = fail_count + 1
                    next_cooldown = min(
                        reconnect_cooldown_base * (2 ** (fail_count + 1)),
                        reconnect_cooldown_max,
                    )
                    # Drop full traceback after the first 3 failures so the
                    # log doesn't fill with identical stacks. Cause is always
                    # the same: Trust pending, no admin rights, or firewall
                    # blocking the RSD loopback handshake.
                    log_with_trace = fail_count < 3
                    logger.warning(
                        "Auto-connect for %s failed (attempt %d, will retry in %.0fs): likely Trust pending / no admin / firewall",
                        udid, fail_count + 1, next_cooldown,
                        exc_info=log_with_trace,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("usbmux watchdog iteration crashed; continuing")


async def _bookmark_backup_loop(service, *, interval_s, sleep=asyncio.sleep, now_provider=datetime.now):
    """Periodic rotating-backup tick. Ticks immediately for an instant baseline,
    then every interval_s. Mirrors _usbmux_presence_watchdog: re-raise
    CancelledError (clean shutdown) but swallow + log any other error so one bad
    tick never kills the loop."""
    while True:
        try:
            service.tick(now_provider())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("backup tick failed")
        await sleep(interval_s)


# Strong references to fire-and-forget startup tasks. asyncio only keeps weak
# refs, so without this set Python can GC a task mid-flight (documented
# footgun). Tasks self-remove on completion; exceptions are logged + swallowed
# so a deferred-startup failure never takes the server down. Mirrors
# api/location.py:_spawn / _bg_tasks.
_startup_bg_tasks: set = set()


def _spawn_bg(coro):
    task = asyncio.create_task(coro)
    _startup_bg_tasks.add(task)

    def _on_done(t):
        _startup_bg_tasks.discard(t)
        exc = t.exception()
        if exc is not None:
            logger.exception("startup background task crashed: %s", exc, exc_info=exc)

    task.add_done_callback(_on_done)
    return task


@asynccontextmanager
async def lifespan(application: FastAPI):
    import asyncio
    # ── Ensure data directory exists (moved here from config.py import time) ──
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # ── Helper handshake + state migration ──
    # The helper split applies ONLY to macOS packaged builds. The helper
    # runs as root and owns ~/.locwarp/ files left over from any previous
    # root-mode launch; on darwin we wait for it to publish READY, then
    # ask it to chown those files back to the regular user. ONLY THEN do
    # we construct BookmarkManager / RouteManager and load settings — the
    # iCloud bookmark adoption path inside BookmarkManager() needs to be
    # able to read and write the user's home directory.
    #
    # On non-darwin (Windows / Linux dev), no helper is spawned, so we
    # skip the handshake entirely. Otherwise the backend would block on
    # a status file that never appears and exit ~30s after launch.
    #
    # Per design §5.1, on darwin a failure here is fatal: if the user
    # cancelled the admin prompt or the helper crashed, the backend
    # cannot safely write to ~/.locwarp/ until ownership is reclaimed.
    # We exit the ASGI process so Electron sees the backend disappear
    # and can surface a clear "restart and grant admin" error rather
    # than leave the user with read-only-looking bookmarks and silent
    # EACCES on write.
    if sys.platform == "darwin":
        try:
            await helper_client.connect(timeout=90.0)
        except (TimeoutError, OSError, ConnectionError) as exc:
            logger.error("tunnel helper did not become ready: %s", exc)
            raise SystemExit(1)

        from core.wifi_tunnel import set_helper_client, set_in_use_predicate
        set_helper_client(helper_client)
        # Never let a WiFi-tunnel open tear down a healthy USB connection
        # (core/wifi_tunnel.open_tunnel_with_reconcile refuses the destructive
        # close+retry when this returns True). Transport-specific on purpose:
        # is_usb_connected, NOT is_connected — a WiFi device whose tunnel is being
        # auto-restarted is still connected (Network) and must keep self-healing.
        # Default is always-False until wired here, so the prior close+retry is
        # preserved if this line is ever absent.
        set_in_use_predicate(app_state.device_manager.is_usb_connected)

        try:
            result = await asyncio.wait_for(
                helper_client.migrate_user_state(
                    home=str(Path.home()),
                    uid=os.getuid(),
                    gid=os.getgid(),
                ),
                timeout=60.0,
            )
            logger.info(
                "helper migrate_user_state: chowned=%d skipped=%d failed=%d",
                result.get("chowned", -1),
                result.get("skipped", -1),
                result.get("failed", -1),
            )
        except HelperError as exc:
            # Helper rejected our identity (e.g. parent_uid mismatch). This
            # is a launcher bug, not a missing-helper. Fail loudly.
            logger.error(
                "helper migrate_user_state rejected (code=%d): %s",
                exc.code, exc.message,
            )
            raise SystemExit(2)
        except (TimeoutError, asyncio.TimeoutError) as exc:
            logger.error("helper migrate_user_state timed out: %s", exc)
            raise SystemExit(1)
    else:
        logger.info(
            "non-darwin platform (%s) — running without tunnel helper",
            sys.platform,
        )

    await app_state.load_state()

    # ── Deferred geo enrichment (Win 1) ──
    # Run the reconciliation sweep off the awaited critical path so uvicorn
    # serves immediately. The heavy ~530ms cost is the ONE-TIME geo-DATA LOAD
    # (numpy + timezonefinder + 2.7MB cities5000.json) triggered by the first
    # resolve(); that load populates the resolver's module-level cache and
    # touches NO store. So we offload ONLY that load to a worker thread, then
    # run the store-MUTATING enrich_all sweep (fast, cached resolves) back on
    # the single-threaded event loop.
    #
    # Why not to_thread(enrich_all): the BookmarkManager store + its CRUD ops
    # (create/delete/update_bookmark) are unlocked — they rely on the
    # single-threaded event-loop invariant. enrich_all iterates and mutates
    # store.bookmarks in place (the trailing _save takes _store_lock, but the
    # iteration does not, and _store_lock does NOT serialize against the
    # unlocked CRUD ops anyway). Running the sweep on a to_thread WORKER while
    # the app serves would race a concurrent add/delete (RuntimeError: list
    # changed size during iteration, or a torn read). Keeping the sweep on the
    # loop restores the single-threaded invariant → no race. The store is
    # already loaded (above) so bookmarks/routes exist the instant the server
    # is up; only the offline geo fields fill a beat later, broadcast via the
    # watcher's bookmarks_changed event (enrich_all's _save).
    if app_state.bookmark_manager is not None:
        manager = app_state.bookmark_manager

        async def _deferred_enrich() -> None:
            # Warm the offline resolver off the loop (the slow data load,
            # store-free), then sweep on the loop (single-threaded → safe).
            from services import geo_offline

            await asyncio.to_thread(geo_offline._ensure_loaded)
            manager.enrich_all()

        _spawn_bg(_deferred_enrich())

    # ── Startup ──
    logger.info("LocWarp starting — scanning for devices…")
    try:
        devices = await app_state.device_manager.discover_devices()
        if devices:
            target = devices[0]
            logger.info("Found device %s (%s), auto-connecting…", target.name, target.udid)
            await app_state.device_manager.connect(target.udid)
            await app_state.create_engine_for_device(target.udid)
            logger.info("Auto-connected to %s", target.udid)
        else:
            logger.info("No iOS devices found on startup")
    except Exception:
        logger.exception("Auto-connect on startup failed (device may need manual connect)")

    watchdog_task = asyncio.create_task(_usbmux_presence_watchdog())

    backup_task = None
    if app_state.backup_service is not None:
        backup_task = asyncio.create_task(
            _bookmark_backup_loop(app_state.backup_service, interval_s=config.BACKUP_INTERVAL_S)
        )

    # Start bookmark file watcher so external changes (iCloud sync from
    # another device) are picked up and broadcast to all WebSocket clients.
    loop = asyncio.get_running_loop()
    from api.websocket import broadcast as _bc

    def _on_bookmark_change():
        asyncio.run_coroutine_threadsafe(
            _bc("bookmarks_changed", {"reason": "external_update"}),
            loop,
        )

    app_state.bookmark_manager.start_watcher(_on_bookmark_change)

    def _on_route_change():
        asyncio.run_coroutine_threadsafe(
            _bc("routes_changed", {"reason": "external_update"}),
            loop,
        )

    app_state.route_manager.start_watcher(_on_route_change)

    yield

    # ── Shutdown ──
    # Mirror the start-side defensive checks: if load_state() failed mid-
    # construction (e.g. crash in BookmarkManager init), bookmark_manager
    # could be None and stop_watcher() would AttributeError. Guard each
    # teardown step so one failure doesn't prevent the rest from running.
    try:
        if app_state.bookmark_manager is not None:
            app_state.bookmark_manager.stop_watcher()
    except Exception:
        logger.exception("error stopping bookmark watcher")

    try:
        if app_state.route_manager is not None:
            app_state.route_manager.stop_watcher()
    except Exception:
        logger.exception("error stopping route watcher")

    # Stop the process-wide file_watcher Observer that backs bookmark +
    # route watchers, so its thread exits with the ASGI process.
    try:
        from services.file_watcher import shutdown as _watcher_shutdown
        _watcher_shutdown()
    except Exception:
        logger.exception("error stopping shared file watcher observer")

    watchdog_task.cancel()
    try:
        await watchdog_task
    except (asyncio.CancelledError, Exception):
        pass

    if backup_task is not None:
        backup_task.cancel()
        try:
            await backup_task
        except (asyncio.CancelledError, Exception):
            pass

    try:
        app_state.save_settings()
    except Exception:
        logger.exception("error saving settings on shutdown")
    try:
        await app_state.device_manager.disconnect_all()
    except Exception:
        logger.exception("error disconnecting devices")

    # Ask the helper to exit cleanly so it doesn't outlive the backend.
    # Only relevant on darwin packaged builds — elsewhere no helper was
    # spawned, so the client was never connected.
    if sys.platform == "darwin":
        try:
            await helper_client.shutdown()
        except Exception:
            logger.exception("helper shutdown call failed")
        await helper_client.close()

    logger.info("LocWarp shut down")


# ── FastAPI app ───────────────────────────────────────────

app = FastAPI(title="LocWarp", version="0.1.0", description="iOS Virtual Location Simulator", lifespan=lifespan)

# ── Composition root ──────────────────────────────────────
# Wire the thin Container onto the real app using app_state's singletons.
# KEY INVARIANT: one DeviceManager, one _engines_lock — shared by reference,
# never duplicated. api/deps.py resolves from request.app.state.container.
from bootstrap.container import Container as _Container
app.state.container = _Container(
    device_manager=app_state.device_manager,
    event_publisher=app_state.device_manager._events,
    tunnel_registry=app_state.device_manager._tunnels,
    engines_lock=app_state._engines_lock,
    engine_registry=app_state,
    cooldown_timer=app_state.cooldown_timer,
    coord_formatter=app_state.coord_formatter,
    helper_client=helper_client,
    geocoding_service=GeocodingService(),
    route_service=RouteService(),
    gpx_service=GpxService(),
    bookmark_manager=app_state.bookmark_manager,
    route_manager=app_state.route_manager,
)
from bootstrap.runtime import set_container as _set_container
_set_container(app.state.container)

# ── Runtime env reads (env belongs in main.py, not config.py) ──
_lan_origin = os.getenv("LOCWARP_LAN_ORIGIN", "").strip()
_cors_origins = [*CORS_ORIGINS, _lan_origin] if _lan_origin else CORS_ORIGINS
CSP_MODE = os.getenv("LOCWARP_CSP_MODE", DEFAULT_CSP_MODE)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── CSP middleware ────────────────────────────────────────

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

# Route-specific CSP for the /phone LAN page served to a real phone over
# WiFi. Leaflet JS+CSS come from unpkg.com; OSM tiles from
# *.tile.openstreetmap.org; the page has an inline <script> block. The
# default CSP (above) deliberately omits all of these — this policy is
# scoped ONLY to /phone so the main app's CSP stays strict.
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


@app.middleware("http")
async def _csp_middleware(request, call_next):
    response = await call_next(request)
    if request.url.path in _PHONE_CSP_PATHS:
        policy = _CSP_PHONE
    elif CSP_MODE == "strict":
        policy = _CSP_STRICT
    else:
        policy = _CSP_DEV
    response.headers["Content-Security-Policy"] = policy
    return response


# Register routers
from api.device import router as device_router
from api.location import router as location_router
from api.route import router as route_router
from api.geocode import router as geocode_router
from api.bookmarks import router as bookmarks_router
from api.recent import router as recent_router
from api.websocket import router as ws_router
from api.system import router as system_router
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


@app.get("/")
async def root():
    return {
        "name": "LocWarp",
        "version": "0.1.0",
        "status": "running",
        "initial_position": app_state.get_initial_position(),
    }



def _port_occupied(host: str, port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.connect((host, port))
            return True
        except (ConnectionRefusedError, OSError):
            return False


def _poll_until_free(host: str, port: int, timeout: float) -> bool:
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _port_occupied(host, port):
            return True
        time.sleep(0.25)
    return False


def _release_stale_backend(host: str, port: int) -> None:
    """If port is occupied, try API shutdown then lsof force-kill before giving up."""
    import signal, subprocess, urllib.request, urllib.error

    if not _port_occupied(host, port):
        return

    logger.warning("port %d already in use — attempting graceful shutdown of stale backend", port)
    try:
        urllib.request.urlopen(
            f"http://{host}:{port}/api/system/shutdown",
            data=b"",
            timeout=3,
        )
    except Exception:
        pass

    if _poll_until_free(host, port, timeout=4.0):
        logger.info("stale backend released port %d gracefully", port)
        return

    # Graceful shutdown didn't work — force-kill by port via lsof
    logger.warning("graceful shutdown timed out; force-killing process on port %d", port)
    try:
        pids = subprocess.check_output(
            ["lsof", "-ti", f"tcp:{port}"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).split()
        for pid_str in pids:
            try:
                os.kill(int(pid_str), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, ValueError):
                pass
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    if _poll_until_free(host, port, timeout=4.0):
        logger.info("force-killed stale backend on port %d", port)
        return

    logger.error(
        "port %d is still occupied after force-kill — another LocWarp instance may be running",
        port,
    )
    raise SystemExit(3)


# Force the stdlib asyncio event loop instead of uvloop. uvloop's datagram
# transport (libuv) BUSY-RETRIES a send that fails with ENOBUFS — e.g. an mDNS
# multicast to a torn-down WiFi-tunnel utun interface (via pymobiledevice3
# browse_remotepairing, behind GET /wifi/tunnel/discover) — pegging a core at
# 100% CPU and starving the whole event loop. stdlib asyncio drops such datagrams
# (error_received, no retry). See tests/test_event_loop_asyncio.py.
UVICORN_LOOP = "asyncio"


def _run_server() -> None:
    # Pass the app OBJECT, not the "main:app" import string. In a codesigned
    # PyInstaller bundle, uvicorn's import_module("main") fails ("Could not
    # import module 'main'") even though main.py already ran as __main__ — the
    # frozen entry module is not re-importable by name inside the signed .app.
    # Passing the object skips that re-import entirely (reload/workers are off).
    uvicorn.run(
        app,
        host=API_HOST,
        port=API_PORT,
        reload=False,
        access_log=True,
        loop=UVICORN_LOOP,
    )


if __name__ == "__main__":
    _release_stale_backend(API_HOST, API_PORT)

    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.setLevel(logging.INFO)
    uvicorn_access.propagate = True
    _run_server()
