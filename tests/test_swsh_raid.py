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
