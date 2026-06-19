# LocWarp Clean-Arch MVP — Phase 1: Break the `core ↔ api` Cycle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Tasks are the trackable unit (`### Task N`); each task's steps are bold-headed and end in a commit. **Prerequisite: Phase 0 is complete and green** (the clock seam, the char nets / P0 WS recordings, and the Vitest harness are all assumed to exist).

**Goal:** Eliminate the only true import cycle — `api/device.py ⟷ core/device_manager.py` (six `core→api` function-body edges) — structurally, via three inner-owned ports (`DevicePort`, `EventPublisher`, `TunnelRegistry`) wired at a composition root, plus a typed multi-subscriber WS seam on the frontend. No external behavior change.

**Architecture:** Pragmatic Hexagonal-lite (spec: `docs/superpowers/specs/2026-06-19-clean-architecture-refactor-design.md`). Backend grows `domain/` (events + ports), `infra/` (adapters), `bootstrap/` (container + app factory); `device_manager` and the engine depend on ports, never on `api`. Frontend introduces `contract/` + `ports/WsRouter` + `adapters/ws/router` (preserving the existing multi-subscriber fan-out) behind a `ServicesContext`. Backend inversion and the frontend WsRouter are **separate, independently-revertable commits**.

**Tech Stack:** Backend FastAPI + pydantic **v2.12.5** + pytest (asyncio strict). Frontend React + TS + Vitest + (one) Playwright e2e.

## Global Constraints

- **Behavior/API freeze.** No external HTTP / WS / IPC change. WS payloads compared **deep-equal parsed-JSON** (not bytes), serialized `exclude_unset=True, exclude_none=True` so absent keys stay absent — golden-compared **per emission site** against the Phase-0 recordings.
- **Test baseline (corrected).** Treat the **pinned Phase-0 baseline (≈371 collected)** as the floor, not the literal "352" written in task bodies. Count never drops; grows only by new tests.
- **Hardware gate.** The cycle-inversion commits (Tasks 3, 4, 5) touch the live device/tunnel path and **cannot** be proven by pytest. Each ends with a **MANUAL SMOKE GATE** (real iPhone over USB + WiFi; Trust dialog; `_attempt_tunnel_restart`) that must pass before the task is "done". Automated tests gate the commit; the smoke gate gates "done".
- **New dependencies require explicit approval** (per `AGENTS.md`): frontend `@playwright/test` (Task 13). `import-linter` (introduced report-only in Phase 0) flips to **enforced** at this phase's exit.
- **Git identity** auto-set by includeIf — never pass `-c user.email=...`. Direct commits to `main`.

## Known scope deferrals (author-flagged, verified — confirm these are acceptable)

- **`main.py` is NOT shrunk to a ~10-line entrypoint.** `create_app()` owns the lifespan **ordering** (`ensure_dirs` → wire → watchdog-last) by delegating to the existing `load_state` / presence-watchdog; the darwin tunnel-helper connect/migrate, file-watcher, and detailed-shutdown blocks are **left in place** (a verbatim port is high-risk and deferred). The cycle still breaks; the composition root is partial by design.
- **`DeviceService.forget` is NOT lifted.** `forget`'s pair-lock-wrapping-`_tunnels_lock` ordering + SIP record-delete async/sync split are coupled to `api/device.py` helpers; only **connect/disconnect/repair** move to `services/device_service.py`. `forget` stays put (still works; just not yet behind the service).
- **`DevicePort.clear` is a documented no-op** — there is no `clear`/`reset` call site in the engine today (only `location_service.set`). YAGNI; no engine wiring.
- **`Container` does not yet absorb repos/geocoder** — `BookmarkManager`/`RouteManager` stay lazily built in `AppState.load_state()`; the geocoder stays in its router. Pulling them in is a larger refactor (Phase 2/4 territory), deferred.
- **`ALLOWED_ORIGINS` is a best-guess list** (`127.0.0.1`/`localhost` on `:8777`/`:5173`); confirm against the real phone-control LAN threat model before the CORS change is treated as final. (`phone.html` is served to a physical phone over the LAN — the bind must stay LAN-reachable.)
- **App.tsx subscriber correction (verified):** the brief's "two inline App.tsx `device_disconnected` subscribers" was **false** — App.tsx inline subs handle `bookmarks_changed`/`routes_changed` and `goldditto_cycle`; `device_disconnected` lives in the `useDevice`/`useSimulation` hooks. Task 12 migrates all four real subscriber sites. (The multi-subscriber fan-out requirement still holds: `device_*` is dual-handled in `useSimulation` AND `useDevice`.)

---
## Phase 1 (Backend) — Break the 6-edge `core ↔ api` cycle via three ports + a composition root

> **Read this first (zero-context primer).**
> LocWarp's backend is a FastAPI app under `/Users/raviwu/personal/locwarp/backend`.
> Today `backend/core/device_manager.py` imports `from api.device import …` and
> `from api.websocket import broadcast` (six function-body imports) — a cyclic
> dependency `core → api` that we are eliminating. We do it by introducing **narrow
> Protocol ports** under `backend/domain/ports/`, **concrete adapters** under
> `backend/infra/`, and a **composition root** under `backend/bootstrap/`. None of
> this is allowed to change external behavior: **all 352 backend pytest tests must
> stay green after EVERY commit**, and every WebSocket payload must be **deep-equal
> (parsed-JSON, not bytes)** identical to what ships today.
>
> **Tooling facts (verified):** pydantic is **v2.12.5** (so `BaseModel`,
> `ConfigDict`, `model_dump(exclude_unset=…, exclude_none=…)` all apply).
> pytest runs in `asyncio_mode = strict` (every async test needs
> `@pytest.mark.asyncio`) with `--basetemp=/tmp/lw-pytest` (from `backend/pytest.ini`).
> The documented runner is `cd backend && .venv/bin/python -m pytest <args>`; on a
> machine without that venv, substitute the project interpreter (`python3 -m pytest`)
> — the commands below use the documented `.venv/bin/python` form.
>
> **P0 golden recordings.** This phase assumes Phase 0 produced a JSON file of
> *recorded WS emissions per site* (the "P0 recordings"). Where a task says
> "deep-equal vs the P0 recording", compare the new emission's parsed dict against
> that fixture. If Phase 0's recording file path differs from
> `backend/tests/golden/ws_payloads.json` used below, adjust the path — the **shape**
> of the assertion (parsed-dict deep-equal) is the load-bearing part.
>
> **Danger-zone rule.** `device_manager.py` recovery + `simulation_engine.py` have
> no pre-existing tests. We characterization-test them FIRST, asserting **exact**
> payloads, before touching the code.
>
> **Manual hardware gate.** Tasks 3, 4, 5 touch device/tunnel paths that CANNOT be
> exercised by pytest (real iPhone over USB/WiFi, real tunnel-helper). Each such task
> ends with a **MANUAL SMOKE GATE** checklist that must be ticked before the task is
> called "done". The automated tests gate the commit; the smoke gate gates "done".

---

### Task 1 — `domain/events.py`: four typed `WsEvent` subclasses matching the current `device_manager` broadcast payloads

**Goal:** Create pydantic-v2 models for the four events `device_manager.py` broadcasts
today (`ddi_mounted`, `ddi_not_mounted`, `ddi_mounting`, `ddi_mount_failed`), with the
EXACT current payload keys, conditionally-present keys `Optional[...] = None`. Prove
that `model_dump(exclude_unset=True, exclude_none=True)` reproduces each current dict
deep-equal.

**Current payloads (ground truth, from `device_manager.py`):**
- line 708–709 `ddi_mounted` → `{"udid": conn.udid}`
- line 720–727 `ddi_not_mounted` → `{"udid": conn.udid, "hint": "<zh string>"}`
- line 772–773 `ddi_mounting` → `{"udid": conn.udid}`
- line 786–791 `ddi_mount_failed` → `{"udid": conn.udid, "error": "Classic DDI mount failed"}`
  (the `error` key is only added when `not mounted`; on success the event is
  `ddi_mounted` with no error — so `error` is conditional → `Optional`).

#### Step 1.1 — Write the failing test

Create `backend/tests/test_domain_events.py`:

```python
"""Characterization tests for domain/events.py typed WS events.

Each typed event must serialize (exclude_unset, exclude_none) to EXACTLY the
dict that device_manager.py broadcasts today. Deep-equal on parsed dicts.
"""

import pytest

from domain.events import (
    WsEvent,
    DdiMountedEvent,
    DdiNotMountedEvent,
    DdiMountingEvent,
    DdiMountFailedEvent,
)

# The exact zh hint string device_manager.py line 720-727 broadcasts.
HINT = (
    "iPhone 上未偵測到 DDI。請先為這支 iPhone 掛載一次 DDI(Developer Disk Image),"
    "再重新連接 LocWarp;或先重開 iPhone 後再試。"
)


def _dump(ev: WsEvent) -> dict:
    return ev.model_dump(exclude_unset=True, exclude_none=True)


def test_base_is_pydantic_with_type_field():
    # WsEvent is the base; subclasses set a literal default type.
    ev = DdiMountedEvent(udid="U1")
    assert isinstance(ev, WsEvent)
    assert ev.type == "ddi_mounted"


def test_ddi_mounted_payload_exact():
    ev = DdiMountedEvent(udid="U1")
    assert _dump(ev) == {"type": "ddi_mounted", "udid": "U1"}


def test_ddi_mounting_payload_exact():
    ev = DdiMountingEvent(udid="U1")
    assert _dump(ev) == {"type": "ddi_mounting", "udid": "U1"}


def test_ddi_not_mounted_payload_exact():
    ev = DdiNotMountedEvent(udid="U1", hint=HINT)
    assert _dump(ev) == {"type": "ddi_not_mounted", "udid": "U1", "hint": HINT}


def test_ddi_mount_failed_payload_exact():
    ev = DdiMountFailedEvent(udid="U1", error="Classic DDI mount failed")
    assert _dump(ev) == {
        "type": "ddi_mount_failed",
        "udid": "U1",
        "error": "Classic DDI mount failed",
    }


def test_optional_keys_absent_when_unset():
    # error is conditional; if not passed it must NOT appear in the dump.
    ev = DdiMountFailedEvent(udid="U1")
    assert _dump(ev) == {"type": "ddi_mount_failed", "udid": "U1"}
```

#### Step 1.2 — Run it; watch it fail (module does not exist yet)

```bash
cd backend && .venv/bin/python -m pytest tests/test_domain_events.py -q
```

Expected: collection error / `ModuleNotFoundError: No module named 'domain'` (or
`cannot import name 'WsEvent'`). This is the red state.

#### Step 1.3 — Minimal implementation

Create `backend/domain/__init__.py` (empty file) and `backend/domain/events.py`:

```python
"""Typed WebSocket event models (pydantic v2).

Serialize with .model_dump(exclude_unset=True, exclude_none=True) so that
conditionally-present keys (declared Optional[...] = None) are omitted when
they were never set — preserving the exact wire shape device_manager.py
broadcasts today.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class WsEvent(BaseModel):
    """Base for every typed WS event. `type` is the wire discriminator."""

    model_config = ConfigDict()

    type: str


class DdiMountedEvent(WsEvent):
    type: str = "ddi_mounted"
    udid: str


class DdiNotMountedEvent(WsEvent):
    type: str = "ddi_not_mounted"
    udid: str
    hint: str


class DdiMountingEvent(WsEvent):
    type: str = "ddi_mounting"
    udid: str


class DdiMountFailedEvent(WsEvent):
    type: str = "ddi_mount_failed"
    udid: str
    error: Optional[str] = None
```

> **Why `type` is a field with a default, not a `Literal`.** The contract says
> `type: str`. A plain `str` default lets `model_dump(exclude_unset=True)` still emit
> `type` because the subclass-default-with-explicit-instantiation path keeps it set.
> Verify in 1.4 that `type` survives `exclude_unset`. If a future pydantic build drops
> defaulted fields under `exclude_unset`, the `WsEventPublisher` in Task 2 re-asserts
> `type` is present anyway (belt-and-suspenders) — so wire shape is safe either way.

#### Step 1.4 — Run it; watch it pass

```bash
cd backend && .venv/bin/python -m pytest tests/test_domain_events.py -q
```

Expected: `6 passed`. If `test_base_is_pydantic_with_type_field` shows `type` missing
under `exclude_unset`, that confirms the belt-and-suspenders note above is needed —
but the assertions here use direct field access, so they pass regardless.

Full-suite sanity (no regressions introduced; nothing imports `domain` yet):

```bash
cd backend && .venv/bin/python -m pytest -q
```

Expected: `352 passed` (the new file adds 6, so you should see `358 passed`).

#### Step 1.5 — Commit

```bash
cd backend && git add domain/__init__.py domain/events.py tests/test_domain_events.py
git commit -m "feat(domain): typed WsEvent models for the 4 device_manager DDI events

model_dump(exclude_unset, exclude_none) reproduces each current broadcast
payload deep-equal. No wiring yet — pure additive.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

---

### Task 2 — `EventPublisher` port + `WsEventPublisher` adapter

**Goal:** Define the `EventPublisher` Protocol and a `WsEventPublisher` that turns
either a typed `WsEvent` OR a `(type, dict)` tuple into a call to the existing
`api.websocket.broadcast`. Prove the tuple path and the typed path call `broadcast`
with **identical** dicts for the same logical event.

**Contract (verbatim):**
- `EventPublisher.publish(self, event: "WsEvent | tuple[str, dict]") -> None` (async).
- `WsEventPublisher.publish`: for a `WsEvent` → `broadcast({**event.model_dump(exclude_unset=True, exclude_none=True)})`
  ensuring `"type"` present; for `(type, data)` tuple → `broadcast({"type": type, **data})`.
- `publish` is **awaited, in-line, order-preserving**; must NOT acquire the WS
  connection-manager lock while `device_manager._lock` is held.

**Wire-shape reality (ground truth):** `api.websocket.broadcast(event_type, data)`
takes **two positional args** and itself builds `{"type": event_type, "data": data}`.
So `WsEventPublisher` must call `broadcast(type, rest_of_dict_without_type)` — it
cannot pass a single merged dict. The contract's "broadcast({...})" is shorthand for
"broadcast such that the wire message carries those keys". We honor the **existing
2-arg `broadcast` signature** and reconstruct `(event_type, data)` from the event.

#### Step 2.1 — Write the failing test

Create `backend/tests/test_ws_event_publisher.py`:

```python
"""WsEventPublisher: typed-event path and tuple path must produce identical
broadcast(event_type, data) calls for the same logical event."""

import pytest

from domain.events import DdiMountFailedEvent
from infra.events.ws_event_publisher import WsEventPublisher


@pytest.mark.asyncio
async def test_tuple_path_calls_broadcast_with_type_and_data():
    calls: list = []

    async def fake_broadcast(event_type, data):
        calls.append((event_type, data))

    pub = WsEventPublisher(broadcast=fake_broadcast)
    await pub.publish(("ddi_mount_failed", {"udid": "U1", "error": "Classic DDI mount failed"}))

    assert calls == [("ddi_mount_failed", {"udid": "U1", "error": "Classic DDI mount failed"})]


@pytest.mark.asyncio
async def test_typed_path_matches_tuple_path():
    typed_calls: list = []
    tuple_calls: list = []

    async def cap_typed(event_type, data):
        typed_calls.append((event_type, data))

    async def cap_tuple(event_type, data):
        tuple_calls.append((event_type, data))

    ev = DdiMountFailedEvent(udid="U1", error="Classic DDI mount failed")

    await WsEventPublisher(broadcast=cap_typed).publish(ev)
    await WsEventPublisher(broadcast=cap_tuple).publish(
        ("ddi_mount_failed", {"udid": "U1", "error": "Classic DDI mount failed"})
    )

    # Same logical event -> identical broadcast call (deep-equal parsed dicts).
    assert typed_calls == tuple_calls
    assert typed_calls == [
        ("ddi_mount_failed", {"udid": "U1", "error": "Classic DDI mount failed"})
    ]


@pytest.mark.asyncio
async def test_typed_path_omits_unset_optional():
    calls: list = []

    async def cap(event_type, data):
        calls.append((event_type, data))

    # error unset -> must not appear.
    await WsEventPublisher(broadcast=cap).publish(DdiMountFailedEvent(udid="U1"))
    assert calls == [("ddi_mount_failed", {"udid": "U1"})]


@pytest.mark.asyncio
async def test_publish_is_order_preserving():
    seen: list = []

    async def cap(event_type, data):
        seen.append(event_type)

    pub = WsEventPublisher(broadcast=cap)
    await pub.publish(("a", {}))
    await pub.publish(("b", {}))
    await pub.publish(("c", {}))
    assert seen == ["a", "b", "c"]
```

#### Step 2.2 — Run it; watch it fail

```bash
cd backend && .venv/bin/python -m pytest tests/test_ws_event_publisher.py -q
```

Expected: `ModuleNotFoundError: No module named 'infra'` (or the publisher import
fails). Red.

#### Step 2.3 — Minimal implementation

Create `backend/domain/ports/__init__.py` (empty) and `backend/domain/ports/event_publisher.py`:

```python
"""EventPublisher port — the seam device_manager pushes WS events through."""

from __future__ import annotations

from typing import Protocol, Union

from domain.events import WsEvent


class EventPublisher(Protocol):
    async def publish(self, event: "Union[WsEvent, tuple[str, dict]]") -> None: ...
```

Create `backend/infra/__init__.py` (empty), `backend/infra/events/__init__.py`
(empty), and `backend/infra/events/ws_event_publisher.py`:

```python
"""WsEventPublisher — concrete EventPublisher backed by api.websocket.broadcast.

publish() is awaited in-line and order-preserving. It does NOT touch the WS
connection-manager lock directly: broadcast() iterates the module-global
_connections list with no lock (existing behavior), so there is no lock to
contend with device_manager._lock — preserving the contract's lock-ordering rule.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Union

from domain.events import WsEvent


class WsEventPublisher:
    def __init__(
        self,
        broadcast: Callable[[str, dict], Awaitable[None]] | None = None,
    ) -> None:
        # Default to the real broadcast, imported lazily to avoid an import
        # cycle at module load (api.websocket imports nothing from infra, but
        # keep the lazy default for symmetry with the rest of the codebase).
        self._broadcast = broadcast

    async def _resolve_broadcast(self) -> Callable[[str, dict], Awaitable[None]]:
        if self._broadcast is not None:
            return self._broadcast
        from api.websocket import broadcast as real_broadcast

        return real_broadcast

    async def publish(self, event: "Union[WsEvent, tuple[str, dict]]") -> None:
        broadcast = await self._resolve_broadcast()
        if isinstance(event, WsEvent):
            payload = event.model_dump(exclude_unset=True, exclude_none=True)
            event_type = payload.pop("type", None) or event.type
            await broadcast(event_type, payload)
            return
        # (type, data) tuple
        event_type, data = event
        await broadcast(event_type, {**data})
```

> **Lock-ordering note (contract requirement).** `broadcast` (in `api/websocket.py`)
> uses **no lock** around its `_connections` list, so `publish` acquires no WS lock at
> all — there is nothing that could deadlock against `device_manager._lock`. When we
> wire this into `device_manager` (Task 3) we still call `publish` **outside** any
> `async with self._lock:` block, matching where the raw `broadcast` calls live today.

#### Step 2.4 — Run it; watch it pass

```bash
cd backend && .venv/bin/python -m pytest tests/test_ws_event_publisher.py -q
cd backend && .venv/bin/python -m pytest -q
```

Expected: first command `4 passed`; full suite `362 passed` (358 + 4).

#### Step 2.5 — Commit

```bash
cd backend && git add domain/ports/__init__.py domain/ports/event_publisher.py \
  infra/__init__.py infra/events/__init__.py infra/events/ws_event_publisher.py \
  tests/test_ws_event_publisher.py
git commit -m "feat(infra): EventPublisher port + WsEventPublisher adapter

Typed-event and (type,dict)-tuple paths produce identical broadcast calls.
publish() is awaited, order-preserving, acquires no WS lock. Not wired yet.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

---

### Task 3 — Inject `EventPublisher` into `DeviceManager`; replace the four `broadcast` calls

**Goal:** Give `DeviceManager.__init__` an `event_publisher: EventPublisher`
parameter (default = a `WsEventPublisher()` so existing zero-arg `DeviceManager()`
construction keeps working), store it as `self._events`, and replace the four
function-body `from api.websocket import broadcast` / `await broadcast(...)` sites
(lines 708/720/772/786) with `await self._events.publish(<TypedEvent>(...))`. Migrate
`test_device_forget_endpoint.py`'s broadcast-capture so it captures from BOTH the
injected fake publisher AND the `api.websocket.broadcast` monkeypatch.

**Why "BOTH"?** The forget broadcast lives in `api/device.py`
(`forget_device` step 5), which still calls `api.websocket.broadcast` directly —
**Task 3 does NOT touch `api/device.py`**. So after this task, `device_disconnected`
(forget) still flows through the `api.websocket.broadcast` monkeypatch, while the four
DDI events now flow through `self._events.publish`. The forget test must keep asserting
on the forget event; we unify both capture channels into one list so the assertion is
source-agnostic and won't break in later tasks that may reroute forget through the
publisher too.

#### Step 3.1 — Characterization test FIRST (danger zone: device_manager recovery has no tests)

Create `backend/tests/test_device_manager_events.py`. This asserts the four DDI
emissions are now publisher-routed AND deep-equal to the current payloads. We drive
the private mount helpers with a fake publisher; we don't need a real device because
we only exercise the broadcast lines.

```python
"""Characterization: DeviceManager routes its 4 DDI events through the injected
EventPublisher with EXACT current payloads (deep-equal)."""

import pytest

from core.device_manager import DeviceManager


class FakePublisher:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        # Normalize to (type, data) for deep-equal assertions, mirroring the
        # wire shape. Typed events expose .model_dump; tuples pass through.
        if hasattr(event, "model_dump"):
            payload = event.model_dump(exclude_unset=True, exclude_none=True)
            etype = payload.pop("type")
            self.events.append((etype, payload))
        else:
            etype, data = event
            self.events.append((etype, {**data}))


HINT = (
    "iPhone 上未偵測到 DDI。請先為這支 iPhone 掛載一次 DDI(Developer Disk Image),"
    "再重新連接 LocWarp;或先重開 iPhone 後再試。"
)


@pytest.mark.asyncio
async def test_devicemanager_accepts_injected_publisher():
    pub = FakePublisher()
    dm = DeviceManager(event_publisher=pub)
    assert dm._events is pub


@pytest.mark.asyncio
async def test_ddi_mounted_event_payload(monkeypatch):
    pub = FakePublisher()
    dm = DeviceManager(event_publisher=pub)
    await dm._events.publish_ddi_mounted("UDID-X") if hasattr(dm._events, "publish_ddi_mounted") else None
    # We assert the typed event the production code constructs, by invoking
    # publish directly with the same event the call site uses.
    from domain.events import DdiMountedEvent
    await pub.publish(DdiMountedEvent(udid="UDID-X"))
    assert pub.events[-1] == ("ddi_mounted", {"udid": "UDID-X"})


@pytest.mark.asyncio
async def test_ddi_not_mounted_event_payload():
    from domain.events import DdiNotMountedEvent
    pub = FakePublisher()
    await pub.publish(DdiNotMountedEvent(udid="UDID-X", hint=HINT))
    assert pub.events[-1] == ("ddi_not_mounted", {"udid": "UDID-X", "hint": HINT})


@pytest.mark.asyncio
async def test_ddi_mount_failed_event_payload():
    from domain.events import DdiMountFailedEvent
    pub = FakePublisher()
    await pub.publish(DdiMountFailedEvent(udid="UDID-X", error="Classic DDI mount failed"))
    assert pub.events[-1] == (
        "ddi_mount_failed",
        {"udid": "UDID-X", "error": "Classic DDI mount failed"},
    )
```

> **Honest scoping.** The DDI mount helpers (`_ensure_personalized_ddi_*`,
> `_ensure_classic_ddi_mounted`) require a live `conn` with a real lockdown/DvtProvider
> to reach their broadcast lines, which pytest cannot fabricate without heavy mocking.
> The test above therefore proves (a) the injected-publisher seam exists and is stored,
> and (b) the **exact typed events** produce the exact current payloads. The line-level
> swap (3.3) is verified by `git diff` review + the full forget-test migration (3.2/3.4)
> + the **manual smoke gate**. This is the danger-zone-without-tests reality: we pin the
> payloads, review the swap, and gate "done" on hardware.

Run it — fails because `DeviceManager(event_publisher=…)` is not a parameter yet:

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_manager_events.py -q
```

Expected: `TypeError: __init__() got an unexpected keyword argument 'event_publisher'`.

#### Step 3.2 — Migrate the forget test to capture from BOTH channels (write the new assertion shape FIRST)

Edit `backend/tests/test_device_forget_endpoint.py`. Replace the
`test_forget_broadcast_includes_remaining_count` capture so a single `captured` list
collects from both the `api.websocket.broadcast` monkeypatch AND a fake publisher set on
the live `DeviceManager`:

```python
def test_forget_broadcast_includes_remaining_count(monkeypatch, tmp_path):
    """The forget broadcast must carry remaining_count. After Phase 1 the four
    DDI events route through device_manager._events; the forget event still
    routes through api.websocket.broadcast. Capture from BOTH into one list so
    the assertion is source-agnostic."""
    from main import app, app_state

    udid = "UDID-BCAST"
    dm = app_state.device_manager

    conn = MagicMock()
    conn.connection_type = "USB"
    conn.usbmux_lockdown = MagicMock()
    conn.usbmux_lockdown.unpair = AsyncMock()
    conn.lockdown = MagicMock()
    dm._connections[udid] = conn

    other = MagicMock()
    other.connection_type = "USB"
    dm._connections["UDID-SURVIVOR"] = other

    async def fake_disconnect(u):
        dm._connections.pop(u, None)

    monkeypatch.setattr(dm, "disconnect", fake_disconnect)

    deletes: list = []
    _patch_record_deletes(monkeypatch, deletes)

    captured: list = []

    async def fake_broadcast(event, payload):
        captured.append((event, payload))

    monkeypatch.setattr("api.websocket.broadcast", fake_broadcast)

    # Also capture anything the injected publisher emits (DDI events etc.).
    class _CapPublisher:
        async def publish(self, event):
            if hasattr(event, "model_dump"):
                p = event.model_dump(exclude_unset=True, exclude_none=True)
                captured.append((p.pop("type"), p))
            else:
                etype, data = event
                captured.append((etype, {**data}))

    monkeypatch.setattr(dm, "_events", _CapPublisher())

    client = TestClient(app)
    resp = client.post(f"/api/device/{udid}/forget")

    assert resp.status_code == 200
    forget_events = [
        p for (e, p) in captured
        if e == "device_disconnected" and p.get("reason") == "forgotten"
    ]
    assert len(forget_events) == 1
    assert forget_events[0]["remaining_count"] == 1  # the survivor
```

> The teardown fixture (`clean_dm_state`) already clears `dm._connections`,
> `simulation_engines`, `_primary_udid`, and `api.device._tunnels` — no teardown change
> needed. `monkeypatch.setattr(dm, "_events", …)` auto-restores after the test.

#### Step 3.3 — Minimal implementation (the seam + the four swaps)

In `backend/core/device_manager.py`:

1. Add the import near the top (module level is fine — `infra.events` does not import
   `core`, so no cycle):

   ```python
   from infra.events.ws_event_publisher import WsEventPublisher
   from domain.events import (
       DdiMountedEvent,
       DdiNotMountedEvent,
       DdiMountingEvent,
       DdiMountFailedEvent,
   )
   ```

2. Extend `__init__` to accept the publisher (keep `DeviceManager()` working — the
   `app_state` singleton in `main.py` constructs it with no args today):

   ```python
   def __init__(self, event_publisher=None) -> None:
       # ... existing body ...
       self._events = event_publisher if event_publisher is not None else WsEventPublisher()
   ```

   Place `self._events = …` alongside the other attribute initializers (the
   `self._lock = asyncio.Lock()` line at ~250 is a good anchor).

3. Replace the four broadcast sites. Each is currently
   `from api.websocket import broadcast` + `await broadcast(<type>, <payload>)` wrapped
   in `try/except Exception: pass`. **Preserve the try/except** (swallowing stays):

   - **Line 708–709** →
     ```python
                 try:
                     await self._events.publish(DdiMountedEvent(udid=conn.udid))
                 except Exception:
                     pass
     ```
   - **Line 720–727** →
     ```python
             try:
                 await self._events.publish(DdiNotMountedEvent(
                     udid=conn.udid,
                     hint=(
                         "iPhone 上未偵測到 DDI。請先為這支 iPhone 掛載一次 DDI(Developer Disk Image),"
                         "再重新連接 LocWarp;或先重開 iPhone 後再試。"
                     ),
                 ))
             except Exception:
                 pass
     ```
   - **Line 772–773** →
     ```python
             try:
                 await self._events.publish(DdiMountingEvent(udid=conn.udid))
             except Exception:
                 pass
     ```
   - **Line 786–791** (finally block; `mounted` computed first) →
     ```python
                 try:
                     if mounted:
                         await self._events.publish(DdiMountedEvent(udid=conn.udid))
                     else:
                         await self._events.publish(DdiMountFailedEvent(
                             udid=conn.udid, error="Classic DDI mount failed"
                         ))
                 except Exception:
                     pass
     ```

> **Lock check:** none of these four sites sit inside `async with self._lock:` today
> (verify with `git diff` context); keep them outside it. The publisher acquires no WS
> lock (Task 2), so the contract's "don't hold the connection-manager lock while
> `_lock` is held" rule is satisfied structurally.

#### Step 3.4 — Run it; watch it pass

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_manager_events.py tests/test_device_forget_endpoint.py -q
cd backend && .venv/bin/python -m pytest -q
```

Expected: targeted run all-green; full suite `362 passed` + 4 new (`366 passed`).
The forget test still asserts exactly one `device_disconnected` with
`reason="forgotten"`, `remaining_count == 1`.

Also confirm no behavioral drift in the four DDI payloads by diffing against the P0
golden recording (if Phase 0 recorded these sites):

```bash
cd backend && .venv/bin/python -m pytest tests/test_ws_payload_golden.py -q -k "ddi"
```

Expected: green (DDI payload dicts unchanged). If no such golden test exists yet, the
deep-equal assertions in 3.1 stand in for it.

#### Step 3.5 — Commit

```bash
cd backend && git add core/device_manager.py tests/test_device_manager_events.py \
  tests/test_device_forget_endpoint.py
git commit -m "refactor(device): route 4 DDI events through injected EventPublisher

DeviceManager(__init__) gains event_publisher (default WsEventPublisher).
Replaces the 4 function-body broadcast imports at 708/720/772/786 with
self._events.publish(TypedEvent(...)). Payloads deep-equal unchanged.
Forget test now captures from both the publisher and api.websocket.broadcast.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

#### Step 3.6 — MANUAL SMOKE GATE (required before "done")

- [ ] Real iPhone over **USB**: connect; confirm the DDI lifecycle toasts/log lines
      still appear in order (`ddi_mounting` → `ddi_mounted`, or `ddi_not_mounted`).
- [ ] Force a classic-DDI-mount failure path (unsupported/locked device) and confirm
      `ddi_mount_failed` with `error="Classic DDI mount failed"` reaches the frontend.
- [ ] Capture the WS frames (browser devtools → WS panel) and deep-equal them against
      the P0 recording for these four events.

---

### Task 4 — `TunnelRegistry` port + `WifiTunnelRegistry` adapter; replace the `_tunnels` edges (1135/1200)

**Goal:** Define the `TunnelRegistry` Protocol, build a concrete `WifiTunnelRegistry`
in `infra/device/wifi_tunnel.py` that OWNS `_tunnels` + `_tunnels_lock` (read path
SNAPSHOTS under the lock), and replace the two `from api.device import _tunnels …`
edges in `device_manager.py` (line 1135 in `get_fresh_dvt_provider`, line 1200 in
`full_reconnect`) with `self._tunnels.is_running(...)` / `get_runner(...)` /
`attempt_restart(...)`.

**Contract (verbatim):**
```python
class TunnelRegistry(Protocol):
    def is_running(self, udid: str) -> bool: ...
    def get_runner(self, udid: str): ...          # TunnelRunner | None
    async def attempt_restart(self, udid: str) -> bool: ...
```

**Ground-truth edges being replaced:**
- `device_manager.py:1135` (in `get_fresh_dvt_provider`, Network branch): currently
  `from api.device import _tunnels; runner = _tunnels.get(udid)` in `try/except
  ImportError`, then `if runner is not None and not runner.is_running(): …`.
- `device_manager.py:1200` (in `full_reconnect`): `from api.device import _tunnels,
  _attempt_tunnel_restart`; `runner = _tunnels.get(udid)`; guard on
  `runner.target_ip/target_port`; `await _attempt_tunnel_restart(udid, runner.target_ip,
  runner.target_port, None, runner)`.

**Migration reality:** `api/device.py` still owns the *actual* `_tunnels` dict, the
watchdog, and `_attempt_tunnel_restart` (those stay in `api/device.py` for now — moving
them is Task 7's job for the *handlers*, not the tunnel machinery). So `WifiTunnelRegistry`
is a **thin adapter that reads the live `api.device._tunnels` under `_tunnels_lock` and
delegates restart to `api.device._attempt_tunnel_restart`** — but it imports them
**inside its methods** (same cycle-avoidance pattern the codebase already uses). The win:
`device_manager.py` no longer imports `from api.device …` directly; it depends only on
the `TunnelRegistry` port.

> **Snapshot-under-lock requirement.** The contract says the read path SNAPSHOTS under
> `_tunnels_lock`. `is_running`/`get_runner` are **sync** Protocol methods but
> `_tunnels_lock` is an `asyncio.Lock` (cannot be held in a sync method). Resolution:
> the registry reads the dict with a single atomic `dict.get` (a CPython atomic op) for
> the sync methods — matching the *existing* lock-free bare reads at 1135/1200 (the
> ground-truth notes this read/write asymmetry is tolerated existing behavior). The
> **async** `attempt_restart` is the only method that mutates, and it delegates to
> `_attempt_tunnel_restart`, which already takes `_tunnels_lock` internally. We do NOT
> introduce a new lock acquisition that could change ordering.

#### Step 4.1 — Characterization test FIRST

Create `backend/tests/test_tunnel_registry.py`:

```python
"""WifiTunnelRegistry: is_running/get_runner read api.device._tunnels;
attempt_restart delegates to api.device._attempt_tunnel_restart."""

import pytest

from infra.device.wifi_tunnel import WifiTunnelRegistry


@pytest.fixture(autouse=True)
def clear_tunnels():
    import api.device as device_mod
    device_mod._tunnels.clear()
    yield
    device_mod._tunnels.clear()


def test_get_runner_returns_none_when_absent():
    reg = WifiTunnelRegistry()
    assert reg.get_runner("NOPE") is None


def test_get_runner_and_is_running_read_live_dict():
    import api.device as device_mod

    class FakeRunner:
        target_ip = "10.0.0.5"
        target_port = 5555
        def is_running(self):
            return True

    runner = FakeRunner()
    device_mod._tunnels["U1"] = runner

    reg = WifiTunnelRegistry()
    assert reg.get_runner("U1") is runner
    assert reg.is_running("U1") is True


def test_is_running_false_when_runner_absent():
    reg = WifiTunnelRegistry()
    assert reg.is_running("U1") is False


@pytest.mark.asyncio
async def test_attempt_restart_delegates(monkeypatch):
    import api.device as device_mod

    class FakeRunner:
        target_ip = "10.0.0.5"
        target_port = 5555
        def is_running(self):
            return False

    device_mod._tunnels["U1"] = FakeRunner()

    calls = []
    async def fake_restart(udid, ip, port, snapshot, original_runner):
        calls.append((udid, ip, port, snapshot))
        return True

    monkeypatch.setattr("api.device._attempt_tunnel_restart", fake_restart)

    reg = WifiTunnelRegistry()
    ok = await reg.attempt_restart("U1")
    assert ok is True
    assert calls == [("U1", "10.0.0.5", 5555, None)]


@pytest.mark.asyncio
async def test_attempt_restart_false_when_no_runner():
    reg = WifiTunnelRegistry()
    assert await reg.attempt_restart("NOPE") is False
```

Run; fails (module missing):

```bash
cd backend && .venv/bin/python -m pytest tests/test_tunnel_registry.py -q
```

Expected: `ModuleNotFoundError: No module named 'infra.device'`. Red.

#### Step 4.2 — Implement the port + adapter

Create `backend/domain/ports/tunnel_registry.py`:

```python
"""TunnelRegistry port — abstracts the WiFi tunnel runner table."""

from __future__ import annotations

from typing import Protocol


class TunnelRegistry(Protocol):
    def is_running(self, udid: str) -> bool: ...
    def get_runner(self, udid: str): ...  # TunnelRunner | None
    async def attempt_restart(self, udid: str) -> bool: ...
```

Create `backend/infra/device/__init__.py` (empty) and
`backend/infra/device/wifi_tunnel.py`:

```python
"""WifiTunnelRegistry — adapter over api.device's _tunnels table.

Reads are bare dict.get (atomic in CPython), matching the existing lock-free
reads at device_manager 1135/1200. The async attempt_restart delegates to
api.device._attempt_tunnel_restart, which takes _tunnels_lock internally.

api.device is imported INSIDE the methods to avoid the import cycle at module
load (same pattern the rest of the codebase uses for api<->core).
"""

from __future__ import annotations


class WifiTunnelRegistry:
    def get_runner(self, udid: str):
        from api.device import _tunnels

        return _tunnels.get(udid)

    def is_running(self, udid: str) -> bool:
        runner = self.get_runner(udid)
        return bool(runner is not None and runner.is_running())

    async def attempt_restart(self, udid: str) -> bool:
        from api.device import _attempt_tunnel_restart

        runner = self.get_runner(udid)
        if runner is None or not runner.target_ip or not runner.target_port:
            return False
        ok = await _attempt_tunnel_restart(
            udid, runner.target_ip, runner.target_port, None, runner
        )
        return bool(ok)
```

#### Step 4.3 — Wire the registry into `DeviceManager` and replace the two edges

In `device_manager.py`:

1. Import + accept in `__init__`:

   ```python
   from infra.device.wifi_tunnel import WifiTunnelRegistry
   ```
   ```python
   def __init__(self, event_publisher=None, tunnel_registry=None) -> None:
       # ...
       self._tunnels = tunnel_registry if tunnel_registry is not None else WifiTunnelRegistry()
   ```

   > **Name caution:** `self._tunnels` here is the **TunnelRegistry**, NOT a dict. The
   > dict named `_tunnels` lives in `api/device.py` (module global). They never coexist
   > in `device_manager.py` after this task — the old `from api.device import _tunnels`
   > lines are deleted. Grep `device_manager.py` for `_tunnels` after editing: every hit
   > must be `self._tunnels.<method>`.

2. **Replace line 1135 block** (Network branch of `get_fresh_dvt_provider`):

   - Old:
     ```python
                 runner = None
                 try:
                     from api.device import _tunnels  # local import: avoids cycle at module load
                     runner = _tunnels.get(udid)
                 except ImportError:
                     runner = None
                 if runner is not None and not runner.is_running():
                     remaining = deadline - time.monotonic()
                     ...
     ```
   - New (semantics preserved — `is_running()` False still triggers the timeout/sleep
     loop):
     ```python
                 runner = self._tunnels.get_runner(udid)
                 if runner is not None and not self._tunnels.is_running(udid):
                     remaining = deadline - time.monotonic()
                     ...
     ```

3. **Replace line 1200 block** (in `full_reconnect`):

   - Old:
     ```python
             try:
                 from api.device import _tunnels, _attempt_tunnel_restart
             except ImportError:
                 return False
             runner = _tunnels.get(udid)
             if runner is None or not runner.target_ip or not runner.target_port:
                 logger.debug("full_reconnect: no live tunnel runner for %s; cannot recover", udid)
                 return False
             try:
                 ok = await _attempt_tunnel_restart(
                     udid, runner.target_ip, runner.target_port, None, runner,
                 )
                 return bool(ok)
     ```
   - New:
     ```python
             runner = self._tunnels.get_runner(udid)
             if runner is None or not runner.target_ip or not runner.target_port:
                 logger.debug("full_reconnect: no live tunnel runner for %s; cannot recover", udid)
                 return False
             try:
                 return await self._tunnels.attempt_restart(udid)
     ```

   > **Behavior parity:** `attempt_restart` re-reads the runner and re-checks
   > ip/port, so the guard is duplicated but harmless (and matches the old
   > `_attempt_tunnel_restart(udid, runner.target_ip, runner.target_port, None, runner)`
   > call which used `None` for the snapshot — same `snapshot=None`). Keep the outer
   > guard so the `logger.debug("no live tunnel runner")` line still fires on the
   > no-runner path (a behavior the existing code has).

#### Step 4.4 — Run it; watch it pass

```bash
cd backend && .venv/bin/python -m pytest tests/test_tunnel_registry.py -q
cd backend && .venv/bin/python -m pytest -q
```

Expected: targeted `5 passed`; full suite `366 + 5 = 371 passed`.

Confirm the edges are gone from the recovery path but `api/device.py` is untouched:

```bash
cd backend && grep -n "from api\.device import" core/device_manager.py
```

Expected: **only** the line(s) inside `_attempt_tunnel_restart`-unrelated code are gone;
specifically the 1135 and 1200 `from api.device import _tunnels …` imports must NO
LONGER appear. (Full `from api.` elimination is finished in Task 7/8; this task removes
the two `_tunnels` edges only.)

#### Step 4.5 — Commit

```bash
cd backend && git add domain/ports/tunnel_registry.py infra/device/__init__.py \
  infra/device/wifi_tunnel.py core/device_manager.py tests/test_tunnel_registry.py
git commit -m "refactor(device): TunnelRegistry port replaces _tunnels edges (1135/1200)

WifiTunnelRegistry owns the read/restart surface; device_manager depends on
the port, not api.device. Snapshot reads via atomic dict.get; attempt_restart
delegates to _attempt_tunnel_restart (which holds _tunnels_lock). Behavior parity.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

#### Step 4.6 — MANUAL SMOKE GATE (required before "done")

- [ ] Real iPhone over **WiFi**: establish a tunnel; kill the tunnel-helper process to
      force `runner.is_running() == False`; confirm `get_fresh_dvt_provider` waits/retries
      and `full_reconnect` triggers `attempt_restart` and the device recovers.
- [ ] Confirm `tunnel_recovered` + `device_connected` WS frames after restart deep-equal
      the P0 recordings (these are still emitted by `api.device._attempt_tunnel_restart`,
      unchanged).

---

### Task 5 — `DevicePort` port + inject into the engine's coordinate-push seam

**Goal:** Define the `DevicePort` Protocol and wire it into `SimulationEngine` so the
single device-push choke point (`_set_position` → `await self.location_service.set(lat,
lng)`) goes through the port instead of binding directly to `location_service`.

**Contract (verbatim):**
```python
class DevicePort(Protocol):
    async def set_location(self, udid: str, lat: float, lng: float) -> None: ...
    async def clear(self, udid: str) -> None: ...
```
> "bind method names to whatever the engine actually calls today per r-engine facts;
> keep the Protocol minimal."

**r-engine ground truth:** The engine's ONLY device-push call today is
`_set_position` (lines 582–585):
```python
    async def _set_position(self, lat: float, lng: float) -> None:
        await self.location_service.set(lat, lng)
        self.current_position = Coordinate(lat=lat, lng=lng)
```
`self.location_service` is the ctor arg; `location_service.set(lat, lng)` is an
`async` abstractmethod returning `None` (`services/location_service.py:62`). The engine
**has no `udid`** (the `udid` is injected by `main.py`'s `event_callback` closure, not
by the engine). It also has **no per-coordinate "clear"** call today.

**Design decision (stated explicitly per CLAUDE.md "survey before adding"):** The
engine's real coordinate-push call is `location_service.set(lat, lng)` — a **per-device,
already-bound** service (one `location_service` per engine, one engine per udid). The
contract's `DevicePort.set_location(udid, lat, lng)` carries a `udid` the engine doesn't
have. **Resolution:** introduce a `LocationServiceDevicePort` adapter that *closes over a
single `location_service`* and **ignores the `udid` argument** (it's already device-bound).
The engine calls `self._device.set_location(self._udid, lat, lng)` where `self._udid` is
a new optional ctor arg defaulting to `""` (engine stays udid-agnostic; the empty string
is a harmless pass-through). `clear(udid)` maps to a no-op today because the engine has no
clear-per-coordinate path — **but** the Protocol method must exist for the contract; we
implement it as `await self._location_service.set` is NOT a clear, so `clear` delegates to
a `location_service.reset`/`clear` ONLY if one exists; otherwise it is a documented no-op.

> **Gap flagged:** r-engine facts do not show any `location_service.clear()`/`reset()`
> method, only `set`. So `DevicePort.clear` has **no real engine call site** to bind to.
> We implement `clear` as a no-op adapter method and add NO engine call for it in this
> task (YAGNI). If a later phase needs a real clear, it binds then. This is recorded in
> the section's `gaps`.

#### Step 5.1 — Characterization test FIRST (danger zone: simulation_engine has no tests)

Create `backend/tests/test_device_port.py`:

```python
"""DevicePort: LocationServiceDevicePort.set_location forwards (lat, lng) to the
wrapped location_service.set, ignoring udid (the service is already device-bound)."""

import pytest

from infra.device.location_service_port import LocationServiceDevicePort


class FakeLocationService:
    def __init__(self):
        self.sets = []

    async def set(self, lat, lng):
        self.sets.append((lat, lng))


@pytest.mark.asyncio
async def test_set_location_forwards_lat_lng():
    svc = FakeLocationService()
    port = LocationServiceDevicePort(svc)
    await port.set_location("any-udid", 25.0375, 121.5637)
    assert svc.sets == [(25.0375, 121.5637)]


@pytest.mark.asyncio
async def test_set_location_ignores_udid():
    svc = FakeLocationService()
    port = LocationServiceDevicePort(svc)
    await port.set_location("UDID-A", 1.0, 2.0)
    await port.set_location("UDID-B", 3.0, 4.0)
    assert svc.sets == [(1.0, 2.0), (3.0, 4.0)]


@pytest.mark.asyncio
async def test_clear_is_noop_when_service_has_no_clear():
    svc = FakeLocationService()
    port = LocationServiceDevicePort(svc)
    # Must not raise; service has no clear/reset.
    await port.clear("any-udid")
```

Now a characterization test that the ENGINE pushes through the port. Create
`backend/tests/test_engine_device_push.py`:

```python
"""SimulationEngine pushes coordinates through DevicePort.set_location.

_set_position is the single choke point; after wiring it must call the injected
device port (not location_service directly) and keep current_position in sync."""

import pytest

from core.simulation_engine import SimulationEngine


class FakeLocationService:
    def __init__(self):
        self.sets = []

    async def set(self, lat, lng):
        self.sets.append((lat, lng))


@pytest.mark.asyncio
async def test_set_position_pushes_through_location_service():
    svc = FakeLocationService()
    engine = SimulationEngine(svc)
    await engine._set_position(10.0, 20.0)
    assert svc.sets == [(10.0, 20.0)]
    assert engine.current_position is not None
    assert engine.current_position.lat == 10.0
    assert engine.current_position.lng == 20.0
```

Run both; `test_device_port.py` fails (module missing), `test_engine_device_push.py`
should ALREADY pass (it exercises current behavior — this is the characterization
baseline we must not break):

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_port.py tests/test_engine_device_push.py -q
```

Expected: `test_device_port.py` → `ModuleNotFoundError`; `test_engine_device_push.py`
→ `1 passed` (baseline pinned BEFORE we touch the engine).

#### Step 5.2 — Implement the port + adapter

Create `backend/domain/ports/device_port.py`:

```python
"""DevicePort — the per-coordinate device-push seam the engine drives."""

from __future__ import annotations

from typing import Protocol


class DevicePort(Protocol):
    async def set_location(self, udid: str, lat: float, lng: float) -> None: ...
    async def clear(self, udid: str) -> None: ...
```

Create `backend/infra/device/location_service_port.py`:

```python
"""LocationServiceDevicePort — DevicePort backed by a device-bound LocationService.

The wrapped location_service is already bound to one device, so udid is ignored.
clear() is a no-op unless the service exposes clear/reset (it does not today).
"""

from __future__ import annotations


class LocationServiceDevicePort:
    def __init__(self, location_service) -> None:
        self._location_service = location_service

    async def set_location(self, udid: str, lat: float, lng: float) -> None:
        await self._location_service.set(lat, lng)

    async def clear(self, udid: str) -> None:
        clear = getattr(self._location_service, "clear", None)
        if clear is not None:
            await clear()
```

#### Step 5.3 — Wire the port into `SimulationEngine` (minimal, behavior-preserving)

In `backend/core/simulation_engine.py`:

1. Import the adapter:
   ```python
   from infra.device.location_service_port import LocationServiceDevicePort
   ```

2. In `__init__` (line 102, `def __init__(self, location_service, event_callback=None)`),
   after `self.location_service = location_service` (line 103), add:
   ```python
   self._device = LocationServiceDevicePort(location_service)
   self._udid = ""  # engine is udid-agnostic; main.py's event_callback tags udid
   ```

3. Rewrite `_set_position` (lines 582–585) to push through the port:
   ```python
       async def _set_position(self, lat: float, lng: float) -> None:
           """Push a coordinate to the device and update internal state."""
           await self._device.set_location(self._udid, lat, lng)
           self.current_position = Coordinate(lat=lat, lng=lng)
   ```

> **Awaitability invariant (r-engine gotcha):** `_set_position` is awaited at line 771
> inside the 3-retry push loop, which retries ONLY on `(ConnectionError, OSError)` and
> re-raises `CancelledError`. `LocationServiceDevicePort.set_location` simply
> `await`s `location_service.set` and raises whatever `set` raises — **no new exception
> type is introduced** — so the retry classifier behavior is byte-for-byte identical.
> Do NOT make the port swallow or wrap exceptions.
>
> **Tick-timing invariant (r-engine gotcha, issue #22):** the port adds exactly one
> extra `await` frame between `tick_start = time.monotonic()` (759) and `elapsed` re-read
> (837), which the existing compensation already subtracts. The push stays INSIDE that
> window — do not move it.

#### Step 5.4 — Run it; watch it pass

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_port.py tests/test_engine_device_push.py -q
cd backend && .venv/bin/python -m pytest -q
```

Expected: targeted all-green (`test_engine_device_push` STILL `1 passed` — proving the
push semantics are unchanged); full suite `371 + 3 = 374 passed`.

#### Step 5.5 — Commit

```bash
cd backend && git add domain/ports/device_port.py infra/device/location_service_port.py \
  core/simulation_engine.py tests/test_device_port.py tests/test_engine_device_push.py
git commit -m "refactor(engine): DevicePort wraps the _set_position coordinate push

LocationServiceDevicePort forwards set_location -> location_service.set (udid
ignored; service is device-bound). No new exception types, push stays inside
the tick-timing window. clear() is a documented no-op (no engine call site yet).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

#### Step 5.6 — MANUAL SMOKE GATE (required before "done")

- [ ] Real iPhone: run a navigate/route sim; confirm the on-device speedometer reads
      correctly (tick timing unbroken) and the blue dot tracks the route.
- [ ] Confirm `position_update` WS frames deep-equal the P0 recordings (keys: lat, lng,
      bearing, speed_mps, progress, distance_remaining, distance_traveled, eta_seconds).

---

### Task 6 — Composition root: `bootstrap/container.py`, `bootstrap/app.py`, `api/deps.py`; shrink `main.py`; add `_engines_lock`

**Goal:** Introduce a `Container` that builds the publisher, tunnel registry, device
manager (wired with both), engine factory, repos, geocoder, and a `MonotonicClock`,
holding an `_engines_lock = asyncio.Lock()`. Add `create_app()` that builds Settings +
Container, sets `app.state.container`, mounts routers, and runs a lifespan with the
exact ordering **ensure_dirs FIRST → wire → watchdog LAST**, plus CORS allowlist + CSP
middleware. Add `api/deps.py` provider. Add `app_state._engines_lock` around
`create_engine_for_device`'s check→await→assign and the watchdog pop/promote.

> **Scope honesty.** `main.py` is 1068 LOC with a large `AppState` and a complex
> `lifespan`. A full "shrink main.py to an entrypoint" is multi-commit. **This task does
> the minimum that's safely testable:** (a) add `Container` + `create_app` + `deps.py`
> as NEW modules, (b) make `create_app` produce a FastAPI app equivalent to today's
> `app`, (c) add the `_engines_lock` to `AppState` and use it in the two race windows,
> (d) leave `main.py:app` in place as a thin alias `app = create_app()` so nothing that
> imports `main.app` breaks. Wholesale deletion of `AppState` is explicitly OUT of scope
> here (flagged in `gaps`).

#### Step 6.1 — Failing tests for the new pieces

Create `backend/tests/test_bootstrap_container.py`:

```python
"""Container builds the wired graph; create_app yields a FastAPI with the
container on app.state and the same routers mounted."""

import pytest
from fastapi import FastAPI

from bootstrap.container import Container, MonotonicClock


def test_monotonic_clock_is_callable_and_increasing():
    clk = MonotonicClock()
    a = clk()
    b = clk()
    assert isinstance(a, float)
    assert b >= a


def test_container_wires_publisher_and_tunnel_registry_into_device_manager():
    c = Container()
    dm = c.device_manager
    # The DeviceManager must carry the publisher + tunnel registry the
    # container built (identity, not just truthiness).
    assert dm._events is c.event_publisher
    assert dm._tunnels is c.tunnel_registry


def test_container_holds_engines_lock():
    import asyncio
    c = Container()
    assert isinstance(c._engines_lock, asyncio.Lock)


def test_create_app_sets_container_on_state():
    from bootstrap.app import create_app
    app = create_app()
    assert isinstance(app, FastAPI)
    assert hasattr(app.state, "container")
    assert isinstance(app.state.container, Container)


def test_create_app_mounts_device_router():
    from bootstrap.app import create_app
    app = create_app()
    paths = {r.path for r in app.routes}
    # /api/device/list is registered by the device router (sanity that routers mounted).
    assert any(p.startswith("/api/device") for p in paths)
```

Create `backend/tests/test_engines_lock.py`:

```python
"""AppState.create_engine_for_device guards check->await->assign with _engines_lock
so two concurrent calls for the same udid create exactly one engine."""

import asyncio
import pytest


@pytest.mark.asyncio
async def test_concurrent_create_engine_creates_one(monkeypatch):
    from main import app_state

    # Fresh state.
    app_state.simulation_engines.clear()
    app_state._primary_udid = None

    created = []

    class FakeLocService:
        async def set(self, lat, lng):
            pass

    async def slow_get_location_service(udid):
        await asyncio.sleep(0)  # yield, widening the race window
        return FakeLocService()

    monkeypatch.setattr(
        app_state.device_manager, "get_location_service", slow_get_location_service
    )

    udid = "RACE-UDID"
    await asyncio.gather(
        app_state.create_engine_for_device(udid),
        app_state.create_engine_for_device(udid),
    )
    assert list(app_state.simulation_engines.keys()).count(udid) == 1

    # cleanup
    app_state.simulation_engines.clear()
    app_state._primary_udid = None
```

Run; both fail (modules / lock missing):

```bash
cd backend && .venv/bin/python -m pytest tests/test_bootstrap_container.py tests/test_engines_lock.py -q
```

Expected: `ModuleNotFoundError: No module named 'bootstrap'` and (for the lock test)
either a failure or flake — red.

#### Step 6.2 — Implement `MonotonicClock` + `Container`

Create `backend/bootstrap/__init__.py` (empty) and `backend/bootstrap/container.py`:

```python
"""Composition root. Builds the wired object graph for the app."""

from __future__ import annotations

import asyncio
import time


class MonotonicClock:
    """Callable returning a monotonic float — the production clock seam."""

    def __call__(self) -> float:
        return time.monotonic()


class Container:
    def __init__(self) -> None:
        from infra.events.ws_event_publisher import WsEventPublisher
        from infra.device.wifi_tunnel import WifiTunnelRegistry
        from core.device_manager import DeviceManager

        self.clock = MonotonicClock()
        self.event_publisher = WsEventPublisher()
        self.tunnel_registry = WifiTunnelRegistry()
        self.device_manager = DeviceManager(
            event_publisher=self.event_publisher,
            tunnel_registry=self.tunnel_registry,
        )
        # Guards create_engine_for_device's check->await->assign and the
        # watchdog pop/promote (used via app_state in this phase).
        self._engines_lock = asyncio.Lock()

    def engine_factory(self, location_service, event_callback=None):
        from core.simulation_engine import SimulationEngine

        return SimulationEngine(location_service, event_callback)
```

> **Repos / geocoder note:** the contract lists "repos, geocoder" on `Container`. The
> current `AppState` builds `BookmarkManager`/`RouteManager` lazily in `load_state()`
> and the geocoder lives in the geocode router. Pulling those into `Container` now would
> require threading them back through `AppState`/routers — a larger refactor than this
> commit should attempt. **Deferred to a later phase**; the `Container` exposes
> `device_manager`, `event_publisher`, `tunnel_registry`, `engine_factory`, `clock`,
> `_engines_lock` here. Recorded in `gaps`.

#### Step 6.3 — Implement `create_app` (lifespan order + CORS + CSP)

Create `backend/bootstrap/app.py`:

```python
"""create_app() — FastAPI factory with ordered lifespan and security middleware."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from bootstrap.container import Container


# Allowlist: desktop Electron polls 127.0.0.1; the /phone LAN page is served
# same-origin. We reflect explicit local origins instead of wildcard-with-credentials.
ALLOWED_ORIGINS = [
    "http://127.0.0.1:8777",
    "http://localhost:8777",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]

CSP_VALUE = (
    "default-src 'self'; "
    "img-src 'self' data: https:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; "
    "connect-src 'self' ws: wss:"
)


class CspMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CSP_VALUE)
        return response


def create_app() -> FastAPI:
    container = Container()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 1. ensure_dirs FIRST
        from config import DATA_DIR
        DATA_DIR.mkdir(exist_ok=True)
        # 2. wire (load persisted state, build managers, connect devices)
        from main import app_state
        await app_state.load_state()
        # ... (device discovery/connect exactly as today's lifespan does) ...
        # 3. watchdog LAST
        from main import _usbmux_presence_watchdog
        import asyncio
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(CspMiddleware)

    # Mount routers in the SAME order as main.py (970-979).
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

    return app
```

> **Lifespan honesty / gap.** Today's `main.py` lifespan (line 786) does darwin
> tunnel-helper connect/migrate, full device discovery+connect, bookmark/route file
> watchers, and a detailed shutdown. Re-implementing all of it verbatim inside
> `create_app` is large and risky. For THIS commit, `create_app`'s lifespan covers the
> **ordering contract** (ensure_dirs → wire → watchdog-last) by delegating to the
> existing `app_state.load_state()` and `_usbmux_presence_watchdog`; the darwin
> helper-connect / file-watcher blocks remain driven by `main.py`'s own `app`. To avoid
> running two divergent lifespans, **`main.py` keeps its own `app` as the process entry
> (`uvicorn.run("main:app")`)**, and `create_app` is used by tests + the future cutover.
> The full lifespan port is a dedicated follow-up. Flagged in `gaps`.

> **CORS/CSP behavioral change — call out loudly.** Switching `allow_origins=["*"]`
> (today, main.py:952, with `allow_credentials=True`) to an explicit allowlist IS an
> observable change. It only affects `create_app`'s app, not `main:app`, so the 374
> existing tests (which import `main.app`) are unaffected. If any test asserts CORS on
> `create_app`, account for the allowlist. The CSP header is additive (`setdefault`), so
> it never overwrites an existing one.

#### Step 6.4 — `api/deps.py` providers

Create `backend/api/deps.py`:

```python
"""FastAPI dependency providers — one per service, reading app.state.container."""

from __future__ import annotations

from fastapi import Request


def get_container(request: Request):
    return request.app.state.container


def get_device_manager(request: Request):
    return request.app.state.container.device_manager


def get_device_service(request: Request):
    # DeviceService is added in Task 7; until then this provider is unused.
    return request.app.state.container.device_service
```

> `get_device_service` references `container.device_service`, which Task 7 adds. To keep
> this commit's imports valid without a partial `DeviceService`, give `Container` a
> placeholder property that raises a clear error until Task 7 fills it:
>
> ```python
> # in Container.__init__, add nothing; instead add a property:
> @property
> def device_service(self):
>     raise NotImplementedError("DeviceService wired in Task 7")
> ```
>
> This keeps `api/deps.py` importable now and makes the Task-7 gap explicit at runtime.

#### Step 6.5 — Add `_engines_lock` to `AppState` and guard the two race windows

In `backend/main.py`:

1. In `AppState.__init__`, add:
   ```python
   self._engines_lock = asyncio.Lock()
   ```
   (`asyncio` is already imported at module top.)

2. Wrap `create_engine_for_device` (line 329) so the check→await→assign is atomic:
   ```python
   async def create_engine_for_device(self, udid: str):
       async with self._engines_lock:
           if udid in self.simulation_engines:
               logger.debug("Simulation engine already exists for %s; preserving current_position", udid)
               return
           from core.simulation_engine import SimulationEngine
           from api.websocket import broadcast

           loc_service = await self.device_manager.get_location_service(udid)

           async def event_callback(event_type: str, data: dict):
               if isinstance(data, dict) and "udid" not in data:
                   data = {**data, "udid": udid}
               await broadcast(event_type, data)
               if event_type == "position_update" and "lat" in data:
                   self.update_last_position(data["lat"], data["lng"])

           engine = SimulationEngine(loc_service, event_callback)
           self.simulation_engines[udid] = engine
           if self._primary_udid is None:
               self._primary_udid = udid
           # ... rest of body (reconnect_manager assignment, logging) ...
   ```

   > **Deadlock check:** `get_location_service` must NOT call back into
   > `create_engine_for_device` (it doesn't — it's a `DeviceManager` method). Holding
   > `_engines_lock` across the `await` is the whole point (it serializes the race). The
   > lock is distinct from `device_manager._lock`, so no nesting-order conflict.

3. In the **watchdog pop/promote** logic (the watchdog mutates `simulation_engines.pop`
   + `_primary_udid` reassignment, r-wiring lines ~638-650), wrap the pop+promote in the
   same lock:
   ```python
   async with app_state._engines_lock:
       app_state.simulation_engines.pop(dead_udid, None)
       # ... _primary_udid promotion to a surviving engine ...
   ```
   (Apply at each watchdog site that pops an engine and reassigns `_primary_udid`.)

#### Step 6.6 — Run it; watch it pass

```bash
cd backend && .venv/bin/python -m pytest tests/test_bootstrap_container.py tests/test_engines_lock.py -q
cd backend && .venv/bin/python -m pytest -q
```

Expected: targeted all-green; full suite `374 + (5 container + 1 lock) = 380 passed`.

#### Step 6.7 — Commit

```bash
cd backend && git add bootstrap/__init__.py bootstrap/container.py bootstrap/app.py \
  api/deps.py main.py tests/test_bootstrap_container.py tests/test_engines_lock.py
git commit -m "feat(bootstrap): Container + create_app + deps; _engines_lock guard

Container wires publisher+tunnel_registry into DeviceManager, holds clock and
_engines_lock. create_app sets app.state.container, mounts routers in main.py
order, lifespan = ensure_dirs->wire->watchdog-last, CORS allowlist + CSP.
AppState.create_engine_for_device + watchdog pop/promote now hold _engines_lock.
main:app remains the process entry (full lifespan port deferred).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

---

### Task 7 — Lift connect/disconnect/forget/repair orchestration into `services/device_service.py`

**Goal:** Create `DeviceService` with `connect`/`disconnect`/`forget`/`repair`
use-cases, constructor-injected `device_manager` + `tunnel_registry` + engine registry.
Make `api/device.py` handlers thin via `Depends(get_device_service)`, removing their
`from main import app_state` for these four paths. Wire `Container.device_service`.

> **Scope honesty.** The forget handler (`api/device.py:1540-1613`) is dense (pair lock,
> tunnel teardown, record deletes, sticky mark, broadcast). Moving the FULL body is
> high-risk. **This task moves the orchestration that's cleanly liftable** —
> `connect` and `forget` first (they have the clearest seams and existing tests), and
> leaves `disconnect`/`repair` as thin delegators that the service also exposes. The
> existing `test_device_forget_endpoint.py` (migrated in Task 3) is the regression gate.

#### Step 7.1 — Failing test for `DeviceService`

Create `backend/tests/test_device_service.py`:

```python
"""DeviceService.connect orchestrates dm.connect + engine creation; forget runs
the unpair/teardown/record-delete/sticky/broadcast sequence."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from services.device_service import DeviceService


@pytest.mark.asyncio
async def test_connect_calls_dm_and_engine_factory():
    dm = MagicMock()
    dm._connections = {}
    dm.connect = AsyncMock()
    engine_registry = MagicMock()
    engine_registry.create_engine_for_device = AsyncMock()

    svc = DeviceService(
        device_manager=dm,
        tunnel_registry=MagicMock(),
        engine_registry=engine_registry,
    )
    await svc.connect("U1")

    dm.connect.assert_awaited_once_with("U1")
    engine_registry.create_engine_for_device.assert_awaited_once_with("U1")
```

Run; fails (module missing):

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_service.py -q
```

Expected: `ModuleNotFoundError: No module named 'services.device_service'`.

#### Step 7.2 — Implement `DeviceService`

Create `backend/services/device_service.py`:

```python
"""DeviceService — connect/disconnect/forget/repair use-cases.

Constructor-injected device_manager + tunnel_registry + engine_registry
(the object exposing create_engine_for_device, i.e. AppState today / Container
later). Keeps thick device internals (pymobiledevice3/usbmux/SIP) behind the
existing narrow helpers; this service only orchestrates ordering.
"""

from __future__ import annotations


class DeviceService:
    def __init__(self, device_manager, tunnel_registry, engine_registry) -> None:
        self._dm = device_manager
        self._tunnels = tunnel_registry
        self._engines = engine_registry

    async def connect(self, udid: str) -> None:
        await self._dm.connect(udid)
        await self._engines.create_engine_for_device(udid)

    async def disconnect(self, udid: str) -> None:
        await self._dm.disconnect(udid)

    async def repair(self, udid: str) -> None:
        # Re-trust path: clear the sticky-denied flag (matches wifi_repair:242).
        self._dm.clear_user_denied(udid)
```

> **Forget stays in the handler for now.** The forget sequence's pair-lock ordering
> (`acquire_pair_lock(udid)` wrapping `_tunnels_lock`) and the SIP record-delete
> async/sync split are too coupled to `api/device.py`'s module-level helpers
> (`_cleanup_wifi_connection_for`, `_tear_down_tunnel`) to lift cleanly in this commit
> without moving those helpers too. **`DeviceService.forget` is added in a follow-up**;
> this task lifts `connect`/`disconnect`/`repair`. Flagged in `gaps`. The forget test
> already passes (Task 3) and is unaffected.

#### Step 7.3 — Wire `Container.device_service` and thin the connect handler

1. In `bootstrap/container.py`, replace the placeholder property with a real build:
   ```python
   # in Container.__init__, AFTER device_manager is built:
   from services.device_service import DeviceService
   from main import app_state  # engine_registry = AppState (holds create_engine_for_device)
   self.device_service = DeviceService(
       device_manager=self.device_manager,
       tunnel_registry=self.tunnel_registry,
       engine_registry=app_state,
   )
   ```

   > **Cycle caution:** importing `main` inside `Container.__init__` is the same
   > function-body-import pattern used elsewhere; it's safe because `Container` is
   > constructed at `create_app()` time, well after `main` is imported. If a test
   > constructs `Container()` before `main` is importable, the import still resolves
   > (main is a top-level module). Keep the import inside `__init__`, not at module top.

2. In `api/device.py`, thin `connect_device` (line 1479) to use the service via
   `Depends`. Add at top of `api/device.py`:
   ```python
   from fastapi import Depends
   from api.deps import get_device_service
   ```
   Rewrite the handler signature + body core:
   ```python
   @router.post("/{udid}/connect")
   async def connect_device(udid: str, service=Depends(get_device_service)):
       from core.device_manager import UnsupportedIosVersionError
       dm = service._dm
       if udid not in dm._connections and len(dm._connections) >= MAX_DEVICES:
           raise HTTPException(status_code=409, detail={"code": "max_devices_reached", "message": f"已連接最多 {MAX_DEVICES} 台裝置"})
       try:
           await service.connect(udid)
           try:
               from api.websocket import broadcast
               devs = await dm.discover_devices()
               info = next((d for d in devs if d.udid == udid), None)
               await broadcast("device_connected", {"udid": udid, "name": ..., "ios_version": ..., "connection_type": info.connection_type if info else "USB"})
           except Exception:
               pass
           return {"status": "connected", "udid": udid}
       except UnsupportedIosVersionError as e:
           raise HTTPException(status_code=400, detail=str(e))
       except Exception as e:
           raise HTTPException(status_code=500, detail=str(e))
   ```
   > Preserve the EXACT `name`/`ios_version` expressions from the current handler
   > (shown as `...` in r-wiring) — copy them verbatim from the live code; do not
   > invent. The `device_connected` payload must stay deep-equal.
   >
   > **Note:** `connect_device` is reached via `main:app`, whose routers are the SAME
   > router objects `create_app` mounts. But `Depends(get_device_service)` reads
   > `request.app.state.container`, which `main:app` does NOT set today. **Fix:** in
   > `main.py`, after `app = FastAPI(...)` (line 948), add
   > `app.state.container = Container()` so the dependency resolves under `main:app` too.
   > Import `Container` at the top of `main.py`:
   > `from bootstrap.container import Container`. This is the minimal bridge so existing
   > tests (which hit `main:app`) get a container.

#### Step 7.4 — Run it; watch it pass

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_service.py -q
cd backend && .venv/bin/python -m pytest -q
```

Expected: targeted `1 passed`; full suite `380 + 1 = 381 passed`. The connect-path and
forget-path tests under `tests/test_device_*` must remain green (they exercise
`main:app`, now container-backed).

Confirm `app_state` is no longer imported by the connect handler path:

```bash
cd backend && grep -n "from main import app_state" api/device.py
```

Expected: the `connect_device` handler no longer contains `from main import app_state`
(other handlers in the file may still — those are out of this task's scope; forget/repair
helpers move in the follow-up). The count must be strictly lower than before.

#### Step 7.5 — Commit

```bash
cd backend && git add services/device_service.py bootstrap/container.py api/device.py \
  api/deps.py main.py tests/test_device_service.py
git commit -m "refactor(device): DeviceService use-cases; connect handler via Depends

DeviceService(connect/disconnect/repair) injected with dm+tunnel_registry+
engine_registry. connect_device handler is thin via Depends(get_device_service),
dropping its from-main-import-app_state. main:app gains app.state.container so
the dependency resolves. forget orchestration lift deferred (helpers coupled).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

#### Step 7.6 — MANUAL SMOKE GATE (required before "done")

- [ ] Real iPhone: connect via the UI; confirm `device_connected` frame deep-equal to
      P0 recording; confirm the sim engine is created (joystick/teleport works).
- [ ] Forget a device; confirm the forget flow (unpair, teardown, `device_disconnected`
      with `remaining_count`) still works end-to-end.

---

### Task 8 — Flip the import-linter `no core → api` contract to ENFORCED

**Goal:** Turn the import-linter contract forbidding `core → api` (whole `api` package)
from informational to **enforced**, and prove `device_manager.py` no longer imports
`from api.`.

> **Survey first (CLAUDE.md rule).** Confirm whether an import-linter config already
> exists before adding one:
> ```bash
> cd backend && ls .importlinter setup.cfg pyproject.toml 2>/dev/null; \
>   grep -rl "importlinter\|import-linter\|importlinter:contract" . 2>/dev/null | grep -v .venv | head
> ```
> If a config exists, EXTEND it (flip `weak`/disabled → enforced). If none exists,
> create `.importlinter` as below. import-linter is a dev dependency — if it's absent
> from `requirements-dev.txt`, adding it is a **new-dependency decision** requiring
> Ravi's approval (note it; do not add silently).

#### Step 8.1 — Validation test FIRST: grep must return zero

The primary acceptance is a grep, codified as a test so it stays enforced:

Create `backend/tests/test_no_core_to_api_imports.py`:

```python
"""core/device_manager.py must not import from the api package (cycle broken)."""

import pathlib
import re


def test_device_manager_has_no_api_imports():
    src = pathlib.Path(__file__).parent.parent / "core" / "device_manager.py"
    text = src.read_text(encoding="utf-8")
    # Both 'from api.x import y' and 'import api.x'
    offenders = re.findall(r"^\s*(?:from\s+api\.|import\s+api\.)", text, re.MULTILINE)
    assert offenders == [], f"device_manager.py still imports api: {offenders}"
```

Run it:

```bash
cd backend && .venv/bin/python -m pytest tests/test_no_core_to_api_imports.py -q
```

Expected outcome depends on Tasks 3–7: the two `_tunnels` edges (Task 4) and any
`api.websocket` import in `device_manager` (Task 3) are gone. If this passes already,
the test is the regression guard. If it FAILS, there is a residual `from api.` import in
`device_manager.py` — fix it (route through `self._events` / `self._tunnels`) before
proceeding. Grep to locate:

```bash
cd backend && grep -nE "from api\.|import api\." core/device_manager.py
```

Expected after Tasks 3–4: **0 lines**.

#### Step 8.2 — Add/flip the import-linter contract

Create (or extend) `backend/.importlinter`:

```ini
[importlinter]
root_packages =
    core
    api
    domain
    infra
    services
    bootstrap

[importlinter:contract:no-core-to-api]
name = core must not import api
type = forbidden
source_modules =
    core
forbidden_modules =
    api
```

> The contract is `type = forbidden`, `source_modules = core`, `forbidden_modules = api`
> — the WHOLE `api` package, ENFORCED (import-linter contracts are pass/fail by default;
> there is no "weak" mode to flip — making it a real contract IS the enforcement).

#### Step 8.3 — Run the linter; watch it pass

If import-linter is available in the venv:

```bash
cd backend && .venv/bin/python -m importlinter.cli.main lint --config .importlinter
```

Expected: `Contracts: 1 kept, 0 broken.`

If import-linter is NOT installed (and adding it is pending Ravi's approval), the grep
test (`test_no_core_to_api_imports.py`) is the enforcement floor and MUST pass:

```bash
cd backend && .venv/bin/python -m pytest tests/test_no_core_to_api_imports.py -q
```

Expected: `1 passed`.

Full suite:

```bash
cd backend && .venv/bin/python -m pytest -q
```

Expected: `381 + 1 = 382 passed`.

#### Step 8.4 — Commit

```bash
cd backend && git add .importlinter tests/test_no_core_to_api_imports.py
git commit -m "chore(arch): enforce no core->api imports (import-linter + grep guard)

Forbidden-contract on the whole api package; regression test asserts
device_manager.py has zero 'from api.' / 'import api.' lines. Cycle broken.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"
```

#### Step 8.5 — Final phase verification

```bash
cd backend && .venv/bin/python -m pytest -q
cd backend && grep -nE "from api\.|import api\." core/device_manager.py | wc -l   # must print 0
```

Expected: full suite green (`382 passed`); grep count `0`.

---

### Phase 1 exit checklist

- [ ] All 8 commits landed; each independently revertable.
- [ ] Full backend suite green after EVERY commit (352 baseline + new tests).
- [ ] `grep -nE 'from api\.|import api\.' core/device_manager.py` → `0`.
- [ ] All WS payloads (4 DDI events, `device_connected`, `device_disconnected`/forget,
      `position_update`) deep-equal vs the P0 recordings.
- [ ] **Manual hardware smoke gates** (Tasks 3, 4, 5, 7) all ticked: USB connect, WiFi
      tunnel restart, route-sim speedometer, forget end-to-end.
- [ ] Deferred items recorded for the next phase: full `main.py`/`AppState` shrink,
      `Container` repos+geocoder, full lifespan port into `create_app`, `DeviceService.forget`,
      `DevicePort.clear` real binding.
## Phase 1 (FRONTEND) — typed WS contract seam + WsRouter preserving multi-subscriber fan-out

> Runs AFTER the backend inversion (Phase 0/0a) is green and hardware-smoked.
> This is an INDEPENDENT, separately-revertable commit per task. No backend
> behavior changes here. The wire payload shape is fixed by the backend:
> every WS message is `{"type": <event_type>, "data": <dict>}` (see
> `backend/api/websocket.py` `broadcast`); the frontend `JSON.parse`s that and
> dispatches on `msg.type`.
>
> **HARD CONSTRAINTS for this whole phase**
> - The WS fan-out is SYNCHRONOUS, per-subscriber `try/catch`-wrapped, and
>   delivers EVERY message to EVERY subscriber in insertion order
>   (`useWebSocket.ts:57-68`). A throwing subscriber must NOT stop delivery to
>   others, and malformed JSON must be silently ignored. Preserve this exactly.
>   Do NOT collapse to a single-owner dispatcher.
> - Two hooks consume the SAME `device_disconnected` message with DIVERGENT key
>   expectations and BOTH must keep firing:
>   - `useDevice` reads `data.udid` (string) AND `data.udids` (array); empty-both
>     path clears all, array path marks specific udids, then ALWAYS re-fetches
>     via `listDevices()` to promote a survivor.
>   - `useSimulation` reads `data.udid` (runtimes map → `state:'disconnected'`)
>     AND `data.remaining_count` (number; banner shown ONLY when
>     `remaining_count === 0`; absent → defaults to `0` → banner shows).
>   Any test message must include whichever keys the assertion targets.
> - `vitest` / `jsdom` / `happy-dom` are NEW devDependencies. Per AGENTS.md
>   "No new dependencies without discussion" — Task 9 assumes that approval has
>   already been granted as part of accepting this plan. If not yet approved,
>   STOP and get sign-off before running the `npm install` in Task 9 Step 0.
> - Commands: `cd frontend && npx vitest run` (Vitest, one-shot),
>   `cd frontend && npx tsc --noEmit` (types). Personal repo → direct commits to
>   main; git identity is auto-set by includeIf — NEVER pass `-c user.email=...`.

---

### Task 9 — `contract/` typed WS events + single-origin config (kills the 3× hardcoded `8777`)

**Goal:** introduce `frontend/src/adapters/config.ts` as the ONE origin source, a
typed `contract/wsEvents.ts`, and `contract/endpoints.ts` derived from
`config.ts`. Repoint the three hardcoded `127.0.0.1:8777` literals
(`services/api.ts:1`, `hooks/useWebSocket.ts:8`, `components/PhoneControl.tsx:24`)
at the new constants. One commit.

> Fact check (verified): `grep -rn "8777" frontend/src` returns exactly three
> source literals — `services/api.ts:1` (`const API = 'http://127.0.0.1:8777'`),
> `hooks/useWebSocket.ts:8` (`const WS_URL = 'ws://127.0.0.1:8777/ws/status'`),
> and `components/PhoneControl.tsx:24` (`const API = 'http://127.0.0.1:8777'`).
> `frontend/electron/main.js:355` (`http://127.0.0.1:8777/docs`) is Electron
> main-process code, OUTSIDE `src/`, and is left untouched.

#### Step 0 — install Vitest + jsdom (run ONCE for the whole phase)

```bash
cd frontend && npm install -D vitest@^2 jsdom@^25
```

Add a `test` script and a Vitest config. Create `frontend/vitest.config.ts`:

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
  },
})
```

Add to `frontend/package.json` `scripts`:

```json
    "test": "vitest run",
```

Verify the runner boots (no tests yet → exit 0 with "No test files found"):

```bash
cd frontend && npx vitest run
```

Expected: a "No test files found" notice and exit code 0.

#### Step 1 — write the failing test

Create `frontend/src/adapters/config.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { ORIGIN_HOST, ORIGIN_PORT, HTTP_ORIGIN, WS_ORIGIN } from './config'

describe('config single origin', () => {
  it('exposes the canonical host and port', () => {
    expect(ORIGIN_HOST).toBe('127.0.0.1')
    expect(ORIGIN_PORT).toBe(8777)
  })

  it('derives http and ws origins from host+port (no second hardcode)', () => {
    expect(HTTP_ORIGIN).toBe('http://127.0.0.1:8777')
    expect(WS_ORIGIN).toBe('ws://127.0.0.1:8777')
  })
})
```

Create `frontend/src/contract/endpoints.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { BASE_URL, WS_URL } from './endpoints'
import { HTTP_ORIGIN, WS_ORIGIN } from '../adapters/config'

describe('endpoints derive from config only', () => {
  it('BASE_URL is the http origin', () => {
    expect(BASE_URL).toBe(HTTP_ORIGIN)
  })

  it('WS_URL is the ws origin + /ws/status path', () => {
    expect(WS_URL).toBe(`${WS_ORIGIN}/ws/status`)
    expect(WS_URL).toBe('ws://127.0.0.1:8777/ws/status')
  })
})
```

#### Step 2 — run it, watch it fail

```bash
cd frontend && npx vitest run src/adapters/config.test.ts src/contract/endpoints.test.ts
```

Expected: FAIL — `Failed to resolve import "./config"` and
`"./endpoints"` (files do not exist yet).

#### Step 3 — minimal implementation

Create `frontend/src/adapters/config.ts`:

```ts
// The ONLY origin source for the renderer. Every base URL / WS URL in the app
// MUST derive from these — do not hardcode 127.0.0.1:8777 anywhere else.
export const ORIGIN_HOST = '127.0.0.1'
export const ORIGIN_PORT = 8777

export const HTTP_ORIGIN = `http://${ORIGIN_HOST}:${ORIGIN_PORT}`
export const WS_ORIGIN = `ws://${ORIGIN_HOST}:${ORIGIN_PORT}`
```

Create `frontend/src/contract/endpoints.ts`:

```ts
import { HTTP_ORIGIN, WS_ORIGIN } from '../adapters/config'

// Derived from adapters/config.ts — the single origin source. Never reintroduce
// a literal host:port here.
export const BASE_URL = HTTP_ORIGIN
export const WS_URL = `${WS_ORIGIN}/ws/status`
```

Create `frontend/src/contract/wsEvents.ts`:

```ts
// Typed view of the WS wire frames. The backend sends {"type", "data"} and the
// renderer flattens to a single object keyed by `type` (see adapters/ws/router).
// WsEvent stays intentionally open (Record<string, unknown>) so unknown event
// types still flow through the router untouched.
export type WsEvent = { type: string } & Record<string, unknown>

// device_disconnected is the ONE message two hooks read with divergent shapes.
// `udid` / `udids` feed useDevice; `remaining_count` feeds the useSimulation
// banner (absent → treated as 0 → banner shows). All payload keys optional
// because the backend omits absent keys (exclude_unset/exclude_none).
export interface DeviceDisconnectedEvent {
  type: 'device_disconnected'
  udid?: string
  udids?: string[]
  reason?: string
  remaining_count?: number
}
```

Now repoint the three hardcoded literals.

`frontend/src/services/api.ts:1` — replace
`const API = 'http://127.0.0.1:8777'` with:

```ts
import { BASE_URL } from '../contract/endpoints'
const API = BASE_URL
```

`frontend/src/hooks/useWebSocket.ts:8` — replace
`const WS_URL = 'ws://127.0.0.1:8777/ws/status'` with an import at the top of the
file and delete the local const:

```ts
import { WS_URL } from '../contract/endpoints'
```

(Keep `RECONNECT_INTERVAL` / `MAX_RECONNECT_INTERVAL` as-is; only the `WS_URL`
const line is removed.)

`frontend/src/components/PhoneControl.tsx:24` — replace
`const API = 'http://127.0.0.1:8777';` with:

```ts
import { BASE_URL } from '../contract/endpoints';
const API = BASE_URL;
```

> Note: keep PhoneControl's existing trailing semicolons (that file uses them);
> match the surrounding style. The import path is `'../contract/endpoints'`
> because PhoneControl lives in `components/`.

#### Step 4 — run it, watch it pass + types + no stray literals

```bash
cd frontend && npx vitest run src/adapters/config.test.ts src/contract/endpoints.test.ts
cd frontend && npx tsc --noEmit
cd frontend && grep -rn "8777" src/   # expect: ONLY adapters/config.ts:ORIGIN_PORT = 8777
```

Expected: both test files PASS; `tsc` clean (exit 0); the `grep` prints exactly
ONE line — `src/adapters/config.ts:...ORIGIN_PORT = 8777`. If any of
api.ts / useWebSocket.ts / PhoneControl.tsx still appear, you missed a repoint.

#### Step 5 — commit

```bash
cd frontend && git add src/adapters/config.ts src/adapters/config.test.ts \
  src/contract/wsEvents.ts src/contract/endpoints.ts src/contract/endpoints.test.ts \
  src/services/api.ts src/hooks/useWebSocket.ts src/components/PhoneControl.tsx \
  package.json package-lock.json vitest.config.ts
git commit -m "$(cat <<'EOF'
feat(frontend): single-origin config + typed WS contract seam

Introduce adapters/config.ts as the ONLY host:port source; derive
contract/endpoints.ts (BASE_URL/WS_URL) and add contract/wsEvents.ts
(WsEvent, DeviceDisconnectedEvent). Repoint the 3 hardcoded 127.0.0.1:8777
literals (api.ts, useWebSocket.ts, PhoneControl.tsx) at the new constants.
Add Vitest + jsdom test harness (no prior frontend test infra).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
```

---

### Task 10 — `adapters/ws/router.ts`: `WsRouter` over `Map<type, Set<handler>>`, fan-out PROVEN

**Goal:** a pure dispatch layer matching the locked `WsRouter` port. Dispatch
keys off `e.type`, fans out to ALL subscribers of that type via `forEach` with
per-handler `try/catch`. The defining test PROVES one `device_disconnected`
fires TWO distinct subscribers (the useDevice-shaped handler AND the
useSimulation-shaped handler). One commit.

> The router is the typed replacement for the inline `subscribersRef` Set in
> `useWebSocket.ts:57-68`. It keeps the SAME semantics: synchronous fan-out,
> per-handler isolation, insertion order. The difference: it indexes by `type`
> so each consumer subscribes only to the types it cares about — but a single
> message type still fans out to every handler registered for that type.

#### Step 1 — write the failing test

Create `frontend/src/ports/WsRouter.ts` FIRST (interface only — it is a pure
type, no logic, locked by contract):

```ts
import type { WsEvent } from '../contract/wsEvents'

export interface WsRouter {
  subscribe(type: string, handler: (e: WsEvent) => void): () => void
}
```

Create `frontend/src/adapters/ws/router.test.ts`:

```ts
import { describe, it, expect, vi } from 'vitest'
import { createWsRouter } from './router'
import type { WsEvent } from '../../contract/wsEvents'

describe('createWsRouter', () => {
  it('dispatches a message to ALL subscribers of its type (fan-out preserved)', () => {
    const router = createWsRouter()
    // Stand-ins for the two real consumers that both read device_disconnected.
    const deviceHandler = vi.fn()       // useDevice-shaped: reads udid / udids
    const simulationHandler = vi.fn()   // useSimulation-shaped: reads remaining_count

    router.subscribe('device_disconnected', deviceHandler)
    router.subscribe('device_disconnected', simulationHandler)

    const evt: WsEvent = {
      type: 'device_disconnected',
      udid: 'UDID-A',
      udids: ['UDID-A'],
      reason: 'forgotten',
      remaining_count: 1,
    }
    router.dispatch(evt)

    expect(deviceHandler).toHaveBeenCalledTimes(1)
    expect(deviceHandler).toHaveBeenCalledWith(evt)
    expect(simulationHandler).toHaveBeenCalledTimes(1)
    expect(simulationHandler).toHaveBeenCalledWith(evt)
  })

  it('only delivers to subscribers of the matching type', () => {
    const router = createWsRouter()
    const onDisc = vi.fn()
    const onPos = vi.fn()
    router.subscribe('device_disconnected', onDisc)
    router.subscribe('position_update', onPos)

    router.dispatch({ type: 'position_update', lat: 1, lng: 2 })

    expect(onPos).toHaveBeenCalledTimes(1)
    expect(onDisc).not.toHaveBeenCalled()
  })

  it('isolates a throwing handler — others still fire (per-handler try/catch)', () => {
    const router = createWsRouter()
    const boom = vi.fn(() => { throw new Error('subscriber blew up') })
    const ok = vi.fn()
    router.subscribe('state_change', boom)
    router.subscribe('state_change', ok)

    expect(() => router.dispatch({ type: 'state_change', state: 'idle' })).not.toThrow()
    expect(boom).toHaveBeenCalledTimes(1)
    expect(ok).toHaveBeenCalledTimes(1)
  })

  it('unsubscribe stops further delivery to that handler only', () => {
    const router = createWsRouter()
    const a = vi.fn()
    const b = vi.fn()
    const unsubA = router.subscribe('device_connected', a)
    router.subscribe('device_connected', b)

    unsubA()
    router.dispatch({ type: 'device_connected', udid: 'X' })

    expect(a).not.toHaveBeenCalled()
    expect(b).toHaveBeenCalledTimes(1)
  })

  it('dropping the last subscriber of a type leaves no empty bucket leak', () => {
    const router = createWsRouter()
    const h = vi.fn()
    const unsub = router.subscribe('tunnel_recovered', h)
    unsub()
    // Dispatching to a now-empty type must be a no-op, not a crash.
    expect(() => router.dispatch({ type: 'tunnel_recovered', udid: 'X' })).not.toThrow()
    expect(h).not.toHaveBeenCalled()
  })

  it('an unknown type with no subscribers is a silent no-op', () => {
    const router = createWsRouter()
    expect(() => router.dispatch({ type: 'never_registered' })).not.toThrow()
  })
})
```

#### Step 2 — run it, watch it fail

```bash
cd frontend && npx vitest run src/adapters/ws/router.test.ts
```

Expected: FAIL — `Failed to resolve import "./router"` (file does not exist).

#### Step 3 — minimal implementation

Create `frontend/src/adapters/ws/router.ts`:

```ts
import type { WsEvent } from '../../contract/wsEvents'
import type { WsRouter } from '../../ports/WsRouter'

type Handler = (e: WsEvent) => void

// Concrete WsRouter: a Map<type, Set<handler>>. dispatch() fans a single event
// out to EVERY handler registered for e.type, in insertion order, each wrapped
// in its own try/catch so one throwing subscriber cannot starve the others or
// kill the stream. This preserves the multi-subscriber fan-out semantics of the
// old useWebSocket subscribersRef Set — it is NOT a single-owner dispatcher.
export interface WsRouterImpl extends WsRouter {
  dispatch(e: WsEvent): void
}

export function createWsRouter(): WsRouterImpl {
  const buckets = new Map<string, Set<Handler>>()

  function subscribe(type: string, handler: Handler): () => void {
    let set = buckets.get(type)
    if (!set) {
      set = new Set<Handler>()
      buckets.set(type, set)
    }
    set.add(handler)
    return () => {
      const s = buckets.get(type)
      if (!s) return
      s.delete(handler)
      if (s.size === 0) buckets.delete(type)
    }
  }

  function dispatch(e: WsEvent): void {
    const set = buckets.get(e.type)
    if (!set) return
    // Snapshot so a handler that (un)subscribes during dispatch can't mutate the
    // set we're iterating.
    for (const handler of [...set]) {
      try {
        handler(e)
      } catch {
        // A subscriber's error must not kill the stream or block other handlers.
      }
    }
  }

  return { subscribe, dispatch }
}
```

#### Step 4 — run it, watch it pass

```bash
cd frontend && npx vitest run src/adapters/ws/router.test.ts
cd frontend && npx tsc --noEmit
```

Expected: all 6 cases PASS; `tsc` clean. The first case is the load-bearing
proof: ONE `device_disconnected` dispatch → BOTH `deviceHandler` and
`simulationHandler` called exactly once with the identical event object.

#### Step 5 — commit

```bash
cd frontend && git add src/ports/WsRouter.ts src/adapters/ws/router.ts \
  src/adapters/ws/router.test.ts
git commit -m "$(cat <<'EOF'
feat(frontend): WsRouter — typed Map<type,Set> fan-out dispatcher

Map<type, Set<handler>> with per-handler try/catch, snapshot iteration,
insertion-order delivery, and empty-bucket cleanup on last unsubscribe.
Test proves one device_disconnected fires BOTH the useDevice-shaped and
useSimulation-shaped subscribers (fan-out preserved, not single-owner).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
```

---

### Task 11 — `ServicesContext` (api + ws) + `useServices`; feed the live socket into `WsRouter`

**Goal:** a React context exposing `{ api, ws }` where `ws` is a `WsRouter`. A
small adapter wires the existing `useWebSocket()` socket's raw fan-out into
`router.dispatch`, so a real WS frame `{type,data}` becomes a flat
`WsEvent = { type, ...data }` delivered to typed subscribers. One commit.

> `useWebSocket` already JSON-parses each frame and fans out `WsMessage =
> { type, data }` to its Set (`useWebSocket.ts:57-68`). We DON'T rip that out —
> we subscribe ONE adapter to it that flattens `{type, data}` →
> `{ type, ...data }` and calls `router.dispatch`. This keeps the proven
> reconnect/backoff/JSON-guard logic of `useWebSocket` and layers the typed
> router on top.

#### Step 1 — write the failing test

Create `frontend/src/contexts/ServicesContext.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { renderHook } from '@testing-library/react'  // see Step 3 note
import React from 'react'
import { ServicesProvider, useServices } from './ServicesContext'
import { createWsRouter } from '../adapters/ws/router'

describe('useServices', () => {
  it('exposes the injected api and ws', () => {
    const ws = createWsRouter()
    const api = { listDevices: vi.fn() }
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <ServicesProvider value={{ api: api as any, ws }}>{children}</ServicesProvider>
    )
    const { result } = renderHook(() => useServices(), { wrapper })
    expect(result.current.api).toBe(api)
    expect(result.current.ws).toBe(ws)
  })

  it('throws if used outside the provider', () => {
    expect(() => renderHook(() => useServices())).toThrow(/ServicesProvider/)
  })
})
```

> Dependency note: `renderHook` lives in `@testing-library/react`, which is NOT
> yet installed (see r-frontend: no testing-library). If approval for it was not
> granted, replace this hook-render test with a non-React unit test that calls
> the context's default-guard directly, OR defer the provider unit test and rely
> on Task 13's Playwright e2e for coverage. The simplest in-scope path: add
> `@testing-library/react@^16` + `@testing-library/dom@^10` as devDeps in Task 9
> Step 0 alongside vitest/jsdom. **GAP:** this devDep was not pre-approved in the
> contract; flag for sign-off before installing.

#### Step 2 — run it, watch it fail

```bash
cd frontend && npx vitest run src/contexts/ServicesContext.test.tsx
```

Expected: FAIL — `Failed to resolve import "./ServicesContext"`.

#### Step 3 — minimal implementation

Define the `ApiGateway` type as the existing api namespace surface (the app
already imports `* as api from './services/api'`). Create
`frontend/src/contract/apiGateway.ts`:

```ts
import * as api from '../services/api'

// The api surface the rest of the app depends on. Using the module's own type
// keeps every existing `api.*` call site valid with zero signature drift.
export type ApiGateway = typeof api
```

Create `frontend/src/contexts/ServicesContext.tsx`:

```tsx
import React, { createContext, useContext } from 'react'
import type { ApiGateway } from '../contract/apiGateway'
import type { WsRouter } from '../ports/WsRouter'

export interface Services {
  api: ApiGateway
  ws: WsRouter
}

const ServicesContext = createContext<Services | null>(null)

export function ServicesProvider(
  { value, children }: { value: Services; children: React.ReactNode },
) {
  return <ServicesContext.Provider value={value}>{children}</ServicesContext.Provider>
}

export function useServices(): Services {
  const ctx = useContext(ServicesContext)
  if (ctx === null) {
    throw new Error('useServices must be used within a ServicesProvider')
  }
  return ctx
}
```

Create the adapter that bridges the live `useWebSocket` socket into a router.
Create `frontend/src/adapters/ws/useWsRouter.ts`:

```ts
import { useEffect, useMemo } from 'react'
import { useWebSocket } from '../../hooks/useWebSocket'
import { createWsRouter } from './router'
import type { WsEvent } from '../../contract/wsEvents'

// Bridges the existing useWebSocket subscribe-fanout onto a typed WsRouter.
// Flattens the wire frame {type, data} into a flat WsEvent {type, ...data} so
// typed subscribers see one object keyed by `type`. Reuses useWebSocket's proven
// reconnect/backoff/JSON-guard; this hook adds the typed routing layer only.
export function useWsRouter() {
  const { subscribe, sendMessage, connected } = useWebSocket()
  const router = useMemo(() => createWsRouter(), [])

  useEffect(() => {
    // subscribe identity is stable (empty-deps useCallback in useWebSocket).
    return subscribe((msg) => {
      const flat: WsEvent = { type: msg.type, ...(msg.data ?? {}) }
      router.dispatch(flat)
    })
  }, [subscribe, router])

  return { router, sendMessage, connected }
}
```

> Why flatten `{type, ...data}`? The current hooks read `msg.data?.udid`,
> `msg.data?.remaining_count`, etc. AFTER migration (Task 12) they will read the
> flattened `e.udid` / `e.remaining_count` directly off the `WsEvent`. The
> backend's `event_callback` already injects `udid` INTO `data`
> (`main.py:351-357`), so `udid` lands at the top level after the spread. This
> matches `DeviceDisconnectedEvent` (Task 9) where `udid`/`udids`/
> `remaining_count` are top-level keys.

#### Step 4 — run it, watch it pass

```bash
cd frontend && npx vitest run src/contexts/ServicesContext.test.tsx
cd frontend && npx tsc --noEmit
```

Expected: both context cases PASS; `tsc` clean.

#### Step 5 — commit

```bash
cd frontend && git add src/contract/apiGateway.ts src/contexts/ServicesContext.tsx \
  src/contexts/ServicesContext.test.tsx src/adapters/ws/useWsRouter.ts \
  package.json package-lock.json
git commit -m "$(cat <<'EOF'
feat(frontend): ServicesContext { api, ws } + useWsRouter bridge

ServicesProvider/useServices expose { api: ApiGateway, ws: WsRouter }.
useWsRouter subscribes one adapter to the live useWebSocket fan-out and
flattens {type,data} -> {type,...data} into router.dispatch, reusing the
existing reconnect/backoff/JSON-guard. No old subscriber removed yet.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
```

---

### Task 12 — migrate every `useWebSocket.subscribe` site onto `WsRouter`, pinned test-first

**Goal:** move all consumers from the raw `ws.subscribe((msg) => switch(msg.type))`
pattern onto typed `ws.subscribe('<type>', handler)` via the router. For EACH
migrated site, write a Vitest test FIRST that pins the EXACT current handler
behavior, watch it pass against the new wiring, THEN delete the old inline
subscription. One commit (the whole migration is atomic so no half-migrated
runtime state ships).

> **Subscriber inventory (verified against the live tree):**
> - `useDevice.ts:43-96` — branches on `device_disconnected` / `device_connected`
>   / `device_reconnected`. Divergent shape: reads `data.udid` + `data.udids`
>   (array) + always re-fetches via `listDevices()`.
> - `useSimulation.ts:276-528` — two-pass: group-mode (keyed by `data.udid`) then
>   the dual-device primary filter `if (primary && msgUdid && msgUdid !== primary)
>   return` then the legacy switch. `device_disconnected` reads
>   `data.remaining_count` for the banner.
> - `App.tsx:207-218` (inline sub #1) — `bookmarks_changed` → `bm.refresh()`+toast;
>   `routes_changed` → `getSavedRoutes()`/`refreshRouteCategories()`+toast.
> - `App.tsx:1264-1304` (inline sub #2) — `goldditto_cycle` only; branches on
>   `data.phase`, drives a `setInterval` countdown.
>
> **CORRECTION to the task brief:** there are NO inline `device_disconnected`
> subscribers in `App.tsx` (`grep` confirms App.tsx handles only
> `bookmarks_changed` / `routes_changed` / `goldditto_cycle`). The
> `device_disconnected` handling lives in the `useDevice` and `useSimulation`
> hooks. This task migrates ALL four subscriber sites; the "two inline App.tsx
> device_disconnected subscribers" in the brief map to the TWO inline App.tsx
> subscribers above (bookmarks/routes + goldditto), plus the two hook subscribers.
>
> **Migration mechanic:** the router delivers a flat `WsEvent` (`{type,...data}`),
> so handlers that read `msg.data?.udid` become `e.udid`, `msg.data?.udids`
> becomes `e.udids`, `msg.data?.remaining_count` becomes `e.remaining_count`, and
> `msg.data?.phase` becomes `e.phase`. PRESERVE the divergent branching verbatim
> (empty-`udids` clears all; array marks specific; `remaining_count` absent →
> banner shows). Change `useDevice(subscribe?: WsSubscribe)` /
> `useSimulation(subscribe?, primaryUdid?)` to accept the `WsRouter` instead, and
> register per-type via `ws.subscribe('device_disconnected', ...)` etc.

#### Step 1 — write the pinning tests FIRST (before deleting anything)

Create `frontend/src/hooks/useDevice.router.test.tsx`. This drives the migrated
hook through a real `createWsRouter` and asserts the exact current behavior
(udids array path marks specific devices; empty path clears all; survivor
promotion via `listDevices`). Mock `services/api`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { createWsRouter } from '../adapters/ws/router'
import { useDevice } from './useDevice'
import * as api from '../services/api'

vi.mock('../services/api')

const DEV = (udid: string, connected: boolean) => ({
  udid, name: udid, ios_version: '17.0', connection_type: 'USB',
  is_connected: connected,
})

beforeEach(() => {
  vi.resetAllMocks()
})

describe('useDevice on WsRouter', () => {
  it('device_disconnected with udids=[A] marks A only and promotes a survivor', async () => {
    // listDevices() resolves with B still alive after A is unplugged.
    vi.mocked(api.listDevices).mockResolvedValue([DEV('A', false), DEV('B', true)])
    const ws = createWsRouter()
    const { result } = renderHook(() => useDevice(ws))

    act(() => {
      ws.dispatch({ type: 'device_disconnected', udid: 'A', udids: ['A'], remaining_count: 1 })
    })

    // The authoritative re-fetch promotes B as the surviving connected device.
    await waitFor(() => {
      expect(result.current.connectedDevice?.udid).toBe('B')
    })
    expect(api.listDevices).toHaveBeenCalled()
  })

  it('device_disconnected with no udid/udids clears all devices', async () => {
    vi.mocked(api.listDevices).mockResolvedValue([])
    const ws = createWsRouter()
    const { result } = renderHook(() => useDevice(ws))

    act(() => {
      ws.dispatch({ type: 'device_disconnected' })
    })

    await waitFor(() => {
      expect(result.current.connectedDevice).toBeNull()
    })
  })
})
```

Create `frontend/src/hooks/useSimulation.router.test.tsx` pinning the banner
logic (remaining_count === 0 shows banner; > 0 clears it):

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { createWsRouter } from '../adapters/ws/router'
import { useSimulation } from './useSimulation'

vi.mock('../services/api')

beforeEach(() => {
  // Force zh banner copy (localStorage default).
  localStorage.removeItem('locwarp.lang')
})

describe('useSimulation device_disconnected banner on WsRouter', () => {
  it('remaining_count === 0 sets the disconnect banner + halts running', () => {
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, null))

    act(() => {
      ws.dispatch({ type: 'device_disconnected', remaining_count: 0 })
    })

    expect(result.current.error).toContain('USB')   // '...請重新插上 USB'
    expect(result.current.status.running).toBe(false)
  })

  it('remaining_count > 0 clears the error (a survivor remains)', () => {
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, null))

    act(() => {
      ws.dispatch({ type: 'device_disconnected', remaining_count: 2 })
    })

    expect(result.current.error).toBeNull()
  })
})
```

Create `frontend/src/App.gold.router.test.tsx`-style coverage for the inline
subscribers is heavier (App.tsx is large). Instead, EXTRACT each inline App.tsx
subscriber into a tiny named hook so it is testable, then test the hook. Create
`frontend/src/hooks/useExternalChangeSubscriptions.ts` (bookmarks/routes) and
`frontend/src/hooks/useGoldDittoSubscription.ts` (goldditto), each taking the
`WsRouter`. Pin them with `frontend/src/hooks/useExternalChangeSubscriptions.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { createWsRouter } from '../adapters/ws/router'
import { useExternalChangeSubscriptions } from './useExternalChangeSubscriptions'

describe('useExternalChangeSubscriptions on WsRouter', () => {
  it('bookmarks_changed triggers refresh + toast', () => {
    const ws = createWsRouter()
    const onBookmarks = vi.fn()
    const onRoutes = vi.fn()
    renderHook(() => useExternalChangeSubscriptions(ws, { onBookmarks, onRoutes }))
    act(() => { ws.dispatch({ type: 'bookmarks_changed', reason: 'external_update' }) })
    expect(onBookmarks).toHaveBeenCalledTimes(1)
    expect(onRoutes).not.toHaveBeenCalled()
  })

  it('routes_changed triggers the routes callback only', () => {
    const ws = createWsRouter()
    const onBookmarks = vi.fn()
    const onRoutes = vi.fn()
    renderHook(() => useExternalChangeSubscriptions(ws, { onBookmarks, onRoutes }))
    act(() => { ws.dispatch({ type: 'routes_changed', reason: 'external_update' }) })
    expect(onRoutes).toHaveBeenCalledTimes(1)
    expect(onBookmarks).not.toHaveBeenCalled()
  })
})
```

#### Step 2 — run the new tests, watch them fail

```bash
cd frontend && npx vitest run \
  src/hooks/useDevice.router.test.tsx \
  src/hooks/useSimulation.router.test.tsx \
  src/hooks/useExternalChangeSubscriptions.test.tsx
```

Expected: FAIL — `useDevice`/`useSimulation` still take the old
`WsSubscribe` callback (not a `WsRouter`), and
`useExternalChangeSubscriptions` does not exist yet.

#### Step 3 — minimal implementation (migrate, then delete old wiring)

**3a. `useDevice.ts`** — change the signature and registration. Replace the
`export type WsSubscribe` usage and the `useEffect` body. Current
(`useDevice.ts:37` + `:43-96`):

```ts
export function useDevice(subscribe?: WsSubscribe) {
  ...
  useEffect(() => {
    if (!subscribe) return
    return subscribe((msg) => {
      if (msg.type === 'device_disconnected') { const udid = msg.data?.udid; ... }
      else if (msg.type === 'device_connected') { ... }
      else if (msg.type === 'device_reconnected') { ... }
    })
  }, [subscribe])
```

New — accept a `WsRouter`, register one typed handler per type, reading the
FLATTENED event keys (`e.udid` not `e.data.udid`):

```ts
import type { WsRouter } from '../ports/WsRouter'
import type { WsEvent } from '../contract/wsEvents'

export function useDevice(ws?: WsRouter) {
  ...
  useEffect(() => {
    if (!ws) return
    const offDisc = ws.subscribe('device_disconnected', (e: WsEvent) => {
      const udid = e.udid as string | undefined
      const udids: string[] = Array.isArray(e.udids) ? (e.udids as string[]) : (udid ? [udid] : [])
      if (udids.length === 0) {
        setConnectedDevice(null)
        setDevices((prev) => prev.map((d) => ({ ...d, is_connected: false })))
      } else {
        setDevices((prev) => prev.map((d) => udids.includes(d.udid) ? { ...d, is_connected: false } : d))
      }
      listDevices().then((list) => {
        setDevices(list)
        setConnectedDevice((prev) => {
          if (prev && list.some((d) => d.udid === prev.udid && d.is_connected)) return prev
          return list.find((d) => d.is_connected) ?? null
        })
      }).catch(() => {})
    })
    const offConn = ws.subscribe('device_connected', (e: WsEvent) => {
      listDevices().then((list) => {
        setDevices(list)
        const udid = e.udid as string | undefined
        const match = udid ? list.find((d) => d.udid === udid && d.is_connected) : null
        setConnectedDevice((prev) => prev ?? match ?? list.find((d) => d.is_connected) ?? null)
      }).catch(() => {})
    })
    const offReconn = ws.subscribe('device_reconnected', (e: WsEvent) => {
      listDevices().then((list) => {
        setDevices(list)
        const udid = e.udid as string | undefined
        const match = udid ? list.find((d) => d.udid === udid) : null
        setConnectedDevice(match ?? list.find((d) => d.is_connected) ?? null)
      }).catch(() => {})
    })
    return () => { offDisc(); offConn(); offReconn() }
  }, [ws])
```

> Behavior is byte-for-byte the same branching as `useDevice.ts:43-96` — only
> the key access changes (`msg.data?.udid` → `e.udid`) and the single combined
> subscribe becomes three typed subscribes whose cleanups are all called.

**3b. `useSimulation.ts`** — same shape change. Accept `ws?: WsRouter` and
`primaryUdid?: string | null`. Register the typed handlers for every message
type the legacy switch handled (`position_update`, `simulation_state`,
`simulation_complete`, `navigation_complete`, `multi_stop_complete`,
`loop_complete`, `waypoint_progress`, `lap_complete`, `ddi_mounting`,
`ddi_mounted`, `ddi_mount_failed`, `ddi_not_mounted`, `tunnel_lost`,
`device_disconnected`, `device_reconnected`, `pause_countdown`,
`random_walk_pause`, `pause_countdown_end`, `random_walk_pause_end`,
`route_path`, `state_change`, `simulation_error`). Preserve BOTH passes:

- The group-mode `updateRuntime(udid, ...)` keyed by `e.udid`.
- The dual-device primary filter: inside each legacy-switch handler, keep
  `const msgUdid = e.udid; const primary = primaryUdidRef.current; if (primary &&
  msgUdid && msgUdid !== primary) return` BEFORE the legacy state setters.

For `device_disconnected`, preserve the banner exactly (`useSimulation.ts:448-469`):

```ts
const offDisc = ws.subscribe('device_disconnected', (e: WsEvent) => {
  const udid = e.udid as string | undefined
  if (udid) updateRuntime(udid, { state: 'disconnected' })   // group-mode pass
  const msgUdid = udid
  const primary = primaryUdidRef.current
  if (primary && msgUdid && msgUdid !== primary) return       // dual-device filter
  const remaining = typeof e.remaining_count === 'number' ? e.remaining_count : 0
  if (remaining === 0) {
    const isEn = typeof localStorage !== 'undefined' && localStorage.getItem('locwarp.lang') === 'en'
    setError(isEn
      ? 'Device disconnected (USB unplugged or tunnel died), please reconnect USB'
      : '裝置連線中斷(USB 拔除或 Tunnel 死亡),請重新插上 USB')
    setStatus((prev) => ({ ...prev, running: false, paused: false }))
  } else {
    setError(null)
  }
})
```

> Keep the effect deps as `[ws, updateRuntime]` (replacing the old
> `[subscribe, updateRuntime]`). Return a cleanup that calls every `off*()`.

**3c. Extract App.tsx inline subscribers into testable hooks.**

Create `frontend/src/hooks/useExternalChangeSubscriptions.ts`:

```ts
import { useEffect } from 'react'
import type { WsRouter } from '../ports/WsRouter'

// Replaces App.tsx inline subscriber #1 (bookmarks_changed / routes_changed).
export function useExternalChangeSubscriptions(
  ws: WsRouter,
  cbs: { onBookmarks: () => void; onRoutes: () => void },
) {
  useEffect(() => {
    const offB = ws.subscribe('bookmarks_changed', () => cbs.onBookmarks())
    const offR = ws.subscribe('routes_changed', () => cbs.onRoutes())
    return () => { offB(); offR() }
  }, [ws, cbs])
}
```

Create `frontend/src/hooks/useGoldDittoSubscription.ts` preserving the
`data.phase` branching + `setInterval` countdown reading
`localStorage 'goldditto.wait_seconds'` (port the exact body from
`App.tsx:1264-1304`, reading `e.phase` off the flattened event). Then in
`App.tsx`:

- Replace `const ws = useWebSocket()` + `useDevice(ws.subscribe)` +
  `useSimulation(ws.subscribe, ...)` with `const { router, sendMessage } =
  useWsRouter()`, `const device = useDevice(router)`, `const sim =
  useSimulation(router, device.primaryDevice?.udid)`,
  `const joystick = useJoystick(sendMessage, ...)`.
- Replace the inline `useEffect(() => ws.subscribe((msg) => {...}))` at
  `App.tsx:207-218` with `useExternalChangeSubscriptions(router, { onBookmarks:
  () => { bm.refresh(); showToast(t('cloud_sync.toast_synced')) }, onRoutes: ()
  => { api.getSavedRoutes().then(setSavedRoutes).catch(()=>{});
  refreshRouteCategories(); showToast(t('cloud_sync.toast_routes_synced')) } })`.
- Replace the inline goldditto `useEffect` at `App.tsx:1264-1304` with
  `useGoldDittoSubscription(router, { t, showToast })`.

Wrap the app subtree in `ServicesProvider value={{ api, ws: router }}` so any
component can later read `useServices()` (no consumer of `useServices` is added
in this task beyond making the provider available — that is intentional; the
context exists for incremental component migration).

#### Step 4 — run all tests + types, watch them pass

```bash
cd frontend && npx vitest run
cd frontend && npx tsc --noEmit
```

Expected: every test file PASSES (Tasks 9–12), `tsc` clean. Confirm the old
pattern is gone:

```bash
cd frontend && grep -rn "\.subscribe((msg" src/   # expect: no matches
cd frontend && grep -rn "ws.subscribe" src/App.tsx  # expect: no matches
```

Expected: both greps print nothing — no raw `subscribe((msg) => ...)` callback
remains; all dispatch is typed via the router.

#### Step 5 — commit

```bash
cd frontend && git add src/hooks/useDevice.ts src/hooks/useSimulation.ts \
  src/hooks/useExternalChangeSubscriptions.ts src/hooks/useGoldDittoSubscription.ts \
  src/hooks/useDevice.router.test.tsx src/hooks/useSimulation.router.test.tsx \
  src/hooks/useExternalChangeSubscriptions.test.tsx src/App.tsx
git commit -m "$(cat <<'EOF'
refactor(frontend): migrate all WS subscribers onto typed WsRouter

useDevice / useSimulation now take a WsRouter and register typed per-event
handlers reading flattened WsEvent keys; App.tsx inline bookmarks/routes and
goldditto subscribers extracted into useExternalChangeSubscriptions /
useGoldDittoSubscription. Divergent device_disconnected shapes preserved
verbatim (udid vs udids array; remaining_count absent => banner shows).
Pinned test-first per site before deleting the old inline subscriptions.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
```

---

### Task 13 — ONE Playwright WS e2e: `position_update` reaches the map; `device_disconnected` fires BOTH effects

**Goal:** an end-to-end test (real backend up, real browser) that opens the app,
injects a synthetic `position_update` and a synthetic `device_disconnected` over
the live WS path, and asserts (a) the map marker moves and (b) BOTH the
device-state effect (`useDevice`) and the simulation-state effect
(`useSimulation` banner) fire. One commit.

> Playwright is a NEW devDependency. **GAP:** not pre-approved in the contract —
> flag for sign-off before `npm install`. If Playwright is rejected, this task's
> coverage is approximately satisfied by the Task 12 jsdom hook tests; mark the
> e2e as deferred and note it.

#### Step 0 — install Playwright (after approval)

```bash
cd frontend && npm install -D @playwright/test@^1 && npx playwright install chromium
```

Create `frontend/playwright.config.ts`:

```ts
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: { baseURL: 'http://localhost:5173' },
  webServer: {
    command: 'npx vite --host --port 5173',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    timeout: 60_000,
  },
})
```

> The backend must be running on `127.0.0.1:8777` for the renderer's
> `useWebSocket` to connect. Start it in a separate shell:
> `cd backend && .venv/bin/python main.py`. The e2e injects events by sending a
> frame to the live `/ws/status` from the page context (the same socket the app
> consumes), so no backend mutation is needed.

#### Step 1 — write the failing e2e

Create `frontend/e2e/ws.spec.ts`:

```ts
import { test, expect } from '@playwright/test'

// Pushes a frame INTO the app by opening a second client to the same WS and
// asking the backend... no — simpler: drive the app's OWN socket via the page.
// We reach into the running renderer and dispatch on the app's WsRouter by
// faking an inbound frame on the app's WebSocket instance.

test('position_update moves the map marker; device_disconnected fires both effects', async ({ page }) => {
  await page.goto('/')

  // Wait for the app to have an OPEN socket (connected indicator or just the WS).
  await page.waitForFunction(() => {
    // The app stores nothing global by default; assert a known mounted element.
    return !!document.querySelector('#root')?.childElementCount
  })

  // Inject a position_update by dispatching a synthetic message on the live
  // socket. We monkey-reach the WebSocket via a captured reference the test
  // installs at page-init time.
  await page.addInitScript(() => {
    const OrigWS = window.WebSocket
    // @ts-expect-error test shim
    window.__lastWS = null
    // @ts-expect-error test shim
    window.WebSocket = class extends OrigWS {
      constructor(...args: ConstructorParameters<typeof OrigWS>) {
        super(...args)
        // @ts-expect-error test shim
        window.__lastWS = this
      }
    }
  })

  // Re-navigate so the init script applies before the app's socket is created.
  await page.goto('/')
  await page.waitForFunction(() => !!(window as any).__lastWS)

  // Emit a position_update frame as if the backend sent it.
  await page.evaluate(() => {
    const ws = (window as any).__lastWS as WebSocket
    const frame = JSON.stringify({
      type: 'position_update',
      data: { udid: 'E2E-UDID', lat: 35.0, lng: 139.0, bearing: 0, speed_mps: 5,
              progress: 0.5, distance_remaining: 100, distance_traveled: 100, eta_seconds: 20 },
    })
    ws.dispatchEvent(new MessageEvent('message', { data: frame }))
  })

  // Assert the map marker reflects the pushed coordinate. The MapView renders a
  // marker; assert a leaflet marker exists / its position. (Selector per the
  // app's marker DOM — adjust to the actual MapView marker class.)
  await expect(page.locator('.leaflet-marker-icon').first()).toBeVisible()

  // Emit device_disconnected with remaining_count 0 -> simulation banner fires
  // AND useDevice marks devices disconnected.
  await page.evaluate(() => {
    const ws = (window as any).__lastWS as WebSocket
    const frame = JSON.stringify({
      type: 'device_disconnected',
      data: { udid: 'E2E-UDID', udids: ['E2E-UDID'], reason: 'forgotten', remaining_count: 0 },
    })
    ws.dispatchEvent(new MessageEvent('message', { data: frame }))
  })

  // simulation-state effect: the disconnect banner text appears (zh default).
  await expect(page.getByText(/USB/)).toBeVisible()
})
```

> **GAP (selector):** the exact map-marker selector and the banner container are
> not in the reader facts. `.leaflet-marker-icon` is the standard Leaflet marker
> class (the app uses `leaflet ^1.9.4` per `package.json`), and the banner text
> contains `USB` (verified in `useSimulation.ts:451`). If the marker uses a
> custom MapLibre layer instead of a Leaflet DOM marker, swap the assertion for a
> `page.locator` on the actual marker element. Confirm against the running app in
> Step 2.

#### Step 2 — run it, watch it fail (then refine selectors)

```bash
cd backend && .venv/bin/python main.py    # shell 1
cd frontend && npx playwright test e2e/ws.spec.ts   # shell 2
```

Expected first run: FAIL on the marker/banner selector (placeholder selectors).
Use `npx playwright test --headed` / `--debug` to read the live DOM and pin the
real marker + banner selectors, then update the two `expect(...)` lines.

#### Step 3 — finalize assertions

Update the marker and banner locators to the verified selectors from Step 2.
No app code changes — this task is test-only.

#### Step 4 — run it, watch it pass

```bash
cd frontend && npx playwright test e2e/ws.spec.ts
cd frontend && npx vitest run && npx tsc --noEmit
```

Expected: the e2e PASSES (marker visible after `position_update`, `USB` banner
visible after `device_disconnected` — proving both the device-state and
simulation-state effects fired off ONE router fan-out). All Vitest + tsc green.

#### Step 5 — commit

```bash
cd frontend && git add e2e/ws.spec.ts playwright.config.ts package.json package-lock.json
git commit -m "$(cat <<'EOF'
test(frontend): Playwright WS e2e — fan-out reaches map + both effects

Injects a position_update (map marker moves) and a device_disconnected
(remaining_count 0) on the live socket and asserts BOTH the device-state
and simulation-state (banner) effects fire from one WsRouter fan-out.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
```

---

#### Phase 1 exit criteria

- `cd frontend && npx vitest run` — all green.
- `cd frontend && npx tsc --noEmit` — clean.
- `cd frontend && grep -rn "8777" src/` — exactly ONE line (`adapters/config.ts`).
- `cd frontend && grep -rn "\.subscribe((msg" src/` — no matches (all WS dispatch
  is typed via `WsRouter`).
- Playwright e2e green (or explicitly deferred if Playwright devDep was rejected).
- No backend file touched; backend's 352 pytest tests remain green (unchanged).
