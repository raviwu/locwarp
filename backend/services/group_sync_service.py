"""Group-sync use-case: align a freshly-connected device to the primary.

Extracted verbatim from ``main._auto_sync_new_device_to_primary`` /
``main._follow_primary_positions``. The behaviour is unchanged — the only
substitution is the module-global ``app_state`` becoming the ctor-injected
``self._engines`` engine registry.

``device_manager`` is injected for forward-compat even though the current body
only reads the engine registry.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("locwarp")


class GroupSyncService:
    def __init__(self, *, engine_registry, device_manager):
        self._engines = engine_registry
        self._dm = device_manager

    async def auto_sync_new_device_to_primary(self, new_udid: str) -> None:
        """Align a freshly-connected second device to whatever the primary
        device is doing, so dual-device mode behaves as one unit without the
        user having to explicitly restart actions.

        Behaviour:
          * No primary yet, or primary is the same as *new_udid* → noop
          * Primary has a ``current_position`` → teleport new device there
          * Primary is running navigate / loop / multi_stop / random_walk →
            replay the same action (with the same args) on the new engine so
            both devices share the target / waypoints / seed
          * Primary is idle / paused / teleport-only → only the position
            sync happens; the user's next action will fan-out to both
        """
        primary_udid = self._engines._primary_udid
        if primary_udid is None or primary_udid == new_udid:
            return
        primary_eng = self._engines.simulation_engines.get(primary_udid)
        new_eng = self._engines.simulation_engines.get(new_udid)
        if primary_eng is None or new_eng is None:
            return

        pos = primary_eng.current_position
        if pos is None:
            # Primary hasn't been given a position yet — nothing to sync.
            logger.info("Auto-sync: primary %s has no position, skipping %s", primary_udid, new_udid)
            return

        # 1) Teleport the new device to match the primary's current virtual
        #    position (keeps the 'one marker' invariant in dual mode).
        try:
            await new_eng.teleport(pos.lat, pos.lng)
            logger.info("Auto-sync: %s teleported to primary %s position (%.6f, %.6f)",
                        new_udid, primary_udid, pos.lat, pos.lng)
        except Exception:
            logger.exception("Auto-sync: teleport failed for %s", new_udid)
            return

        # 2) If the primary is running a dynamic sim, attach the new device
        #    as a position-follower instead of replaying the sim from scratch.
        #    Why not replay: each sim mode restarts at its own "beginning"
        #      * loop:      _move_along_route emits coords[0] first → iPhone
        #                   teleports back to waypoint[0] before walking
        #      * multi_stop: routes from current pos back to waypoint[0]
        #                   first if >50m away → iPhone walks back to start
        #      * random_walk: rng resets at walk_count=0 → iPhone walks the
        #                   first random destination from scratch
        #    All three desync the rejoining iPhone from the surviving one and
        #    show up on Google Maps as the rejoining phone going back to the
        #    route's beginning. Following primary's positions instead keeps
        #    both iPhones perfectly in sync.
        from models.schemas import SimulationState
        dynamic = {
            SimulationState.NAVIGATING,
            SimulationState.LOOPING,
            SimulationState.MULTI_STOP,
            SimulationState.RANDOM_WALK,
        }
        if primary_eng.state not in dynamic:
            return

        logger.info("Auto-sync: attaching %s as position-follower of primary %s", new_udid, primary_udid)
        asyncio.create_task(self._follow_primary_positions(new_udid, primary_udid))

    async def _follow_primary_positions(self, follower_udid: str, primary_udid: str) -> None:
        """Mirror the primary engine's current_position onto the follower
        device. Runs until the primary changes, the follower disconnects,
        the follower starts its own simulation (which sets _stop_event via
        _ensure_stopped), or the primary engine is gone."""
        poll_interval = 0.5  # 500ms — primary's own updates run ~1 Hz, so this oversamples slightly without thrashing
        last_pushed_lat: float | None = None
        last_pushed_lng: float | None = None
        while True:
            # Tear down conditions
            if self._engines._primary_udid != primary_udid:
                logger.info("Follower %s: primary changed (%s → %s), stopping follow",
                            follower_udid, primary_udid, self._engines._primary_udid)
                return
            follower_eng = self._engines.simulation_engines.get(follower_udid)
            if follower_eng is None:
                logger.info("Follower %s: engine gone, stopping follow", follower_udid)
                return
            if follower_eng._stop_event.is_set():
                logger.info("Follower %s: stop_event set (own sim started or stop pressed), stopping follow",
                            follower_udid)
                return
            primary_eng = self._engines.simulation_engines.get(primary_udid)
            if primary_eng is None:
                logger.info("Follower %s: primary engine gone, stopping follow", follower_udid)
                return

            pos = primary_eng.current_position
            if pos is not None and (pos.lat != last_pushed_lat or pos.lng != last_pushed_lng):
                try:
                    await follower_eng._set_position(pos.lat, pos.lng)
                    last_pushed_lat, last_pushed_lng = pos.lat, pos.lng
                except Exception:
                    logger.debug("Follower %s: _set_position failed", follower_udid, exc_info=True)
            await asyncio.sleep(poll_interval)
