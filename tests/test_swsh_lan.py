"""Sword/Shield in LAN mode: the browse exchange pinned to an emulated Shield's own bytes, then our
LAN joiner trading with our LAN host on the loopback aliases (docs/swsh_session.md, LAN mode)."""
import json
import os
import socket
import tempfile
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


@pytest.fixture
def loopback_lan():
    """One loopback LAN test at a time across xdist workers: every LAN socket sets SO_REUSEPORT, and
    Linux spreads a port's datagrams over all its sockets, another test's host among them."""
    fd = os.open(os.path.join(tempfile.gettempdir(), "pokeldn-swsh-lan.lock"), os.O_RDWR | os.O_CREAT)
    try:
        if os.name == "nt":
            import msvcrt
            while True:
                try:
                    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    pass
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)        # closing releases either lock


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
    request_key = pia_lan.parse_challenge(request["challenge"])["key"]
    assert pia_lan.check_response(GAME_KEY, BROADCAST, reply["challenge_reply"], plain, request_key)
    ours = pia_lan.build_response(GAME_KEY, BROADCAST, theirs["counter"], plain, reply["key_param"],
                                  challenge_key=theirs["key"])
    assert ours == reply["challenge_reply"]
    assert not pia_lan.check_response(GAME_KEY, "192.168.0.255", reply["challenge_reply"], plain,
                                      request_key)


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


def test_our_host_answers_a_swords_trade_browse_as_a_console_host_does(loopback_lan):
    """A retail Sword browses for its Y-Comm registry (maximum 4) before its trade search's own
    browse (game mode 60001, maximum 2). A 2-player host answers only the second, and keys each
    reply to the request it answers: the Sword checks a reply under the reply's challenge key and
    its own latest request's (0x0178ab2c), while the session info keeps the first key param."""
    if not _bindable(HOST_IP, pia_lan.BROWSE_PORT):
        pytest.skip("needs the lo0 alias 127.0.0.2 with port 30000 free")
    host = pia_lan.LanHostTransport(GAME_KEY, 60001, our_ip=HOST_IP, broadcast=BROADCAST,
                                    console_ip=CONSOLE_IP, log=lambda *a: None)
    host.bind_host(pia_lan.constant_id(HOST_IP, 49152), 1, host.network_id, bytes(32))
    host.start()
    criteria = VECTORS["criteria"]
    try:
        def browse(name):
            return pia_lan.browse(GAME_KEY, HOST_IP, bytes.fromhex(criteria[name]), our_ip=JOIN_IP,
                                  broadcast=BROADCAST, tries=1, wait=0.5)
        assert browse("registry") is None
        first, second = browse("trade"), browse("trade")
    finally:
        host.stop()
    assert first["challenge_ok"] and second["challenge_ok"]
    assert first["key_param"] == second["key_param"] == host.key_param
    assert (pia_lan.parse_challenge(first["challenge_reply"])["key"]
            != pia_lan.parse_challenge(second["challenge_reply"])["key"])


def test_our_host_seats_a_retail_swords_host_request_and_answers_its_session_request(loopback_lan):
    """A retail Sword's host request names source constant 0, and once in the mesh it asks for the
    session info (0x44 type 5) and leaves 5 s later without it. Its constant id is its address and
    station port; the answer is the session info in type 6 fragments, the Sword seated in it."""
    if not (_bindable(HOST_IP, pia_lan.BROWSE_PORT) and _bindable(JOIN_IP, 49155)):
        pytest.skip("needs the lo0 aliases 127.0.0.2 and 127.0.0.3 with ports 30000 and 49155 free")
    host = pia_lan.LanHostTransport(GAME_KEY, 60001, our_ip=HOST_IP, broadcast=BROADCAST,
                                    console_ip=CONSOLE_IP, log=lambda *a: None)
    host.bind_host(pia_lan.constant_id(HOST_IP, 49152), 1, host.network_id, bytes(32))
    host.start()
    sword = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sword.bind((JOIN_IP, 49155))
    sword.settimeout(2)
    try:
        assert pia_lan.browse(GAME_KEY, HOST_IP, bytes.fromhex(VECTORS["criteria"]["trade"]),
                              our_ip=JOIN_IP, broadcast=BROADCAST, tries=3, wait=1.0)
        msg = pia4.build_message(pia_lan.build_host_request(host.network_id),
                                 protocol=pia_lan.PROTOCOL, source=0)
        nonce8 = bytes(8)
        sword.sendto(pia4.build_packet(host.session_key, pia_lan.packet_iv(JOIN_IP, 0, nonce8),
                                       msg, nonce8=nonce8), (HOST_IP, 49152))
        deadline = time.time() + 2
        while not host.participants and time.time() < deadline:
            host.recv()
            time.sleep(0.02)
        assert host.constants[JOIN_IP] == pia_lan.constant_id(JOIN_IP, 49155)
        sword.recvfrom(4096)                                  # the host message
        host.answer_session_request(JOIN_IP)
        fragments = {}
        while len(fragments) < 2:
            data, _ = sword.recvfrom(4096)
            h = pia4.PiaHeader4.parse(data)
            plain = pia4.decrypt_payload(host.session_key,
                                         pia_lan.packet_iv(HOST_IP, h.station, h.nonce8),
                                         pia4.ciphertext(data), h.tag)
            (m,) = pia4.parse_packet(plain)
            body = m["payload"]
            assert body[0] == pia_lan.SESSION_MESSAGE
            index, count, size = struct.unpack_from(">BBI", body, 0x12)
            fragments[index] = body[0x18:0x18 + size]
            assert count == 2
    finally:
        host.stop()
        sword.close()
    info = pia_lan.parse_session_info(fragments[0] + fragments[1])
    assert info["players"] == 2 and info["key_param"] == host.key_param
    assert [s["constant_id"] for s in info["stations"]] == [
        pia_lan.constant_id(HOST_IP, 49152), pia_lan.constant_id(JOIN_IP, 49155)]


def _bindable(ip, port):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # as LanSocket binds
        try:
            s.bind((ip, port))
        except OSError:
            return False
    return True


@pytest.mark.parametrize("empty_offer", [False, True], ids=["offer-files", "empty-offer"])
def test_the_apps_lan_trade_trades_twice_with_our_lan_host_on_loopback(tmp_path, monkeypatch,
                                                                        empty_offer, loopback_lan):
    """The app's Trade (LAN Join) arguments, pointed at its Trade (LAN Host) on loopback: two trades
    on one seat, keyed by nothing but the browse, with no board and no keys. An empty offer trades the console's own
    first party Pokemon back; PKHeX refuses that record under a new PID, as it refused a retail
    Gengar whose PID is tied to its encounter, so only PKHeX may renew it."""
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
    party = a_payload(count=4)
    own_pids = {gen8.decrypt(party[i * gen8.SIZE_PARTY:(i + 1) * gen8.SIZE_PARTY])[0x1C:0x20]
                for i in range(4)}

    def prepare(game, raw, fresh=False, **kw):
        plain = gen8.decrypt(raw)
        if plain[0x1C:0x20] not in own_pids:
            raise ValueError("PID+ correlation does not match")
        return plain
    monkeypatch.setattr(pokemon_service, "prepare", prepare)

    (tmp_path / "snapshot.bin").write_bytes(party)
    for slot in range(4):
        (tmp_path / f"offer{slot}.pk8").write_bytes(
            party[slot * gen8.SIZE_PARTY:(slot + 1) * gen8.SIZE_PARTY])
    lan = ["--lan-broadcast", "127.255.255.255"]
    result = {}
    tools = {t.key: t for game in GAMES for t in game.tools}
    host_tool = tools["swsh-lan-host"]
    assert not host_tool.radio
    host_args = build(host_tool, {"--offer-file": [{"file": str(tmp_path / "offer0.pk8")},
                                                   {"file": str(tmp_path / "offer1.pk8")}]},
                      {}, Settings())
    host_args[host_args.index("--received") + 1] = str(tmp_path / "host.pk8")
    host = threading.Thread(target=lambda: result.setdefault("host", swsh_host.main(
        host_args + ["--our-ip", HOST_IP, *lan, "--seconds", "60", "--accept-first", "--lead", "3",
                     "--snapshot", str(tmp_path / "snapshot.bin")])), daemon=True)
    tool = tools["swsh-lan"]
    assert not tool.radio
    offers = [] if empty_offer else [{"file": str(tmp_path / "offer2.pk8")},
                                     {"file": str(tmp_path / "offer3.pk8")}]
    args = build(tool, {"--offer-file": offers}, {}, Settings())
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
    assert [species(n) for n in ("host.pk8", "host-2.pk8")] == ([94, 94] if empty_offer
                                                                else [96, 97])


@pytest.mark.parametrize("activity", ["raid", "lair"])
def test_our_lan_den_and_adventure_lobbies_seat_our_lan_guest(tmp_path, monkeypatch, capsys, activity,
                                                              loopback_lan):
    """The app's Max Raid and Dynamax Adventure LAN tools against each other: the guest's 4-seat
    browse finds the lobby, whose session info carries the lobby's game bytes a guest's Y-Comm reads
    (`0x006bb968`), and the lobby runs to the battle start or the adventure's handover."""
    ports = (pia_lan.BROWSE_PORT, pia_lan.BROADCAST_PORT, pia_lan.STATION_PORTS[0])
    if not all(_bindable(ip, port) for ip in (HOST_IP, JOIN_IP) for port in ports):
        pytest.skip("needs the lo0 aliases 127.0.0.2 and 127.0.0.3 with ports 30000, 40000 and "
                    "49152 free")
    monkeypatch.delenv("POKELDN_RADIO", raising=False)
    import swsh_connect
    import swsh_host
    from test_swsh_trade_payload import a_payload
    from pokeldn import gen8, pokemon as pokemon_service
    monkeypatch.setattr(pokemon_service, "prepare_file", lambda game, path, **kw: path)
    monkeypatch.setattr(pokemon_service, "prepare", lambda game, raw, **kw: gen8.decrypt(raw))
    party = a_payload(count=3)
    (tmp_path / "snapshot.bin").write_bytes(party)
    lan = ["--lan-broadcast", "127.255.255.255"]
    from pokeldn.app.catalog import GAMES
    from pokeldn.app.command import build
    from pokeldn.app.settings import Settings
    tools = {t.key: t for game in GAMES for t in game.tools}
    if activity == "raid":
        adverts = json.loads((Path(__file__).parent / "data" / "swsh_raid_adverts.json").read_text())
        (tmp_path / "boss.pk8").write_bytes(bytes.fromhex(adverts["boss_hoothoot"]))
        (tmp_path / "m1.pk8").write_bytes(party[gen8.SIZE_PARTY:2 * gen8.SIZE_PARTY])
        host_tool, join_tool = tools["swsh-lan-raid-host"], tools["swsh-lan-raid-join"]
        hosting = {"--raid-boss": {"file": str(tmp_path / "boss.pk8")},
                   "--offer-file": {"file": str(tmp_path / "m1.pk8")}}
    else:
        host_tool, join_tool = tools["swsh-lan-lair-host"], tools["swsh-lan-lair-join"]
        hosting = {"--lair-legendary": "144", "--lair-seed": "173502832"}
    assert not host_tool.radio and not join_tool.radio
    host_args = build(host_tool, hosting, {}, Settings())
    join_args = build(join_tool, {}, {}, Settings())
    # Our host is on an alias, not on a local /24: the address replaces the tool's `auto`.
    join_args[join_args.index("auto")] = HOST_IP
    result = {}
    host = threading.Thread(target=lambda: result.setdefault("host", swsh_host.main(
        host_args + ["--our-ip", HOST_IP, *lan, "--seconds", "45"])), daemon=True)
    join = threading.Thread(target=lambda: result.setdefault("join", swsh_connect.main(
        join_args + ["--our-ip", JOIN_IP, *lan, "--capture", str(tmp_path / "join.jsonl"),
                     "--dwell", "0.5", "--scans", "20", "--listen-first", "2", "--hold", "35",
                     "--send-snapshot", str(tmp_path / "snapshot.bin")])), daemon=True)
    host.start()
    time.sleep(1.0)
    join.start()
    join.join(150)
    host.join(150)
    out = capsys.readouterr().out
    assert result == {"host": 0, "join": 0}
    target = next(json.loads(line) for line in (tmp_path / "join.jsonl").read_text().splitlines()
                  if '"target"' in line)
    data = bytes.fromhex(target["application_data"])
    assert len(data) == 0x168
    if activity == "raid":
        # Den record at advertisement 0xAF and 0xB0 (docs/swsh_raid.md), 0x18 lower: rank 0, Hoothoot.
        assert data[0xAF - 0x18] == 0x11 and struct.unpack_from("<H", data, 0xB0 - 0x18)[0] == 163
        assert "[raid] 127.0.0.3: both sides started" in out
    else:
        assert "[lair] the legendary is species 144" in out and "we are index 1" in out


def test_a_host_on_an_alias_hears_a_session_request_broadcast_to_its_station_port(loopback_lan):
    """An emulated Shield joining from Y-Comm sent its session request to 192.168.1.255:49152..49155
    and nothing to the host's own address; a host on a loopback alias missed it (error 34)."""
    if not _bindable(HOST_IP, pia_lan.STATION_PORTS[0]):
        pytest.skip("needs the lo0 alias 127.0.0.2 with port 49152 free")
    ours = next((ip for ip in pia_lan.local_addresses() if not ip.startswith("127.")), None)
    if ours is None:
        pytest.skip("needs an address off loopback")
    host = pia_lan.LanHostTransport(GAME_KEY, 60006, our_ip=HOST_IP, console_ip=ours,
                                    log=lambda *a: None)
    host.start()
    try:
        heard = {s.getsockname() for s in host._station_ports}
    finally:
        host.stop()
    assert (pia_lan.broadcast_address(ours), pia_lan.STATION_PORTS[0]) in heard


def test_our_adventure_host_answers_a_retail_max_lair_search_with_its_attributes(loopback_lan):
    """A retail Sword's Invite Others in LAN mode browses once for game mode 50000 with attributes
    2, 3 and 4 set, and joins only a session whose attributes hold those values; then it hosts."""
    if not _bindable(HOST_IP, pia_lan.BROWSE_PORT):
        pytest.skip("needs the lo0 alias 127.0.0.2 with port 30000 free")
    host = pia_lan.LanHostTransport(GAME_KEY, 50000, our_ip=HOST_IP, broadcast=BROADCAST,
                                    console_ip=CONSOLE_IP, max_participants=4, log=lambda *a: None)
    host.bind_host(pia_lan.constant_id(HOST_IP, 49152), 1, host.network_id, bytes(32))
    host.start()
    try:
        reply = pia_lan.browse(GAME_KEY, HOST_IP, bytes.fromhex(VECTORS["criteria"]["lair"]),
                               our_ip=JOIN_IP, broadcast=BROADCAST, tries=1, wait=0.5)
    finally:
        host.stop()
    assert reply["attributes"] == [0, 0, 0xFFFFFFFE, 0x33D39298, 0x253CAD29, 0]
