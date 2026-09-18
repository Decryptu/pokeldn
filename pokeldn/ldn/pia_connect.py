"""Pia connection layer (Net + Session + RTT), the handshake the host completes before registering us as a peer.
Station var-ids are ASSIGNED per session, not derived from the MAC: the header is [dst_var][src_var] and the footer is
the DESTINATION var, so both are learned from the first incoming packet. The 8-byte constant id = 6-byte MAC + 0000.
"""

PROTO_NET = 1
PROTO_RTT = 3
PROTO_RELIABLE = 10
PROTO_SESSION = 13

# RTT and session control ride header dst=0x0001 (the session pseudo-station); the footer recipient stays the host var.
SESSION_VAR = 0x0001
RTT_ORIGINATE_PERIOD = 10

NET_CONN_REQUEST = 0x11
NET_CONN_RESPONSE = 0x12
NET_UPDATE_PROPERTY = 0x50
NET_UPDATE_PROPERTY_ACK = 0x51

SESSION_JOIN_REQUEST = 0
SESSION_JOIN_RESPONSE = 2
SESSION_UPDATE = 5
SESSION_UPDATE_ACK = 6
SESSION_LEFT_SYNC = 7

DEFAULT_PROTOCOLS = [(1, 0), (3, 5), (5, 1), (10, 3), (13, 7), (15, 0)]
DEFAULT_APP_VER = bytes.fromhex("0058")
DEFAULT_PLAYER_ID = bytes.fromhex("00000000000000010000000000000000")


def _ip4(ip):
    return bytes(int(x) for x in ip.split("."))


def parse_net(payload):
    if len(payload) < 4:
        return None
    # `size` is not the full body length (Net 0x11 stores only the NetStation-array size, 0x12 stores zero), so return the whole body.
    return payload[0], payload[1], payload[4:]


def build_net_response(seqid=2):
    """The seqid must echo the host's 0x11 seqid; a fixed value deadlocks (endless 500ms 0x11 retransmits)."""
    return bytes([0x01, NET_CONN_RESPONSE, 0x00, 0x00]) + (seqid & 0xFFFFFFFF).to_bytes(4, "big")


def ldn_constant_id(mac):
    mac = bytes(mac)
    if len(mac) != 6:
        raise ValueError("LDN constant id requires a 6-byte MAC")
    return bytes((mac[2], mac[4], mac[5], mac[3], mac[1], mac[0], 0, 0))


def _net_station(ip=None, port=12345, *, migration_state=0, migration_rank=0, prefix_len=4):
    """A NetStation: a prefix then an 18-byte station address (16-byte address, IPv4 in the first 4,
    then a big-endian port). An empty slot is rank 0xff with zero address and port.

    The prefix is 4 bytes at Pia 6.39 ([migration_state][rank][disconnection candidate][kicking]) and
    3 bytes at the 6.16-6.23 band ([migration_state][rank][one byte]), measured off a console's own
    0x11 (docs/pla.md). So a station is 22 bytes at 6.39 and 21 here.
    """
    address = (_ip4(ip) + b"\x00" * 12) if ip is not None else b"\x00" * 16
    if ip is None:
        port = 0
    prefix = bytes([migration_state & 0xFF, migration_rank & 0xFF]) + b"\x00" * (prefix_len - 2)
    return prefix + address + (port & 0xFFFF).to_bytes(2, "big")


def build_net_conn_request(seqid, host_var, host_mac, network_id, stations, max_stations=6,
                           station_size=22):
    """Net 0x11: all max_stations slots are always emitted, unused ones rank 0xff; the network id is the 32-bit SSID CRC
    zero-extended to 8 bytes. `station_size` is 22 at Pia 6.39 (the GBA app's 6.32 host) and 21 at the
    6.16-6.23 band Legends Arceus speaks; it sets the NetStation prefix width.
    """
    entries = list(stations)
    if not 1 <= len(entries) <= max_stations:
        raise ValueError("Net 0x11 needs 1..max_stations occupied station addresses")
    prefix_len = station_size - 18
    body = bytearray()
    body += (seqid & 0xFFFFFFFF).to_bytes(4, "big")
    body += (_vid(host_var) & 0xFFFF).to_bytes(2, "big")
    body += ldn_constant_id(host_mac)
    body += (network_id & 0xFFFFFFFF).to_bytes(8, "big")
    body += bytes([1])
    body += max_stations.to_bytes(2, "big")
    body += bytes([0])
    for rank, ip in enumerate(entries):
        body += _net_station(ip, migration_rank=rank, prefix_len=prefix_len)
    for _ in range(max_stations - len(entries)):
        body += _net_station(migration_rank=0xFF, prefix_len=prefix_len)
    station_array_size = max_stations * station_size
    return bytes([0x01, NET_CONN_REQUEST]) + station_array_size.to_bytes(2, "big") + body


def build_net_property_ack(seqid):
    """Echoes the host's 0x50 seqid; the host retransmits its 0x50 every 500ms until acked."""
    return bytes([0x01, NET_UPDATE_PROPERTY_ACK, 0x00, 0x00]) + (seqid & 0xFFFFFFFF).to_bytes(4, "big")


def parse_net_conn_request(payload):
    """-> (host_var, host_mac, seqid). The host's Pia constant id is the emulator's fixed virtual GBA-adapter MAC (identical
    across Switches), NOT its LDN MAC from the participant list; the Session join must address this one.
    """
    n = parse_net(payload)
    if not n or n[1] != NET_CONN_REQUEST or len(n[2]) < 12:
        return None
    body = n[2]
    return int.from_bytes(body[4:6], "big"), bytes(body[6:12]), int.from_bytes(body[0:4], "big")


def parse_rtt(payload):
    """[wiki RTT-Protocol] byte 0 = type (0 request, 1 response), byte 3 = protocol version (must be preserved), [8:16] system
    time, [19:21] subject var-id.
    """
    if len(payload) < 16:
        return None
    return {"type": payload[0],
            "version": payload[3],
            "systime": payload[8:16],
            "subject": payload[19:21] if len(payload) >= 21 else b""}


def build_rtt_response(request):
    """Echo the request verbatim with byte 0 = 1: the host uses the echoed timestamp for its round-trip; the subject stays
    the host var.
    """
    b = bytearray(request[:21].ljust(21, b"\x00"))
    b[0] = 1
    return bytes(b)


def build_rtt_request(template, systime):
    """Clone the host's last request layout, type=0, fresh systime (echoed back in its type-1 response)."""
    b = bytearray(template[:21].ljust(21, b"\x00"))
    b[0] = 0
    b[8:16] = (systime & ((1 << 64) - 1)).to_bytes(8, "little")
    return bytes(b)


def build_session_join(src_mac, src_var, src_ip, dst_mac, dst_var, player_name,
                       random4, *, src_port=12345, app_ver=DEFAULT_APP_VER,
                       protocols=DEFAULT_PROTOCOLS, player_id=DEFAULT_PLAYER_ID):
    out = bytearray([SESSION_JOIN_REQUEST, len(protocols)])
    for pid, ver in protocols:
        out += bytes([pid, ver])
    out += app_ver
    out += random4                                   # 4-byte random nonce
    out += bytes(src_mac) + b"\x00\x00"              # source constant id (8)
    out += bytes(src_var)                            # source variable id (2)
    out += bytes([0, 0])                             # NAT mapping, is-private-IPv6
    out += b"\x00" * 32                              # identification token
    out += bytes(dst_mac) + b"\x00\x00"             # dest constant id (8)
    out += bytes(dst_var)                            # dest variable id (2)
    out += bytes([1, 1])                             # num players, num participants
    out += bytes([0]) + _ip4(src_ip) + src_port.to_bytes(2, "big")   # StationAddress (IPv4)
    nm = player_name.encode()[:20]                   # PlayerInfo
    out += player_id + len(nm).to_bytes(4, "big") + bytes([1]) + nm
    return bytes(out)


def _constant_id8(value):
    value = bytes(value)
    if len(value) == 6:
        return value + b"\x00\x00"
    if len(value) != 8:
        raise ValueError("Pia constant id must be 6 or 8 bytes")
    return value


def _parse_player_info(payload, offset):
    if offset + 21 > len(payload):
        raise ValueError("truncated Session PlayerInfo")
    player_id = bytes(payload[offset:offset + 16])
    name_size = int.from_bytes(payload[offset + 16:offset + 20], "big")
    encoding = payload[offset + 20]
    end = offset + 21 + name_size
    if name_size > 40 or end > len(payload):
        raise ValueError("invalid Session PlayerInfo name size")
    return {
        "player_id": player_id,
        "encoding": encoding,
        "name": bytes(payload[offset + 21:end]),
    }, end


def parse_session_join(payload):
    """Returns None for malformed or non-IPv4 requests rather than letting network input escape into the host loop."""
    payload = bytes(payload)
    try:
        if len(payload) < 2 or payload[0] != SESSION_JOIN_REQUEST:
            return None
        nprotocols = payload[1]
        pos = 2
        if pos + nprotocols * 2 + 2 + 4 + 8 + 2 + 2 + 32 + 8 + 2 + 2 > len(payload):
            return None
        protocols = [(payload[pos + i * 2], payload[pos + i * 2 + 1])
                     for i in range(nprotocols)]
        pos += nprotocols * 2
        app_ver = bytes(payload[pos:pos + 2]); pos += 2
        random4 = bytes(payload[pos:pos + 4]); pos += 4
        source_constant_id = bytes(payload[pos:pos + 8]); pos += 8
        source_var = int.from_bytes(payload[pos:pos + 2], "big"); pos += 2
        nat_mapping, private_ipv6 = payload[pos], payload[pos + 1]; pos += 2
        token = bytes(payload[pos:pos + 32]); pos += 32
        destination_constant_id = bytes(payload[pos:pos + 8]); pos += 8
        destination_var = int.from_bytes(payload[pos:pos + 2], "big"); pos += 2
        num_players, num_participants = payload[pos], payload[pos + 1]; pos += 2
        if pos >= len(payload) or payload[pos] != 0:
            return None
        pos += 1
        if pos + 6 > len(payload):
            return None
        ip = ".".join(str(x) for x in payload[pos:pos + 4]); pos += 4
        port = int.from_bytes(payload[pos:pos + 2], "big"); pos += 2
        players = []
        for _ in range(num_players):
            player, pos = _parse_player_info(payload, pos)
            players.append(player)
        if pos != len(payload):
            return None
        return {
            "protocols": protocols,
            "app_ver": app_ver,
            "random4": random4,
            "source_constant_id": source_constant_id,
            "source_var": source_var,
            "nat_mapping": nat_mapping,
            "private_ipv6": private_ipv6,
            "identification_token": token,
            "destination_constant_id": destination_constant_id,
            "destination_var": destination_var,
            "num_players": num_players,
            "num_participants": num_participants,
            "ip": ip,
            "port": port,
            "players": players,
        }
    except (IndexError, ValueError):
        return None


def _build_player_info(player_id, name, encoding=1):
    player_id = bytes(player_id)
    if len(player_id) != 16:
        raise ValueError("Pia player id must be 16 bytes")
    name = name.encode() if isinstance(name, str) else bytes(name)
    if len(name) > 40:
        raise ValueError("Pia player name is too long")
    return player_id + len(name).to_bytes(4, "big") + bytes([encoding]) + name


def _build_session_station(constant_id, variable_id, ip, port, station_index,
                           join_order, token, num_players, num_participants, players):
    token = bytes(token)
    if len(token) != 32:
        raise ValueError("Pia identification token must be 32 bytes")
    out = bytearray(_constant_id8(constant_id))
    out += (_vid(variable_id) & 0xFFFF).to_bytes(2, "big")
    out += _ip4(ip) + (port & 0xFFFF).to_bytes(2, "big")
    out += bytes([station_index & 0xFF])
    out += (join_order & 0xFFFF).to_bytes(2, "big")
    out += b"\x00\x00"                              # left-join order / reserved
    out += token
    out += bytes([num_players & 0xFF, num_participants & 0xFF])
    out += b"\x00\x00"
    for player in players:
        out += _build_player_info(player["player_id"], player["name"], player["encoding"])
    return bytes(out)


def build_session_update(join, host_constant_id, host_var, host_ip, host_name,
                         *, host_player_id=DEFAULT_PLAYER_ID, sequence_id=1):
    """Leader's fragmented Session type-5 update, the two-station Pia 6.39 layout: 7-byte fragment header (one fragment),
    leader first, requester second.
    """
    if not join or not join.get("players"):
        raise ValueError("a parsed Session join with at least one player is required")
    host_constant_id = _constant_id8(host_constant_id)
    host_var = _vid(host_var)
    host_player = {"player_id": bytes(host_player_id), "name": host_name, "encoding": 1}
    host_station = _build_session_station(
        host_constant_id, host_var, host_ip, 12345, 0, 0, b"\x00" * 32, 1, 1,
        [host_player])
    guest_station = _build_session_station(
        join["source_constant_id"], join["source_var"], join["ip"], join["port"], 1, 1,
        join["identification_token"], join["num_players"], join["num_participants"],
        join["players"])
    # [type, unknown:u16, fragment-count, fragment-index, fragment-offset:u16]
    out = bytearray.fromhex("05000001000003")
    out += host_constant_id
    out += host_var.to_bytes(2, "big")
    out += bytes([2, 0])                            # two stations, no departed stations
    out += (sequence_id & 0xFFFF).to_bytes(2, "big")
    out += b"\x00" * 6                            # two documented + four 6.39 reserved bytes
    out += host_station + guest_station
    return bytes(out)


def build_session_join_response(join, host_constant_id, host_var, random4):
    random4 = bytes(random4)
    if len(random4) != 4:
        raise ValueError("Session join response random value must be four bytes")
    versions = dict(join["protocols"])
    session_version = versions.get(PROTO_SESSION, 7)
    return (bytes([SESSION_JOIN_RESPONSE, PROTO_SESSION, session_version, 1])
            + b"\x00" * 4 + random4
            + _constant_id8(host_constant_id) + (_vid(host_var) & 0xFFFF).to_bytes(2, "big")
            + _constant_id8(join["source_constant_id"])
            + (join["source_var"] & 0xFFFF).to_bytes(2, "big")
            + bytes([1]) + (1).to_bytes(2, "big") + b"\x00\x00")


# --- Pia 6.16-6.30 (version 11) Session layouts, read from the console's own parsers -------------
#
# A location id on the wire is 12 bytes: u64 BE constant id, two zero bytes, u16 BE variable id.
# `0x73fd98`/`0x73fda0` read the constant and variable ids the ack and response compare against.
SESSION_JOIN_ACK = 1
WIRE_SESSION_PROTOCOL = 0x98


def _location_id(constant_id, variable_id):
    return _constant_id8(constant_id) + b"\x00\x00" + (_vid(variable_id) & 0xFFFF).to_bytes(2, "big")


def parse_session_join_v11(payload, *, header_end=None):
    """Parse a version-11 Session type-0 join request (`0x7364e4`), returning None on anything malformed.

    The body is the type byte, a protocol count, that many (id, version) pairs, then a four-byte
    application/nonce field, the source location id (12), a 32-byte identification token, three
    zero bytes, the source station address (IPv4 + big-endian port), the destination location id
    (12), and a trailer. Only the fields the response echoes are returned.
    """
    payload = bytes(payload)
    try:
        if len(payload) < 2 or payload[0] != SESSION_JOIN_REQUEST:
            return None
        nprotocols = payload[1]
        p = 2 + nprotocols * 2
        protocols = [(payload[2 + i * 2], payload[2 + i * 2 + 1]) for i in range(nprotocols)]
        if header_end is not None:
            p = header_end
        if p + 4 + 12 + 32 + 3 + 6 + 12 > len(payload):
            return None
        app4 = bytes(payload[p:p + 4])
        source_constant_id = bytes(payload[p + 4:p + 12])
        source_var = int.from_bytes(payload[p + 14:p + 16], "big")
        token = bytes(payload[p + 16:p + 48])
        ip = ".".join(str(x) for x in payload[p + 51:p + 55])
        port = int.from_bytes(payload[p + 55:p + 57], "big")
        destination_constant_id = bytes(payload[p + 57:p + 65])
        destination_var = int.from_bytes(payload[p + 67:p + 69], "big")
        return {
            "protocols": protocols,
            "app4": app4,
            "source_constant_id": source_constant_id,
            "source_var": source_var,
            "identification_token": token,
            "ip": ip,
            "port": port,
            "destination_constant_id": destination_constant_id,
            "destination_var": destination_var,
        }
    except (IndexError, ValueError):
        return None


def build_session_join_ack_v11(host_constant_id, host_var, console_constant_id, console_var):
    """Session type-1 join-request-ack, 25 bytes (`0x737534`). Every id is compared; a mismatch is
    dropped silently. It extends the join deadline by 8 s and completes nothing on its own.
    """
    return (bytes([SESSION_JOIN_ACK])
            + _location_id(host_constant_id, host_var)
            + _location_id(console_constant_id, console_var))


def build_session_join_response_v11(host_constant_id, host_var, console_constant_id, console_var,
                                    *, version=0, status=1, route=(0, 1), station_index=1,
                                    join_order=1, sequence_id=1):
    """Session type-2 join response, 43 bytes (`0x7379c0`). Status 1 is the accept path; the four
    ids are compared, the random field (bytes +4..+0xc) is unread, and the assignment (route bytes,
    station index, join order, sequence id) is stored without validation. The sequence id is what a
    later type-5 update must reach to set `JoinMeshJob+0x7c`. The console's own writer puts
    `(0, 1)`, index 1, join order 1 for a first joiner.
    """
    return (bytes([SESSION_JOIN_RESPONSE, WIRE_SESSION_PROTOCOL, version & 0xFF, status & 0xFF])
            + b"\x00" * 8
            + _location_id(host_constant_id, host_var)
            + _location_id(console_constant_id, console_var)
            + bytes([route[0] & 0xFF, route[1] & 0xFF, station_index & 0xFF])
            + (join_order & 0xFFFF).to_bytes(2, "big")
            + (sequence_id & 0xFFFF).to_bytes(2, "big"))


def _session_station_v11(constant_id, variable_id, ip, port, *, station_index, route,
                         join_order, token, players, participants=None, nat=0, private_ipv6=0):
    """One IPv4 entry in a version-11 type-5 station list, read by `0x739050`.

    The variable id is a big-endian u32 whose low half is the id (`[0000 | var]`), the address is the
    six-byte IPv4 form, then route bytes A and B, the station index, a big-endian u16 join order, a
    NAT-mapping byte, a private-IPv6 flag, the 32-byte token, a player count, a participant count, and
    the 6.32-style player records. The caller clears this station's IPv6 bitmap bit to match.
    """
    token = bytes(token)
    if len(token) != 32:
        raise ValueError("Pia identification token must be 32 bytes")
    out = bytearray(_constant_id8(constant_id))
    out += (_vid(variable_id) & 0xFFFF).to_bytes(4, "big")       # [0000 | var]
    out += _ip4(ip) + (port & 0xFFFF).to_bytes(2, "big")
    out += bytes([route[0] & 0xFF, route[1] & 0xFF, station_index & 0xFF])
    out += (join_order & 0xFFFF).to_bytes(2, "big")
    out += bytes([nat & 0xFF, 1 if private_ipv6 else 0])
    out += token
    out += bytes([len(players) & 0xFF,
                  (len(players) if participants is None else participants) & 0xFF])
    for player in players:
        out += _build_player_info(player["player_id"], player["name"], player.get("encoding", 1))
    return bytes(out)


SESSION_LEAVE_REQUEST = 3


def build_session_leave_v11(constant_id, variable_id, ip, port=12345, *, reason=0,
                            random4=b"\0\0\0\0"):
    """Session type-3 leave request, 24 bytes: the station saying it is going.

    Read off four of a console's own, two per session, which it sends in a burst and does not wait
    to have answered. The band's type table (NintendoClients, Session Protocol (new)) pairs a leave
    with nothing; what a host owes the OTHER stations is the type-7 left-station sync, and a session
    of two has none to tell.

        03 | u32 random | location id (12) | reason byte | IPv4 (4) | port big-endian (2)

    The random field differs on every send, including retransmissions of one leave, so nothing
    reads it back and the default here is zeros; the host passes fresh bytes to look like a station
    rather than because anything depends on it. `reason` is 0 on all four.
    """
    return (bytes([SESSION_LEAVE_REQUEST])
            + bytes(random4)[:4].ljust(4, b"\0")
            + _location_id(constant_id, variable_id)
            + bytes([reason & 0xFF])
            + _ip4(ip) + (port & 0xFFFF).to_bytes(2, "big"))


def build_session_update_v11(host_constant_id, host_var, stations, *, sequence_id=1):
    """Session type-5 station-list update for the 6.16-6.30 band (`0x738740`, body read at `0x73897c`).

    The reassembler `0x7404a8` reads a seven-byte fragment header first: the type, the big-endian u16
    sequence, a fragment count, a fragment index, and a big-endian u16 offset. It seeds the buffer with
    the first three bytes (type and sequence) and copies the fragment payload at the offset, so the
    payload begins at the host constant id and the reassembled body reads: `05`, the sequence, the host
    constant id, the host variable id as a `[0000 | var]` u32, the station count, an IPv6 bitmap of
    `(count + 31) // 32 * 4` bytes, then the station entries. One fragment carries the whole update.
    """
    count = len(stations)
    payload = bytearray(_constant_id8(host_constant_id))
    payload += (_vid(host_var) & 0xFFFF).to_bytes(4, "big")      # [0000 | var]
    payload += bytes([count & 0xFF])
    payload += bytearray((count + 31) // 32 * 4)                 # IPv6 bitmap, all IPv4, bits clear
    for st in stations:
        payload += _session_station_v11(
            st["constant_id"], st["variable_id"], st["ip"], st["port"],
            station_index=st["station_index"], route=st.get("route", (0, 0)),
            join_order=st.get("join_order", 0), token=st.get("token", b"\x00" * 32),
            players=st.get("players", []), participants=st.get("participants"))
    fragment_header = (bytes([SESSION_UPDATE]) + (sequence_id & 0xFFFF).to_bytes(2, "big")
                       + bytes([1, 0]) + (3).to_bytes(2, "big"))  # count 1, index 0, offset 3
    return fragment_header + bytes(payload)


def parse_session(payload):
    if not payload:
        return None
    t = payload[0]
    rec = {"type": t}
    if t in (SESSION_JOIN_REQUEST, SESSION_UPDATE) and len(payload) > 2:
        rec["count"] = payload[1]
    return rec


# Host-ack-gated: we never advance on our own send, only when the host acknowledges (it retransmits every stage and we
# answer each), so a dropped OUT packet is re-sent on its next retransmit. Header (dst,src) per stage: net 0x12 -> (0, 0),
# session join -> (0, our_var), finalize/reliable -> (host_var, our_var).
ST_NET, ST_FINALIZE, ST_CONNECTED = "net", "finalize", "connected"
NET_WAIT, SESSION_WAIT, CONNECTED = ST_NET, ST_FINALIZE, ST_CONNECTED


def build_session_finalize(our_mac):
    """Session type 6: `06 <our_mac:6> 0000 0000000000 01` - it references OUR constant id, not the host's."""
    return bytes([6]) + bytes(our_mac) + b"\x00\x00" + b"\x00" * 5 + bytes([1])


def _vid(x):
    return x if isinstance(x, int) else int.from_bytes(x, "big")


class ConnectionManager:
    def __init__(self, our_mac, host_mac, our_ip, host_ip, our_var=0xc493,
                 player_name="EMU", random4=b"\x00\x00\x00\x00", log=lambda *a: None,
                 player_id=None, rtt_before_finalize=False, join_repeat_ticks=0):
        self.player_id = bytes(player_id) if player_id else DEFAULT_PLAYER_ID
        self.rtt_before_finalize = bool(rtt_before_finalize)
        self.join_repeat_ticks = int(join_repeat_ticks or 0)
        self._join_sent_tick = None
        self.our_mac = bytes(our_mac)
        self.host_mac = bytes(host_mac)
        self.our_ip = our_ip
        self.host_ip = host_ip
        self.our_var = _vid(our_var)
        self.host_var = None
        self.player_name = player_name
        self.random4 = random4
        self.log = log
        self.info = getattr(log, "info", log)
        self.state = ST_NET
        self._outbox = []
        self._last_host_rtt = None
        self._rtt_systime = 0x10000
        self._rtt_orig_tick = -10 ** 9
        self._rtt_pending = {}
        self.rtt_samples = []

    def maybe_originate_rtt(self, tick):
        """Once connected, originate a type-0 RTT probe every RTT_ORIGINATE_PERIOD VBlanks; the host expects liveness probes
        from us. No-op until a host request has been seen to clone the layout from.
        """
        if not self.connected or self._last_host_rtt is None or self.host_var is None:
            return
        if tick - self._rtt_orig_tick < RTT_ORIGINATE_PERIOD:
            return
        self._rtt_orig_tick = tick
        self._rtt_systime = (self._rtt_systime + 1) & ((1 << 64) - 1)
        self._rtt_pending[self._rtt_systime] = tick
        if len(self._rtt_pending) > 64:
            for k in sorted(self._rtt_pending, key=self._rtt_pending.get)[:32]:
                del self._rtt_pending[k]
        self._q(PROTO_RTT, build_rtt_request(self._last_host_rtt, self._rtt_systime),
                SESSION_VAR, self.our_var, False, True, False, footer_var=self.host_var)

    @property
    def connected(self):
        return self.state == ST_CONNECTED

    def learn_ids(self, our_var, host_var):
        if our_var is not None:
            self.our_var = _vid(our_var)
        if host_var is not None:
            self.host_var = _vid(host_var)

    def _join(self):
        return build_session_join(self.our_mac, self.our_var.to_bytes(2, "big"), self.our_ip,
                                  self.host_mac, (self.host_var or 0).to_bytes(2, "big"),
                                  self.player_name, self.random4, player_id=self.player_id)

    def maybe_repeat_join(self, tick):
        if (not self.join_repeat_ticks or self.state != ST_NET or self.host_var is None
                or self._join_sent_tick is None):
            return
        if tick - self._join_sent_tick < self.join_repeat_ticks:
            return
        self._join_sent_tick = tick
        self._q(PROTO_SESSION, self._join(), 0, self.our_var, True, False, True, pktid=0)
        self.log("[pia] re-sent the Session join (join_repeat_ticks)")

    def _q(self, proto, payload, dst, src, compress, footer, establishing, pktid=None, footer_var=None):
        """`pktid` overrides the per-channel counter (establishing frames force 0); `footer_var` overrides the footer recipient
        (RTT: header dst=0x0001, footer=host var).
        """
        self._outbox.append({"proto": proto, "payload": payload, "dst": dst, "src": src,
                             "compress": compress, "footer": footer, "establishing": establishing,
                             "unicast": True, "pktid": pktid, "footer_var": footer_var})

    def on_message(self, proto, payload, tick=None):
        """Framing per stage: Net 0x12 -> hdr(0,0), establishing, no footer, raw; Session join -> hdr(0, our_var), establishing,
        no footer, zstd; finalize / RTT response -> hdr(host_var, our_var), footer=host_var, raw.
        """
        if proto == PROTO_NET:
            n = parse_net(payload)
            if n and n[1] == NET_CONN_REQUEST and self.state == ST_NET:
                req = parse_net_conn_request(payload)
                seqid = 2
                if req:
                    host_var, host_mac, seqid = req
                    self.host_mac = host_mac
                    if self.host_var is None:
                        self.host_var = host_var
                self._q(PROTO_NET, build_net_response(seqid), 0, 0, False, False, True, pktid=0)
                if self.host_var is not None:
                    self._q(PROTO_SESSION, self._join(), 0, self.our_var, True, False, True, pktid=0)
                    if self._join_sent_tick is None and tick is not None:
                        self._join_sent_tick = tick
            elif n and n[1] == NET_UPDATE_PROPERTY:
                body = n[2]
                seqid = int.from_bytes(body[0:4], "big") if len(body) >= 4 else 1
                self._q(PROTO_NET, build_net_property_ack(seqid), 0, self.our_var, False, False, True)
        elif proto == PROTO_SESSION:
            # Finalize only on the type-5 accept (re-emitted on a re-sent accept), never on the type-2 follow-up: native sends exactly one.
            s = parse_session(payload)
            if (s and s["type"] == SESSION_UPDATE
                    and self.host_var is not None and self.state != ST_CONNECTED):
                self._q(PROTO_SESSION, build_session_finalize(self.our_mac),
                        self.host_var, self.our_var, False, True, False)
            if self.state == ST_NET:
                self.state = ST_FINALIZE
                self.log("host acked join (Session) -> FINALIZE")
                self.info("Host acknowledged our join.")
        elif proto in (PROTO_RTT, PROTO_RELIABLE):
            if self.state == ST_FINALIZE:
                self.state = ST_CONNECTED
                self.log("host live (RTT/Reliable) -> CONNECTED")
                self.info("Connection established.")
            # Native does not answer RTT before finalize.
            if proto == PROTO_RTT and (self.state != ST_NET or self.rtt_before_finalize) \
                    and self.host_var is not None:
                r = parse_rtt(payload)
                if r and r["type"] == 0:
                    self._last_host_rtt = bytes(payload[:21])
                    self._q(PROTO_RTT, build_rtt_response(payload),
                            SESSION_VAR, self.our_var, False, True, False, footer_var=self.host_var)
                elif r and r["type"] == 1 and tick is not None:
                    systime = int.from_bytes(r["systime"], "little")
                    sent = self._rtt_pending.pop(systime, None)
                    if sent is not None and tick >= sent:
                        self.rtt_samples.append(tick - sent)

    def drain(self):
        out, self._outbox = self._outbox, []
        return out
