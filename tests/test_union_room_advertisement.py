"""The Union Room advertisement (the middle NPC on Pokemon Center 2F).

LINK_GROUP_UNION_ROOM_INIT accepts ACTIVITY_SEARCH only [src/data/union_room.h:419, src/union_room.c:1590];
the resume search accepts IN_UNION_ROOM | activity [src/data/union_room.h:407-418].

Run standalone (no pytest needed):   python tests/test_union_room_advertisement.py
"""

import functools
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.frlg.save import mevent_pokemon  # noqa: E402
from pokeldn.frlg.link import beacon
from pokeldn.ldn import transport  # noqa: E402
from pokeldn.frlg.link.host_beacon import (  # noqa: E402
    build_trade_app_data, build_union_room_app_data,
)
from pokeldn.config import DEFAULT_TRAINER  # noqa: E402
from pokeldn import config, host_cli  # noqa: E402
from pokeldn.frlg.link.host_app import HostApplication  # noqa: E402

SESSION_ID = b"\x7b\xf1"


def _search_word(app_data):
    record = _record(app_data)
    return int.from_bytes(
        record[beacon.SEARCH_WORD_OFFSET:beacon.SEARCH_WORD_OFFSET + 2], "little")


def test_constants_match_the_decomp():
    assert beacon.ACTIVITY_SEARCH == 12
    assert beacon.IN_UNION_ROOM == 1 << 6
    # IN_UNION_ROOM has to survive the packed field or the resume form cannot be expressed.
    assert beacon.IN_UNION_ROOM & beacon.SEARCH_ACTIVITY_MASK == beacon.IN_UNION_ROOM


def test_default_advertisement_is_the_bare_in_union_room_activity():
    """IsPartnerActivityIncompatible [link_rfu_2.c:2933] compares activity with IN_UNION_ROOM
    exactly; measured on hardware."""
    inactive, active = build_union_room_app_data(DEFAULT_TRAINER, SESSION_ID)
    word = _search_word(inactive)
    assert word & beacon.SEARCH_ACTIVITY_MASK == beacon.IN_UNION_ROOM
    assert word & beacon.SEARCH_ACTIVITY_MASK & ~beacon.IN_UNION_ROOM == 0
    # SetHostRfuGameData(ACTIVITY_SEARCH, 0, FALSE): no started bit, no wonder flags.
    assert not word & beacon.SEARCH_STARTED_ACTIVITY
    assert not word & beacon.SEARCH_HAS_CARD
    assert _search_word(active) & beacon.SEARCH_STARTED_ACTIVITY


def test_resume_form_is_expressible():
    """A console already inside the room accepts IN_UNION_ROOM | ACTIVITY_TRADE."""
    activity = beacon.IN_UNION_ROOM | beacon.ACTIVITY_TRADE
    inactive, _ = build_union_room_app_data(DEFAULT_TRAINER, SESSION_ID, activity=activity)
    word = _search_word(inactive)
    assert word & beacon.SEARCH_ACTIVITY_MASK == activity
    assert word & beacon.SEARCH_ACTIVITY_MASK & ~beacon.IN_UNION_ROOM == beacon.ACTIVITY_TRADE


def test_only_the_activity_differs_from_the_trade_advertisement():
    """Only the activity differs; the Pia header, version, language and unexplained regions are kept."""
    uroom, _ = build_union_room_app_data(DEFAULT_TRAINER, SESSION_ID)
    trade, _ = build_trade_app_data(DEFAULT_TRAINER, SESSION_ID)
    assert uroom[:beacon.PIA_HDR] == trade[:beacon.PIA_HDR]
    u_record, t_record = bytearray(_record(uroom)), bytearray(_record(trade))
    offset = beacon.SEARCH_WORD_OFFSET
    u_word = int.from_bytes(u_record[offset:offset + 2], "little")
    t_word = int.from_bytes(t_record[offset:offset + 2], "little")
    assert u_word & ~beacon.SEARCH_ACTIVITY_MASK == t_word & ~beacon.SEARCH_ACTIVITY_MASK
    u_record[offset:offset + 2] = t_record[offset:offset + 2]
    assert bytes(u_record) == bytes(t_record)


def test_activity_names_resolve_to_the_decomp_values():
    resolve = config.resolve_union_room_activity
    assert resolve(None) == beacon.IN_UNION_ROOM  # proven on hardware
    assert resolve("search") == beacon.ACTIVITY_SEARCH
    assert resolve("in-room") == beacon.IN_UNION_ROOM
    assert resolve("in-room-trade") == beacon.IN_UNION_ROOM | beacon.ACTIVITY_TRADE
    for name, value in config.UNION_ROOM_ACTIVITIES.items():
        assert value & beacon.SEARCH_ACTIVITY_MASK == value, name
    try:
        resolve("nonsense")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown name must raise")


def test_in_room_activities_carry_the_union_room_bit_and_search_does_not():
    """A console in the room searches with the resume list and drops a bare ACTIVITY_SEARCH."""
    assert not config.resolve_union_room_activity("search") & beacon.IN_UNION_ROOM
    for name in ("in-room", "in-room-trade", "in-room-chat"):
        assert config.resolve_union_room_activity(name) & beacon.IN_UNION_ROOM


def test_union_room_activity_flag_reaches_host_options():
    import frlg_trade_host
    parser = frlg_trade_host.build_parser()
    args = parser.parse_args(["--union-room", "--union-room-activity", "in-room-trade", "--no-live"])
    _p, _l, options = host_cli.build_host_config(parser, args)
    assert options.union_room_activity == beacon.IN_UNION_ROOM | beacon.ACTIVITY_TRADE
    assert options.union_room is True


@functools.lru_cache(maxsize=1)
def _party_files():
    """Two throwaway party files; `*.pk3` is gitignored."""
    directory = tempfile.mkdtemp(prefix="frlg-party-")
    paths = []
    for name, species, level in (("PARTY1.pk3", 129, 5),        # MAGIKARP, trade fodder
                                 ("PARTY2.pk3", 113, 26)):      # CHANSEY lv26: the offered slot
        path = os.path.join(directory, name)
        with open(path, "wb") as handle:
            handle.write(mevent_pokemon.build_party_mon(
                species, level, nickname="FODDER",
                language=mevent_pokemon.LANGUAGE_FRENCH).party_bytes())
        paths.append(path)
    return tuple(paths)


def _advertised_activity(union_room, union_room_activity=None):
    """Drive the real HostApplication._build_components and read the activity it puts on the air."""
    seen = {}

    class FakeTransport:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    run = config.TradeRunConfig(
        DEFAULT_TRAINER,
        config.TradePlan(party_paths=_party_files(), trade_slot=1,
                         offered_slots=(1,), trust_pia=True),
        config.LdnConfig(phy="phy7", keys_path=__file__),
        config.HostOptions(union_room=union_room,
                           union_room_activity=union_room_activity))
    app = HostApplication(run, transport_factory=FakeTransport, log=lambda *_a: None,
                          injector_factory=lambda **unused: None)
    app._build_components()
    return _search_word(seen["app_data"]) & beacon.SEARCH_ACTIVITY_MASK


def test_host_app_advertises_activity_search_only_with_the_option():
    assert _advertised_activity(True) == beacon.IN_UNION_ROOM
    assert _advertised_activity(False) == beacon.ACTIVITY_TRADE


def test_host_app_advertises_the_chosen_in_room_activity():
    activity = beacon.IN_UNION_ROOM | beacon.ACTIVITY_TRADE
    assert _advertised_activity(True, activity) == activity


def _advertisements(union_room):
    """Drive the real HostApplication._build_components; return (pre-join app_data, the app_data
    handed to HostPeerProtocol for the post-join session update)."""
    from pokeldn.frlg.link import host_app as host_app_module
    seen = {}
    peer_args = []

    class FakeTransport:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    class FakePeer:
        def __init__(self, *args, **kwargs):
            peer_args.extend(args)

    run = config.TradeRunConfig(
        DEFAULT_TRAINER,
        config.TradePlan(party_paths=_party_files(), trade_slot=1,
                         offered_slots=(1,), trust_pia=True),
        config.LdnConfig(phy="phy7", keys_path=__file__),
        config.HostOptions(union_room=union_room))
    original = host_app_module.HostPeerProtocol
    host_app_module.HostPeerProtocol = FakePeer
    try:
        app = HostApplication(run, transport_factory=FakeTransport, log=lambda *_a: None,
                              injector_factory=lambda **unused: None)
        app._build_components()
    finally:
        host_app_module.HostPeerProtocol = original
    return seen["app_data"], peer_args[3]


def test_post_join_advertisement_sets_started_activity_by_default():
    inactive, active = _advertisements(True)
    assert active != inactive
    assert _search_word(inactive) & beacon.SEARCH_STARTED_ACTIVITY == 0
    assert _search_word(active) & beacon.SEARCH_STARTED_ACTIVITY



# One console's record before and after registering Chansey lv26 asking for FEU. Byte 10 is its
# re-rolled RFU session id.
CONSOLE_BASELINE = bytes.fromhex("65dfc1cfccd0bbc8ff00805d00000000401c030100000000")
CONSOLE_REGISTERED = bytes.fromhex("65dfc1cfccd0bbc8ff00815d00000000401c2b3500007100")


def test_trade_board_registration_reproduces_the_console_diff():
    ours = bytearray(beacon.set_trade_board(CONSOLE_BASELINE, 113, 26, beacon.TYPE_NAMES["fire"]))
    ours[10] = CONSOLE_REGISTERED[10]
    assert bytes(ours) == CONSOLE_REGISTERED


def test_trade_board_leaves_the_unknown_bits_alone():
    rec = beacon.set_trade_board(CONSOLE_BASELINE, 300, 100, 3)
    assert rec[18] & 0x03 == CONSOLE_BASELINE[18] & 0x03
    assert rec[19] & 0x01 == CONSOLE_BASELINE[19] & 0x01
    assert int.from_bytes(rec[22:24], "little") == 300 and rec[19] >> 1 == 100 and rec[18] >> 2 == 3


def _record(app_data):
    return beacon.b85_decode(bytes(app_data)[beacon.PIA_HDR:])[:beacon.RECORD_SIZE]


def test_host_app_registers_the_offered_mon_on_the_board():
    """The offered slot (1) is the CHANSEY lv26 that _party_files builds."""
    from pokeldn.frlg.link import host_app as host_app_module
    seen = {}

    class FakeTransport:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    class FakePeer:
        def __init__(self, *args, **kwargs):
            pass

    run = config.TradeRunConfig(
        DEFAULT_TRAINER,
        config.TradePlan(party_paths=_party_files(), trade_slot=1,
                         offered_slots=(1,), trust_pia=True),
        config.LdnConfig(phy="phy7", keys_path=__file__),
        config.HostOptions(union_room=True, union_room_board_type=beacon.TYPE_NAMES["normal"]))
    original = host_app_module.HostPeerProtocol
    host_app_module.HostPeerProtocol = FakePeer
    try:
        app = HostApplication(run, transport_factory=FakeTransport, log=lambda *_a: None,
                              injector_factory=lambda **unused: None)
        app._build_components()
    finally:
        host_app_module.HostPeerProtocol = original
    rec = _record(seen["app_data"])
    assert int.from_bytes(rec[22:24], "little") == 113
    assert rec[19] >> 1 == 26 and rec[18] >> 2 == 0
    assert _search_word(seen["app_data"]) & beacon.SEARCH_ACTIVITY_MASK == beacon.IN_UNION_ROOM


def test_no_board_type_means_no_registration():
    inactive, _ = _advertisements(True)
    rec = _record(inactive)
    assert rec[22:24] == b"\x00\x00" and rec[19] >> 1 == 0
