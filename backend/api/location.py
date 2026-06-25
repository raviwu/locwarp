from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.location_service import DeviceLostError
from core.goldditto import GoldDittoLockedError

from models.schemas import (
    MovementMode,
    TeleportRequest,
    NavigateRequest,
    LoopRequest,
    MultiStopRequest,
    RandomWalkRequest,
    JoystickStartRequest,
    SimulationStatus,
    Coordinate,
    CooldownSettings,
    CooldownStatus,
    CoordFormatRequest,
    CoordinateFormat,
    GoldDittoCycleRequest,
)
from api.deps import (
    get_engine_registry,
    _engine_registry_or_main,
)

router = APIRouter(prefix="/api/location", tags=["location"])


# NOTE (SH3 / A4): EngineResolver (services/engine_resolver.py) owns the
# resolve+recovery+device-lost-cleanup orchestration. The main.py usbmux
# watchdog (main.py: lost_now handling, ~lines 587-672) deliberately does
# NOT reuse EngineResolver.cleanup_device_lost: it broadcasts
# device_disconnected with reason="usb_unplugged" (not "device_lost") via
# broadcast(...) (not dm._events.publish), captures a leader resume
# snapshot, and promotes a follower via GroupSyncService. Those are a
# DIFFERENT observable WS contract; unifying them is out of scope for a
# behavior-preserving carve. This controller is the ONLY place a resolve/
# recovery domain error is mapped to an HTTPException.
async def _engine(udid: str | None = None, registry=None):
    """Resolve the active SimulationEngine via EngineResolver, mapping the
    domain EngineUnavailableError to the frozen 400 HTTPException."""
    from services.engine_resolver import EngineResolver
    from domain.errors import EngineUnavailableError
    app_state = _engine_registry_or_main(registry)
    resolver = EngineResolver(app_state, app_state.device_manager)
    try:
        return await resolver.resolve_engine(udid)
    except EngineUnavailableError as e:
        raise HTTPException(
            status_code=400,
            detail={"code": e.code, "message": e.message},
        )


async def _try_with_recovery_retry(udid: str | None, op, registry=None):
    from services.engine_resolver import EngineResolver
    app_state = _engine_registry_or_main(registry)
    resolver = EngineResolver(app_state, app_state.device_manager)
    return await resolver.with_recovery(udid, op)


async def _handle_device_lost(exc: Exception, udid: str, registry=None) -> "HTTPException":
    from services.engine_resolver import EngineResolver
    app_state = _engine_registry_or_main(registry)
    resolver = EngineResolver(app_state, app_state.device_manager)
    reason, message = await resolver.cleanup_device_lost(exc, udid)
    return HTTPException(
        status_code=503,
        detail={"code": "device_lost", "reason": reason, "message": message},
    )


def _cooldown(registry):
    return registry.cooldown_timer


def _coord_fmt(registry):
    return registry.coord_formatter


# ── Simulation modes ─────────────────────────────────────

class ApplySpeedRequest(BaseModel):
    mode: MovementMode = MovementMode.WALKING
    speed_kmh: float | None = None
    speed_min_kmh: float | None = None
    speed_max_kmh: float | None = None
    udid: str | None = None


@router.post("/apply-speed")
async def apply_speed(req: ApplySpeedRequest, registry=Depends(get_engine_registry)):
    """Hot-swap the active navigation's speed profile. The current
    _move_along_route loop re-interpolates from the current position
    with the new speed; already-completed progress is kept."""
    from config import resolve_speed_profile
    engine = await _engine(getattr(req, "udid", None) if 'req' in dir() else None, registry)
    profile = resolve_speed_profile(
        req.mode.value,
        speed_kmh=req.speed_kmh,
        speed_min_kmh=req.speed_min_kmh,
        speed_max_kmh=req.speed_max_kmh,
    )
    swapped = engine.apply_speed(profile)
    if not swapped:
        raise HTTPException(
            status_code=400,
            detail={"code": "no_active_route",
                    "message": "目前沒有進行中的路線,無法套用新速度"},
        )
    return {"status": "applied", "speed_mps": profile["speed_mps"]}


@router.post("/teleport")
async def teleport(req: TeleportRequest, registry=Depends(get_engine_registry)):
    engine = await _engine(getattr(req, "udid", None) if 'req' in dir() else None, registry)
    cooldown = _cooldown(registry)

    # Group mode (2+ engines): bypass cooldown entirely. The UI also locks the
    # toggle off, but the saved cooldown_enabled value is preserved so single-
    # device mode restores the user's preference automatically.
    dual_mode = len(registry.simulation_engines) >= 2

    # Enforce cooldown server-side: if enabled and currently active,
    # refuse the teleport so API clients cannot bypass the UI guard.
    if not dual_mode and cooldown.enabled and cooldown.is_active and cooldown.remaining > 0:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "cooldown_active",
                "message": f"冷卻中,還需等待 {int(cooldown.remaining)} 秒",
                "remaining_seconds": cooldown.remaining,
            },
        )

    old_pos = engine.current_position
    # Resolve which udid this action was targeting so device_lost cleanup
    # can be scoped to JUST that device in dual-device mode.
    action_udid = getattr(req, "udid", None) or registry.get_primary_udid()

    # The op closure re-resolves the engine each call: full_reconnect
    # rebuilds it, so a captured reference would point at the dead one.
    async def _do_teleport():
        eng = await _engine(action_udid, registry)
        await eng.teleport(req.lat, req.lng)

    try:
        await _try_with_recovery_retry(action_udid, _do_teleport, registry)
    except HTTPException:
        raise
    except DeviceLostError as e:
        raise (await _handle_device_lost(e, action_udid, registry))
    except Exception as e:
        import traceback, logging
        logging.getLogger("locwarp").error("Teleport failed:\n%s", traceback.format_exc())
        # Also inspect the cause — nested DeviceLostError (e.g. re-raised from
        # the simulation engine retry loop) should still trigger cleanup.
        cause = e
        while cause is not None:
            if isinstance(cause, DeviceLostError):
                raise (await _handle_device_lost(cause, action_udid, registry))
            cause = cause.__cause__
        raise HTTPException(status_code=500, detail=str(e))

    # Start cooldown if enabled and there was a previous position.
    # Skipped in dual mode for the same reason the check above is skipped.
    if old_pos and cooldown.enabled and not dual_mode:
        await cooldown.start(old_pos.lat, old_pos.lng, req.lat, req.lng)

    return {"status": "ok", "lat": req.lat, "lng": req.lng}


# Module-level background task set to keep strong references to fire-and-forget
# tasks. Without this, asyncio only keeps weak refs and Python can GC a task
# mid-execution (documented asyncio footgun). Tasks self-remove on completion.
_bg_tasks: set = set()


def _spawn(coro):
    import asyncio
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)

    def _on_done(t):
        _bg_tasks.discard(t)
        exc = t.exception()
        if exc is not None:
            import logging as _logging
            _logging.getLogger("locwarp").exception(
                "background task crashed: %s", exc, exc_info=exc
            )

    task.add_done_callback(_on_done)
    return task


@router.post("/navigate")
async def navigate(req: NavigateRequest, registry=Depends(get_engine_registry)):
    engine = await _engine(getattr(req, "udid", None) if 'req' in dir() else None, registry)
    _spawn(engine.navigate(
        Coordinate(lat=req.lat, lng=req.lng), req.mode,
        speed_kmh=req.speed_kmh,
        speed_min_kmh=req.speed_min_kmh, speed_max_kmh=req.speed_max_kmh,
        straight_line=req.straight_line,
        route_engine=req.route_engine,
    ))
    return {"status": "started", "destination": {"lat": req.lat, "lng": req.lng}, "mode": req.mode}


@router.post("/loop")
async def loop(req: LoopRequest, registry=Depends(get_engine_registry)):
    engine = await _engine(getattr(req, "udid", None) if 'req' in dir() else None, registry)
    _spawn(engine.start_loop(
        req.waypoints, req.mode,
        speed_kmh=req.speed_kmh,
        speed_min_kmh=req.speed_min_kmh, speed_max_kmh=req.speed_max_kmh,
        pause_enabled=req.pause_enabled, pause_min=req.pause_min, pause_max=req.pause_max,
        straight_line=req.straight_line,
        route_engine=req.route_engine,
        lap_count=req.lap_count,
        jump_mode=req.jump_mode, jump_interval=req.jump_interval,
        timestamps=req.timestamps,
    ))
    return {"status": "started", "waypoints": len(req.waypoints), "mode": req.mode}


@router.post("/multistop")
async def multi_stop(req: MultiStopRequest, registry=Depends(get_engine_registry)):
    engine = await _engine(getattr(req, "udid", None) if 'req' in dir() else None, registry)
    _spawn(engine.multi_stop(
        req.waypoints, req.mode, req.stop_duration, req.loop,
        speed_kmh=req.speed_kmh,
        speed_min_kmh=req.speed_min_kmh, speed_max_kmh=req.speed_max_kmh,
        pause_enabled=req.pause_enabled, pause_min=req.pause_min, pause_max=req.pause_max,
        straight_line=req.straight_line,
        route_engine=req.route_engine,
        jump_mode=req.jump_mode, jump_interval=req.jump_interval,
    ))
    return {"status": "started", "stops": len(req.waypoints), "mode": req.mode}


class InsertWaypointRequest(BaseModel):
    after_index: int
    lat: float
    lng: float
    udid: str | None = None


@router.post("/insert_waypoint")
async def insert_waypoint(req: InsertWaypointRequest, registry=Depends(get_engine_registry)):
    """Insert a new waypoint into the running multi-stop / loop route at
    after_index+1 without requiring the user to Stop+Start. See
    SimulationEngine.live_insert_waypoint for the splice / resume contract."""
    engine = await _engine(req.udid, registry)
    try:
        result = await engine.live_insert_waypoint(req.after_index, req.lat, req.lng)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result


@router.post("/randomwalk")
async def random_walk(req: RandomWalkRequest, registry=Depends(get_engine_registry)):
    engine = await _engine(getattr(req, "udid", None) if 'req' in dir() else None, registry)
    _spawn(engine.random_walk(
        req.center, req.radius_m, req.mode,
        speed_kmh=req.speed_kmh,
        speed_min_kmh=req.speed_min_kmh, speed_max_kmh=req.speed_max_kmh,
        pause_enabled=req.pause_enabled, pause_min=req.pause_min, pause_max=req.pause_max,
        seed=req.seed,
        straight_line=req.straight_line,
        route_engine=req.route_engine,
    ))
    return {"status": "started", "radius_m": req.radius_m, "mode": req.mode}


@router.post("/joystick/start")
async def joystick_start(req: JoystickStartRequest, registry=Depends(get_engine_registry)):
    engine = await _engine(getattr(req, "udid", None) if 'req' in dir() else None, registry)
    try:
        await engine.joystick_start(req.mode)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "started", "mode": req.mode}


@router.post("/joystick/stop")
async def joystick_stop(udid: str | None = None, registry=Depends(get_engine_registry)):
    engine = await _engine(udid, registry)
    await engine.joystick_stop()
    return {"status": "stopped"}


@router.post("/pause")
async def pause(udid: str | None = None, registry=Depends(get_engine_registry)):
    engine = await _engine(udid, registry)
    await engine.pause()
    return {"status": "paused"}


@router.post("/resume")
async def resume(udid: str | None = None, registry=Depends(get_engine_registry)):
    engine = await _engine(udid, registry)
    await engine.resume()
    return {"status": "resumed"}


@router.post("/restore")
async def restore(udid: str | None = None, registry=Depends(get_engine_registry)):
    # Resolve the engine first (may set _primary_udid via lazy rebuild),
    # THEN capture action_udid so cleanup_device_lost targets the actual
    # resolved device even when udid is None and _primary_udid was not set
    # at entry. Mirrors teleport's ordering.
    await _engine(udid, registry)
    action_udid = udid or registry.get_primary_udid()

    async def _do_restore():
        eng = await _engine(action_udid, registry)
        await eng.restore()

    try:
        await _try_with_recovery_retry(action_udid, _do_restore, registry)
    except DeviceLostError as e:
        raise (await _handle_device_lost(e, action_udid, registry))
    return {"status": "restored"}


@router.post("/goldditto/cycle")
async def goldditto_cycle(req: GoldDittoCycleRequest, registry=Depends(get_engine_registry)):
    """拉金盆 cycle: teleport → asyncio.sleep(wait) → restore, atomic."""
    engine = await _engine(req.udid, registry)
    try:
        result = await engine.goldditto_cycle(
            target=req.target,
            lat_a=req.lat_a, lng_a=req.lng_a,
            lat_b=req.lat_b, lng_b=req.lng_b,
            wait_seconds=req.wait_seconds,
        )
    except GoldDittoLockedError:
        raise HTTPException(
            status_code=409,
            detail={"code": "cycle_in_progress",
                    "message": "拉金盆 cycle already in progress, wait for it to finish"},
        )
    except DeviceLostError as e:
        action_udid = req.udid or registry.get_primary_udid()
        raise (await _handle_device_lost(e, action_udid, registry))
    except Exception as e:
        import logging, traceback
        logging.getLogger("locwarp").error("Gold Ditto cycle failed:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "completed", **result}


@router.post("/stop")
async def stop_movement(udid: str | None = None, registry=Depends(get_engine_registry)):
    """Stop active movement without clearing the simulated location.
    Keeps the device at its last reported position instead of restoring
    real GPS. restore() is a separate endpoint for that."""
    engine = await _engine(udid, registry)
    await engine.stop()
    return {"status": "stopped"}


@router.delete("/simulation")
async def stop_simulation(udid: str | None = None, registry=Depends(get_engine_registry)):
    """Legacy endpoint: stop + restore. Kept for backwards compatibility,
    prefer /stop (movement only) or /restore (clear location)."""
    engine = await _engine(udid, registry)
    await engine.restore()
    return {"status": "stopped"}


@router.get("/debug")
async def debug_info(registry=Depends(get_engine_registry)):
    """Debug endpoint to check engine and location service state."""
    engine = registry.simulation_engine
    if engine is None:
        return {"engine": None}
    loc_svc = engine.location_service
    return {
        "engine": type(engine).__name__,
        "state": engine.state.value if engine.state else None,
        "current_position": {"lat": engine.current_position.lat, "lng": engine.current_position.lng} if engine.current_position else None,
        "location_service": type(loc_svc).__name__ if loc_svc else None,
        "location_service_active": getattr(loc_svc, '_active', None),
    }


@router.get("/status", response_model=SimulationStatus)
async def get_status(udid: str | None = None, registry=Depends(get_engine_registry)):
    engine = await _engine(udid, registry)
    status = engine.get_status()
    cooldown = _cooldown(registry)
    cs = cooldown.get_status()
    status.cooldown_remaining = cs["remaining_seconds"]
    return status


# ── Cooldown ──────────────────────────────────────────────

@router.get("/cooldown/status", response_model=CooldownStatus, tags=["cooldown"])
async def cooldown_status(registry=Depends(get_engine_registry)):
    cd = _cooldown(registry)
    s = cd.get_status()
    return CooldownStatus(**s)


@router.put("/cooldown/settings", tags=["cooldown"])
async def cooldown_settings(req: CooldownSettings, registry=Depends(get_engine_registry)):
    cd = _cooldown(registry)
    cd.enabled = req.enabled
    if not req.enabled:
        await cd.dismiss()
    return {"enabled": cd.enabled}


@router.post("/cooldown/dismiss", tags=["cooldown"])
async def cooldown_dismiss(registry=Depends(get_engine_registry)):
    cd = _cooldown(registry)
    await cd.dismiss()
    return {"status": "dismissed"}


# ── Coordinate format ────────────────────────────────────

@router.get("/settings/coord-format", tags=["settings"])
async def get_coord_format(registry=Depends(get_engine_registry)):
    fmt = _coord_fmt(registry)
    return {"format": fmt.format.value}


@router.put("/settings/coord-format", tags=["settings"])
async def set_coord_format(req: CoordFormatRequest, registry=Depends(get_engine_registry)):
    fmt = _coord_fmt(registry)
    fmt.format = req.format
    return {"format": fmt.format.value}


# --- Initial map position (persisted in settings.json) ---

class _InitialPosRequest(BaseModel):
    lat: float | None = None
    lng: float | None = None


@router.get("/settings/initial-position", tags=["settings"])
async def get_initial_position(registry=Depends(get_engine_registry)):
    return {"position": registry.get_initial_map_position()}


@router.put("/settings/initial-position", tags=["settings"])
async def set_initial_position(req: _InitialPosRequest, registry=Depends(get_engine_registry)):
    """Pass `{lat: null, lng: null}` (or omit) to clear the custom initial
    map center and fall back to the default on next launch."""
    if req.lat is None or req.lng is None:
        registry.set_initial_map_position(None)
    else:
        if not (-90 <= req.lat <= 90) or not (-180 <= req.lng <= 180):
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_coord", "message": "lat must be in [-90, 90], lng in [-180, 180]"},
            )
        registry.set_initial_map_position({"lat": float(req.lat), "lng": float(req.lng)})
    return {"position": registry.get_initial_map_position()}
