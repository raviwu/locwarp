# USB Transport Auto-Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a device is already connected via Network (WiFi Sync / saved-IP auto-connect) and the usbmux presence watchdog then sees it present on USB too, automatically switch it to USB — matching `DeviceManager.connect()`'s own existing "prefer USB if device shows up as both" intent, which today only ever applies at first-connect and is never re-asserted afterward.

**Architecture:** One new pure function `compute_usb_promotion_targets` in the existing `backend/services/device_presence.py` (stdlib-only, same module as this morning's `compute_usb_reconnect_targets`), wired into `backend/main.py`'s `_usbmux_presence_watchdog` as a second loop that reuses the existing per-udid cooldown maps and the existing `device_connected` WS broadcast. No changes to `device_manager.py` or the frontend.

**Tech Stack:** Python 3.13 (backend), stdlib only for the new helper, pytest (`asyncio_mode = strict`).

Full design: `docs/superpowers/specs/2026-07-02-usb-transport-promotion-design.md`

## Global Constraints

- **Behavior scope:** only a device already connected via a non-USB transport that is also currently present on USB gets touched. A device already on USB, or a device not connected at all, is untouched by this change (the latter is `compute_usb_reconnect_targets`'s job, unchanged).
- **No `device_manager.py` changes.** `DeviceManager.connect()`'s "prefer USB if shown as both" logic (`device_manager.py:500-513`) already does the right thing once a fresh `connect()` runs — do not touch its semantics or the connect-latch machinery from the sibling USB-reconnect plan (`c00b6b6`).
- **No frontend changes.** The promotion loop reuses the existing `device_connected` WS broadcast; the frontend already renders `connection_type` from it.
- **Structural gotcha (see Task 1 Step 5):** the existing appearance block does `if not new_udids: continue`, which skips the rest of the watchdog tick. The promotion check must be computed *before* that early-exit and the exit condition widened, or the promotion loop will only ever run on ticks that also happen to have a genuinely new device.
- **Layering:** `backend/services/device_presence.py` stays stdlib-only (import-linter `services/` ring contract). `main.py` (composition root) may import it.
- **Backend suite green after the commit.** Baseline pinned in Task 0: **1107 tests collected**.
- **Test command:** `cd backend && .venv/bin/python -m pytest <args>`; repo root `/Users/raviwu/personal/locwarp`, venv at `backend/.venv`.
- **Git identity** auto-set by includeIf — never pass `-c user.email=...`. Personal repo → direct commit to `main`.

---

## File Structure

- **Modify** `backend/services/device_presence.py` — add `compute_usb_promotion_targets(...)`, same file as `compute_usb_reconnect_targets`
- **Modify** `backend/tests/test_device_presence.py` — add its tests
- **Modify** `backend/main.py` — widen the early-exit in `_usbmux_presence_watchdog` (~line 750) and add the new promotion loop (~after line 828)

---

## Task 0: Pin the baseline

- [ ] **Step 1: Record collected count**

Run:
```bash
cd backend && .venv/bin/python -m pytest --collect-only -q | tail -1
```
Expected: `1107 tests collected in ...` (matches the count already verified before this plan was written — if it differs, note the actual number and use it as the baseline for Task 2's verification instead).

---

## Task 1: Add `compute_usb_promotion_targets` and wire the watchdog

**Files:**
- Modify: `backend/services/device_presence.py`
- Modify: `backend/tests/test_device_presence.py`
- Modify: `backend/main.py` (`_usbmux_presence_watchdog`, lines ~739-828)

**Interfaces:**
- Produces: `compute_usb_promotion_targets(connections: Mapping[str, str], present_usb_serials: Iterable[str]) -> list[str]` — UDIDs (in the exact casing of the `connections` dict's keys) that are connected via a non-`"USB"` transport and are now also present on USB.
- Consumes (existing, unchanged): `dm._connections` (`Mapping[str, _ActiveConnection]`, each with a `.connection_type: str` attribute), `present_usb_original: dict[str, str]` (lowercase → original-case serial, already built earlier in the watchdog loop), `reconnect_failure_count: dict[str, int]`, `last_reconnect_attempt: dict[str, float]`, `reconnect_cooldown_base`, `reconnect_cooldown_max`, `dm.disconnect(udid)`, `dm.connect(udid)`, `dm.discover_devices()`, `broadcast(event, payload)`.

- [ ] **Step 1: Write the failing tests**

Add to the end of `backend/tests/test_device_presence.py` (the existing `compute_usb_reconnect_targets` import at the top of the file needs a second name added):

```python
from services.device_presence import (
    compute_usb_promotion_targets,
    compute_usb_reconnect_targets,
)
```

Replace the existing single-name import line (`from services.device_presence import compute_usb_reconnect_targets`) with the two-name import above, then append these tests to the file:

```python
def test_network_connected_and_present_on_usb_is_promoted():
    # The core bug this fixes: a device connected via Network that is now
    # also visible on USB must be promoted, so the panel switches off WiFi.
    assert compute_usb_promotion_targets(
        connections={"RENEE": "Network"},
        present_usb_serials=["RENEE"],
    ) == ["RENEE"]


def test_already_usb_connected_is_not_promoted():
    # Nothing to promote — it's already on USB.
    assert compute_usb_promotion_targets(
        connections={"RENEE": "USB"},
        present_usb_serials=["RENEE"],
    ) == []


def test_network_connected_but_absent_from_usb_is_not_promoted():
    # Nothing to promote to — the device isn't present on USB at all.
    assert compute_usb_promotion_targets(
        connections={"RENEE": "Network"},
        present_usb_serials=[],
    ) == []


def test_promotion_comparison_is_case_insensitive():
    assert compute_usb_promotion_targets(
        connections={"renee": "Network"},
        present_usb_serials=["RENEE"],
    ) == ["renee"]


def test_promotion_returns_original_casing_from_connections_keys():
    # Caller uses this UDID directly in dm.disconnect()/dm.connect(), which
    # index _connections by the exact casing DeviceManager stored it under —
    # so the returned casing must come from `connections`, not from
    # `present_usb_serials`.
    assert compute_usb_promotion_targets(
        connections={"MixedCase-UDID": "Network"},
        present_usb_serials=["mixedcase-udid"],
    ) == ["MixedCase-UDID"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
cd backend && .venv/bin/python -m pytest tests/test_device_presence.py -v
```
Expected: the 4 pre-existing `compute_usb_reconnect_targets` tests still PASS; the 5 new tests FAIL with `ImportError: cannot import name 'compute_usb_promotion_targets'`.

- [ ] **Step 3: Implement `compute_usb_promotion_targets`**

In `backend/services/device_presence.py`, change the import line at the top from:
```python
from collections.abc import Iterable
```
to:
```python
from collections.abc import Iterable, Mapping
```

Then append this function to the end of the file (after `compute_usb_reconnect_targets`):

```python
def compute_usb_promotion_targets(
    connections: Mapping[str, str],
    present_usb_serials: Iterable[str],
) -> list[str]:
    """UDIDs connected via a non-USB transport that are now present on USB.

    ``connections`` maps udid (in the exact casing DeviceManager stores it
    under in ``_connections`` — the caller must use that same casing for its
    disconnect()/connect() calls) to its current connection_type. A udid
    already on USB is never a promotion target — nothing to promote.
    Comparison against ``present_usb_serials`` is case-insensitive, matching
    ``compute_usb_reconnect_targets``. No ``max_devices`` cap: promotion
    swaps one already-counted connection's transport, it never changes the
    connected-device count.
    """
    present_lc = {s.lower() for s in present_usb_serials}
    return sorted(
        udid for udid, conn_type in connections.items()
        if conn_type != "USB" and udid.lower() in present_lc
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
cd backend && .venv/bin/python -m pytest tests/test_device_presence.py -v
```
Expected: 9 PASS (4 pre-existing + 5 new).

- [ ] **Step 5: Wire the watchdog — widen the early-exit and compute `promotable`**

In `backend/main.py`, find the existing appearance block (currently lines ~739-750):
```python
            MAX_DEVICES = 3
            # Dedup against ALL connected devices (any transport), not just the
            # USB-typed `connected` set used for disappearance — otherwise a
            # device stored as non-USB (or under different casing) is re-flagged
            # 'new' every poll and connect() no-ops forever (busy-loop).
            from services.device_presence import compute_usb_reconnect_targets
            new_udids = compute_usb_reconnect_targets(
                connected_udids=dm._connections.keys(),
                present_usb_serials=present_usb_original.values(),
                max_devices=MAX_DEVICES,
            )
            if not new_udids:
                continue
```

Replace it with (adds the promotion computation and widens the exit condition — the `new_udids` computation itself is unchanged):
```python
            MAX_DEVICES = 3
            # Dedup against ALL connected devices (any transport), not just the
            # USB-typed `connected` set used for disappearance — otherwise a
            # device stored as non-USB (or under different casing) is re-flagged
            # 'new' every poll and connect() no-ops forever (busy-loop).
            from services.device_presence import (
                compute_usb_promotion_targets,
                compute_usb_reconnect_targets,
            )
            new_udids = compute_usb_reconnect_targets(
                connected_udids=dm._connections.keys(),
                present_usb_serials=present_usb_original.values(),
                max_devices=MAX_DEVICES,
            )
            # A device connected via Network (WiFi Sync / saved-IP auto-
            # connect) is never re-evaluated once connected — connect() is a
            # no-op for any UDID already in _connections. This re-asserts
            # connect()'s own "prefer USB if shown as both" preference for a
            # device that connected over WiFi before USB became available.
            promotable = compute_usb_promotion_targets(
                connections={u: c.connection_type for u, c in dm._connections.items()},
                present_usb_serials=present_usb_original.values(),
            )
            if not new_udids and not promotable:
                continue
```

**Do not** move or duplicate the `stale = [...]` backoff-reset block or the `now = time.monotonic()` line that follow this block — they stay exactly where they are, unchanged, and both the existing `new_udids` loop and the new `promotable` loop (Step 6) run after them, sharing the same `now`.

- [ ] **Step 6: Wire the watchdog — add the promotion loop**

In `backend/main.py`, find the end of the existing `for udid in new_udids:` loop — it ends right before `except asyncio.CancelledError:` (currently line 829), with the loop's last lines being:
```python
                    logger.warning(
                        "Auto-connect for %s failed (attempt %d, will retry in %.0fs): likely Trust pending / no admin / firewall",
                        udid, fail_count + 1, next_cooldown,
                        exc_info=log_with_trace,
                    )
        except asyncio.CancelledError:
```

Insert the new promotion loop between the end of the existing `for udid in new_udids:` loop body and `except asyncio.CancelledError:`, so it reads:
```python
                    logger.warning(
                        "Auto-connect for %s failed (attempt %d, will retry in %.0fs): likely Trust pending / no admin / firewall",
                        udid, fail_count + 1, next_cooldown,
                        exc_info=log_with_trace,
                    )

            # --- Promotion (Network -> USB when USB becomes available) ---
            for udid in promotable:
                fail_count = reconnect_failure_count.get(udid, 0)
                cooldown = min(
                    reconnect_cooldown_base * (2 ** fail_count),
                    reconnect_cooldown_max,
                )
                last = last_reconnect_attempt.get(udid, 0.0)
                if now - last < cooldown:
                    continue
                last_reconnect_attempt[udid] = now
                logger.info(
                    "usbmux watchdog: promoting %s from Network to USB (fail_count=%d, cooldown=%.0fs)",
                    udid, fail_count, cooldown,
                )
                try:
                    await dm.disconnect(udid)
                    await dm.connect(udid)
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
                        logger.exception("watchdog: broadcast (promoted) failed")
                    logger.info("Promotion to USB succeeded for %s", udid)
                    reconnect_failure_count.pop(udid, None)
                except Exception:
                    reconnect_failure_count[udid] = fail_count + 1
                    next_cooldown = min(
                        reconnect_cooldown_base * (2 ** (fail_count + 1)),
                        reconnect_cooldown_max,
                    )
                    logger.warning(
                        "Promotion to USB for %s failed (attempt %d, will retry in %.0fs)",
                        udid, fail_count + 1, next_cooldown,
                        exc_info=fail_count < 3,
                    )
        except asyncio.CancelledError:
```

Deliberately, this loop does **not**: check `dm.sticky_user_denied` (a currently-connected device already passed pairing, so it can't be in that set), check `len(dm._connections) >= MAX_DEVICES` (promotion swaps an already-counted connection's transport, it never adds one), or call `_auto_sync_new_device_to_primary(udid)` (the promoted device was already in sync; that call is for a device newly joining group mode and its "replay the current action" branch would risk restarting the promoted device's own in-progress route from scratch).

- [ ] **Step 7: Verify `main.py` still imports cleanly**

Run:
```bash
cd backend && .venv/bin/python -c "import main; print('import OK')"
```
Expected: `import OK` (confirms no syntax error was introduced by the edit).

- [ ] **Step 8: Full backend suite green**

Run:
```bash
cd backend && .venv/bin/python -m pytest -q
```
Expected: all pass; baseline (Task 0's count) + 5 new tests.

- [ ] **Step 9: Commit**

```bash
git add backend/services/device_presence.py backend/tests/test_device_presence.py backend/main.py
git commit -m "$(cat <<'EOF'
feat(device): auto-promote a Network-connected device to USB when it appears

DeviceManager.connect() already prefers USB "if device shows up as both",
but only at first-connect — once connected via any transport, connect()
is an unconditional no-op, so a device that connected over WiFi (WiFi
Sync / saved-IP auto-connect) before USB became available stayed on
WiFi forever, even with the cable plugged in. Add
compute_usb_promotion_targets (services/device_presence.py, stdlib-only)
and wire it into the usbmux watchdog as a second loop that
disconnect()+connect()s a Network-connected device once it's also seen
present on USB, reusing the existing per-udid cooldown maps and the
device_connected WS broadcast so the frontend panel updates without any
frontend changes.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Full verification

**Files:** none.

- [ ] **Step 1: Full backend suite green, count = baseline + 5**

Run:
```bash
cd backend && .venv/bin/python -m pytest -q
```
Expected: all pass, count = Task 0's baseline + 5.

- [ ] **Step 2: Import-linter contracts still `7 kept, 0 broken`**

Run:
```bash
cd backend && .venv/bin/lint-imports
```
Expected: `Contracts: 7 kept, 0 broken.` — `device_presence.py` stayed stdlib-only.

- [ ] **Step 3: Runtime smoke (macOS, physical device — manual, deferred to the user)**

With the iPhone already connected via Network (WiFi Sync, or a saved-IP auto-connect on backend startup), plug in the USB cable. Within a few seconds, confirm:
```bash
grep 'promoting .* from Network to USB\|Promotion to USB succeeded' ~/.locwarp/logs/backend.log
```
shows both lines for the device's UDID, and the frontend DeviceChip panel's connection badge switches from WiFi to USB. If a route/multi-stop was actively running at the moment of promotion, confirm it resumes (rather than aborting) after the brief flicker described in the design doc's "Accepted tradeoff" section.

---

## Self-Review

1. **Spec coverage:** the design doc's "New pure helper", "Watchdog wiring" (including the early-exit gotcha), "Deliberately skipped" list, and "Testing" sections are each covered by Task 1's steps 1-6 and its docstring/comments. The "Accepted tradeoff" and "Runtime smoke" sections are covered by Task 2 Step 3. No `device_manager.py` or frontend changes are proposed anywhere in this plan, matching the design's constraints. ✅
2. **Placeholder scan:** every step has real code; no TBD/TODO; test assertions use exact expected values (`== ["NEWDEV"]`-style lists, exact casing). ✅
3. **Type/name consistency:** `compute_usb_promotion_targets(connections, present_usb_serials)` signature identical across the test file, the implementation, and the `main.py` call site. `promotable` name consistent between Step 5 (computed) and Step 6 (consumed). Reused names (`reconnect_failure_count`, `last_reconnect_attempt`, `reconnect_cooldown_base`, `reconnect_cooldown_max`, `now`, `dm`, `broadcast`) match their existing definitions elsewhere in `_usbmux_presence_watchdog`, unchanged by this plan. ✅
