#!/usr/bin/env python3
"""Host a Let's Go Pikachu trade session, so the console joins us and speaks first.

The console's trade screen alternates hosting and scanning every few seconds, so it will find and
join a network that carries Let's Go's own title, passphrase and advertisement. A joining Let's Go
drives the session: it sends the station connection request, the mesh join request, its clone
announcements and, once the game is satisfied, the first message of the game's own protocol, which
is the thing a joiner of ours cannot synthesise.

    sudo ./.venv/bin/python bin/lgpe_host.py --seconds 180 --player-name PkCamp

    (them) Let's Go Pikachu: menu -> Communiquer -> Communication locale -> Echange,
           link code Pikachu, Pikachu, Pikachu, then wait on the search screen.

Every datagram in and out goes to --capture as one JSON line, and any game payload the console
sends is written beside it. docs/lgpe_session.md has every layout this speaks.
"""
import argparse
import json
import os
import random
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.ldn import clone, pia3, pia4, reliable3, station4, station9, sync_clock
from pokeldn.lgpe import pb7
from pokeldn.lgpe.trade import fresh_offer
from pokeldn.lgpe.trade import (TRADE_IN_PROGRESS, _answer_offer, _send_step,
                                _warn_if_mid_trade)
from pokeldn.ldn import local_protocol as lp
from pokeldn.ldn import mesh_protocol as mp
from pokeldn.ldn import rtt_protocol as rtt
from pokeldn.ldn.station_protocol import (DISCONNECTION_REQUEST, DISCONNECTION_RESPONSE,
                                          ldn_constant_id, ldn_service_variable_id,
                                          station_location)
from pokeldn.ldn.transport import HostTransport, board_radio, find_ap_phy
from pokeldn.host_support import resolve_keys
from pokeldn.lgpe import (APPLICATION_VERSION, COMM_ID_PIKACHU, MAX_PARTICIPANTS, PASSPHRASE,
                          PIA_PORT, SCENE_ID, SSID, build_advertise_data, packet_iv, session_keys)
from pokeldn.lgpe import local_host, mesh_host
from pokeldn.ldn import show_done

HOST_INDEX = 0
JOINER_INDEX = 1
HOST_BIT = 1 << HOST_INDEX
JOINER_BIT = 1 << JOINER_INDEX
KEEPALIVE_PROTOCOL = 0x08


class Advertisement:
    """What we advertise, and the keys that follow from it."""

    def __init__(self, network_id=None, session_param=None):
        self.network_id = network_id if network_id is not None else random.getrandbits(32)
        self.session_param = (session_param if session_param is not None
                              else random.getrandbits(32))
        self.data = build_advertise_data(self.network_id, self.session_param)
        self.keys = session_keys(self)

    @property
    def application_data(self):
        return self.data


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=180.0, help="how long to host")
    ap.add_argument("--player-name", default="PkCamp",
                    help="the nickname our connection response carries")
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--ifname", default="ldn-tap")
    ap.add_argument("--ap-ifname", default="ldn")
    ap.add_argument("--mon-ifname", default="ldn-mon")
    ap.add_argument("--channel", type=int, default=6)
    ap.add_argument("--no-skip-encryption", action="store_true",
                    help="let the LDN layer encrypt in software. The Archer T3U wants the "
                         "hardware path, which is the default here")
    ap.add_argument("--no-accept-decrypted-ccmp", action="store_true",
                    help="do not accept the frames rtw88 has already decrypted. With this the "
                         "host reads nothing on that adapter")
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--capture", default=None, help="every datagram, one JSON line each")
    ap.add_argument("--variable-id", type=lambda s: int(s, 0), default=0x0C0C0C0C,
                    help="our own variable id, any nonzero value")
    ap.add_argument("--protocol", type=int, default=1,
                    help="the LDN advertisement protocol. A title sees only its own: Let's Go "
                         "advertises and scans on 1, measured off the console's own beacon")
    ap.add_argument("--random-ssid", action="store_true",
                    help="let the LDN layer pick the session id. A Let's Go network's is the "
                         "fixed value every console advertises, which is the default here")
    ap.add_argument("--network-id", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--first", metavar="echo|PATH",
                    help="our kind-1 identity message, sent when the console's arrives: a captured "
                         "376-byte message, header included, or echo for the console's own back")
    ap.add_argument("--our-trainer", metavar="TID:SID",
                    help="the trainer id pair written over the identity's")
    ap.add_argument("--scene-id", type=int, default=SCENE_ID,
                    help="the advertised scene id; the link code moves it (Pikachu x3: 1, "
                         "docs/lgpe_session.md, The link code)")
    ap.add_argument("--fresh-pid", action="store_true",
                    help="offer the --offer structure under a new PID and encryption constant, "
                         "shiny state kept, so a save that took it before takes it again")
    ap.add_argument("--offer", metavar="echo|PATH",
                    help="answer the console's offer with this 232-byte box structure (echo: "
                         "its own back), and its commits with commits")
    ap.add_argument("--no-type4-data", dest="type4_data", action="store_false",
                    help="publish no clone data on clone types 4 and 1. Without it the console "
                         "never passes the gate at 0x11b080 and stays on its search screen")
    ap.add_argument("--drive-delay", type=float, default=1.0,
                    help="seconds between the steps the host drives an offered clone through")
    ap.add_argument("--grace", type=float, default=900.0,
                    help="seconds past --seconds to hold a session whose trade is half done")
    ap.add_argument("--first-copies", type=int, default=1,
                    help="how many kind 1 identities to send, 0.3 s apart under successive steps")
    ap.add_argument("--advance-after", type=float, default=0.0,
                    help="seconds after the party clones to move our state word to 2 and send the "
                         "offer, which is what a station does as its own state word reaches 2")
    ap.add_argument("--party-clones", type=int, default=2,
                    help="how many party clones (ids 2 up) to announce after the identities; the "
                         "reference host announced two")
    ap.add_argument("--party-clones-delay", type=float, default=3.2,
                    help="seconds after our identity to announce them")
    ap.add_argument("--session-param", type=lambda s: int(s, 0), default=None)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    fresh_offer(args, "[lgh]")
    if os.geteuid() != 0 and not board_radio():
        print("[lgh] must run as root (LDN needs the raw radio)"); return 1
    phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
    if phy is None:
        print("[lgh] no AP-capable phy"); return 1
    keys_path = resolve_keys(args.keys)
    if not os.path.exists(keys_path):
        print(f"[lgh] prod.keys not found at {keys_path!r}"); return 2

    adv = Advertisement(args.network_id, args.session_param)
    print(f"[lgh] advertising network id {adv.network_id:#010x} session param "
          f"{adv.session_param:#010x}")
    print(f"[lgh] {adv.keys}")

    cap = open(args.capture, "w") if args.capture else None

    def record(**kw):
        if cap:
            cap.write(json.dumps(kw) + "\n"); cap.flush()

    host = HostTransport(app_data=adv.data, password=PASSPHRASE, nickname=args.player_name,
                         keys_path=keys_path, local_comm_id=COMM_ID_PIKACHU, scene_id=args.scene_id,
                         app_version=APPLICATION_VERSION, max_participants=MAX_PARTICIPANTS,
                         phyname=phy, ifname=args.ifname, ap_ifname=args.ap_ifname,
                         mon_ifname=args.mon_ifname, channel=args.channel,
                         skip_encryption=not args.no_skip_encryption,
                         accept_decrypted_ccmp=not args.no_accept_decrypted_ccmp,
                         ssid=None if args.random_ssid else SSID, protocol=args.protocol)
    if not host.start():
        print("[lgh] the AP did not come up"); return 3
    print(f"[lgh] hosting: ssid={host.ssid.hex()} us={host.our_ip}/{host.our_mac.hex()}")
    record(rec="target", network_id=adv.network_id, session_param=adv.session_param,
           application_data=adv.data.hex(), session_key=adv.keys.session_key.hex(),
           our_ip=host.our_ip, our_mac=host.our_mac.hex())

    session = Session(host, adv, args, record)
    t0 = time.monotonic()
    try:
        while True:
            if time.monotonic() - t0 >= args.seconds:
                # a run that stops between the offer and the result leaves the console waiting on
                # a peer that is gone, and it refuses the next trade for about half an hour. Hold
                # the session until the exchange is settled or the console has left.
                if not TRADE_IN_PROGRESS["offer"] or session.trade.get("done"):
                    break
                if time.monotonic() - t0 >= args.seconds + args.grace:
                    break
            session.poll()
            time.sleep(0.005)
    except KeyboardInterrupt:
        print("[lgh] interrupted")
    finally:
        host.stop()
        if cap:
            cap.close()
        _warn_if_mid_trade(tag="[lgh]")
    print(f"[lgh] done: {session.rx} datagrams in, {session.tx} out, "
          f"{len(session.payloads)} game payload(s)")
    return 0


class Session:
    """One console's session, from its connection request to its game payloads."""

    def __init__(self, host, adv, args, record):
        self.host, self.adv, self.args, self.record = host, adv, args, record
        self.keys = adv.keys
        self.t0 = time.monotonic()
        self.rx = self.tx = 0
        self.nonce = 0
        self.peer_ip = None
        self.peer_mac = None
        self.peer_location = None
        self.peer_variable_id = 0
        self.our_const = ldn_constant_id(host.our_mac)
        self.our_location = station_location(host.our_ip, PIA_PORT, self.our_const,
                                             args.variable_id,
                                             ldn_service_variable_id(host.our_mac),
                                             nat_flags=0, nat_location=0, public=False)
        self.ack_id = 1
        self.seen = {}
        self.window = reliable3.Window()
        # an unacknowledged game message goes again: a commit that never arrives leaves the
        # console on its confirmation screen and its save refusing trades for half an hour
        self.window.clock = time.monotonic
        self.trade = {"window": self.window, "step": 1}
        self.payloads = []
        self.clone = None
        # the reference host's order, each step timed off the console's answer to the last:
        # its 0x33 -> a1+b1 for clone 0 30 ms later; its a2 -> the filled f3 30 ms later; the
        # f3 -> the clone 1 announcement 30 ms later, before the e3 arrives (docs/lgpe_session.md)
        self.announce_clone_0_at = None
        self.clone_0_announced = False
        self.publish_clone_0_at = None
        self.clone_0_published = False
        self.clone_0_acked = False
        self.clone_0_data = bytes(8)
        self.next_clone_0 = 0.0
        self.announce_clone_1_at = None
        self.clone_1_announced = False
        self.party_clones_at = None
        self.party_clones_announced = False
        self.advance_at = None
        self.advanced = False
        self.extra_first = None
        self.drive = []
        self.commit_clone = None
        self.committed = False
        self.commit_2_at = None
        self.peer_committed = False
        self.committed_2 = False
        self.result_clones_at = None
        self.result_clones_announced = False
        self.result_at = None
        self.result_sent = False
        self.leaving = set()
        self.peer_left = False
        self.released = set()
        self.release_at = []
        self.participants_at = None
        self.update_counter = 0
        self.session_sequence = 1
        self.sent_nodes = None
        self.repeat_session_at = None
        self.local_network_id = random.getrandbits(32)
        self.next_update = 0.0
        self.next_rtt = 0.0
        self.joined = False

    # -- plumbing ---------------------------------------------------------------------------
    def now(self):
        return time.monotonic() - self.t0

    def ms(self):
        return int(self.now() * 1000)

    def send(self, payload, protocol, destination=JOINER_BIT,
             flags=pia3.MESSAGE_FLAG_BITMAP, port=0, **what):
        """Everything a host sends carries the bitmap flag and its own constant id as the source.
        The station and mesh-join messages are addressed to 0 and the rest to the joiner's bit,
        which is what a retail console does (docs/lgpe_session.md)."""
        if self.peer_ip is None:
            return
        body = pia3.build_message(payload, protocol=protocol, source=self.our_const, port=port,
                                  destination=destination, message_flags=flags)
        self.nonce += 1
        nonce8 = self.nonce.to_bytes(8, "big")
        iv = packet_iv(self.keys, self.host.our_mac, nonce8, source_id=0)
        pkt = pia3.build_packet(self.keys.session_key, iv, body, station=HOST_INDEX,
                                nonce8=nonce8)
        self.host.send(pkt, self.peer_ip)
        self.tx += 1
        self.record(rec="tx", t=round(self.now(), 3), to=self.peer_ip, len=len(pkt),
                    data=pkt.hex(), **what)

    def decrypt(self, data):
        hdr = pia4.PiaHeader4.parse(data)
        ct = pia4.ciphertext(data)
        for mac in (self.peer_mac, self.host.our_mac):
            if not mac:
                continue
            for sid in sorted({hdr.station, 0, JOINER_INDEX}):
                iv = packet_iv(self.keys, mac, hdr.nonce8, source_id=sid)
                pt = pia4.decrypt_payload(self.keys.session_key, iv, ct, hdr.tag)
                if pt is not None:
                    return hdr, pt
        return hdr, None

    # -- the session ------------------------------------------------------------------------
    def poll(self):
        for participant in list(self.host.participants):
            index, ip, mac, name = participant
            if self.peer_ip is None:
                self.peer_ip, self.peer_mac = ip, bytes(mac)
                who = bytes(name).split(b"\0")[0]
                print(f"[lgh] *** CONSOLE JOINED *** idx={index} ip={ip} "
                      f"mac={bytes(mac).hex()} name={who!r}")
                self.record(rec="seat", ip=ip, mac=bytes(mac).hex(), name=bytes(name).hex())
        for payload, src_ip in self.host.recv():
            if not pia3.is_pia3(payload):
                continue
            if self.peer_ip is None:
                self.peer_ip = src_ip
            self.rx += 1
            self.record(rec="rx", t=round(self.now(), 3), src=src_ip, len=len(payload),
                        data=payload.hex())
            hdr, pt = self.decrypt(payload)
            if pt is None:
                if self.rx <= 5:
                    print(f"[lgh] a datagram from {src_ip} did not authenticate")
                continue
            for m in pia3.parse_packet(pt):
                self.handle(m["protocol"], m["payload"])
        self.tick()

    def tick(self):
        now = time.monotonic()
        if self.peer_ip is None:
            return
        # A host speaks first: a console that associates and hears nothing leaves again. The
        # update session goes out from the moment a station is seated, the mesh once it has joined.
        # the update session goes out when the session changes and once more behind it, never on a
        # timer: a reference host sent four in 441 s, one per change, each repeated once. The mesh
        # update is the one that goes every 2 s (docs/lgpe_session.md)
        nodes = self.session_nodes()
        if nodes != self.sent_nodes:
            self.sent_nodes = nodes
            self.session_sequence += 1
            self.repeat_session_at = now + 0.1
            self.broadcast_session(nodes)
        elif self.repeat_session_at is not None and now >= self.repeat_session_at:
            self.repeat_session_at = None
            self.broadcast_session(nodes)
        if not self.joined:
            return
        if now >= self.next_update:
            self.next_update = now + 2.0
            self.broadcast_mesh()
        if now >= self.next_rtt:
            self.next_rtt = now + 1.0
            self.send(rtt.build_v3(rtt.REQUEST, int(now * rtt.TICK_HZ_V3)), rtt.PROTOCOL)
        for msg in self.window.due(now):
            self.send(msg, reliable3.PROTOCOL)
            print(f"[lgh] reliable: sent again, unacknowledged for {self.window.RETRANSMIT_AFTER} s: "
                  f"{reliable3.parse(msg)['sequence']:#x}")
        if self.clone is not None:
            for out in self.clone.poll(now):
                if out[1] == clone.PARTICIPATE:
                    print("[lgh] clone: PARTICIPATE sent, 1.1 s after the console's")
                self.send(out, clone.PROTOCOL)
            if (self.announce_clone_0_at is not None and not self.clone_0_announced
                    and now >= self.announce_clone_0_at):
                self.clone_0_announced = True
                self.announce_clone_0(now)
            # the host owns clone 0 and publishes its data once the console has answered the
            # announcement pair; the console acknowledges it with an 0xe3
            if (self.publish_clone_0_at is not None and not self.clone_0_acked
                    and now >= self.publish_clone_0_at and now >= self.next_clone_0):
                self.next_clone_0 = now + 0.5
                record = clone.build_state_record(0, HOST_INDEX, 3, self.clone.ms(now),
                                                  bytes(self.clone_0_data))
                self.send(clone.build_data_message(clone.STATE_DATA, 3, 0xFD, 0,
                                                   self.clone.frame(now), record, flags=3),
                          clone.PROTOCOL)
                if not self.clone_0_published:
                    self.clone_0_published = True
                    # the reference host announces clone 1 in the frame it publishes clone 0, and
                    # the joiner's own copy is a mirror of it. The console announces its own 31 ms
                    # after this, so anything later loses the race and reverses the two roles.
                    self.announce_clone_1_at = now
                    print("[lgh] clone: published clone 0")
            if (self.announce_clone_1_at is not None and not self.clone_1_announced
                    and now >= self.announce_clone_1_at):
                self.clone_1_announced = True
                self.announce_clone_1(now)
            # the party clones, ids 2 and 3, come 3.2 s after the identities in the reference
            # session, from the host, one per party Pokemon (docs/lgpe_session.md)
            if (self.party_clones_at is not None and not self.party_clones_announced
                    and now >= self.party_clones_at):
                self.party_clones_announced = True
                for cid in range(2, 2 + self.args.party_clones):
                    self.announce_clone(now, cid)
                if self.args.advance_after:
                    self.advance_at = now + self.args.advance_after
            # the state word's move to 2 and the offer that goes with it: in the reference the
            # two stations do this 3.4 s after the identities, within 30 ms of each other
            while self.release_at and now >= self.release_at[0][0]:
                _, cid = self.release_at.pop(0)
                for out in self.clone.release(cid, now):
                    self.send(out, clone.PROTOCOL)
                self.participants_at = now + 0.1
                print(f"[lgh] clone: released our clone {cid} after the console's")
            # under test: the emulated station that stayed sent, with its acknowledgements of
            # the last releases, a clock-and-participant for clone 0 naming itself alone, and
            # the leaver answered with its clone exit within 30 ms. The console waits 2.4 s after
            # the releases before its leave request; this may be what it waits for.
            if self.participants_at is not None and now >= self.participants_at:
                self.participants_at = None
                c = self.clone
                self.send(c._command(clone.CLOCK_AND_PARTICIPANT, 3, 0xFD, 0, now,
                                     struct.pack(">II", c.ms(now), HOST_BIT)), clone.PROTOCOL)
                print("[lgh] clone: clone 0 participants: ourselves alone")
            while self.drive and now >= self.drive[0][0]:
                _, cid, flags, tail = self.drive.pop(0)
                self.clone.flags[cid] = flags
                self.clone.tail[cid] = tail
                self.publish_step()
                print(f"[lgh] clone: clone {cid} -> {flags.hex()} tail {tail}")
            if self.extra_first is not None and now >= self.extra_first[1]:
                body, _, left = self.extra_first
                # the same bytes, step 1 again: the receive at 0x117390 compares the message's
                # word at +8 against a fixed value, so a copy under a fresh step is dropped
                self.send(self.window.send(pb7.build_message(pb7.FIRST_MESSAGE, body)),
                          reliable3.PROTOCOL)
                left -= 1
                self.extra_first = (body, now + 0.3, left) if left else None
                print("[lgh] game: another identity, step 1 again")
            if self.advance_at is not None and not self.advanced and now >= self.advance_at:
                self.advanced = True
                self.send_offer()
            # the second commit, carrying 2, 63 to 66 ms after the first on both reference hosts
            # and behind the peer's own kind 3 on both
            if (self.commit_2_at is not None and not self.committed_2 and self.peer_committed
                    and now >= self.commit_2_at):
                self.committed_2 = True
                step = _send_step(self.trade, self.send, pb7.COMMIT_MESSAGE, b"\x02\0\0\0")
                self.publish_step()
                # the trade animation: a retail host sent its result 26.8 s after this, an
                # emulated one 29.9 s. The result clones come half a second before it.
                self.result_clones_at = now + 26.5
                self.result_at = now + 27.0
                print(f"[lgh] game: *** COMMIT sent, 2 under step {step} *** the trade is agreed; "
                      "the animation runs on the console now")
            if (self.result_clones_at is not None and not self.result_clones_announced
                    and now >= self.result_clones_at):
                self.result_clones_announced = True
                for cid in (self.commit_clone + 1, self.commit_clone + 2):
                    self.announce_clone(now, cid)
            if self.result_at is not None and now >= self.result_at:
                self.send_result()

    def announce_clone_0(self, now):
        """The clone the host owns from the start. A host announces it with the clock-and-count
        and the clock-and-participant messages and only then publishes its data; the joiner
        answers the pair with an 0xa2 and an 0xc1."""
        c = self.clone
        ms = c.ms(now)
        self.send(c._command(clone.CLOCK_AND_COUNT, 3, 0xFD, 0, now,
                             struct.pack(">IBBH", ms, 1, 0, c.element_ms(now) & 0xFFFF)),
                  clone.PROTOCOL)
        self.send(c._command(clone.CLOCK_AND_PARTICIPANT, 3, 0xFD, 0, now,
                             struct.pack(">II", ms, HOST_BIT | JOINER_BIT)), clone.PROTOCOL)
        print("[lgh] clone: announced clone 0 (a1 + b1)")

    def publish_step(self):
        """Our step counter goes in the clone type 2 copies, at +12 of the 20-byte data. Both
        stations carry their own there and it moves with every game message they send: the
        reference pair walked 1 with the identity, 2 with the offer, 3 and 4 with the commits and
        5 with the result (docs/lgpe_session.md)."""
        for out in self.clone.advance_state(time.monotonic(), self.trade.get("step", 1) & 0xFF):
            self.send(out, clone.PROTOCOL)

    def send_offer(self):
        """Our kind 2 offer, unprompted. A station sends one as its own state word reaches 2
        rather than in answer to the peer's (docs/lgpe_session.md)."""
        if not self.args.offer or self.args.offer == "echo":
            print("[lgh] game: no --offer structure to send first")
            return
        raw = open(self.args.offer, "rb").read()
        if len(raw) != pb7.BOX_SIZE:
            print(f"[lgh] game: {self.args.offer} is {len(raw)} bytes, not {pb7.BOX_SIZE}")
            return
        body = raw if pb7.valid(raw) else pb7.encrypt(raw)
        TRADE_IN_PROGRESS["offer"] = True
        step = _send_step(self.trade, self.send, pb7.OFFER_MESSAGE, body)
        print(f"[lgh] offer: *** SENT {len(body)} B step {step} *** {self.args.offer}, unprompted")
        self.publish_step()

    def send_result(self):
        """Our kind 4, once: the party as it stands, one message per slot. A reference host
        sent its own first slot, unchanged, 27 to 30 s after its second commit, and the joiner's
        own followed within 34 ms (docs/lgpe_session.md)."""
        if self.result_sent or not self.committed_2:
            return
        self.result_sent = True
        if not self.args.offer or self.args.offer == "echo":
            print("[lgh] game: no --offer structure to send as the result")
            return
        raw = open(self.args.offer, "rb").read()
        body = raw if pb7.valid(raw) else pb7.encrypt(raw)
        step = _send_step(self.trade, self.send, pb7.RESULT_MESSAGE, body)
        self.publish_step()
        print(f"[lgh] game: *** RESULT sent, step {step} *** {self.args.offer}")

    def announce_clone(self, now, cid):
        """A clone this station owns. A host announces it on clone type 2 and on types 4 and 1,
        then publishes its data on clone type 4; the joiner takes it over and announces its own
        copy (docs/lgpe_session.md, "The take-over exchange a joiner runs once per clone")."""
        c = self.clone
        c.owned.add(cid)
        content = b"\x01\x28\x08\xab"
        # the announcement is addressed to every station, where the rest go to the peer alone
        announce = clone.build_command(clone.COMMAND_ANNOUNCE, 2, HOST_INDEX, cid,
                                       c._next_count(), HOST_BIT | JOINER_BIT)
        self.send(announce[:2] + struct.pack(">H", c.frame(now)) + announce[4:], clone.PROTOCOL)
        clk = struct.pack(">I", c.ms(now))
        for ctype in (4, 1):
            self.send(c._command(clone.CLOCK_AND_COUNT, ctype, 0xFD, cid, now, clk + content),
                      clone.PROTOCOL)
        if c.publish_type4:
            record = clone.build_state_record(cid, HOST_INDEX, 3, c.ms(now), bytes(32))
            self.send(clone.build_data_message(clone.STATE_DATA, 4, 0xFD, cid, c.frame(now),
                                               record, flags=3), clone.PROTOCOL)
        c.held.add(cid)
        # the clone type 2 copy is not published here: a reference host publishes it only in the
        # frame that answers the peer's re-announcement, with the 0x82 (docs/lgpe_session.md)
        print(f"[lgh] clone: announced clone {cid} on clone types 2, 4 and 1")

    def announce_clone_1(self, now):
        self.announce_clone(now, 1)

    def session_nodes(self):
        """The session's node list. The peer joins it when it joins the mesh, not when it
        associates: a reference host declared one node until the joiner's mesh join and two from
        the frame after it (docs/lgpe_session.md)."""
        nodes = [(self.host.our_ip, PIA_PORT, 0)]
        if self.peer_ip and self.joined:
            nodes.append((self.peer_ip, PIA_PORT, 1))
        return tuple(nodes)

    def broadcast_session(self, nodes):
        body = local_host.build_update_session(
            self.session_sequence, self.local_network_id, self.args.variable_id,
            # the Local Protocol's body carries the constant id little-endian where the message
            # header carries it big-endian (tests/test_pia4.py, over a retail console's own
            # announcement). The game resolves a message's sender to a node through this table.
            ldn_service_variable_id(self.host.our_mac), self.our_const.to_bytes(8, "little"),
            list(nodes))
        self.send(body, lp.PROTOCOL, destination=0,
                  flags=pia3.MESSAGE_FLAG_BITMAP | pia3.MESSAGE_FLAG_UNBUNDLED)

    def broadcast_mesh(self):
        self.update_counter += 1
        entries = [(self.our_location, HOST_INDEX)]
        if self.peer_location:
            entries.append((self.peer_location, JOINER_INDEX))
        self.send(mesh_host.build_update_mesh(entries, self.update_counter), mp.PROTOCOL)

    def handle(self, protocol, pl):
        first = pl[0] if pl else -1
        key = (protocol, first)
        if key not in self.seen:
            self.seen[key] = 0
            print(f"[lgh] first {protocol:#04x} type {first:#04x} ({len(pl)}B) {pl[:24].hex()}")
        self.seen[key] += 1
        if protocol == station9.PROTOCOL:
            self.station(pl)
        elif protocol == mp.PROTOCOL:
            self.mesh(pl)
        elif protocol == lp.PROTOCOL:
            pass                                   # the joiner's acks need no answer
        elif protocol == sync_clock.PROTOCOL:
            m = sync_clock.parse_message(pl)
            if m is not None and m[1] == 0:
                self.send(struct.pack(">QQ", m[0], self.ms()), sync_clock.PROTOCOL)
        elif protocol == rtt.PROTOCOL:
            ans = rtt.response_for_v3(pl)
            if ans is not None:
                self.send(ans, rtt.PROTOCOL)
        elif protocol == KEEPALIVE_PROTOCOL:
            self.send(b"", KEEPALIVE_PROTOCOL)
        elif protocol == clone.PROTOCOL:
            if self.clone is None:
                self.new_clone()
            now = time.monotonic()
            # the Participant reads the peer's record first: a copy published off the record
            # before it lands carries the previous one, which put a zero first word in the type 4
            # copy at the commit clone's trailing word 1 and the console never answered it
            for out in self.clone.receive(pl, now):
                self.send(out, clone.PROTOCOL)
            self.clone_step(pl, now)
        elif protocol == reliable3.PROTOCOL:
            r = reliable3.parse(pl)
            for out in self.window.receive(pl):
                self.send(out, reliable3.PROTOCOL)
            if r and r["size"]:
                self.payloads.append(r["payload"])
                name = f"{self.args.capture or 'scratchpad/lgpe_host'}.payload{len(self.payloads)}.bin"
                open(name, "wb").write(r["payload"])
                print(f"[lgh] *** THE CONSOLE'S GAME PAYLOAD *** {r['size']}B -> {name}")
                print(f"[lgh]     {r['payload'][:48].hex()}")
                self.game(pb7.parse_message(r["payload"]))

    def game(self, msg):
        """The trade's own protocol: our identity once the console's arrives, then the offer and
        the commit answered the way the joiner answers a host's."""
        if msg is None:
            print("[lgh] game: not a trade message")
            return
        print(f"[lgh] game: kind {msg['kind']} step {msg['step']} body {msg['size']} B")
        if msg["kind"] == pb7.FIRST_MESSAGE and self.args.first and not self.trade.get("first"):
            self.trade["first"] = True
            # echo: the console's own identity back, under our trainer id, which separates a
            # field it needs from the peer from a screen that waits on something else
            body = (pb7.build_message(msg["kind"], msg["body"]) if self.args.first == "echo"
                    else open(self.args.first, "rb").read())
            first = pb7.parse_message(body)
            if first and self.args.our_trainer:
                tid, sid = (int(v, 0) for v in self.args.our_trainer.split(":"))
                body = pb7.build_message(first["kind"], pb7.set_trainer_id(first["body"], tid, sid))
            self.send(self.window.send(body), reliable3.PROTOCOL)
            self.trade["step"] = 1
            self.publish_step()
            print(f"[lgh] game: *** SENT our identity *** {len(body)} B from {self.args.first}")
            # state 7 leaves for 8 at exactly two first messages counted at obj+0x470, and the
            # console's own is assumed to be one of them. A second of ours separates a count that
            # never sees ours from a count that needs two from the peer (main 0x34946c).
            if self.args.first_copies > 1:
                self.extra_first = (first["body"] if first else body[16:],
                                    time.monotonic() + 0.3, self.args.first_copies - 1)
            self.party_clones_at = time.monotonic() + self.args.party_clones_delay
        elif msg["kind"] == pb7.OFFER_MESSAGE:
            _answer_offer(self.args, self.trade, msg, self.send, tag="[lgh]")
            self.publish_step()
        elif msg["kind"] == pb7.COMMIT_MESSAGE:
            # the peer's kind 3 answers the host's first; a host sends its second behind it and
            # echoes nothing (docs/lgpe_session.md, "The game's messages")
            value = int.from_bytes(msg["body"][:4], "little")
            print(f"[lgh] game: the console's commit carries {value}")
            if value == 1:
                self.peer_committed = True
        elif msg["kind"] == pb7.RESULT_MESSAGE:
            self.trade["done"] = True
            show_done()
            TRADE_IN_PROGRESS["offer"] = TRADE_IN_PROGRESS["commit"] = False
            print("[lgh] game: *** THE RESULT *** the trade has gone through on the console")
            self.send_result()

    def new_clone(self):
        self.clone = clone.Participant(time.monotonic(), dest=JOINER_BIT, own=HOST_BIT,
                                       station=HOST_INDEX)
        self.clone.host_role = True
        # the take-over corrections a joiner of ours needs against a console that announces:
        # one take-over per clone, later re-announcements answered with one a2 carrying their clock
        self.clone.ack_peer_clock = True
        self.clone.ack_re_announcement = True
        # under test: publish our copy of a taken-over clone 40 ms after the take-over, without
        # waiting for the announcer's, which the console never sends
        self.clone.publish_on_announce = True
        self.clone.publish_delay = 0.04
        self.clone.request_publishes_type4 = True
        self.clone.publish_type4 = self.args.type4_data
        # a retail station answers every clone type 2 publish with its own copy and keeps the
        # exchange running about ten times a second for the whole session: the completed trade
        # carried 2410 from the console and 2393 from the joiner (docs/lgpe_session.md)
        self.clone.publish_once = False

    def clone_step(self, pl, now):
        """What the console's clone message schedules on the host's side."""
        kind = pl[1] if len(pl) > 1 else -1
        if kind == clone.PARTICIPATE:
            print("[lgh] clone: the console PARTICIPATED")
        elif kind == clone.COMMAND_ANNOUNCE and not self.clone_1_announced:
            # the console announces clone 1 itself 32 ms after our clone 0 data; the Participant
            # takes it over the way a joiner does and the wrapper's own announcement is not owed
            self.clone_1_announced = True
            print("[lgh] clone: the console announced clone 1 first; taking it over")
        elif kind == clone.PARTICIPATE_ACK and self.announce_clone_0_at is None:
            self.announce_clone_0_at = now + 0.03
        elif kind in (clone.CLOCK_AND_COUNT_2, clone.CLOCK_COUNT_PARTICIPANT,
                      clone.CLOCK_COMMAND) and self.clone_0_announced \
                and self.publish_clone_0_at is None:
            # the reference joiner answers the pair with an a2 and a c1 in one frame; a 0x91
            # here is the answer a console gave when the pair reached it before its own a1
            c = clone.parse_command(pl)
            if c and (c["ctype"], c["station"], c["clone_id"]) == (3, 0xFD, 0):
                self.publish_clone_0_at = now + 0.03
                print(f"[lgh] clone: the console answered the clone 0 pair with {kind:#04x}")
        elif kind == clone.EXIT_REQUEST:
            print("[lgh] clone: the console left the clone protocol; acknowledged")
        elif kind == clone.COMMAND_END:
            # under test: the console released its copies and then waited 2.5 s before its leave
            # request. The emulated pair released their own copies in answer to each other's
            c = clone.parse_command(pl)
            if c and c["clone_id"] not in self.released:
                self.released.add(c["clone_id"])
                self.release_at.append((now + 0.03, c["clone_id"]))
        d = clone.parse_data_message(pl)
        # the offered party clone: once both stations publish 1 in each of the first three words,
        # the host is what moves the trailing word to 1 and the joiner answers it
        # (docs/lgpe_session.md). Until it does, the console holds "communication en cours".
        if (d and d["type"] == clone.STATE_DATA and d["ctype"] == 2 and d["record"]
                and d["record"].get("data", b"")[:12] == b"\x01\0\0\0" * 3
                and self.clone.tail.get(d["clone_id"]) is None
                and d["clone_id"] not in self.clone.flags):
            ones = b"\x01\0\0\0" * 3
            # the trailing word 1 goes out 30 ms after the 1 1 1, on both reference hosts
            self.drive = [(now + 0.03, d["clone_id"], ones, 1)]
            if d["clone_id"] < 2 + self.args.party_clones:
                # the rest of the walk the host drives, on the pace a player sets in a real
                # session: 01 02 02 with the trailing word still 1, then the trailing word 2
                self.drive += [(now + self.args.drive_delay, d["clone_id"],
                                b"\x01\0\0\0" + b"\x02\0\0\0" * 2, 1),
                               (now + 2 * self.args.drive_delay, d["clone_id"],
                                b"\x01\0\0\0" + b"\x02\0\0\0" * 2, 2)]
            else:
                # the clone the commit creates stops at the trailing word 1: the peer answers
                # it with a zero first word (docs/lgpe_session.md, "The two clone records")
                self.commit_clone = d["clone_id"]
            print(f"[lgh] clone: clone {d['clone_id']} offered on both sides; driving it on")
        # the peer's state word 4 is its player leaving. The emulated host answered it 29 ms
        # later with zeros in the first three words, the trailing word moved on by one, and the
        # peer's own argument in the type 4 copy's first word; the peer then released its clones
        # (docs/lgpe_session.md). A retail console sends two: argument 0 as it backs out of its
        # selection, then argument 3 as it leaves, each under a fresh counter and each answered.
        if (d and d["type"] == clone.STATE_DATA and d["ctype"] == 2 and d["record"]
                and d["record"].get("data", b"")[:4] == b"\x04\0\0\0"
                and (d["clone_id"], d["record"]["data"][8:12]) not in self.leaving):
            self.leaving.add((d["clone_id"], d["record"]["data"][8:12]))
            self.clone.arg[d["clone_id"]] = d["record"]["data"][4:8]
            # whatever walk was pending on that clone is off
            self.drive = [step for step in self.drive if step[1] != d["clone_id"]]
            self.drive.append((now + 0.03, d["clone_id"], bytes(12),
                               (self.clone.tail.get(d["clone_id"]) or 0) + 1))
            arg = int.from_bytes(d["record"]["data"][4:8], "little")
            print(f"[lgh] clone: the console's state 4 on clone {d['clone_id']}, argument {arg}; "
                  "acknowledging")
        # the peer answers the commit clone's trailing word 1 with a zero in its first word. The
        # host then zeroes the first word of every clone it drove, moves its step and sends its
        # kind 3 carrying 1, all in one frame; the peer's own kind 3 follows within a frame and
        # the host's second, carrying 2, four frames after the first (docs/lgpe_session.md)
        if (d and d["type"] == clone.STATE_DATA and d["ctype"] == 2
                and d["clone_id"] == self.commit_clone and d["record"]
                and d["record"].get("data", b"")[:4] == bytes(4)
                and self.clone.tail.get(self.commit_clone) == 1 and not self.committed):
            self.committed = True
            self.drive = []
            for cid, flags in list(self.clone.flags.items()):
                self.clone.flags[cid] = bytes(4) + flags[4:12]
            TRADE_IN_PROGRESS["commit"] = True
            self.trade["step"] = self.trade.get("step", 1) + 1
            self.publish_step()
            self.send(self.window.send(pb7.build_message(pb7.COMMIT_MESSAGE, b"\x01\0\0\0",
                                                         step=self.trade["step"])),
                      reliable3.PROTOCOL)
            self.commit_2_at = now + 0.065
            print(f"[lgh] game: *** COMMIT sent, 1 under step {self.trade['step']} ***")
        if d and d["type"] == clone.STATE_ACK and d["clone_id"] == 0 \
                and not self.clone_0_acked:
            self.clone_0_acked = True
            print("[lgh] clone: the console acknowledged our clone 0")

    def station(self, pl):
        kind = pl[0]
        if kind == station9.CONNECTION_REQUEST:
            ack = station9.ack_id_of(pl)
            self.peer_location = pl[station9.OFF_LOCATION:-4]
            try:
                self.peer_variable_id = station4.parse_station_location(
                    self.peer_location)["variable_id"]
            except Exception:
                self.peer_variable_id = 0
            # what a console does in this order: its own inverse request, the ack, its response
            # the inverse request carries the connection id the peer chose for its own request;
            # the console checks it against the record it keeps for us and drops a zero
            inverse = station9.build_connection_request(
                ldn_constant_id(self.peer_mac) if self.peer_mac else 0, self.peer_variable_id,
                self.our_location, ack_id=self.ack_id, connection_id=0xEC,
                inverse_connection_id=pl[station9.OFF_CONNECTION_ID], is_inverse=True)
            self.ack_id += 1
            self.send(inverse, station9.PROTOCOL, destination=0, kind="inverse_request")
            self.send(station9.build_ack(ack), station9.PROTOCOL, destination=0)
            resp = station9.build_connection_response(
                ldn_constant_id(self.peer_mac) if self.peer_mac else 0,
                self.peer_variable_id, ack_id=self.ack_id,
                network_id=int.from_bytes(self.keys.network_id_le, "little"),
                player_name=self.args.player_name)
            self.ack_id += 1
            self.send(resp, station9.PROTOCOL, destination=0, kind="connection_response")
            print(f"[lgh] answered the console's connection request ({len(resp)} B)")
        elif kind == station9.CONNECTION_RESPONSE:
            self.send(station9.build_ack(station9.ack_id_of(pl)), station9.PROTOCOL,
                      destination=0)
        elif kind == DISCONNECTION_RESPONSE:
            print("[lgh] the console answered our disconnection request")
        elif kind == DISCONNECTION_REQUEST:
            # one byte each way. A console that gets no answer repeats it every half second,
            # eight times, and deauthenticates: four seconds of black screen for its player
            self.send(bytes([DISCONNECTION_RESPONSE]), station9.PROTOCOL, destination=0)
            print("[lgh] the console asked to disconnect; answered")

    def mesh(self, pl):
        if pl[0] == mp.JOIN_REQUEST:
            ack = mp.read_ack_id(pl)
            entries = [(self.our_location, HOST_INDEX)]
            if self.peer_location:
                entries.append((self.peer_location, JOINER_INDEX))
            self.send(mesh_host.build_join_response(entries, ack), mp.PROTOCOL,
                      destination=0, kind="join_response")
            self.joined = True
            # the host starts the clone protocol: in a real session its first clock request goes
            # out about 40 ms after the join response
            self.new_clone()
            print("[lgh] *** THE CONSOLE JOINED THE MESH *** answered its join request; "
                  "starting the clone protocol")
            self.broadcast_mesh()
        elif pl[0] == 0 and len(pl) >= reliable3.HEADER_SIZE:
            # the mesh's reliable port: the leave request rides there under the same 24-byte
            # header as the game's data, and is owed that header's acknowledgement on that port
            # and a leave response on the unreliable one. Unanswered, a console repeats it every
            # 40 ms for five seconds and then falls back to the station disconnect.
            r = reliable3.parse(pl)
            if r and r["size"] and r["payload"][0] == mp.LEAVE_REQUEST and not self.peer_left:
                self.peer_left = True
                TRADE_IN_PROGRESS["offer"] = TRADE_IN_PROGRESS["commit"] = False
                self.send(reliable3.build_ack(r["sequence"] + 1), mp.PROTOCOL, port=1)
                self.send(bytes([mp.LEAVE_RESPONSE, r["payload"][1]]), mp.PROTOCOL,
                          destination=0, kind="leave_response")
                self.peer_location = None
                self.joined = False
                self.broadcast_mesh()
                # under test: the console waited five seconds after the leave response and then
                # sent its own disconnection request. A host that closes the connection itself,
                # with its own disconnection request, may be what it waits for.
                self.send(bytes([DISCONNECTION_REQUEST]), station9.PROTOCOL, destination=0)
                print(f"[lgh] *** THE CONSOLE LEFT THE MESH *** station {r['payload'][1]}; "
                      "answered its leave request and asked it to disconnect")


if __name__ == "__main__":
    sys.exit(main())
