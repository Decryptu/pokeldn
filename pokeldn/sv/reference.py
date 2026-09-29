"""A Scarlet station's identity, recorded from an emulated Scarlet whose player is Player: 44
records on 0x81 and two fragments on 0x7C port 0, each fragment sent twice (docs/sv.md, The records).
"""
import os

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RECORDS = os.path.join(DATA, "records")
# (seconds after the host's key-0x80 open, fragment); both ends send this schedule.
OPEN_SCHEDULE = ((0.15, "start"), (0.17, "end"), (0.30, "start"), (0.32, "end"))


def open_fragment(tag):
    with open(os.path.join(DATA, f"open_{tag}.bin"), "rb") as fh:
        return fh.read()


def open_specs():
    """-> the identity fragments as `--send-on-open` specs, zlib-flagged."""
    return [f"{delay}:0x7c:0:{open_fragment(tag).hex()}:z:{tag}" for delay, tag in OPEN_SCHEDULE]


def fill_identity(args):
    """Give a launcher's `--record-set` and `--send-on-open` this identity where it passed neither,
    unless `--no-identity` (or, on the joiner, `--mirror-records`)."""
    if args.no_identity:
        return
    if args.record_set is None and not getattr(args, "mirror_records", False):
        args.record_set = RECORDS
    if not args.send_on_open:
        args.send_on_open = open_specs()
