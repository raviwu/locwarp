from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Coordinate(BaseModel):
    lat: float = Field(ge=-90.0, le=90.0, description="Latitude in degrees")
    lng: float = Field(ge=-180.0, le=180.0, description="Longitude in degrees")


class SimulationState(str, Enum):
    IDLE = "idle"
    TELEPORTING = "teleporting"
    NAVIGATING = "navigating"
    LOOPING = "looping"
    JOYSTICK = "joystick"
    RANDOM_WALK = "random_walk"
    MULTI_STOP = "multi_stop"
    PAUSED = "paused"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"


class MovementMode(str, Enum):
    WALKING = "walking"
    RUNNING = "running"
    DRIVING = "driving"


class CoordinateFormat(str, Enum):
    DD = "dd"
    DMS = "dms"
    DM = "dm"


# ── Device ───────────────────────────────────────────────
class DeviceInfo(BaseModel):
    udid: str
    name: str
    ios_version: str
    connection_type: str = "usb"
    is_connected: bool = False
    # iOS 16+ "Developer Mode" toggle state. None means we couldn't query
    # (not connected, iOS <16, or service call failed). Frontend uses this
    # to decide whether to show the "Reveal Developer Mode option" button.
    developer_mode_enabled: bool | None = None
    # Pair-handshake state. "ok" = lockdown query succeeded; "trust_required"
    # = device is muxed but iPhone has forgotten this host (re-trust needed);
    # "error" = some other failure (text in pair_error). Default keeps legacy
    # callers green — existing happy paths leave both fields untouched.
    pair_status: Literal["ok", "trust_required", "error"] = "ok"
    pair_error: str | None = None


# ── Location requests ────────────────────────────────────
class TeleportRequest(BaseModel):
    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)
    udid: str | None = None


class NavigateRequest(BaseModel):
    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)
    mode: MovementMode = MovementMode.WALKING
    speed_kmh: float | None = None
    speed_min_kmh: float | None = None
    speed_max_kmh: float | None = None
    straight_line: bool = False
    route_engine: str | None = None
    udid: str | None = None
    speed_jitter_enabled: bool = True


class LoopRequest(BaseModel):
    waypoints: list[Coordinate]
    mode: MovementMode = MovementMode.WALKING
    speed_kmh: float | None = None
    speed_min_kmh: float | None = None
    speed_max_kmh: float | None = None
    pause_enabled: bool = True
    pause_min: float = 5.0
    pause_max: float = 20.0
    straight_line: bool = False
    route_engine: str | None = None
    udid: str | None = None
    speed_jitter_enabled: bool = True
    # Number of laps to run before auto-stopping. None / 0 / negative means
    # infinite laps (current default behaviour, user stops manually).
    lap_count: int | None = None
    # Jump mode: teleport point-to-point with a fixed interval instead of
    # walking the routed path. Used for fruit-farm sniping where the user
    # wants the device to dwell at each waypoint, not interpolate between.
    jump_mode: bool = False
    jump_interval: float = 12.0
    # Per-waypoint seconds-from-start offsets, parallel to `waypoints`. When
    # present the engine's timed-replay branch is activated and the route plays
    # back at its original GPX cadence instead of at the profile speed.
    # Additive / backward-compatible: existing callers omit this field and the
    # engine falls through to the constant-speed path unchanged.
    timestamps: list[float] | None = None


class MultiStopRequest(BaseModel):
    waypoints: list[Coordinate]
    mode: MovementMode = MovementMode.WALKING
    stop_duration: int = 0
    loop: bool = False
    speed_kmh: float | None = None
    speed_min_kmh: float | None = None
    speed_max_kmh: float | None = None
    pause_enabled: bool = True
    pause_min: float = 5.0
    pause_max: float = 20.0
    straight_line: bool = False
    route_engine: str | None = None
    udid: str | None = None
    speed_jitter_enabled: bool = True
    # Jump mode: teleport point-to-point with a fixed interval instead of
    # walking the routed path. See LoopRequest.jump_mode for details.
    jump_mode: bool = False
    jump_interval: float = 12.0


class RandomWalkRequest(BaseModel):
    center: Coordinate
    radius_m: float = 500.0
    mode: MovementMode = MovementMode.WALKING
    speed_kmh: float | None = None
    speed_min_kmh: float | None = None
    speed_max_kmh: float | None = None
    pause_enabled: bool = True
    pause_min: float = 5.0
    pause_max: float = 20.0
    straight_line: bool = False
    route_engine: str | None = None
    udid: str | None = None
    speed_jitter_enabled: bool = True
    # Dual-device group mode: both devices pass the same seed so they pick
    # identical sequences of random destinations, keeping their paths synced.
    seed: int | None = None


class JoystickStartRequest(BaseModel):
    mode: MovementMode = MovementMode.WALKING
    speed_kmh: float | None = None
    udid: str | None = None


class JoystickInput(BaseModel):
    direction: float = Field(ge=0, le=360)
    intensity: float = Field(ge=0, le=1)


# ── Simulation status ────────────────────────────────────
class SimulationStatus(BaseModel):
    state: SimulationState = SimulationState.IDLE
    current_position: Coordinate | None = None
    destination: Coordinate | None = None
    progress: float = 0.0
    speed_mps: float = 0.0
    eta_seconds: float = 0.0
    eta_arrival: str = ""
    distance_remaining: float = 0.0
    distance_traveled: float = 0.0
    lap_count: int = 0
    segment_index: int = 0
    total_segments: int = 0
    cooldown_remaining: float = 0.0
    is_paused: bool = False


# ── Route ─────────────────────────────────────────────────
class RoutePlanRequest(BaseModel):
    start: Coordinate
    end: Coordinate
    profile: str = "foot"


class Tombstone(BaseModel):
    """Records that an item was deleted, so the deletion propagates across
    cloud-synced devices instead of being resurrected by a concurrent writer
    that still has the item. ``kind`` is "bookmark" | "category" | "route".
    """
    id: str
    kind: str
    deleted_at: str  # ISO 8601


class RouteCategory(BaseModel):
    id: str = ""
    name: str
    color: str = "#6c8cff"
    sort_order: int = 0
    created_at: str = ""
    # Bumped on every mutation so the cloud-sync merge can pick the newer
    # copy on an id collision. Empty = legacy (pre-sync-merge) record.
    updated_at: str = ""


class SavedRoute(BaseModel):
    id: str = ""
    name: str
    waypoints: list[Coordinate]
    profile: str = "walking"
    created_at: str = ""
    # Default keeps legacy routes.json files (which have no category_id field)
    # working with no migration step: pydantic populates "default" on load.
    category_id: str = "default"
    # Set whenever the route is replaced (PUT /saved/{id}) so the UI can
    # show a "last modified" timestamp distinct from created_at.
    updated_at: str = ""
    # Per-waypoint seconds-from-start, parallel to `waypoints`. Empty = a
    # timing-less route (replay at profile speed). Populated from GPX <time>
    # on import; honored by the engine's timing-aware interpolation. Additive
    # / backward-compatible: pre-existing routes.json files load with [].
    timestamps: list[float] = []


class RouteMoveRequest(BaseModel):
    route_ids: list[str]
    target_category_id: str


class RouteStore(BaseModel):
    categories: list[RouteCategory] = []
    routes: list[SavedRoute] = []
    # Deletions pending propagation to other cloud-synced devices.
    tombstones: list[Tombstone] = []


# ── Bookmarks ─────────────────────────────────────────────
class BookmarkCategory(BaseModel):
    id: str = ""
    name: str
    color: str = "#6c8cff"
    sort_order: int = 0
    created_at: str = ""
    # ISO 8601 date 'YYYY-MM-DD'. Empty string = unbounded on that side.
    # Both empty → evergreen (never archives). Validation lives in the
    # API layer (api/bookmarks.py::_validate_date_range).
    start_date: str = ""
    end_date: str = ""
    # Bumped on every mutation so the cloud-sync merge can pick the newer
    # copy on an id collision. Empty = legacy (pre-sync-merge) record.
    updated_at: str = ""


class Bookmark(BaseModel):
    id: str = ""
    name: str
    lat: float
    lng: float
    address: str = ""
    category_id: str = "default"
    created_at: str = ""
    last_used_at: str = ""
    # ISO 3166-1 alpha-2 (lowercase), populated at add time via reverse
    # geocode. Used to render a flag next to the bookmark. Empty = unknown
    # (legacy bookmarks or offline-added); UI simply skips the flag.
    country_code: str = ""
    # Offline-resolved geo metadata (timezonefinder + a bundled GeoNames
    # extract), populated by enrich_bookmark on create / GPS-edit / import
    # and by the startup reconciliation sweep. Empty = unresolved (an ocean
    # point, or a pre-feature record awaiting the next sweep) — the UI
    # simply skips whichever field is blank.
    timezone: str = ""   # IANA zone, e.g. 'Asia/Taipei'
    city: str = ""       # nearest notable city, ASCII name
    region: str = ""     # admin1 — province / state / county
    # Bumped on every mutation so the cloud-sync merge can pick the newer
    # copy on an id collision. Empty = legacy (pre-sync-merge) record.
    updated_at: str = ""


class BookmarkMoveRequest(BaseModel):
    bookmark_ids: list[str]
    target_category_id: str


class BookmarkStore(BaseModel):
    categories: list[BookmarkCategory] = []
    bookmarks: list[Bookmark] = []
    # Deletions pending propagation to other cloud-synced devices.
    tombstones: list[Tombstone] = []


# ── Cooldown ──────────────────────────────────────────────
class CooldownSettings(BaseModel):
    enabled: bool = True


class CooldownStatus(BaseModel):
    enabled: bool = True
    is_active: bool = False
    remaining_seconds: float = 0.0
    total_seconds: float = 0.0
    distance_km: float = 0.0


# ── Coord format ─────────────────────────────────────────
class CoordFormatRequest(BaseModel):
    format: CoordinateFormat


# ── Geocoding ─────────────────────────────────────────────
class GeocodingResult(BaseModel):
    display_name: str
    lat: float
    lng: float
    type: str = ""
    importance: float = 0.0
    country_code: str = ""  # ISO 3166-1 alpha-2 (lowercase), for flag lookup
    # Short, human-friendly name for UI (bookmark auto-name, POI label).
    # Picks the best available tag from Nominatim's address details.
    short_name: str = ""


class TimezoneInfo(BaseModel):
    zone: str  # IANA zone, e.g. 'Asia/Taipei'
    gmt_offset_seconds: int  # offset vs UTC in seconds (positive = east)
    abbreviation: str = ""  # e.g. 'CST', 'EDT'
    timestamp: int = 0  # unix timestamp at the zone's current wall time


class NearbyPoi(BaseModel):
    id: str
    name: str
    category: str  # 'amenity', 'shop', 'tourism', etc.
    subcategory: str  # 'restaurant', 'cafe', ...
    lat: float
    lng: float
    distance_m: float


class RouteOptimizeRequest(BaseModel):
    waypoints: list[Coordinate]
    profile: str = "foot"  # 'foot' or 'car'
    keep_first: bool = True  # first waypoint is the fixed start
    # Routing engine for the duration matrix used by the TSP solver.
    # The selected engine drives the simulation path between points;
    # for ordering we additionally cascade across matrix providers
    # (OSRM /table → Valhalla /sources_to_targets → haversine) since
    # BRouter has no matrix API of its own. used_estimate is only set
    # when every road-aware matrix is unavailable.
    engine: str = "osrm"


class RouteOptimizeResponse(BaseModel):
    waypoints: list[Coordinate]
    total_distance_m: float
    total_duration_s: float
    # True when the durations came from a straight-line haversine fallback
    # (OSRM /table unavailable or too many waypoints). Frontend uses this
    # to label the result as an estimate vs a road-distance optimum.
    used_estimate: bool = False


# ── Cloud sync ────────────────────────────────────────────
class CloudSyncResource(BaseModel):
    """Per-file resource info within the unified cloud-sync status."""
    path: str
    count: int = 0
    category_count: int = 0


class CloudSyncStatus(BaseModel):
    """Unified shape returned by /api/cloud-sync/*."""
    enabled: bool
    sync_folder: str | None = None
    detected_icloud_path: str | None = None
    prompt_dismissed: bool = False
    bookmarks: CloudSyncResource
    routes: CloudSyncResource


class CloudSyncEnableRequest(BaseModel):
    folder: str | None = None  # absolute path; None = use detected iCloud


# ── Pull-Gold-Ditto ───────────────────────────────────────
class GoldDittoCycleRequest(BaseModel):
    """Pull-Gold-Ditto cycle request.

    target=A → use (lat_a, lng_a)
    target=B → use (lat_b, lng_b)
    target=auto → backend picks farther-from-current point
    """
    udid: str | None = None
    target: Literal["A", "B", "auto"]
    lat_a: float = Field(..., ge=-90.0, le=90.0)
    lng_a: float = Field(..., ge=-180.0, le=180.0)
    lat_b: float = Field(..., ge=-90.0, le=90.0)
    lng_b: float = Field(..., ge=-180.0, le=180.0)
    wait_seconds: float = Field(..., ge=0.5, le=10.0)
