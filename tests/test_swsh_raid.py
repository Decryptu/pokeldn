"""A Max Raid guest against the bytes an emulated Shield guest sent in a won raid (docs/swsh_raid.md)."""
import json
from pathlib import Path

from pokeldn.swsh import raid, raid_battle

DATA = json.loads((Path(__file__).parent / "data" / "swsh_raid_emulated.json").read_text())


def test_lobby_messages_are_the_emulated_guests():
    by_field = {raid.parse(bytes.fromhex(h))[0]: bytes.fromhex(h) for h in DATA["lobby"]}
    pk8 = raid.parse(by_field[raid.SELECT_POKEMON])[1][8:]
    assert by_field[raid.PLAYER_INFO] == raid.player_info("Guest")
    assert by_field[raid.BATTLE_READY] == raid.battle_ready()
    assert by_field[raid.SELECT_POKEMON] == raid.select_pokemon(pk8)


def _shape(port, payload):
    fw = raid_battle.parse_framework(payload)
    # The framework clock is the station's own; compare everything else.
    return (port, "fw", fw["base"], fw["station"], fw["body"]) if fw else (port, payload)


def test_guest_answers_the_recorded_host_battle():
    guest = raid_battle.Guest(0x7F00030000020000, slot=1)
    ours = []
    for m in DATA["battle"]:
        if m["dir"] == "rx":
            ours += [_shape(p, x) for p, x in guest.receive(m["port"], bytes.fromhex(m["payload"]))]
    theirs = [_shape(m["port"], bytes.fromhex(m["payload"])) for m in DATA["battle"] if m["dir"] == "tx"]
    assert ours == theirs


def test_action_names_the_move_as_the_emulated_guest_did():
    # Entry 2 of four recorded actions of an emulated Drizzile guest, one per move.
    recorded = {(1, 8): "c128000000000000", (20, 8): "c188020000000000",
                (45, 2): "c1a2050000000000", (55, 8): "c1e8060000000000"}
    for (move, target), entry in recorded.items():
        built = raid_battle.action(move, target)
        assert built[8:16].hex() == entry
        assert built[:8] + built[16:] == raid_battle.ACTION[:8] + raid_battle.ACTION[16:]


def test_host_start_messages_are_the_emulated_hosts():
    got = {raid.parse(bytes.fromhex(h))[0]: bytes.fromhex(h) for h in DATA["host_start"]}
    stations = raid.parse(got[raid.BATTLE_START])[1]
    boss = raid.parse(got[raid.BOSS_POKEMON])[1][len(raid.BOSS_HEAD):]
    seed = raid.parse(got[raid.BATTLE_SEED])[1][:8]
    assert got[raid.BATTLE_START] == raid.battle_start([0x7F00020000020000, 0x7F00030000020000])
    assert stations[16:] == bytes(16)
    assert got[raid.BOSS_POKEMON] == raid.boss_pokemon(boss)
    # The emulated den's item ids and counts, as the guest listed them.
    assert got[raid.REWARDS] == raid.rewards([(1124, 5), (1125, 1), (1129, 1), (50, 1), (1149, 1)])
    assert got[raid.BATTLE_SEED] == raid.battle_seed(int.from_bytes(seed, "little"))


def test_lobby_host_follows_the_emulated_hosts_order():
    """The fields the emulated host sent after the snapshot, in order, time limits dropped, against
    our host fed the emulated guest's lobby messages."""
    from pokeldn.swsh import raid_host
    sent = []
    lobby = [bytes.fromhex(h) for h in DATA["lobby"]]
    guest_pk8 = raid.parse(lobby[2])[1][8:]
    boss = raid.parse(bytes.fromhex(DATA["host_start"][1]))[1][len(raid.BOSS_HEAD):]
    host = raid_host.RaidHost(0x7F00020000020000, 0x7F00030000020000, None, guest_pk8, boss,
                              lambda pr, port, p, z: sent.append((raid.parse(p)[0], z)),
                              None, None, ready_after=1.0, log=lambda *a: None)
    host.stage = "lobby"
    for p in lobby:
        host.on_data(0x80, 0, p)
    t = 100.0
    for _ in range(4):
        host.tick(t); t += 0.5
    host.on_data(0x80, 0, raid.battle_ready(True))
    host.tick(t)
    host.on_data(0x80, 0, raid.select_pokemon(guest_pk8))
    host.on_data(0x80, 0, raid.battle_ready(True, started=True))
    host.tick(t + 0.1)
    assert host.stage == "battle"
    fields = [f for f in sent if f[0] != raid.TIME_LIMIT]
    assert fields == [(2, True), (3, False), (4, False), (3, False),
                      (5, True), (4, False), (6, False), (7, True), (8, False), (3, False)]
