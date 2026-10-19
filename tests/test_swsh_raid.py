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


def test_master_steps_the_barrier_once_the_console_mirrors_it():
    console, ours = 0x7F00030000020000, 0x7F00020000020000
    m = raid_battle.Master(ours, [console], log=lambda *a: None)
    m.receive(0, raid_battle.sync(raid_battle.PING_REPLY), console)
    out = m.receive(1, raid_battle.framework(raid_battle.BATTLE, console, 909, bytes.fromhex("00000100")),
                    console)
    bodies = [raid_battle.parse_framework(p)["body"].hex() for _, p, _ in out]
    assert bodies == ["0100", "01000100"]


def test_den_advert_points_at_the_bosss_den_slot_as_the_emulated_host_did():
    """The first raid's advertisement rewritten for the second raid's boss carries the second
    advertisement's boss block and den table and slot (Hoothoot, Shield table 30, slot 1)."""
    ads = json.loads((Path(__file__).parent / "data" / "swsh_raid_adverts.json").read_text())
    first, second = bytes.fromhex(ads["advert_pidove"]), bytes.fromhex(ads["advert_hoothoot"])
    built = raid.den_advert(first, bytes.fromhex(ads["boss_hoothoot"]))
    assert built[0xB0:0xB8] == second[0xB0:0xB8]
    assert built[0xD4:0xDC] == second[0xD4:0xDC]
    assert built[0xDE:0xE2] == second[0xDE:0xE2]
    from pokeldn.swsh import beacon
    assert int.from_bytes(built[0x18:0x1A], "little") == beacon.crc16(built[0x1A:0x180])


def test_den_advert_zeroes_the_den_record_for_a_boss_no_den_holds():
    ads = json.loads((Path(__file__).parent / "data" / "swsh_raid_adverts.json").read_text())
    from pokeldn import gen8
    from pokeldn.swsh import pokemon
    plain = bytearray(gen8.decrypt(bytes.fromhex(ads["boss_hoothoot"])))
    plain[gen8.OFF_SPECIES:gen8.OFF_SPECIES + 2] = (151).to_bytes(2, "little")   # Mew: no den
    built = raid.den_advert(bytes.fromhex(ads["advert_pidove"]), pokemon.encrypt(bytes(plain)))
    assert built[0xD4:0xDC] == bytes(8)
    assert int.from_bytes(built[0xB0:0xB2], "little") & 0x3FF == 151


def test_boss_record_keeps_the_den_bosss_dynamax_type():
    """Both recorded den bosses carry Dynamax type 1; a traded record's 0 made a retail guest leave."""
    from pokeldn import gen8
    from pokeldn.swsh import pokemon
    ads = json.loads((Path(__file__).parent / "data" / "swsh_raid_adverts.json").read_text())
    den_boss = gen8.decrypt(bytes.fromhex(ads["boss_hoothoot"]))
    traded = bytearray(den_boss)
    traded[gen8.OFF_DYNAMAX_TYPE:gen8.OFF_DYNAMAX_TYPE + 2] = bytes(2)
    traded[gen8.OFF_SPECIES:gen8.OFF_SPECIES + 2] = (831).to_bytes(2, "little")
    built = gen8.decrypt(raid.boss_record(pokemon.encrypt(bytes(traded))))
    assert built[gen8.OFF_DYNAMAX_TYPE:] == den_boss[gen8.OFF_DYNAMAX_TYPE:] == b"\x01\x00"
    assert gen8.read(built)["species"] == 831


def test_an_emulated_den_hosts_rewards_fit_its_den_slot():
    """The Rewards an emulated Shield den host sent all pass the guest's check against the den slot
    and rank its advertisement names (0x01032570), and a pair from outside the tables does not."""
    import struct
    ads = json.loads((Path(__file__).parent / "data" / "swsh_raid_adverts.json").read_text())
    row, rank = raid.den_of(bytes.fromhex(ads["advert_pidove"]))
    assert row[:4] == [38, 2, 519, 0] and rank == 0
    sent = raid.parse(bytes.fromhex(DATA["host_start"][2]))[1]
    pairs = [p for p in struct.iter_unpack("<II", sent) if p[0]]
    kept, refused = raid.fitting_rewards(row, rank, pairs + [(1, 1)])
    assert kept == pairs and refused == [(1, 1)]


def test_two_consoles_start_together_and_both_must_mirror_the_barrier():
    """Two emulated Shields in one hosted lobby: the start waits for both, BattleStart lists both
    consoles then us, object k is console k's record and ours is last, and the framework barrier
    steps only once both consoles mirror it. Each failure was a stall or a split battle."""
    from pokeldn.swsh import raid_host
    ours, a, b = 0x7F00020000020000, 0x7F00030000020000, 0x7F00040000020000
    lobby = [bytes.fromhex(h) for h in DATA["lobby"]]
    pk8 = raid.parse(lobby[2])[1][8:]
    boss = raid.parse(bytes.fromhex(DATA["host_start"][1]))[1][len(raid.BOSS_HEAD):]
    party = raid_host.RaidParty(ours, console_serves=True, log=lambda *x: None)
    sent = {a: [], b: []}
    hosts = {}
    for console in (a, b):
        hosts[console] = raid_host.RaidHost(
            ours, console, None, pk8, boss,
            lambda pr, port, p, z, c=console: sent[c].append((pr, port, p)), None, None,
            ready_after=0.0, log=lambda *x: None, console_serves=True, party=party)
        hosts[console].stage = "lobby"
    hosts[a].on_data(0x80, 0, raid.battle_ready(True))
    for h in hosts.values():
        h.tick(100.0)
    assert all(h.stage == "lobby" for h in hosts.values())
    hosts[b].on_data(0x80, 0, raid.battle_ready(True))
    for t in (101.0, 101.1):
        for h in hosts.values():
            h.tick(t)
    for console in (a, b):
        start = [raid.parse(p)[1] for pr, _, p in sent[console]
                 if pr == 0x80 and raid.parse(p) and raid.parse(p)[0] == raid.BATTLE_START]
        assert start == [raid.parse(raid.battle_start([a, b, ours]))[1]]
    for console in (a, b):
        hosts[console].on_data(0x80, 0, raid.battle_ready(True, started=True))
        hosts[console].tick(102.0)
    m = party.battle
    assert m is not None and m.consoles == [a, b] and m.slot == 2
    out = []
    for console in (a, b):
        out += m.receive(0, raid_battle.sync(raid_battle.PING_REPLY), console)
    records = {raid_battle.parse_framework(p)["base"]: raid_battle.parse_framework(p)["body"]
               for _, p, _ in out if raid_battle.parse_framework(p)
               and raid_battle.parse_framework(p)["station"] is None}
    assert records[0] == raid_battle.server_record(a, 0)
    assert records[1] == raid_battle.server_record(b, 1)
    assert records[2] == raid_battle.server_record(ours, 2)
    step = raid_battle.framework(raid_battle.BATTLE, a, 909, bytes.fromhex("00000100"))
    assert m.receive(1, step, a) == []
    out = m.receive(1, raid_battle.framework(raid_battle.BATTLE, b, 909, bytes.fromhex("00000100")), b)
    assert [raid_battle.parse_framework(p)["body"].hex() for _, p, _ in out] == ["0100", "01000100"]
