from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_device_service
from models.schemas import DeviceInfo

router = APIRouter(prefix="/api/device", tags=["device"])


def _dm():
    from main import app_state
    return app_state.device_manager


@router.get("/list", response_model=list[DeviceInfo])
async def list_devices():
    dm = _dm()
    return await dm.discover_devices()


# /wifi/connect (legacy direct-IP WiFi for iOS <17) removed in v0.1.49.


@router.get("/wifi/scan")
async def wifi_scan():
    """Scan the local network for iOS devices."""
    dm = _dm()
    try:
        results = await dm.scan_wifi_devices()
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class WifiTunnelConnectRequest(BaseModel):
    rsd_address: str
    rsd_port: int


@router.post("/wifi/tunnel")
async def wifi_tunnel_connect(req: WifiTunnelConnectRequest):
    """Connect to a device via an existing WiFi tunnel (RSD address/port)."""
    from main import app_state
    from core.device_manager import UnsupportedIosVersionError
    dm = _dm()
    # Max 3 devices (group mode). connect_wifi_tunnel may reconnect an existing udid;
    # we can only cheaply check the pre-state here.
    if len(dm._connections) >= MAX_DEVICES:
        raise HTTPException(
            status_code=409,
            detail={"code": "max_devices_reached", "message": f"已連接最多 {MAX_DEVICES} 台裝置"},
        )
    try:
        info = await dm.connect_wifi_tunnel(req.rsd_address, req.rsd_port)
        await app_state.create_engine_for_device(info.udid)
        try:
            await dm._events.publish(("device_connected", {
                "udid": info.udid,
                "name": info.name,
                "ios_version": info.ios_version,
                "connection_type": "Network",
            }))
        except Exception:
            pass
        return {
            "status": "connected",
            "udid": info.udid,
            "name": info.name,
            "ios_version": info.ios_version,
            "connection_type": "Network",
        }
    except UnsupportedIosVersionError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "ios_unsupported",
                "message": (
                    f"偵測到 iOS {e.version},LocWarp 自 v0.1.49 起僅支援 "
                    f"iOS {UnsupportedIosVersionError.MIN_VERSION} 以上。"
                    f"請將裝置升級至 iOS {UnsupportedIosVersionError.MIN_VERSION} 或更新版本後再連線。"
                ),
                "ios_version": e.version,
                "min_version": UnsupportedIosVersionError.MIN_VERSION,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── WiFi Tunnel lifecycle (start / status / stop) ───────

import asyncio
import logging

from core.wifi_tunnel import TunnelRunner

_tunnel_logger = logging.getLogger("wifi_tunnel")

# Group-mode device cap. Same value gates USB auto-connect, /wifi/tunnel,
# /wifi/tunnel/start, /wifi/tunnel/start-and-connect, and /{udid}/connect.
MAX_DEVICES = 3

# Per-device tunnel registry. Each connected iOS 17+ device that uses
# WiFi (instead of USB) gets its own TunnelRunner. v0.2.83 lifted the
# previous singleton design so multiple iPhones can run on WiFi at once.
# Registry mutations go through _tunnels_lock. Each device has its own
# TunnelRunner facade; the actual TUN lives in the helper process. The
# facade's `.task` resolves when either stop() is called locally or the
# helper drops the tunnel (detected via list_tunnels poll), which is
# what _per_tunnel_watchdog awaits to trigger auto-restart.
# The registry state now lives in infra/device/tunnel_state.py so the
# WifiTunnelRegistry can read it without importing api (killing the last
# infra->api edge). These module aliases keep api.device._tunnels et al.
# pointing at the SAME objects, so every mutation/read site below — and
# every test that does device_mod._tunnels.clear() — works unchanged.
from infra.device.tunnel_state import (  # noqa: E402
    _tunnels,
    _tunnel_watchdogs,
    _tunnels_lock,
)


def _classify_repair_error(msg: str) -> str:
    """Map a RemotePairing handshake failure string to a friendly hint.

    Order matters: the utun branch must precede the generic fallback
    because the underlying exception text bundles "Errno 0 Failed to
    create any utun interface" — that case calls for a privilege fix,
    not a Trust-prompt or USB-reseat hint.
    """
    lower = msg.lower()
    if "utun" in lower:
        return (
            "RemotePairing 握手失敗：無法建立 utun 介面。"
            "請以系統管理員身分重啟 LocWarp（或確認 tunnel helper 已啟用）。"
        )
    if "PairingDialogResponsePending" in msg or "consent" in lower:
        return "請在 iPhone 解鎖螢幕上按「信任」後重試(timeout 只有幾秒)。"
    if "not paired" in lower or "pairingerror" in lower:
        return "USB 配對失效,請拔 USB 重插一次並按信任。"
    return f"RemotePairing 握手失敗:{msg}"


def _humanize_pair_error(exc: BaseException, *, stale_cleared: bool) -> str:
    """Map a USB pair failure to a specific, actionable user-facing message.

    The branches are ordered so a "user hasn't tapped Trust yet" case wins
    over the post-stale-clear fallback — if both could apply, the more
    specific message helps the user more.
    """
    name = type(exc).__name__
    msg = str(exc)
    lower = msg.lower()

    if "PairingDialogResponsePending" in name or "consent" in lower:
        return "請在 iPhone 解鎖畫面上按「信任」"

    if "UserDeniedPairing" in name or "denied" in lower:
        return (
            "之前在 iPhone 上點了「不信任」。請到 iPhone Settings → 一般 → "
            "移轉或重置 iPhone → 重置 → 重置位置與隱私權，然後重插 USB"
        )

    if stale_cleared:
        return (
            "已重置配對紀錄但 iPhone 仍未跳信任提示。請確認 iPhone 已解鎖、"
            "USB 線可傳輸資料；如仍不出現，請走 Settings → 一般 → 移轉或重置 "
            "iPhone → 重置 → 重置位置與隱私權"
        )

    return f"USB 配對失敗:{exc}"


class WifiRepairRequest(BaseModel):
    """Optional body for /wifi/repair. When ``udid`` is set, repair that
    specific device; when None, fall back to the legacy "first USB device
    in the mux list" behavior so the existing global Repair button keeps
    working unchanged."""
    udid: str | None = None


@router.post("/wifi/repair")
async def wifi_repair(req: WifiRepairRequest | None = None, device_service=Depends(get_device_service)):
    """Regenerate the RemotePairing pair record (~/.pymobiledevice3/) using a
    currently-attached USB device. The iPhone will show a 'Trust This Computer'
    prompt the first time; after the user taps 信任, a fresh RemotePairing
    record is written and WiFi Tunnel will work again.

    Flow:
      1. List USB devices (must have at least one plugged in).
      2. Open a USB lockdown session with autopair=True — this triggers the
         Trust prompt if the Apple Lockdown USB record is missing.
      3. For iOS 17+: open CoreDeviceTunnelProxy.start_tcp_tunnel() briefly.
         pymobiledevice3 persists the RemotePairing record to
         ~/.pymobiledevice3/ as a side effect of the RSD handshake.
    """
    from pymobiledevice3.usbmux import list_devices as mux_list_devices
    from main import helper_client
    from services.tunnel_helper_client import HelperError

    try:
        raw_devices = await mux_list_devices()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"code": "usbmux_unavailable", "message": f"無法列出 USB 裝置:{e}"},
        )

    # Prefer a USB-attached device (Network entries won't help us regenerate
    # the RemotePairing record).
    requested_udid = req.udid if req else None
    if requested_udid:
        usb_dev = next(
            (d for d in raw_devices
             if d.serial == requested_udid
             and getattr(d, "connection_type", "USB") == "USB"),
            None,
        )
        if usb_dev is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "device_not_found",
                    "message": f"找不到 USB 裝置 {requested_udid}。請確認 USB 線已接好。",
                    "udid": requested_udid,
                },
            )
    else:
        # Legacy behavior: pick the first USB-attached device.
        usb_dev = next(
            (d for d in raw_devices if getattr(d, "connection_type", "USB") == "USB"),
            None,
        )
        if usb_dev is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "repair_needs_usb",
                    "message": "請先用 USB 線連接 iPhone。重新配對需要 USB 觸發『信任這台電腦』提示。",
                },
            )

    udid = usb_dev.serial
    _tunnel_logger.info("Re-pair requested for USB device %s", udid)

    # Clear any sticky "user denied" flag from the watchdog — explicit user
    # intent (they clicked Re-trust) overrides the watchdog's auto-skip.
    await device_service.repair(udid)

    # Step 1: USB lockdown autopair via the shared recovery helper. If the
    # host has a stale pair record (iPhone has forgotten this Mac), the
    # helper clears it and retries exactly once — that's the only way to
    # coax the iPhone into showing the "Trust This Computer" prompt again
    # under macOS 11+ SIP rules (sudo rm of /var/db/lockdown/ does not work).
    from services.usbmux_pair_records import (
        autopair_with_recovery,
        _is_stale_cert_error,
    )
    try:
        lockdown, stale_cleared = await autopair_with_recovery(udid, autopair=True)
    except Exception as exc:
        # Distinguish "we already cleared, but iPhone still won't prompt"
        # from "first attempt failed, never cleared" — the former gets a
        # different code so the UI can show a stronger guidance string.
        cleared = getattr(exc, "_locwarp_stale_cleared", False)
        if _is_stale_cert_error(exc):
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "trust_prompt_unavailable",
                    "message": _humanize_pair_error(exc, stale_cleared=True),
                    "udid": udid,
                    "stale_cleared": True,
                },
            )
        raise HTTPException(
            status_code=500,
            detail={
                "code": "trust_failed",
                "message": _humanize_pair_error(exc, stale_cleared=cleared),
                "udid": udid,
                "stale_cleared": cleared,
            },
        )

    ios_version = lockdown.all_values.get("ProductVersion", "0.0")
    name = lockdown.all_values.get("DeviceName", "iPhone")

    # Step 2: iOS 17+ — briefly open a CoreDeviceTunnelProxy. The RSD handshake
    # re-generates the ~/.pymobiledevice3/ RemotePairing record.
    try:
        major = int(ios_version.split(".")[0])
    except (ValueError, IndexError):
        major = 0

    remote_record_regenerated = False
    if major >= 17:
        # Delete any stale remote pair record for this udid so the
        # RemotePairingProtocol.connect() path can't short-circuit through
        # the cached (possibly-corrupt) record and actually runs _pair().
        try:
            from pymobiledevice3.common import get_home_folder
            from pymobiledevice3.pair_records import (
                PAIRING_RECORD_EXT,
                get_remote_pairing_record_filename,
            )
            stale = get_home_folder() / f"{get_remote_pairing_record_filename(udid)}.{PAIRING_RECORD_EXT}"
            if stale.exists():
                stale.unlink()
                _tunnel_logger.info("Re-pair: removed stale remote pair record %s", stale)
        except Exception:
            _tunnel_logger.debug("Re-pair: could not check/remove stale pair record", exc_info=True)

        # The RemotePairing handshake opens a CoreDeviceTunnelProxy, which
        # constructs a utun interface on macOS — that operation requires
        # root. Run it inside the elevated helper instead of in-process.
        if not helper_client.is_connected:
            _tunnel_logger.warning(
                "Re-pair: helper not connected; cannot perform RemotePairing handshake"
            )
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "remote_pair_failed",
                    "message": (
                        "Tunnel helper 尚未啟用。請重啟 LocWarp 並於"
                        "跳出的授權對話框輸入密碼後再試。"
                    ),
                    "udid": udid,
                    "ios_version": ios_version,
                },
            )

        try:
            _tunnel_logger.info(
                "Re-pair: delegating RemotePairing handshake to helper for %s",
                udid,
            )
            await helper_client.repair_remote_record(udid)
            _tunnel_logger.info(
                "Re-pair: helper completed RemotePairing record write for %s", udid
            )
            remote_record_regenerated = True
        except HelperError as e:
            _tunnel_logger.exception("Re-pair: helper RemotePairing handshake failed")
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "remote_pair_failed",
                    "message": _classify_repair_error(str(e)),
                    "udid": udid,
                    "ios_version": ios_version,
                },
            )

    return {
        "status": "paired",
        "udid": udid,
        "name": name,
        "ios_version": ios_version,
        "remote_record_regenerated": remote_record_regenerated,
        "stale_cleared": stale_cleared,
    }


class WifiTunnelStartRequest(BaseModel):
    ip: str
    port: int = 49152
    udid: str | None = None
    # Stable Bonjour service id stripped from the ``_remotepairing._tcp.local.``
    # PTR — passed back from the frontend when the user picks an entry from
    # /wifi/tunnel/discover. We use it to persist a ``bonjour_id → {udid,
    # name}`` alias on a successful connect, so the next discover can label
    # the picker with the real DeviceName.
    bonjour_id: str | None = None


def _get_primary_local_ip() -> str | None:
    """Return this machine's primary IPv4 (the one used to reach the internet)."""
    import socket as _s
    try:
        s = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


async def _tcp_probe(ip: str, port: int, timeout: float = 0.4) -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except (OSError, ConnectionError):
            pass
        return True
    except (OSError, ConnectionError, asyncio.TimeoutError):
        return False


async def _scan_subnet_for_port(port: int = 49152) -> list[str]:
    """Scan the local /24 subnet for hosts responding on the given TCP port."""
    my_ip = _get_primary_local_ip()
    if not my_ip:
        return []
    try:
        parts = my_ip.split(".")
        prefix = ".".join(parts[:3])
    except (AttributeError, IndexError):
        return []

    candidates = [f"{prefix}.{i}" for i in range(1, 255) if f"{prefix}.{i}" != my_ip]
    results = await asyncio.gather(
        *[_tcp_probe(ip, port, 0.4) for ip in candidates],
        return_exceptions=True,
    )
    hits = [ip for ip, ok in zip(candidates, results) if ok is True]
    return hits


async def _scan_ports_for_ip(
    ip: str,
    start: int = 49152,
    end: int = 65535,
    concurrency: int = 1024,
    timeout: float = 0.35,
) -> list[int]:
    """Scan the IANA dynamic / ephemeral range on a single IP for open TCP ports.

    iOS picks the RemotePairing port from this range at boot / network rebind,
    so the actual port on a given iPhone is rarely the legacy 49152 default.
    Scanning one host across 16k ports finishes in a few seconds because most
    closed ports return RST immediately on a same-LAN probe.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _probe_one(p: int) -> int | None:
        async with sem:
            ok = await _tcp_probe(ip, p, timeout)
            return p if ok else None

    tasks = [asyncio.create_task(_probe_one(p)) for p in range(start, end + 1)]
    hits: list[int] = []
    for fut in asyncio.as_completed(tasks):
        try:
            res = await fut
        except (OSError, ConnectionError, asyncio.TimeoutError):
            res = None
        if res is not None:
            hits.append(res)
    hits.sort()
    return hits


class WifiTunnelFindPortRequest(BaseModel):
    ip: str


@router.post("/wifi/tunnel/find_port")
async def wifi_tunnel_find_port(req: WifiTunnelFindPortRequest):
    """Scan an iPhone IP across the IANA dynamic range (49152-65535) and return
    every open TCP port. Used as the manual fallback when mDNS / Bonjour fails
    because the user's router blocks multicast or the PC has VPN / virtual NICs
    that hijack the broadcast path."""
    ip = (req.ip or "").strip()
    if not ip:
        raise HTTPException(status_code=400, detail="ip required")
    try:
        ports = await _scan_ports_for_ip(ip)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ip": ip, "ports": ports}


@router.get("/wifi/tunnel/discover")
async def wifi_tunnel_discover():
    """Find iPhones on the local network. First tries mDNS (Bonjour RemotePairing
    broadcast); if that yields nothing, falls back to a /24 subnet TCP scan on the
    standard RemotePairing port (49152).

    Each result carries:
      - ``bonjour_id``: stable id stripped from the ``_remotepairing._tcp.local.``
        PTR (empty for TCP-scan fallback). The frontend echoes it back to
        /wifi/tunnel/start-and-connect so we can remember the DeviceName.
      - ``name``: human-readable label for the picker — cached DeviceName from
        a previous connect when we recognise ``bonjour_id``; otherwise the
        bare bonjour_id (still way better than a full PTR), and as a last
        resort the IP (TCP-scan path).
    """
    # Loaded once per call. The cache is small (one entry per iPhone the user
    # has ever WiFi-paired through LocWarp) and we'd rather pay one read than
    # hammer the disk per discovered device.
    from core.device_manager import strip_bonjour_suffix, _load_wifi_alias_cache
    alias_cache = _load_wifi_alias_cache()

    results: list[dict] = []

    # --- 1) mDNS / Bonjour broadcast ---
    try:
        from pymobiledevice3.bonjour import browse_remotepairing
        instances = await browse_remotepairing(timeout=3.0)
        for inst in instances:
            # Newer pymobiledevice3 returns Address objects with .ip and
            # .iface attributes; older releases returned plain string IPs.
            # Pull the bare IP either way so the UI shows e.g.
            # "192.168.0.185" not "Address(ip='192.168.0.185',
            # iface='Intel(R) Ethernet Controller (3) I225-V')".
            raw_addrs = inst.addresses or []
            str_addrs: list[str] = []
            for a in raw_addrs:
                if hasattr(a, "ip"):
                    str_addrs.append(str(a.ip))
                else:
                    str_addrs.append(str(a))
            ipv4s = [s for s in str_addrs if ":" not in s]
            addrs = ipv4s if ipv4s else str_addrs
            bonjour_id = strip_bonjour_suffix(inst.instance)
            # alias_cache holds the user's DeviceName from the previous
            # successful connect for this Bonjour id. If we don't have one
            # yet, fall back to the stripped bonjour_id — at least it's
            # short, stable, and not an IPv6 link-local.
            alias = alias_cache.get(bonjour_id)
            if alias and alias.get("name"):
                display_name = alias["name"]
            elif bonjour_id:
                display_name = bonjour_id
            else:
                display_name = inst.host or ""
            for addr in addrs:
                results.append({
                    "ip": addr,
                    "port": inst.port,
                    "host": inst.host,
                    "name": display_name,
                    "bonjour_id": bonjour_id,
                    "method": "mdns",
                })
    except Exception as e:
        _tunnel_logger.warning("mDNS browse failed: %s", e)

    # --- 2) Fallback: smart /24 scan ---
    # Old behavior tested only port 49152 across /24, which missed any iPhone
    # that bound RemotePairing higher in the 49152-65535 dynamic range (most
    # of them, after the first reboot). Two-phase replacement:
    #   a) probe every host on /24 against a small set of "iPhone tells"
    #      (49152 legacy port + 62078 lockdown) to find live candidates
    #   b) full-range scan (49152-65535) on each candidate to find the
    #      port iOS actually picked this boot
    if not results:
        _tunnel_logger.info(
            "mDNS empty; falling back to smart /24 scan (probe + full-range)",
        )
        try:
            my_ip = _get_primary_local_ip()
            candidates: set[str] = set()
            if my_ip:
                # Phase a: probe a few likely ports across the /24 in
                # parallel. ANY hit means "host is alive and probably
                # interesting" — we'll full-range scan it next.
                probe_ports = (49152, 62078)
                for p in probe_ports:
                    try:
                        hits = await _scan_subnet_for_port(p)
                        candidates.update(hits)
                    except Exception as e:
                        _tunnel_logger.warning("probe scan port %d failed: %s", p, e)

            if candidates:
                _tunnel_logger.info(
                    "Smart scan found %d live host(s); full-range scanning each",
                    len(candidates),
                )
                # Phase b: full 49152-65535 scan in parallel across all
                # candidate IPs. RemotePairing answers immediately on the
                # right port, so the first hit per IP is what we want.
                async def _scan_one(ip: str) -> tuple[str, list[int]]:
                    try:
                        ports = await _scan_ports_for_ip(ip)
                    except Exception as e:
                        _tunnel_logger.warning("port scan for %s failed: %s", ip, e)
                        return ip, []
                    return ip, ports

                scan_results = await asyncio.gather(
                    *[_scan_one(ip) for ip in candidates],
                )
                for ip, ports in scan_results:
                    if not ports:
                        continue
                    # Use the first open port in the dynamic range. We
                    # add one entry per IP — the user picks from the list.
                    # No Bonjour data on this path, so no alias lookup is
                    # possible; the IP is the only meaningful label.
                    results.append({
                        "ip": ip,
                        "port": ports[0],
                        "host": ip,
                        "name": ip,
                        "bonjour_id": "",
                        "method": "tcp_scan",
                    })
        except Exception as e:
            _tunnel_logger.warning("Smart fallback scan failed: %s", e)

    # De-dupe on (ip, port)
    seen = set()
    unique = []
    for r in results:
        key = (r["ip"], r["port"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)

    return {"devices": unique}


async def _cleanup_wifi_connection_for(udid: str, *, caller: str) -> bool:
    """Disconnect a single WiFi-connected device + drop its sim engine.
    Broadcasts device_disconnected for that udid so the frontend chip
    flips to disconnected. Returns True iff a Network connection was found
    and torn down.

    The engine MUST be stopped before the dm.disconnect closes the RSD —
    otherwise its in-flight task (random_walk / loop / multi_stop /
    navigate / _move_along_route) keeps trying to push positions through
    the now-dead RSD, hits DeviceLostError, retries, fails again, and
    floods the log with `Giving up on this route after repeated push
    failures` every ~2 seconds for as long as LocWarp stays open.
    Mirrors the USB watchdog teardown sequence in main.py:387-418."""
    from main import app_state
    dm = _dm()
    conn = dm._connections.get(udid)
    if conn is None or getattr(conn, "connection_type", "") != "Network":
        return False

    # Stop the running simulation BEFORE we close the underlying lockdown,
    # so its retry loop doesn't get a chance to log a dozen DeviceLostError
    # rounds against the dying RSD.
    old_eng = app_state.simulation_engines.get(udid)
    if old_eng is not None:
        try:
            from models.schemas import SimulationState as _SS
            old_eng.state = _SS.DISCONNECTED
            try:
                await old_eng._emit("state_change", {"state": old_eng.state.value})
            except Exception:
                _tunnel_logger.debug(
                    "[%s] disconnected state_change emit failed", caller, exc_info=True,
                )
            old_eng._stop_event.set()
            old_eng._pause_event.set()  # unstick anyone awaiting pause_event
            active = getattr(old_eng, "_active_task", None)
            if active is not None and not active.done():
                active.cancel()
        except Exception:
            _tunnel_logger.debug(
                "[%s] failed to stop old engine for %s", caller, udid, exc_info=True,
            )

    try:
        await dm.disconnect(udid)
        _tunnel_logger.info("[%s] Disconnected WiFi device %s", caller, udid)
    except (OSError, RuntimeError):
        _tunnel_logger.exception("[%s] Failed to disconnect %s", caller, udid)
    await app_state.remove_engine(udid)
    try:
        await dm._events.publish(("device_disconnected", {
            "udid": udid,
            "udids": [udid],
            "reason": "wifi_tunnel_stopped",
            "remaining_count": len(dm._connections),
        }))
    except Exception:
        _tunnel_logger.exception("[%s] WiFi cleanup broadcast failed", caller)
    return True


async def _cleanup_all_wifi_connections(caller: str = "unknown") -> list[str]:
    """Disconnect every Network device + drop their sim engines. Used by
    the legacy stop-all flow and shutdown paths."""
    import traceback
    dm = _dm()
    stack = traceback.extract_stack(limit=8)[:-1]
    stack_str = " <- ".join(f"{fr.name}@{fr.filename.split(chr(92))[-1]}:{fr.lineno}" for fr in reversed(stack))
    _tunnel_logger.warning(
        "_cleanup_all_wifi_connections called (caller=%s); stack: %s",
        caller, stack_str,
    )
    udids = [
        udid for udid, conn in list(dm._connections.items())
        if getattr(conn, "connection_type", "") == "Network"
    ]
    for udid in udids:
        await _cleanup_wifi_connection_for(udid, caller=caller)
    return udids


async def _tear_down_tunnel(udid: str, *, caller: str) -> None:
    """Cancel this udid's watchdog (if any) and stop the runner. Caller
    decides whether to also clean up the DM connection."""
    wd = _tunnel_watchdogs.pop(udid, None)
    if wd is not None and not wd.done():
        wd.cancel()
        try:
            await wd
        except (asyncio.CancelledError, Exception):
            pass
    runner = _tunnels.pop(udid, None)
    if runner is not None:
        try:
            await runner.stop()
        except Exception:
            _tunnel_logger.exception("[%s] runner.stop failed for %s", caller, udid)


# Restart backoff sequence (seconds). Three attempts cover most WiFi blips
# (transient packet loss, brief screen-lock pause) without sitting on a dead
# tunnel for an unbounded time. Total worst-case wait ~21s before final
# teardown — within the user's tolerance for "auto-recovers" before they'd
# look at the UI and notice.
_TUNNEL_RESTART_BACKOFF: tuple[float, ...] = (3.0, 6.0, 12.0)


async def _attempt_tunnel_restart(
    udid: str,
    ip: str,
    port: int,
    snapshot: dict | None,
    original_runner: TunnelRunner,
) -> bool:
    """Thin api-layer wrapper: resolves the live collaborators and delegates to
    the relocated infra implementation. Behavior is identical to the
    pre-relocation function; see infra/device/tunnel_restart."""
    from main import app_state, _auto_sync_new_device_to_primary
    from infra.device.tunnel_restart import attempt_tunnel_restart

    dm = _dm()

    async def broadcast(event_type, payload):
        await dm._events.publish((event_type, payload))

    def _watchdog_factory(u: str, runner: TunnelRunner):
        return asyncio.create_task(_per_tunnel_watchdog(u, runner))

    return await attempt_tunnel_restart(
        udid, ip, port, snapshot, original_runner,
        engine_registry=app_state, device_manager=dm, broadcast=broadcast,
        auto_sync=_auto_sync_new_device_to_primary, watchdog_factory=_watchdog_factory,
    )


async def _per_tunnel_watchdog(udid: str, runner: TunnelRunner) -> None:
    """Watch a single device's tunnel. If the runner's task dies (WiFi
    blip, iPhone locked, admin revoked), capture the sim state, then try
    up to len(_TUNNEL_RESTART_BACKOFF) restarts with backoff. Each restart
    rebuilds the device manager connection (the new TUN interface gets a
    fresh RSD address) and resumes the sim from snapshot so the iPhone
    keeps moving across the blip. Other tunnels stay isolated."""
    dm = _dm()
    try:
        task = runner.task
        if task is None:
            return
        try:
            await task
        except asyncio.CancelledError:
            return
        except BaseException:
            pass

        # If the registry was already updated (explicit stop, re-key on
        # reconnect, etc.) this watchdog is stale.
        if _tunnels.get(udid) is not runner:
            return

        ip = runner.target_ip
        port = runner.target_port

        _tunnel_logger.warning(
            "Tunnel for %s exited unexpectedly (target=%s:%s); will attempt %d restart(s)",
            udid, ip, port, len(_TUNNEL_RESTART_BACKOFF),
        )
        try:
            await dm._events.publish(("tunnel_degraded", {"udid": udid, "reason": "task_exited"}))
        except Exception:
            _tunnel_logger.exception("Failed to emit tunnel_degraded event")

        if ip is None or port is None:
            # No target captured; we have nothing to retry against. Fall
            # through to teardown.
            _tunnel_logger.warning(
                "Tunnel for %s has no captured target ip/port; skipping retries",
                udid,
            )
        else:
            from main import app_state
            snapshot: dict | None = None
            old_eng = app_state.simulation_engines.get(udid)
            if old_eng is not None:
                try:
                    snapshot = old_eng.capture_resumable_snapshot()
                    if snapshot:
                        _tunnel_logger.info(
                            "Captured resumable snapshot for %s before tunnel restart (kind=%s)",
                            udid, snapshot.get("kind"),
                        )
                except Exception:
                    _tunnel_logger.exception("capture_resumable_snapshot failed for %s", udid)

                # Park the engine while we restart. Without this, multi-stop /
                # loop / random-walk keep iterating to the next leg, each call
                # burning ~3s in DvtLocationService._reconnect retries against
                # the dead RSD before raising DeviceLostError, then the handler
                # immediately tries the next leg. The log fills with "Giving up
                # on this route after repeated push failures" every ~6s for as
                # long as the watchdog is mid-restart. Cancelling the active
                # task here halts the thrash; on a successful restart, the
                # snapshot we just captured drives resume_from_snapshot back to
                # the same leg / segment.
                try:
                    from models.schemas import SimulationState as _SS
                    old_eng.state = _SS.DISCONNECTED
                    try:
                        await old_eng._emit("state_change", {"state": old_eng.state.value})
                    except Exception:
                        _tunnel_logger.debug(
                            "Disconnected state_change emit failed during watchdog pause",
                            exc_info=True,
                        )
                    old_eng._stop_event.set()
                    old_eng._pause_event.set()  # unstick anyone awaiting pause_event
                    active = getattr(old_eng, "_active_task", None)
                    if active is not None and not active.done():
                        active.cancel()
                except Exception:
                    _tunnel_logger.exception(
                        "Failed to park engine for %s before tunnel restart", udid,
                    )

            for attempt, delay in enumerate(_TUNNEL_RESTART_BACKOFF, start=1):
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    return

                # User may have explicitly stopped or replaced this tunnel
                # during the sleep; if so, abort the retry loop.
                if _tunnels.get(udid) is not runner:
                    _tunnel_logger.info(
                        "Tunnel for %s no longer registered (user stop?); aborting retries",
                        udid,
                    )
                    return

                _tunnel_logger.info(
                    "Tunnel restart attempt %d/%d for %s (after %.0fs backoff)",
                    attempt, len(_TUNNEL_RESTART_BACKOFF), udid, delay,
                )
                ok = await _attempt_tunnel_restart(udid, ip, port, snapshot, runner)
                if ok:
                    # On success the new watchdog has been armed and this
                    # one's job is done.
                    return

        # All retries exhausted (or no target to retry against).
        _tunnel_logger.warning(
            "Tunnel for %s could not be restarted; tearing down WiFi connection",
            udid,
        )
        async with _tunnels_lock:
            current = _tunnels.get(udid)
            if current is runner:
                _tunnels.pop(udid, None)
            wd = _tunnel_watchdogs.pop(udid, None)
            if wd is not None and wd is not asyncio.current_task() and not wd.done():
                wd.cancel()
            await _cleanup_wifi_connection_for(udid, caller="watchdog_tunnel_died")
            try:
                await dm._events.publish(("tunnel_lost", {"udid": udid, "reason": "task_exited"}))
            except Exception:
                _tunnel_logger.exception("Failed to emit tunnel_lost event")
    except asyncio.CancelledError:
        raise


def _build_tunnel_udid_candidates(req: WifiTunnelStartRequest) -> list[str]:
    """Return udids to try for an incoming /wifi/tunnel/start request,
    in priority order:

    1. The udid the caller explicitly passed (always trusted)
    2. Currently USB-tracked udids (most likely correct in single-device
       use, and for the dual-device USB+WiFi flow)
    3. Cached pair records under ~/.pymobiledevice3/, sorted by mtime
       (most recently used first) — needed when the user opens LocWarp
       without USB and just types an IP

    The list is de-duped while preserving order. Caller iterates them;
    pair-verify fails fast (~200-400ms) on a wrong identifier so trying
    several is cheap. Bug history: v0.2.92 only used the first candidate,
    which broke multi-iPhone users whose target's pair record happened
    to not be the most-recently-used one."""
    candidates: list[str] = []

    def _add(c: str | None) -> None:
        if c and c not in candidates:
            candidates.append(c)

    _add(req.udid)
    try:
        dm = _dm()
        for u in dm._connections.keys():
            _add(u)
    except (RuntimeError, AttributeError):
        pass
    try:
        from pymobiledevice3.pair_records import iter_remote_pair_records
        records = sorted(
            iter_remote_pair_records(),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for rec in records:
            stem = rec.name
            if stem.startswith("remote_"):
                stem = stem.split("remote_", 1)[1]
            ident = stem.split(".", 1)[0]
            _add(ident)
    except Exception:
        _tunnel_logger.debug("Could not enumerate cached pair records", exc_info=True)

    if not candidates:
        candidates.append(f"pending:{req.ip}:{req.port}")
    return candidates


@router.post("/wifi/tunnel/start")
async def wifi_tunnel_start(req: WifiTunnelStartRequest):
    """Start an in-process WiFi tunnel for one device (requires admin).

    The runner is keyed in _tunnels by the actual udid once we resolve
    which paired iPhone is at the requested IP/port. Resolution iterates
    candidate udids (req.udid > USB-tracked > cached pair records) and
    keeps the one whose pair-verify handshake actually succeeds. The
    tunnel cap is enforced separately from the device cap so we don't
    accidentally start a 4th tunnel while only 3 devices are visible to
    dm._connections."""
    async with _tunnels_lock:
        # Active runners count toward the cap. Stale entries get pruned
        # so a crashed tunnel doesn't permanently block reconnect.
        live_count = sum(1 for r in _tunnels.values() if r.is_running())
        if live_count >= MAX_DEVICES:
            raise HTTPException(
                status_code=409,
                detail={"code": "max_devices_reached", "message": f"已連接最多 {MAX_DEVICES} 台裝置"},
            )

        candidates = _build_tunnel_udid_candidates(req)
        _tunnel_logger.info(
            "WiFi tunnel start: ip=%s port=%d candidates=%s",
            req.ip, req.port, candidates,
        )

        # If any candidate already has a running tunnel for the same
        # (ip, port) target, that one wins immediately — idempotent
        # re-click. We compare target_ip/port (not just udid) so a
        # tunnel for a DIFFERENT iPhone doesn't get returned when the
        # user is now trying to connect a new device.
        for cand in candidates:
            existing = _tunnels.get(cand)
            if (
                existing is not None
                and existing.is_running()
                and existing.target_ip == req.ip
                and existing.target_port == req.port
            ):
                return {"status": "already_running", "udid": cand, **(existing.info or {})}

        last_error: Exception | None = None
        for cand in candidates:
            existing = _tunnels.get(cand)
            if existing is not None and existing.is_running():
                # This udid already owns a tunnel for a DIFFERENT (ip,
                # port). Don't tear it down — that would kill an active
                # connection the user isn't asking us to touch. Just skip
                # this candidate and try the next one.
                _tunnel_logger.debug(
                    "Skipping candidate %s: already tunneling to %s:%s "
                    "(user requested %s:%s)",
                    cand, existing.target_ip, existing.target_port,
                    req.ip, req.port,
                )
                continue
            if existing is not None:
                # Stale entry (runner not running but slot still held);
                # safe to clean up before reusing.
                await _tear_down_tunnel(cand, caller="start_replace_stale")

            _tunnel_logger.info(
                "Trying WiFi tunnel with udid=%s ip=%s port=%d",
                cand, req.ip, req.port,
            )

            # Per-candidate timeout is shorter than the legacy 20s budget.
            # Pair-verify against the wrong iPhone fails in well under a
            # second; if a candidate hasn't responded in 8s the iPhone is
            # almost certainly unreachable on the network and the next
            # candidate would just hit the same wall, so the loop bails
            # below on TimeoutError.
            runner = TunnelRunner()
            try:
                info = await runner.start(cand, req.ip, req.port, timeout=8.0)
            except asyncio.TimeoutError as e:
                last_error = e
                _tunnel_logger.warning(
                    "WiFi tunnel timed out for udid=%s; iPhone may be "
                    "unreachable on the network — stopping further "
                    "candidates",
                    cand,
                )
                # Network-level timeout: trying more udids is unlikely to
                # help. Surface the timeout error to the caller.
                raise HTTPException(
                    status_code=500,
                    detail={"code": "tunnel_timeout", "message": "Tunnel 啟動逾時"},
                ) from e
            except Exception as e:
                last_error = e
                _tunnel_logger.info(
                    "WiFi tunnel candidate %s failed (%s); trying next",
                    cand, type(e).__name__,
                )
                continue

            _tunnels[cand] = runner
            _tunnel_watchdogs[cand] = asyncio.create_task(
                _per_tunnel_watchdog(cand, runner)
            )
            _tunnel_logger.info("WiFi tunnel started for %s: %s", cand, info)
            return {"status": "started", "udid": cand, **info}

        # All candidates exhausted without a successful handshake.
        msg = f"無法啟動 tunnel:{last_error}" if last_error else "無法啟動 tunnel"
        raise HTTPException(
            status_code=500,
            detail={"code": "tunnel_spawn_failed", "message": msg},
        )


@router.get("/wifi/tunnel/status")
async def wifi_tunnel_status():
    """Return all active WiFi tunnels with their RSD info.

    The response shape is forward-compatible: the canonical payload is
    `{"tunnels": [{"udid", "rsd_address", "rsd_port", ...}, ...]}`. Legacy
    fields (`running`, `rsd_address`, `rsd_port`) mirror the FIRST tunnel
    so older single-tunnel callers keep working until they migrate."""
    dm = _dm()
    tunnels: list[dict] = []
    for udid, runner in list(_tunnels.items()):
        if not runner.is_running():
            continue
        entry: dict = {"udid": udid, **(runner.info or {})}
        # Surface a display name so the WiFi-tunnel UI doesn't fall back
        # to a UDID slice when no USB device entry exists for this udid.
        name = dm.get_display_name(udid)
        if name:
            entry["name"] = name
        tunnels.append(entry)

    legacy = {"running": len(tunnels) > 0}
    if tunnels:
        legacy.update({k: v for k, v in tunnels[0].items() if k != "udid"})
    return {"tunnels": tunnels, **legacy}


class WifiTunnelStopRequest(BaseModel):
    udid: str | None = None  # None = stop ALL tunnels (legacy stop-all path)


@router.post("/wifi/tunnel/stop")
async def wifi_tunnel_stop(req: WifiTunnelStopRequest | None = None):
    """Stop a specific WiFi tunnel by udid, or all if udid is None.

    Per-udid stop tears down only the named tunnel and its DM
    connection — other tunnels keep running. The legacy stop-all path
    (no udid) preserves prior single-tunnel behaviour for callers that
    haven't migrated yet."""
    target_udid = req.udid if req else None
    dm = _dm()

    _tunnel_logger.warning(
        "/wifi/tunnel/stop endpoint hit. target_udid=%s, active_tunnels=%d, network_conns=%d",
        target_udid,
        sum(1 for r in _tunnels.values() if r.is_running()),
        sum(1 for c in dm._connections.values() if getattr(c, "connection_type", "") == "Network"),
    )

    async with _tunnels_lock:
        if target_udid is not None:
            if target_udid not in _tunnels and target_udid not in dm._connections:
                return {"status": "not_running", "udid": target_udid}
            udids_to_stop = [target_udid]
        else:
            # Stop everything: union of registered tunnels and any orphan
            # WiFi connections (defensive — shouldn't normally happen).
            udids_to_stop = list({
                *_tunnels.keys(),
                *(udid for udid, c in dm._connections.items()
                  if getattr(c, "connection_type", "") == "Network"),
            })

        if not udids_to_stop:
            return {"status": "not_running"}

        # Snapshot for the USB fallback step below: only re-attach via USB
        # the udids that just had a WiFi conn here, AND skip pending: keys
        # which were only ever placeholders.
        was_network_udids = [u for u in udids_to_stop if not u.startswith("pending:")]

        for udid in udids_to_stop:
            await _cleanup_wifi_connection_for(udid, caller="wifi_tunnel_stop_endpoint")
            await _tear_down_tunnel(udid, caller="wifi_tunnel_stop_endpoint")

    # USB fallback: only re-attach udids that were just in WiFi AND show
    # up as USB right now (covers users plugging in a cable mid-stop).
    try:
        from main import app_state
        devices = await dm.discover_devices()
        for udid in was_network_udids:
            # Never resurrect a Trust prompt for a device the user has
            # forgotten / tapped Don't Trust on. The Re-trust button is
            # the only path back (it clears this flag).
            if udid in dm.sticky_user_denied:
                _tunnel_logger.info(
                    "USB fallback: skipping %s (sticky_user_denied)", udid,
                )
                continue
            usb_dev = next(
                (d for d in devices if d.udid == udid and d.connection_type == "USB"),
                None,
            )
            if usb_dev is None:
                _tunnel_logger.info(
                    "USB fallback: skipping %s (not visible as USB after tunnel stop)",
                    udid,
                )
                continue
            try:
                await dm.connect(usb_dev.udid)
            except Exception:
                _tunnel_logger.exception("USB fallback: connect failed for %s", usb_dev.udid)
                continue
            try:
                await app_state.create_engine_for_device(usb_dev.udid, force=True)
                _tunnel_logger.info("Switched back to USB connection: %s", usb_dev.udid)
            except Exception:
                _tunnel_logger.exception(
                    "USB fallback: engine creation failed for %s; rolling back",
                    usb_dev.udid,
                )
                try:
                    await dm.disconnect(usb_dev.udid)
                except Exception:
                    pass
                await app_state.remove_engine(usb_dev.udid)
                try:
                    await dm._events.publish(("device_error", {
                        "udid": usb_dev.udid,
                        "stage": "usb_fallback",
                        "error": "USB fallback engine creation failed",
                    }))
                except Exception:
                    pass
    except Exception:
        _tunnel_logger.exception("USB fallback after tunnel stop failed")

    return {"status": "stopped", "udids": udids_to_stop}


@router.post("/wifi/tunnel/start-and-connect")
async def wifi_tunnel_start_and_connect(req: WifiTunnelStartRequest):
    """Start a WiFi tunnel and immediately connect the device through it.

    Re-keys the runner from any temporary IP-based key to the real udid
    after dm.connect_wifi_tunnel reveals the device identity. This is the
    primary entrypoint the frontend uses; /start and /wifi/tunnel exist as
    separate primitives but are not chained from the UI today."""
    from main import app_state

    # Cap check before we even spawn a runner. Counts active runners,
    # not dm._connections — a tunnel that's mid-handshake but not yet
    # registered as a device connection still consumes a slot.
    async with _tunnels_lock:
        live_count = sum(1 for r in _tunnels.values() if r.is_running())
        if live_count >= MAX_DEVICES:
            raise HTTPException(
                status_code=409,
                detail={"code": "max_devices_reached", "message": f"已連接最多 {MAX_DEVICES} 台裝置"},
            )

    tunnel_result = await wifi_tunnel_start(req)
    if tunnel_result.get("status") not in ("started", "already_running"):
        raise HTTPException(status_code=500, detail="Tunnel failed to start")

    rsd_address = tunnel_result.get("rsd_address")
    rsd_port = tunnel_result.get("rsd_port")
    temp_key = tunnel_result.get("udid")

    if not rsd_address or not rsd_port:
        raise HTTPException(status_code=500, detail="Tunnel started but no RSD info available")

    dm = _dm()
    if len(dm._connections) >= MAX_DEVICES:
        raise HTTPException(
            status_code=409,
            detail={"code": "max_devices_reached", "message": f"已連接最多 {MAX_DEVICES} 台裝置"},
        )
    try:
        info = await dm.connect_wifi_tunnel(
            rsd_address, rsd_port, bonjour_id=req.bonjour_id
        )
        # v0.2.60: Drop the stale engine from the prior USB conn so
        # create_engine_for_device rebuilds a fresh one bound to the new
        # WiFi RSD. v0.2.57 made create_engine_for_device idempotent (to
        # survive the watchdog loop wiping current_position), but that
        # means on a USB→WiFi conn switch it would keep the old engine —
        # whose location_service._lockdown still points at the now-closed
        # USB RSD. First teleport over WiFi would then throw
        # ConnectionTerminatedError, reconnect would fail because the
        # cached lockdown is dead, and the user would see the device get
        # kicked as device_lost within 8 seconds of the WiFi switch.
        await app_state.create_engine_for_device(info.udid, force=True)

        # Re-key the runner from temp_key (often "pending:ip:port") to
        # the real udid so per-udid stop / status / watchdog keep working.
        if temp_key and temp_key != info.udid:
            async with _tunnels_lock:
                runner = _tunnels.pop(temp_key, None)
                old_wd = _tunnel_watchdogs.pop(temp_key, None)
                if old_wd is not None and not old_wd.done():
                    old_wd.cancel()
                if runner is not None and runner.is_running():
                    # Replace any pre-existing entry under the real udid
                    # (defensive — shouldn't happen in normal flow).
                    prior = _tunnels.pop(info.udid, None)
                    if prior is not None and prior is not runner:
                        try:
                            await prior.stop()
                        except Exception:
                            pass
                    prior_wd = _tunnel_watchdogs.pop(info.udid, None)
                    if prior_wd is not None and not prior_wd.done():
                        prior_wd.cancel()
                    _tunnels[info.udid] = runner
                    _tunnel_watchdogs[info.udid] = asyncio.create_task(
                        _per_tunnel_watchdog(info.udid, runner)
                    )

        return {
            "status": "connected",
            "udid": info.udid,
            "name": info.name,
            "ios_version": info.ios_version,
            "connection_type": "Network",
            "rsd_address": rsd_address,
            "rsd_port": rsd_port,
        }
    except Exception as e:
        # On failure, tear down the runner we just started so we don't
        # leave a zombie tunnel + leaked watchdog.
        if temp_key:
            try:
                async with _tunnels_lock:
                    await _tear_down_tunnel(temp_key, caller="start_and_connect_failed")
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Tunnel started but connection failed: {e}")


# ── Generic UDID routes (MUST be defined after all specific /wifi/* routes
#    so that /wifi/* paths do not accidentally match {udid}). ─────────────

@router.post("/{udid}/amfi/reveal-developer-mode")
async def amfi_reveal_developer_mode(udid: str):
    """Make iOS's "Developer Mode" option appear in Settings → Privacy &
    Security. Same end state as side-loading a developer-signed IPA via
    Sideloadly / Xcode, but done directly through AMFI so the user doesn't
    need a third-party side-loader. iOS 16+ only.

    This is action 0 (REVEAL) of the com.apple.amfi.lockdown service. It
    just creates the AMFIShowOverridePath marker file on the device —
    no reboot, no passcode prompt, completely safe. The user still has
    to open Settings and toggle Developer Mode on themselves (which iOS
    will then require passcode removal + reboot for, per Apple's rules).
    """
    dm = _dm()
    conn = dm._connections.get(udid)
    if conn is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "device_not_connected", "message": "裝置未連線,請先連線再試"},
        )

    # iOS 15 and below have no Developer Mode concept.
    try:
        major = int((conn.ios_version or "0.0").split(".")[0])
    except Exception:
        major = 0
    if major < 16:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "ios_too_old",
                "message": f"iOS {conn.ios_version} 沒有開發者模式,不需要此操作",
            },
        )

    try:
        from pymobiledevice3.services.amfi import AmfiService
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "amfi_not_available", "message": f"AMFI 服務載入失敗: {exc}"},
        )

    # AMFI is a legacy lockdown service (com.apple.amfi.lockdown) that's only
    # advertised on the classic USB lockdown, NOT on iOS 17+'s RSD tunnel.
    # For iOS 17+ devices we stash the original USB lockdown on
    # conn.usbmux_lockdown; use it here. For iOS 16 devices conn.lockdown
    # IS the USB lockdown, so fall back to it.
    amfi_lockdown = getattr(conn, "usbmux_lockdown", None) or conn.lockdown
    if amfi_lockdown is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "amfi_needs_usb",
                "message": "AMFI 需要走 USB 連線。請插 USB 後再試(WiFi tunnel 不 advertise AMFI 服務)。",
            },
        )

    try:
        await AmfiService(amfi_lockdown).reveal_developer_mode_option_in_ui()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "amfi_reveal_failed",
                "message": f"AMFI reveal 失敗: {exc.__class__.__name__}: {exc}",
            },
        )

    return {"status": "ok"}


@router.post("/{udid}/connect")
async def connect_device(udid: str, device_service=Depends(get_device_service)):
    from core.device_manager import UnsupportedIosVersionError
    dm = device_service._dm
    # Group-mode device cap. Allow re-connect of an already-connected udid.
    if udid not in dm._connections and len(dm._connections) >= MAX_DEVICES:
        raise HTTPException(
            status_code=409,
            detail={"code": "max_devices_reached", "message": f"已連接最多 {MAX_DEVICES} 台裝置"},
        )
    try:
        await device_service.connect(udid)
        try:
            devs = await dm.discover_devices()
            info = next((d for d in devs if d.udid == udid), None)
            await dm._events.publish(("device_connected", {
                "udid": udid,
                "name": info.name if info else "",
                "ios_version": info.ios_version if info else "",
                "connection_type": info.connection_type if info else "USB",
            }))
        except Exception:
            pass
        return {"status": "connected", "udid": udid}
    except UnsupportedIosVersionError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "ios_unsupported",
                "message": (
                    f"偵測到 iOS {e.version},LocWarp 自 v0.1.49 起僅支援 "
                    f"iOS {UnsupportedIosVersionError.MIN_VERSION} 以上。"
                    f"請將裝置升級至 iOS {UnsupportedIosVersionError.MIN_VERSION} 或更新版本後再連線。"
                ),
                "ios_version": e.version,
                "min_version": UnsupportedIosVersionError.MIN_VERSION,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{udid}/connect")
async def disconnect_device(udid: str, device_service=Depends(get_device_service)):
    # Drop the per-udid engine + dm connection via the service.
    await device_service.disconnect(udid)
    try:
        await device_service._dm._events.publish(
            ("device_disconnected", {"udid": udid, "udids": [udid], "reason": "user"})
        )
    except Exception:
        pass
    return {"status": "disconnected", "udid": udid}


@router.post("/{udid}/forget")
async def forget_device(udid: str):
    """Forget a device — Bluetooth-style. iPhone-side unpair (best-effort),
    session teardown, host pair-record removal, and persistent watchdog
    suppression via sticky_user_denied.

    Idempotent: forgetting an unknown or already-forgotten udid still
    returns 200 (record deletes are idempotent; set-add is idempotent).
    The user's path back is the Re-trust button (wifi/repair), which
    clears the sticky flag and re-triggers the iPhone Trust prompt.
    """
    from main import app_state
    from services.usbmux_pair_records import (
        acquire_pair_lock,
        delete_local_pair_record,
        delete_system_pair_record,
    )

    dm = _dm()
    lock = await acquire_pair_lock(udid)
    async with lock:
        # 1. iPhone-side unpair (best-effort) — needs the live session.
        #    Failure is fine: host-side cleanup below is sufficient for
        #    LocWarp's own behavior; the iPhone merely keeps a dangling
        #    host entry (today's status quo for every stale record).
        conn = dm._connections.get(udid)
        if conn is not None:
            unpair_lockdown = getattr(conn, "usbmux_lockdown", None) or conn.lockdown
            try:
                await unpair_lockdown.unpair()
                _tunnel_logger.info("Forget: iPhone-side unpair OK for %s", udid)
            except Exception:
                _tunnel_logger.debug(
                    "Forget: iPhone-side unpair failed for %s (continuing)",
                    udid, exc_info=True,
                )

        # 2. Session teardown. WiFi path mirrors wifi_tunnel_stop's
        #    per-udid sequence; USB path mirrors disconnect_device.
        async with _tunnels_lock:
            await _cleanup_wifi_connection_for(udid, caller="forget_device")
            await _tear_down_tunnel(udid, caller="forget_device")
        if udid in dm._connections:
            try:
                await dm.disconnect(udid)
            except Exception:
                _tunnel_logger.exception("Forget: disconnect failed for %s", udid)
        await app_state.remove_engine(udid)

        # 3. Clear host pair records (both idempotent, never raise).
        system_cleared = await delete_system_pair_record(udid)
        local_cleared = delete_local_pair_record(udid)

        # 4. Suppress the watchdog's auto-re-pair (persisted across restarts).
        dm.mark_user_denied(udid)

    # 5. Notify the frontend.
    try:
        await dm._events.publish(("device_disconnected", {
            "udid": udid, "udids": [udid], "reason": "forgotten",
            "remaining_count": len(dm._connections),
        }))
    except Exception:
        pass

    return {
        "status": "forgotten",
        "udid": udid,
        "system_cleared": system_cleared,
        "local_cleared": local_cleared,
    }


@router.get("/{udid}/info", response_model=DeviceInfo | None)
async def device_info(udid: str):
    dm = _dm()
    devices = await dm.discover_devices()
    for d in devices:
        if d.udid == udid:
            return d
    raise HTTPException(status_code=404, detail="Device not found")
