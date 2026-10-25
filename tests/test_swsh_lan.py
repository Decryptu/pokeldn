"""Sword/Shield in LAN mode: the browse exchange pinned to an emulated Shield's own bytes, then our
LAN joiner trading with our LAN host on the loopback aliases (docs/swsh_session.md, LAN mode)."""
import json
import socket
import struct
import threading
import time
from pathlib import Path

import pytest

from pokeldn.ldn import pia4, pia_lan
from pokeldn.swsh import GAME_KEY

VECTORS = json.loads((Path(__file__).parent / "data" / "swsh_lan_console.json").read_text())
CONSOLE_IP, BROADCAST = "192.168.1.31", "192.168.1.255"
HOST_IP, JOIN_IP = "127.0.0.2", "127.0.0.3"


def test_our_reply_to_a_challenge_is_the_consoles_byte_for_byte():
    """The console keys its session with the first valid request: its challenge key, then ours.
    Our reply to the same challenge under the same key param is the console's, tag included."""
    v = VECTORS["challenge"]
    request = pia_lan.parse_browse_request(bytes.fromhex(v["request"]))
    reply = pia_lan.parse_browse_reply(bytes.fromhex(v["reply"]))
    theirs = pia_lan.parse_challenge(reply["challenge_reply"])
    plain = bytes.fromhex(v["challenge_plain"])
    assert pia_lan.open_challenge(GAME_KEY, BROADCAST, request["challenge"]) == plain
    assert reply["key_param"] == theirs["key"] + pia_lan.parse_challenge(request["challenge"])["key"]
    assert pia_lan.check_response(GAME_KEY, BROADCAST, reply["challenge_reply"], plain,
                                  reply["key_param"])
    ours = pia_lan.build_response(GAME_KEY, BROADCAST, theirs["counter"], plain, reply["key_param"],
                                  challenge_key=theirs["key"])
    assert ours == reply["challenge_reply"]
    assert not pia_lan.check_response(GAME_KEY, "192.168.0.255", reply["challenge_reply"], plain,
                                      reply["key_param"])


def test_our_session_info_is_the_consoles():
    """Every field the builder writes, read off the console's reply and written back."""
    reply = bytes.fromhex(VECTORS["challenge"]["reply"])
    got = pia_lan.parse_browse_reply(reply)
    assert (got["game_mode"], got["players"], got["max_players"]) == (60001, 1, 2)
    assert got["host_ip"] == CONSOLE_IP and got["stations"][0]["name"] == "RyuPlayer"
    # A console's ids are its address and port, its network id the service variable id.
    assert got["host_constant"] == pia_lan.constant_id(CONSOLE_IP, got["host_port"])
    assert got["host_service_variable"] == got["network_id"] == pia_lan.service_variable_id(
        CONSOLE_IP, got["host_port"])
    info = pia_lan.build_session_info(
        got["game_mode"], got["network_id"], got["host_ip"], got["host_port"],
        got["host_constant"], got["host_variable"], got["host_service_variable"], got["key_param"],
        [(s["role"], s["name"], s["constant_id"]) for s in got["stations"]],
        max_players=got["max_players"], system_version=got["system_version"],
        application_version=got["application_version"])
    assert info == reply[5:5 + pia_lan.SESSION_INFO_SIZE]


def test_the_session_key_and_the_iv_open_the_consoles_host_message():
    v = VECTORS["host_message"]
    reply = pia_lan.parse_browse_reply(bytes.fromhex(v["reply"]))
    packet = bytes.fromhex(v["packet"])
    h = pia4.PiaHeader4.parse(packet)
    key = pia_lan.session_key(GAME_KEY, reply["key_param"])
    plain = pia4.decrypt_payload(key, pia_lan.packet_iv(CONSOLE_IP, h.station, h.nonce8),
                                 pia4.ciphertext(packet), h.tag)
    assert plain is not None
    assert pia4.decrypt_payload(key, pia_lan.packet_iv(HOST_IP, h.station, h.nonce8),
                                pia4.ciphertext(packet), h.tag) is None
    (m,) = pia4.parse_packet(plain)
    assert m["protocol"] == pia_lan.PROTOCOL and m["source"] == reply["host_constant"]
    network_id, location = pia_lan.parse_host_message(m["payload"])
    assert network_id == reply["network_id"]
    t = 2 + location[0] + location[1]
    assert struct.unpack_from(">QI", location, t + 6) == (reply["host_constant"],
                                                          reply["host_variable"])


def _bindable(ip, port):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # as LanSocket binds
        try:
            s.bind((ip, port))
        except OSError:
            return False
    return True


def test_the_apps_lan_trade_trades_twice_with_our_lan_host_on_loopback(tmp_path, monkeypatch):
    """The app's Trade (LAN mode) arguments, pointed at our LAN host: two trades on one seat, keyed
    by nothing but the browse, with no board and no keys."""
    ports = (pia_lan.BROWSE_PORT, pia_lan.BROADCAST_PORT, pia_lan.STATION_PORTS[0])
    if not all(_bindable(ip, port) for ip in (HOST_IP, JOIN_IP) for port in ports):
        pytest.skip("needs the lo0 aliases 127.0.0.2 and 127.0.0.3 with ports 30000, 40000 and "
                    "49152 free")
    monkeypatch.delenv("POKELDN_RADIO", raising=False)
    import swsh_connect
    import swsh_host
    from test_swsh_trade_payload import a_payload
    from pokeldn.app.catalog import GAMES
    from pokeldn.app.command import build
    from pokeldn.app.settings import Settings
    from pokeldn import gen8, pokemon as pokemon_service
    from pokeldn.swsh import pokemon
    monkeypatch.setattr(pokemon_service, "prepare_file", lambda game, path, **kw: path)
    monkeypatch.setattr(pokemon_service, "prepare", lambda game, raw, **kw: gen8.decrypt(raw))

    party = a_payload(count=4)
    (tmp_path / "snapshot.bin").write_bytes(party)
    for slot in range(4):
        (tmp_path / f"offer{slot}.pk8").write_bytes(
            party[slot * gen8.SIZE_PARTY:(slot + 1) * gen8.SIZE_PARTY])
    lan = ["--lan-broadcast", "127.255.255.255"]
    result = {}
    host = threading.Thread(target=lambda: result.setdefault("host", swsh_host.main(
        ["--lan", "--our-ip", HOST_IP, *lan, "--seconds", "60", "--accept-first", "--lead", "3",
         "--snapshot", str(tmp_path / "snapshot.bin"), "--received", str(tmp_path / "host.pk8"),
         "--offer-file", str(tmp_path / "offer0.pk8"),
         "--offer-file", str(tmp_path / "offer1.pk8")])), daemon=True)
    tool = next(t for game in GAMES for t in game.tools if t.key == "swsh-lan")
    assert not tool.radio
    offers = [{"file": str(tmp_path / "offer2.pk8")}, {"file": str(tmp_path / "offer3.pk8")}]
    args = build(tool, {"--offer-file": offers, "--fresh-pid": False}, {}, Settings())
    args[args.index("--save-offered") + 1] = str(tmp_path / "join.pk8")
    # Our host is on an alias, not on a local /24: the address replaces the tool's `auto`.
    join = threading.Thread(target=lambda: result.setdefault("join", swsh_connect.main(
        args + ["--lan", HOST_IP, "--our-ip", JOIN_IP, *lan, "--dwell", "0.5", "--scans", "20",
                "--listen-first", "2", "--hold", "40"])), daemon=True)
    host.start()
    # Bound first: an emulated console on this machine answers on *:30000 until the alias is taken.
    time.sleep(1.0)
    join.start()
    join.join(150)
    host.join(150)
    assert result == {"host": 0, "join": 0}

    def species(name):
        return pokemon.read(pokemon.encrypt(gen8.load((tmp_path / name).read_bytes())))["species"]
    assert [species(n) for n in ("join.pk8", "join-2.pk8")] == [94, 95]
    assert [species(n) for n in ("host.pk8", "host-2.pk8")] == [96, 97]
