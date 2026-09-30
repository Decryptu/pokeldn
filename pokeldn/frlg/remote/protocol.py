"""Bounded, authenticated JSON framing for the FRLG LAN probe.

This is a business-data protocol. It deliberately has no representation for RFU/Pia frames,
held-key rows, or arbitrary Python objects.
"""

import base64
import binascii
import hashlib
import hmac
import json
import re
import struct
from dataclasses import dataclass


PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 16 * 1024
AUTH_TAG_BYTES = hashlib.sha256().digest_size
MAX_BUFFER_BYTES = 4 * (MAX_FRAME_BYTES + 4 + AUTH_TAG_BYTES)
PHASE_SIZES = {
    "link_player": 200,
    "trainer_card": 100,
    "party_0": 200,
    "party_1": 200,
    "party_2": 200,
    "mail": 220,
    "ribbons": 40,
}
PHASE_ORDER = tuple(PHASE_SIZES)
MESSAGE_TYPES = {
    "HELLO", "AUTH", "ROOM_READY", "ROOM_READY_ACK", "LOCAL_LINK_STATE",
    "PEER_BLOCK", "SNAPSHOT_READY", "PING", "PONG", "ERROR", "PROBE_STOP",
}
LINK_STATES = {"waiting", "connected", "closing", "closed", "failed"}
ERROR_CODES = {
    "protocol_mismatch", "room_mismatch", "phase_mismatch", "queue_full",
    "link_lost", "local_link_failed", "invalid_data",
}


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class LanMessage:
    protocol_version: int
    room_id: str
    run_id: str
    sender_id: str
    seq: int
    ack_seq: int
    type: str
    phase: str | None
    payload: dict

    def as_dict(self):
        return {
            "protocol_version": self.protocol_version,
            "room_id": self.room_id,
            "run_id": self.run_id,
            "sender_id": self.sender_id,
            "seq": self.seq,
            "ack_seq": self.ack_seq,
            "type": self.type,
            "phase": self.phase,
            "payload": self.payload,
        }


def _canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _is_hex(value, length):
    return (isinstance(value, str) and len(value) == length
            and re.fullmatch(r"[0-9a-fA-F]+", value) is not None)


def _valid_bridge_name(value):
    return (isinstance(value, str) and 1 <= len(value) <= 7
            and value.isascii() and value.isprintable())


def logical_bytes(phase, raw):
    """Return bytes used for the phase digest; block padding is never included."""
    if not isinstance(phase, str) or phase not in PHASE_SIZES:
        raise ProtocolError(f"unknown data phase: {phase!r}")
    data = bytes(raw)
    if len(data) != PHASE_SIZES[phase]:
        raise ProtocolError(f"{phase} block must be {PHASE_SIZES[phase]} bytes")
    return data[:60] if phase == "link_player" else data


def validate_message(value):
    if not isinstance(value, dict):
        raise ProtocolError("message must be a JSON object")
    required = {"protocol_version", "room_id", "run_id", "sender_id", "seq",
                "ack_seq", "type", "phase", "payload"}
    if set(value) != required:
        raise ProtocolError("message fields do not match the protocol schema")
    if type(value["protocol_version"]) is not int or value["protocol_version"] != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol_version")
    if not _is_hex(value["room_id"], 32) or not _is_hex(value["run_id"], 32):
        raise ProtocolError("room_id and run_id must be 128-bit hex identifiers")
    if value["sender_id"] not in ("host", "join"):
        raise ProtocolError("sender_id must be host or join")
    for name in ("seq", "ack_seq"):
        if type(value[name]) is not int or not 0 <= value[name] <= 0x7FFFFFFF:
            raise ProtocolError(f"{name} must be a non-negative 31-bit sequence")
    message_type = value["type"]
    if not isinstance(message_type, str):
        raise ProtocolError("type must be a string")
    if message_type not in MESSAGE_TYPES:
        raise ProtocolError(f"unknown message type: {message_type!r}")
    phase = value["phase"]
    if phase is not None and (not isinstance(phase, str) or phase not in PHASE_SIZES):
        raise ProtocolError(f"unknown phase: {phase!r}")
    payload = value["payload"]
    if not isinstance(payload, dict):
        raise ProtocolError("payload must be an object")

    if message_type == "HELLO":
        if (phase is not None or set(payload) != {"challenge", "capabilities", "bridge_name"}
                or not _is_hex(payload["challenge"], 64)
                or payload["capabilities"] != ["frlg-direct-trade-probe-v1"]
                or not _valid_bridge_name(payload["bridge_name"])):
            raise ProtocolError("invalid HELLO payload")
    elif message_type == "AUTH":
        if (phase is not None or set(payload) != {
                "challenge_echo", "nonce", "capabilities", "bridge_name"}
                or not _is_hex(payload["challenge_echo"], 64)
                or not _is_hex(payload["nonce"], 64)
                or payload["capabilities"] != ["frlg-direct-trade-probe-v1"]
                or not _valid_bridge_name(payload["bridge_name"])):
            raise ProtocolError("invalid AUTH payload")
    elif message_type == "ROOM_READY":
        if (phase is not None or set(payload) != {"peer_nonce", "transcript"}
                or not _is_hex(payload["peer_nonce"], 64)
                or not _is_hex(payload["transcript"], 64)):
            raise ProtocolError("invalid ROOM_READY payload")
    elif message_type == "ROOM_READY_ACK":
        if phase is not None or set(payload) != {"transcript"} or not _is_hex(payload["transcript"], 64):
            raise ProtocolError("invalid ROOM_READY_ACK payload")
    elif message_type == "LOCAL_LINK_STATE":
        if (phase is not None or set(payload) != {"state"}
                or not isinstance(payload["state"], str)
                or payload["state"] not in LINK_STATES):
            raise ProtocolError("invalid LOCAL_LINK_STATE payload")
    elif message_type == "PEER_BLOCK":
        if (not isinstance(phase, str) or phase not in PHASE_SIZES
                or set(payload) != {"data", "digest"}
                or not _is_hex(payload["digest"], 64)
                or not isinstance(payload["data"], str)):
            raise ProtocolError("invalid PEER_BLOCK payload")
        try:
            data = base64.b64decode(payload["data"], validate=True)
        except (TypeError, ValueError, binascii.Error) as exc:
            raise ProtocolError("PEER_BLOCK data is not valid Base64") from exc
        if len(data) != PHASE_SIZES[phase]:
            raise ProtocolError(f"{phase} data has the wrong logical length")
        expected = hashlib.sha256(logical_bytes(phase, data)).hexdigest()
        if not hmac.compare_digest(payload["digest"], expected):
            raise ProtocolError(f"{phase} data digest mismatch")
    elif message_type == "SNAPSHOT_READY":
        if (phase is not None or set(payload) != {"snapshot_id", "digest", "phases"}
                or not _is_hex(payload["snapshot_id"], 32)
                or not _is_hex(payload["digest"], 64)
                or payload["phases"] != list(PHASE_ORDER)):
            raise ProtocolError("invalid SNAPSHOT_READY payload")
    elif message_type in ("PING", "PONG"):
        if phase is not None or set(payload) != {"time_ns"} or type(payload["time_ns"]) is not int or payload["time_ns"] < 0:
            raise ProtocolError(f"invalid {message_type} payload")
    elif message_type == "ERROR":
        if (phase is not None or set(payload) != {"code"}
                or not isinstance(payload["code"], str)
                or payload["code"] not in ERROR_CODES):
            raise ProtocolError("invalid ERROR payload")
    elif message_type == "PROBE_STOP":
        if (phase is not None or set(payload) != {"reason"}
                or not isinstance(payload["reason"], str) or payload["reason"] not in {
                    "cancelled", "completed", "in_doubt", "link_failed"}):
            raise ProtocolError("invalid PROBE_STOP payload")
    return LanMessage(**value)


def encode_frame(message, key):
    message = validate_message(message.as_dict() if isinstance(message, LanMessage) else message)
    body = _canonical_json(message.as_dict())
    length = len(body) + AUTH_TAG_BYTES
    if length > MAX_FRAME_BYTES:
        raise ProtocolError("frame exceeds 16 KiB")
    length_prefix = struct.pack(">I", length)
    tag = hmac.new(bytes(key), length_prefix + body, hashlib.sha256).digest()
    return length_prefix + body + tag


def decode_payload(frame_payload, key):
    if len(frame_payload) < AUTH_TAG_BYTES or len(frame_payload) > MAX_FRAME_BYTES:
        raise ProtocolError("invalid frame payload length")
    body, tag = frame_payload[:-AUTH_TAG_BYTES], frame_payload[-AUTH_TAG_BYTES:]
    length_prefix = struct.pack(">I", len(frame_payload))
    expected = hmac.new(bytes(key), length_prefix + body, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ProtocolError("frame authentication failed")
    try:
        decoded = json.loads(body.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys,
                             parse_constant=lambda _value: (_ for _ in ()).throw(
                                 ProtocolError("non-finite JSON number")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("frame is not valid UTF-8 JSON") from exc
    return validate_message(decoded)


class FrameDecoder:
    """Incrementally decode length-prefixed frames; handles split and coalesced TCP reads."""

    def __init__(self, key):
        self._key = bytes(key)
        self._buffer = bytearray()

    def feed(self, data):
        if len(self._buffer) + len(data) > MAX_BUFFER_BYTES:
            raise ProtocolError("receive buffer limit exceeded")
        self._buffer.extend(data)
        messages = []
        while len(self._buffer) >= 4:
            length = struct.unpack(">I", self._buffer[:4])[0]
            if length < AUTH_TAG_BYTES or length > MAX_FRAME_BYTES:
                raise ProtocolError("frame length is outside the allowed range")
            total = 4 + length
            if len(self._buffer) < total:
                break
            frame = bytes(self._buffer[4:total])
            del self._buffer[:total]
            messages.append(decode_payload(frame, self._key))
        return messages

    def eof(self):
        if self._buffer:
            raise ProtocolError("EOF inside a LAN frame")
