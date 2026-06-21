"""Characterization + regression guard for the mDNS-ENOBUFS event-loop wedge.

Root cause (PRE-EXISTING — not P1/P2; see the project memory note): pymobiledevice3
``browse_remotepairing`` (behind ``GET /api/device/wifi/tunnel/discover``) opens one
mDNS multicast socket per network interface. When one of those interfaces is a
torn-down WiFi-tunnel ``utunN``, its multicast ``sendmsg`` fails with **ENOBUFS**.
Under **uvloop** the datagram transport (libuv) BUSY-RETRIES the failing send,
pegging a core at 100% CPU and starving the whole event loop — every HTTP/WS
request then hangs (observed in prod via ``fs_usage``: a ``sendmsg`` ENOBUFS flood
on the ``:5353`` sockets). **stdlib asyncio** instead DROPS such a datagram
(``error_received`` fires once, no retry).

Fix: launch uvicorn with ``loop="asyncio"`` instead of the default ``"auto"``
(which selects uvloop). The first test pins the *premise* (stdlib drops ENOBUFS);
the last two pin the *fix* (the backend forces the asyncio loop).
"""
import asyncio
import errno
import socket

import pytest


class _ENOBUFSSocket(socket.socket):
    """UDP socket whose send/sendto always raise ENOBUFS, counting attempts."""

    sends = 0

    def send(self, data, *args, **kwargs):
        type(self).sends += 1
        raise OSError(errno.ENOBUFS, "No buffer space available")

    def sendto(self, data, *args, **kwargs):
        type(self).sends += 1
        raise OSError(errno.ENOBUFS, "No buffer space available")


@pytest.mark.asyncio
async def test_stdlib_asyncio_drops_datagram_enobufs_without_spin():
    """PREMISE GUARD: on the stdlib asyncio loop a datagram whose send raises
    ENOBUFS is dropped (``error_received`` once) and NOT busy-retried. This is
    exactly the property uvloop lacks (it retries -> 100% CPU wedge) and is why
    the backend must run on ``loop="asyncio"``.
    """
    _ENOBUFSSocket.sends = 0

    class _Proto(asyncio.DatagramProtocol):
        def __init__(self):
            self.errors = 0

        def error_received(self, exc):
            self.errors += 1

    sock = _ENOBUFSSocket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.connect(("127.0.0.1", 9))  # connected -> transport uses sock.send()
    loop = asyncio.get_running_loop()
    transport, proto = await loop.create_datagram_endpoint(lambda: _Proto(), sock=sock)
    try:
        transport.sendto(b"x" * 16)   # the failing send
        await asyncio.sleep(0.2)      # pump; a busy-retry would explode .sends
    finally:
        transport.close()

    assert proto.errors >= 1, "ENOBUFS was not surfaced via error_received"
    assert _ENOBUFSSocket.sends <= 3, (
        f"datagram send was retried {_ENOBUFSSocket.sends}x — the loop is "
        "busy-spinning on ENOBUFS; the assumption behind loop=asyncio is broken"
    )


def test_backend_forces_stdlib_asyncio_loop():
    """RED->GREEN: the backend must declare the stdlib asyncio loop (not the
    default 'auto' which selects uvloop and busy-spins on the mDNS ENOBUFS send).
    """
    import main

    assert getattr(main, "UVICORN_LOOP", None) == "asyncio"


def test_run_server_passes_loop_asyncio(monkeypatch):
    """RED->GREEN: ``_run_server()`` must actually pass ``loop='asyncio'`` to
    ``uvicorn.run`` (a constant alone is not enough — it has to be wired)."""
    import main

    captured: dict = {}

    def _fake_run(app, **kwargs):
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(main.uvicorn, "run", _fake_run)
    main._run_server()
    assert captured.get("loop") == "asyncio"
