#!/usr/bin/env python3
"""Host a Legends Arceus local trade network, so the console joins and speaks first.

A console waiting on the trade search screen scans as well as advertising, so it will join a
network carrying Arceus's own title, passphrase, advertisement and link code. A joiner sends the
session protocol's join request before anything else, and that request is the thing this project
cannot synthesise yet: it states the protocol list, the versions and the field layout this Pia band
uses. Hosting is how to read it.

    sudo ./.venv/bin/python bin/pla_host.py --code 00000000 --seconds 240

    (them) Jubilife Village, the trading post, Simona (Trado) -> echanger des pokemon !
           -> local -> the warning -> the SAME eight digits -> wait on the search screen

Every datagram in and out goes to --capture as one JSON line. Inbound packets are authenticated
with the session key derived from our own SSID, and every message inside is printed by protocol id.
`docs/pla.md` has the layouts this decodes.
"""
import argparse
import binascii
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn import pla
from pokeldn.ldn import pia6, pia_connect
from pokeldn.ldn.ldn_mitm_host import IpHostTransport
from pokeldn.ldn.transport import HostTransport, find_ap_phy
from pokeldn.host_support import resolve_keys

# The 6.16-6.30 protocol ids, from docs/pla.md. A name makes a capture readable at a glance.
PROTOCOL_NAMES = {
    0x08: "keep alive", 0x2C: "net", 0x30: "turn", 0x58: "rtt", 0x65: "sync",
    0x68: "unreliable", 0x74: "clone atomic", 0x75: "clone event",
    0x76: "clone broadcast event", 0x77: "clone clock", 0x7B: "voice", 0x7C: "reliable",
    0x80: "broadcast reliable", 0x81: "stream broadcast reliable", 0x98: "session",
    0xA0: "nat traversal result", 0xA4: "monitoring data", 0xAC: "wan nat",
    0xB0: "reckoning 1d", 0xB4: "reckoning 3d",
}

# Whoever is waited on speaks first. At Pia 6.32 the HOST opens the exchange with a Net Protocol
# connection request and the joiner only answers it; `host_pia.build_net_probe` is that move for the
# GBA app. A joiner that gets no 0x11 sends nothing at all and leaves on a timer, which is what both
# an emulated and a retail Arceus do. Net is protocol 0x2C at this band.
# THE DISPATCH KEY IS THE SOURCE VARIABLE ID, NOT THE PROTOCOL. The parser copies the packet's
# source variable id into the message's lookup field and walks the station registry for it; a
# station it has never heard of makes the message unroutable and it is skipped, protocol and all.
# A joiner's registry holds its own station under an id it re-rolls every session, so a host that
# invents a fixed id can never match. Message flag 0x01 at this band is "skip the source variable
# id check", which is what a message sent before the peer knows the sender is for.
ESTABLISHING_FLAGS = pia6.MESSAGE_FLAG_SKIP_SOURCE_CHECK

PROTO_NET = 0x2C
PROTO_RTT = 0x58
PIA_HOST_VAR = 0x00C6
NET_REPEAT_SECONDS = 0.5

SESSION_MESSAGE_NAMES = {
    0: "join request", 1: "join request ack", 2: "join response", 3: "leave request",
    5: "update session", 6: "update session ack", 7: "left station sync",
    8: "left station sync ack", 9: "start host migration", 10: "start host migration ack",
}


def _describe(msg):
    name = PROTOCOL_NAMES.get(msg.protocol, "?")
    extra = ""
    if msg.protocol == 0x98 and msg.payload:
        extra = f" {SESSION_MESSAGE_NAMES.get(msg.payload[0], '?')}({msg.payload[0]})"
    return (f"proto 0x{msg.protocol:02x} {name}{extra} port={msg.port} "
            f"flags=0x{msg.message_flags:02x} len={len(msg.payload)}")


def build_net_probe(keys, our_ip, our_mac, station_ips, seqid, nonce8, max_stations,
                    protocol=PROTO_NET):
    """The host's Net 0x11, in a version-11 packet: dst 0, src the host variable id, packet id 0.

    The body is `pia_connect.build_net_conn_request`, which is the 6.39 layout and the one the GBA
    app's host sends at 6.32. Whether 6.16 to 6.23 lays the station array out the same way is
    unread; the joiner's answer, or its silence, is the measurement.
    """
    body = pia6.build_message(
        pia_connect.build_net_conn_request(seqid, PIA_HOST_VAR, our_mac, keys.network_id,
                                           station_ips, max_stations=max_stations),
        protocol=protocol, port=0, message_flags=ESTABLISHING_FLAGS)
    return pia6.build_packet(keys.session_key, keys.network_id, our_ip, body,
                             dst_var=0, src_var=PIA_HOST_VAR, packet_id=0, nonce8=nonce8)


def build_rtt_probe(keys, our_ip, systime, nonce8, version=5, subject=PIA_HOST_VAR):
    """An RTT type-0 request, the cheapest thing a peer can answer.

    RTT keeps no state, so a reply proves the packet authenticated, the message framing parsed and
    the protocol id reached a registered protocol. Silence to both this and the Net request puts the
    fault below the Net layout. [wiki RTT-Protocol]
    """
    body = bytearray(21)
    body[0] = 0
    body[3] = version & 0xFF
    body[8:16] = (systime & ((1 << 64) - 1)).to_bytes(8, "little")
    body[19:21] = (subject & 0xFFFF).to_bytes(2, "big")
    msg = pia6.build_message(bytes(body), protocol=PROTO_RTT, port=0,
                             message_flags=ESTABLISHING_FLAGS)
    return pia6.build_packet(keys.session_key, keys.network_id, our_ip, msg,
                             dst_var=0, src_var=PIA_HOST_VAR, packet_id=0, nonce8=nonce8)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code", default="00000000", help="the eight digits the player types")
    ap.add_argument("--seconds", type=float, default=240.0, help="how long to hold the network up")
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--channel", type=int, default=None)
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--capture", default=None, help="write every datagram here as JSON lines")
    ap.add_argument("--app-version", type=int, default=0,
                    help="the LDN application version; the console's own is unread")
    ap.add_argument("--ssid", default=None, help="hex, 16 bytes; default lets the LDN layer pick")
    ap.add_argument("--ip-host", action="store_true",
                    help="host over ldn_mitm on the LAN for an emulator; no radio and no root")
    ap.add_argument("--net-protocol", type=lambda v: int(v, 0), default=PROTO_NET,
                    help="the Net protocol id to send the connection request under")
    ap.add_argument("--player-name", default="PkCamp",
                    help="the LDN node name; a retail console publishes its profile name here")
    ap.add_argument("--rtt-probe", action="store_true",
                    help="also send an RTT request, which a peer answers with no state at all")
    ap.add_argument("--rtt-version", type=int, default=5, help="the RTT protocol version byte")
    ap.add_argument("--no-net-probe", action="store_true",
                    help="stay silent after a join, to measure what the joiner does unprompted")
    ap.add_argument("--our-ip", default=None,
                    help="with --ip-host, the address to advertise and serve on")
    args = ap.parse_args()

    if len(args.code) != pla.LINK_CODE_LEN or not args.code.isdigit():
        ap.error(f"--code is {pla.LINK_CODE_LEN} digits")
    if not args.ip_host and os.geteuid() != 0:
        ap.error("hosting over the radio needs root; re-run under sudo, or pass --ip-host")

    phy = None
    if not args.ip_host:
        phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
        if phy is None:
            print("[pla] no AP-capable phy")
            return 1

    app_data = pla.build_advertise_data(args.code)
    print(f"[pla] advertising code {args.code}, {len(app_data)} bytes of application data")

    factory = IpHostTransport if args.ip_host else HostTransport
    transport = factory(
        app_data=app_data, password=pla.PASSPHRASE, nickname=args.player_name,
        keys_path=resolve_keys(args.keys), local_comm_id=pla.COMM_ID, scene_id=pla.SCENE_ID,
        app_version=args.app_version, max_participants=pla.MAX_PARTICIPANTS, phyname=phy,
        channel=args.channel, protocol=pla.LDN_PROTOCOL,
        ssid=binascii.unhexlify(args.ssid) if args.ssid else None,
        **({"mirror_comm_version": True} if args.ip_host else {}),
        **({"our_ip": args.our_ip} if args.ip_host and args.our_ip else {}))

    cap = open(args.capture, "w") if args.capture else None

    def record(**row):
        if cap:
            cap.write(json.dumps(row) + "\n")
            cap.flush()

    try:
        transport.start()
    except RuntimeError as exc:
        print(f"[pla] the network did not come up: {exc}")
        return 2

    keys = pla.session_keys(transport.ssid)
    print(f"[pla] ssid={transport.ssid.hex()} network_id={keys.network_id:#010x} "
          f"us={transport.our_ip}")
    record(rec="host", ssid=transport.ssid.hex(), network_id=keys.network_id,
           our_ip=transport.our_ip, code=args.code, app_data=app_data.hex())

    deadline = time.time() + args.seconds
    seen, authed, failed = 0, 0, 0
    net_seqid, net_sent, answered = 2, {}, set()
    try:
        while time.time() < deadline:
            now = time.time()
            # Open the Net exchange with every station that has joined, and keep repeating it until
            # that station answers. A joiner waiting on this sends nothing before it arrives.
            if not args.no_net_probe:
                for entry in list(transport.participants):
                    ip = entry[1]
                    if ip in answered or ip == transport.our_ip:
                        continue
                    if now - net_sent.get(ip, 0) < NET_REPEAT_SECONDS:
                        continue
                    net_sent[ip] = now
                    net_seqid += 1
                    probe = build_net_probe(keys, transport.our_ip, transport.our_mac,
                                            [transport.our_ip, ip], net_seqid, os.urandom(8),
                                            pla.MAX_PARTICIPANTS, protocol=args.net_protocol)
                    transport.send(probe, ip)
                    record(rec="out", dst=ip, kind="net conn request", seqid=net_seqid,
                           hex=probe.hex(), t=now)
                    print(f"[pla] -> {ip}: net 0x11 connection request on "
                          f"protocol 0x{args.net_protocol:02x}, seqid={net_seqid}")
                    if args.rtt_probe:
                        rtt = build_rtt_probe(keys, transport.our_ip, int(now * 1000) & 0xFFFFFFFF,
                                              os.urandom(8), version=args.rtt_version)
                        transport.send(rtt, ip)
                        record(rec="out", dst=ip, kind="rtt request", hex=rtt.hex(), t=now)
                        print(f"[pla] -> {ip}: rtt request, version {args.rtt_version}")
            transport.wait_readable(0.2)
            for payload, src_ip in transport.recv():
                seen += 1
                record(rec="in", src=src_ip, hex=payload.hex(), t=time.time())
                if not pia6.is_pia6(payload):
                    print(f"[pla] {src_ip}: not a version-11 packet, {payload[:8].hex()}")
                    continue
                header, plain, ids = pia6.parse_packet(keys.session_key, src_ip,
                                                       keys.network_id, payload)
                if plain is None:
                    failed += 1
                    print(f"[pla] {src_ip}: {header!r} DID NOT AUTHENTICATE")
                    continue
                authed += 1
                print(f"[pla] {src_ip}: {header!r} footer={ids}")
                for msg in pia6.parse_messages(plain):
                    print(f"       {_describe(msg)}  {msg.payload.hex()}")
                    record(rec="msg", src=src_ip, protocol=msg.protocol, port=msg.port,
                           flags=msg.message_flags, payload=msg.payload.hex())
                    if msg.protocol == PROTO_NET and len(msg.payload) > 1:
                        if msg.payload[1] == pia_connect.NET_CONN_RESPONSE:
                            answered.add(src_ip)
                            print(f"[pla] {src_ip} answered the connection request; "
                                  f"waiting for its session join")
    except KeyboardInterrupt:
        print("\n[pla] interrupted")
    finally:
        transport.stop()
        if cap:
            cap.close()

    print(f"[pla] {seen} datagram(s) in, {authed} authenticated, {failed} not. "
          f"joins={transport.join_events}")
    if seen and not authed:
        print("[pla] nothing authenticated: the SSID the key came from is the one we advertised, "
              "so a failure here is the header layout or the source address, not the session.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
