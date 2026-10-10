"""bin/swsh_connect.py --ip-join against bin/swsh_host.py --ip-host on the loopback aliases an
emulated pair uses: the ldn_mitm scan and Connect, then the whole trade over plain UDP."""
import os
import socket
import threading

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


def test_the_joiner_trades_with_an_ldn_mitm_host_on_loopback(tmp_path, monkeypatch):
    """Two trades on one seat. The joiner is keyed only from the advertise data the scan and the
    SyncNetwork carried, and seats with the MAC ldn_mitm derives from its address."""
    from pokeldn.swsh import PIA_PORT
    from pokeldn.ldn import ldn_mitm
    if not all(_bindable(ip, port) for ip in (HOST_IP, JOIN_IP)
               for port in (PIA_PORT, ldn_mitm.PORT)):
        pytest.skip("needs the lo0 aliases 127.0.0.2 and 127.0.0.3, with ports 12345 and 11452 free")

    import swsh_connect
    import swsh_host
    from test_swsh_trade_payload import a_payload
    from pokeldn import gen8, pokemon as pokemon_service
    from pokeldn.swsh import pokemon

    monkeypatch.delenv("POKELDN_RADIO", raising=False)
    monkeypatch.setattr(pokemon_service, "prepare_file", lambda game, path, **kw: path)
    monkeypatch.setattr(pokemon_service, "prepare", lambda game, raw, **kw: gen8.decrypt(raw))
    keys_file = tmp_path / "prod.keys"
    keys_file.write_text("".join(f"{k} = {os.urandom(16).hex()}\n"
                                 for k in ("aes_kek_generation_source", "aes_key_generation_source",
                                           "master_key_00")))
    party = a_payload(count=4)
    (tmp_path / "snapshot.bin").write_bytes(party)
    for slot in range(4):
        (tmp_path / f"offer{slot}.pk8").write_bytes(
            party[slot * gen8.SIZE_PARTY:(slot + 1) * gen8.SIZE_PARTY])

    result = {}
    host = threading.Thread(target=lambda: result.setdefault("host", swsh_host.main(
        ["--ip-host", "--our-ip", HOST_IP, "--keys", str(keys_file), "--seconds", "50",
         "--accept-first", "--lead", "3", "--snapshot", str(tmp_path / "snapshot.bin"),
         "--received", str(tmp_path / "host.pk8"),
         "--offer-file", str(tmp_path / "offer0.pk8"),
         "--offer-file", str(tmp_path / "offer1.pk8")])), daemon=True)
    join = threading.Thread(target=lambda: result.setdefault("join", swsh_connect.main(
        ["--ip-join", "--host-ip", HOST_IP, "--our-ip", JOIN_IP, "--preset", "trade",
         "--dwell", "0.5", "--scans", "20", "--listen-first", "2", "--hold", "20",
         "--save-offered", str(tmp_path / "join.pk8"), "--capture", str(tmp_path / "join.jsonl"),
         "--offer-file", str(tmp_path / "offer2.pk8"),
         "--offer-file", str(tmp_path / "offer3.pk8")])), daemon=True)
    join.start()                         # before the host: the joiner rescans until it answers
    host.start()
    join.join(120)
    host.join(120)
    assert result == {"host": 0, "join": 0}

    def species(name):
        return pokemon.read(pokemon.encrypt(gen8.load((tmp_path / name).read_bytes())))["species"]
    assert [species(n) for n in ("join.pk8", "join-2.pk8")] == [94, 95]
    assert [species(n) for n in ("host.pk8", "host-2.pk8")] == [96, 97]
