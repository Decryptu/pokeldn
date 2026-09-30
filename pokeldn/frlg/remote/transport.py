"""Single-peer TCP transport for the structured FRLG probe."""

from collections import deque
from dataclasses import dataclass
import queue
import secrets
import socket
import threading
import time
import hashlib
import hmac

from pokeldn.frlg.remote.config import PROBE_CAPABILITY
from pokeldn.frlg.remote.protocol import (
    FrameDecoder, LanMessage, ProtocolError, PROTOCOL_VERSION, encode_frame,
)


HEARTBEAT_SECONDS = 1.0
DISCONNECT_SECONDS = 5.0
QUEUE_CAPACITY = 64
POLL_SECONDS = 0.2


class TransportError(RuntimeError):
    pass


@dataclass(frozen=True)
class TransportEvent:
    kind: str
    message: LanMessage | None = None
    error: str | None = None


class _SequenceState:
    def __init__(self, room_id, run_id, sender_id, peer_id, key, *, tx_seq, rx_seq,
                 peer_ack=0, receive_key=None):
        self.room_id = room_id
        self.run_id = run_id
        self.sender_id = sender_id
        self.peer_id = peer_id
        self.send_key = bytes(key)
        self.receive_key = bytes(receive_key if receive_key is not None else key)
        self.tx_seq = tx_seq
        self.rx_seq = rx_seq
        self.peer_ack = peer_ack

    def frame(self, message_type, payload, phase=None):
        if self.tx_seq > 0x7FFFFFFF:
            raise TransportError("LAN sequence exhausted; establish a new run")
        message = LanMessage(
            PROTOCOL_VERSION, self.room_id, self.run_id, self.sender_id,
            self.tx_seq, max(0, self.rx_seq - 1), message_type, phase, payload)
        frame = encode_frame(message, self.send_key)
        self.tx_seq += 1
        return frame

    def accept(self, message):
        if message.room_id != self.room_id or message.run_id != self.run_id:
            raise ProtocolError("message belongs to a different room or run")
        if message.sender_id != self.peer_id:
            raise ProtocolError("message direction does not match this connection")
        if message.seq != self.rx_seq:
            raise ProtocolError("unexpected or replayed sequence number")
        if message.ack_seq >= self.tx_seq:
            raise ProtocolError("peer acknowledged a message that was never sent")
        if message.ack_seq < self.peer_ack:
            raise ProtocolError("peer acknowledgement moved backwards")
        self.peer_ack = message.ack_seq
        self.rx_seq += 1


def _read_message(sock, decoder):
    pending = getattr(decoder, "_pending", None)
    if pending:
        return pending.popleft()
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            decoder.eof()
            raise TransportError("peer closed during the pairing handshake")
        messages = decoder.feed(chunk)
        if messages:
            if len(messages) > 1:
                decoder._pending = deque(messages[1:])
            return messages[0]


def _send_sync(sock, state, message_type, payload):
    sock.sendall(state.frame(message_type, payload))


def _accept_sync(sock, decoder, state, expected_type):
    message = _read_message(sock, decoder)
    state.accept(message)
    if message.type != expected_type:
        raise ProtocolError(f"expected {expected_type}, received {message.type}")
    return message


def _transcript(room_id, run_id, host_nonce, join_nonce, host_name, join_name):
    material = (b"pokeldn/frlg/remote/probe/v1\0" + bytes.fromhex(room_id)
                + bytes.fromhex(run_id) + host_nonce + join_nonce
                + host_name.encode("ascii") + b"\0" + join_name.encode("ascii"))
    return hashlib.sha256(material).hexdigest()


def _session_keys(key, room_id, run_id, host_nonce, join_nonce, host_name, join_name):
    context = (b"pokeldn/frlg/remote/lan-alpha/v1\0" + bytes.fromhex(room_id)
               + bytes.fromhex(run_id) + host_nonce + join_nonce
               + host_name.encode("ascii") + b"\0" + join_name.encode("ascii"))
    host_to_join = hmac.new(key, context + b"\0host-to-join", hashlib.sha256).digest()
    join_to_host = hmac.new(key, context + b"\0join-to-host", hashlib.sha256).digest()
    return host_to_join, join_to_host


def _handshake_host(sock, key, host_name):
    room_id, run_id = secrets.token_hex(16), secrets.token_hex(16)
    host_nonce = secrets.token_bytes(32)
    state = _SequenceState(room_id, run_id, "host", "join", key,
                           tx_seq=1, rx_seq=1)
    decoder = FrameDecoder(key)
    _send_sync(sock, state, "HELLO", {
        "challenge": host_nonce.hex(), "capabilities": [PROBE_CAPABILITY],
        "bridge_name": host_name})
    auth = _accept_sync(sock, decoder, state, "AUTH")
    if not secrets.compare_digest(auth.payload["challenge_echo"], host_nonce.hex()):
        raise ProtocolError("joiner did not echo the host challenge")
    join_name = auth.payload["bridge_name"]
    if join_name == host_name:
        raise ProtocolError("the two local bridge discovery names must be different")
    join_nonce = bytes.fromhex(auth.payload["nonce"])
    digest = _transcript(room_id, run_id, host_nonce, join_nonce, host_name, join_name)
    _send_sync(sock, state, "ROOM_READY", {
        "peer_nonce": join_nonce.hex(), "transcript": digest})
    ready = _accept_sync(sock, decoder, state, "ROOM_READY_ACK")
    if not secrets.compare_digest(ready.payload["transcript"], digest):
        raise ProtocolError("pairing transcript mismatch")
    host_to_join, join_to_host = _session_keys(
        key, room_id, run_id, host_nonce, join_nonce, host_name, join_name)
    return room_id, run_id, _SequenceState(
        room_id, run_id, "host", "join", host_to_join,
        tx_seq=state.tx_seq, rx_seq=state.rx_seq, peer_ack=state.peer_ack,
        receive_key=join_to_host), join_name


def _handshake_join(sock, key, join_name):
    decoder = FrameDecoder(key)
    hello = _read_message(sock, decoder)
    if hello.type != "HELLO" or hello.sender_id != "host":
        raise ProtocolError("first LAN message must be HELLO from the room host")
    room_id, run_id = hello.room_id, hello.run_id
    host_name = hello.payload["bridge_name"]
    if host_name == join_name:
        raise ProtocolError("the two local bridge discovery names must be different")
    state = _SequenceState(room_id, run_id, "join", "host", key,
                           tx_seq=1, rx_seq=1)
    state.accept(hello)
    host_nonce = bytes.fromhex(hello.payload["challenge"])
    join_nonce = secrets.token_bytes(32)
    _send_sync(sock, state, "AUTH", {
        "challenge_echo": host_nonce.hex(), "nonce": join_nonce.hex(),
        "capabilities": [PROBE_CAPABILITY], "bridge_name": join_name})
    ready = _accept_sync(sock, decoder, state, "ROOM_READY")
    digest = _transcript(room_id, run_id, host_nonce, join_nonce, host_name, join_name)
    if (not secrets.compare_digest(ready.payload["peer_nonce"], join_nonce.hex())
            or not secrets.compare_digest(ready.payload["transcript"], digest)):
        raise ProtocolError("host pairing transcript mismatch")
    _send_sync(sock, state, "ROOM_READY_ACK", {"transcript": digest})
    host_to_join, join_to_host = _session_keys(
        key, room_id, run_id, host_nonce, join_nonce, host_name, join_name)
    return room_id, run_id, _SequenceState(
        room_id, run_id, "join", "host", join_to_host,
        tx_seq=state.tx_seq, rx_seq=state.rx_seq, peer_ack=state.peer_ack,
        receive_key=host_to_join), host_name


class RemoteTransport:
    """A bounded worker owns socket I/O; engine state stays on the caller's thread."""

    def __init__(self, config, *, log=lambda *_args: None):
        self.config = config
        self.key = config.room_key
        self.log = log
        self.room_id = None
        self.run_id = None
        self.peer_name = None
        self._sock = None
        self._state = None
        self._outbound = queue.Queue(maxsize=QUEUE_CAPACITY)
        self._events = queue.Queue(maxsize=QUEUE_CAPACITY)
        self._stop = threading.Event()
        self._thread = None
        self._error = None

    @property
    def error(self):
        return self._error

    def start(self):
        if self._sock is not None:
            raise TransportError("transport already started")
        sock = self._open_socket()
        try:
            sock.settimeout(self.config.connect_timeout)
            if self.config.role == "host":
                self.room_id, self.run_id, self._state, self.peer_name = _handshake_host(
                    sock, self.key, self.config.discovery_name)
            else:
                self.room_id, self.run_id, self._state, self.peer_name = _handshake_join(
                    sock, self.key, self.config.discovery_name)
            sock.settimeout(POLL_SECONDS)
            self._sock = sock
            self._thread = threading.Thread(
                target=self._run, name="frlg-remote-lan", daemon=True)
            self._thread.start()
        except Exception:
            sock.close()
            raise
        self.log(f"LAN room paired with {self.peer_name} (run {self.run_id}).")
        return self

    def _open_socket(self):
        address = self.config.listen if self.config.role == "host" else self.config.connect
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            if self.config.role == "host":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((address, self.config.port))
                sock.listen(1)
                sock.settimeout(self.config.connect_timeout)
                self.log(f"Waiting for one LAN peer on {address}:{self.config.port}.")
                conn, _peer = sock.accept()
                sock.close()
                return conn
            sock.settimeout(self.config.connect_timeout)
            sock.connect((address, self.config.port))
            return sock
        except Exception:
            sock.close()
            raise

    def send(self, message_type, payload, *, phase=None):
        if self._error is not None:
            raise TransportError(self._error)
        if self._sock is None or self._stop.is_set():
            raise TransportError("transport is not connected")
        if message_type in {"HELLO", "AUTH", "ROOM_READY", "ROOM_READY_ACK", "PING", "PONG"}:
            raise ValueError("message type is reserved for transport control")
        try:
            self._outbound.put_nowait((message_type, payload, phase))
        except queue.Full as exc:
            self._fail("outbound LAN message queue is full")
            raise TransportError(self._error) from exc

    def poll(self, limit=32):
        result = []
        for _ in range(max(0, int(limit))):
            try:
                result.append(self._events.get_nowait())
            except queue.Empty:
                break
        return result

    def _queue_event(self, event):
        try:
            self._events.put_nowait(event)
        except queue.Full:
            self._fail("inbound LAN event queue is full")

    def _fail(self, reason):
        if self._error is not None:
            return
        self._error = str(reason)
        self._stop.set()
        self._queue_event(TransportEvent("error", error=self._error))

    def _send(self, message_type, payload, phase=None):
        self._sock.sendall(self._state.frame(message_type, payload, phase))

    def _run(self):
        decoder = FrameDecoder(self._state.receive_key)
        last_valid = time.monotonic()
        last_ping = 0.0
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if now - last_valid >= DISCONNECT_SECONDS:
                    raise TransportError("no authenticated LAN message for five seconds")
                if now - last_ping >= HEARTBEAT_SECONDS:
                    self._send("PING", {"time_ns": time.time_ns()})
                    last_ping = now
                try:
                    outgoing = self._outbound.get_nowait()
                except queue.Empty:
                    outgoing = None
                if outgoing is not None:
                    try:
                        self._send(outgoing[0], outgoing[1], outgoing[2])
                    finally:
                        self._outbound.task_done()
                try:
                    chunk = self._sock.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    decoder.eof()
                    raise TransportError("LAN peer disconnected")
                for message in decoder.feed(chunk):
                    self._state.accept(message)
                    last_valid = time.monotonic()
                    if message.type == "PING":
                        self._send("PONG", {"time_ns": message.payload["time_ns"]})
                    elif message.type == "PONG":
                        continue
                    else:
                        self._queue_event(TransportEvent("message", message=message))
        except (OSError, ProtocolError, TransportError, ValueError) as exc:
            if not self._stop.is_set():
                self._fail(str(exc))

    def close(self):
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.key = b""
        self._state = None
        self.config = None
        for pending in (self._outbound, self._events):
            while True:
                try:
                    pending.get_nowait()
                except queue.Empty:
                    break
                else:
                    if pending is self._outbound:
                        pending.task_done()

    def flush(self, timeout=0.25):
        """Best-effort drain for a final control message, called only outside the RFU tick."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        while self._outbound.unfinished_tasks and time.monotonic() < deadline:
            if self._error is not None:
                return False
            time.sleep(0.005)
        return self._outbound.unfinished_tasks == 0

    def __enter__(self):
        return self.start()

    def __exit__(self, *_exc):
        self.close()
