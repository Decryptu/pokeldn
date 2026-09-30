"""The recorded game messages shipped in pokeldn/*/data carry no real player: every name in them is
an emulator's, and no account identifier is set. A file added there must pass this too."""
from pathlib import Path
import glob
import os
import re
import zlib

import pytest

from pokeldn.lgpe import reference as lgpe_reference
from pokeldn.sv import reference as sv_reference
from pokeldn.za import reference as za_reference

ROOT = os.path.join(os.path.dirname(__file__), "..", "pokeldn")
EMULATOR_NAMES = {"Player", "POKELDN", "VMJOINER"}
FILES = sorted(glob.glob(os.path.join(ROOT, "*", "data", "**", "*.bin"), recursive=True))


def plain(data):
    """A zlib-flagged Pia message (4 KB window, `484b`) inflated; anything else as it is."""
    return zlib.decompressobj().decompress(data) if data[:2] == b"\x48\x4b" else data


@pytest.mark.parametrize("path", FILES, ids=lambda p: os.path.relpath(p, ROOT))
def test_a_shipped_message_names_only_an_emulated_player(path):
    data = plain(Path(path).read_bytes())
    names = {m.decode("utf-16-le") for m in re.findall(rb"(?:[\x20-\x7e]\x00){3,}", data)}
    assert names <= EMULATOR_NAMES
    assert not re.search(rb"u-[0-9a-z]{20}", data)


def test_the_scarlet_identity_is_44_records_and_four_fragments_a_launcher_can_send():
    names = sorted(os.listdir(sv_reference.RECORDS))
    assert len(names) == 44 and "005.bin" not in names and "006.bin" not in names
    first = plain(Path(os.path.join(sv_reference.RECORDS, '001.bin')).read_bytes())
    sizes = [len(plain(Path(os.path.join(sv_reference.RECORDS, n)).read_bytes())) for n in names]
    assert sizes == [1395] * 43 + [75]              # 45 chunks of 1384 and one of 64, each after 11
    assert first[0x13:0x2d].decode("utf-16-le").rstrip("\0") == "Player"
    assert first[0x2d:0x43] == bytes(22)            # the account identifier, unset
    specs = sv_reference.open_specs()
    assert [s.split(":")[0] for s in specs] == ["0.15", "0.17", "0.3", "0.32"]
    assert all(plain(bytes.fromhex(s.split(":")[3])) for s in specs)


def test_the_launchers_find_the_shipped_messages_by_default():
    import lgpe_join
    import sv_join
    import za_join

    assert lgpe_join.build_parser().parse_args([]).reliable_payload == lgpe_reference.IDENTITY
    args = sv_join.build_parser().parse_args([])
    sv_reference.fill_identity(args)
    assert args.record_set == sv_reference.RECORDS and len(args.send_on_open) == 4
    args = sv_join.build_parser().parse_args(["--no-identity"])
    sv_reference.fill_identity(args)
    assert args.record_set is None and args.send_on_open == []
    game_dir = za_join.build_parser().parse_args([]).game_dir
    assert {n: len(za_reference.load(n, game_dir)) for n in za_reference.NAMES} == {
        "identity10": 106, "open11": 8, "identity11": 110, "identity11b": 13, "selection": 1211}
