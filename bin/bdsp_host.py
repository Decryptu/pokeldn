#!/usr/bin/env python3
"""Host a BDSP Union Room, so a console entering the Union Room joins us instead of opening its own.

A console looks for a room before it opens one (`IlcaNetSessionSetting.matchingMode = Random`).
This advertises one with BDSP's title, passphrase, scene and advertisement, answers the Local,
Station and Mesh handshakes as a retail host does, and speaks the game's room protocol.

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/bdsp_host.py \
        --keys "$HOME/Documents/Switch/23.0.0 keys/prod.keys" --capture scratchpad/bhNN.jsonl

    (them) with the host up: any Pokemon Center -> 2F -> the LEFT attendant -> plain "Oui"

docs/bdsp_session.md, Hosting. Never pass --verbose to a live run; use --capture.
"""
import argparse
import json
import os
import random
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import pathlib

from pokeldn.bdsp import pokemon, room
from pokeldn.bdsp.host import (APP_VERSION, MAX_PARTICIPANTS, SCENE_UNION_ROOM,
                               SCENE_UNION_ROOM_PASSWORD, Advertisement,
                               HostSession, TradePartner)
from pokeldn.bdsp.session import COMM_ID, PASSPHRASE
from pokeldn.host_support import resolve_keys
from pokeldn.ldn.transport import HostTransport, board_radio, find_ap_phy

SHOWN = {"seat", "left", "session_ack", "connection_request", "request_not_ours",
         "connection_acked", "join_request", "join_acked", "mesh_rx", "rx_bad", "their_emote",
         "approach", "approach_result", "talked_to", "their_trainer", "their_poke",
         "their_check_ok", "their_ready_ok", "their_security_state", "trade_complete"}


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=600.0, help="how long to host")
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--capture", default=None, help="every datagram and event, one JSON line each")
    ap.add_argument("--channel", type=int, default=6)
    ap.add_argument("--ldn-protocol", type=int, default=1, choices=(1, 3),
                    help="the LDN protocol the advertisement is encrypted for")
    ap.add_argument("--scene-id", type=lambda s: int(s, 0), default=None,
                    help="default the Union Room's, or the password room's with --password")
    ap.add_argument("--password", default="",
                    help="host the room the player enters with this password, e.g. 00000000")
    ap.add_argument("--app-version", type=int, default=APP_VERSION)
    ap.add_argument("--name", default="PkCamp", help="the player name our side carries")
    ap.add_argument("--language", type=int, default=3, help="3 is French")
    ap.add_argument("--variable-id", type=lambda s: int(s, 0), default=None,
                    help="our Pia variable id; random by default")
    ap.add_argument("--network-id", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--session-param", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--at", default="-10.57,0,6.29,243",
                    help="where our character stands: x,y,z,rot_y (a retail host's own spot)")
    ap.add_argument("--avatar", type=int, default=8)
    ap.add_argument("--state", type=int, default=room.STATE_NONE,
                    help="the OnlineState we report when asked; 4 raises the trade bubble")
    ap.add_argument("--recruiting", type=int, default=0)
    ap.add_argument("--fresh-pid", action="store_true",
                    help="offer it under a new PID and encryption constant, shiny state kept, so a "
                         "save that took it before takes it again")
    ap.add_argument("--offer", metavar="PB8",
                    help="the Pokemon we trade: a complete, legal, encrypted 328-byte PB8 whose PID "
                         "the console's save does not already hold")
    ap.add_argument("--complete-trade", action="store_true",
                    help="answer the ready-ok, after which the console writes its save")
    ap.add_argument("--trainer", default="PkCamp:41234:23117", metavar="NAME:TID:SID",
                    help="our trade trainer record")
    ap.add_argument("--save-theirs", default=None, metavar="PREFIX",
                    help="write each Pokemon the console offers to PREFIX_N.pb8")
    ap.add_argument("--approach-delay", type=float, default=3.0,
                    help="seconds after the player's trade emote before our character walks up")
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--ifname", default="ldn-tap")
    ap.add_argument("--ap-ifname", default="ldn")
    ap.add_argument("--mon-ifname", default="ldn-mon")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    if os.geteuid() != 0 and not board_radio():
        print("[bh] needs the ESP32 board (POKELDN_RADIO) or root"); return 1
    phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
    if phy is None:
        print("[bh] no AP-capable phy"); return 1
    keys_path = resolve_keys(args.keys)
    if not os.path.exists(keys_path):
        print(f"[bh] prod.keys not found at {keys_path!r}"); return 2

    adv = Advertisement(args.network_id if args.network_id is not None else random.getrandbits(32),
                        args.session_param if args.session_param is not None
                        else random.getrandbits(32), args.app_version, args.password)
    if args.scene_id is None:
        args.scene_id = SCENE_UNION_ROOM_PASSWORD if args.password else SCENE_UNION_ROOM
    keys = adv.keys
    variable_id = args.variable_id if args.variable_id is not None else random.getrandbits(32) | 1
    x, y, z, rot = (float(v) for v in args.at.split(","))
    join = room.build_join(x, y, z, rot_y=int(rot), avatar_id=args.avatar)

    cap = open(args.capture, "w") if args.capture else None
    t0 = time.monotonic()

    def record(**kw):
        if cap:
            cap.write(json.dumps(kw, default=str) + "\n")
            cap.flush()
        if kw.get("rec") in SHOWN:
            print(f"[bh] t={kw.get('t', 0):7.2f} {kw['rec']} "
                  + " ".join(f"{k}={v}" for k, v in kw.items() if k not in ("rec", "t", "data")))
        elif kw.get("rec") == "game_message":
            print(f"[bh] t={kw['t']:7.2f} game {kw['via']:10s} {kw['name']} {kw.get('fields') or ''}")

    offer = None
    if args.offer:
        offer = pathlib.Path(args.offer).read_bytes()[:0x148]
        if args.fresh_pid:
            offer = pokemon.fresh(offer)
        o = pokemon.read(offer)
        print(f"[bh] offering species {o['species']} {o['nickname']!r} OT {o['ot_name']!r} "
              f"pid {o['pid']:08x}")
    if args.complete_trade:
        print("[bh] *** --complete-trade: the console WRITES ITS SAVE and the Pokemon the player "
              "picks LEAVES THEIR BOX ***")
    tname, tid, sid = args.trainer.split(":")
    prefix = args.save_theirs or (args.capture.rsplit(".", 1)[0] + "_theirs" if args.capture
                                  else None)

    def save_theirs(n, raw):
        if prefix:
            pathlib.Path(f"{prefix}_{n}.pb8").write_bytes(raw)

    partner = TradePartner(offer, tname, int(tid), int(sid), complete=args.complete_trade,
                           approach_delay=args.approach_delay, state=args.state,
                           recruiting=args.recruiting, save_theirs=save_theirs, record=record)
    on_game = partner.game if offer is not None else None

    host = HostTransport(app_data=adv.application_data, password=PASSPHRASE, nickname=args.name,
                         keys_path=keys_path, local_comm_id=COMM_ID, scene_id=args.scene_id,
                         app_version=args.app_version, max_participants=MAX_PARTICIPANTS,
                         phyname=phy, ifname=args.ifname, ap_ifname=args.ap_ifname,
                         mon_ifname=args.mon_ifname, channel=args.channel,
                         skip_encryption=True, accept_decrypted_ccmp=True,
                         protocol=args.ldn_protocol)
    print(f"[bh] network id {adv.network_id:#010x} session param {adv.session_param:#010x} "
          f"variable id {variable_id:#010x}")
    print(f"[bh] {keys}")
    if not host.start():
        print("[bh] the AP did not come up"); return 3
    record(rec="target", t=0.0, ssid=host.ssid.hex(), our_ip=host.our_ip,
           our_mac=host.our_mac.hex(), application_data=adv.application_data.hex(),
           session_key=keys.session_key.hex(), variable_id=variable_id,
           ldn_protocol=args.ldn_protocol)
    print(f"[bh] *** HOSTING the Union Room: ssid={host.ssid.hex()} channel {args.channel} "
          f"us={host.our_ip} ***")

    session = HostSession(keys, adv, host.our_ip, host.our_mac, variable_id, name=args.name,
                          language=args.language, join=join, on_game=on_game,
                          on_tick=partner.tick if offer is not None else None, record=record,
                          nonce_start=random.getrandbits(48))
    last_status = 0.0
    joins_seen = 0
    try:
        while time.monotonic() - t0 < args.seconds:
            now = time.monotonic() - t0
            out = []
            present = list(host.participants)
            if session.joiner is not None and not any(p[1] == session.joiner.ip for p in present):
                print(f"[bh] t={now:7.2f} the console left its seat")
                session.leave(now)
            # an association can follow a deauthentication inside one pass, and the transport
            # reports a join without a leave; every join event starts the handshake over
            if host.join_events > joins_seen and present:
                joins_seen = host.join_events
                _, ip, mac, _ = present[-1]
                print(f"[bh] t={now:7.2f} *** CONSOLE ASSOCIATED *** ip={ip} mac={bytes(mac).hex()}")
                out += session.seat(ip, mac, now)
            for payload, src_ip in host.recv():
                out += session.receive(payload, src_ip, now)
            out += session.tick(now)
            for pkt, ip in out:
                host.send(pkt, ip)
            if now - last_status >= 10:
                last_status = now
                print(f"[bh] t={now:7.2f} {session.counters}")
            time.sleep(0.005)
    except KeyboardInterrupt:
        print("[bh] interrupted")
    finally:
        host.stop()
        record(rec="end", t=time.monotonic() - t0, counters=session.counters)
        if cap:
            cap.close()
    print(f"[bh] done: {session.counters}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
