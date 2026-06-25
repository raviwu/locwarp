from pathlib import Path
from typing import TypedDict

# Paths
DATA_DIR = Path.home() / ".locwarp"
# NOTE: DATA_DIR is created at RUNTIME in the FastAPI lifespan (main.py),
# not here — config.py must remain import-pure (no filesystem side effects).
SETTINGS_FILE = DATA_DIR / "settings.json"
_DEFAULT_BOOKMARKS_FILE = DATA_DIR / "bookmarks.json"


def get_bookmarks_path() -> Path:
    """Return the configured bookmarks file path.

    Resolution order:
      1. ``sync_folder`` from settings.json (new model) →
         ``<sync_folder>/bookmarks.json``
      2. ``bookmarks_path`` from settings.json (legacy, migration window)
      3. ``DATA_DIR / "bookmarks.json"``
    """
    import config as _cfg
    from services.json_safe import safe_load_json
    data = safe_load_json(_cfg.SETTINGS_FILE)
    if isinstance(data, dict):
        sync_folder = data.get("sync_folder")
        if isinstance(sync_folder, str) and sync_folder:
            p = Path(sync_folder)
            if p.exists():
                return p / "bookmarks.json"
        override = data.get("bookmarks_path")
        if isinstance(override, str) and override:
            p = Path(override)
            if p.parent.exists():
                return p
    return _cfg.DATA_DIR / "bookmarks.json"


def get_routes_path() -> Path:
    """Return the configured routes file path.

    Reads ``sync_folder`` from settings.json — falls back to legacy
    ``bookmarks_path``'s parent during the migration window so routes
    co-locate with bookmarks before AppState migrates the setting.
    Falls back to ``DATA_DIR / "routes.json"`` when no sync folder is
    configured or the configured folder is unreachable.
    """
    import config as _cfg
    from services.json_safe import safe_load_json
    data = safe_load_json(_cfg.SETTINGS_FILE)
    if isinstance(data, dict):
        sync_folder = data.get("sync_folder")
        if isinstance(sync_folder, str) and sync_folder:
            p = Path(sync_folder)
            if p.exists():
                return p / "routes.json"
        legacy = data.get("bookmarks_path")
        if isinstance(legacy, str) and legacy:
            parent = Path(legacy).parent
            if parent.exists():
                return parent / "routes.json"
    return _cfg.DATA_DIR / "routes.json"


# Backwards-compat alias for code that imports the constant. Kept so
# unrelated modules (e.g. tests that already patch BOOKMARKS_FILE) keep
# working until they are migrated to get_bookmarks_path().
BOOKMARKS_FILE = _DEFAULT_BOOKMARKS_FILE
ROUTES_FILE = DATA_DIR / "routes.json"
RECENT_PLACES_FILE = DATA_DIR / "recent_places.json"
# Persisted UDID → DeviceName cache. Populated whenever USB / usbmuxd
# exposes the user's actual DeviceName (e.g. "My iPhone") so a later
# WiFi-only session — where peer_info only carries DeviceClass ("iPhone")
# — can still display the user's chosen name.
DEVICE_NAMES_FILE = DATA_DIR / "device_names.json"

# Persisted Bonjour-instance → { udid, name } map. Populated after every
# successful WiFi tunnel pair-and-connect so the next /wifi/tunnel/discover
# can label the picker with the user's DeviceName instead of an opaque
# RemotePairing identifier or an IPv6 link-local address.
WIFI_ALIASES_FILE = DATA_DIR / "wifi_aliases.json"

# Persisted set of udids the user has explicitly refused to pair with
# ("Don't Trust" on the iPhone, or the in-app Forget action). The usbmux
# watchdog skips these so it never re-pops the Trust dialog uninvited;
# the in-app Re-trust button (wifi/repair) clears the entry.
# Shape: JSON list of udid strings.
STICKY_DENIED_FILE = DATA_DIR / "sticky_denied.json"

# In-process rotating local backup of the live bookmark + route stores.
# A lifespan-owned task snapshots every BACKUP_INTERVAL_S, archiving a
# timestamped copy only on data change and pruning past BACKUP_RETENTION_HOURS.
# Kept LOCAL under ~/.locwarp (never the iCloud sync_folder) so backups are
# not themselves re-synced/clobbered. The dir is mkdir'd at runtime in the
# lifespan (config stays import-pure). Reference config.BACKUP_DIR lazily —
# never `from config import BACKUP_DIR` — so the test isolation guard works.
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_INTERVAL_S = 300          # 5 minutes
BACKUP_RETENTION_HOURS = 72      # 3 days

# OSRM
OSRM_BASE_URL = "https://router.project-osrm.org"

# Routing engines the user can pick from in the UI. 'osrm' = the original
# demo server (kept as default for backwards compat). 'osrm_fossgis' is
# the same OSRM software hosted by FOSSGIS at a different URL with split
# /routed-{car|foot|bike} prefixes per profile. 'valhalla' is a different
# routing engine entirely (POST JSON, polyline6 geometry).
ROUTE_ENGINE_OSRM = "osrm"
ROUTE_ENGINE_OSRM_FOSSGIS = "osrm_fossgis"
ROUTE_ENGINE_VALHALLA = "valhalla"
ROUTE_ENGINE_BROUTER = "brouter"
ROUTE_ENGINES_ALLOWED = (
    ROUTE_ENGINE_OSRM,
    ROUTE_ENGINE_OSRM_FOSSGIS,
    ROUTE_ENGINE_VALHALLA,
    ROUTE_ENGINE_BROUTER,
)
DEFAULT_ROUTE_ENGINE = ROUTE_ENGINE_OSRM
OSRM_FOSSGIS_BASE_URL = "https://routing.openstreetmap.de"
VALHALLA_BASE_URL = "https://valhalla1.openstreetmap.de"
BROUTER_BASE_URL = "https://brouter.de"

# Nominatim
NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org"
NOMINATIM_USER_AGENT = "LocWarp/0.1"


class SpeedProfile(TypedDict):
    """Runtime speed profile consumed by the simulation engine."""
    speed_mps: float        # metres per second
    jitter: float           # ± jitter added to each tick for realism (metres)
    update_interval: float  # tick period (seconds)
    speed_jitter: float     # ± fraction of speed_mps applied per tick (0 = off)


# Speed profiles (m/s). Defaults align with the frontend ControlPanel
# preset chips (10.8 / 19.8 / 60 km/h). v0.2.84 lifted these from the
# v0.1.0 numbers (1.4 / 2.8 / 11.1) which dated from when "running" still
# meant actual running; the i18n label was later renamed to 腳踏車 and
# the chip value bumped to bike speed without touching the backend.
SPEED_PROFILES: dict[str, SpeedProfile] = {
    "walking": {"speed_mps": 3.0, "jitter": 0.5, "update_interval": 1.0, "speed_jitter": 0.12},
    "running": {"speed_mps": 5.5, "jitter": 0.7, "update_interval": 0.5, "speed_jitter": 0.12},
    "driving": {"speed_mps": 16.7, "jitter": 1.2, "update_interval": 0.5, "speed_jitter": 0.12},
}


def make_speed_profile(speed_kmh: float) -> SpeedProfile:
    """Build a speed profile dict from a km/h value."""
    speed_mps = speed_kmh / 3.6
    jitter = min(speed_mps * 0.2, 1.5)
    update_interval = 0.5 if speed_mps > 5 else 1.0
    return {"speed_mps": speed_mps, "jitter": jitter, "update_interval": update_interval, "speed_jitter": 0.12}


def resolve_speed_profile(
    profile_name: str,
    speed_kmh: float | None = None,
    speed_min_kmh: float | None = None,
    speed_max_kmh: float | None = None,
    jitter_enabled: bool = True,
) -> SpeedProfile:
    """Return a speed profile, picking a random km/h from the range if provided.
    Precedence: range > fixed custom > mode default. When jitter_enabled is
    False, the returned profile's speed_jitter is forced to 0.0 (a COPY — the
    shared SPEED_PROFILES table is never mutated) for byte-reproducible runs."""
    import random
    if speed_min_kmh is not None and speed_max_kmh is not None:
        lo, hi = sorted((float(speed_min_kmh), float(speed_max_kmh)))
        if lo <= 0:
            lo = 0.1
        profile = make_speed_profile(random.uniform(lo, hi))
    elif speed_kmh:
        profile = make_speed_profile(speed_kmh)
    else:
        profile = dict(SPEED_PROFILES[profile_name])  # copy so we never mutate the table
    if not jitter_enabled:
        profile = dict(profile)
        profile["speed_jitter"] = 0.0
    return profile  # type: ignore[return-value]


# Cooldown table: (max_distance_km, cooldown_seconds)
COOLDOWN_TABLE = [
    (1, 0),
    (5, 30),
    (10, 120),
    (25, 300),
    (100, 900),
    (250, 1500),
    (500, 2700),
    (750, 3600),
    (1000, 5400),
    (float("inf"), 7200),
]

# Default location (Taipei City Hall)
DEFAULT_LOCATION = {"lat": 25.0375, "lng": 121.5637}

# Server — API_HOST must stay 0.0.0.0 (LAN bind). phone.html is served to a
# real phone over WiFi; narrowing to 127.0.0.1 would silently break it.
# LAN exposure is closed by the phone-control PIN/token gate (api/phone_control.py)
# and the CORS allowlist (CORS_ORIGINS below), not by loopback bind.
API_HOST = "0.0.0.0"
API_PORT = 8777

# CORS — explicit allowlist: Electron/loopback UI, Vite dev server, optional LAN origin.
# phone.html is served same-origin from :8777 over LAN, so the LAN host:port must be
# covered. Set LOCWARP_LAN_ORIGIN=http://<LAN-IP>:8777 to add it at runtime (in main.py).
CORS_ORIGINS: list[str] = [
    # Backend-origin entries derive from API_PORT — the single source of the
    # backend port (no stray 8777 literal here). The 5173 entries are the Vite
    # dev server (a separate concern).
    f"http://127.0.0.1:{API_PORT}",
    f"http://localhost:{API_PORT}",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]

# CSP — "dev" allows Vite HMR + unsafe-inline for dev convenience; "strict"
# drops unsafe-inline for scripts (requires externalized JS, see boot-splash.ts).
# Set LOCWARP_CSP_MODE=strict in the packaged/production build.
# The runtime env read happens in main.py; this is the fallback default.
DEFAULT_CSP_MODE: str = "dev"
