"""Pia's LAN mode up to 5.45: sessions found by UDP broadcast on an ordinary IP network, no radio.

The browse exchange, its crypto challenge, the session key and the host message, from the
NintendoClients wiki's LAN Protocol page checked against an emulated Shield (docs/pia.md, LAN mode).
Everything above the station handshake is the same Pia as over LDN.
"""
import hashlib
import hmac
import os
import select
import socket
import struct
import threading
import time

from pokeldn.ldn.userspace_ip import _Readable

BROWSE_PORT = 30000          # browse requests, 5.45 and earlier
STATION_PORTS = range(49152, 49156)
BROADCAST_PORT = 40000       # a station's broadcast messages

PROTOCOL = 0x44
BROWSE_REQUEST, BROWSE_REPLY, HOST_REQUEST, HOST_MESSAGE = 0, 1, 3, 4
SESSION_REQUEST, SESSION_MESSAGE, KEEP_ALIVE = 5, 6, 7

SEARCH_CRITERIA_SIZE = 0x23A
SESSION_INFO_SIZE = 0x511
CHALLENGE_VERSION = 2        # 5.11-5.45
CHALLENGE_SIZE = 256
RESPONSE_SIZE = 16
STATION_INFO_SIZE = 50

SEARCH_MIN_PLAYERS, SEARCH_MAX_PLAYERS, SEARCH_OPENED, SEARCH_VACANT = 0x1, 0x2, 0x4, 0x8
SEARCH_GAME_MODE, SEARCH_SESSION_TYPE = 0x10, 0x20


def constant_id(ip, port):
    """A LAN station's constant id: its IPv4 address over its port, as a console reports its own."""
    return (struct.unpack(">I", socket.inet_aton(ip))[0] << 32) | (port & 0xFFFF)


def service_variable_id(ip, port):
    return ((struct.unpack(">I", socket.inet_aton(ip))[0] & 0xFFFF) << 16) | (port & 0xFFFF)


def station_mac(ip):
    """A LAN station's stand-in MAC, `02 00` then its address, the shape a launcher's seat carries
    (the ldn_mitm seat's convention); `station_ip` reads it back."""
    return b"\x02\x00" + socket.inet_aton(ip)


def station_ip(mac):
    return socket.inet_ntoa(bytes(mac)[2:6])


def broadcast_address(ip, netmask="255.255.255.0"):
    """`local | ~mask`, the address the challenge nonce opens with."""
    a = struct.unpack(">I", socket.inet_aton(ip))[0]
    m = struct.unpack(">I", socket.inet_aton(netmask))[0]
    return socket.inet_ntoa(struct.pack(">I", (a | ~m) & 0xFFFFFFFF))


def _hmac16(key, data):
    return hmac.new(bytes(key), bytes(data), hashlib.sha256).digest()[:16]


def session_key(game_key, key_param):
    """The session's AES key: HMAC-SHA256(game key, key param with its last byte plus one)[:16]."""
    p = bytearray(key_param)
    p[-1] = (p[-1] + 1) & 0xFF
    return _hmac16(game_key, p)


def packet_iv(source_ip, connection_id, nonce8):
    """The GCM IV of a LAN packet: the sender's IPv4 address, the header's connection id, the last
    seven bytes of the header nonce."""
    return socket.inet_aton(source_ip) + bytes([connection_id & 0xFF]) + bytes(nonce8)[1:]


def _gcm(key, nonce):
    from Crypto.Cipher import AES
    return AES.new(bytes(key), AES.MODE_GCM, nonce=nonce)


def _nonce(broadcast, counter):
    return socket.inet_aton(broadcast) + struct.pack(">Q", counter & (2 ** 64 - 1))


def build_challenge(game_key, broadcast, counter, challenge_key=None, challenge=None):
    """-> (the 0x12A-byte challenge, its plaintext). `broadcast` is the receiver's broadcast address."""
    from Crypto.Cipher import AES
    challenge_key = challenge_key or os.urandom(16)
    plain = challenge or os.urandom(CHALLENGE_SIZE)
    key = AES.new(bytes(game_key), AES.MODE_ECB).encrypt(challenge_key)
    ct, tag = _gcm(key, _nonce(broadcast, counter)).encrypt_and_digest(plain)
    return (struct.pack(">BBQ16s16s", CHALLENGE_VERSION, 1, counter, challenge_key, tag) + ct,
            plain)


def parse_challenge(data):
    version, enabled, counter, key, tag = struct.unpack_from(">BBQ16s16s", data, 0)
    return {"version": version, "enabled": enabled, "counter": counter, "key": key, "tag": tag,
            "data": bytes(data[0x2A:])}


def open_challenge(game_key, broadcast, data):
    """-> the 256 challenge bytes a browse request carries, or None if its tag fails."""
    from Crypto.Cipher import AES
    c = parse_challenge(data)
    key = AES.new(bytes(game_key), AES.MODE_ECB).encrypt(c["key"])
    try:
        return _gcm(key, _nonce(broadcast, c["counter"])).decrypt_and_verify(c["data"], c["tag"])
    except ValueError:
        return None


def build_response(game_key, broadcast, counter, challenge_plain, key_param, challenge_key=None):
    """The 0x3A-byte challenge reply: HMAC(game key, challenge)[:16], under HMAC(game key, key param).
    The key param is this reply's challenge key followed by the request's (`0x0178b464`)."""
    challenge_key = challenge_key or os.urandom(16)
    ct, tag = _gcm(_hmac16(game_key, key_param), _nonce(broadcast, counter)).encrypt_and_digest(
        _hmac16(game_key, challenge_plain))
    return struct.pack(">BBQ16s16s", CHALLENGE_VERSION, 1, counter, challenge_key, tag) + ct


def check_response(game_key, broadcast, data, challenge_plain, request_key):
    """True when a browse reply's challenge reply answers the challenge we sent under `request_key`.
    A console checks it under the reply's challenge key and its own request's, never under the
    session info's key param (`0x0178ab2c`)."""
    c = parse_challenge(data)
    key_param = c["key"] + bytes(request_key)
    try:
        got = _gcm(_hmac16(game_key, key_param), _nonce(broadcast, c["counter"])).decrypt_and_verify(
            c["data"], c["tag"])
    except ValueError:
        return False
    return hmac.compare_digest(got, _hmac16(game_key, challenge_plain))


def build_search_criteria(game_mode, max_players, session_type=0, min_players=None,
                          opened_only=True, vacant_only=True, offset=0, size=8, flags=None):
    """The 0x23A-byte LanSessionSearchCriteria; each range is a (maximum, minimum) pair of u16."""
    if flags is None:
        flags = SEARCH_GAME_MODE | SEARCH_MAX_PLAYERS
    lo = 0xFFFF if min_players is None else min_players
    out = bytearray(SEARCH_CRITERIA_SIZE)
    struct.pack_into(">HHHHBBIIII", out, 0, lo, lo, max_players, max_players, opened_only,
                     vacant_only, offset, size, game_mode, session_type)
    struct.pack_into(">I", out, 0x236, flags)
    return bytes(out)


def criteria_match(criteria, game_mode, players, max_players, min_players=0, session_type=0,
                   opened=True):
    """True when a session matches a browse's criteria, as a console host judges it before it
    answers (`0x0178e590`). Attribute criteria are not checked: Sword's trade search sets none."""
    flags = struct.unpack_from(">I", criteria, 0x236)[0]
    if flags & SEARCH_GAME_MODE and struct.unpack_from(">I", criteria, 0x12)[0] != game_mode:
        return False
    for flag, offset, value in ((SEARCH_MIN_PLAYERS, 0, min_players),
                                (SEARCH_MAX_PLAYERS, 4, max_players)):
        high, low = struct.unpack_from(">HH", criteria, offset)
        if flags & flag and high != 0xFFFF and low != 0xFFFF and not low <= value <= high:
            return False
    if flags & SEARCH_SESSION_TYPE and struct.unpack_from(">I", criteria, 0x16)[0] != session_type:
        return False
    opened_only, vacant_only = criteria[8], criteria[9]
    return not (opened_only and not opened) and not (vacant_only and players >= max_players)


def build_browse_request(criteria, challenge):
    return struct.pack(">BI", BROWSE_REQUEST, SEARCH_CRITERIA_SIZE) + bytes(criteria) + bytes(challenge)


def parse_browse_request(data):
    if len(data) < 5 + SEARCH_CRITERIA_SIZE or data[0] != BROWSE_REQUEST:
        raise ValueError("not a 5.45 browse request")
    criteria = data[5:5 + SEARCH_CRITERIA_SIZE]
    game_mode, session_type = struct.unpack_from(">II", criteria, 0x12)
    return {"criteria": criteria, "game_mode": game_mode, "session_type": session_type,
            "flags": struct.unpack_from(">I", criteria, 0x236)[0],
            "challenge": data[5 + SEARCH_CRITERIA_SIZE:]}


def parse_session_info(info):
    """LanSessionInfo, 5.10-5.45."""
    if len(info) < SESSION_INFO_SIZE:
        raise ValueError(f"a session info is {SESSION_INFO_SIZE:#x} bytes, this is {len(info):#x}")
    (game_mode, network_id) = struct.unpack_from(">II", info, 0)
    attributes = list(struct.unpack_from(">6I", info, 8))
    players, min_players, max_players, sys_ver, app_ver, session_type = struct.unpack_from(
        ">HHHBBH", info, 0x20)
    app_size = struct.unpack_from(">I", info, 0x1AA)[0]
    addr = info[0x1AF:0x1C1]
    host_ip = socket.inet_ntoa(addr[:4])
    host_port = struct.unpack_from(">H", addr, 16)[0]
    host_constant, host_variable, host_service = struct.unpack_from(">QII", info, 0x1C1)
    stations = []
    for i in range(16):
        e = info[0x1D1 + i * STATION_INFO_SIZE:0x1D1 + (i + 1) * STATION_INFO_SIZE]
        if e[0]:
            raw = e[2:0x2A]
            name = (raw.decode("utf-8", "replace") if e[1] == 1 else
                    raw.decode("utf-16-be", "replace")).rstrip("\0")
            stations.append({"role": e[0], "name": name,
                             "constant_id": struct.unpack_from(">Q", e, 0x2A)[0]})
    return {"game_mode": game_mode, "network_id": network_id, "attributes": attributes,
            "players": players, "min_players": min_players, "max_players": max_players,
            "system_version": sys_ver, "application_version": app_ver,
            "session_type": session_type, "application_data": bytes(info[0x2A:0x2A + app_size]),
            "opened": bool(info[0x1AE]), "host_ip": host_ip, "host_port": host_port,
            "host_constant": host_constant, "host_variable": host_variable,
            "host_service_variable": host_service, "stations": stations,
            "key_param": bytes(info[0x4F1:0x511])}


def parse_browse_reply(data):
    if len(data) < 5 or data[0] != BROWSE_REPLY:
        raise ValueError("not a browse reply")
    size = struct.unpack_from(">I", data, 1)[0]
    out = parse_session_info(data[5:5 + size])
    out["challenge_reply"] = bytes(data[5 + size:])
    return out


def build_host_request(network_id):
    return bytes([HOST_REQUEST]) + bytes(11) + struct.pack(">I", network_id)


def parse_host_message(body):
    """-> (network id, the host's station location bytes)."""
    if len(body) < 0x10 or body[0] != HOST_MESSAGE:
        raise ValueError("not a host message")
    return struct.unpack_from(">I", body, 0xC)[0], bytes(body[0x10:])


class LanSocket(_Readable):
    """One selectable socket over a station port and the broadcast port, as a launcher's Pia socket.

    It reads as the LDN socket does: a datagram from the console comes from (console, `pia_port`),
    and a send to `pia_port` goes to the console's own station port. A console on this machine
    answers from the alias it was sent to, so the source is the console whatever the kernel says."""

    def __init__(self, our_ip, our_port, console_ip, console_port, pia_port, broadcast=None):
        super().__init__()
        self.our_ip, self.our_port = our_ip, our_port
        self.console = (console_ip, console_port)
        self.pia_port = pia_port
        self._socks = [self._bind(our_ip, our_port)]
        if our_ip.startswith("127."):
            # A console on this machine holds *:40000: its broadcasts reach a socket bound to the
            # broadcast address itself, its unicasts the alias.
            self._socks.append(self._bind(our_ip, BROADCAST_PORT))
            try:
                self._socks.append(self._bind(broadcast or broadcast_address(console_ip),
                                              BROADCAST_PORT))
            except OSError:
                pass        # no interface has that broadcast address: unicasts only
        else:
            self._socks.append(self._bind("", BROADCAST_PORT))
        self._stop = False
        threading.Thread(target=self._pump, daemon=True).start()

    @staticmethod
    def _bind(ip, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            s.bind((ip, port))
        except OSError:
            s.close()
            raise
        return s

    def _pump(self):
        while not self._stop:
            try:
                ready = select.select(self._socks, [], [], 0.5)[0]
            except (OSError, ValueError):
                return
            for s in ready:
                try:
                    data, _src = s.recvfrom(65535)
                except OSError:
                    continue
                self._push((data, (self.console[0], self.pia_port)))

    def recvfrom(self, bufsize=65535):
        data, src = self._pop()
        return data[:bufsize], src

    def sendto(self, data, address):
        ip, port = address
        if port == self.pia_port:
            ip, port = self.console
        return self._socks[0].sendto(bytes(data), (ip, port))

    def getsockname(self):
        return (self.our_ip, self.our_port)

    def _detach(self):
        self._stop = True
        for s in self._socks:
            s.close()


def browse(game_key, console_ip, criteria, our_ip="", broadcast=None, tries=10, wait=1.0):
    """Browse requests to `console_ip` (an address or the subnet broadcast) until one is answered
    -> the parsed reply with `session_key`, or None. `broadcast` is the console's broadcast
    address, which the challenge nonce opens with."""
    broadcast = broadcast or broadcast_address(console_ip)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.bind((our_ip, 0))
    s.settimeout(wait)
    sent = {}
    try:
        for counter in range(1, tries + 1):
            challenge, plain = build_challenge(game_key, broadcast, counter)
            sent[counter] = (plain, parse_challenge(challenge)["key"])
            s.sendto(build_browse_request(criteria, challenge), (console_ip, BROWSE_PORT))
            try:
                while True:
                    data, src = s.recvfrom(4096)
                    if not data or data[0] != BROWSE_REPLY:
                        continue
                    got = parse_browse_reply(data)
                    answered = sent.get(parse_challenge(got["challenge_reply"])["counter"])
                    got["challenge_ok"] = answered is not None and check_response(
                        game_key, broadcast, got["challenge_reply"], *answered)
                    got["session_key"] = session_key(game_key, got["key_param"])
                    got["source"] = src
                    return got
            except socket.timeout:
                continue
    finally:
        s.close()
    return None


def build_session_info(game_mode, network_id, host_ip, host_port, host_constant, host_variable,
                       host_service_variable, key_param, stations, players=None, max_players=2,
                       system_version=7, application_version=7, session_type=0, app_data=b"",
                       opened=True, attributes=(0,) * 6):
    """LanSessionInfo, 5.10-5.45; `stations` is [(role, name, constant id)], role 1 the host."""
    out = bytearray(SESSION_INFO_SIZE)
    struct.pack_into(">II6IHHHBBH", out, 0, game_mode, network_id, *attributes,
                     len(stations) if players is None else players, 0, max_players,
                     system_version, application_version, session_type)
    out[0x2A:0x2A + len(app_data)] = app_data
    struct.pack_into(">I", out, 0x1AA, len(app_data))
    out[0x1AE] = int(opened)
    out[0x1AF:0x1B3] = socket.inet_aton(host_ip)
    struct.pack_into(">H", out, 0x1BF, host_port)
    struct.pack_into(">QII", out, 0x1C1, host_constant, host_variable, host_service_variable)
    for i, (role, name, constant) in enumerate(stations[:16]):
        at = 0x1D1 + i * STATION_INFO_SIZE
        out[at], out[at + 1] = role, 1
        raw = name.encode("utf-8")[:40]
        out[at + 2:at + 2 + len(raw)] = raw
        struct.pack_into(">Q", out, at + 0x2A, constant)
    out[0x4F1:0x511] = key_param
    return bytes(out)


def build_browse_reply(session_info, challenge_reply):
    return struct.pack(">BI", BROWSE_REPLY, len(session_info)) + session_info + challenge_reply


def build_host_message(network_id, location):
    return bytes([HOST_MESSAGE]) + bytes(11) + struct.pack(">I", network_id) + bytes(location)


def parse_lan_message(body):
    """-> (type, network id) of a host or session request, or None."""
    if len(body) < 0x10 or body[0] not in (HOST_REQUEST, SESSION_REQUEST, HOST_MESSAGE):
        return None
    return body[0], struct.unpack_from(">I", body, 0xC)[0]


def build_session_messages(session_info, sequence, nonce=None):
    """The session info cut into 800-byte fragments, each a SESSION_MESSAGE body."""
    nonce = nonce if nonce is not None else struct.unpack(">I", os.urandom(4))[0]
    pieces = [session_info[i:i + 800] for i in range(0, len(session_info), 800)]
    return [bytes([SESSION_MESSAGE]) + bytes(11)
            + struct.pack(">IHBBI", nonce, sequence & 0xFFFF, i, len(pieces), len(p)) + p
            for i, p in enumerate(pieces)]


def local_addresses():
    """This machine's IPv4 addresses off loopback, the default route's first."""
    out = [local_ip()]
    try:
        out += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    return [ip for i, ip in enumerate(out) if not ip.startswith("127.") and ip not in out[:i]]


def browse_any(game_key, criteria, tries=10, wait=1.0, addresses=None):
    """`browse` on the /24 broadcast of every local address at once -> the first reply, with the
    address it came in on as `our_ip` and that subnet's broadcast as `broadcast`, or None."""
    socks = {}
    for ip in addresses or local_addresses():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            s.bind((ip, 0))
        except OSError:
            s.close()
            continue
        socks[s] = (ip, broadcast_address(ip))
    try:
        for counter in range(1, tries + 1):
            sent = {}
            for s, (ip, bcast) in socks.items():
                challenge, plain = build_challenge(game_key, bcast, counter)
                sent[s] = (plain, parse_challenge(challenge)["key"])
                try:
                    s.sendto(build_browse_request(criteria, challenge), (bcast, BROWSE_PORT))
                except OSError:
                    pass
            deadline = time.time() + wait
            while time.time() < deadline:
                ready = select.select(list(socks), [], [], max(0.0, deadline - time.time()))[0]
                for s in ready:
                    data, src = s.recvfrom(4096)
                    if not data or data[0] != BROWSE_REPLY:
                        continue
                    got = parse_browse_reply(data)
                    ip, bcast = socks[s]
                    got["challenge_ok"] = check_response(game_key, bcast, got["challenge_reply"],
                                                         *sent[s])
                    got["session_key"] = session_key(game_key, got["key_param"])
                    got.update(source=src, our_ip=ip, broadcast=bcast)
                    return got
    finally:
        for s in socks:
            s.close()
    return None


def local_ip():
    """This machine's address on its default route."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


class LanHostTransport:
    """A LAN-mode session for a console to join: `transport.HostTransport`'s surface over UDP/IP.

    It answers browse requests with the session info, keys the session at the first valid one,
    seats a console on its host request and answers with `location`. `bind_host` names our station
    before `start`. A console on this machine is reached through a loopback alias: its packets
    arrive from that alias and stand for `console_ip` (default this machine's address)."""

    NEEDS_RADIO = False

    def __init__(self, game_key, game_mode, our_ip=None, our_port=STATION_PORTS[0],
                 max_participants=2, nickname="POKELDN", app_data=b"", broadcast=None,
                 console_ip=None, system_version=7, application_version=7, session_type=0,
                 quiet=5.0, log=print):
        self.game_key, self.game_mode = bytes(game_key), game_mode
        self.our_ip = our_ip or local_ip()
        self.our_port = our_port
        self.our_mac = station_mac(self.our_ip)
        self.loopback = self.our_ip.startswith("127.")
        self.console_ip = console_ip or (local_ip() if self.loopback else None)
        self.broadcast = broadcast or broadcast_address(
            self.console_ip if self.loopback else self.our_ip)
        self.max_participants, self.nickname = max_participants, nickname
        self.app_data = bytes(app_data)
        self.versions = (system_version, application_version, session_type)
        self.quiet = quiet
        self.log = log
        self.network_id = service_variable_id(self.our_ip, our_port)
        self.key_param = None
        self.session_key = None
        self.participants = []          # (index, ip, mac, name), as HostTransport lists them
        self.join_events = 0
        self.ports = {}                 # console ip -> its station port
        self.constants = {}             # console ip -> its constant id
        self.last_heard = {}
        self.host_constant = self.host_variable = self.host_service = None
        self.location = None
        self._rx = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._browse = []
        self._station = []
        self._browses = 0

    def bind_host(self, constant, variable, service_variable, location):
        self.host_constant, self.host_variable = constant, variable
        self.host_service, self.location = service_variable, bytes(location)

    @staticmethod
    def _bind(ip, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            s.bind((ip, port))
        except OSError:
            s.close()
            raise
        return s

    def _binds(self, port):
        # On this machine the console holds *:port: the alias takes unicasts, the broadcast address
        # its broadcasts.
        if not self.loopback:
            return [self._bind("", port)]
        out = [self._bind(self.our_ip, port)]
        try:
            out.append(self._bind(self.broadcast, port))
        except OSError:
            pass            # no interface has that broadcast address: unicasts only
        return out

    def start(self):
        self._browse = self._binds(BROWSE_PORT)
        self._station = [self._bind(self.our_ip if self.loopback else "", self.our_port)]
        self._station += self._binds(BROADCAST_PORT)
        threading.Thread(target=self._serve, daemon=True).start()
        self.log(f"[lan] session {self.network_id:#010x} on {self.our_ip}:{self.our_port}, "
                 f"answering browse requests on {BROWSE_PORT} (broadcast {self.broadcast})")
        return self

    def stop(self):
        self._stop.set()
        for s in self._browse + self._station:
            s.close()

    def stations(self):
        out = [(1, self.nickname, self.host_constant)]
        out += [(2, name, self.constants.get(ip, 0)) for _i, ip, _m, name in self.participants]
        return out

    def session_info(self):
        return build_session_info(
            self.game_mode, self.network_id, self.our_ip, self.our_port, self.host_constant,
            self.host_variable, self.host_service, self.key_param or bytes(32), self.stations(),
            max_players=self.max_participants, system_version=self.versions[0],
            application_version=self.versions[1], session_type=self.versions[2],
            app_data=self.app_data, opened=len(self.participants) + 1 < self.max_participants)

    def _on_browse(self, sock):
        data, addr = sock.recvfrom(4096)
        if self.location is None:
            return
        try:
            req = parse_browse_request(data)
        except ValueError:
            return
        players = len(self.participants) + 1
        if not criteria_match(req["criteria"], self.game_mode, players, self.max_participants,
                              session_type=self.versions[2]):
            return
        plain = open_challenge(self.game_key, self.broadcast, req["challenge"])
        if plain is None:
            self.log(f"[lan] browse from {addr[0]}:{addr[1]} whose challenge does not open with "
                     f"broadcast {self.broadcast}")
            return
        c = parse_challenge(req["challenge"])
        if self.key_param is None:
            self.first_request = data
            attrs = sum(1 for b in req["criteria"][0x1A:0x236] if b)
            self.log(f"[lan] first browse: game mode {req['game_mode']}, session type "
                     f"{req['session_type']}, flags {req['flags']:#x}, {attrs} attribute bytes set, "
                     f"ranges {req['criteria'][:0x12].hex()}")
            # The first valid request keys the session (wiki, Session Key Param).
            self.key_param = os.urandom(16) + c["key"]
            self.session_key = session_key(self.game_key, self.key_param)
            self.log(f"[lan] keyed by the first browse, session key {self.session_key.hex()}")
        # Only the session info keeps the first key param; each reply is keyed to its own request.
        reply_key = os.urandom(16)
        reply = build_response(self.game_key, self.broadcast, c["counter"], plain,
                               reply_key + c["key"], challenge_key=reply_key)
        self._browse[0].sendto(build_browse_reply(self.session_info(), reply), addr)
        self._browses += 1
        if self._browses in (1, 2, 5, 20, 100):
            self.log(f"[lan] browse #{self._browses} from {addr[0]}:{addr[1]} answered")

    def _source(self, ip):
        # A console on this machine answers from the alias it was sent to.
        return self.console_ip if self.loopback and ip == self.our_ip else ip

    def _serve(self):
        while not self._stop.is_set():
            try:
                ready = select.select(self._browse + self._station, [], [], 0.2)[0]
            except (OSError, ValueError):
                return
            for s in ready:
                try:
                    if s in self._browse:
                        self._on_browse(s)
                        continue
                    data, addr = s.recvfrom(65535)
                except OSError:
                    continue
                ip = self._source(addr[0])
                if s is self._station[0]:
                    self.ports[ip] = addr[1]
                with self._lock:
                    self.last_heard[ip] = time.time()
                    self._rx.append((data, ip))

    def _host_request(self, data, ip):
        """A Pia packet from a console not yet seated: seat it on its host request."""
        from pokeldn.ldn import pia4
        if self.session_key is None or not pia4.is_pia4(data):
            self.log(f"[lan] {ip}: {len(data)} B before the session is keyed: {data[:8].hex()}")
            return
        h = pia4.PiaHeader4.parse(data)
        plain = pia4.decrypt_payload(self.session_key, packet_iv(ip, h.station, h.nonce8),
                                     pia4.ciphertext(data), h.tag)
        if plain is None:
            self.log(f"[lan] {ip}: {len(data)} B that do not decrypt")
            return
        for m in pia4.parse_packet(plain):
            got = parse_lan_message(m["payload"]) if m["protocol"] == PROTOCOL else None
            if got is None or got[1] != self.network_id:
                self.log(f"[lan] {ip}: {m['protocol']:#04x} {m['payload'][:16].hex()} before a "
                         f"host request")
                continue
            if got[0] == HOST_REQUEST:
                self.constants[ip] = m["source"]
                if not any(p[1] == ip for p in self.participants):
                    index = 1 + max((p[0] for p in self.participants), default=0)
                    self.participants.append((index, ip, station_mac(ip), ""))
                    self.join_events += 1
                    self.log(f"[lan] {ip}:{self.ports.get(ip)} host request; seated at {index}, "
                             f"constant {m['source']:#018x}")
                self._send_lan(build_host_message(self.network_id, self.location), ip)
            elif got[0] == SESSION_REQUEST:
                for body in build_session_messages(self.session_info(), 0):
                    self._send_lan(body, ip)

    def _send_lan(self, body, ip):
        from pokeldn.ldn import pia4
        msg = pia4.build_message(body, protocol=PROTOCOL, source=self.host_constant,
                                 message_flags=pia4.MESSAGE_FLAGS)
        nonce8 = os.urandom(8)
        self.send(pia4.build_packet(self.session_key, packet_iv(self.our_ip, 0, nonce8), msg,
                                    nonce8=nonce8), ip)

    def recv(self):
        with self._lock:
            got, self._rx = self._rx, []
        out = []
        seated = {p[1] for p in self.participants}
        for data, ip in got:
            if ip in seated:
                out.append((data, ip))
            else:
                self._host_request(data, ip)
        now = time.time()
        for p in list(self.participants):
            if now - self.last_heard.get(p[1], now) > self.quiet:
                self.participants.remove(p)
                self.log(f"[lan] {p[1]} silent for {self.quiet:.0f} s; it left")
        return out

    def send(self, packet, dst_ip):
        port = self.ports.get(dst_ip, STATION_PORTS[0])
        try:
            self._station[0].sendto(bytes(packet), (dst_ip, port))
        except OSError as e:
            self.log(f"[lan] send to {dst_ip}:{port}: {e}")

    def wait_readable(self, timeout):
        with self._lock:
            if self._rx:
                return
        time.sleep(timeout)
