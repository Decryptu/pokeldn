"""The ldn_mitm discovery and join protocol, as an emulated console speaks it.

On the radio the LDN association is the Wi-Fi link. Against an emulator there is no radio: the
association is this exchange on port 11452, and a peer that skips it sends Pia traffic from a station
the host's game has no node for. Game-independent, so it lives here rather than under a title.

    UDP  joiner -> host:11452   Scan          header only
    UDP  host   -> joiner       ScanResp      NetworkInfo, 0x480
    TCP  joiner -> host:11452   Connect       NodeInfo, 0x40
    TCP  host   -> joiner       SyncNetwork   NetworkInfo with the joiner in it

The host holds the TCP connection open for the session and closes it when the game leaves, so the
joiner must hold it too. `docs/lgpe_session.md` has the NetworkInfo layout.
"""

import socket
import struct

MAGIC = 0x11451400
HEADER_SIZE = 12
PORT = 11452

SCAN = 0
SCAN_RESP = 1
CONNECT = 2
SYNC_NETWORK = 3

NETWORK_INFO_SIZE = 0x480
NODE_INFO_SIZE = 0x40

# nn::ldn::NetworkInfo. The nodes run 0x68..0x268, then a reserved u16, then the advertise data.
OFF_SESSION_ID = 0x10
OFF_HOST_MAC = 0x20
OFF_SSID = 0x26
OFF_ADVERTISE_SIZE = 0x26A
OFF_ADVERTISE_DATA = 0x26C


def compress(data):
    """ldn_mitm's zero-run encoding: a zero byte is followed by the count of further zeros, so a
    run of n zeros costs two bytes for any n up to 256."""
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        if b != 0:
            out.append(b)
            i += 1
            continue
        run = 0
        while i + run < n and data[i + run] == 0 and run < 256:
            run += 1
        out += bytes((0, run - 1))
        i += run
    return bytes(out)


def decompress(data, expect=None):
    """The inverse. Raises on a truncated run or a length that does not match `expect`."""
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        i += 1
        if b != 0:
            out.append(b)
            continue
        if i >= n:
            raise ValueError("a zero run with no count")
        out += b"\0" * (data[i] + 1)
        i += 1
    if expect is not None and len(out) != expect:
        raise ValueError(f"decompressed {len(out)} bytes, the header declared {expect}")
    return bytes(out)


def build(kind, payload=b"", compressed=True):
    """-> the datagram for `kind`, compressing the payload the way the emulator does."""
    body = compress(payload) if compressed and payload else payload
    return struct.pack("<IBBHHH", MAGIC, kind, 1 if (compressed and payload) else 0,
                       len(body), len(payload), 0) + body


def parse(data):
    """-> (kind, payload). Raises on a foreign magic or a short datagram."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"{len(data)} bytes is shorter than the header")
    magic, kind, comp, length, declared, _ = struct.unpack_from("<IBBHHH", data, 0)
    if magic != MAGIC:
        raise ValueError(f"magic {magic:#010x} is not ldn_mitm's")
    body = data[HEADER_SIZE:HEADER_SIZE + length]
    if len(body) != length:
        raise ValueError(f"payload is {len(body)} bytes, the header declared {length}")
    return kind, (decompress(body, declared) if comp else body)


NODE_INFO_VERSION_OFF = 0x2E


def build_node_info(ip, mac, name=b"RyuPlayer", version=0):
    """The 0x40-byte NodeInfo a joiner sends in its Connect: the IPv4 little-endian, the MAC, a
    one, then the user name, and at +0x2E the local communication version.

    A host publishes its own version there (a Legends Z-A host publishes 6, its application
    version) and a game compares the two before it will treat a station as a partner. A node that
    leaves it zero is admitted by LDN and by Pia and is never paired with.
    """
    packed = socket.inet_aton(ip)[::-1]
    info = bytearray((packed + mac + struct.pack("<H", 0x0100)
                      + name.ljust(0x20, b"\0")[:0x20]).ljust(NODE_INFO_SIZE, b"\0")
                     [:NODE_INFO_SIZE])
    struct.pack_into("<H", info, NODE_INFO_VERSION_OFF, version & 0xFFFF)
    return bytes(info)


def session_id(network_info):
    """-> the network's 16-byte SessionId, which at Pia 6.16-6.42 is the session key's plaintext."""
    if len(network_info) < OFF_SESSION_ID + 16:
        raise ValueError(f"a NetworkInfo is {NETWORK_INFO_SIZE} bytes, got {len(network_info)}")
    return bytes(network_info[OFF_SESSION_ID:OFF_SESSION_ID + 16])


def advertise_data(network_info):
    """-> the advertise data a NetworkInfo declares, which is what a session key derives from."""
    if len(network_info) < OFF_ADVERTISE_DATA:
        raise ValueError(f"a NetworkInfo is {NETWORK_INFO_SIZE} bytes, got {len(network_info)}")
    size = struct.unpack_from("<H", network_info, OFF_ADVERTISE_SIZE)[0]
    return network_info[OFF_ADVERTISE_DATA:OFF_ADVERTISE_DATA + size]


def host_mac(network_info):
    return network_info[OFF_HOST_MAC:OFF_HOST_MAC + 6]
