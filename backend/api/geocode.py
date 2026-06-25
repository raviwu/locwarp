import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import APIRouter, Depends, HTTPException

from models.schemas import (
    Coordinate,
    GeocodingResult,
    NearbyPoi,
    RouteOptimizeRequest,
    RouteOptimizeResponse,
    TimezoneInfo,
)
from services import geo_offline
from api.deps import get_geocoding_service
from domain.errors import GeocodeError, NearbyPoiError
from services.geo_extras import (
    _HAVERSINE_PROFILE_SPEED_MPS,
    haversine_duration_matrix,
    nearby_pois_checked,
    optimize_order_exact,
    optimize_order_nearest_neighbor,
    osrm_table,
    valhalla_matrix,
)

router = APIRouter(prefix="/api/geocode", tags=["geocode"])
logger = logging.getLogger("locwarp")


@router.get("/search", response_model=list[GeocodingResult])
async def search_address(
    q: str,
    limit: int = 5,
    provider: str = "nominatim",
    google_key: str | None = None,
    geocoding_service=Depends(get_geocoding_service),
):
    """Forward geocode.

    `provider` is one of ``nominatim`` (default, free, no key) or
    ``google`` (requires `google_key`, 10k events/month free tier on
    Google's Essentials plan).
    """
    try:
        return await geocoding_service.search(q, limit, provider, google_key)
    except GeocodeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/reverse", response_model=GeocodingResult | None)
async def reverse_geocode(lat: float, lng: float, geocoding_service=Depends(get_geocoding_service)):
    """Reverse-geocode a coordinate. Tries Nominatim first; falls back
    to the offline city/region/country DB when Nominatim is unreachable,
    rate-limited, or returns an error. Returns ``None`` only when both
    layers have nothing.
    """
    try:
        result = await geocoding_service.reverse(lat, lng)
        if result is not None:
            return result
    except Exception:
        logger.exception("Nominatim reverse failed; falling back to offline")

    cc, _tz, city, region = geo_offline.resolve(lat, lng)
    parts: list[str] = []
    for p in [city, region, cc.upper() if cc else ""]:
        if p and (not parts or parts[-1].lower() != p.lower()):
            parts.append(p)
    if not parts:
        return None
    return GeocodingResult(
        display_name=", ".join(parts),
        lat=lat,
        lng=lng,
        country_code=cc.lower(),
        short_name=city or region or (cc.upper() if cc else ""),
    )


@router.get("/nearby", response_model=list[NearbyPoi])
async def nearby(lat: float, lng: float, radius_m: int = 200, limit: int = 40):
    """Named POIs near a coordinate via Overpass (4-mirror fallback).

    Thin controller over services.geo_extras.nearby_pois_checked. Out-of-range
    radius/limit → 400; an upstream Overpass outage degrades to an empty list
    (HTTP 200), never a 500. Imported at the call site so monkeypatching the
    geo_extras.nearby_pois_checked attribute in tests rebinds the lookup."""
    import services.geo_extras as _geo_extras
    try:
        return await _geo_extras.nearby_pois_checked(lat, lng, radius_m, limit)
    except NearbyPoiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/timezone", response_model=TimezoneInfo | None)
async def timezone_lookup(lat: float, lng: float):
    """IANA timezone + current UTC offset for a coordinate, resolved fully
    offline via timezonefinder (no external API key). Returns ``None`` when the
    offline tables are unavailable or the point has no resolvable zone.

    The same offline resolver already backs bookmark geo-info, so this drops
    the previous TimezoneDB online dependency entirely. The UTC offset is
    computed server-side from the IANA zone via the stdlib zoneinfo tz database.
    """
    _cc, zone, _city, _region = geo_offline.resolve(lat, lng)
    if not zone:
        return None
    try:
        now = datetime.now(ZoneInfo(zone))
        offset = now.utcoffset()
        return TimezoneInfo(
            zone=zone,
            gmt_offset_seconds=int(offset.total_seconds()) if offset else 0,
            abbreviation=now.tzname() or "",
            timestamp=int(now.timestamp()),
        )
    except (ZoneInfoNotFoundError, ValueError):
        # Zone resolved but the tz database lacks it (e.g. missing tzdata on a
        # stripped platform) — still return the zone so the frontend can derive
        # the offset itself via Intl.
        logger.info("timezone offset unavailable for zone %s; returning zone only", zone)
        return TimezoneInfo(zone=zone, gmt_offset_seconds=0, abbreviation="", timestamp=0)


@router.get("/real-location")
async def real_location():
    """Resolve the user's real public IP to city-level coordinates.

    Runs on the backend (not the Electron renderer) so we bypass CORS and
    TLS-cert issues that killed the renderer-direct version. Tries three
    free providers in sequence and returns the first one that gives us a
    valid lat/lng.

    Returns: {"lat": float, "lng": float, "city": str, "country": str}
    Raises 502 if every provider fails.
    """
    providers = [
        # (name, url, extractor)
        (
            "ipwho.is",
            "https://ipwho.is/?fields=success,latitude,longitude,city,region,country",
            lambda d: None
            if d.get("success") is False
            else (
                float(d["latitude"]),
                float(d["longitude"]),
                str(d.get("city") or d.get("region") or ""),
                str(d.get("country") or ""),
            )
            if d.get("latitude") is not None and d.get("longitude") is not None
            else None,
        ),
        (
            "ip-api.com",
            "http://ip-api.com/json/?fields=status,lat,lon,city,regionName,country",
            lambda d: (
                float(d["lat"]),
                float(d["lon"]),
                str(d.get("city") or d.get("regionName") or ""),
                str(d.get("country") or ""),
            )
            if d.get("status") == "success"
            else None,
        ),
        (
            "ipapi.co",
            "https://ipapi.co/json/",
            lambda d: (
                float(d["latitude"]),
                float(d["longitude"]),
                str(d.get("city") or d.get("region") or ""),
                str(d.get("country_name") or d.get("country") or ""),
            )
            if d.get("latitude") is not None and d.get("longitude") is not None
            else None,
        ),
    ]

    last_err: str = ""
    async with httpx.AsyncClient(timeout=httpx.Timeout(6.0, connect=3.0)) as client:
        for name, url, extract in providers:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                result = extract(data)
                if result is None:
                    last_err = f"{name} returned no location"
                    continue
                lat, lng, city, country = result
                logger.info("real-location resolved via %s: %.4f, %.4f (%s)", name, lat, lng, city)
                return {"lat": lat, "lng": lng, "city": city, "country": country}
            except Exception as exc:
                last_err = f"{name}: {exc}"
                logger.info("real-location provider %s failed: %s", name, exc)
                continue

    raise HTTPException(status_code=502, detail=f"All IP geolocation providers failed ({last_err})")


@router.post("/route-optimize", response_model=RouteOptimizeResponse)
async def route_optimize(req: RouteOptimizeRequest):
    """Reorder waypoints to minimize total travel time.

    Uses OSRM /table when feasible (<=100 waypoints AND the demo server
    responds). Otherwise falls back to a straight-line haversine duration
    matrix — accuracy trades road distance for crow-flight, which is fine
    for dense Pokemon-GO style loops where adjacent points are already
    close together. The endpoint always succeeds; no more 503.
    """
    if len(req.waypoints) < 2:
        raise HTTPException(status_code=400, detail="need >=2 waypoints")

    # Engine dispatch for the duration matrix used by the TSP solver.
    # The user-selected engine controls the *path* taken between points
    # at simulation time, but the matrix only affects ordering — so
    # when the chosen engine has no matrix API (BRouter), we silently
    # try OSRM /table → Valhalla /sources_to_targets → haversine. That
    # way picking BRouter still gives road-aware ordering instead of
    # forcing a "straight-line estimate" label on every optimize.
    engine = (req.engine or "osrm").lower()
    durations: list[list[float]] | None = None
    if engine == "valhalla":
        durations = await valhalla_matrix(req.waypoints, req.profile)
        if not durations:
            logger.info(
                "route_optimize: Valhalla matrix unavailable for %d waypoints, trying OSRM /table",
                len(req.waypoints),
            )
            durations = await osrm_table(req.waypoints, req.profile)
    elif engine == "brouter":
        # BRouter has no matrix endpoint, so reach for OSRM /table first
        # (closest in semantics to BRouter's road-aware costing) and
        # then Valhalla as a second fallback.
        logger.info(
            "route_optimize: BRouter has no matrix API; using OSRM /table for ordering of %d waypoints",
            len(req.waypoints),
        )
        durations = await osrm_table(req.waypoints, req.profile)
        if not durations:
            durations = await valhalla_matrix(req.waypoints, req.profile)
    else:  # osrm
        durations = await osrm_table(req.waypoints, req.profile)
        if not durations:
            logger.info(
                "route_optimize: OSRM /table unavailable, trying Valhalla matrix for %d waypoints",
                len(req.waypoints),
            )
            durations = await valhalla_matrix(req.waypoints, req.profile)

    used_estimate = False
    if not durations:
        durations = haversine_duration_matrix(req.waypoints, req.profile)
        used_estimate = True
        logger.info(
            "route_optimize: all matrix engines unavailable, using haversine fallback for %d waypoints (engine=%s)",
            len(req.waypoints), engine,
        )

    # Brute-force optimal up to 8 points, heuristic beyond. With the
    # haversine matrix the brute-force is still cheap (8! = 40320 perms).
    if len(req.waypoints) <= 8:
        order = optimize_order_exact(durations, req.keep_first)
    else:
        order = optimize_order_nearest_neighbor(durations, req.keep_first)

    reordered = [req.waypoints[i] for i in order]
    total_duration = 0.0
    for a, b in zip(order, order[1:]):
        d = durations[a][b] or 0.0
        total_duration += d

    # Reconstruct an estimated road distance from the duration matrix using
    # each engine's natural-walking baseline. The frontend re-derives ETA
    # from this distance using the user's actual sim speed (which is often
    # 3~10 km/h, very different from OSRM/Valhalla's 5 km/h built-in
    # pedestrian speed). Without this scaling step the optimizer toast
    # would advertise OSRM's wall-clock instead of the user's.
    baseline_speed = _HAVERSINE_PROFILE_SPEED_MPS.get(req.profile, 1.4)
    total_distance_m = total_duration * baseline_speed

    return RouteOptimizeResponse(
        waypoints=[Coordinate(lat=wp.lat, lng=wp.lng) for wp in reordered],
        total_distance_m=total_distance_m,
        total_duration_s=total_duration,
        used_estimate=used_estimate,
    )
