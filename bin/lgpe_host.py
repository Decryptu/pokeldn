#!/usr/bin/env python3
"""Host a Let's Go Pikachu trade session: the console joins us and speaks first.

    sudo ./.venv/bin/python bin/lgpe_host.py --seconds 180 --player-name POKELDN

    (them) Let's Go Pikachu: menu -> Communiquer -> Communication locale -> Echange,
           link code Pikachu, Pikachu, Pikachu, then wait on the search screen.

Game payloads are written beside --capture. docs/lgpe_session.md has every layout.
"""
from pathlib import Path
import argparse
import json
import os
import random
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.host_support import open_output
from pokeldn import pokemon as pokemon_service
from pokeldn.ldn import clone, pia3, pia4, reliable3, station4, station9, sync_clock
from pokeldn.lgpe import pb7
from pokeldn.lgpe.trade import (TRADE_IN_PROGRESS, _answer_offer, _send_step,
                                _warn_if_mid_trade, show_offer)
from pokeldn.app import screen
from pokeldn.online import session as online
from pokeldn.ldn import local_protocol as lp
from pokeldn.ldn import mesh_protocol as mp
from pokeldn.ldn import rtt_protocol as rtt
from pokeldn.ldn.station_protocol import (DISCONNECTION_REQUEST, DISCONNECTION_RESPONSE,
                                          ldn_constant_id, ldn_service_variable_id,
                                          station_location)
from pokeldn.ldn.ldn_mitm_host import IpHostTransport
from pokeldn.ldn.transport import HostTransport, board_radio, find_ap_phy
from pokeldn.host_support import resolve_keys, needs_root, write_file
from pokeldn.lgpe import (APPLICATION_VERSION, COMM_ID_PIKACHU, MAX_PARTICIPANTS, PASSPHRASE,
                          PIA_PORT, SSID, build_advertise_data, packet_iv, scene_id,
                          session_keys)
from pokeldn.lgpe.session import SEARCH_CHANNELS
from pokeldn.lgpe import local_host, mesh_host
from pokeldn.ldn import left_after_trade, show_done

HOST_INDEX = 0
JOINER_INDEX = 1
HOST_BIT = 1 << HOST_INDEX
JOINER_BIT = 1 << JOINER_INDEX
KEEPALIVE_PROTOCOL = 0x08


class Advertisement:
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
    ap.add_argument("--player-name", default="POKELDN",
                    help="the nickname our connection response carries")
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--ifname", default="ldn-tap")
    ap.add_argument("--ap-ifname", default="ldn")
    ap.add_argument("--mon-ifname", default="ldn-mon")
    ap.add_argument("--channel", default="code",
                    help="1, 6, 11; code (default): the channel the link code puts a searching "
                         "console on, the only one it joins on; auto: scan for the console's own "
                         "network under our scene id and host on its channel")
    ap.add_argument("--code", default="pikachu,pikachu,pikachu",
                    help="the link code the player enters: three picker names (English or French) "
                         "or indices 0-9, comma-separated")
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
    ap.add_argument("--trainer-name", default="POKELDN",
                    help="the player name our identity carries, the one the trade screen shows")
    ap.add_argument("--our-trainer", metavar="TID:SID",
                    help="the trainer id pair written over the identity's")
    ap.add_argument("--scene-id", type=int, default=None,
                    help="the advertised scene id, in place of the one --code gives")
    ap.add_argument("--received", help="write the peer's offered PB7 here")
    ap.add_argument("--fresh-pid", action="store_true",
                    help="offer every --offer and --next-offer structure under a new PID and encryption constant, "
                         "shiny state kept, so a save that took it before takes it again")
    ap.add_argument("--offer", metavar="echo|PATH",
                    help="answer the console's offer with this 232-byte box structure (echo: "
                         "its own back), and its commits with commits")
    ap.add_argument("--next-offer", metavar="PATH", action="append", default=[],
                    help="232-byte box structure for the next trade in the same session; "
                         "repeatable, one per trade after the first")
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
    ap.add_argument("--result-after", type=float, default=27.0,
                    help="seconds after the second commit to send the result, the next trade's "
                         "first slot, with two clones announced 0.5 s before it; a retail host sent "
                         "it 26.8 s after, behind its trade animation")
    ap.add_argument("--ignore-clone0-answer", action="store_true",
                    help="test only: ignore the console's first answer to our clone 0 pair, as if "
                         "lost, so the pair goes again")
    ap.add_argument("--withhold-announce", type=int, default=0, metavar="N",
                    help="test only: skip the first N of our announcements to the console alone, as "
                         "if lost, so the resend carries them")
    ap.add_argument("--lead", type=float, default=None, metavar="SECONDS",
                    help="test only, for bin/lgpe_join.py: act as a console host's player, each "
                         "step this many seconds after the last. Offer unprompted after the party "
                         "clones and after each result, vote on the offered clone, announce and vote "
                         "the commit clone, commit (docs/lgpe_session.md). Never against a console")
    ap.add_argument("--agree-withdrawn-vote", action="store_true",
                    help="test only: carry the drive on through a withdrawn vote, as the host did "
                         "before it answered state 2 (docs/lgpe_session.md). Locks a console's save")
    ap.add_argument("--ip-host", action="store_true",
                    help="host over ldn_mitm for an emulator instead of the radio (docs/ldn.md)")
    ap.add_argument("--our-ip", default=None, help="with --ip-host, the address to advertise")
    online.add_arguments(ap)
    return ap


async def find_console_channel(keys, phy, scene, seconds, channels=(1, 6, 11), dwell=0.5):
    """The channel of a searching console's own network under `scene`, or None within `seconds`.
    A searching console joins only a host on its own channel (docs/lgpe_session.md, The link code)."""
    import trio
    import ldn
    deadline = trio.current_time() + seconds
    while trio.current_time() < deadline:
        for net in await ldn.scan(keys, phyname=phy, channels=list(channels), dwell_time=dwell):
            if net.local_communication_id == COMM_ID_PIKACHU and net.scene_id == scene:
                print(f"[lgh] the console searches on channel {net.channel} ({net.address})")
                return net.channel
    return None


def console_channel(keys_path, phy, scene, seconds):
    import trio
    import ldn
    return trio.run(find_console_channel, ldn.load_keys(keys_path), phy, scene, seconds)


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.online and (args.offer or args.next_offer):
        print("[lgh] --online offers the partner's Pokemon; --offer and --next-offer are ignored")
        args.offer, args.next_offer = None, []
    fresh, args.fresh_pid = args.fresh_pid, False
    if args.offer and args.offer != "echo":
        args.offer = pokemon_service.prepare_file("lgpe", args.offer, fresh=fresh)
    args.next_offer = [pokemon_service.prepare_file("lgpe", path, fresh=fresh) for path in args.next_offer]
    for path in args.next_offer:
        with open(path, "rb") as fh:
            if not pb7.valid(fh.read()):
                print(f"[lgh] next offer {path} is not a valid {pb7.BOX_SIZE}-byte box structure")
                return 2
    show_offer(args.offer)
    if not args.ip_host and needs_root():
        print("[lgh] hosting over the radio needs root, a board (POKELDN_RADIO), or --ip-host")
        return 1
    phy = None
    if not args.ip_host:
        phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
        if phy is None:
            print("[lgh] no AP-capable phy"); return 1
    keys_path = resolve_keys(args.keys)
    if not args.ip_host and not os.path.exists(keys_path):
        print(f"[lgh] prod.keys not found at {keys_path!r}"); return 2

    scene = args.scene_id if args.scene_id is not None else scene_id(args.code.split(","))
    if args.channel == "auto" and args.ip_host:
        channel = SEARCH_CHANNELS[scene % 3]
    elif args.channel == "auto":
        channel = console_channel(keys_path, phy, scene, args.seconds)
    elif args.channel == "code":
        channel = SEARCH_CHANNELS[scene % 3]
    else:
        channel = int(args.channel)
    if channel is None:
        print(f"[lgh] no console advertised scene id {scene}: is it searching with that code?")
        return 3
    print(f"[lgh] link code {args.code} -> scene id {scene}, channel {channel}")
    adv = Advertisement(args.network_id, args.session_param)
    print(f"[lgh] advertising network id {adv.network_id:#010x} session param "
          f"{adv.session_param:#010x}")
    print(f"[lgh] {adv.keys}")

    cap = open_output(args.capture, "w") if args.capture else None

    def record(**kw):
        if cap:
            cap.write(json.dumps(kw) + "\n"); cap.flush()

    common = dict(app_data=adv.data, password=PASSPHRASE, nickname=args.player_name,
                  keys_path=keys_path, local_comm_id=COMM_ID_PIKACHU, scene_id=scene,
                  app_version=APPLICATION_VERSION, max_participants=MAX_PARTICIPANTS,
                  channel=channel, ssid=None if args.random_ssid else SSID,
                  protocol=args.protocol)
    if args.ip_host:
        host = IpHostTransport(**common, mirror_comm_version=True,
                               **({"our_ip": args.our_ip} if args.our_ip else {}))
    else:
        host = HostTransport(**common, phyname=phy, ifname=args.ifname, ap_ifname=args.ap_ifname,
                             mon_ifname=args.mon_ifname,
                             skip_encryption=not args.no_skip_encryption,
                             accept_decrypted_ccmp=not args.no_accept_decrypted_ccmp)
    if not host.start():
        print("[lgh] the AP did not come up"); return 3
    print(f"[lgh] hosting: ssid={host.ssid.hex()} us={host.our_ip}/{host.our_mac.hex()}")
    record(rec="target", network_id=adv.network_id, session_param=adv.session_param,
           application_data=adv.data.hex(), session_key=adv.keys.session_key.hex(),
           our_ip=host.our_ip, our_mac=host.our_mac.hex())

    session = Session(host, adv, args, record,
                      partner=online.partner("lgpe", args, code=args.code, name=args.trainer_name))
    t0 = time.monotonic()
    try:
        while True:
            if time.monotonic() - t0 >= args.seconds:
                # Stopping between offer and result makes the console refuse the next trade for
                # 600 s of play: hold until the exchange is settled or the console has left.
                if not TRADE_IN_PROGRESS["offer"] or session.trade.get("done"):
                    break
                if time.monotonic() - t0 >= args.seconds + args.grace:
                    break
            if left_after_trade(host.participants):
                print("[lgh] the console left after the trade; closing")
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
    def __init__(self, host, adv, args, record, partner=None):
        self.host, self.adv, self.args, self.record = host, adv, args, record
        # Online (pokeldn.online): the partner's console's kind 2 answers ours, and the A 2 that
        # starts the console's save waits for both consoles' votes (docs/online.md).
        self.partner = partner
        self.console_offer = None         # the console's kind 2 still owed an answer
        self.sent_remote = None           # the partner record our kind 2 carried
        self.held_vote = None             # the offered clone whose A 2 waits for the partner
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
        # A commit that never arrives leaves the console's save refusing trades for 600 s of play.
        self.window.clock = time.monotonic
        self.trade = {"window": self.window, "step": 1}
        self.round = 0
        self.received = args.received
        self.payloads = []
        self.clone = None
        # Each step is timed 30 ms off the console's answer to the last (docs/lgpe_session.md).
        self.announce_clone_0_at = None
        self.clone_0_announced = False
        self.clone_0_resend_at, self.clone_0_resends = 0.0, 0
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
        # --lead (test only): an unprompted offer awaiting its answer, and the timers.
        self.led = False
        self.lead_offer_at = self.lead_vote_at = None
        self.lead_commit_clone_at = self.lead_commit_at = None
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
        self.withdrawn = {}
        self.revoted = set()
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

    def now(self):
        return time.monotonic() - self.t0

    def ms(self):
        return int(self.now() * 1000)

    def send(self, payload, protocol, destination=JOINER_BIT,
             flags=pia3.MESSAGE_FLAG_BITMAP, port=0, **what):
        """As a retail console: the bitmap flag, our constant id as source
        (docs/lgpe_session.md)."""
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
        # A console that hears nothing leaves again. The update session goes once per change and
        # once more behind it, never on a timer; the mesh update every 2 s (docs/lgpe_session.md).
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
            for event in self.clone.events:
                print(f"[lgh] clone: {event}")
            self.clone.events.clear()
            if (self.announce_clone_0_at is not None and not self.clone_0_announced
                    and now >= self.announce_clone_0_at):
                self.clone_0_announced = True
                self.announce_clone_0(now)
                self.clone_0_resend_at, self.clone_0_resends = now + 0.11, 0
            if (self.clone_0_announced and self.publish_clone_0_at is None
                    and now >= self.clone_0_resend_at and self.clone_0_resends < 20):
                # A retail console host repeats an unanswered pair about 110 ms later
                # (docs/lgpe_session.md, The clone 0 pair).
                self.clone_0_resend_at, self.clone_0_resends = now + 0.11, self.clone_0_resends + 1
                print(f"[lgh] clone: no answer to the clone 0 pair; resent ({self.clone_0_resends})")
                self.announce_clone_0(now)
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
                    # The console announces its own clone 1 31 ms after this: anything later loses
                    # the race and reverses the two roles.
                    self.announce_clone_1_at = now
                    print("[lgh] clone: published clone 0")
            if (self.announce_clone_1_at is not None and not self.clone_1_announced
                    and now >= self.announce_clone_1_at):
                self.clone_1_announced = True
                self.announce_clone_1(now)
            if (self.party_clones_at is not None and not self.party_clones_announced
                    and now >= self.party_clones_at):
                self.party_clones_announced = True
                for cid in range(2, 2 + self.args.party_clones):
                    self.announce_clone(now, cid)
                if self.args.advance_after:
                    self.advance_at = now + self.args.advance_after
                if self.args.lead is not None:
                    self.lead_offer_at = now + self.args.lead
            while self.release_at and now >= self.release_at[0][0]:
                _, cid = self.release_at.pop(0)
                for out in self.clone.release(cid, now):
                    self.send(out, clone.PROTOCOL)
                self.participants_at = now + 0.1
                print(f"[lgh] clone: released our clone {cid} after the console's")
            # Under test: the console waits 2.4 s after the releases before its leave request; a
            # clock-and-participant naming ourselves alone may be what it waits for.
            if self.participants_at is not None and now >= self.participants_at:
                self.participants_at = None
                c = self.clone
                self.send(c._command(clone.CLOCK_AND_PARTICIPANT, 3, 0xFD, 0, now,
                                     struct.pack(">II", c.ms(now), HOST_BIT)), clone.PROTOCOL)
                print("[lgh] clone: clone 0 participants: ourselves alone")
            while self.drive and now >= self.drive[0][0]:
                _, cid, flags, tail, *then = self.drive.pop(0)
                for step in then:
                    step()
                self.clone.flags[cid] = flags
                self.clone.tail[cid] = tail
                self.publish_step()
                print(f"[lgh] clone: clone {cid} -> {flags.hex()} tail {tail}")
            if self.extra_first is not None and now >= self.extra_first[1]:
                body, _, left = self.extra_first
                # Step 1 again: the receive at 0x117390 compares the word at +8 against a fixed
                # value and drops a copy under a fresh step.
                self.send(self.window.send(pb7.build_message(pb7.FIRST_MESSAGE, body)),
                          reliable3.PROTOCOL)
                left -= 1
                self.extra_first = (body, now + 0.3, left) if left else None
                print("[lgh] game: another identity, step 1 again")
            if self.advance_at is not None and not self.advanced and now >= self.advance_at:
                self.advanced = True
                self.send_offer()
            if self.lead_offer_at is not None and now >= self.lead_offer_at:
                self.lead_offer_at = None
                self.send_offer()
            if self.lead_vote_at is not None and now >= self.lead_vote_at:
                self.lead_vote_at = None
                self.lead_vote(now)
            if self.lead_commit_clone_at is not None and now >= self.lead_commit_clone_at:
                self.lead_commit_clone_at = None
                self.lead_commit_clone(now)
            if self.lead_commit_at is not None and now >= self.lead_commit_at:
                self.lead_commit_at = None
                if not self.committed:
                    self.commit(now)
            if (self.commit_2_at is not None and not self.committed_2 and self.peer_committed
                    and now >= self.commit_2_at):
                self.committed_2 = True
                step = _send_step(self.trade, self.send, self.commit_kind, b"\x02\0\0\0")
                self.publish_step()
                screen.received("lgpe", self.trade.get("peer_offer"))
                # A retail host sent its result 26.8 s after this (docs/lgpe_session.md).
                self.result_clones_at = now + self.args.result_after - 0.5
                self.result_at = now + self.args.result_after
                print(f"[lgh] game: *** COMMIT sent, 2 under step {step} *** the trade is agreed; "
                      "the animation runs on the console now")
            if (self.result_clones_at is not None and not self.result_clones_announced
                    and now >= self.result_clones_at):
                self.result_clones_announced = True
                for cid in (self.commit_clone + 1, self.commit_clone + 2):
                    self.announce_clone(now, cid)
            if self.result_at is not None and now >= self.result_at:
                self.send_result()
            if self.partner is not None:
                self.online_tick(now)

    def online_tick(self, now):
        """The partner's progress: their record answers the console's offer, and the A 2 goes once
        both consoles voted (docs/online.md)."""
        theirs = self.partner.theirs()
        if self.committed:
            return
        msg = self.console_offer
        if (msg is not None and theirs.offer is not None and self.held_vote is None
                and (msg["step"] > self.trade.get("answered_step", 0) or theirs.offer != self.sent_remote)):
            if not pb7.valid(theirs.offer):
                return
            self.trade["answered_step"] = max(self.trade.get("answered_step", 0), msg["step"])
            self.trade["mid_trade"] = TRADE_IN_PROGRESS["offer"] = True
            self.sent_remote = theirs.offer
            step = _send_step(self.trade, self.send, self.offer_kind, theirs.offer)
            self.publish_step()
            print(f"[lgh] offer: *** SENT the partner's {len(theirs.offer)} B step {step} *** "
                  f"(answering the console's step {msg['step']})")
        cid = self.held_vote
        if cid is not None and theirs.accepted and theirs.offer == self.sent_remote:
            self.held_vote = None
            agreed = b"\x01\0\0\0" + b"\x02\0\0\0" * 2
            self.drive += [(now, cid, agreed, 1), (now + self.args.drive_delay, cid, agreed, 2)]
            self.drive.sort(key=lambda step: step[0])
            print(f"[lgh] clone: both consoles confirmed; driving clone {cid} to A 2")

    def announce_clone_0(self, now):
        """Announced with a1 + b1, published only once the joiner answers the pair."""
        c = self.clone
        ms = c.ms(now)
        self.send(c._command(clone.CLOCK_AND_COUNT, 3, 0xFD, 0, now,
                             struct.pack(">IBBH", ms, 1, 0, c.element_ms(now) & 0xFFFF)),
                  clone.PROTOCOL)
        self.send(c._command(clone.CLOCK_AND_PARTICIPANT, 3, 0xFD, 0, now,
                             struct.pack(">II", ms, HOST_BIT | JOINER_BIT)), clone.PROTOCOL)
        print("[lgh] clone: announced clone 0 (a1 + b1)")

    def publish_step(self):
        """Our step counter, at +12 of the clone type 2 data (docs/lgpe_session.md)."""
        for out in self.clone.advance_state(time.monotonic(), self.trade.get("step", 1) & 0xFF):
            self.send(out, clone.PROTOCOL)

    @property
    def offer_kind(self):
        return pb7.OFFER_MESSAGE + 2 * self.round

    @property
    def commit_kind(self):
        return pb7.COMMIT_MESSAGE + 2 * self.round

    @property
    def result_kind(self):
        return pb7.RESULT_MESSAGE + 2 * self.round

    def next_round(self, result_step):
        self.round += 1
        if self.partner is not None:
            self.console_offer = self.sent_remote = self.held_vote = None
        else:
            self.args.offer = self.args.next_offer[self.round - 1]
            show_offer(self.args.offer)
        self.args.received = pokemon_service.trade_path(self.received, self.round + 1)
        self.trade["answered_step"] = result_step
        self.commit_clone = None
        self.committed = self.peer_committed = self.committed_2 = False
        self.commit_2_at = None
        self.result_clones_at = self.result_at = None
        self.result_clones_announced = self.result_sent = False
        self.led = False
        if self.args.lead is not None:
            self.lead_offer_at = time.monotonic() + self.args.lead
        print(f"[lgh] game: round {self.round + 1} ready; offers kind {self.offer_kind}, "
              f"commits kind {self.commit_kind}, party clones "
              f"{2 + self.round * (self.args.party_clones + 1)} and "
              f"{3 + self.round * (self.args.party_clones + 1)}")

    def send_offer(self):
        """Unprompted: a station offers as its own state word reaches 2 (docs/lgpe_session.md)."""
        if not self.args.offer or self.args.offer == "echo":
            print("[lgh] game: no --offer structure to send first")
            return
        raw = Path(self.args.offer).read_bytes()
        if len(raw) != pb7.BOX_SIZE:
            print(f"[lgh] game: {self.args.offer} is {len(raw)} bytes, not {pb7.BOX_SIZE}")
            return
        body = raw if pb7.valid(raw) else pb7.encrypt(raw)
        TRADE_IN_PROGRESS["offer"] = True
        self.led = True
        step = _send_step(self.trade, self.send, self.offer_kind, body)
        print(f"[lgh] offer: *** SENT {len(body)} B step {step} *** {self.args.offer}, unprompted")
        self.publish_step()

    @property
    def offered_clone(self):
        """The last party clone of this round, the one a console host votes on (clones 3 and 6
        on retail, docs/lgpe_session.md)."""
        return (self.round + 1) * (self.args.party_clones + 1)

    def lead_vote(self, now):
        """--lead: the vote a console host's player gives, as the authority walks it: 1 1 1, then
        trailing word 1, then 1 2 2 and trailing word 2 (docs/lgpe_session.md)."""
        cid = self.offered_clone
        ones, agreed = b"\x01\0\0\0" * 3, b"\x01\0\0\0" + b"\x02\0\0\0" * 2
        delay = self.args.drive_delay
        self.drive = [(now, cid, ones, 0), (now + 0.066, cid, ones, 1),
                      (now + delay, cid, agreed, 1), (now + delay + 0.046, cid, agreed, 2)]
        self.lead_commit_clone_at = now + delay + self.args.lead
        print(f"[lgh] lead: voting on clone {cid}")

    def lead_commit_clone(self, now):
        """--lead: the sync save announces the commit clone, votes 1 on it and commits, 152 ms
        from announcement to commit on a retail host (docs/lgpe_session.md)."""
        cid = self.commit_clone = self.offered_clone + 1
        self.announce_clone(now, cid)
        ones = b"\x01\0\0\0" * 3
        self.drive = [(now + 0.086, cid, ones, 0), (now + 0.13, cid, ones, 1)]
        self.lead_commit_at = now + 0.152
        print(f"[lgh] lead: commit clone {cid}")

    def send_result(self):
        """The next offer channel, once after this round's animation (docs/lgpe_session.md)."""
        if self.result_sent or not self.committed_2:
            return
        self.result_sent = True
        if self.partner is not None and self.sent_remote is not None:
            # The next trade's first slot: the record just traded, as a station's own (docs/lgpe_session.md).
            step = _send_step(self.trade, self.send, self.result_kind, self.sent_remote)
            self.publish_step()
            print(f"[lgh] game: *** RESULT sent, step {step} *** the partner's record")
            return
        if not self.args.offer or self.args.offer == "echo":
            print("[lgh] game: no --offer structure to send as the result")
            return
        raw = Path(self.args.offer).read_bytes()
        body = raw if pb7.valid(raw) else pb7.encrypt(raw)
        step = _send_step(self.trade, self.send, self.result_kind, body)
        self.publish_step()
        print(f"[lgh] game: *** RESULT sent, step {step} *** {self.args.offer}")

    def announce_clone(self, now, cid):
        """docs/lgpe_session.md, "The take-over exchange a joiner runs once per clone"."""
        c = self.clone
        c.owned.add(cid)
        content = b"\x01\x28\x08\xab"
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
        # No clone type 2 copy here: a reference host publishes it only answering the peer's
        # re-announcement, with the 0x82 (docs/lgpe_session.md).
        print(f"[lgh] clone: announced clone {cid} on clone types 2, 4 and 1")

    def announce_clone_1(self, now):
        self.announce_clone(now, 1)

    def session_nodes(self):
        """The peer joins the node list at its mesh join, not at association
        (docs/lgpe_session.md)."""
        nodes = [(self.host.our_ip, PIA_PORT, 0)]
        if self.peer_ip and self.joined:
            nodes.append((self.peer_ip, PIA_PORT, 1))
        return tuple(nodes)

    def broadcast_session(self, nodes):
        body = local_host.build_update_session(
            self.session_sequence, self.local_network_id, self.args.variable_id,
            # Little-endian here, big-endian in the message header (tests/test_pia4.py). The game
            # resolves a message's sender to a node through this table.
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
            pass
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
            # Receive before publishing: a copy published before the peer's record lands carries the
            # previous one, and the console never answered it at the commit clone.
            for out in self.clone.receive(pl, now):
                self.send(out, clone.PROTOCOL)
            self.clone_step(pl, now)
        elif protocol == reliable3.PROTOCOL:
            r = reliable3.parse(pl)
            for out in self.window.receive(pl):
                self.send(out, reliable3.PROTOCOL)
            if r and r["size"]:
                self.payloads.append(r["payload"])
                if self.args.capture:
                    name = f"{self.args.capture}.payload{len(self.payloads)}.bin"
                    write_file(name, r["payload"])
                self.game(pb7.parse_message(r["payload"]))

    def game(self, msg):
        if msg is None:
            print("[lgh] game: not a trade message")
            return
        print(f"[lgh] game: kind {msg['kind']} step {msg['step']} body {msg['size']} B")
        if msg["kind"] == pb7.FIRST_MESSAGE and self.args.first and not self.trade.get("first"):
            self.trade["first"] = True
            body = (pb7.build_message(msg["kind"], msg["body"]) if self.args.first == "echo"
                    else Path(self.args.first).read_bytes())
            first = pb7.parse_message(body)
            if first:
                inner = pb7.set_trainer_name(first["body"], self.args.trainer_name)
                if self.args.our_trainer:
                    tid, sid = (int(v, 0) for v in self.args.our_trainer.split(":"))
                    inner = pb7.set_trainer_id(inner, tid, sid)
                body = pb7.build_message(first["kind"], inner)
                first = pb7.parse_message(body)
            self.send(self.window.send(body), reliable3.PROTOCOL)
            self.trade["step"] = 1
            self.publish_step()
            print(f"[lgh] game: *** SENT our identity *** {len(body)} B from {self.args.first}")
            # State 7 leaves for 8 at two first messages counted at obj+0x470 (main 0x34946c); a
            # second of ours tells whether the console's own is one of them.
            if self.args.first_copies > 1:
                self.extra_first = (first["body"] if first else body[16:],
                                    time.monotonic() + 0.3, self.args.first_copies - 1)
            self.party_clones_at = time.monotonic() + self.args.party_clones_delay
        elif msg["kind"] == self.offer_kind and self.led:
            # The answer to our own unprompted offer: kept, never answered, or the two stations
            # answer each other without end.
            self.led = False
            self.trade["answered_step"] = max(self.trade.get("answered_step", 0), msg["step"])
            self.trade["done"] = False
            if pb7.valid(msg["body"]):
                self.trade["peer_offer"] = msg["body"]
                if self.args.received:
                    pokemon_service.save_received("lgpe", self.args.received, msg["body"])
            print(f"[lgh] offer: the peer answered ours under step {msg['step']}")
            if self.args.lead is not None:
                self.lead_vote_at = time.monotonic() + self.args.lead
            self.publish_step()
        elif msg["kind"] == self.offer_kind and self.partner is not None:
            if msg["step"] > self.trade.get("answered_step", 0) and pb7.valid(msg["body"]):
                self.console_offer = msg
                self.trade["peer_offer"] = msg["body"]
                self.trade["done"] = False
                if self.args.received:
                    pokemon_service.save_received("lgpe", self.args.received, msg["body"])
                self.partner.offer(msg["body"])
        elif msg["kind"] == self.offer_kind:
            before = self.trade.get("answered_step", 0)
            _answer_offer(self.args, self.trade, msg, self.send, tag="[lgh]",
                          kind=self.offer_kind)
            if self.round and self.trade.get("answered_step", 0) > before:
                self.trade["done"] = False
            self.publish_step()
        elif msg["kind"] == self.commit_kind:
            # docs/lgpe_session.md, "The game's messages".
            value = int.from_bytes(msg["body"][:4], "little")
            print(f"[lgh] game: the console's commit carries {value}")
            if value == 1:
                self.peer_committed = True
        elif msg["kind"] == self.result_kind:
            if self.trade.get("done"):
                print(f"[lgh] game: kind {self.result_kind} after the completed trade; "
                      "recorded without another completion")
                self.record(rec=f"post_trade_kind{self.result_kind}", step=msg["step"],
                            body=msg["body"].hex(), t=round(self.now(), 3))
                return
            self.trade["done"] = True
            show_done()
            screen.arrived()
            TRADE_IN_PROGRESS["offer"] = TRADE_IN_PROGRESS["commit"] = False
            print("[lgh] game: *** THE RESULT *** the trade has gone through on the console")
            self.send_result()
            if self.partner is not None:
                self.partner.done()
                self.next_round(msg["step"])
            elif self.round < len(self.args.next_offer):
                self.next_round(msg["step"])

    def new_clone(self):
        self.clone = clone.Participant(time.monotonic(), dest=JOINER_BIT, own=HOST_BIT,
                                       station=HOST_INDEX)
        self.clone.host_role = True
        self.clone.ack_peer_clock = True
        self.clone.ack_re_announcement = True
        # Under test: the console never sends the announcer's copy, so publish ours 40 ms after the
        # take-over.
        self.clone.publish_on_announce = True
        self.clone.publish_delay = 0.04
        self.clone.request_publishes_type4 = True
        self.clone.publish_type4 = self.args.type4_data
        # A retail station answers every clone type 2 publish with its own copy, about ten a second
        # for the whole session (docs/lgpe_session.md).
        self.clone.publish_once = False
        self.clone.withhold_announces = self.args.withhold_announce

    def clone_step(self, pl, now):
        kind = pl[1] if len(pl) > 1 else -1
        if kind == clone.PARTICIPATE:
            print("[lgh] clone: the console PARTICIPATED")
        elif kind == clone.COMMAND_ANNOUNCE and not self.clone_1_announced:
            # The console announces clone 1 itself 32 ms after our clone 0 data; no announcement of
            # ours is owed.
            self.clone_1_announced = True
            print("[lgh] clone: the console announced clone 1 first; taking it over")
        elif kind == clone.PARTICIPATE_ACK and self.announce_clone_0_at is None:
            self.announce_clone_0_at = now + 0.03
        elif kind in (clone.CLOCK_AND_COUNT_2, clone.CLOCK_COUNT_PARTICIPANT,
                      clone.CLOCK_COMMAND) and self.clone_0_announced \
                and self.publish_clone_0_at is None:
            # A 0x91 here is what a console gave when the pair reached it before its own a1.
            c = clone.parse_command(pl)
            if c and (c["ctype"], c["station"], c["clone_id"]) == (3, 0xFD, 0) \
                    and self.args.ignore_clone0_answer and self.clone_0_resends == 0:
                # Test only: as if the answers were lost, so the console gets the pair twice.
                print(f"[lgh] clone: ignored the console's {kind:#04x} to the clone 0 pair")
            elif c and (c["ctype"], c["station"], c["clone_id"]) == (3, 0xFD, 0):
                self.publish_clone_0_at = now + 0.03
                print(f"[lgh] clone: the console answered the clone 0 pair with {kind:#04x}")
        elif kind == clone.EXIT_REQUEST:
            print("[lgh] clone: the console left the clone protocol; acknowledged")
        elif kind == clone.COMMAND_END:
            # Under test: the emulated pair released their own copies in answer to each other's.
            c = clone.parse_command(pl)
            if c and c["clone_id"] not in self.released:
                self.released.add(c["clone_id"])
                self.release_at.append((now + 0.03, c["clone_id"]))
        d = clone.parse_data_message(pl)
        # The host moves the offered clone's trailing word to 1; until it does the console holds
        # "communication en cours" (docs/lgpe_session.md).
        if (d and d["type"] == clone.STATE_DATA and d["ctype"] == 2 and d["record"]
                and d["record"].get("data", b"")[:12] == b"\x01\0\0\0" * 3
                and self.clone.tail.get(d["clone_id"]) is None
                and d["clone_id"] not in self.clone.flags):
            ones = b"\x01\0\0\0" * 3
            self.drive = [(now + 0.03, d["clone_id"], ones, 1)]
            offer_clone_start = 2 + self.round * (self.args.party_clones + 1)
            if (self.partner is not None
                    and offer_clone_start <= d["clone_id"] < offer_clone_start + self.args.party_clones):
                # The console's 1 1 1 is its player's confirmation; A 2 waits for the partner's.
                self.held_vote = d["clone_id"]
                self.partner.accept()
            elif offer_clone_start <= d["clone_id"] < offer_clone_start + self.args.party_clones:
                self.drive += [(now + self.args.drive_delay, d["clone_id"],
                                b"\x01\0\0\0" + b"\x02\0\0\0" * 2, 1),
                               (now + 2 * self.args.drive_delay, d["clone_id"],
                                b"\x01\0\0\0" + b"\x02\0\0\0" * 2, 2)]
            else:
                # docs/lgpe_session.md, "The two clone records".
                self.commit_clone = d["clone_id"]
            print(f"[lgh] clone: clone {d['clone_id']} offered on both sides; driving it on")
        # State 2 withdraws a vote (main 0x11b4e0), answered as the authority 0x11b6c0 does.
        # Answering it with the vote agreed held the console and locked the save.
        rec = (d["record"].get("data", b"") if d and d["type"] == clone.STATE_DATA
               and d["ctype"] == 2 and d["record"] else b"")
        cid = d["clone_id"] if rec else None
        if (len(rec) >= 20 and rec[:4] == b"\x02\0\0\0" and cid in self.clone.flags
                and self.withdrawn.get(cid) != rec[8:12] and not self.args.agree_withdrawn_vote):
            agreed = self.clone.type4_data(cid)[:4]
            if rec[4:8] != agreed:
                self.withdrawn[cid] = rec[8:12]
                self.drive = [step for step in self.drive if step[1] != cid]
                votes = bytearray(self.clone.votes.get(cid, bytes(20)))
                votes[8:12] = rec[8:12]  # the joiner's station index is 1
                c = self.clone

                def hold(cid=cid, agreed=agreed, votes=bytes(votes)):
                    c.arg[cid] = agreed
                    c.votes[cid] = votes
                self.drive.append((now + 0.03, cid, self.clone.flags[cid],
                                   (self.clone.tail.get(cid) or 0) + 1, hold))
                self.drive.sort(key=lambda step: step[0])
                if self.partner is not None and self.held_vote == cid:
                    self.held_vote = None
                    self.partner.unaccept()
                print(f"[lgh] clone: the console withdrew its vote {int.from_bytes(rec[4:8], 'little')}"
                      f" on clone {cid} (counter {int.from_bytes(rec[8:12], 'little')}); "
                      f"holding {int.from_bytes(agreed, 'little')}")
        # main 0x11b6c0
        if (len(rec) >= 20 and cid in self.withdrawn and rec[:4] == b"\x01\0\0\0"
                and rec[16:20] == struct.pack("<I", self.clone.tail.get(cid) or 0)
                and rec[4:8] != self.clone.type4_data(cid)[:4]
                and (cid, rec[8:12]) not in self.revoted):
            self.revoted.add((cid, rec[8:12]))
            ours = self.clone.flags[cid]
            vote = b"\x01\0\0\0" + rec[4:8] + struct.pack("<I", int.from_bytes(ours[8:12], "little") + 1)
            c = self.clone
            self.drive = [step for step in self.drive if step[1] != cid]
            self.drive.append((now + 0.03, cid, vote, (self.clone.tail.get(cid) or 0) + 1,
                               lambda cid=cid: c.arg.pop(cid, None)))
            self.drive.sort(key=lambda step: step[0])
            print(f"[lgh] clone: the console voted {int.from_bytes(rec[4:8], 'little')} again on "
                  f"clone {cid}; agreeing")
        # State word 4 is the player leaving (docs/lgpe_session.md). A retail console sends two,
        # argument 0 then 3, each under a fresh counter and each answered.
        if (d and d["type"] == clone.STATE_DATA and d["ctype"] == 2 and d["record"]
                and d["record"].get("data", b"")[:4] == b"\x04\0\0\0"
                and (d["clone_id"], d["record"]["data"][8:12]) not in self.leaving):
            self.leaving.add((d["clone_id"], d["record"]["data"][8:12]))
            self.clone.arg[d["clone_id"]] = d["record"]["data"][4:8]
            self.drive = [step for step in self.drive if step[1] != d["clone_id"]]
            self.drive.append((now + 0.03, d["clone_id"], bytes(12),
                               (self.clone.tail.get(d["clone_id"]) or 0) + 1))
            arg = int.from_bytes(d["record"]["data"][4:8], "little")
            print(f"[lgh] clone: the console's state 4 on clone {d['clone_id']}, argument {arg}; "
                  "acknowledging")
            if self.partner is not None and not self.committed:
                self.held_vote = self.console_offer = None
                self.partner.withdraw()
        # docs/lgpe_session.md: the commit follows the peer's zero first word in one frame.
        if (d and d["type"] == clone.STATE_DATA and d["ctype"] == 2
                and d["clone_id"] == self.commit_clone and d["record"]
                and d["record"].get("data", b"")[:4] == bytes(4)
                and self.clone.tail.get(self.commit_clone) == 1 and not self.committed):
            self.commit(now)
        if d and d["type"] == clone.STATE_ACK and d["clone_id"] == 0 \
                and not self.clone_0_acked:
            self.clone_0_acked = True
            print("[lgh] clone: the console acknowledged our clone 0")

    def commit(self, now):
        """0 in every clone's first word and the kind 3 carrying 1, in one frame."""
        self.committed = True
        self.drive = []
        for cid, flags in list(self.clone.flags.items()):
            self.clone.flags[cid] = bytes(4) + flags[4:12]
        TRADE_IN_PROGRESS["commit"] = True
        self.trade["step"] = self.trade.get("step", 1) + 1
        self.publish_step()
        self.send(self.window.send(pb7.build_message(self.commit_kind, b"\x01\0\0\0",
                                                     step=self.trade["step"])),
                  reliable3.PROTOCOL)
        self.commit_2_at = now + 0.065
        print(f"[lgh] game: *** COMMIT sent, 1 under step {self.trade['step']} ***")

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
            # The console checks the inverse request's connection id against its record of us and
            # drops a zero.
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
            # Unanswered, a console repeats it eight times, then deauthenticates: four seconds of
            # black screen.
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
            self.new_clone()
            print("[lgh] *** THE CONSOLE JOINED THE MESH *** answered its join request; "
                  "starting the clone protocol")
            self.broadcast_mesh()
        elif pl[0] == 0 and len(pl) >= reliable3.HEADER_SIZE:
            # The leave request rides the reliable port and is owed that ack and `08 <host index>`:
            # the leaver's handler 0x591bf4 drops any other index and waits out its 5000 ms
            # (0x589490) before it deauthenticates (docs/lgpe_session.md, A joiner leaving).
            r = reliable3.parse(pl)
            if r and r["size"] and r["payload"][0] == mp.LEAVE_REQUEST and not self.peer_left:
                self.peer_left = True
                TRADE_IN_PROGRESS["offer"] = TRADE_IN_PROGRESS["commit"] = False
                self.send(reliable3.build_ack(r["sequence"] + 1), mp.PROTOCOL, port=1)
                for _ in range(2):
                    self.send(mp.build_leave_response(HOST_INDEX), mp.PROTOCOL,
                              destination=0, kind="leave_response")
                self.peer_location = None
                self.joined = False
                self.broadcast_mesh()
                self.send(bytes([DISCONNECTION_REQUEST]), station9.PROTOCOL, destination=0)
                print(f"[lgh] *** THE CONSOLE LEFT THE MESH *** station {r['payload'][1]}; "
                      "answered its leave request and asked it to disconnect")


if __name__ == "__main__":
    sys.exit(main())
