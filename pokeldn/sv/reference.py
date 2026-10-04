"""A Scarlet station's identity, recorded from an emulated Scarlet whose player is Player: 44
records on 0x81 and two fragments on 0x7C port 0, each fragment sent twice (docs/sv.md, The records).
`named_record` puts another player name in record 1.
"""
import os

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RECORDS = os.path.join(DATA, "records")
# (seconds after the host's key-0x80 open, fragment); both ends send this schedule.
OPEN_SCHEDULE = ((0.15, "start"), (0.17, "end"), (0.30, "start"), (0.32, "end"))
NAME_OFFSET, NAME_SIZE = 0x13, 26   # in record 1, the first chunk of the block


def open_fragment(tag):
    with open(os.path.join(DATA, f"open_{tag}.bin"), "rb") as fh:
        return fh.read()


def open_specs():
    """-> the identity fragments as `--send-on-open` specs, zlib-flagged."""
    return [f"{delay}:0x7c:0:{open_fragment(tag).hex()}:z:{tag}" for delay, tag in OPEN_SCHEDULE]


def named_record(payload, name):
    """-> record 1 as sent (zlib) with its player called `name`, at most twelve characters."""
    from pokeldn.sv import streams

    raw = name.encode("utf-16-le")
    if not name or len(raw) > NAME_SIZE - 2:
        raise ValueError(f"a player name is 1 to {(NAME_SIZE - 2) // 2} characters, not {name!r}")
    record = streams.decompress(payload)
    if record[:1] != b"\x01" or len(record) < NAME_OFFSET + NAME_SIZE:
        raise ValueError("record 1 is not the first chunk of a block")
    return streams.compress(record[:NAME_OFFSET] + raw.ljust(NAME_SIZE, b"\0")
                            + record[NAME_OFFSET + NAME_SIZE:])


def player_name(payload):
    from pokeldn.sv import streams

    field = streams.decompress(payload)[NAME_OFFSET:NAME_OFFSET + NAME_SIZE]
    return field.decode("utf-16-le").split("\0", 1)[0]


def fill_identity(args):
    """Give a launcher's `--record-set` and `--send-on-open` this identity where it passed neither,
    unless `--no-identity` (or, on the joiner, `--mirror-records`)."""
    if args.no_identity:
        return
    if args.record_set is None and not getattr(args, "mirror_records", False):
        args.record_set = RECORDS
    if not args.send_on_open:
        args.send_on_open = open_specs()
