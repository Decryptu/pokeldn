"""The process that holds the Bluetooth link to the controller board and takes requests on
127.0.0.1 [docs/hardware_pad.md, The host side]. The app starts it as its own child: macOS aborts a
process that opens Bluetooth without NSBluetoothAlwaysUsageDescription, and only this one dies.

One JSON object per line each way. Requests: status, connect, send {report}, tap {report, ms},
play {macro}, stop, download, scan, disconnect, quit.
"""
import argparse
import asyncio
import hashlib
import json
import os
import socket
import threading

from pokeldn.pad import macro
from pokeldn.pad.link import Pad
from pokeldn.pad.serial_link import SerialPad, candidates

PORT = 47800


def _code() -> str:
    """The link code this process runs; an app finding a service with other code replaces it."""
    from pokeldn.pad import link, serial_link
    digest = hashlib.sha256()
    for module in (link, serial_link, macro):
        with open(module.__file__, "rb") as f:
            digest.update(f.read())
    with open(__file__, "rb") as f:
        digest.update(f.read())
    return digest.hexdigest()[:16]


CODE = _code()


async def connect_any(port: str = ""):
    """A classic board on a serial port when one answers, else the S3 over Bluetooth LE."""
    if port:
        return await SerialPad.connect(port)
    for device in candidates():
        try:
            return await SerialPad.connect(device)
        except Exception:
            continue
    return await Pad.connect()


class Service:
    def __init__(self, port: str = ""):
        self.port = port
        self.pad = None
        self.lock = asyncio.Lock()
        self.taps = 0

    async def ensure(self):
        if self.pad is None or not self.pad.connected:
            self.pad = None
            self.pad = await connect_any(self.port)
        return self.pad

    def link(self) -> str:
        return f"serial {self.pad.port}" if isinstance(self.pad, SerialPad) else "bluetooth"

    async def tap(self, report: bytes, ms: int):
        self.taps += 1
        mine = self.taps
        pad = await self.ensure()
        await pad.send(report)
        await asyncio.sleep(ms / 1000)
        if mine == self.taps:    # a later tap took over the report; it releases it
            await pad.send(macro.NEUTRAL)

    async def handle(self, req: dict) -> dict:
        op = req.get("op")
        if op == "status":
            if self.pad is None or not self.pad.connected:
                return {"ok": True, "connected": False, "code": CODE}
            s = await self.pad.status()
            return {"ok": True, "connected": True, "status": s.__dict__, "link": self.link(), "code": CODE}
        if op == "quit":
            if self.pad is not None:
                await self.pad.close()
            asyncio.get_running_loop().call_later(0.2, os._exit, 0)
            return {"ok": True}
        if op == "scan":
            from bleak import BleakScanner
            found = await BleakScanner.discover(timeout=8, return_adv=True)
            return {"ok": True, "out": [f"{d.address} {a.local_name or d.name} rssi {a.rssi}"
                                        for d, a in found.values()]}
        if op == "disconnect":
            if self.pad is not None:
                await self.pad.close()
                self.pad = None
            return {"ok": True}
        if op == "tap":
            # Answered at once: the release comes later, and the next tap may not wait for it.
            asyncio.ensure_future(self.tap(bytes.fromhex(req["report"]), int(req["ms"])))
            return {"ok": True}
        async with self.lock:
            pad = await self.ensure()
            if op == "connect":
                return {"ok": True}
            if op == "send":
                self.taps += 1
                await pad.send(bytes.fromhex(req["report"]))
            elif op == "play":
                program = macro.compile_macro(macro.loads(req["macro"]))
                await pad.load(program)
                await pad.play()
                return {"ok": True, "entries": len(program.entries), "setup_ms": program.setup_ms,
                        "loop_ms": program.loop_ms, "loops": program.loops}
            elif op == "stop":
                await pad.stop()
            elif op == "download":
                await pad.download()
            else:
                return {"ok": False, "error": f"unknown request {op!r}"}
            return {"ok": True}

    async def client(self, reader, writer):
        try:
            while line := await reader.readline():
                try:
                    reply = await self.handle(json.loads(line))
                except (Exception, macro.MacroError) as e:
                    if not isinstance(e, macro.MacroError):
                        self.pad = None
                    reply = {"ok": False, "error": str(e) or type(e).__name__}
                writer.write(json.dumps(reply).encode() + b"\n")
                await writer.drain()
        finally:
            writer.close()


def _exit_with_the_app() -> None:
    """runner's stdin watch interrupts the main thread, which asyncio.run here does not leave: a
    service from a closed app kept the port and its old code. EOF on stdin ends the process."""
    import sys
    sys.stdin.read()
    os._exit(0)


async def serve(port: int = PORT, serial_port: str = ""):
    if os.environ.get("POKELDN_MANAGED_RUN"):
        threading.Thread(target=_exit_with_the_app, daemon=True).start()
    service = Service(serial_port)
    server = await asyncio.start_server(service.client, "127.0.0.1", port)
    print(f"[pad] listening on 127.0.0.1:{port}", flush=True)
    async with server:
        await server.serve_forever()


class ServiceError(RuntimeError):
    pass


class Client:
    """A blocking connection to the service, safe to share between threads."""

    def __init__(self, port: int = PORT, timeout: float = 2.0):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self.sock.settimeout(None)
        self.file = self.sock.makefile("rwb")
        self.lock = threading.Lock()

    def call(self, op: str, **fields) -> dict:
        with self.lock:
            self.file.write(json.dumps({"op": op, **fields}).encode() + b"\n")
            self.file.flush()
            line = self.file.readline()
        if not line:
            raise ServiceError("the controller service stopped")
        reply = json.loads(line)
        if not reply.get("ok"):
            raise ServiceError(reply.get("error", "failed"))
        return reply

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def running(port: int = PORT) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
        return True
    except OSError:
        return False


def main():
    ap = argparse.ArgumentParser(description="Hold the controller board's Bluetooth link.")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--serial", default="", help="a classic board's serial port; default: look for one")
    args = ap.parse_args()
    try:
        asyncio.run(serve(args.port, args.serial))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
