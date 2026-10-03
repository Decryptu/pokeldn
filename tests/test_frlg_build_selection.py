"""The Mystery Gift host picks the cartridge build from the game code the console sends
[mystery_gift.c:369]."""

import pytest

import frlg_mg_host
from pokeldn import config as configmod
from pokeldn.frlg.gift import host_mystery_gift, mg_client, mg_server
from pokeldn.frlg.gift import mystery_gift as mg
from pokeldn.frlg.link import linkplayer
from pokeldn.frlg.rom import buffer_script as bs, builds
from pokeldn.gba import rfu

INSTALL_NOENCOUNTER = ("--buffer-script", bs.INSTALL_RESIDENT, "--resident", "noencounter",
                       "--write-unsafe")
BEFORE_ANYTHING_BUILD_DEPENDENT = [("in", mg.MG_LINKID_CLIENT_SCRIPT), ("out", mg.MG_LINKID_GAME_DATA)]


def _run_config(*argv):
    parser = frlg_mg_host.build_parser()
    return frlg_mg_host.build_run_config(parser, parser.parse_args(list(argv)))


def _session(config, *, game_code, version):
    plan = configmod.plan_builds(config.payload, config.console_build, config.console_version)
    host = host_mystery_gift.HostMysteryGiftEngine(
        distribution=plan.distribution, per_build=plan.per_build,
        link_player=linkplayer.LinkPlayer(name="EMU", version=linkplayer.VERSION_FIRE_RED),
        timing=host_mystery_gift.MysteryGiftTiming(client_ready_idle_frames=10))
    client = mg_client.MysteryGiftClientEngine(
        linkplayer.LinkPlayer(name="POKELDN", version=linkplayer.VERSION_FIRE_RED),
        version=version, game_code=game_code)
    return host, client


def _drive(host, client, ticks=6000):
    slot, child = rfu.SlotBuilder(), rfu.idle_slot()
    for t in range(ticks):
        table = rfu.pack_recv_cmds([rfu.serialize(host.tick()), child])
        record = {"type": "T", "ts": t, "slot_len": 73, "llsf_state": 4,
                  "slots": [(m, table[m * 14:(m + 1) * 14]) for m in range(2)], "payload": table}
        record["positional"] = record["slots"]
        client.feed_in_frame(record)
        child = slot.build(client.tick() or [0] * 7)
        host.feed_child_slot(child)
        if host.disconnect_requested:
            host.mark_disconnect_sent()
            return
    raise AssertionError(f"flow did not finish: host={host.state} client={client.status()}")


def _messages(client):
    return [(direction, ident) for _t, direction, ident, _s, _p in client.messages]


def _install(build):
    return configmod.BufferScriptPayload(
        script=bs.INSTALL_RESIDENT, resident_name="noencounter",
        write_unsafe=True).build_code(build)


def test_an_english_firered_console_is_sent_the_english_bytes():
    host, client = _session(_run_config(*INSTALL_NOENCOUNTER), game_code=b"BPRE",
                            version="firered")
    _drive(host, client)
    english = _install(builds.BPRE)
    assert english != _install(builds.BPRF)
    assert host.server.build is builds.BPRE
    [received] = client.buffer_scripts           # the whole receive buffer, payload first
    assert received[:len(english)] == english
    assert client.error is None


def test_an_unknown_game_code_is_refused_with_nothing_build_dependent_sent():
    host, client = _session(_run_config(*INSTALL_NOENCOUNTER), game_code=b"BPRD",
                            version="firered")
    with pytest.raises(mg_server.MysteryGiftServerError, match="'BPRD' AND NOTHING WAS SENT"):
        _drive(host, client)
    assert host.server.build_refused == "BPRD"
    assert client.buffer_scripts == []
    assert _messages(client) == BEFORE_ANYTHING_BUILD_DEPENDENT


def test_version_firered_refuses_a_leafgreen_console():
    config = _run_config(*INSTALL_NOENCOUNTER, "--version", "firered")
    assert config.console_version == "firered"
    host, client = _session(config, game_code=b"BPGE", version="leafgreen")
    with pytest.raises(mg_server.MysteryGiftServerError,
                       match="'BPGE' AND NOTHING WAS SENT: --version firered"):
        _drive(host, client)
    assert client.buffer_scripts == []
    assert _messages(client) == BEFORE_ANYTHING_BUILD_DEPENDENT
