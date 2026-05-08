# Pull Gold Ditto (拉金盆) Mode — Design

**Date:** 2026-05-08
**Status:** Approved (pending implementation plan)
**Author:** Ravi Wu
**Type:** Feature design

---

## 1. Background

In Pokémon GO, "拉金盆" (pulling Gold Ditto / shiny Ditto from a flower spot) is a
manual technique that exploits the in-game flower-pulling animation. Players who
spoof their location need to perform a precise three-step manual sequence on
each pull attempt:

1. Tap the location-bookmark button to teleport to a random Taiwan point (call it A — the gold ditto / flower spot)
2. Wait roughly 3 seconds (the exact tuning varies per user, ~2.5–3.5s)
3. Tap "一鍵還原" (restore) so the device returns to the real GPS reading at B (the user's physical location)

If the pull fails (no transformation in ~10 seconds), the player retries by
teleporting back into the flower coordinate and repeating wait + restore.

The current LocWarp UI requires manually pressing teleport, mentally counting
seconds, then pressing restore. Users want a single mode with two coordinate
inputs and dedicated buttons that automate the wait, so they can concentrate
on the in-game flower-pulling.

## 2. Goals

- Provide a dedicated mode tab "拉金盆" with two coordinate inputs (A, B) and a
  shared wait-seconds value
- One verification button (just teleport) and two cycle buttons (1st try, retries)
- Cycle = `teleport → asyncio.sleep(N) → restore`, executed atomically on the
  backend so the wait timing is precise
- Fan out to all connected devices (consistent with existing modes)
- Persist A, B, and wait-seconds via `localStorage`

## 3. Non-Goals

- Auto-looping cycles (continuous unattended pulls)
- A cancel / abort key during the short cycle
- Detection of in-game state (the flower-pulling screen is opaque to LocWarp)
- Success / failure telemetry
- Auto-switch to another mode after a cycle

## 4. Requirements

### 4.1 Inputs

| Field | Type | Default | Notes |
|---|---|---|---|
| A (gold ditto / flower spot) | `lat,lng` string | empty | User selects via map click or paste |
| B (real GPS / physical location) | `lat,lng` string | `25.034897, 121.545827` (Taipei) | "🎲 隨機台灣點" button regenerates B |
| wait_seconds | float | `3.0` | Range `0.5`–`10.0`, decimals allowed |

### 4.2 Buttons

| Button | Action |
|---|---|
| ① **Confirm Location** | `teleport → A` only (no wait, no restore) |
| ② **1st try** | `teleport → B → asyncio.sleep(N) → restore` |
| ③ **retries** | Backend picks target dynamically:<br>- Distance(`engine.current_position`, A) < distance(..., B) → teleport to B<br>- Else → teleport to A<br>- `current_position` is None → default to A<br>Then `wait → restore` |

The "retries" alternation reflects the fact that after each successful cycle
the device's tracked virtual position equals the previous teleport target.
This gives the user A↔B alternation for free without explicit state.

### 4.3 UX

- Mode tab "拉金盆" added to the existing Mode panel beside Teleport / Navigate / Loop / MultiStop / RandomWalk / Joystick
- During an in-flight cycle: all three buttons disabled until the cycle resolves
- Status bar messaging:
  - On teleport phase: `拉金盆: 已瞬移到 A (lat, lng)`
  - On wait phase (live update): `拉金盆: 等待 X.Xs ⋯ 即將還原`
  - On restore phase: `拉金盆: 還原完成,可以開始拉花苞 ✨`
  - On failure: red toast with phase + reason
- Multi-device: 3 buttons fan out to every connected device. Toast aggregates
  successes / failures with UDIDs.

### 4.4 Validation

| Condition | Behavior |
|---|---|
| A missing or malformed | Confirm Location & 1st try disabled with tooltip |
| B missing or malformed | 1st try disabled (B is the teleport target) |
| Either missing | retries disabled |
| `wait_seconds` out of range | Frontend clamps + red border |
| Device disconnected | Whole panel disabled with notice |

### 4.5 Persistence

`localStorage` keys:

- `goldditto.A` — string `"lat,lng"` or null
- `goldditto.B` — string `"lat,lng"` or null
- `goldditto.wait_seconds` — number, default `3.0`

Read on app start with safe fallback to defaults; write on every input change.

## 5. Architecture

```
┌──────────────────────────────────────┐                ┌─────────────────────────┐
│ ControlPanel (new tab: GoldDitto)    │                │ FastAPI backend         │
│  ─ A: lat,lng                        │                │                         │
│  ─ B: lat,lng (default 25.0348..)    │                │ POST /api/location/     │
│  ─ wait_seconds (default 3.0)        │                │      goldditto/cycle    │
│  ─ [Confirm Location]   ──────────────► /teleport     │                         │
│  ─ [1st try]            ──────────────► /goldditto    │  ┌──────────────────┐  │
│  ─ [retries]            ──────────────► /goldditto    │  │ 1. teleport(A/B) │  │
│                                      │                │  │ 2. asyncio.sleep │  │
│  fanout: udids 各自打一次 cycle      │◄──── WS ───────┤  │ 3. restore()     │  │
│  toast / 狀態列                      │                │  │ 4. emit events   │  │
│  buttons disabled during cycle       │                │  └──────────────────┘  │
└──────────────────────────────────────┘                └─────────────────────────┘
```

## 6. Backend Design

### 6.1 New endpoint

```
POST /api/location/goldditto/cycle
Body:
  {
    "udid": str | null,
    "target": "A" | "B" | "auto",
    "lat_a": float, "lng_a": float,
    "lat_b": float, "lng_b": float,
    "wait_seconds": float
  }
Response 200:
  {
    "status": "completed",
    "target_used": "A" | "B",
    "lat": float, "lng": float,
    "duration_ms": int
  }
Response 4xx:
  {
    "status": "failed",
    "phase": "teleport" | "sleep" | "restore",
    "error": str
  }
```

### 6.2 New file: `backend/core/goldditto.py`

```python
class GoldDittoHandler:
    def __init__(self, engine):
        self.engine = engine

    async def cycle(self, target: str, a: Coord, b: Coord, wait_s: float) -> dict:
        chosen = self._pick(target, a, b)
        async with self.engine.lock:
            await self.engine.teleport_handler.teleport(chosen.lat, chosen.lng)
            await self.engine._emit("goldditto_cycle", {
                "phase": "teleported",
                "target": chosen.label,
                "lat": chosen.lat, "lng": chosen.lng,
            })
            await asyncio.sleep(wait_s)
            await self.engine.restore_handler.restore()
            await self.engine._emit("goldditto_cycle", {
                "phase": "restored",
                "target": chosen.label,
            })
        return {"target_used": chosen.label, "lat": chosen.lat, "lng": chosen.lng}

    def _pick(self, target, a, b):
        if target in ("A", "B"):
            return a if target == "A" else b
        # auto: closer to A → return B; closer to B → return A; None → A
        cur = self.engine.current_position
        if cur is None:
            return a
        dist_a = great_circle(cur, a)
        dist_b = great_circle(cur, b)
        return b if dist_a < dist_b else a
```

`engine.lock` (an `asyncio.Lock` already on the SimulationEngine, or to be added
if missing) prevents concurrent teleport / restore / loop / multistop from
interleaving with a cycle. If the lock is busy, the endpoint returns 409.

### 6.3 New schema

```python
class GoldDittoCycleRequest(BaseModel):
    udid: str | None = None
    target: Literal["A", "B", "auto"]
    lat_a: float = Field(..., ge=-90, le=90)
    lng_a: float = Field(..., ge=-180, le=180)
    lat_b: float = Field(..., ge=-90, le=90)
    lng_b: float = Field(..., ge=-180, le=180)
    wait_seconds: float = Field(..., ge=0.5, le=10.0)
```

### 6.4 Engine wiring

In `simulation_engine.py`:

```python
from core.goldditto import GoldDittoHandler
...
self.goldditto_handler = GoldDittoHandler(self)
```

In `api/location.py`, register the new route similarly to `/teleport`,
forwarding to the per-UDID engine resolver.

### 6.5 Cooldown

The cycle's internal teleport and restore must bypass the existing
distance-based cooldown so the N-second wait is not stretched by an inserted
delay. Pass an internal flag (e.g., `bypass_cooldown=True`) through the handler
methods, or call lower-level primitives directly.

## 7. Frontend Design

### 7.1 New SimMode value

`useSimulation.ts`:

```ts
export enum SimMode {
  Teleport = 'teleport',
  Navigate = 'navigate',
  Loop = 'loop',
  Joystick = 'joystick',
  MultiStop = 'multistop',
  RandomWalk = 'randomwalk',
  GoldDitto = 'goldditto',   // new
}
```

`ControlPanel.tsx`: add icon + label to `modeIcons` and `modeLabelKeys`. The
`Object.values(SimMode).map(...)` in the tab renderer already picks it up.

### 7.2 New panel section

When `simMode === SimMode.GoldDitto`, render the panel described in §4. Three
input fields (A, B, wait_seconds), helper buttons (🎲 隨機台灣點 → B, 📍 用目前
地圖中心 → B, map right-click → A), and the three action buttons.

### 7.3 Hook additions

Add to `useSimulation`:

```ts
async function goldDittoCycle(target: 'A' | 'B' | 'auto') {
  const udids = connectedUdids()
  setCycling(true)
  try {
    const results = await Promise.allSettled(
      udids.map(udid => api.goldDittoCycle({
        udid, target,
        lat_a, lng_a, lat_b, lng_b,
        wait_seconds,
      })),
    )
    showFanoutResults(results, udids, 'goldditto')
  } finally {
    setCycling(false)
  }
}
```

Three buttons share a single `cycling` boolean.

### 7.4 WebSocket consumption

Subscribe to `goldditto_cycle` events in the existing WS handler:

- `phase: "teleported"` → status-bar message "已瞬移到 X"
- `phase: "restored"` → status-bar message "還原完成,可以開始拉花苞"

A small interval timer (200ms) updates the wait-countdown text between the two
events for the active device.

### 7.5 Map integration

- Right-click menu on the map: add "設為拉金盆 A 點" entry
- Optional: render small A and B markers on the map when the GoldDitto tab is
  active, similar to how Multi-Stop renders waypoints

### 7.6 i18n

Add new keys to both zh-TW and en locales:
`mode.goldditto`, `goldditto.a_label`, `goldditto.b_label`, `goldditto.wait`,
`goldditto.confirm`, `goldditto.first_try`, `goldditto.retries`,
`goldditto.random_b`, `goldditto.toast.teleported`, `goldditto.toast.waiting`,
`goldditto.toast.restored`, `goldditto.toast.failed`.

## 8. Error Handling

| Scenario | Backend | Frontend |
|---|---|---|
| Device disconnected | 503 + `device not connected` | Panel disabled, "請先連接裝置" |
| Lock busy (cycle in flight) | 409 + `cycle in progress` | Should not happen (button disabled); ignore as race |
| Teleport phase fails | 4xx, no sleep, no restore | Red toast `拉金盆失敗: teleport - <reason>`, re-enable buttons |
| Sleep cancelled | finally-block tries restore, 200 with warning | Toast `cycle 中斷,已嘗試還原` |
| Restore fails (after teleport succeeded) | 4xx + warning | Red banner "已瞬移但還原失敗,請手動按一鍵還原" |
| Multi-device fanout partial fail | Each device independent | Toast `成功 N / 失敗 M: <udid> - <reason>` |
| A == B (degenerate) | Allow; auto picks A | Inline warning "A 跟 B 一樣,輪流會無效" |
| `wait_seconds` out of range | 422 (pydantic) | Frontend clamps before send |
| `target=auto` with no `current_position` | Default to A | No special handling |
| iOS unsupported | Same as existing teleport behavior | Existing handling |

## 9. Edge Cases

1. Tab opened with both fields empty: B prefilled, A empty, cycle buttons stay
   disabled until A is provided
2. User switches mode tab mid-cycle: cycle continues on backend (lock-protected),
   toasts still display; no state corruption
3. USB unplug mid-cycle: teleport / restore throws → failure path
4. Map right-click "設為拉金盆 A 點": uses the existing right-click menu's
   `useLayoutEffect` overflow guard
5. Random Taiwan B point: bounded box `24.0–25.5°N, 120.5–122.0°E`. No water /
   high-mountain check (just a placeholder)
6. localStorage parse failure (manual tampering / old format): silent fallback
   to defaults

## 10. Testing

| Layer | Tool | Scenarios |
|---|---|---|
| Backend unit | pytest + pytest-asyncio | `GoldDittoHandler.cycle` calls in correct order; `target=auto` distance math; lock rejects re-entry; teleport throw skips sleep + restore; sleep cancel still attempts restore |
| Backend API | FastAPI TestClient | endpoint signature; 422 validation; 503 device-not-connected; 409 cycle-in-progress |
| Frontend unit | (no harness yet, follow existing pattern) | skip |
| Manual E2E (real device) | one iPhone + LocWarp | (1) Confirm Location flies to A; (2) 1st try flies to B → wait 3s → restore (verify status bar order); (3) retries first call goes to A, second goes to B; (4) A == B does not deadlock; (5) USB unplug shows banner + disables buttons; (6) two iPhones fan out concurrently |
| Smoke | `LocWarp.bat` | Switch to 拉金盆 tab; press all three buttons; no console errors, no backend traceback |

## 11. Implementation Notes

- Reuse `engine.teleport_handler.teleport()` and `engine.restore_handler.restore()`;
  do not duplicate the underlying device calls
- The cycle handler is a thin orchestrator — no new SimulationState; cycle
  remains within the existing IDLE → TELEPORTING → IDLE flow
- The `goldditto_cycle` WS event is a new event type — backend `_emit()` already
  supports arbitrary event names; frontend WS handler needs the new case
- localStorage writes must be debounced or fire on `onChange` for stability —
  follow the same pattern used by the existing bookmarks / tunnel info storage
- Fanout failure messages should include UDIDs so the user can identify which
  device failed when controlling 2–3 devices

## 12. Open Questions

None at design approval time. Implementation may surface questions around:

- Whether `engine.lock` already exists or needs to be introduced
- Whether the existing teleport / restore paths support a `bypass_cooldown` flag
  or need a small refactor

These are mechanical and will be resolved during the implementation plan.
