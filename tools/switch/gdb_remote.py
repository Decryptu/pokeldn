#!/usr/bin/env python3
"""Minimal GDB remote-protocol client: memory, registers, stop/continue, thread selection.

This drives the GDB stub an emulator exposes for a title's own address space. Addresses are the
title's virtual addresses, not the emulated console's. The stub is single-threaded: halt it before
a read or write. A 4 KB `M` packet trips a substring bug in one build; writes go in 2 KB chunks.
"""
import argparse
import socket
import struct


def checksum(payload):
    return f"{sum(payload) & 0xFF:02x}"


class GdbRemote:
    def __init__(self, host="127.0.0.1", port=55556, timeout=10):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.s.settimeout(timeout)
        self.pending = None

    def _recv_packet(self):
        buf = bytearray()
        while True:
            c = self.s.recv(1)
            if not c:
                raise ConnectionError("the stub closed the connection")
            if c == b"$":
                break
        while True:
            c = self.s.recv(1)
            if not c:
                raise ConnectionError("the stub closed the connection")
            if c == b"#":
                break
            buf += c
        want = self.s.recv(2)
        if checksum(bytes(buf)) != want.decode():
            raise ValueError(f"bad checksum {want!r} for {bytes(buf[:40])!r}")
        self.s.sendall(b"+")
        out = bytearray()
        i = 0
        while i < len(buf):
            if buf[i] == 0x7D:
                out.append(buf[i + 1] ^ 0x20)
                i += 2
            else:
                out.append(buf[i])
                i += 1
        return bytes(out)

    def cmd(self, payload):
        p = payload.encode()
        self.s.sendall(b"$" + p + b"#" + checksum(p).encode())
        while True:
            c = self.s.recv(1)
            if c == b"+":
                break
            if c == b"-":
                self.s.sendall(b"$" + p + b"#" + checksum(p).encode())
            if c == b"$":
                raise RuntimeError("the stub sent a packet before the ack")
        return self._recv_packet()

    def stop(self, timeout=None):
        """Wait for a stop reply. `OK` from vCont is not a stop reply."""
        old = self.s.gettimeout()
        self.s.settimeout(timeout)
        try:
            while True:
                r = self._recv_packet()
                if r != b"OK":
                    return r
        except socket.timeout:
            return None
        finally:
            self.s.settimeout(old)

    def interrupt(self, timeout=5):
        self.s.sendall(b"\x03")
        return self.stop(timeout)

    def cont(self):
        self.cmd("vCont;c")

    def read(self, addr, length, chunk=0x800):
        out = bytearray()
        while length > 0:
            n = min(length, chunk)
            r = self.cmd(f"m{addr:x},{n:x}")
            if r.startswith(b"E") and len(r) <= 3:
                raise IOError(f"read error {r.decode()} at 0x{addr:x} len 0x{n:x}")
            piece = bytes.fromhex(r.decode())
            if len(piece) != n:
                raise IOError(f"short read at 0x{addr:x}: got {len(piece)} want {n}")
            out += piece
            addr += n
            length -= n
        return bytes(out)

    def u32(self, addr):
        return struct.unpack("<I", self.read(addr, 4))[0]

    def u64(self, addr):
        return struct.unpack("<Q", self.read(addr, 8))[0]

    def write(self, addr, data, chunk=0x800):
        for i in range(0, len(data), chunk):
            piece = data[i:i + chunk]
            self.cmd(f"M{addr + i:x},{len(piece):x}:{piece.hex()}")

    def reg(self, n):
        r = self.cmd(f"p{n:x}")
        if r.startswith(b"E") or not r:
            raise IOError(f"p{n:x} -> {r!r}")
        return int.from_bytes(bytes.fromhex(r.decode()), "little")

    def set_thread(self, tid):
        return self.cmd(f"Hg{tid}")

    def threads(self):
        out = []
        r = self.cmd("qfThreadInfo")
        while r and r != b"l":
            if r.startswith(b"m"):
                out += r[1:].decode().split(",")
            r = self.cmd("qsThreadInfo")
        return out

    def close(self):
        try:
            self.cmd("D")
        except Exception:
            pass
        self.s.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=55556)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read")
    r.add_argument("address", type=lambda v: int(v, 0))
    r.add_argument("length", type=lambda v: int(v, 0))
    w = sub.add_parser("write")
    w.add_argument("address", type=lambda v: int(v, 0))
    w.add_argument("hex")
    sub.add_parser("probe")
    args = ap.parse_args()
    g = GdbRemote(args.host, args.port)
    try:
        if args.cmd == "probe":
            print((g.interrupt() or b"").decode(errors="replace"))
            print("threads", g.threads())
        elif args.cmd == "read":
            print(g.read(args.address, args.length).hex())
        else:
            g.interrupt()
            g.write(args.address, bytes.fromhex(args.hex))
            print(g.read(args.address, len(bytes.fromhex(args.hex))).hex())
    finally:
        g.close()


if __name__ == "__main__":
    main()
