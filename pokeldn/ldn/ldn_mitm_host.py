"""The ldn_mitm host side: hosting a network for an emulated console over the LAN.

`ldn_mitm.py` speaks this protocol as a joiner. This is the other end. An emulator in ldn_mitm mode
has no radio, so the association is an exchange on UDP and TCP port 11452 and the game's own Pia
traffic then flows over the LAN on the ordinary Pia port.

    UDP  console -> host:11452   Scan          header only, broadcast and unicast
    UDP  host    -> console      ScanResp      NetworkInfo, 0x480
    TCP  console -> host:11452   Connect       NodeInfo, 0x40
    TCP  host    -> console      SyncNetwork   NetworkInfo with the console in it, held open

`IpHostTransport` carries the same surface as `transport.HostTransport`, so a host application takes
it as its `transport_factory` and nothing above the transport changes.

An emulated console's node carries its real LAN address, so every participant address in the
NetworkInfo is a LAN address and Pia is not tunnelled. docs/ldn.md.
"""

import os
import select
import socket
import struct
import threading

from pokeldn.ldn import ldn_mitm
from pokeldn.ldn.transport import PIA_PORT

NODE_MAX = 8
OFF_INTENT_ID = 0x00
OFF_NODE_COUNT_MAX = 0x66
OFF_NODE_COUNT = 0x67
OFF_NODES = 0x68
OFF_SECURITY_MODE = 0x60
OFF_ACCEPT_POLICY = 0x62
OFF_CHANNEL = 0x48
OFF_LINK_LEVEL = 0x4A
OFF_NETWORK_TYPE = 0x4B

NETWORK_TYPE_LDN = 2
SECURITY_MODE_RETAIL = 1
ACCEPT_ALL = 0


OFF_NODE_LOCAL_COMM_VERSION = 0x2E


def build_node_info(ip, mac, name=b"", node_id=0, connected=1, local_comm_version=0):
    """The 0x40-byte NodeInfo for one participant. The address is the LAN address the emulator
    reaches, little-endian, which is what `ldn_mitm.build_node_info` writes for a joiner.

    `localCommunicationVersion` is a u16 at 0x2E, aligned after the byte at 0x2C rather than packed
    against it. The console's own node in a NetworkInfo read back out of the running game carries 88
    there, which is the value its `ConnectImpl` passes.
    """
    out = bytearray(ldn_mitm.NODE_INFO_SIZE)
    out[0x00:0x04] = socket.inet_aton(ip)[::-1]
    out[0x04:0x0A] = bytes(mac)
    out[0x0A] = node_id & 0xFF
    out[0x0B] = 1 if connected else 0
    out[0x0C:0x2C] = bytes(name).ljust(0x20, b"\0")[:0x20]
    struct.pack_into("<H", out, OFF_NODE_LOCAL_COMM_VERSION, local_comm_version)
    return bytes(out)


def build_network_info(*, local_comm_id, scene_id, host_ip, host_mac, session_id,
                       advertise_data=b"", node_count_max=2, host_name=b"", channel=1,
                       local_comm_version=0):
    """A 0x480 `nn::ldn::NetworkInfo` with one node, the host.

    Layout: NetworkId 0x00 (IntentId 0x10 then SessionId 0x10), CommonNetworkInfo 0x20, then
    LdnNetworkInfo at 0x50 whose nodes start at 0x68 and whose advertise data starts at 0x26C.
    The offsets `ldn_mitm.py` reads a real emulator's SyncNetwork at are the same ones written here.

    `session_id` is the network's 16-byte identity: the LDN `NetworkId.ssid`
    [vendor/LDN/ldn/__init__.py:1921], which the text `Ssid` field carries in hexadecimal [:1910].
    It is also the Pia session key's plaintext, `AES(game_key).encrypt(ssid)` [crypto.py:114], and
    the Pia network id is `crc32(ssid[1:16])` [:115], so a host whose Pia keys off one value while
    it advertises another is dropped without a symptom. The text form is derived here rather than
    passed, so the two cannot disagree.

    SecurityParameter is left zero. It carries the advertisement's key material on the radio, and an
    ldn_mitm network has no advertisement to encrypt.
    """
    session_id = bytes(session_id)
    if len(session_id) != 16:
        raise ValueError(f"a session id is 16 bytes, got {len(session_id)}")
    if len(advertise_data) > 0x180:
        raise ValueError(f"advertise data is {len(advertise_data)} bytes, the field holds 0x180")
    info = bytearray(ldn_mitm.NETWORK_INFO_SIZE)
    struct.pack_into("<QHHI", info, OFF_INTENT_ID, local_comm_id, 0, scene_id, 0)
    info[ldn_mitm.OFF_SESSION_ID:ldn_mitm.OFF_SESSION_ID + 16] = session_id
    info[ldn_mitm.OFF_HOST_MAC:ldn_mitm.OFF_HOST_MAC + 6] = bytes(host_mac)
    name = session_id.hex().encode()
    info[ldn_mitm.OFF_SSID] = len(name)
    info[ldn_mitm.OFF_SSID + 1:ldn_mitm.OFF_SSID + 1 + len(name)] = name
    struct.pack_into("<h", info, OFF_CHANNEL, channel)
    info[OFF_LINK_LEVEL] = 3
    info[OFF_NETWORK_TYPE] = NETWORK_TYPE_LDN
    struct.pack_into("<H", info, OFF_SECURITY_MODE, SECURITY_MODE_RETAIL)
    info[OFF_ACCEPT_POLICY] = ACCEPT_ALL
    info[OFF_NODE_COUNT_MAX] = node_count_max
    info[OFF_NODE_COUNT] = 1
    node = build_node_info(host_ip, host_mac, host_name, node_id=0, connected=1,
                           local_comm_version=local_comm_version)
    info[OFF_NODES:OFF_NODES + ldn_mitm.NODE_INFO_SIZE] = node
    # Every slot carries its own index at NodeInfo+0x0A, connected or not, which is what a
    # NetworkInfo read off a running ldn_mitm host holds: slots 2..7 are zero apart from that id.
    for index in range(1, 8):
        info[OFF_NODES + index * ldn_mitm.NODE_INFO_SIZE + 0x0A] = index
    struct.pack_into("<H", info, ldn_mitm.OFF_ADVERTISE_SIZE, len(advertise_data))
    info[ldn_mitm.OFF_ADVERTISE_DATA:
         ldn_mitm.OFF_ADVERTISE_DATA + len(advertise_data)] = advertise_data
    return bytes(info)


def set_node(info, index, node):
    """-> `info` with node `index` replaced and the node count raised to cover it."""
    out = bytearray(info)
    at = OFF_NODES + index * ldn_mitm.NODE_INFO_SIZE
    out[at:at + ldn_mitm.NODE_INFO_SIZE] = node
    out[OFF_NODE_COUNT] = max(out[OFF_NODE_COUNT], index + 1)
    return bytes(out)


def read_node(info, index):
    """-> (ip, mac, node_id, connected, name) of one node."""
    at = OFF_NODES + index * ldn_mitm.NODE_INFO_SIZE
    raw = info[at:at + ldn_mitm.NODE_INFO_SIZE]
    ip = socket.inet_ntoa(raw[0:4][::-1])
    name = raw[0x0C:0x2C].split(b"\0")[0]
    return ip, raw[4:10], raw[0x0A], raw[0x0B], name


def node_local_comm_version(info, index):
    at = OFF_NODES + index * ldn_mitm.NODE_INFO_SIZE + OFF_NODE_LOCAL_COMM_VERSION
    return int.from_bytes(info[at:at + 2], "little")


def local_ip(toward="8.8.8.8"):
    """-> the address this machine would use to reach `toward`, without sending anything."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((toward, 9))
        return s.getsockname()[0]
    finally:
        s.close()


def broadcast_for(ip):
    """-> the /24 broadcast address. VMware host-only networks are /24."""
    return ip.rsplit(".", 1)[0] + ".255"


class IpHostTransport:
    """`transport.HostTransport`'s surface over ldn_mitm instead of over a radio.

    The constructor takes the radio arguments the host applications pass and ignores them, so it
    drops into `transport_factory` unchanged. Nothing here needs root.
    """

    NEEDS_RADIO = False
    LOCAL_COMMUNICATION_ID = 0x01006fa0233f8000
    SCENE_ID = 22287
    APPLICATION_VERSION = 88

    def __init__(self, app_data=b"", password=None, nickname="EMU", keys_path=None,
                 local_comm_id=None, scene_id=None, app_version=None, max_participants=2,
                 phyname=None, ifname=None, ap_ifname=None, mon_ifname=None,
                 channel=None, skip_encryption=False, accept_decrypted_ccmp=False,
                 tracer=None, log=print, protocol=3, ssid=None,
                 our_ip=None, discovery_port=ldn_mitm.PORT, pia_port=PIA_PORT,
                 mirror_comm_version=False, mac=None):
        self.log = log
        self.info = getattr(log, "info", log)
        self.tracer = tracer
        self.mirror_comm_version = mirror_comm_version
        self.app_data = bytes(app_data or b"")
        self.nickname = nickname
        self.max_participants = max_participants
        self.channel = 1 if channel is None else channel
        self.discovery_port = discovery_port
        # Both ports are arguments so a test can hold a whole host on free ports while a live one
        # is on the real ones.
        self.pia_port = pia_port
        if local_comm_id is not None:
            self.LOCAL_COMMUNICATION_ID = local_comm_id
        if scene_id is not None:
            self.SCENE_ID = scene_id
        if app_version is not None:
            self.APPLICATION_VERSION = app_version
        self.our_ip = our_ip or local_ip()
        self.host_ip = self.our_ip
        # An ldn_mitm node's MAC ENCODES ITS ADDRESS: the emulator gives itself 02:00 followed by
        # the four bytes of its LAN address, so the console at 172.16.86.1 is 02:00:ac:10:56:01.
        # A random MAC here is a node whose two identities disagree, and a peer that maps one to the
        # other gets an address that is nobody. Follow the convention the peer already uses.
        self.our_mac = mac if mac else (b"\x02\x00" + socket.inet_aton(self.our_ip))
        # One value, three uses: the advertised NetworkId.SessionId, the text Ssid in hexadecimal,
        # and the Pia session key's plaintext. HostTransport's `ssid` is the same 16 raw bytes.
        self.ssid = bytes(ssid) if ssid else os.urandom(16)
        if len(self.ssid) != 16:
            raise ValueError(f"an LDN ssid is 16 bytes, got {len(self.ssid)}")
        self.session_id = self.ssid
        self.broadcast = broadcast_for(self.our_ip)
        self.iface = None
        self.participants = []
        self.join_events = 0
        self.tx_dropped = 0
        self._info = None
        self._pia = None
        self._udp = None
        # Bound to the advertised address, for sending. A wildcard socket's replies leave with a
        # source the kernel picks, and on a peer that shares this machine that is the peer's own
        # LDN address, which ldn_mitm discards as its own packet (LanProtocol.Read). The wildcard
        # sockets stay for receiving: a socket bound to one address gets no subnet broadcast, and
        # a stock emulator on the LAN discovers by broadcast alone.
        self._udp_tx = None
        self._pia_tx = None
        self._tcp = None
        self._clients = []
        # conn -> the node slot it was seated in. A station's advertised address is its own node
        # info's, which a peer sharing this machine states differently from the address its TCP
        # connection comes from, so the slot cannot be found by address when the connection closes.
        self._seats = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._rx_seen = 0
        self._scans = 0

    # -- bring-up ---------------------------------------------------------------

    def _build_info(self):
        return build_network_info(
            local_comm_id=self.LOCAL_COMMUNICATION_ID, scene_id=self.SCENE_ID,
            host_ip=self.our_ip, host_mac=self.our_mac,
            session_id=self.session_id, advertise_data=self.app_data,
            node_count_max=self.max_participants,
            host_name=self.nickname.encode()[:0x20], channel=self.channel,
            local_comm_version=self.APPLICATION_VERSION)

    def start(self, timeout=30, attempts=3, settle=1.5, preflight=True):
        self._info = self._build_info()
        self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._udp.bind(("0.0.0.0", self.discovery_port))
        self._udp_tx = self._bound_to_us(self.discovery_port)
        self._tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._tcp.bind(("0.0.0.0", self.discovery_port))
        self._tcp.listen(4)
        self._pia = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._pia.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._pia.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._pia.bind(("0.0.0.0", self.pia_port))
        self._pia.setblocking(False)
        self._pia_tx = self._bound_to_us(self.pia_port)
        self._pia_tx.setblocking(False)
        if self.tracer is not None:
            # There is no advertisement frame to record over IP, so the capture carries the ssid
            # itself; host_decode.py needs it to key Pia.
            self.tracer.write("ldn_ssid", hex=self.ssid.hex(), our_ip=self.our_ip,
                              app_data=self.app_data.hex())
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        self.log(f"[host] ldn_mitm host up on {self.our_ip}:{self.discovery_port} "
                 f"ssid={self.ssid.decode(errors='replace')} mac={self.our_mac.hex()} "
                 f"comm_id=0x{self.LOCAL_COMMUNICATION_ID:016x} scene={self.SCENE_ID} "
                 f"beacon={len(self.app_data)}B, Pia on {self.pia_port}")
        self.info(f"Hosting over the LAN for an emulated console. Answering scans on "
                  f"{self.our_ip}:{self.discovery_port}.")
        return self

    def _bound_to_us(self, port):
        """-> a UDP socket on `our_ip`:`port` next to the wildcard one on the same port. A unicast
        to our address lands here rather than on the wildcard socket, so both are read."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind((self.our_ip, port))
        return s

    # -- the discovery service --------------------------------------------------

    def _serve(self):
        while not self._stop.is_set():
            socks = [s for s in (self._udp, self._udp_tx, self._tcp) if s is not None]
            socks += [c for c, _ in self._clients]
            try:
                readable, _, _ = select.select(socks, [], [], 0.2)
            except (OSError, ValueError):
                break
            for s in readable:
                try:
                    if s is self._udp or s is self._udp_tx:
                        self._on_scan(s)
                    elif s is self._tcp:
                        self._on_accept()
                    else:
                        self._on_client(s)
                except OSError as e:                       # pragma: no cover
                    if not self._stop.is_set():
                        self.log(f"[host] discovery: {e}")

    def _on_scan(self, sock):
        data, addr = sock.recvfrom(4096)
        try:
            kind, _payload = ldn_mitm.parse(data)
        except ValueError as e:
            self.log(f"[host] discovery: {addr[0]} sent {len(data)} bytes we cannot read: {e}")
            return
        if kind != ldn_mitm.SCAN:
            self.log(f"[host] discovery: {addr[0]} sent type {kind} over UDP, not a Scan")
            return
        self._scans += 1
        with self._lock:
            info = self._info
        self._udp_tx.sendto(ldn_mitm.build(ldn_mitm.SCAN_RESP, info), addr)
        if self._scans in (1, 2, 5, 10, 50, 100):
            self.log(f"[host] scan #{self._scans} from {addr[0]}:{addr[1]}, answered with "
                     f"{ldn_mitm.NETWORK_INFO_SIZE} bytes of NetworkInfo")

    def _on_accept(self):
        conn, addr = self._tcp.accept()
        conn.setblocking(True)
        self._clients.append((conn, addr))
        self.log(f"[host] discovery: TCP connection from {addr[0]}:{addr[1]}")

    def _on_client(self, conn):
        addr = next((a for c, a in self._clients if c is conn), ("?", 0))
        try:
            data = conn.recv(8192)
        except OSError:
            data = b""
        if not data:
            self._drop(conn, addr, "the connection closed")
            return
        try:
            kind, payload = ldn_mitm.parse(data)
        except ValueError as e:
            self.log(f"[host] discovery: {addr[0]} sent an unreadable message: {e}")
            return
        if kind != ldn_mitm.CONNECT:
            self.log(f"[host] discovery: {addr[0]} sent type {kind} over TCP, not a Connect")
            return
        node = bytes(payload)[:ldn_mitm.NODE_INFO_SIZE].ljust(ldn_mitm.NODE_INFO_SIZE, b"\0")
        index = self._seat(node)
        self._seats[conn] = index
        with self._lock:
            info = self._info
        conn.sendall(ldn_mitm.build(ldn_mitm.SYNC_NETWORK, info))
        for other, _a in self._clients:
            if other is not conn:
                try:
                    other.sendall(ldn_mitm.build(ldn_mitm.SYNC_NETWORK, info))
                except OSError:
                    pass
        ip, mac, node_id, _c, name = read_node(info, index)
        n1ip, _m, _i, n1c, _nm = read_node(info, 1)
        self.log(f"[host] *** CONSOLE JOINED *** idx={index} ip={ip} mac={mac.hex()} "
                 f"name={name!r} (node id {node_id}); SyncNetwork tx NodeCount="
                 f"{info[OFF_NODE_COUNT]} node1={n1ip} connected={n1c}")
        self.info("A console joined the network.")

    def _seat(self, node):
        """Give the joiner the first free node slot and hand it that node id.

        The joiner's own NodeInfo states its `localCommunicationVersion` at 0x2E. `nn::ldn` refuses
        a connection whose version disagrees with the network's, so what the joiner states is worth
        logging on every join, and `mirror_comm_version` puts it on the host's own node rather than
        leaving the host advertising a version the game did not ask for.
        """
        joiner_version = struct.unpack_from("<H", node, OFF_NODE_LOCAL_COMM_VERSION)[0]
        with self._lock:
            index = self._info[OFF_NODE_COUNT]
            if index >= NODE_MAX:
                index = 1
            seated = bytearray(node)
            seated[0x0A] = index
            seated[0x0B] = 1
            self._info = set_node(self._info, index, bytes(seated))
            host_version = struct.unpack_from(
                "<H", self._info, OFF_NODES + OFF_NODE_LOCAL_COMM_VERSION)[0]
            if self.mirror_comm_version and joiner_version != host_version:
                host = bytearray(self._info[OFF_NODES:OFF_NODES + ldn_mitm.NODE_INFO_SIZE])
                struct.pack_into("<H", host, OFF_NODE_LOCAL_COMM_VERSION, joiner_version)
                self._info = set_node(self._info, 0, bytes(host))
                self.log(f"[host] node localCommunicationVersion: joiner says {joiner_version}, "
                         f"host said {host_version}; the host node now says {joiner_version}")
            else:
                self.log(f"[host] node localCommunicationVersion: joiner {joiner_version}, "
                         f"host {host_version}")
            info = self._info
        ip, mac, _id, _c, name = read_node(info, index)
        self.participants.append((index, ip, mac, name))
        self.join_events += 1
        return index

    def _drop(self, conn, addr, why):
        self._clients = [(c, a) for c, a in self._clients if c is not conn]
        try:
            conn.close()
        except OSError:
            pass
        seat = self._seats.pop(conn, None)
        gone = [p for p in self.participants if p[0] == seat or p[1] == addr[0]]
        for p in gone:
            self.participants.remove(p)
            with self._lock:
                self._info = set_node(self._info, p[0],
                                      bytes(ldn_mitm.NODE_INFO_SIZE))
                count = self._info[OFF_NODE_COUNT]
                self._info = self._info[:OFF_NODE_COUNT] + bytes([max(1, count - 1)]) \
                    + self._info[OFF_NODE_COUNT + 1:]
        self.log(f"[host] console left: {addr[0]} ({why}), "
                 f"node {seat if seat is not None else '?'} freed, "
                 f"{self._info[OFF_NODE_COUNT]} node(s) advertised")

    # -- the data plane ---------------------------------------------------------

    def set_application_data(self, data):
        self.app_data = bytes(data)
        with self._lock:
            if self._info is None:
                return
            info = bytearray(self._info)
            struct.pack_into("<H", info, ldn_mitm.OFF_ADVERTISE_SIZE, len(self.app_data))
            info[ldn_mitm.OFF_ADVERTISE_DATA:ldn_mitm.OFF_ADVERTISE_DATA + 0x180] = \
                self.app_data.ljust(0x180, b"\0")[:0x180]
            self._info = bytes(info)
        for conn, _a in list(self._clients):
            try:
                conn.sendall(ldn_mitm.build(ldn_mitm.SYNC_NETWORK, self._info))
            except OSError:
                pass

    def set_app_data_later(self, data):
        self.set_application_data(data)

    def send(self, datagram, dst_ip):
        dst = self.broadcast if dst_ip in (self.broadcast, "255.255.255.255") else dst_ip
        if self.tracer is not None:
            self.tracer.write("udp_out", dst=dst, hex=bytes(datagram).hex())
        try:
            self._pia_tx.sendto(datagram, (dst, self.pia_port))
        except BlockingIOError:
            self.tx_dropped += 1
            if self.tx_dropped in (1, 10, 100, 1000):
                self.log(f"[host] sendto would block; dropped {self.tx_dropped} datagram(s)")
        except OSError as e:                               # pragma: no cover
            self.log(f"[host] sendto failed: {e}")

    def recv(self):
        out = []
        if self._pia is None:
            return out
        for sock in (self._pia_tx, self._pia):
            self._drain(sock, out)
        return out

    def _drain(self, sock, out):
        while True:
            try:
                payload, addr = sock.recvfrom(65535)
            except (BlockingIOError, OSError):
                break
            src_ip = addr[0]
            if src_ip == self.our_ip:
                continue
            self._rx_seen += 1
            if self._rx_seen <= 10:
                self.log(f"[host] RX #{self._rx_seen}: {src_ip} len={len(payload)} "
                         f"{payload[:4].hex()}")
            if self.tracer is not None:
                self.tracer.write("udp_in", src=src_ip, dst=self.our_ip, hex=payload.hex())
            out.append((payload, src_ip))

    def wait_readable(self, timeout):
        timeout = max(0.0, float(timeout))
        if self._pia is None:
            self._stop.wait(timeout)
            return False
        try:
            readable, _, _ = select.select([self._pia, self._pia_tx], [], [], timeout)
        except (OSError, ValueError):
            return False
        return bool(readable)

    def stop(self):
        self._stop.set()
        for conn, _a in list(self._clients):
            try:
                conn.close()
            except OSError:
                pass
        self._clients = []
        self._seats = {}
        for s in (self._udp, self._udp_tx, self._tcp, self._pia, self._pia_tx):
            try:
                if s:
                    s.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.log(f"[host] ldn_mitm host down after {self._scans} scans, "
                 f"{self.join_events} join(s)")
