"""Emulator 0x57 frames `57 <type> <len:u16 LE> <body>`; C=0x43 A=0x41 T=0x54 K=0x4b D=0x44 G=0x47.
Child 'T' body `<ts:u32><00><slot_len><00 00><slot, pad 4>`; host 'T' has slot_len at body[4].
`ts` counts new frames and repeats on a Pia retransmit. Metadata (0x4a) is a Reliable INIT payload.
"""

GBA_MARKER = 0x57
TYPE_T = 0x54
TYPE_K = 0x4B
SLOT_LEN = 14


TYPE_J, TYPE_C, TYPE_A = 0x4A, 0x43, 0x41
TYPE_D = 0x44
TYPE_G = 0x47


def build_gba_frame(ftype, data):
    return bytes([GBA_MARKER, ftype]) + len(data).to_bytes(2, "little") + bytes(data)


def build_connect(connect_id):
    """`connect_id` is a self-chosen nonzero 2-byte id; the host echoes it in its 'A' and 'D'."""
    return build_gba_frame(TYPE_C, connect_id)


def _roundup4(n):
    return (n + 3) & ~3


def wrap_t(slot, ts):
    """`slot` includes its LLSF."""
    slot = bytes(slot)
    padded = slot + b"\x00" * (_roundup4(len(slot)) - len(slot))
    body = (ts & 0xFFFFFFFF).to_bytes(4, "little") + bytes([0, len(slot) & 0xFF, 0, 0]) + padded
    return bytes([GBA_MARKER, TYPE_T]) + len(body).to_bytes(2, "little") + body


def wrap_t_parent(slot, ts):
    """Host layout: slot_len at body[4]."""
    slot = bytes(slot)
    padded = slot + b"\x00" * (_roundup4(len(slot)) - len(slot))
    body = (ts & 0xFFFFFFFF).to_bytes(4, "little") + bytes([len(slot) & 0xFF, 0, 0, 0]) + padded
    return bytes([GBA_MARKER, TYPE_T]) + len(body).to_bytes(2, "little") + body


def build_link_state(value):
    """57 47 04 00 <value:u32>: a parent sends 0 after its 'A', 1 once it has the child's NI.
    Emulator-to-emulator only; the ROM never sees it."""
    return build_gba_frame(TYPE_G, (int(value) & 0xFFFFFFFF).to_bytes(4, "little"))


def build_accept(host_session_id, connect_id):
    """Body `<host_session_id:2><echoed connect_id:2><00 00>`."""
    hsid = bytes(host_session_id)[:2].ljust(2, b"\x00")
    cid = bytes(connect_id)[:2].ljust(2, b"\x00")
    return build_gba_frame(TYPE_A, hsid + cid + b"\x00\x00")


def build_disconnect(connect_id):
    return build_gba_frame(TYPE_D, bytes(connect_id)[:2].ljust(2, b"\x00"))


def build_k(k_seq, mid, acked_ts):
    """Body `<k_seq:u32><mid:u32><acked_ts:u32>`. k_seq is the cumulative count of host 'T' frames:
    skipping a K is safe, under-reporting stalls the parent's DRAC ack. mid is the 1-based position
    in the outgoing datagram; acked_ts echoes the host 'T' ts."""
    body = ((k_seq & 0xFFFFFFFF).to_bytes(4, "little")
            + (mid & 0xFFFFFFFF).to_bytes(4, "little")
            + (acked_ts & 0xFFFFFFFF).to_bytes(4, "little"))
    return bytes([GBA_MARKER, TYPE_K]) + len(body).to_bytes(2, "little") + body


def parse_in(payload):
    """Decode an incoming 0x57 frame; a 'T' with slot_len <= 1 is a host idle keepalive, still
    K-acked."""
    if len(payload) < 4 or payload[0] != GBA_MARKER:
        return None
    typ = payload[1]
    ln = int.from_bytes(payload[2:4], "little")
    body = payload[4:4 + ln]
    if typ == TYPE_T:
        if len(body) < 5:
            return {"type": "T", "ts": None, "slot_len": 0, "slots": [], "positional": []}
        ts = int.from_bytes(body[0:4], "little")
        slot_len = body[4]
        rec = {"type": "T", "ts": ts, "slot_len": slot_len, "llsf_state": None,
               "slots": [], "positional": [], "payload": b""}
        if slot_len <= 1:
            return rec
        slot = body[8:8 + slot_len]
        llsf = int.from_bytes(slot[0:3], "little")
        rec["llsf_state"] = (llsf >> 14) & 0xF
        rec["payload"] = slot[3:]
        if rec["llsf_state"] == 4:
            for mpid, off in enumerate(range(0, len(rec["payload"]) - 13, SLOT_LEN)):
                rec["slots"].append((mpid, bytes(rec["payload"][off:off + SLOT_LEN])))
        else:
            rec["ni"] = {
                "state": rec["llsf_state"],
                "ack": (llsf >> 13) & 1,
                "n": (llsf >> 11) & 3,
                "phase": (llsf >> 9) & 3,
                "size": llsf & 0x7F,
                "payload": bytes(rec["payload"]),
            }
        rec["positional"] = rec["slots"]
        return rec
    if typ == TYPE_A:
        return {"type": "A", "host_session_id": body[0:2], "connect_id": body[2:4]}
    if typ == TYPE_K:
        return {"type": "K", "k_seq": int.from_bytes(body[0:4], "little"),
                "acked_ts": int.from_bytes(body[8:12], "little") if len(body) >= 12 else None}
    return {"type": typ}


def parse_out(payload):
    """Inverse of wrap_t; `cmd` is the 14-byte gSendCmd of a UNI slot, else None."""
    from pokeldn.gba import rfu as _rfu
    if len(payload) < 4 or payload[0] != GBA_MARKER or payload[1] != TYPE_T:
        return None
    ln = int.from_bytes(payload[2:4], "little")
    body = payload[4:4 + ln]
    if len(body) < 8:
        return None
    ts = int.from_bytes(body[0:4], "little")
    slot_len = body[5]
    slot = bytes(body[8:8 + slot_len])
    rec = {"type": "T", "ts": ts, "slot_len": slot_len, "slot": slot,
           "llsf": None, "cmd": None}
    if slot_len >= 2:
        rec["llsf"] = _rfu.parse_llsf_child(slot)
        if rec["llsf"]["state"] == _rfu.LCOM_UNI:
            rec["cmd"] = slot[2:2 + SLOT_LEN]
    return rec
