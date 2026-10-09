"""Scarlet / Violet Tera Raids (docs/sv_raid.md): the seed against PKHeX and the game's own tables,
the bootstrap against retail bytes, and both launchers against a scripted console."""
import hashlib
import os
import struct
import sys
import zlib

import pytest
import trio

import sv_host
import sv_join
from pokeldn import gen9, sv
from pokeldn.app.catalog import GAMES
from pokeldn.app.command import build
from pokeldn.app.settings import Settings
from pokeldn.ldn import channel_table, game_channel, pia6, pia_connect, reliable5
from pokeldn.sv import lz4, port2, raid, raid_encounter, raid_search, streams

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "switch"))

# PKHeX.Core 26.8.26's `Encounter9RNG.GenerateData` and `Tera9RNG.GetTeraType` on these seeds: seed,
# context, species, form, stars, EC, PID, IVs (HP Atk Def Spe SpA SpD), ability, gender, nature,
# (height, weight, scale), Tera type. Two are Toxtricity, whose nature its form's list gives.
PKHEX = [
    (0xBD13FB43, "violet", "paldea", "4star", "standard", 58, 0, 2, 0xDFB1659E, 0x155C9799,
     (10, 31, 9, 20, 13, 15), 18, 0, 19, (213, 129, 128), 11),
    (0xFDAE7B7D, "violet", "paldea", "4star", "standard", 205, 0, 4, 0x204BE5D8, 0xA809B319,
     (27, 31, 31, 28, 31, 17), 5, 0, 8, (166, 224, 164), 1),
    (0x000F34C3, "violet", "paldea", "4star", "standard", 624, 0, 2, 0x22AC9F1E, 0x36DDA01D,
     (31, 31, 31, 31, 31, 31), 128, 0, 20, (222, 64, 125), 8),
    (0xE7F524F3, "scarlet", "paldea", "5star", "standard", 849, 0, 5, 0x0A928F4E, 0xABDFD5B6,
     (31, 31, 31, 31, 11, 16), 57, 0, 14, (186, 109, 66), 14),
    (0xDA8A6C88, "violet", "paldea", "5star", "standard", 849, 1, 5, 0xFD27D6E3, 0x17705573,
     (31, 31, 16, 31, 3, 31), 58, 0, 15, (43, 181, 161), 3),
    (0x12345678, "scarlet", "kitakami", "6star", "black", 62, 0, 6, 0x34D1C0D3, 0xEDB11674,
     (31, 31, 31, 31, 31, 25), 33, 1, 5, (161, 116, 151), 9),
    (0x9ABCDEF0, "violet", "blueberry", "6star", "black", 89, 1, 6, 0xBD5A494B, 0x8957F6FE,
     (31, 31, 31, 31, 3, 31), 223, 1, 19, (99, 75, 130), 11),
    (0x0BADF00D, "scarlet", "blueberry", "3star", "standard", 170, 0, 1, 0x2E4B5A68, 0xC2E05583,
     (17, 19, 18, 12, 4, 31), 35, 0, 19, (186, 209, 198), 8),
    (0xCAFEBABE, "violet", "kitakami", "beginning", "standard", 173, 0, 1, 0xED9C2519, 0xB6B34799,
     (5, 28, 15, 10, 11, 31), 56, 0, 14, (171, 69, 89), 2),
    (0xDEADBEEF, "scarlet", "paldea", "6star", "black", 691, 0, 6, 0x014B294A, 0x8059C15D,
     (31, 31, 31, 11, 31, 31), 91, 1, 15, (155, 179, 118), 10),
]


@pytest.mark.parametrize("case", PKHEX, ids=[f"{c[0]:08X}-{c[2]}-{c[4]}" for c in PKHEX])
def test_the_boss_a_seed_gives_is_pkhex_s(case):
    seed, version, region, progress, content, species, form, stars, ec, pid, ivs, ability, gender, \
        nature, sizes, tera = case
    found = raid_encounter.generate(seed, version, region, progress, content)
    b = found.boss
    assert (b["species"], b["form"], found.stars, b["encryption_constant"], b["pid"], b["ivs"],
            b["ability"], b["gender"], b["nature"], (b["height_scalar"], b["weight_scalar"], b["scale"]),
            found.tera_type) == (species, form, stars, ec, pid, ivs, ability, gender, nature, sizes, tera)


def test_the_bootstrap_matches_retail_records():
    """A retail Violet's bootstrap for seed BD13FB43: its boss record, and the record it puts in an
    empty participant slot (both empty slots of a retail event bootstrap hold the same bytes)."""
    found = raid_encounter.generate(0xBD13FB43)
    assert hashlib.sha256(raid.boss_record(found)).hexdigest() == \
        "fa48396b91413a0e54b86a074b3b10dcf077d8633e9d5a45c7466830325f66c3"
    assert hashlib.sha256(raid.empty_participant()).hexdigest() == \
        "befa78ce3efc6035ef511bfab95dd962e1019612e7b9bef80c85fb7955e36ae4"


def test_the_raidpoint_matches_two_retail_points():
    """Words of a two-star (Growlithe, BD13FB43) and a four-star (Forretress, FDAE7B7D) retail
    RaidPoint, Violet, Paldea, four-star progress; the bonus rows after the seed's are the host's."""
    two = raid.raid_point(raid_encounter.generate(0xBD13FB43), name="RaidPoint_12_1_11")
    assert two[:0x30] == bytes.fromhex("52616964506f696e745f31325f315f3131000000000000004000000000000000"
                                       "02000000000000000100000014000000")
    assert struct.unpack_from("<I", two, 0x4C) == (500,) and two[0x50:0xE0] == bytes(0x90)
    assert [struct.unpack_from("<II", two, 0xE4 + 16 * i) for i in range(9)] == [
        (1125, 3), (1961, 2), (566, 1), (1961, 1), (88, 1), (1961, 1), (155, 1), (566, 1), (88, 1)]
    assert struct.unpack_from("<7I", two, 0x3B8) == (2, 58, 0, 0, 20, 0, 11)
    four = raid.raid_point(raid_encounter.generate(0xFDAE7B7D), name="RaidPoint_10_01_07")
    assert struct.unpack_from("<4I", four, 0x20) == (4, 0, 1, 45)
    assert struct.unpack_from("<25I", four, 0x4C) == (
        1200, 60, 40, 9999, 30, 0, 334, 20, 80, 40, 3, 1, 90, 106, 2, 2, 60, 0, 3, 1, 40, 106, 0, 0, 0)
    assert [struct.unpack_from("<II", four, 0xE4 + 16 * i) for i in range(15)] == [
        (1126, 2), (1127, 1), (1983, 4), (567, 2), (1983, 2), (1868, 1), (1868, 2), (1126, 1),
        (157, 1), (1126, 1), (171, 3), (171, 3), (1126, 1), (89, 1), (1983, 2)]
    assert struct.unpack_from("<4I", four, 0x210) == (5, 0, 0, 0)
    assert struct.unpack_from("<7I", four, 0x3B8) == (4, 205, 0, 0, 45, 0, 1)


def test_a_boss_past_916_is_named_by_its_devid():
    """Tinkatink, National Dex 957, is DevID 1000 in the game's raid table (raid_enemy_02, no 2050)."""
    found = raid_encounter.generate(0x123)
    assert (found.species, found.row["identifier"]) == (957, 2050)
    assert struct.unpack_from("<I", raid.raid_point(found), 0x3BC) == (1000,)
    assert struct.unpack_from("<I", raid.descriptor(0x105, found), 18 + 4) == (1000,)
    assert gen9.read(gen9.load(raid.boss_record(found)))["species"] == 957


def test_a_reward_list_replaces_the_seed_s_and_must_fit():
    found = raid_encounter.generate(0xFDAE7B7D)
    point = raid.raid_point(found, [(15, 500), (15, 500)])
    assert struct.unpack_from("<8I", point, 0xE0) == (0, 15, 500, 0, 0, 15, 500, 0)
    assert point[0x100:0x3B8] == bytes(0x2B8)
    with pytest.raises(ValueError):
        raid.raid_point(found, [(1, 1)] * (raid.REWARD_ROWS + 1))


def test_lz4_blocks_cross_an_independent_decoder():
    """Ours read by `nso_read.lz4_block`; one liblz4 1.10 made (LZ4_compress_default) read by ours."""
    from nso_read import lz4_block
    plain = raid.bootstrap(raid_encounter.generate(0xBD13FB43), ())
    assert lz4_block(lz4.compress(plain), len(plain)) == plain
    theirs = bytes.fromhex("ff0552616964506f696e745f504f4b454c444e5f30000100145f504b4c444e0500240f6300"
                           "06500000000000")
    assert lz4.decompress(theirs, 149) == b"RaidPoint_POKELDN_0" + bytes(40) + b"PKLDN" * 12 + bytes(30)


def test_the_port2_session_and_the_channel_table_are_a_retail_host_s():
    """A retail raid host's type 6 on 0x7C port 2 (its station id replaced) and its six-key table."""
    assert port2.build_session(0x0102030405060708) == bytes.fromhex(
        "06b905b905b906050400bc09000000000000000000bc8080" + "00" * 128 + "000000b90183080706050403020100ba04b9018308"
        "07060504030201b90100b90100b90100bc04000000000100")
    assert raid.channel_table() == bytes.fromhex(
        "b90106b902b9027b0001b902b902320101b902b902320201b902b902320301b902b90280803301b902b902808034"
        "01")


def test_a_search_keeps_the_best_boss_of_the_species_asked_for():
    scope = raid_search.contexts("violet", "paldea", "4star", "standard")
    found = raid_search.search(0, 3000, scope, "physical", species_id=624, limit=3)
    every = [raid_encounter.generate(s) for s in range(3000)]
    pawniard = sorted((r.boss["stats"][0] * r.boss["stats"][2], r.seed) for r in every if r.species == 624)
    assert [(f.score, f.seed) for f in found] == pawniard[:3]


# The scripted console. Addresses and ids as tests/test_sv_departure.py's.
HOST_IP, JOIN_IP, BROADCAST = "169.254.10.1", "169.254.10.2", "169.254.10.255"
HOST_MAC, JOIN_MAC = bytes.fromhex("02aabbccdd01"), bytes.fromhex("02aabbccdd02")
SSID = bytes.fromhex("7b744617795970bb6882b24ded4cae15")
CONSOLE_CID, CONSOLE_VAR = bytes.fromhex("eb9b2220f1480000"), 0x23AE


class Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    monotonic = time

    def sleep(self, seconds):
        self.now += seconds


def reliable(protocol, seq, payload, flags):
    if protocol == 0x7C:
        return reliable5.build_header(flags, seq, len(payload), lowest_pending=seq) + payload
    return reliable5.build_header(flags, seq, len(payload), lowest_pending=1, destination_bits=3,
                                  bitmap=[1]) + payload


def party(species):
    return gen9.encrypt(gen9.build(species=species, moves=(33, 0, 0, 0), ot_name="Player"))


class RaidGuestConsole:
    """A retail guest as captured against a raid host: it acknowledges the station list, joins port 2
    after the host's type 6, shows its Pokemon after the type 9s, answers the start with 0x0d, loads
    the bootstrap, and marks the battle."""

    def __init__(self, clock):
        self.clock, self.keys = clock, sv.session_keys(SSID)
        self.later, self.queue, self.seen, self.seqs = [], [], [], {}
        self.done = set()
        self.pokemon = party(658)
        self.at(0.2, pia6.build_session_join(CONSOLE_CID, CONSOLE_VAR, JOIN_IP,
                                             pia_connect.ldn_constant_id(HOST_MAC), 1, "Player",
                                             bytes(4)), 0x98)

    def at(self, delay, body, protocol, port=0, flags=0):
        self.later.append((self.clock.now + delay, body, protocol, port, flags))

    def send_data(self, delay, protocol, port, payload, compressed=False):
        seq = self.seqs.get((protocol, port), 1)
        self.seqs[(protocol, port)] = seq + 1
        flags = (raid.COMPLETE_ZLIB if compressed else raid.COMPLETE) \
            | (reliable5.FLAG_IS_INITIALIZED if seq == 1 else 0)
        body = streams.compress(payload) if compressed else payload
        self.at(delay, reliable(protocol, seq, body, flags), protocol, port)

    def once(self, name):
        if name in self.done:
            return False
        self.done.add(name)
        return True

    def received(self, packet, dst):
        _, plain, _ = pia6.parse_packet(self.keys.session_key, HOST_IP, self.keys.network_id, packet)
        for msg in pia6.parse_messages(plain):
            p, row = bytes(msg.payload), dict(t=self.clock.now, dst=dst, protocol=msg.protocol,
                                              port=msg.port, flags=msg.message_flags)
            if msg.protocol in (0x7C, 0x80, 0x81) and len(p) >= reliable5.HEADER_SIZE:
                rm = reliable5.parse(p)
                row.update(seq=rm["sequence_id"], rflags=rm["flags"], lowest=rm["lowest_pending"])
                if rm["flags"] & reliable5.FLAG_APPLICATION_DATA:
                    body = rm["payload"]
                    if rm["flags"] & reliable5.FLAG_ZLIB:
                        body = zlib.decompressobj().decompress(body)
                    row["data"] = body
                    self.answer_data(msg.protocol, msg.port, rm, body)
            else:
                row["data"] = p
                self.answer(msg.protocol, p)
            self.seen.append(row)

    def answer(self, protocol, p):
        if protocol == 0x2C and p[1] == 0x11:
            self.at(0.01, pia_connect.build_net_response(int.from_bytes(p[4:8], "big")), 0x2C, 0, 0x11)
        if protocol == 0x2C and p[1] == 0x50:
            self.at(0.02, bytes([1, 0x51, 0, 0]) + p[4:8], 0x2C, 0, 0x11)
        if protocol == 0x98 and p[0] == 5:
            update = pia_connect.parse_session_update_v11(p, route_bytes=0)
            self.at(0.03, pia_connect.build_session_update_ack_v11(CONSOLE_CID, update["sequence_id"]), 0x98)
        if protocol == 0x58 and p[0] == 0:
            self.at(0.01, streams.build_rtt_response(p, 1), 0x58)

    def answer_data(self, protocol, port, rm, body):
        if protocol == 0x7C:
            self.at(0.01, game_channel.build_ack(rm["sequence_id"] + 1, lowest_pending=1), 0x7C, port)
        else:
            self.at(0.01, streams.build_ack({0: rm["sequence_id"]}, 1, 1), protocol, port, 0xA0)
        if (protocol, port) == (0x7C, 2) and body[:1] == b"\x06" and self.once("join"):
            self.send_data(0.3, 0x7C, 2, port2.build_join(0))
        if (protocol, port) == (0x80, 2) and body[:1] == b"\x09" and self.once("lobby"):
            self.send_data(0.5, 0x80, 0, raid.state(1, raid.STATE_IDLE), compressed=True)
            self.send_data(0.52, 0x80, 0, raid.pokemon(2, self.pokemon))
        if (protocol, port) != (0x80, 0):
            return
        if raid.state_of(body) == raid.STATE_START and self.once("start"):
            self.send_data(0.4, 0x80, 0, raid.state(3, raid.STATE_STARTED), compressed=True)
        if rm["sequence_id"] == 12 and self.once("load"):
            self.send_data(1.0, 0x80, 0, raid.message(raid.KEY_LOAD, 0x6E, 0, 5, bytes(4)))
            self.send_data(3.0, 0x80, 0, raid.message(raid.KEY_LOAD, 0x73, 0, 6, bytes(4)))
        if body[:4] == raid.BATTLE and self.once("battle"):
            self.send_data(2.0, 0x80, 0, raid.message(raid.KEY_BATTLE, 0x93, 1, 7, bytes(4)))

    def tick(self):
        self.clock.now += 0.01
        for item in [x for x in self.later if x[0] <= self.clock.now]:
            self.later.remove(item)
            _, body, protocol, port, flags = item
            self.queue.append(sv_join.build_out(self.keys, JOIN_IP, body, 1, protocol=protocol, port=port,
                                                flags=flags, src_var=CONSOLE_VAR))


def run_raid_host(monkeypatch, tmp_path, rewards=()):
    clock = Clock()
    console = RaidGuestConsole(clock)

    class Transport:
        ssid, our_ip, our_mac, broadcast = SSID, HOST_IP, HOST_MAC, BROADCAST
        participants, join_events = [(JOIN_MAC, JOIN_IP)], 1

        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def set_application_data(self, _):
            pass

        def send(self, packet, dst):
            console.received(packet, dst)

        def wait_readable(self, _):
            console.tick()

        def recv(self):
            queued, console.queue = console.queue, []
            return [(packet, JOIN_IP) for packet in queued]

    ours = tmp_path / "ours.pk9"
    ours.write_bytes(party(25))
    monkeypatch.setattr(sv_host, "time", clock)
    monkeypatch.setattr(sv_host, "HostTransport", Transport)
    monkeypatch.setattr(sv_host, "find_ap_phy", lambda log=None: "esp32")
    monkeypatch.setattr(sv_host, "needs_root", lambda: False)
    monkeypatch.setattr(sv_host.pokemon_service, "prepare_file", lambda game, path, **kw: path)
    monkeypatch.setattr(sv_host.pokemon_service.SERVICE, "names",
                        lambda game, kind: [{"id": 15, "name": "Quick Ball"}])
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-host")
    args = build(tool, {"--raid-pokemon": {"file": str(ours)}, "--raid-seed": "000F34C3",
                        "--raid-reward": [{"item_id": str(i), "quantity": str(q)} for i, q in rewards]},
                 {}, Settings())
    assert sv_host.main(args + ["--keys", str(tmp_path / "prod.keys"), "--seconds", "60"]) == 0
    return console, clock


# What the host's twenty raid messages start with, their reliable flags and lowest pending, as the
# host a retail console fought its raids against sent them.
RAID_MESSAGES = [
    ("80332c01", 31, 1), ("80332d01", 7, 1), ("80332e01", 7, 1), ("80333001", 7, 4),
    ("80333001", 7, 5), ("80333001", 7, 6), ("80332d01", 23, 7), ("80333001", 7, 8),
    ("80333001", 7, 9), ("80332d01", 23, 10), ("80332f01", 3, 11), (None, 21, 11),
    ("32017300", 7, 13), ("80349301", 7, 14), ("7b001327", 23, 15), ("7b001327", 23, 15),
    ("7b001327", 23, 15), ("7b001327", 23, 17), ("7b001327", 23, 18), ("7b001327", 23, 20)]


def test_a_console_fights_the_raid_we_host(monkeypatch, tmp_path):
    console, clock = run_raid_host(monkeypatch, tmp_path, rewards=[(15, 500)])
    first = {}
    for row in console.seen:
        if (row["protocol"], row["port"]) == (0x80, 0) and "data" in row:
            first.setdefault(row["seq"], row)
    assert sorted(first) == list(range(1, 21))
    assert [((first[s]["data"][:4].hex() if s != 12 else None), first[s]["rflags"], first[s]["lowest"])
            for s in range(1, 21)] == RAID_MESSAGES
    assert all(r["dst"] == BROADCAST for r in first.values())
    sent = lambda s: first[s]["t"]
    whole = first[11]["data"] + first[12]["data"]
    plain = raid.payload_of(whole)
    assert plain[:gen9.SIZE_PARTY] == party(25)
    assert plain[gen9.SIZE_PARTY:2 * gen9.SIZE_PARTY] == console.pokemon
    assert plain[2 * gen9.SIZE_PARTY:4 * gen9.SIZE_PARTY] == raid.empty_participant() * 2
    point = plain[raid.RAIDPOINT:]
    assert struct.unpack_from("<8I", point, 0xE0) == (0, 15, 500, 0, 0, 0, 0, 0)
    net = [r for r in console.seen if r["protocol"] == 0x2C and r["data"][1:2] == b"\x50"]
    session = [r for r in console.seen if r["protocol"] == 0x98 and r["data"][0] == 5
               and pia_connect.parse_session_update_v11(r["data"], route_bytes=0)["sequence_id"] == 1]
    assert net and net[0]["flags"] == 0x31 and net[0]["data"][27] == 7
    assert sent(10) < net[0]["t"] < session[0]["t"] < sent(11) <= sent(12) < sent(13) < sent(14) < sent(15)
    assert [sent(s) - sent(15) for s in range(15, 21)] == pytest.approx(raid.HANDOFF_AT, abs=0.011)
    assert clock.now - sent(20) == pytest.approx(raid.LINGER, abs=0.05)



HOST_VAR = sv_host.PIA_HOST_VAR
HOST_CID = pia_connect.ldn_constant_id(HOST_MAC)


class RaidHostConsole:
    """A retail raid host as a captured guest saw it: the join response and station list together,
    the list again 2 s later until acknowledged, the six-key table and the type 6, the start 3 s
    after the guest's Pokemon, the battle 2 s after its answer."""

    def __init__(self, clock):
        self.clock, self.keys = clock, sv.session_keys(SSID)
        self.queue, self.later, self.got, self.seqs, self.done = [], [], [], {}, set()
        self.list_acked = False
        self.at(0.0, sv_host.build_net_probe(self.keys, HOST_IP, HOST_MAC, [HOST_IP, JOIN_IP], 3,
                                             os.urandom(8), 4, net_flags=0x31))

    def at(self, delay, packet):
        self.later.append((self.clock.now + delay, packet))

    def reply(self, body, protocol=0x98, port=0, flags=0, mesh=False):
        return sv_host.build_reply(self.keys, HOST_IP, body, sv_join.OUR_VAR, os.urandom(8),
                                   protocol=protocol, port=port, flags=flags, mesh=mesh)

    def data(self, delay, protocol, port, payload, compressed=False):
        seq = self.seqs.get((protocol, port), 1)
        self.seqs[(protocol, port)] = seq + 1
        flags = (raid.COMPLETE_ZLIB if compressed else raid.COMPLETE) \
            | (reliable5.FLAG_IS_INITIALIZED if seq == 1 else 0)
        body = streams.compress(payload) if compressed else payload
        self.at(delay, self.reply(reliable(protocol, seq, body, flags), protocol, port))

    def station_list(self, sequence):
        stations = [dict(constant_id=HOST_CID, variable_id=HOST_VAR, ip=HOST_IP, port=12345,
                         station_index=0, route=None, join_order=0, token=bytes(32),
                         players=[dict(player_id=pia_connect.DEFAULT_PLAYER_ID, name="Player")]),
                    dict(constant_id=self.guest_cid, variable_id=sv_join.OUR_VAR, ip=JOIN_IP,
                         port=12345, station_index=1, route=None, join_order=1, token=bytes(32),
                         players=[dict(player_id=pia_connect.DEFAULT_PLAYER_ID, name="POKELDN")])]
        return self.reply(pia_connect.build_session_update_v11(HOST_CID, HOST_VAR, stations,
                                                               sequence_id=sequence), mesh=True)

    def resend_list(self):
        if not self.list_acked:
            self.queue.append(self.station_list(0))
            self.later.append((self.clock.now + 2.0, None))

    def sendto(self, packet, _):
        _, plain, _ = pia6.parse_packet(self.keys.session_key, JOIN_IP, self.keys.network_id, packet)
        for msg in pia6.parse_messages(plain):
            p = bytes(msg.payload)
            row = dict(t=self.clock.now, protocol=msg.protocol, port=msg.port, flags=msg.message_flags,
                       payload=p)
            self.got.append(row)
            if msg.protocol == 0x98 and p[0] == 0 and "join" not in self.done:
                self.done.add("join")
                self.guest_cid = pia_connect.parse_session_join_v11(p)["source_constant_id"]
                self.queue.append(self.reply(pia_connect.build_session_join_response_v11(
                    HOST_CID, HOST_VAR, self.guest_cid, sv_join.OUR_VAR, version=0, sequence_id=0,
                    route=None, random4=bytes(4))))
                self.queue.append(self.station_list(0))
                self.later.append((self.clock.now + 2.0, None))
            elif msg.protocol == 0x98 and p[0] == 6 and not self.list_acked:
                self.list_acked = True
                self.data(0.1, 0x7C, 1, raid.channel_table(), compressed=True)
                self.data(0.1, 0x7C, 2, port2.build_session(port2.station_id(HOST_CID)), compressed=True)
            elif msg.protocol in (0x7C, 0x80, 0x81) and len(p) >= reliable5.HEADER_SIZE:
                rm = reliable5.parse(p)
                row.update(seq=rm["sequence_id"], rflags=rm["flags"])
                if rm["flags"] & reliable5.FLAG_APPLICATION_DATA:
                    body = rm["payload"]
                    if rm["flags"] & reliable5.FLAG_ZLIB:
                        body = zlib.decompressobj().decompress(body)
                    row["data"] = body
                    if msg.protocol == 0x80 and body[:4] == raid.CONSOLE_POKEMON and "start" not in self.done:
                        self.done.add("start")
                        self.data(3.0, 0x80, 0, raid.state(0x10E, raid.STATE_START), compressed=True)
                    if msg.protocol == 0x80 and raid.state_of(body) == raid.STATE_STARTED \
                            and "battle" not in self.done:
                        self.done.add("battle")
                        self.data(2.0, 0x80, 0, raid.BATTLE_READY)

    def recvfrom(self, _):
        if self.queue:
            return self.queue.pop(0), (HOST_IP, sv.PIA_PORT)
        raise BlockingIOError

    def close(self):
        pass

    def tick(self):
        self.clock.now += 0.01
        for item in [x for x in self.later if x[0] <= self.clock.now]:
            self.later.remove(item)
            if item[1] is None:
                self.resend_list()
            else:
                self.queue.append(item[1])


def test_our_guest_joins_a_console_s_raid_and_leaves_its_pokemon_in_the_battle(monkeypatch, tmp_path):
    clock = Clock()
    host = RaidHostConsole(clock)

    async def wait_readable(_):
        host.tick()
        await trio.lowlevel.checkpoint()

    ours = tmp_path / "ours.pk9"
    ours.write_bytes(party(25))
    monkeypatch.setattr(sv_join, "time", clock)
    monkeypatch.setattr(sv_join, "make_socket", lambda *a: host)
    monkeypatch.setattr(trio.lowlevel, "wait_readable", wait_readable)
    monkeypatch.setattr(sv_join.pokemon_service, "prepare_file", lambda game, path, **kw: path)
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-join")
    ap = sv_join.build_parser()
    args = ap.parse_args(build(tool, {"--raid-pokemon": {"file": str(ours)}}, {}, Settings())
                         + ["--ip-join", "--rtt-period", "0"])
    sv_join.raid_guest(ap, args)
    seat = trio.run(sv_join.run_session, args, host.keys, HOST_IP, HOST_MAC, JOIN_IP, JOIN_MAC,
                    lambda **row: None)
    assert seat["raided"]
    got = host.got
    first = lambda pred: next(r for r in got if pred(r))
    acks = [r for r in got if r["protocol"] == 0x98 and r["payload"][0] == 6]
    # The station list that came with the join response is left; its retransmission is answered.
    assert acks[0]["t"] >= got[0]["t"] + 2.0
    clock_request = first(lambda r: r["protocol"] == 0x77)
    assert clock_request["payload"] == bytes(9) + b"\x01" + bytes(8)
    assert all(r["flags"] == 0x11 for r in got if r["protocol"] == 0x2C)
    tables = [r for r in got if (r["protocol"], r["port"]) == (0x7C, 1) and "data" in r]
    assert [len(channel_table.parse(r["data"])) for r in tables[:2]] == [4, 2]
    assert tables[1]["t"] - tables[0]["t"] == pytest.approx(sv_join.RAID_KEYS_DELAY, abs=0.02)
    port2_join = first(lambda r: (r["protocol"], r["port"]) == (0x7C, 2) and "data" in r)
    assert port2_join["data"] == port2.build_join(0)
    assert port2_join["t"] - tables[0]["t"] == pytest.approx(sv_join.RAID_PORT2_DELAY, abs=0.02)
    channel_acks = [r for r in got if r["protocol"] == 0x7C and "data" not in r]
    assert channel_acks and all(r["flags"] == streams.MESSAGE_FLAGS_ACK for r in channel_acks)
    sends = {r["seq"]: r for r in reversed(got) if (r["protocol"], r["port"]) == (0x80, 0) and "data" in r}
    lobby = [sends[seq] for seq in sorted(sends)]
    assert [raid.state_of(r["data"]) for r in lobby] == [raid.STATE_IDLE, None, raid.STATE_READY,
                                                         raid.STATE_STARTED]
    assert raid.pokemon_of(lobby[1]["data"]) == gen9.load(party(25))
    assert lobby[2]["t"] - lobby[0]["t"] == pytest.approx(2.0, abs=0.02)
    battle_ack = [r for r in got if (r["protocol"], r["port"]) == (0x80, 0) and "data" not in r]
    assert battle_ack[-1]["t"] == got[-1]["t"]
