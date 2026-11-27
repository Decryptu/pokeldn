"""bin/swsh_connect.py --ip-join against bin/swsh_host.py --ip-host on the loopback aliases an
emulated pair uses: the ldn_mitm scan and Connect, then the whole trade over plain UDP."""
import json
import os
import socket
import threading
from pathlib import Path

import pytest

HOST_IP, JOIN_IP = "127.0.0.2", "127.0.0.3"


def _bindable(ip, port):
    for kind in (socket.SOCK_DGRAM, socket.SOCK_STREAM):
        with socket.socket(socket.AF_INET, kind) as s:
            try:
                s.bind((ip, port))
            except OSError:
                return False
    return True


def _loopback(tmp_path, monkeypatch):
    """-> a prod.keys file of random keys, once the aliases are bindable and nothing is mocked out."""
    from pokeldn.swsh import PIA_PORT
    from pokeldn.ldn import ldn_mitm
    from pokeldn import gen8, pokemon as pokemon_service
    if not all(_bindable(ip, port) for ip in (HOST_IP, JOIN_IP)
               for port in (PIA_PORT, ldn_mitm.PORT)):
        pytest.skip("needs the lo0 aliases 127.0.0.2 and 127.0.0.3, with ports 12345 and 11452 free")
    monkeypatch.delenv("POKELDN_RADIO", raising=False)
    monkeypatch.setattr(pokemon_service, "prepare_file", lambda game, path, **kw: path)
    monkeypatch.setattr(pokemon_service, "prepare", lambda game, raw, **kw: gen8.decrypt(raw))
    keys_file = tmp_path / "prod.keys"
    keys_file.write_text("".join(f"{k} = {os.urandom(16).hex()}\n"
                                 for k in ("aes_kek_generation_source", "aes_key_generation_source",
                                           "master_key_00")))
    return keys_file


@pytest.mark.parametrize("owns", ["", "receiver", "fixed"])
def test_the_joiner_trades_with_an_ldn_mitm_host_on_loopback(tmp_path, monkeypatch, capsys, owns):
    """Two trades on one seat. The joiner is keyed only from the advertise data the scan and the
    SyncNetwork carried, and seats with the MAC ldn_mitm derives from its address. With --receiver-owns
    its offers go under the trainer the host's live snapshot names (pokeldn.for_receiver); a record PKHeX
    refuses another trainer, `fixed`, goes as given."""
    keys_file = _loopback(tmp_path, monkeypatch)
    import swsh_connect
    import swsh_host
    from test_swsh_trade_payload import a_payload
    from pokeldn import gen8, pokemon as pokemon_service
    from pokeldn.swsh import pokemon

    def prepare(game, raw, *, fresh=False, fields=None):
        if not fields:
            return gen8.decrypt(raw)
        if owns == "fixed" and gen8.read(gen8.load(raw))["species"] == 97:
            raise pokemon_service.BuilderError("it is legal only with its own trainer")
        trainer = fields["trainer"]
        return gen8.encrypt(gen8.write(gen8.load(raw), ot_name=trainer["ot"], trainer_id=trainer["tid"],
                                       secret_id=trainer["sid"], ot_gender=trainer["gender"]))
    monkeypatch.setattr(pokemon_service, "prepare", prepare)

    party = a_payload(count=4)
    (tmp_path / "snapshot.bin").write_bytes(party)
    for slot in range(4):
        (tmp_path / f"offer{slot}.pk8").write_bytes(
            party[slot * gen8.SIZE_PARTY:(slot + 1) * gen8.SIZE_PARTY])

    result = {}
    host = threading.Thread(target=lambda: result.setdefault("host", swsh_host.main(
        ["--ip-host", "--our-ip", HOST_IP, "--keys", str(keys_file), "--seconds", "50",
         "--accept-first", "--lead", "0.1", "--snapshot", str(tmp_path / "snapshot.bin"),
         "--received", str(tmp_path / "host.pk8"),
         "--trainer-name", "LiveSword", "--trainer-tid", "48765", "--trainer-sid", "56789",
         "--offer-file", str(tmp_path / "offer0.pk8"),
         "--offer-file", str(tmp_path / "offer1.pk8")])), daemon=True)
    join = threading.Thread(target=lambda: result.setdefault("join", swsh_connect.main(
        ["--ip-join", "--host-ip", HOST_IP, "--our-ip", JOIN_IP, "--preset", "trade",
         "--dwell", "0.1", "--scans", "30", "--listen-first", "0.4", "--quiet-for", "0.2",
         "--ack-seconds", "1", "--period", "0.03", "--request-gap", "0.05", "--join-gap", "0.05",
         "--send-after", "0.1", "--send-period", "0.03", "--box-period", "0.03",
         "--rpc-period", "0.03", "--hold-after-trade", "0.1", "--hold", "30",
         "--save-offered", str(tmp_path / "join.pk8"), "--capture", str(tmp_path / "join.jsonl"),
         "--offer-file", str(tmp_path / "offer2.pk8"),
         "--offer-file", str(tmp_path / "offer3.pk8"),
         *(["--receiver-owns", "1", "--receiver-owns", "2"] if owns else [])])), daemon=True)
    join.start()                         # before the host: the joiner rescans until it answers
    host.start()
    join.join(120)
    host.join(120)
    assert result == {"host": 0, "join": 0}

    def species(name):
        return pokemon.read(pokemon.encrypt(gen8.load((tmp_path / name).read_bytes())))["species"]
    assert [species(n) for n in ("join.pk8", "join-2.pk8")] == [94, 95]
    assert [species(n) for n in ("host.pk8", "host-2.pk8")] == [96, 97]
    received = [gen8.read(gen8.load((tmp_path / n).read_bytes())) for n in ("host.pk8", "host-2.pk8")]
    given = gen8.read(gen8.load((tmp_path / "offer3.pk8").read_bytes()))
    owners = [(f["ot_name"], f["trainer_id"], f["secret_id"]) for f in received]
    live, kept = ("LiveSword", 48765, 56789), (given["ot_name"], given["trainer_id"], given["secret_id"])
    assert owners == {"": [owners[0], kept], "receiver": [live, live], "fixed": [live, kept]}[owns]
    assert owns == "" or owners[0] == live
    out = capsys.readouterr().out
    assert ("Offer 2 could not be made the receiving player's own" in out) == (owns == "fixed")


@pytest.mark.parametrize("scene", [50000, 50480])   # 50480: a player's retail lobby, docs/swsh_raid.md
def test_the_apps_dynamax_adventure_guest_seats_in_our_max_lair_host(tmp_path, monkeypatch, capsys,
                                                                      scene):
    """The app's Dynamax Adventure (Join) arguments against swsh_host.py --lair-legendary: the guest
    takes index 1, hears the legendary and leaves with the host's handover."""
    keys_file = _loopback(tmp_path, monkeypatch)
    import swsh_connect
    import swsh_host
    from test_swsh_trade_payload import a_payload
    from pokeldn.app.catalog import GAMES
    from pokeldn.app.command import build
    from pokeldn.app.settings import Settings

    (tmp_path / "snapshot.bin").write_bytes(a_payload(count=2))
    tool = next(t for game in GAMES for t in game.tools if t.key == "swsh-lair-raid-join")
    result = {}
    host = threading.Thread(target=lambda: result.setdefault("host", swsh_host.main(
        ["--ip-host", "--our-ip", HOST_IP, "--keys", str(keys_file), "--seconds", "60",
         "--raid-ready", "0.1", "--lair-leave", "0.1",
         "--lair-legendary", "144", "--lair-seed", "173502832", "--lair-scene", str(scene)])), daemon=True)
    join = threading.Thread(target=lambda: result.setdefault("join", swsh_connect.main(
        build(tool, {}, {}, Settings())
        + ["--keys", str(keys_file), "--ip-join", "--host-ip", HOST_IP, "--our-ip", JOIN_IP,
           "--dwell", "0.1", "--scans", "40", "--listen-first", "0.4", "--quiet-for", "0.2",
           "--ack-seconds", "1", "--period", "0.03", "--request-gap", "0.05", "--join-gap", "0.05",
           "--hold", "40",
           "--send-snapshot", str(tmp_path / "snapshot.bin")])), daemon=True)
    join.start()
    host.start()
    join.join(150)
    host.join(150)
    out = capsys.readouterr().out
    assert result == {"host": 0, "join": 0}
    assert "[lair] the legendary is species 144" in out
    assert "we are index 1" in out
    assert f"scene={scene} app_version" in out


def test_the_apps_max_raid_guest_brings_its_pokemon_into_our_den_raid(tmp_path, monkeypatch, capsys):
    """The app's Max Raid (Join) arguments against swsh_host.py --raid-boss: the guest selects the
    chosen Pokemon, readies, and both sides start the battle."""
    keys_file = _loopback(tmp_path, monkeypatch)
    import swsh_connect
    import swsh_host
    from test_swsh_trade_payload import a_payload
    from pokeldn import gen8
    from pokeldn.app.catalog import GAMES
    from pokeldn.app.command import build
    from pokeldn.app.settings import Settings

    party = a_payload(count=3)
    (tmp_path / "snapshot.bin").write_bytes(party)
    for slot in (1, 2):
        (tmp_path / f"m{slot}.pk8").write_bytes(party[slot * gen8.SIZE_PARTY:(slot + 1) * gen8.SIZE_PARTY])
    adverts = json.loads((Path(__file__).parent / "data" / "swsh_raid_adverts.json").read_text())
    (tmp_path / "boss.pk8").write_bytes(bytes.fromhex(adverts["boss_hoothoot"]))
    tool = next(t for game in GAMES for t in game.tools if t.key == "swsh-raid-join")
    real_raid_host = swsh_host.raid_host.RaidHost

    class _FinishOnBattle(real_raid_host):
        def __init__(self, *a, on_battle=None, **kw):
            def done(lobby):
                if on_battle:
                    on_battle(lobby)
                lobby.finished = True
            super().__init__(*a, on_battle=done, **kw)
    monkeypatch.setattr(swsh_host.raid_host, "RaidHost", _FinishOnBattle)
    result = {}
    host = threading.Thread(target=lambda: result.setdefault("host", swsh_host.main(
        ["--ip-host", "--our-ip", HOST_IP, "--keys", str(keys_file), "--seconds", "40",
         "--raid-ready", "0.1",
         "--raid-boss", str(tmp_path / "boss.pk8"), "--offer-file", str(tmp_path / "m1.pk8")])), daemon=True)
    join = threading.Thread(target=lambda: result.setdefault("join", swsh_connect.main(
        build(tool, {"--offer-file": {"file": str(tmp_path / "m2.pk8")}, "--raid-move": "2"}, {}, Settings())
        + ["--keys", str(keys_file), "--ip-join", "--host-ip", HOST_IP, "--our-ip", JOIN_IP,
           "--dwell", "0.1", "--scans", "40", "--listen-first", "0.4", "--quiet-for", "0.2",
           "--ack-seconds", "1", "--period", "0.03", "--request-gap", "0.05", "--join-gap", "0.05",
           "--raid-ready", "0.1", "--hold", "30",
           "--send-snapshot", str(tmp_path / "snapshot.bin")])), daemon=True)
    join.start()
    host.start()
    join.join(150)
    host.join(150)
    out = capsys.readouterr().out
    assert result == {"host": 0, "join": 0}
    # a_payload's slot 2 carries encryption constant 0x39C5F2CE.
    assert "[raid] <- the guest selects EC cef2c539" in out
    assert "[raid] 127.0.0.3: both sides started" in out
