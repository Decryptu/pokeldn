"""The 232-byte box structure Let's Go trades, and the 16-byte-header messages that carry it
(docs/lgpe_session.md)."""
import struct

BOX_SIZE = 232
BLOCK_SIZE = 56
HEADER_SIZE = 16
FLAGS = 0x0000FF00
FIRST_MESSAGE = 1
OFFER_MESSAGE = 2
COMMIT_MESSAGE = 3   # body is one u32; both stations send it twice, carrying 1 and then 2
RESULT_MESSAGE = 4   # the next round's party-offer channel, first sent after the trade animation

BLOCK_ORDER = [
    [0, 1, 2, 3], [0, 1, 3, 2], [0, 2, 1, 3], [0, 3, 1, 2], [0, 2, 3, 1], [0, 3, 2, 1],
    [1, 0, 2, 3], [1, 0, 3, 2], [2, 0, 1, 3], [3, 0, 1, 2], [2, 0, 3, 1], [3, 0, 2, 1],
    [1, 2, 0, 3], [1, 3, 0, 2], [2, 1, 0, 3], [3, 1, 0, 2], [2, 3, 0, 1], [3, 2, 0, 1],
    [1, 2, 3, 0], [1, 3, 2, 0], [2, 1, 3, 0], [3, 1, 2, 0], [2, 3, 1, 0], [3, 2, 1, 0],
]

__all__ = ["BOX_SIZE", "HEADER_SIZE", "FIRST_MESSAGE", "OFFER_MESSAGE", "COMMIT_MESSAGE", "RESULT_MESSAGE",
           "shuffle_value",
           "crypt", "checksum", "decrypt", "encrypt", "parse_message", "build_message",
           "TRAINER_ID", "trainer_id", "set_trainer_id"]

TRAINER_ID = 0x00
BOX_TRAINER_ID = 0x0C
OFF_PID = 0x18                      # PKHeX PB7.cs; the encryption constant is at 0x00


def shuffle_value(ec):
    return ((ec >> 13) & 0x1F) % 24


def crypt(data):
    """XOR the blocks with the stream keyed by the encryption constant. Its own inverse."""
    out = bytearray(data)
    seed = struct.unpack_from("<I", out, 0)[0]
    for i in range(8, BOX_SIZE, 2):
        seed = (seed * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        struct.pack_into("<H", out, i,
                         struct.unpack_from("<H", out, i)[0] ^ ((seed >> 16) & 0xFFFF))
    return bytes(out)


def checksum(plain):
    """The stored checksum covers the four blocks of the decrypted, unshuffled structure."""
    return sum(struct.unpack_from("<H", plain, i)[0]
               for i in range(8, BOX_SIZE, 2)) & 0xFFFF


def _reorder(data, order):
    out = bytearray(data[:8])
    for b in order:
        out += data[8 + b * BLOCK_SIZE:8 + (b + 1) * BLOCK_SIZE]
    return bytes(out)


def decrypt(data):
    """-> the 232-byte structure with its blocks decrypted and in order."""
    if len(data) != BOX_SIZE:
        raise ValueError(f"a box structure is {BOX_SIZE} bytes, not {len(data)}")
    plain = crypt(data)
    return _reorder(plain, BLOCK_ORDER[shuffle_value(struct.unpack_from("<I", plain, 0)[0])])


def encrypt(plain):
    """-> the structure shuffled and encrypted, with its checksum written."""
    if len(plain) != BOX_SIZE:
        raise ValueError(f"a box structure is {BOX_SIZE} bytes, not {len(plain)}")
    out = bytearray(plain)
    struct.pack_into("<H", out, 6, checksum(out))
    order = BLOCK_ORDER[shuffle_value(struct.unpack_from("<I", out, 0)[0])]
    inverse = [order.index(b) for b in range(4)]
    return crypt(_reorder(bytes(out), inverse))


def valid(data):
    """Whether an encrypted structure's sanity word and checksum agree with its contents."""
    if len(data) != BOX_SIZE:
        return False
    plain = decrypt(data)
    return (struct.unpack_from("<H", plain, 4)[0] == 0
            and struct.unpack_from("<H", plain, 6)[0] == checksum(plain))


def parse_message(data):
    """-> the header fields and the body of a trade message, or None if it is not one."""
    if len(data) < HEADER_SIZE:
        return None
    kind, size, step, flags = struct.unpack_from("<IIII", data, 0)
    # Every kind is accepted: narrowing to the kinds already seen has hidden a protocol step twice.
    if not 1 <= kind <= 0xFF or len(data) != HEADER_SIZE + size:
        return None
    return {"kind": kind, "size": size, "step": step, "flags": flags,
            "body": data[HEADER_SIZE:]}


def build_message(kind, body, step=None):
    """-> the 16-byte header and the body. A repeated offer under a fresh step is a new question,
    not a retransmission."""
    return struct.pack("<IIII", kind, len(body), kind if step is None else step,
                       FLAGS) + bytes(body)


def trainer_id(body, offset=TRAINER_ID):
    """-> the (id, secret id) pair a first message or a decrypted structure carries."""
    return struct.unpack_from("<HH", body, offset)


def set_trainer_id(body, tid, sid, offset=TRAINER_ID):
    """-> `body` with its trainer id pair replaced."""
    out = bytearray(body)
    struct.pack_into("<HH", out, offset, tid & 0xFFFF, sid & 0xFFFF)
    return bytes(out)


def fresh(raw, rand=None):
    """-> the structure, encrypted, under a new encryption constant and PID; shiny state kept."""
    import os
    rand = rand or os.urandom
    plain = bytearray(decrypt(raw) if valid(raw) else raw)
    pid = struct.unpack_from("<I", plain, OFF_PID)[0]
    high = int.from_bytes(rand(2), "little")
    struct.pack_into("<I", plain, OFF_PID, (high << 16) | (high ^ (pid >> 16) ^ (pid & 0xFFFF)))
    struct.pack_into("<I", plain, 0, int.from_bytes(rand(4), "little"))
    return encrypt(bytes(plain))
