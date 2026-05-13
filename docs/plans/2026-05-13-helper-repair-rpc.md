# Helper-Owned RemotePairing Re-Pair

## Problem

`POST /api/device/repair` regenerates the cached RemotePairing record by
opening a `CoreDeviceTunnelProxy` over USB lockdown and stepping through the
`create_core_device_tunnel_service_using_rsd` handshake. This call constructs
a `utun` virtual interface on macOS, which requires root. The repair endpoint
runs in the **main backend process** (user-context), so it fails with:

```
RemotePairing 握手失敗: [Errno 0] Failed to create any utun interface
```

…regardless of whether the user has authorised the elevated tunnel helper —
because the repair path never calls into the helper at all.

The helper *does* already own equivalent code: `_handle_open_usb_tunnel` →
`UsbTunnelRunner` → `CoreDeviceTunnelProxy.create()` → `start_tcp_tunnel()`,
running with root, succeeds in creating utun and persisting the RemotePairing
record under the user's home (`~/.pymobiledevice3/…`).

## Goal

Move the repair handshake into the helper, exposed as a new JSON-RPC method
that:

1. opens just enough of the USB tunnel to trigger the Trust dialog and the
   `save_pair_record` side effect,
2. tears the tunnel down immediately afterwards (we don't want to leak a
   tunnel from a brief re-pair call),
3. returns success → backend reports `remote_record_regenerated: true`.

Failure modes the helper must still distinguish so the existing per-case
friendly mapping in `device.py` keeps working:

- Trust dialog timeout / consent pending,
- USB pair record invalid,
- Anything else (raw exception text).

## Approach Survey

| Approach | Mechanism | Pros | Cons |
|---|---|---|---|
| **A. New helper RPC `repair_remote_record(udid)`** | Helper opens a CoreDeviceTunnelProxy long enough to write the RemotePairing record, then closes. Backend's repair endpoint calls into it. | Single-purpose, names the intent, no tunnel leak. | One new RPC + a small re-pair sequencer in the helper. |
| **B. Reuse `open_usb_tunnel` then immediately `close_tunnel`** | Backend calls existing methods in sequence purely for the record-write side effect. | Zero new helper code. | Misnames intent; race during close; helper's `_tunnels` dict toggles for no real reason; log noise. |
| **C. Stop offering re-pair from backend, route via tunnel-helper CLI** | User runs the helper directly. | None for UX. | Regression — repair must stay one-click. |

**Decision: A.** Distinct surface, no false tunnel state in the helper's
in-memory dict, and the helper code path is simple enough that the extra
RPC is cheaper than the semantic confusion of B.

## Design

### Helper side

In `tunnel_helper_main.py`:

```python
"repair_remote_record": self._handle_repair_remote_record,
...
async def _handle_repair_remote_record(self, params: dict) -> dict:
    udid = params.get("udid")
    if not isinstance(udid, str):
        raise _HelperRpcError(-32602, "repair_remote_record needs udid:str")
    # Don't gate on _tunnels — repair is a transient handshake, not
    # a persistent tunnel registration.
    try:
        result = await _run_repair(udid, parent_uid=self.parent_uid)
    except Exception as exc:
        raise _HelperRpcError(-32002, f"repair_remote_record failed: {exc}")
    return result  # { "status": "ok", "record_path": str, "udid": udid }
```

`_run_repair(udid, parent_uid)` (new helper-internal function, lives next to
`UsbTunnelRunner`):

1. `lockdown = await create_using_usbmux(serial=udid)`
2. `proxy = await CoreDeviceTunnelProxy.create(lockdown)`
3. `async with proxy.start_tcp_tunnel() as tun:` — this is the line that
   triggers Trust + the `save_pair_record` write (same place
   `UsbTunnelRunner` waits inside).
4. Exit the `async with` immediately to tear the tunnel down.
5. `chown` the freshly-written `~/.pymobiledevice3/<udid>.plist` to
   `parent_uid` so the user-context backend can read it on next launch.
6. Return `{ status, record_path, udid }`.

Reusing helper's `parent_uid` (already passed on argv at launch) keeps
the chown safe against the I3 socket-permission attack class.

### Client wrapper

In `services/tunnel_helper_client.py`:

```python
async def repair_remote_record(self, udid: str) -> dict:
    return await self.call("repair_remote_record", udid=udid)
```

### Backend endpoint

In `backend/api/device.py`, replace the in-process CoreDeviceTunnelProxy
block (lines ~203–268) with:

```python
try:
    await helper_client.repair_remote_record(udid)
    remote_record_regenerated = True
except HelperError as e:
    msg = str(e)
    # Reuse existing friendly classifier — utun / Trust / not paired / generic.
    friendly = _classify_repair_error(msg)
    raise HTTPException(
        status_code=500,
        detail={
            "code": "remote_pair_failed",
            "message": friendly,
            "udid": udid,
            "ios_version": ios_version,
        },
    )
```

Pull the existing switch ladder out into `_classify_repair_error(msg)` so the
endpoint is shorter and the classifier can be unit-tested.

Special case: when `helper_client` is not connected (helper not authorised
yet), surface a distinct hint:

```
"請先安裝/啟用 tunnel helper（系統會跳出授權對話框）。"
```

…rather than the generic utun message. The endpoint already imports
`helper_client` from `main`; check `helper_client.is_connected` (add a small
property if missing) before calling.

### Cleanup

The in-process imports `CoreDeviceTunnelProxy`, `RemoteServiceDiscoveryService`,
`create_core_device_tunnel_service_using_rsd` become unused in device.py
once the repair block is removed. Keep them only if other endpoints in the
file need them; otherwise drop the imports.

## Test plan

`backend/tests/test_device_repair.py` (new, mocked helper):

1. `test_repair_calls_helper_repair_remote_record` — mock `helper_client`
   so the endpoint dispatches to `repair_remote_record(udid=...)`.
2. `test_repair_classifies_utun_error` — helper raises `HelperError("...utun...")`;
   endpoint returns 500 with the admin-restart friendly message.
3. `test_repair_classifies_trust_error` — helper raises with
   `"PairingDialogResponsePending"`; endpoint returns 500 with Trust-prompt
   friendly message.
4. `test_repair_classifies_pairing_error` — helper raises
   `"PairingError: not paired"`; endpoint returns 500 with USB-reseat message.
5. `test_repair_helper_disconnected` — `helper_client.is_connected` False;
   endpoint returns 500 with "請先安裝/啟用 tunnel helper" message.
6. `test_classify_repair_error` — pure unit test of the classifier ladder.

For the helper side, the existing helper-process tests already cover the
RPC dispatch envelope (`open_*_tunnel`); add one analogous parametrised
case that confirms `repair_remote_record` is registered and its params
schema check rejects bad input.

`backend/tests/test_tunnel_helper_client.py` — add one round-trip test
(mocked stream) for the new client method.

## Out of scope

- iOS 16 legacy path: lockdown-only, no utun, no RemotePairing record;
  unchanged.
- Pair record migration for users who have a stale record in root's home
  from a previous helper version. Reserved for a follow-up if user reports
  it.
- Backend `/api/cloud-sync/*` flows — unrelated.

## Open question

Does `proxy.start_tcp_tunnel()` finalise the record write at the
`__aenter__` boundary, or only after a brief async tick? If the latter
we may need to keep the `async with` body alive for a short moment
(`await asyncio.sleep(0)` or wait on a small future) to give
pymobiledevice3 time to flush `save_pair_record`. Easiest empirical
answer: in implementation, after the `async with`, assert the record
file exists; if not, retry with a `0.1s` post-enter delay.
