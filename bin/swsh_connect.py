#!/usr/bin/env python3
"""Speak version-4 Pia to a Sword/Shield console, from the first packet out to a completed trade.

Never pass --verbose to a live run; use --capture. docs/swsh_session.md, docs/pia.md.
An emulated console hosting over ldn_mitm, with no radio:

    ./.venv/bin/python bin/swsh_connect.py --ip-join --host-ip 127.0.0.2 --our-ip 127.0.0.3 \
        --preset trade --offer-file FILE
"""
from pathlib import Path
import argparse, contextlib, json, math, os, shlex, socket, struct, sys, time, traceback, zlib

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
BUNDLED = os.path.join(PROJECT_ROOT, 'vendor', 'LDN')
if os.path.isdir(BUNDLED):
    sys.path.insert(0, BUNDLED)

import trio, ldn
from pokeldn.host_support import open_output, write_file
from pokeldn import pokemon as pokemon_service
from pokeldn.host_support import resolve_keys, needs_root
from pokeldn.ldn import (broadcast4, ldn_mitm, ldn_mitm_host, local_protocol as lp,
                        mesh_protocol as mesh, pia4, reliable4,
                        reliable5, rtt_protocol as rtt, station4,
                        station_protocol as stp)
from pokeldn.ldn.transport import board_radio, find_ap_phy
from pokeldn.swsh import COMM_ID, PASSPHRASE, PIA_PORT, packet_iv, session_keys
from pokeldn.swsh import trade as swsh_trade
from pokeldn import gen8
from pokeldn.swsh import pokemon as swsh_pokemon
from pokeldn.swsh import trade_payload
from pokeldn.ldn import show_done
from pokeldn.app import screen

# Only a matching search's network takes a seat; its Y-Comm beacon (65535) never reached the trade
# box in 16 of 16 joins [docs/swsh_session.md, How a searching Sword finds a partner].
SCENE_ACCEPTING = 60001


def _expand(spec):
    """"0-15" or "5,1,0" -> a list of strings, so a sweep and a single value are the same flag."""
    out = []
    for part in str(spec).split(","):
        part = part.strip()
        if "-" in part[1:]:
            lo, _, hi = part.partition("-")
            out += [str(v) for v in range(int(lo, 0), int(hi, 0) + 1)]
        elif part:
            out.append(part)
    return out


def cleanup():
    if board_radio():
        return
    import subprocess
    for v in ("ldn", "ldn-mon", "ldn-tap", "ldnclient"):
        subprocess.run(["iw", "dev", v, "del"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_socket(ifname, our_ip=None):
    if our_ip is not None:
        # An emulated host holds UDP *:12345 on this machine: bind our own address [docs/ldn.md].
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((our_ip, PIA_PORT))
        s.setblocking(False)
        return s
    from pokeldn.ldn import userspace_ip  # no kernel interface on the ESP32
    if (user := userspace_ip.udp_socket(ifname, PIA_PORT)) is not None:
        user.setblocking(False)
        return user
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, ifname.encode())
    except PermissionError:
        pass
    except OSError as e:
        raise SystemExit(f"[cx] interface {ifname!r} not found ({e}): with a board set "
                         "POKELDN_RADIO=esp32:PORT; with a Wi-Fi card check NetworkManager "
                         "leaves ldn* unmanaged (docs/hardware_adapters.md)")
    s.bind(("", PIA_PORT))
    s.setblocking(False)
    return s


def wrap(keys, our_mac, our_constant, nonce8, payload, protocol, station, port=0,
         message_flags=pia4.MESSAGE_FLAGS, destination=0):
    """A version-4 packet carrying one message; the station byte goes in the header and the IV.

    `destination` is a station bitmap, not an index: the console addresses seat 1 as 2.
    """
    body = pia4.build_message(payload, protocol=protocol, source=our_constant, port=port,
                              message_flags=message_flags, destination=destination)
    iv = packet_iv(keys, our_mac, nonce8, source_id=station)
    return pia4.build_packet(keys.session_key, iv, body, station=station, nonce8=nonce8)


async def find_radio(args):
    """-> (SessionKeys, target record, seat context) for the matching search on the air, or an exit
    code. The seat yields (host_ip, host_mac, our_ip, our_mac)."""
    keys_file = ldn.load_keys(resolve_keys(args.keys))
    phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
    cleanup()
    want = int(args.comm_id, 16) if args.comm_id else COMM_ID
    net = None
    for _ in range(args.scans):
        nets = await ldn.scan(keys_file, phyname=phy,
                              channels=[int(c) for c in args.channels.split(",")],
                              dwell_time=args.dwell)
        for n in nets:
            print(f"[cx] saw comm_id=0x{n.local_communication_id:016x} ch={n.channel} "
                  f"scene={n.scene_id} {n.num_participants}/{n.max_participants}")
        net = next((n for n in nets if n.local_communication_id == want
                    and n.scene_id == SCENE_ACCEPTING), None)
        if net is not None:
            break
    if net is None:
        print("[cx] no matching search on the air - is the console on Y-Comm -> Link Trade, past BOTH "
              "messages? It stops advertising a minute or so after a seat is released.")
        return 3
    if net.num_participants >= net.max_participants:
        print("[cx] the session is FULL, no seat to take")
        return 5
    keys = session_keys(net)
    print(f"[cx] target ssid={net.ssid.hex()} ch={net.channel} scene={net.scene_id} "
          f"app_version={net.app_version}")
    print(f"[cx] {keys}")

    param = ldn.ConnectNetworkParam()
    param.keys, param.network, param.password = keys_file, net, PASSPHRASE
    param.name, param.app_version = args.name.encode(), net.app_version
    param.phyname, param.ifname = phy, args.ifname
    target = dict(comm_id=net.local_communication_id, channel=net.channel,
                  scene_id=net.scene_id, ssid=net.ssid.hex(),
                  application_data=bytes(getattr(net, "application_data", b"") or b"").hex())

    @contextlib.asynccontextmanager
    async def seat():
        async with ldn.connect(param) as network:
            info = network.info()
            parts = list(getattr(info, "participants", []) or [])
            host = parts[0] if parts else None
            host_ip = getattr(host, "ip_address", None) or "169.254.14.1"
            host_mac = bytes(getattr(host, "mac_address", b"") or b"")
            ours = next((p for p in parts[1:] if getattr(p, "connected", False)), None)
            our_ip = getattr(ours, "ip_address", None) or host_ip.rsplit(".", 1)[0] + ".2"
            our_mac = bytes(getattr(ours, "mac_address", b"") or b"")
            yield host_ip, host_mac, our_ip, our_mac
    return keys, target, seat


class _Advertised:
    """The fields of a scanned network `session_keys` and the target record read."""

    def __init__(self, info):
        self.application_data = bytes(ldn_mitm.advertise_data(info))
        self.local_communication_id, _, self.scene_id = struct.unpack_from("<QHH", info, 0)
        self.num_participants = info[ldn_mitm_host.OFF_NODE_COUNT]
        self.max_participants = info[ldn_mitm_host.OFF_NODE_COUNT_MAX]
        self.app_version = ldn_mitm_host.node_local_comm_version(info, 0)
        self.ssid = ldn_mitm.session_id(info)


def ip_scan_once(scan_ip, host_ip, timeout):
    """-> the emulated host's NetworkInfo, or None. The bridge drops a scan from the host's own
    address, so it leaves from `scan_ip` [docs/ldn.md, Hosting for an emulator]."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as us:
        us.settimeout(timeout)
        us.bind((scan_ip, 0))
        try:
            us.sendto(ldn_mitm.build(ldn_mitm.SCAN), (host_ip, ldn_mitm.PORT))
            while True:
                data, _ = us.recvfrom(4096)
                kind, info = ldn_mitm.parse(data)
                if kind == ldn_mitm.SCAN_RESP:
                    return info
        except (socket.timeout, OSError, ValueError):
            return None


def ip_associate(our_ip, host_ip, our_mac, name, timeout, version):
    """-> (synced NetworkInfo, the TCP connection the seat lasts as long as)."""
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.settimeout(timeout)
    tcp.bind((our_ip, 0))
    tcp.connect((host_ip, ldn_mitm.PORT))
    tcp.sendall(ldn_mitm.build(ldn_mitm.CONNECT,
                               ldn_mitm.build_node_info(our_ip, our_mac, name.encode(),
                                                        version=version)))
    kind, synced = ldn_mitm.parse(tcp.recv(8192))
    if kind != ldn_mitm.SYNC_NETWORK:
        tcp.close()
        raise RuntimeError(f"the host answered our connect with type {kind}, not SyncNetwork")
    tcp.settimeout(None)
    return synced, tcp


async def find_ip(args):
    """`find_radio` against an emulated console hosting over ldn_mitm: no radio, no root, no keys."""
    our_ip = args.our_ip
    if our_ip is None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect((args.host_ip, ldn_mitm.PORT))
            our_ip = probe.getsockname()[0]
    our_mac = b"\x02\x00" + socket.inet_aton(our_ip)
    want = int(args.comm_id, 16) if args.comm_id else COMM_ID
    print(f"[cx] ip-join: host {args.host_ip}, us {our_ip}, comm_id={want:#018x}")
    net = None
    for _ in range(args.scans):
        info = ip_scan_once(args.scan_ip or our_ip, args.host_ip, args.dwell)
        if info is None:
            continue
        n = _Advertised(info)
        print(f"[cx] saw comm_id=0x{n.local_communication_id:016x} scene={n.scene_id} "
              f"{n.num_participants}/{n.max_participants}")
        if n.local_communication_id == want and n.scene_id == SCENE_ACCEPTING:
            net = n
            break
        await trio.sleep(args.dwell)
    if net is None:
        print(f"[cx] no matching search at {args.host_ip} - is the emulated console on Y-Comm -> "
              "Link Trade, past BOTH messages?")
        return 3
    if net.num_participants >= net.max_participants:
        print("[cx] the session is FULL, no seat to take")
        return 5
    synced, tcp = ip_associate(our_ip, args.host_ip, our_mac, args.name, args.dwell * 4,
                               net.app_version)
    net = _Advertised(synced)
    keys = session_keys(net)
    print(f"[cx] target ssid={net.ssid.hex()} scene={net.scene_id} app_version={net.app_version}")
    print(f"[cx] {keys}")
    target = dict(comm_id=net.local_communication_id, channel=None, scene_id=net.scene_id,
                  ssid=net.ssid.hex(), application_data=net.application_data.hex())
    _ip, host_mac, *_ = ldn_mitm_host.read_node(synced, 0)

    @contextlib.asynccontextmanager
    async def seat():
        try:
            yield args.host_ip, bytes(host_mac), our_ip, our_mac
        finally:
            tcp.close()
    return keys, target, seat


async def main_async(args):
    found = await (find_ip if args.ip_join else find_radio)(args)
    if isinstance(found, int):
        return found
    keys, target, seat = found
    cap = open_output(args.capture, "w") if args.capture else None

    def record(**kw):
        if cap:
            cap.write(json.dumps(kw) + "\n")
            cap.flush()

    record(rec="target", **target, session_key=keys.session_key.hex(),
           session_param=keys.session_param)

    async with seat() as (host_ip, host_mac, our_ip, our_mac):
        # Over ldn_mitm the subnet broadcast reaches no emulator: the host is the only peer.
        bcast = host_ip if args.ip_join else our_ip.rsplit(".", 1)[0] + ".255"
        print(f"[cx] *** ASSOCIATED *** us={our_ip} ({our_mac.hex()}) "
              f"host={host_ip} ({host_mac.hex()})")
        if len(our_mac) != 6 or len(host_mac) != 6:
            print("[cx] a MAC is missing - the IV and the constant ids cannot be built")
            return 6
        our_constant = stp.ldn_constant_id(our_mac)
        host_constant = stp.ldn_constant_id(host_mac)
        print(f"[cx] our constant id  {our_constant:#018x}")
        print(f"[cx] host constant id {host_constant:#018x}  (from its MAC)")
        record(rec="seat", us=our_ip, our_mac=our_mac.hex(), host=host_ip,
               host_mac=host_mac.hex(), our_constant=our_constant, host_constant=host_constant)

        sock = make_socket(args.ifname, our_ip if args.ip_join else None)
        t0 = time.monotonic()
        st = {"seq": None, "host_var": None, "host_constant_seen": None, "last_update": None,
              "updates": 0, "phase": "listen", "station": None, "acks": 0,
              "rx": 0, "undecrypted": 0, "other": [], "answer": None, "station_replies": 0,
              "requests": 0, "requests_in": 0, "responses": 0, "their_request": None,
              "our_variable_id": 0, "responses_in": 0, "acks_out": 0,
              "joins_out": 0, "mesh_in": 0, "join_response": None, "mesh_acks": 0,
              "updates_mesh": 0, "rtt_in": 0, "rtt_out": 0, "reliable_in": 0,
              "reliable_last": None, "broadcast_in": 0, "data_out": 0, "data_acked": None,
              "broadcast_ack_ids": set(), "broadcast_stray_ids": set(), "windows": {},
              "their_ack_id": 0, "data_seqs": 0,
              "their_payload": None, "ack_by_proto": {}, "said_by_proto": {},
              "seen_by_proto": {}, "answer_queue": [],
              "snapshot_in": 0, "snapshot_total": None, "snapshot_indexes": set(),
              "snapshot_bodies": {},
              "their_sequence": None, "snapshot_out": 0, "snapshot_acked": None,
              "snapshot_acks_out": 0, "snapshot_rx": broadcast4.Receiver(),
              "snapshot_fragments": 0, "snapshot_done_sent": False, "snapshot_seq": 0,
              "offered_pk8": None, "our_pk8": None, "offer_pending": None, "offer_seq": None,
              "said_by_port": {}, "ack_by_port": {}, "rpc_out": 0, "rpc_acked": None,
              "trade_ready_sent": False, "box_open_sent": False, "pk8_offer_sent": False,
              "our_index": None, "host_index": None, "last_update_mesh": None, "rpc_queue": [],
              "selection_sent": False, "box_queue": [], "box_seen": [], "box_next": 0.0,
              "we_are_host": False, "update_mesh_out": 0,
              "migration_pending": None, "migration_out": 0, "migration_acked": None,
              "host_leaving": None,
              "said_serial": 0, "serial_by_proto": {}, "serial_by_port": {},
              "rpc_seen": {}, "rpc_pair_sent": set(), "offer_status_answered": set(),
              "rpc_bodies_answered": set(), "confirmation_opened": False, "rpc_pair_delta": {},
              "confirm_status_answered": set(),
              "confirm_queue": None,
              "confirm_steps_seen": set(), "confirm_last_step": None,
              "ladder_finished": False, "trades": 0, "first_pk8": None,
              "block_out": 0, "block_acked": None}

        accepted = trio.Event()           # station handshake closed; a mesh join waits for it
        nonce = int.from_bytes(os.urandom(8), "big")

        def run_until(extra=0.0):
            """-> when a sender gives up; --send-seconds 0 keeps it sending until the run ends."""
            return time.monotonic() + args.send_seconds + extra if args.send_seconds else math.inf

        def next_nonce():
            nonlocal nonce
            nonce = (nonce + 1) & ((1 << 64) - 1)
            return nonce.to_bytes(8, "big")

        def open_phase(offset, label):
            """Queue an RPC pair that opens a phase, built from the console's own 40030 envelope.

            Sent on the migration start (the teardown) the pair is never read or acked."""
            if st["selection_sent"]:
                return
            last = st["said_by_port"].get((reliable5.PROTOCOL, args.rpc_port))
            got = swsh_trade.parse_rpc(last) if last else None
            if got is None or got.get("clock") is None:
                print("[tx]     no 40030 pair seen on port 1; cannot build a phase opener")
                return
            clock = got["clock"] + args.rpc_clock_delta
            pair = swsh_trade.build_rpc_pair(offset, our_constant, clock)
            if args.offer_on_50 and st["our_pk8"] is not None:
                # Content 50 ignores a pair with 40030's four-byte bodies; its PK8 rides field 5.
                pair = (pair[0], swsh_trade.build_rpc_pokemon(
                    offset, swsh_trade.RPC_BASES[1], our_constant, clock, st["our_pk8"]))
                print(f"[tx]     the second member carries our PK8 in field "
                      f"{swsh_trade.RPC_POKEMON_FIELD}, {len(pair[1])} bytes")
            st["rpc_queue"].extend(pair)
            st["selection_sent"] = True
            print(f"\n[tx]     *** OPENING THE {label} PHASE *** {40000 + offset} pair on "
                  f"0x7c port {args.rpc_port}, clock {clock}\n"
                  f"[tx]       {pair[0].hex()}\n[tx]       {pair[1].hex()}")


        def validated(raw):
            if getattr(args, "validate_offer", False):
                raw = swsh_pokemon.encrypt(gen8.load(pokemon_service.prepare("swsh", raw)))
            return raw

        def renewed(raw):
            return swsh_pokemon.encrypt(gen8.fresh_identity(gen8.decrypt(raw)))

        def queued_offer(n):
            """-> our record for trade n > 1: the n-th --offer-file, else the last again, else the
            first trade's; one offered again gets a new PID under --fresh-pid."""
            files = args.offer_file
            if n <= len(files):
                return validated(swsh_pokemon.encrypt(gen8.load(Path(files[n - 1]).read_bytes())))
            raw = (swsh_pokemon.encrypt(gen8.load(Path(files[-1]).read_bytes())) if files
                   else st["first_pk8"])
            return validated(renewed(raw) if args.fresh_pid else raw)

        def next_trade():
            """The console offers from its box after a finished ladder: the next trade.

            Contents 50 and 40 and pings 130 and 120 are built anew for every trade; content 30
            and ping 110 last the session (docs/swsh_trade.md, Trades in a row on one session)."""
            n = st["trades"] + 1
            st["our_pk8"] = queued_offer(n)
            for key in ("offered_pk8", "confirm_queue", "confirm_last_step"):
                st[key] = None
            for key in ("pk8_offer_sent", "trade_ready_sent", "ladder_finished",
                        "confirmation_opened", "selection_sent"):
                st[key] = False
            for key in ("offer_status_answered", "confirm_steps_seen", "confirm_status_answered"):
                st[key] = set()
            per_trade = {swsh_trade.RPC_ENVELOPE_BASE + offset
                         for offset in (swsh_trade.SELECTION_OFFSET, swsh_trade.CONFIRMATION_OFFSET)}
            st["rpc_seen"] = {k: v for k, v in st["rpc_seen"].items() if k[0] not in per_trade}
            st["rpc_pair_sent"] -= per_trade
            st["rpc_bodies_answered"] = {k for k in st["rpc_bodies_answered"]
                                         if k[0] not in per_trade}
            for envelope in per_trade:
                st["rpc_pair_delta"].pop(envelope, None)
            ours = swsh_pokemon.read(st["our_pk8"])
            screen.offer("swsh", st["our_pk8"])
            print(f"\n[tx] *** TRADE {n}: THE CONSOLE OFFERS AGAIN *** we offer species "
                  f"{ours['species']} {ours['nickname']!r} level {ours['level']}")
            record(rec="next_trade", trade=n, our_pk8=st["our_pk8"].hex())

        def _opener_for(offset):
            """-> the opener for content `offset`'s 10000-base holder.

            An empty opener is taken as our Pokemon and offers the player an egg (`0x010d81d0`)."""
            if args.open_content_offer and st["our_pk8"] is not None:
                return swsh_trade.pokemon_offer(offset, st["our_pk8"])
            return swsh_trade.open_content(offset)


        def reliable_window(protocol, port, body, now):
            """One version-4 reliable window, keyed by (protocol, port).

            A rejoined stream resumes mid-sequence: the first message carrying FLAG_IS_INITIALIZED
            sets where it starts (`0x01859d20`)."""
            key = (protocol, port)
            w = st["windows"].setdefault(key, {"seqs": set(), "through": None, "acks": 0, "in": 0})
            w["in"] += 1
            try:
                got = reliable4.parse_message(body)
            except ValueError as e:
                print(f"[rx] t={now:6.2f} {protocol:#04x}/{port} {len(body)} B unreadable: {e}")
                return
            st["reliable_last"] = now
            if not (got["flags"] & reliable4.FLAG_APPLICATION_DATA):
                try:
                    shape = [e for e in reliable4.parse_ack_payload(got["payload"])
                             if e["slot"] < 8 and e["ack_id"]]
                except ValueError as e:
                    shape = f"not the version-4 shape: {e}"
                print(f"\n[rx] t={now:6.2f} *** ACK FROM THE CONSOLE on {protocol:#04x}/{port} "
                      f"*** {len(got['payload'])} B, slots 0..7: {shape}")
                record(rec="rx_reliable_ack", t=now, protocol=protocol, port=port,
                       raw=got["payload"].hex())
                for e in (shape if isinstance(shape, list) else []):
                    st["their_ack_id"] = max(st["their_ack_id"], e["ack_id"])
                    st["ack_by_proto"][protocol] = max(st["ack_by_proto"].get(protocol, 0),
                                                       e["ack_id"])
                    # Per port: 0x7C port 1 carries the RPC pair, port 0 the offer; one counter
                    # conflates them.
                    st["ack_by_port"][(protocol, port)] = max(
                        st["ack_by_port"].get((protocol, port), 0), e["ack_id"])
                if (st["data_acked"] is None and st["data_out"]
                        and protocol == args.send_protocol):
                    st["data_acked"] = now
                    print(f"[rx]     *** IT ANSWERED OUR DATA, t={now:.2f} ***")
                return
            # An older resend must not replace the current payload: pingReply (9) arriving after
            # pingSynced (10) stalled the sync.
            if not (w["seqs"] and got["sequence_id"] <= max(w["seqs"])):
                st["their_payload"] = got["payload"]
                st["said_by_proto"][protocol] = got["payload"]
                st["said_by_port"][(protocol, port)] = got["payload"]
            # pingSynced on id 130 is the cue to open the selection phase.
            if args.selection_start and got["payload"] == swsh_trade.sync(
                    130, swsh_trade.PING_SYNCED):
                open_phase(swsh_trade.SELECTION_OFFSET, "SELECTION, ON THE 130 PINGSYNCED")
            # An RPC is a pair, one member per base; keep both. Key on the base field, never
            # payload[5]: that is the inner length and varies with the station-id varint width.
            if protocol == reliable5.PROTOCOL:
                member = swsh_trade.parse_rpc(got["payload"])
                if member is not None and member["base"] in swsh_trade.RPC_BASES:
                    st["rpc_seen"][(member["envelope"], member["base"])] = got["payload"]
                    # --abort-on-stall: any four-byte body on 40040/20000 is a step (`0x006d6490`
                    # drops other lengths); the console repeats its parked step, so only an unseen
                    # body is movement.
                    if (member["envelope"] == (swsh_trade.RPC_ENVELOPE_BASE
                                               + swsh_trade.CONFIRMATION_OFFSET)
                            and member["base"] == swsh_trade.RPC_BASES[1]
                            and len(member["body"]) == 4
                            and bytes(member["body"]) not in st["confirm_steps_seen"]):
                        st["confirm_steps_seen"].add(bytes(member["body"]))
                        st["confirm_last_step"] = now
                        step = swsh_trade.parse_sync_step(member["body"])
                        if step is not None and step[0] >= LADDER_FINAL_PHASE:
                            if not st["ladder_finished"]:
                                st["trades"] += 1
                                show_done()
                                screen.received("swsh", st["offered_pk8"])
                                print(f"\n[rx] *** THE LADDER IS FINISHED - phase {step[0]} is the "
                                      f"teardown rung, THE ABORT STANDS DOWN *** "
                                      f"{member['body'].hex()} at t={now:.2f}")
                            st["ladder_finished"] = True
                    # The confirmation cue (40040/20000, body ending `0100`) needs its own latch.
                    # The answer is a `SyncSaveDataHolder` command (`0x010df6d0`), one per new step
                    # with --confirm-commands; `01000200` is a step that does not end `0100`.
                    answered_confirmation = False
                    if st["confirm_queue"] is None:
                        st["confirm_queue"] = (
                            [int(c, 0) for c in args.confirm_commands.split(",") if c.strip()]
                            if args.confirm_commands
                            else ([args.confirm_command] if args.confirm_command is not None
                                  else []))
                    if (st["confirm_queue"]
                            and member["envelope"] == (swsh_trade.RPC_ENVELOPE_BASE
                                                       + swsh_trade.CONFIRMATION_OFFSET)
                            and member["base"] == swsh_trade.RPC_BASES[1]
                            and len(member["body"]) == 4
                            and (args.confirm_commands
                                 or member["body"][-2:] == b"\x01\x00")
                            and (member["envelope"], member["base"], bytes(member["body"]))
                            not in st["confirm_status_answered"]):
                        st["confirm_status_answered"].add(
                            (member["envelope"], member["base"], bytes(member["body"])))
                        command = st["confirm_queue"].pop(0)
                        answered_confirmation = True
                        st["box_queue"] = st["box_queue"] + [
                            swsh_trade.sync_command(member["offset"], command)]
                        st["box_next"] = 0.0
                        status = swsh_trade.answer_rpc(got["payload"], our_constant,
                                                       args.rpc_clock_delta)
                        if status is not None:
                            st["rpc_queue"] = [status] + st["rpc_queue"]
                        st["rpc_bodies_answered"].add(
                            (member["envelope"], member["base"], bytes(member["body"])))
                        step = swsh_trade.parse_sync_step(member["body"])
                        print(f"[tx]     *** THE CONFIRMATION STATUS *** sending "
                              f"syncCommand{{data:{command}}} on "
                              f"{swsh_trade.CONTENT_BASE_LOW + member['offset']} port 0 and "
                              f"answering the status on port 1, triggered by "
                              f"{got['payload'].hex()}"
                              + (f" (step: phase {step[0]}, announced {step[1]})"
                                 if step else ""))
                    # After the 40050 pair the console sends its PK8, then a status ending `0100`
                    # (not `18fc`): the cue to offer ours on 10050 port 0 and answer the status on
                    # port 1.
                    if (args.selection_offer and not answered_confirmation
                            and member["base"] == swsh_trade.RPC_BASES[1]
                            and member["body"][-2:] == b"\x01\x00" and len(member["body"]) == 4
                            and not st["offer_status_answered"]
                            and st["our_pk8"] is not None):
                        # A hard latch: a set keyed on a parsed field let this fire 48 times in one
                        # run.
                        st["offer_status_answered"].add(True)
                        # `box_queue` drains to port 0, `rpc_queue` to port 1.
                        if args.selection_offer_sweep:
                            # The shapes: swsh_trade.SELECTION_SWEEP_NOTE.
                            st["box_queue"] = (st["box_queue"]
                                               + list(swsh_trade.selection_sweep(
                                                   member["offset"], st["our_pk8"])))
                            st["box_next"] = 0.0
                        elif args.selection_offer_high:
                            st["box_queue"] = st["box_queue"] + [
                                swsh_trade.pokemon_offer_high(member["offset"], st["our_pk8"])]
                            st["box_next"] = 0.0
                        elif args.selection_offer_mirror:
                            clock = (member["clock"] or 0) + args.rpc_clock_delta
                            st["rpc_queue"] = [swsh_trade.mirror_pokemon_offer(
                                member["offset"], clock, st["our_pk8"])] + st["rpc_queue"]
                        elif args.selection_offer_data:
                            # `0x010d5e40` drops a body whose sender resolves to no station
                            # (docs/swsh_protocol.md).
                            clock = (member["clock"] or 0) + args.rpc_clock_delta
                            st["rpc_queue"] = [swsh_trade.build_rpc_pokemon(
                                member["offset"], swsh_trade.RPC_BASES[1], our_constant,
                                clock, st["our_pk8"])] + st["rpc_queue"]
                        else:
                            st["box_queue"] = st["box_queue"] + [
                                swsh_trade.pokemon_offer(member["offset"], st["our_pk8"])]
                            st["box_next"] = 0.0
                        if args.sync_after_offer is not None:
                            # --sync-after-hash cannot fire here: this branch latches the body
                            # first, so queue the opener behind our Pokemon.
                            st["box_queue"] = st["box_queue"] + [
                                swsh_trade.sync(args.sync_after_offer, args.sync_field)]
                            st["box_next"] = 0.0
                            print(f"[tx]     *** SYNC {args.sync_after_offer} FIELD "
                                  f"{args.sync_field} BEHIND OUR OFFER ***")
                        status = swsh_trade.answer_rpc(got["payload"], our_constant,
                                                       args.rpc_clock_delta)
                        if status is not None:
                            st["rpc_queue"] = [status] + st["rpc_queue"]
                        st["rpc_bodies_answered"].add(
                            (member["envelope"], member["base"], bytes(member["body"])))
                        where = (f"as a PokemonTradeDataHolder on "
                                 f"{swsh_trade.RPC_BASES[1] + member['offset']} port 0"
                                 if args.selection_offer_high else
                                 f"as the console's own field set on "
                                 f"{swsh_trade.RPC_ENVELOPE_BASE + member['offset']} port "
                                 f"{args.rpc_port}" if args.selection_offer_mirror else
                                 f"as a Data on {swsh_trade.RPC_ENVELOPE_BASE + member['offset']}"
                                 f" port {args.rpc_port} with our ownerId"
                                 if args.selection_offer_data else
                                 f"on {swsh_trade.CONTENT_BASE_LOW + member['offset']} port 0")
                        print(f"[tx]     *** THE SELECTION OFFER STATUS *** offering our "
                              f"Pokemon {where} and answering the status on port 1, triggered by "
                              f"{got['payload'].hex()}")
                    # Every other distinct body, once; the clock changes per message, so it is not
                    # the key.
                    elif (args.rpc_bodies and member["clock"] is not None
                            and len(member["body"]) == 4):
                        seen_body = (member["envelope"], member["base"],
                                     bytes(member["body"]))
                        if (seen_body not in st["rpc_bodies_answered"]
                                and bytes(member["body"]) not in (b"\x00\x00\x00\x00",
                                                                  b"\x00\x00\x18\xfc")):
                            # The confirmation content stalls at the selection's hash rung and takes
                            # the same re-arm.
                            if (args.confirm_final_delta
                                    and member["envelope"] ==
                                    swsh_trade.RPC_ENVELOPE_BASE
                                    + swsh_trade.CONFIRMATION_OFFSET):
                                st["rpc_pair_sent"].discard(member["envelope"])
                                st["rpc_pair_delta"][member["envelope"]] = \
                                    args.confirm_final_delta
                                print(f"[tx]     *** THE CONFIRMATION HASH - RE-ARMING THE "
                                      f"{member['envelope']} PAIR AT CLOCK "
                                      f"+{args.confirm_final_delta} ***")
                            if (args.selection_final_delta
                                    and member["envelope"] ==
                                    swsh_trade.RPC_ENVELOPE_BASE + swsh_trade.SELECTION_OFFSET):
                                # `--rpc-pair` latches per envelope; the post-hash pair at the
                                # larger delta needs it cleared.
                                st["rpc_pair_sent"].discard(member["envelope"])
                                st["rpc_pair_delta"][member["envelope"]] = \
                                    args.selection_final_delta
                                print(f"[tx]     *** THE HASH - RE-ARMING THE {member['envelope']}"
                                      f" PAIR AT CLOCK +{args.selection_final_delta} ***")
                            # An echo copies the console's own body and cannot move the phase
                            # (`0x006d6490`, `0x006d3260`); --confirm-phase writes the low half.
                            reply = None
                            if (args.confirm_phase is not None
                                    and member["envelope"] == swsh_trade.RPC_ENVELOPE_BASE
                                    + swsh_trade.CONFIRMATION_OFFSET
                                    and member["base"] == swsh_trade.RPC_BASES[1]):
                                reply = swsh_trade.answer_rpc_with_phase(
                                    got["payload"], our_constant, args.confirm_phase,
                                    args.rpc_clock_delta)
                                if reply is not None:
                                    step = swsh_trade.parse_sync_step(member["body"])
                                    print(f"[tx]     *** THE CONFIRMATION PHASE *** answering "
                                          f"{bytes(member['body']).hex()} (phase {step[0]}, "
                                          f"announced {step[1]}) with phase "
                                          f"{args.confirm_phase} instead of echoing it")
                            if reply is None:
                                reply = swsh_trade.answer_rpc(got["payload"], our_constant,
                                                              args.rpc_clock_delta)
                            if reply is not None:
                                st["rpc_bodies_answered"].add(seen_body)
                                st["rpc_queue"] = st["rpc_queue"] + [reply]
                                # The console sends no more 40050 once this lands; the next phase is
                                # opened here.
                                if (args.pair_after_hash is not None
                                        and not st["confirmation_opened"]):
                                    # A phase opens on a pair of RPC members; a bare ping on the
                                    # 10000 base is ignored.
                                    st["confirmation_opened"] = True
                                    clock = (member["clock"] or 0) + args.rpc_clock_delta
                                    pair = swsh_trade.build_rpc_pair(
                                        args.pair_after_hash, our_constant, clock)
                                    st["rpc_queue"] = st["rpc_queue"] + list(pair)
                                    print(f"[tx]     *** OPENING THE {40000 + args.pair_after_hash}"
                                          f" PHASE WITH A PAIR *** {[p.hex() for p in pair]}")
                                elif (args.sync_after_hash is not None
                                        and not st["confirmation_opened"]):
                                    # The console never sends id 120, the confirmation's trigger;
                                    # nothing starts it but this.
                                    st["confirmation_opened"] = True
                                    opener = swsh_trade.sync(args.sync_after_hash,
                                                             args.sync_field)
                                    st["box_queue"] = st["box_queue"] + [opener]
                                    st["box_next"] = 0.0
                                    print(f"[tx]     *** STARTING SYNC {args.sync_after_hash} "
                                          f"AFTER THE HASH *** {opener.hex()}")
                                print(f"[tx]     *** ANSWERING A NEW {member['envelope']} BODY "
                                      f"{bytes(member['body']).hex()} *** {reply.hex()}")
            st["said_serial"] += 1
            st["serial_by_proto"][protocol] = st["said_serial"]
            st["serial_by_port"][(protocol, port)] = st["said_serial"]
            if protocol == mesh.PROTOCOL:
                start = mesh.parse_migration_start(got["payload"])
                if start is not None:
                    print(f"\n[rx] t={now:6.2f} *** THE CONSOLE IS MIGRATING THE MESH TO US *** "
                          f"host {start['host_index']} names station "
                          f"{start['new_host_index']} as the next host")
                    record(rec="rx_migration_start", t=now, **start)
                    if args.box_on_accept:
                        st["box_queue"] = [swsh_trade.box_sync_state(int(c, 0))
                                           for c in args.box_on_accept.split(",")]
                        st["box_next"] = 0.0
                        st["offer_pending"] = None
                        print(f"[tx]     *** ANSWERING THE ACCEPT *** box commands "
                              f"{args.box_on_accept}: "
                              f"{[p.hex() for p in st['box_queue']]}")
                    # MIGRATION_START is never retransmitted; answering it makes the console give up
                    # sooner.
                    if args.send_selection == "migration":
                        open_phase(swsh_trade.SELECTION_OFFSET, "SELECTION")
                    if args.answer_migration and st["migration_pending"] is None:
                        index = st["our_index"]
                        if index is None:
                            index = start["new_host_index"]
                            print("[tx]     no join response gave us an index; using the one the "
                                  "migration start names")
                        # A MIGRATION_RESPONSE goes TO the new host (`0x017c3250`), so the named
                        # host owes a FINISH; 0x48 sent to the console drops the link with
                        # 2-ALZAA-0016.
                        if args.migration_answer == "response" or (
                                args.migration_answer == "auto"
                                and start["new_host_index"] != index):
                            st["migration_pending"] = mesh.build_migration_response(index)
                            print(f"[tx]     *** ANSWERING WITH MIGRATION_RESPONSE *** "
                                  f"{st['migration_pending'].hex()} (our station index {index})")
                        else:
                            st["migration_pending"] = mesh.build_migration_finish(index)
                            st["we_are_host"] = True
                            print(f"[tx]     *** IT NAMED US THE NEXT HOST - SENDING "
                                  f"MIGRATION_FINISH *** {st['migration_pending'].hex()} "
                                  f"(we are station {index} and therefore the host now)")
                finish = mesh.parse_migration_finish(got["payload"])
                if finish is not None:
                    print(f"\n[rx] t={now:6.2f} *** MIGRATION FINISHED *** host "
                          f"{finish['host_index']} flag {finish['flag']}")
                    record(rec="rx_migration_finish", t=now, **finish)
            command = swsh_trade.parse_box_command(got["payload"])
            if command is not None:
                st["box_seen"].append((round(now, 2), command))
                print(f"\n[rx] t={now:6.2f} *** BOX SYNC STATE COMMAND {command} *** on the trade "
                      f"holder - the console naming its own state machine")
                record(rec="rx_box_command", t=now, command=command)
            offered = swsh_trade.offered_pokemon(got["payload"])
            if offered is not None and st["ladder_finished"]:
                next_trade()
            if offered is not None and st["offered_pk8"] is None:
                st["offered_pk8"] = offered
                read = swsh_pokemon.read(offered)
                print(f"\n[rx]     *** THE CONSOLE OFFERED US A POKEMON *** species "
                      f"{read['species']} {read['nickname']!r} level {read['level']} "
                      f"OT {read['ot_name']!r} ({read['trainer_id']}/{read['secret_id']})")
                if args.save_offered:
                    path = pokemon_service.trade_path(args.save_offered, st["trades"] + 1)
                    write_file(path, offered)
                    print(f"[rx]     saved to {path}")
                # One-shot, and it outranks the mirror, which answers the RPC pair the console
                # repeats.
                if args.offer_echo:
                    st["our_pk8"] = offered
                    print("[tx]     *** ECHOING ITS OWN RECORD BACK, unchanged ***")
                if st["our_pk8"] is not None:
                    st["offer_pending"] = swsh_trade.pokemon_trade(st["our_pk8"])
                    st["pk8_offer_sent"] = True
                    ours = swsh_pokemon.read(st["our_pk8"])
                    print(f"[tx]     *** OFFERING species {ours['species']} "
                          f"{ours['nickname']!r} level {ours['level']} BACK ***")
            seen = st["seen_by_proto"].setdefault(protocol, [])
            if got["payload"] not in seen:
                seen.append(got["payload"])
                if args.sync_answers and not swsh_trade.answers_for(got["payload"]):
                    print(f"[rx]     *** NO RULE for {got['payload'].hex()} on {protocol:#04x} "
                          f"- id {swsh_trade.parse(got['payload'])[0] if len(got['payload']) >= 4 else '?'} ***")
            if w["through"] is None:
                w["through"] = got["sequence_id"] - 1
                print(f"\n[rx] t={now:6.2f} {protocol:#04x}/{port} stream opens at seq "
                      f"{got['sequence_id']} stream {got['stream_id']} flags {got['flag_names']} "
                      f"payload {got['payload'].hex()}")
            w["seqs"].add(got["sequence_id"])
            through = reliable5.contiguous_through(w["seqs"], w["through"])
            if through == w["through"]:
                return
            w["through"] = through
            ack = reliable4.build_ack_message(through + 1, stream_id=got["stream_id"],
                                              slots=args.ack_slots,
                                              lowest_pending=args.ack_lowest_pending)
            sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), ack, protocol,
                             args.connect_station_first, port=port,
                             message_flags=reliable5.MESSAGE_FLAGS,
                             destination=args.data_destination),
                        (host_ip, PIA_PORT))
            w["acks"] += 1
            record(rec="tx_reliable_ack", t=now, protocol=protocol, port=port, through=through,
                   ack=ack.hex())
            if w["acks"] <= 3 or w["acks"] % 50 == 0:
                print(f"[tx]     acked {protocol:#04x}/{port} through seq {through} "
                      f"(ack id {through + 1}), {w['acks']} acks on this window")

        async def receiver():
            while True:
                await trio.lowlevel.wait_readable(sock)
                try:
                    data, addr = sock.recvfrom(4096)
                except BlockingIOError:
                    continue
                now = time.monotonic() - t0
                if addr[0] == our_ip:
                    continue                      # our own broadcast, looped back on the tap
                if not pia4.is_pia4(data):
                    record(rec="rx_nonpia", t=now, src=addr[0], data=data[:64].hex())
                    continue
                st["rx"] += 1
                h = pia4.PiaHeader4.parse(data)
                iv = packet_iv(keys, host_mac, h.nonce8, source_id=h.station)
                pt = pia4.decrypt_payload(keys.session_key, iv, pia4.ciphertext(data), h.tag)
                if pt is None:
                    st["undecrypted"] += 1
                    record(rec="rx_undecrypted", t=now, src=addr[0], station=h.station,
                           raw=data[:48].hex())
                    continue
                msgs = pia4.parse_packet(pt)
                record(rec="rx", t=now, src=addr[0], station=h.station, session=h.session_id,
                       phase=st["phase"],
                       msgs=[{k: (sorted(v) if k == "inherited" else
                                  v.hex() if isinstance(v, (bytes, bytearray)) else v)
                              for k, v in m.items()} for m in msgs])
                for f in msgs:
                    body = f["payload"]
                    step = departure_step(body) if (args.leave_with_host and
                                                    f["protocol"] == lp.PROTOCOL) else None
                    if step and step[0] == "ack":
                        station = st["station"] if st["station"] is not None else 0
                        sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), step[1],
                                         lp.PROTOCOL, station),
                                    (host_ip if args.unicast else bcast, PIA_PORT))
                        record(rec="tx_ack", t=now, seq=lp.parse_ack(step[1]), station=station,
                               departure=True)
                    elif step and st["host_leaving"] is None:
                        st["host_leaving"] = now
                        record(rec="leave_with_host", t=now)
                        print(f"\n[rx] t={now:6.2f} *** START_HOST_MIGRATION: THE CONSOLE IS "
                              f"CLOSING ITS NETWORK - LEAVING IT ***")
                    if f["protocol"] == lp.PROTOCOL and len(body) >= 2 \
                            and body[1] == lp.UPDATE_SESSION:
                        us = lp.parse_update_session(body)
                        st["last_update"], st["updates"] = now, st["updates"] + 1
                        st["host_var"] = us.host_variable_id
                        st["host_constant_seen"] = int.from_bytes(us.host_constant_id, "little")
                        if st["seq"] != us.sequence_id:
                            st["seq"] = us.sequence_id
                            seats = ", ".join(f"{n.ip}:{n.port}#{n.ranking}" for n in us.occupied)
                            print(f"[rx] t={now:6.2f} update session seq={us.sequence_id} "
                                  f"host_var={us.host_variable_id:#010x} seats: {seats}")
                    elif f["protocol"] == lp.PROTOCOL:
                        kind = body[1] if len(body) >= 2 else None
                        st["other"].append((now, "local", kind, body.hex()))
                        print(f"[rx] t={now:6.2f} local protocol type {kind:#04x}, "
                              f"{len(body)} B, phase {st['phase']}")
                    elif f["protocol"] == station4.PROTOCOL:
                        kind, result = station4.parse_reply(body)
                        st["station_replies"] += 1
                        st["answer"] = st["answer"] or (now, st["phase"], f["protocol"])
                        st["other"].append((now, "station", kind, body.hex()))
                        verdict = station4.RESULT_NAMES.get(result, result)
                        print(f"\n[rx] t={now:6.2f} *** STATION PROTOCOL 0x14, type {kind}, "
                              f"result {verdict} *** phase {st['phase']}\n     {body.hex()}")
                        if kind == station4.CONNECTION_REQUEST and args.respond:
                            try:
                                got = station4.parse_incoming_request(body)
                            except (IndexError, ValueError) as e:
                                print(f"[rx]     could not parse it: {e}")
                                continue
                            them = got["station"]
                            st["their_request"] = got
                            if st["requests_in"] == 0:
                                print(f"[rx]     it is addressed to our constant "
                                      f"{got['constant_id']:#018x} and our variable "
                                      f"{got['variable_id']:#010x}; its own location says "
                                      f"{them['ip']}:{them['port']} constant "
                                      f"{them['constant_id']:#018x} variable "
                                      f"{them['variable_id']:#010x} nat "
                                      f"{them['nat_flags']}/{them['nat_location']} ack "
                                      f"{got['ack_id']}")
                            st["requests_in"] += 1
                            # Which ids belong in the response is unknown; alternate the two
                            # readings.
                            mine = args.respond_with == "ours" or (
                                args.respond_with == "both" and st["responses"] % 2)
                            cid = our_constant if mine else them["constant_id"]
                            vid = (st["our_variable_id"] if mine else them["variable_id"])
                            reply = station4.build_connection_response(
                                args.respond_result, cid, vid,
                                min_size=station4.ACCEPTED_RESPONSE_SIZE)
                            pkt = wrap(keys, our_mac, our_constant, next_nonce(), reply,
                                       station4.PROTOCOL, args.connect_station_first)
                            sock.sendto(pkt, (addr[0], PIA_PORT))
                            st["responses"] += 1
                            record(rec="tx_response", t=now, ids="ours" if mine else "theirs",
                                   response=reply.hex())
                            print(f"[tx]     answered with result {args.respond_result}, "
                                  f"{'our' if mine else 'their'} ids: {reply.hex()}")
                        elif kind == station4.CONNECTION_RESPONSE and args.respond:
                            # The console repeats its acceptance until acked; the ack's u32
                            # alternates two readings.
                            st["responses_in"] += 1
                            if result == 0 and st["responses_in"] == 1:
                                print(f"[rx]     *** ACCEPTED INTO THE MESH *** {len(body)} B")
                            if result == 0:
                                accepted.set()
                            trailing = station4.ack_id_of(body)
                            theirs = (st["their_request"] or {}).get("station", {}).get(
                                "variable_id", 0)
                            use_trailing = st["acks_out"] % 2 == 0
                            ack_id = trailing if use_trailing else theirs
                            ack = station4.build_ack(ack_id)
                            sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), ack,
                                             station4.PROTOCOL, args.connect_station_first),
                                        (addr[0], PIA_PORT))
                            st["acks_out"] += 1
                            record(rec="tx_station_ack", t=now, ack_id=ack_id,
                                   reading="trailing" if use_trailing else "their_variable_id")
                            if st["acks_out"] <= 4:
                                print(f"[tx]     acked with {ack_id:#010x} "
                                      f"({'the message tail' if use_trailing else 'their variable id'})")
                    elif f["protocol"] == mesh.PROTOCOL and f["port"] == mesh.PORT_RELIABLE:
                        st["mesh_in"] += 1
                        if args.ack_reliable:
                            reliable_window(mesh.PROTOCOL, mesh.PORT_RELIABLE, body, now)
                        else:
                            print(f"\n[rx] t={now:6.2f} *** 0x18 PORT 1 *** {len(body)} B "
                                  f"{body[:32].hex()} - not acked, --ack-reliable is off")
                    elif f["protocol"] == mesh.PROTOCOL:
                        # Version-4 mesh entries are 64 bytes, the index at 0x3E (docs/pia.md).
                        st["mesh_in"] += 1
                        st["answer"] = st["answer"] or (now, st["phase"], f["protocol"])
                        kind, kname = mesh.parse_message(body)
                        st["other"].append((now, "mesh", kind, body.hex()))
                        print(f"\n[rx] t={now:6.2f} *** MESH PROTOCOL 0x18, {kname} *** "
                              f"{len(body)} B, phase {st['phase']}\n     {body[:64].hex()}")
                        if kind == mesh.JOIN_RESPONSE:
                            try:
                                got = mesh.parse_join_response(body, version4=True)
                            except (IndexError, ValueError) as e:
                                print(f"[rx]     could not parse it: {e}")
                                got = None
                            if got and got.get("refused"):
                                print(f"[rx]     REFUSED, reason {got['reason']}")
                            elif got:
                                print(f"[rx]     stations={got['stations']} "
                                      f"host_index={got['host_index']} "
                                      f"our_index={got['our_index']} "
                                      f"fragment {got['fragment_index'] + 1}/{got['fragments']} "
                                      f"counter={got['update_counter']}")
                                for e in got["station_info"]:
                                    loc = e.get("location") or {}
                                    print(f"[rx]       index {e['station_index']}: "
                                          f"{loc.get('private')} constant "
                                          f"{loc.get('constant_id', 0):#018x}")
                                st["our_index"] = got["our_index"]
                                st["host_index"] = got["host_index"]
                            st["join_response"] = st["join_response"] or (now, body.hex())
                            record(rec="rx_join_response", t=now, parsed=got, raw=body.hex())
                        elif kind == mesh.UPDATE_MESH:
                            st["updates_mesh"] += 1
                            # Kept: after a migration we resend the console's own with the host
                            # index changed.
                            st["last_update_mesh"] = body
                            try:
                                got = mesh.parse_update_mesh(body, version4=True)
                            except (IndexError, ValueError) as e:
                                print(f"[rx]     could not parse it: {e}")
                                continue
                            if st["updates_mesh"] == 1:
                                print(f"[rx]     stations={got['stations']} "
                                      f"host_index={got['host_index']} "
                                      f"counter={got['update_counter']} "
                                      f"({len(body)} B; {mesh.UPDATE_MESH_SIZE_V4} is the full "
                                      f"eight seats at version 4)")
                            record(rec="rx_update_mesh", t=now, parsed=got, raw=body.hex())
                        reply = mesh.ack_for(body)
                        if reply and args.join:
                            proto, payload = reply
                            sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), payload,
                                             proto, args.connect_station_first),
                                        (addr[0], PIA_PORT))
                            st["mesh_acks"] += 1
                            record(rec="tx_mesh_ack", t=now, protocol=proto, ack=payload.hex())
                            print(f"[tx]     acked it on {proto:#04x}: {payload.hex()}")
                    elif f["protocol"] == rtt.PROTOCOL and args.answer_rtt:
                        # 0x58 is sixteen bytes at version 4; the answer echoes every byte we do not
                        # read.
                        st["rtt_in"] += 1
                        try:
                            got = rtt.parse_v4(body)
                        except ValueError as e:
                            print(f"[rx] t={now:6.2f} 0x58 {len(body)} B, not the shape read off "
                                  f"the binary: {e}")
                            continue
                        if got["kind"] != rtt.REQUEST:
                            continue
                        reply = rtt.response_for_v4(body)
                        sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), reply,
                                         rtt.PROTOCOL, args.connect_station_first,
                                         message_flags=rtt.MESSAGE_FLAGS,
                                         destination=args.data_destination),
                                    (addr[0], PIA_PORT))
                        st["rtt_out"] += 1
                        record(rec="tx_rtt", t=now, timestamp=got["timestamp"], reply=reply.hex())
                        if st["rtt_out"] <= 3:
                            print(f"[rx] t={now:6.2f} 0x58 RTT request, timestamp "
                                  f"{got['timestamp']:#014x}")
                            print(f"[tx]     answered: {reply.hex()}")
                    elif f["protocol"] == reliable5.PROTOCOL and args.ack_reliable:
                        st["reliable_in"] += 1
                        reliable_window(reliable5.PROTOCOL, f["port"], body, now)
                    elif f["protocol"] == reliable4.BROADCAST_PROTOCOL:
                        # Every 0x80 message is zlib compressed; pia4 has already inflated it
                        # (docs/pia.md).
                        st["broadcast_in"] += 1
                        try:
                            got = reliable4.parse_broadcast_message(body)
                        except ValueError as e:
                            print(f"[rx] t={now:6.2f} 0x80 {len(body)} B unreadable: {e}")
                            continue
                        if st["broadcast_in"] == 1:
                            print(f"\n[rx] t={now:6.2f} *** 0x80 BROADCAST RELIABLE *** "
                                  f"{'ACK' if got['is_ack'] else 'DATA'} seq {got['sequence_id']:#06x} "
                                  f"lowest_pending {got['lowest_pending']} to "
                                  f"{[hex(d) for d in got['destinations']]}")
                            if got["is_ack"]:
                                ents = reliable4.parse_ack_payload(got["payload"])
                                live = [e for e in ents if e["ack_id"]]
                                print(f"[rx]     acking slots "
                                      f"{[e['slot'] for e in live]} at id "
                                      f"{sorted({e['ack_id'] for e in live})}")
                        if got["is_ack"] and len(got["payload"]) == reliable4.ACK_PAYLOAD_SIZE:
                            # Slots 0..7 are the mesh's stations; ack id 1 means nothing received. A
                            # stray byte at slots 18/21/23/31 tracks our own 0x7C ack id and is not
                            # an ack.
                            entries = reliable4.parse_ack_payload(got["payload"])
                            real = {e["ack_id"] for e in entries
                                    if e["slot"] < 8 and e["ack_id"]}
                            stray = {e["ack_id"] for e in entries
                                     if e["slot"] >= 8 and e["ack_id"]}
                            fresh = real - st["broadcast_ack_ids"]
                            st["broadcast_ack_ids"] |= real
                            st["broadcast_stray_ids"] |= stray
                            moved = {i for i in real if i > args.send_sequence}
                            if (moved and st["data_acked"] is None and st["data_out"]
                                    and args.send_protocol == reliable4.BROADCAST_PROTOCOL):
                                st["data_acked"] = now
                                print(f"\n[rx] t={now:6.2f} *** THE BROADCAST WINDOW MOVED: ack "
                                      f"ids {sorted(moved)} in slots 0..7, past our sequence "
                                      f"{args.send_sequence} for the first time ***")
                            elif fresh and st["broadcast_in"] > 1:
                                print(f"[rx] t={now:6.2f} 0x80 ack ids now {sorted(real)}")
                        if got["flags"] & reliable4.FLAG_APPLICATION_DATA and args.ack_reliable:
                            reliable_window(reliable4.BROADCAST_PROTOCOL, f["port"], body, now)
                        record(rec="rx_broadcast", t=now, parsed={
                            k: (v if not isinstance(v, bytes) else v.hex())
                            for k, v in got.items() if k != "payload"})
                    elif f["protocol"] == broadcast4.PROTOCOL:
                        # 0x84: its sequence is echoed in the peer-sequence field of every message
                        # we send.
                        st["snapshot_in"] += 1
                        try:
                            got = broadcast4.parse(body)
                        except ValueError:
                            continue
                        st["their_sequence"] = got["sequence"]
                        if got["is_control"] and st["snapshot_total"] is None:
                            st["snapshot_total"] = got["total"]
                            print(f"\n[rx] t={now:6.2f} *** 0x84 SNAPSHOT INCOMING *** "
                                  f"{got['total']} bytes in chunks of {got['chunk_size']}")
                        if got["is_data"] and got["index"] not in st["snapshot_indexes"]:
                            st["snapshot_indexes"].add(got["index"])
                            st["snapshot_bodies"][got["index"]] = got["body"]
                            print(f"[rx]     fragment {got['index']} of the snapshot, "
                                  f"{len(got['body'])} B on the wire")
                        if got["kind"] == broadcast4.KIND_ACK:
                            if st["snapshot_acked"] is None:
                                st["snapshot_acked"] = now
                                print(f"\n[rx] t={now:6.2f} *** IT ACKED OUR SNAPSHOT: base "
                                      f"{got['base']} mask {got['mask']:#x} *** - the first 0x84 "
                                      f"ack this project has ever been sent")
                                if ((args.box_open or args.open_early)
                                        and not st["box_open_sent"]):
                                    # The game sends command 3 once the trade session is built
                                    # (`0x010c9bb0`); sent after the offers, the console leaves. The
                                    # snapshot ack is the earliest one-shot.
                                    st["box_open_sent"] = True
                                    st["box_queue"] = ([swsh_trade.box_sync_state(int(c, 0))
                                                        for c in (args.box_open or "").split(",")
                                                        if c.strip()]
                                                       + [swsh_trade.open_content(int(c, 0))
                                                          for c in (args.open_early or "").split(",")
                                                          if c.strip()]
                                                       + st["box_queue"])
                                    st["box_next"] = 0.0
                                    print(f"[tx]     *** OPENING WITH box {args.box_open}, "
                                          f"content {args.open_early} *** "
                                          f"{[p.hex() for p in st['box_queue']]}")
                            # When the base reaches every fragment, say so once with 0x19 or it
                            # repeats forever.
                            if (st["snapshot_fragments"]
                                    and got["base"] >= st["snapshot_fragments"]
                                    and not st["snapshot_done_sent"]):
                                st["snapshot_done_sent"] = True
                                done = broadcast4.build_done(st["snapshot_seq"], got["sequence"])
                                sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), done,
                                                 broadcast4.PROTOCOL,
                                                 args.connect_station_first, port=f["port"],
                                                 message_flags=pia4.MESSAGE_FLAGS,
                                                 destination=args.data_destination),
                                            (host_ip, PIA_PORT))
                                print(f"\n[tx] *** IT HAS ALL {got['base']} OF OUR FRAGMENTS - "
                                      f"sending 0x19, the transfer is complete *** {done.hex()}")
                        elif got["kind"] in (broadcast4.KIND_DONE, broadcast4.KIND_DONE_ACK):
                            print(f"[rx] t={now:6.2f} 0x84 kind {got['kind']:#04x} "
                                  f"seq {got['sequence']}")
                        if args.ack_snapshot:
                            # `body` is already inflated by pia4, as for 0x80.
                            for reply in st["snapshot_rx"].feed(body):
                                sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), reply,
                                                 broadcast4.PROTOCOL,
                                                 args.connect_station_first, port=f["port"],
                                                 message_flags=pia4.MESSAGE_FLAGS,
                                                 destination=args.data_destination),
                                            (host_ip, PIA_PORT))
                                st["snapshot_acks_out"] += 1
                                if st["snapshot_acks_out"] <= 4:
                                    print(f"[tx]     acked 0x84 {reply[:16].hex()}")
                    else:
                        st["other"].append((now, "proto", f["protocol"], body.hex()))
                        st["answer"] = st["answer"] or (now, st["phase"], f["protocol"])
                        print(f"\n[rx] t={now:6.2f} *** PROTOCOL {f['protocol']:#04x}, "
                              f"{len(body)} B, phase {st['phase']} *** {body[:32].hex()}")

        async def sender():
            await trio.sleep(args.listen_first)
            if st["seq"] is None:
                print("[cx] no update session seen - the console is not hosting a Pia network. "
                      "Nothing to answer; holding so the capture says so.")
                return
            dst = host_ip if args.unicast else bcast
            stopped = False
            for station in [int(s, 0) for s in args.station_sweep.split(",")]:
                st["phase"], st["station"] = f"ack:station={station}", station
                print(f"\n[tx] acking seq={st['seq'] + args.seq_delta} "
                      f"{'(THE CONTROL: not a sequence the console sent) ' if args.seq_delta else ''}"
                      f"with station byte {station} -> {dst} "
                      f"(the IV's source id follows it)")
                deadline = time.monotonic() + args.ack_seconds
                while time.monotonic() < deadline:
                    payload = lp.build_ack(st["seq"] + args.seq_delta)
                    pkt = wrap(keys, our_mac, our_constant, next_nonce(), payload,
                               lp.PROTOCOL, station)
                    sock.sendto(pkt, (dst, PIA_PORT))
                    st["acks"] += 1
                    record(rec="tx_ack", t=time.monotonic() - t0, seq=st["seq"] + args.seq_delta,
                           station=station, dst=dst, packet=pkt.hex())
                    await trio.sleep(args.period)
                    quiet = time.monotonic() - t0 - (st["last_update"] or 0)
                    if st["updates"] > 3 and quiet > args.quiet_for:
                        print(f"\n[tx] *** THE REBROADCAST STOPPED *** ({quiet:.2f}s quiet, "
                              f"station byte {station}, {st['acks']} acks sent)")
                        st["phase"] = f"stopped:station={station}"
                        stopped = True
                        break
                if stopped:
                    break                 # returning would drop the association
                print(f"[tx] station byte {station}: the rebroadcast did not stop "
                      f"({st['updates']} update sessions so far)")
            if args.connect:
                await connect_sweep(dst)
            st["phase"] = "hold"

        async def connect_sweep(dst):
            """Sweep the target's nat flags [1] and nat location [0x10], unknown before 0x18 speaks.

            A mismatch is silence; a match is the console's first word on 0x14."""
            variable_id = args.src_var if args.src_var is not None else \
                int.from_bytes(os.urandom(4), "big")
            st["our_variable_id"] = variable_id
            location = stp.station_location(our_ip, PIA_PORT, our_constant, variable_id,
                                            stp.ldn_service_variable_id(our_mac))
            target_constant = st["host_constant_seen"] or stp.ldn_constant_id(host_mac)
            target_var = st["host_var"] or 0
            flags = [int(x, 0) for x in _expand(args.nat_flags)]
            locs = [int(x, 0) for x in _expand(args.nat_location)]
            print(f"\n[tx] connection requests on 0x14 -> {host_ip}: target constant "
                  f"{target_constant:#018x} variable {target_var:#010x}, our variable id "
                  f"{variable_id:#010x}")
            print(f"[tx] sweeping platform {args.request_platform} x "
                  f"message flags {args.request_flags} x station "
                  f"{args.connect_station} x nat flags {flags} x nat location {locs}, "
                  f"{args.request_gap:.2f}s apart")
            platforms = [int(x, 0) for x in _expand(args.request_platform)]
            framings = [int(x, 0) for x in _expand(args.request_flags)]
            stations = [int(x, 0) for x in _expand(args.connect_station)]
            for mf in framings:
                for stn in stations:
                    for pf in platforms:
                      for nl in locs:
                        for nf in flags:
                            st["phase"] = (f"connect:platform={pf},msgflags={mf:#04x},"
                                           f"station={stn},nat={nf}/{nl}")
                            payload = station4.build_connection_request(
                                target_constant, target_var, location, nat_flags=nf,
                                nat_location=nl, platform=pf,
                                with_variable_id=not args.no_variable_id)
                            pkt = wrap(keys, our_mac, our_constant, next_nonce(), payload,
                                       station4.PROTOCOL, stn, message_flags=mf)
                            sock.sendto(pkt, (host_ip if args.request_unicast else bcast,
                                              PIA_PORT))
                            st["requests"] += 1
                            record(rec="tx_request", t=time.monotonic() - t0, nat_flags=nf,
                                   nat_location=nl, message_flags=mf, station=stn, platform=pf,
                                   request=payload.hex())
                            await trio.sleep(args.request_gap)
                            if st["station_replies"]:
                                print(f"[tx] a 0x14 reply arrived at platform={pf} "
                                      f"msgflags={mf:#04x} station={stn} nat={nf}/{nl} - stopping "
                                      f"the sweep so the capture is unambiguous")
                                return
            if st["station_replies"]:
                return
            print(f"[tx] {st['requests']} requests, no 0x14 reply. Silence is what a wrong "
                  f"constant id, a wrong count or a malformed location all look like.")

        async def joiner():
            """The six-byte join request, sent only once the console has accepted us on 0x14.

            0x18 answers nothing before that; the response is acked on 0x14 (`0x017c6dd0`)."""
            if not args.join:
                return
            with trio.move_on_after(args.join_wait):
                await accepted.wait()
            if not accepted.is_set():
                print(f"\n[tx] no station acceptance in {args.join_wait:.0f}s - not joining. "
                      f"A join before the handshake closes is silence, and an unclassifiable run.")
                return
            ack_id = args.join_ack_id if args.join_ack_id is not None else \
                int.from_bytes(os.urandom(4), "big")
            payload = mesh.build_join_request(ack_id, station_index=args.join_station_index)
            st["phase"] = "join"
            print(f"\n[tx] *** MESH JOIN on 0x18 *** {payload.hex()} (ack id {ack_id:#010x}, "
                  f"calling ourselves {args.join_station_index}) -> {host_ip}, every "
                  f"{args.join_gap:.2f}s for {args.join_seconds:.0f}s")
            deadline = time.monotonic() + args.join_seconds
            while time.monotonic() < deadline and st["join_response"] is None:
                sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), payload,
                                 mesh.PROTOCOL, args.connect_station_first,
                                 port=args.join_port),
                            (host_ip, PIA_PORT))
                st["joins_out"] += 1
                record(rec="tx_join", t=time.monotonic() - t0, ack_id=ack_id,
                       port=args.join_port, request=payload.hex())
                await trio.sleep(args.join_gap)
            if st["join_response"] is None:
                print(f"[tx] {st['joins_out']} join requests, nothing back on 0x18. "
                      f"{st['mesh_in']} mesh messages in all.")
            st["phase"] = "hold"


        async def data_sender():
            """Application data on 0x7C or 0x80; the first message must carry FLAG_IS_INITIALIZED.

            An unopened stream drops anything without it in silence (`0x01859ca0`, docs/pia.md)."""
            if args.send_data is None:
                return
            payload = bytes.fromhex(args.send_data)
            with trio.move_on_after(args.send_wait):
                await accepted.wait()
            if not accepted.is_set():
                print(f"\n[tx] no station acceptance in {args.send_wait:.0f}s - sending no data. "
                      f"Data before the mesh is up is an unclassifiable run.")
                return
            await trio.sleep(args.send_after)
            want = args.send_destinations
            if want == "auto":
                want = "console" if args.send_protocol == reliable4.BROADCAST_PROTOCOL else "none"
            dests = [host_constant] if want == "console" else []
            body = reliable4.build_data_message(payload, sequence_id=args.send_sequence,
                                                destinations=dests,
                                                stream_id=args.send_stream)
            flags = pia4.MESSAGE_FLAGS
            wire = body
            if args.send_zlib:
                wire = zlib.compress(body)
                flags |= pia4.MESSAGE_FLAG_ZLIB
            st["phase"] = "data"
            print(f"\n[tx] *** APPLICATION DATA on {args.send_protocol:#04x} *** seq "
                  f"{args.send_sequence} flags {reliable5.flag_names(body[0])} to "
                  f"{[hex(d) for d in dests] or 'everyone (count 0)'}, payload {payload.hex()}"
                  f"{f' zlib {len(body)}->{len(wire)} B' if args.send_zlib else ''}")
            print(f"[tx]     the message: {body.hex()}")
            # A stream: one message alone does not hold the console's state.
            deadline = run_until()
            seq = args.send_sequence
            answered_serial = None
            while time.monotonic() < deadline:
                if args.send_count and seq - args.send_sequence >= args.send_count:
                    break
                said = st["said_by_proto"].get(args.send_protocol)
                if (args.answer_once and st["offer_pending"] is None
                        and not st["answer_queue"]):
                    # A repeated answer stalls its phase, so answer each serial once. The guard
                    # clears while a queued answer waits: one rule can be several payloads (`ping`
                    # -> `pingReply`, `ping`).
                    serial = st["serial_by_proto"].get(args.send_protocol)
                    if serial is not None and serial == answered_serial:
                        await trio.sleep(args.send_period)
                        continue
                    answered_serial = serial
                if (st["offer_pending"] is None and st["box_queue"]
                        and time.monotonic() >= st["box_next"]):
                    # Drain here, never in the ack branch: that runs only on a queued payload's ack
                    # and would deadlock.
                    st["offer_pending"] = st["box_queue"].pop(0)
                    st["box_next"] = time.monotonic() + args.box_period
                    print(f"[tx]     *** QUEUED PAYLOAD *** {st['offer_pending'].hex()} "
                          f"({len(st['box_queue'])} left)")
                if st["offer_pending"] is not None:
                    # Sticky until acked: a payload swapped mid-sequence may never arrive whole.
                    payload = st["offer_pending"]
                    st["offer_seq"] = seq
                elif args.sync_answers and said:
                    # `SYNC_ANSWERS` covers four payloads; the mirror stands for the rest.
                    payload, st["answer_queue"] = swsh_trade.next_answer(
                        said, st["answer_queue"], station_id=our_constant,
                        clock_delta=args.rpc_clock_delta, offer_pk8=st["our_pk8"])
                elif args.send_mirror and said:
                    # Mirror per protocol: a shared last payload makes 0x7C echo what 0x80 said, and
                    # the transfer stalls.
                    payload = st["said_by_proto"][args.send_protocol]
                body = reliable4.build_data_message(payload, sequence_id=seq, destinations=dests,
                                                    stream_id=args.send_stream)
                wire = zlib.compress(body) if args.send_zlib else body
                for port in [int(p, 0) for p in _expand(args.send_port)]:
                    sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), wire,
                                     args.send_protocol, args.connect_station_first, port=port,
                                     message_flags=flags, destination=args.data_destination),
                                (host_ip, PIA_PORT))
                    st["data_out"] += 1
                record(rec="tx_data", t=time.monotonic() - t0, protocol=args.send_protocol,
                       sequence=seq, message=body.hex(), payload=payload.hex())
                await trio.sleep(args.send_period)
                if st["ack_by_proto"].get(args.send_protocol, 0) > seq:
                    if st["offer_seq"] == seq:
                        print(f"[tx]     *** OUR OFFER WAS ACKNOWLEDGED at sequence {seq} ***")
                        st["offer_pending"], st["offer_seq"] = None, None
                        if args.send_selection == "offer":
                            # The console goes quiet after acking the offer until the accept; open
                            # the phase now.
                            open_phase(swsh_trade.SELECTION_OFFSET, "SELECTION")
                        if st["box_queue"]:
                            # Built payloads only: a command int raises in the drain and kills the
                            # nursery.
                            pass
                        elif (st["pk8_offer_sent"] and not st["trade_ready_sent"]
                                and (args.open_content or args.box_commands)):
                            # Gate on our Pokemon's ack, not any queued payload's: --box-open queues
                            # one ten seconds earlier.
                            st["trade_ready_sent"] = True
                            # Box commands first: `3e4e000012020801` after our offer makes the
                            # console draw it.
                            st["box_queue"] = (
                                [swsh_trade.box_sync_state(int(c, 0))
                                 for c in (args.box_commands or "").split(",") if c.strip()]
                                + [_opener_for(int(c, 0))
                                   for c in (args.open_content or "").split(",") if c.strip()])
                            print(f"[tx]     *** AFTER THE OFFER: box {args.box_commands}, "
                                  f"open {args.open_content} *** "
                                  f"{[p.hex() for p in st['box_queue']]}")
                            st["box_next"] = 0.0
                        elif (args.trade_ready and st["pk8_offer_sent"]
                                and not st["trade_ready_sent"]):
                            st["trade_ready_sent"] = True
                            # imReady on the trade holder; the console never sends these bytes
                            # itself.
                            st["offer_pending"] = swsh_trade.trade_ready()
                            print(f"[tx]     *** SAYING imReady ON THE TRADE HOLDER *** "
                                  f"{st['offer_pending'].hex()}")
                    seq += 1
                    st["data_seqs"] += 1
                    if st["data_seqs"] <= 3 or st["data_seqs"] % 25 == 0:
                        print(f"[tx]     sequence {seq - 1} acknowledged, sending {seq} "
                              f"({st['data_seqs']} of ours acked)")
            if st["data_acked"] is None:
                print(f"\n[tx] {st['data_out']} data messages out, NOTHING acknowledged them. "
                      f"0x80 ack ids seen: {sorted(st['broadcast_ack_ids'])}")
            st["phase"] = "hold"


        async def snapshot_sender():
            """Send our trade snapshot on 0x84: the console's own, with the identity rewritten.

            The console sends nothing past its own snapshot until it receives one."""
            if args.send_snapshot is None:
                return
            if args.send_snapshot == "live":
                deadline = run_until(args.send_after + args.send_wait)
                wanted = range(trade_payload.FRAGMENT_COUNT)
                while not all(i in st["snapshot_bodies"] for i in wanted):
                    if time.monotonic() > deadline:
                        print("\n[tx] the console never sent its whole snapshot; ours stayed home")
                        return
                    await trio.sleep(0.05)
                payload = trade_payload.reassemble([st["snapshot_bodies"][i] for i in wanted])
                print(f"[tx] the console's own snapshot, {len(payload)} bytes, is ours to rewrite")
            else:
                payload = Path(args.send_snapshot).read_bytes()
            if len(payload) != trade_payload.PAYLOAD_LENGTH:
                payload = trade_payload.inflate_short(payload)
            original_party = payload
            was = trade_payload.read(payload)["trainer_name"]
            # The tail's three ids are not drawn on the trade screen (docs/swsh_protocol.md).
            profile = trade_payload.read_tail(payload)
            theirs = profile["device_id"] + profile["account_uid"] + profile["nsa_id"]
            ids = {}
            if args.snapshot_account:
                ids = {k: bytes(b ^ 0x5A for b in profile[k])
                       for k in ("device_id", "account_uid", "nsa_id")}
            payload = trade_payload.rewrite(payload, trainer_name=args.snapshot_name,
                                            trainer_id=args.snapshot_tid,
                                            secret_id=args.snapshot_sid, **ids)
            payload = original_party[:swsh_pokemon.PARTY_BLOCK] + payload[swsh_pokemon.PARTY_BLOCK:]
            edits = offer_edits(args)
            if args.offer_file:
                if not args.offer_slot:
                    raise ValueError("--offer-file needs --offer-slot")

            if edits or args.offer_file:
                at = (args.offer_slot - 1) * swsh_pokemon.SIZE_PARTY
                if args.offer_file:
                    raw = swsh_pokemon.encrypt(gen8.load(Path(args.offer_file[0]).read_bytes()))
                    print(f"[tx] slot {args.offer_slot} is {args.offer_file[0]}")
                else:
                    raw = original_party[at:at + swsh_pokemon.SIZE_PARTY]
                if struct.unpack_from("<I", raw, 0)[0] == 0:
                    raise ValueError(f"slot {args.offer_slot} of the snapshot is empty")
                built = swsh_pokemon.build_from(raw, **edits) if edits else raw
                payload = payload[:at] + built + payload[at + swsh_pokemon.SIZE_PARTY:]
                before, after = swsh_pokemon.read(raw), swsh_pokemon.read(built)
                print(f"[tx] slot {args.offer_slot} built: species {before['species']} -> "
                      f"{after['species']}, {before['nickname']!r} -> {after['nickname']!r}, "
                      f"OT {before['ot_name']!r} -> {after['ot_name']!r}, "
                      f"IVs {before['ivs']} -> {after['ivs']}")
            fields = trade_payload.read(payload)
            if args.offer_slot:
                at = (args.offer_slot - 1) * swsh_pokemon.SIZE_PARTY
                raw = payload[at:at + swsh_pokemon.SIZE_PARTY]
                if args.fresh_pid and not args.offer_file:
                    raw = renewed(raw)
                raw = validated(raw)
                payload = payload[:at] + raw + payload[at + swsh_pokemon.SIZE_PARTY:]
                st["our_pk8"] = st["first_pk8"] = raw
                screen.offer("swsh", raw)
                ours = swsh_pokemon.read(st["our_pk8"])
                print(f"[tx] we will offer slot {args.offer_slot}: species {ours['species']} "
                      f"{ours['nickname']!r} level {ours['level']}")
                if args.save_offer:
                    write_file(args.save_offer, st['our_pk8'])
                    print(f"[tx]     saved to {args.save_offer}")
            left = payload.count(was.encode("utf-16-le")) if was else 0
            print(f"[tx] the snapshot was {was!r}; {left} copies of that name left in it, "
                  f"and {payload.count(theirs)} of its device, account and service ids "
                  f"{theirs.hex()}")
            print(f"\n[tx] our snapshot: trainer {fields['trainer_name']!r} "
                  f"{fields['trainer_id']}/{fields['secret_id']}, party "
                  f"{[p['nickname'] for p in fields['party'] if p]}, "
                  f"consistent {trade_payload.party_matches_trainer(fields)}")

            deadline = run_until(args.send_after + args.send_wait)
            while st["snapshot_in"] == 0:
                if time.monotonic() > deadline:
                    print("\n[tx] the console never sent its snapshot; ours stayed home")
                    return
                await trio.sleep(0.2)
            print(f"\n[tx] *** SENDING OUR SNAPSHOT on {broadcast4.PROTOCOL:#04x} *** "
                  f"{len(payload)} bytes")
            sender4 = broadcast4.Sender()
            st["snapshot_fragments"] = len(broadcast4.split(payload, sender4.chunk_size))
            while time.monotonic() < deadline:
                if st["snapshot_done_sent"]:
                    # Retransmitting past the 0x19 talks over the answer.
                    print(f"\n[tx] snapshot complete and acknowledged after "
                          f"{st['snapshot_out']} messages; the window is quiet now")
                    return
                if st["their_sequence"] is not None:
                    sender4.saw(st["their_sequence"])
                st["snapshot_seq"] = sender4.sequence
                for message, compressed in sender4.transfer(payload):
                    flags = pia4.MESSAGE_FLAGS | (pia4.MESSAGE_FLAG_ZLIB if compressed else 0)
                    for port in [int(p, 0) for p in _expand(args.snapshot_port)]:
                        sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), message,
                                         broadcast4.PROTOCOL, args.connect_station_first,
                                         port=port, message_flags=flags,
                                         destination=args.data_destination),
                                    (host_ip, PIA_PORT))
                        st["snapshot_out"] += 1
                    record(rec="tx_snapshot", t=time.monotonic() - t0,
                           message=message[:16].hex(), compressed=compressed)
                    await trio.sleep(args.snapshot_period)
                print(f"[tx]     snapshot sent, {st['snapshot_out']} messages out so far")
                await trio.sleep(args.snapshot_repeat)
            print(f"\n[tx] {st['snapshot_out']} snapshot messages out")


        async def rpc_sender():
            """Answer the trade RPC pair on 0x7C port 1, a window of its own; port 0 is not read."""
            if not args.rpc_port_answers:
                return
            port = args.rpc_port
            key = (reliable5.PROTOCOL, port)
            dests = [host_constant] if args.send_destinations != "none" else []
            deadline = run_until(args.send_after + args.send_wait)
            seq = reliable4.FIRST_SEQUENCE
            last_answered = None
            answered_serial = None
            while time.monotonic() < deadline:
                said = st["said_by_port"].get(key)
                # This port has one sequence and one ack counter: a phase opened here goes through
                # rpc_queue, never beside it.
                if args.rpc_pair:
                    for envelope in sorted({e for e, _ in st["rpc_seen"]}):
                        if envelope in st["rpc_pair_sent"]:
                            continue
                        # Not `keys`: that name holds the session crypto in this scope.
                        members = [(envelope, b) for b in swsh_trade.RPC_BASES]
                        if not all(k in st["rpc_seen"] for k in members):
                            continue
                        delta = st["rpc_pair_delta"].get(envelope, args.rpc_clock_delta)
                        both = [swsh_trade.answer_rpc(st["rpc_seen"][k], our_constant, delta)
                                for k in members]
                        if all(b is not None for b in both):
                            st["rpc_pair_sent"].add(envelope)
                            queued = list(both)
                            print(f"[tx]     *** ANSWERING THE {envelope} PAIR, BOTH MEMBERS *** "
                                  f"{[b.hex() for b in both]}")
                            if args.rpc_pair_advance:
                                # A repeated clock is a repeated state (`0x006d59f0`); the console's
                                # own pair goes out three times, clock +2 per burst.
                                again = [swsh_trade.answer_rpc(
                                    st["rpc_seen"][k], our_constant,
                                    args.rpc_clock_delta + args.rpc_pair_advance)
                                    for k in members]
                                if all(a is not None for a in again):
                                    queued += list(again)
                                    print(f"[tx]     *** AND THE {envelope} PAIR AGAIN AT CLOCK "
                                          f"+{args.rpc_pair_advance} *** "
                                          f"{[a.hex() for a in again]}")
                            st["rpc_queue"] = queued + st["rpc_queue"]
                pending = st["rpc_queue"][0] if st["rpc_queue"] else None
                answer = pending if pending is not None else (
                    swsh_trade.answer_rpc(said, our_constant, args.rpc_clock_delta)
                    if said else None)
                if answer is None:
                    await trio.sleep(0.1)
                    continue
                if args.rpc_pair and pending is None and st["rpc_pair_sent"]:
                    # Every phase seen is answered; more is a flood. A new envelope re-arms the
                    # branch above.
                    await trio.sleep(args.rpc_period)
                    continue
                if args.answer_once and pending is None:
                    serial = st["serial_by_port"].get(key)
                    if serial is not None and serial == answered_serial:
                        await trio.sleep(args.rpc_period)
                        continue
                    answered_serial = serial
                if answer != last_answered:
                    last_answered = answer
                body = reliable4.build_data_message(answer, sequence_id=seq, destinations=dests,
                                                   stream_id=args.send_stream)
                sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), body,
                                 reliable5.PROTOCOL, args.connect_station_first, port=port,
                                 message_flags=pia4.MESSAGE_FLAGS,
                                 destination=args.data_destination),
                            (host_ip, PIA_PORT))
                st["rpc_out"] += 1
                if st["rpc_out"] == 1:
                    print(f"\n[tx] *** ANSWERING THE TRADE RPC on 0x7c port {port} *** "
                          f"{answer.hex()}")
                record(rec="tx_rpc", t=time.monotonic() - t0, port=port, sequence=seq,
                       payload=answer.hex())
                await trio.sleep(args.rpc_period)
                if st["ack_by_port"].get(key, 0) > seq:
                    if pending is not None and st["rpc_queue"] and st["rpc_queue"][0] is pending:
                        st["rpc_queue"].pop(0)
                    if st["rpc_acked"] is None:
                        st["rpc_acked"] = time.monotonic() - t0
                        print(f"\n[rx] *** THE CONSOLE ACKED OUR RPC on port {port} *** "
                              f"sequence {seq}")
                    seq += 1
            print(f"\n[tx] {st['rpc_out']} RPC answers out on port {port}, "
                  f"{'acknowledged' if st['rpc_acked'] else 'NOTHING acknowledged them'}")


        async def migration_sender():
            """Answer MIGRATION_START on 0x18 port 1, a window of its own, until the console acks.

            After `440001` the console goes silent on every window and waits for this message."""
            if not args.answer_migration:
                return
            key = (mesh.PROTOCOL, mesh.PORT_RELIABLE)
            dests = [host_constant] if args.send_destinations != "none" else []
            deadline = run_until(args.send_after + args.send_wait)
            seq = reliable4.FIRST_SEQUENCE
            while time.monotonic() < deadline:
                payload = st["migration_pending"]
                if payload is None:
                    await trio.sleep(0.1)
                    continue
                body = reliable4.build_data_message(payload, sequence_id=seq, destinations=dests,
                                                   stream_id=args.send_stream)
                sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), body,
                                 mesh.PROTOCOL, args.connect_station_first,
                                 port=mesh.PORT_RELIABLE, message_flags=pia4.MESSAGE_FLAGS,
                                 destination=args.data_destination),
                            (host_ip, PIA_PORT))
                st["migration_out"] += 1
                if st["migration_out"] == 1:
                    print(f"\n[tx] *** MIGRATION_RESPONSE on 0x18 port {mesh.PORT_RELIABLE} *** "
                          f"seq {seq}: {body.hex()}")
                record(rec="tx_migration", t=time.monotonic() - t0, sequence=seq,
                       payload=payload.hex())
                await trio.sleep(args.migration_period)
                if st["ack_by_port"].get(key, 0) > seq:
                    if st["migration_acked"] is None:
                        st["migration_acked"] = time.monotonic() - t0
                        print(f"\n[rx] *** IT ACKED OUR MIGRATION RESPONSE, "
                              f"t={st['migration_acked']:.2f} ***")
                    # One message: a state transition repeated past its ack stalls the phase.
                    st["migration_pending"] = None
                    return
            if st["migration_out"] and st["migration_acked"] is None:
                print(f"\n[tx] {st['migration_out']} migration responses out, nothing acked them")


        async def update_mesh_sender():
            """Once we are the host, rebroadcast the console's last UPDATE_MESH under our index.

            Without it the link drops about 1.3 s after the console hands the host role over."""
            if not args.update_mesh:
                return
            deadline = run_until(args.send_after + args.send_wait)
            counter = None
            while time.monotonic() < deadline:
                if not (st["we_are_host"] and st["last_update_mesh"] and st["our_index"] is not None):
                    await trio.sleep(0.1)
                    continue
                if counter is None:
                    try:
                        counter = mesh.parse_update_mesh(st["last_update_mesh"],
                                                         version4=True)["update_counter"]
                    except (IndexError, ValueError) as e:
                        print(f"[tx] cannot read the console's update mesh: {e}")
                        return
                counter += 1
                body = mesh.rewrite_update_mesh(st["last_update_mesh"], st["our_index"], counter)
                sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), body,
                                 mesh.PROTOCOL, args.connect_station_first, port=0,
                                 message_flags=pia4.MESSAGE_FLAGS,
                                 destination=args.data_destination),
                            (host_ip, PIA_PORT))
                st["update_mesh_out"] += 1
                if st["update_mesh_out"] == 1:
                    print(f"\n[tx] *** WE ARE THE HOST NOW - UPDATE_MESH on 0x18 port 0 *** "
                          f"{len(body)} B, host index {st['our_index']}, counter {counter}")
                record(rec="tx_update_mesh", t=time.monotonic() - t0, counter=counter,
                       raw=body.hex())
                await trio.sleep(args.update_mesh_period)


        async def block_sender():
            """The second stream: `imReady` (`60ea000012020801`) on the broadcast window.

            docs/swsh_session.md."""
            if args.send2_data is None:
                return
            payload = bytes.fromhex(args.send2_data)
            trigger = bytes.fromhex(args.send2_trigger) if args.send2_trigger else None
            deadline = run_until(args.send_after + args.send_wait)
            while trigger is not None:
                if st["said_by_proto"].get(args.send2_protocol) == trigger:
                    print(f"\n[tx] the console said {trigger.hex()} on "
                          f"{args.send2_protocol:#04x} - answering it")
                    break
                if time.monotonic() > deadline:
                    print(f"\n[tx] it never said {trigger.hex()} on {args.send2_protocol:#04x}; "
                          f"nothing sent on that window")
                    return
                await trio.sleep(0.2)
            dests = [host_constant] if args.send_destinations != "none" else []
            seq = reliable4.FIRST_SEQUENCE
            while time.monotonic() < deadline:
                if seq - reliable4.FIRST_SEQUENCE >= args.send2_count:
                    break
                body = reliable4.build_data_message(payload, sequence_id=seq, destinations=dests)
                sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), body,
                                 args.send2_protocol, args.connect_station_first,
                                 port=args.send2_port, message_flags=pia4.MESSAGE_FLAGS,
                                 destination=args.data_destination),
                            (host_ip, PIA_PORT))
                st["block_out"] += 1
                record(rec="tx_block", t=time.monotonic() - t0, protocol=args.send2_protocol,
                       sequence=seq, message=body.hex(), payload=payload.hex())
                if st["block_out"] == 1:
                    print(f"[tx] *** {payload.hex()} on {args.send2_protocol:#04x} *** "
                          f"seq {seq}: {body.hex()}")
                await trio.sleep(args.send_period)
                if st["ack_by_proto"].get(args.send2_protocol, 0) > seq:
                    if st["block_acked"] is None:
                        st["block_acked"] = time.monotonic() - t0
                        print(f"\n[rx] *** IT ACKNOWLEDGED THAT TOO, t={st['block_acked']:.2f} ***")
                    seq += 1
            if st["block_acked"] is None and st["block_out"]:
                print(f"\n[tx] {st['block_out']} out on {args.send2_protocol:#04x}, not acked")

        def mid_trade():
            """The console has offered and the ladder has not finished: leaving now fails it."""
            return st["offered_pk8"] is not None and not st["ladder_finished"]

        async def guarded(name, task):
            """Run one sender; an exception reaching the nursery would stop sending mid-trade."""
            try:
                await task()
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                print(f"\n[tx] *** {name} DIED: {exc!r} *** the run continues without it")

        async with trio.open_nursery() as nursery:
            nursery.start_soon(receiver)
            nursery.start_soon(guarded, "joiner", joiner)
            nursery.start_soon(guarded, "data_sender", data_sender)
            nursery.start_soon(guarded, "block_sender", block_sender)
            nursery.start_soon(guarded, "snapshot_sender", snapshot_sender)
            nursery.start_soon(guarded, "rpc_sender", rpc_sender)
            nursery.start_soon(guarded, "migration_sender", migration_sender)
            nursery.start_soon(guarded, "update_mesh_sender", update_mesh_sender)
            await sender()
            # Drop the link on a stall: one held through a stalled ladder becomes a failed trade and
            # an hour's lockout; a dropped link is a plain communication error.
            hold_until = time.monotonic() + args.hold
            while (time.monotonic() < hold_until
                   or mid_trade() and time.monotonic() < hold_until + args.grace):
                await trio.sleep(0.25)
                if st["host_leaving"] is not None:
                    break
                if stall_abort(st["confirm_last_step"], time.monotonic() - t0,
                               args.abort_on_stall, st["ladder_finished"]):
                    print(f"\n[tx] *** THE LADDER STALLED FOR {args.abort_on_stall:.1f} s - "
                          f"ABORTING SO THE CONSOLE SEES A DROPPED LINK, NOT A FAILED TRADE *** "
                          f"last step at t={st['confirm_last_step']:.2f}, "
                          f"{len(st['confirm_steps_seen'])} distinct steps")
                    break
            nursery.cancel_scope.cancel()
        # Closed before the network is released.
        sock.close()

        windows = " / ".join(
            f"{p:#04x}:{port} {w['in']} in {w['acks']} acked through {w['through']}"
            for (p, port), w in sorted(st["windows"].items())) or "no reliable window opened"
        answered = ("NOT acknowledged" if st["data_acked"] is None
                    else f"acknowledged at t={st['data_acked']:.2f}")
        print(f"\n[cx] === {st['rx']} packets in, {st['undecrypted']} that did not decrypt, "
              f"{st['updates']} update sessions, {st['acks']} acks out, "
              f"{st['requests']} connection requests, {st['station_replies']} messages on 0x14, "
              f"{st['requests_in']} of them requests, {st['responses_in']} connection responses "
              f"in, {st['responses']} responses out, {st['acks_out']} station acks out, "
              f"{st['joins_out']} join requests out, {st['mesh_in']} messages on 0x18, "
              f"{st['mesh_acks']} mesh acks out, {st['rtt_in']} RTT in / {st['rtt_out']} answered, "
              f"{st['reliable_in']} reliable in, {windows}, {st['broadcast_in']} on 0x80, "
              f"{st['data_out']} application data out over {st['data_seqs'] + 1} "
              f"sequence ids, {answered}")
        if st["answer"]:
            now, phase, proto = st["answer"]
            print(f"[cx] FIRST TRAFFIC ON A NEW PROTOCOL: {proto:#04x} at t={now:.2f} in {phase}")
        record(rec="end", updates=st["updates"], acks=st["acks"], rx=st["rx"],
               undecrypted=st["undecrypted"], phase=st["phase"], answer=st["answer"],
               requests=st["requests"], station_replies=st["station_replies"],
               requests_in=st["requests_in"], responses=st["responses"],
               responses_in=st["responses_in"], acks_out=st["acks_out"],
               joins_out=st["joins_out"], mesh_in=st["mesh_in"],
               mesh_acks=st["mesh_acks"], join_response=st["join_response"],
               rtt_in=st["rtt_in"], rtt_out=st["rtt_out"], reliable_in=st["reliable_in"],
               windows={f"{p:#04x}:{port}": {"in": w["in"], "acks": w["acks"],
                                              "through": w["through"],
                                              "seqs": sorted(w["seqs"])}
                        for (p, port), w in st["windows"].items()},
               broadcast_in=st["broadcast_in"], data_out=st["data_out"],
               data_acked=st["data_acked"], data_seqs=st["data_seqs"],
               block_out=st["block_out"], block_acked=st["block_acked"],
               their_ack_id=st["their_ack_id"],
               broadcast_ack_ids=sorted(st["broadcast_ack_ids"]),
               broadcast_stray_ids=sorted(st["broadcast_stray_ids"]))
    if cap:
        cap.close()
    return 0


LADDER_FINAL_PHASE = 4        # `0x010dbf40`: phase 4 -> state 13 -> 14, the teardown, no send


def departure_step(body):
    """What a hosting Sword's leave owes its client, from one Local Protocol message: ("ack", payload)
    for an update session carrying the host-migration state, ("leave", None) for
    START_HOST_MIGRATION, else None. Each waits up to 10 s unanswered (docs/swsh_session.md,
    Leaving)."""
    try:
        kind, _size = lp.parse_header(body)
        if kind == lp.START_HOST_MIGRATION:
            return ("leave", None)
        if kind == lp.UPDATE_SESSION:
            us = lp.parse_update_session(body)
            if us.host_migration_state:
                return ("ack", lp.build_ack(us.sequence_id))
    except ValueError:
        pass
    return None


def stall_abort(last_step, now, limit, final_phase_seen=False):
    """Has the confirmation ladder started and then gone quiet for `limit` seconds?

    A ladder that reached `LADDER_FINAL_PHASE` is finished and silent, never stalled."""
    if not limit or last_step is None or final_phase_seen:
        return False
    return (now - last_step) >= limit


def offer_edits(args):
    """-> the fields to write into the offered party record, or `{}`.

    Parsed before the radio starts, so a bad nickname or a missing slot fails early."""
    edits = {k: v for k, v in (("species", args.offer_species),
                               ("ability", args.offer_ability),
                               ("level", args.offer_level),
                               ("experience", args.offer_experience),
                               ("nickname", args.offer_nickname),
                               ("ot_name", args.offer_ot)) if v is not None}
    for key in ("nickname", "ot_name"):
        if key in edits and len(edits[key].encode("utf-16-le")) + 2 > gen8.NAME_LENGTH:
            raise ValueError(f"{edits[key]!r} is too long for a {gen8.NAME_LENGTH}-byte name")
    if args.offer_ivs is not None:
        ivs = [int(x, 0) for x in args.offer_ivs.split(",")]
        if len(ivs) != 6 or not all(0 <= iv <= 31 for iv in ivs):
            raise ValueError(f"--offer-ivs wants six values 0..31, got {args.offer_ivs!r}")
        edits["ivs"] = ivs
    if args.offer_level is not None and not 1 <= args.offer_level <= 100:
        raise ValueError(f"--offer-level wants 1..100, got {args.offer_level}")
    if args.offer_moves is not None:
        moves = [int(x, 0) for x in args.offer_moves.split(",")]
        if len(moves) != 4 or not all(0 <= m <= 0xFFFF for m in moves):
            raise ValueError(f"--offer-moves wants four move ids, got {args.offer_moves!r}")
        edits["moves"] = moves
    if edits and not args.offer_slot:
        raise ValueError("--offer-species, --offer-ability, --offer-level, --offer-experience, "
                         "--offer-moves, --offer-nickname, --offer-ot and --offer-ivs edit the "
                         "record in --offer-slot, and no slot was named")
    return edits


# The flags that completed a retail trade (docs/swsh_trade.md); later flags override them.
_TRANSPORT = (
    "--channels 1,6,11 --dwell 2.5 --listen-first 6 --station-sweep 0 --ack-seconds 12 --connect "
    "--no-variable-id --request-platform 9 --request-flags 0x09 --connect-station 0 --nat-flags 0 "
    "--nat-location 0 --respond --respond-with theirs --join --answer-rtt --ack-reliable "
    "--send-data 610000000a00 --sync-answers --send-protocol 0x7c --send-after 4 --send-count 1200 "
    "--send-period 0.3 --send-seconds 350 --send2-data 60ea000012020801 "
    "--send2-trigger 60ea000012020801 --send2-protocol 0x80 --ack-snapshot")
PRESETS = {
    "capture": _TRANSPORT + " --hold 90",
    "trade": (_TRANSPORT + " --snapshot-port 1 --rpc-port-answers --rpc-pair --rpc-bodies "
              "--selection-final-delta 9 --selection-offer --offer-slot 1 --offer-nickname POKELDN "
              "--open-content 30,50 --open-content-offer --box-commands 1 --box-on-accept 4 "
              "--box-period 0.35 --confirm-commands 0,1,2,3,0,1,2,3,0,1,2,3 "
              "--confirm-final-delta 9 --abort-on-stall 15 --hold 240 --send-seconds 0 "
              "--send-count 0 --answer-migration --update-mesh --leave-with-host"),
}


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", choices=sorted(PRESETS),
                    help="the tested flag set: 'capture' records the console's party snapshot, "
                         "'trade' needs --send-snapshot")
    ap.add_argument("--comm-id", default=None, help="hex; defaults to Sword's 0x0100abf008968000")
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--ip-join", action="store_true",
                    help="join an emulated console hosting over ldn_mitm on the LAN; no radio, "
                         "no root, no keys. Each of --scans waits --dwell seconds for an answer")
    ap.add_argument("--host-ip", default="127.0.0.2", help="--ip-join: the console's address")
    ap.add_argument("--our-ip", default=None, help="--ip-join: our own address on that LAN")
    ap.add_argument("--scan-ip", default=None,
                    help="--ip-join: the address a scan leaves from; default --our-ip")
    ap.add_argument("--ifname", default="ldnclient")
    ap.add_argument("--channels", default="1,6,11")
    ap.add_argument("--dwell", type=float, default=1.5)
    ap.add_argument("--scans", type=int, default=8,
                    help="scans for a matching search (scene 60001) before giving up")
    ap.add_argument("--name", default="POKELDN")
    ap.add_argument("--listen-first", type=float, default=6.0,
                    help="seconds of listening before the first packet out, so the capture holds "
                         "the console's own rate to compare against")
    ap.add_argument("--station-sweep", default="0,1",
                    help="readings of the header byte at 0x05, in order; the IV's source id "
                         "follows each one")
    ap.add_argument("--ack-seconds", type=float, default=12.0, help="per reading")
    ap.add_argument("--period", type=float, default=0.1)
    ap.add_argument("--quiet-for", type=float, default=1.5,
                    help="seconds without an update session that count as the rebroadcast stopping "
                         "- the console sends ten a second, so this is fifteen missed")
    ap.add_argument("--seq-delta", type=int, default=0,
                    help="THE CONTROL. Ack a sequence id the console never sent: a rebroadcast "
                         "that carries on under --seq-delta 1 is what attributes a stop under 0 to "
                         "the ack's CONTENT rather than to our merely having transmitted")
    ap.add_argument("--connect", action="store_true",
                    help="after the ack, sweep the version-4 connection request on protocol 0x14")
    ap.add_argument("--nat-flags", default="0-15", help="values for byte [1], list or LO-HI")
    ap.add_argument("--nat-location", default="0-3", help="values for byte [0x10]")
    ap.add_argument("--request-gap", type=float, default=0.25,
                    help="seconds between requests; the console answered BDSP's in 40 ms")
    ap.add_argument("--connect-station", default="0",
                    help="values for the header byte at 0x05 on the requests, and their IV source "
                         "id; list or LO-HI")
    ap.add_argument("--respond", action="store_true",
                    help="answer a connection request the CONSOLE sends us with a connection "
                         "response")
    ap.add_argument("--respond-result", type=int, default=0, help="0 is accepted")
    ap.add_argument("--respond-with", default="theirs", choices=["theirs", "ours", "both"],
                    help="whose constant and variable id go in the response's two id fields - a "
                         "deduction, so 'both' alternates them across the retransmits")
    ap.add_argument("--request-platform", default="9",
                    help="values for the platform byte at [2]. 9 is the real one; ANY other value "
                         "is answered with a connection response rather than dropped, which is the "
                         "probe for whether our message reaches the 0x14 handler at all")
    ap.add_argument("--request-flags", default="0x09",
                    help="values for the MESSAGE flags byte. 0x09 is what the console puts on its "
                         "own Local Protocol messages; BDSP's station requests carry 0x11")
    ap.add_argument("--request-unicast", action="store_true", default=True,
                    help="send the requests to the console rather than the broadcast address")
    ap.add_argument("--request-broadcast", dest="request_unicast", action="store_false",
                    help="send them to the broadcast address instead")
    ap.add_argument("--src-var", type=lambda s: int(s, 0), default=None,
                    help="our own station variable id; fresh random when omitted, because a reused "
                         "one is 'already one of my stations' on BDSP")
    ap.add_argument("--no-variable-id", action="store_true",
                    help="clear [3], which makes the console skip the variable-id comparison")
    ap.add_argument("--unicast", action="store_true",
                    help="send to the console rather than the broadcast address")
    ap.add_argument("--join", action="store_true",
                    help="after the station handshake closes, send the Mesh Protocol (0x18) join "
                         "request and ack whatever comes back")
    ap.add_argument("--join-wait", type=float, default=45.0,
                    help="how long to wait for the station acceptance before giving up on joining")
    ap.add_argument("--join-seconds", type=float, default=10.0,
                    help="how long to retransmit the join request; Pia's own joiner gives up at 10")
    ap.add_argument("--join-gap", type=float, default=0.5,
                    help="Pia retransmits an unacknowledged join request every 500 ms")
    ap.add_argument("--join-port", type=int, default=mesh.PORT_UNRELIABLE,
                    help="the Pia port the join travels on; the update mesh uses the reliable one")
    ap.add_argument("--join-station-index", type=lambda s: int(s, 0),
                    default=mesh.STATION_INDEX_INVALID,
                    help="byte [1]. 0xFD is what 0x017c1700 compares against; anything else is the "
                         "instrument that says the handler was reached")
    ap.add_argument("--join-ack-id", type=lambda s: int(s, 0), default=None,
                    help="fixed ack id for the join request; random when omitted")
    ap.add_argument("--answer-rtt", action="store_true",
                    help="answer the console's 0x58 RTT requests. Sixteen bytes at version 4, and "
                         "the reply echoes the seven bytes nothing has read yet")
    ap.add_argument("--ack-reliable", action="store_true",
                    help="acknowledge the 0x7C reliable window. The pass signal is the "
                         "retransmits STOPPING and the sequence ids moving on")
    ap.add_argument("--ack-slots", default=None,
                    type=lambda v: None if v in ("", "all") else [int(x, 0) for x in v.split(",")],
                    help="which of the 32 ack slots to fill; \"all\" (the default) fills every "
                         "one, because only the slot at some station index is read and whose index "
                         "it is has not been settled. \"0\" is the console, \"1\" is us")
    ap.add_argument("--ack-lowest-pending", type=lambda s: int(s, 0), default=1,
                    help="the header's own 'lowest sequence pending ack'. We have sent nothing on "
                         "this protocol, so 1 (the next id we would use) and 0 are both readings; "
                         "the console itself sends 1 while waiting on its own first message")
    ap.add_argument("--data-destination", type=lambda s: int(s, 0), default=1,
                    help="the station BITMAP on 0x58 and 0x7C. The console sends 2 to us, station "
                         "index 1; 1 is the bit for station 0, which is the console")
    ap.add_argument("--send-data", default=None, metavar="HEX",
                    help="send APPLICATION DATA once the mesh is up - the first of the project. "
                         "The payload as hex; \"610000000a00\" is the six bytes the console "
                         "repeats at us on 0x7C. Nothing is sent without this flag")
    ap.add_argument("--send-protocol", type=lambda s: int(s, 0),
                    default=reliable4.BROADCAST_PROTOCOL,
                    help="0x80 (the broadcast reliable window, the default: it asks us for "
                         "sequence 1 once a second) or 0x7c (the unicast one, which has never had "
                         "an ack to send us because it has never had our data)")
    ap.add_argument("--send-sequence", type=lambda s: int(s, 0), default=reliable4.FIRST_SEQUENCE,
                    help="the sequence id. 1 is what both windows ask for; the first message also "
                         "carries FLAG_IS_INITIALIZED and DEFINES where the stream starts")
    ap.add_argument("--send-stream", type=lambda s: int(s, 0), default=0,
                    help="the stream id. 0 is what the console sends on both protocols")
    ap.add_argument("--send-destinations", choices=("auto", "none", "console"), default="auto",
                    help="the header's destination list. \"console\" names its station constant "
                         "id, which is what its own broadcast acks do to us; \"none\" sends "
                         "count 0, which 0x01859578 never filters and every 0x7C message carries. "
                         "\"auto\" mirrors the console per protocol: none on 0x7C, the console "
                         "on 0x80")
    ap.add_argument("--send-zlib", action="store_true",
                    help="compress the message, the way the console compresses every 0x80 message "
                         "it sends. The flag is the Pia message's (0x10 at version 4), so this is "
                         "free either way - and it is one variable, so sweep it alone")
    ap.add_argument("--send-port", default="0",
                    help="the Pia message port. The console sends its 0x80 acks on 0 AND 1, each "
                         "packet carrying both; \"0,1\" mirrors that")
    ap.add_argument("--send-wait", type=float, default=60.0,
                    help="how long to wait for the station handshake before giving up on sending")
    ap.add_argument("--send-after", type=float, default=5.0,
                    help="seconds after acceptance before the first data message, so the mesh join "
                         "and the RTT exchange are already running when it lands")
    ap.add_argument("--send2-data", default=None, metavar="HEX",
                    help="a SECOND stream, on --send2-protocol, sent once the console says "
                         "--send2-trigger. `60ea000012020801` is BlockDataHolder{imReady:true}, "
                         "which the console says on 0x80 and waits on")
    ap.add_argument("--send2-protocol", type=lambda s: int(s, 0),
                    default=reliable4.BROADCAST_PROTOCOL)
    ap.add_argument("--send2-port", type=lambda s: int(s, 0), default=0)
    ap.add_argument("--send2-trigger", default=None, metavar="HEX",
                    help="wait for this payload on --send2-protocol before sending; omit to send "
                         "as soon as the mesh is up")
    ap.add_argument("--send2-count", type=lambda s: int(s, 0), default=200)
    ap.add_argument("--trade-ready", action="store_true",
                    help="after our offer is acknowledged, send imReady on the TRADE holder "
                         "(20030). The console has never sent these bytes and the published client "
                         "waits for them before it offers, so it may be our turn to say them")
    ap.add_argument("--rpc-port-answers", action="store_true",
                    help="answer the trade RPC on its OWN Pia port with its own reliable window. "
                         "The console sends them on 0x7C port 1; an answer on port 0 lands on a "
                         "window it does not read them on")
    ap.add_argument("--rpc-port", type=lambda s: int(s, 0), default=1)
    ap.add_argument("--rpc-period", type=float, default=0.3)
    ap.add_argument("--answer-migration", action="store_true",
                    help="answer the console's MIGRATION_START on 0x18 port 1 with a "
                         "MIGRATION_RESPONSE. `440001` arrives there only when the player "
                         "accepts, and the console goes silent on every window afterwards: the "
                         "last thing it asks for is two bytes of mesh, not application data")
    ap.add_argument("--leave-with-host", action="store_true",
                    help="when the hosting console leaves, ack its update session carrying the "
                         "host-migration state and leave the network on its START_HOST_MIGRATION, "
                         "as its own clients do; each step waits 10 s unanswered")
    ap.add_argument("--migration-answer", choices=("auto", "finish", "response"), default="auto",
                    help="what to send when the console migrates the mesh. \"auto\" sends "
                         "MIGRATION_FINISH when the start names US as the next host and a "
                         "MIGRATION_RESPONSE when it names anyone else, which is what the binary "
                         "says. \"response\" always answers 0x48, for comparison")
    ap.add_argument("--open-content", default=None, metavar="N,N,...",
                    help="after our offer is acknowledged, send `ping` on content N's 10000-base "
                         "holder for each N - `382700000a00` for 40, which is exactly the opener "
                         "nxldn-lab's client sends to start the confirmation phase, rebuilt here "
                         "from our own content registry rather than copied")
    ap.add_argument("--confirm-command", type=lambda s: int(s, 0), default=None,
                    metavar="N",
                    help="when the CONFIRMATION envelope (40040) sends a four-byte status whose "
                         "body ends `0100` - the same cue the selection content sends before its "
                         "Pokemon - reply with SyncSaveDataHolder{syncCommand{data:N}} on that "
                         "content's 10000-base holder, id 10040, reliable port 0, and answer the "
                         "status itself on port 1. Content 40 takes a command and not a Pokemon: "
                         "its parser 0x010df6d0 accepts one submessage carrying one int32. Its own "
                         "machine sends 0, 1, 2 and 3 in that order (swsh_trade.SYNC_COMMANDS)")
    ap.add_argument("--confirm-phase", type=int, default=None, metavar="N",
                    help="answer the confirmation content's four-byte steps with phase N in the "
                         "LOW u16 instead of echoing the console's own. The console reads its "
                         "phase out of exactly those bytes (`0x006d6490` stores them, "
                         "`0x006d3260` reads them), and every step this project has sent so far "
                         "echoed the value back unchanged")
    ap.add_argument("--abort-on-stall", type=float, default=0.0, metavar="SECONDS",
                    help="once the confirmation ladder has produced its first step, end the run "
                         "as soon as SECONDS pass with no NEW step body: stop transmitting, drop "
                         "the link and let the console report a lost connection. Holding a stalled "
                         "ladder open with acks instead makes the game declare the TRADE failed, "
                         "which costs the player about an hour. Nothing but acks follows the last "
                         "step body. 0 is off and the hold runs in full.")
    ap.add_argument("--confirm-commands", default=None, metavar="N,N,...",
                    help="the handshake form of --confirm-command: send the NEXT of these on each "
                         "new four-byte body the confirmation content puts on elementId 20000. "
                         "Content 40's own machine sends 0,1,2,3 and parks after each; one "
                         "command buys two rungs and then the ladder stops")
    ap.add_argument("--confirm-final-delta", type=lambda s: int(s, 0), default=0,
                    metavar="N",
                    help="after the CONFIRMATION content answers our syncCommand with a hash, "
                         "re-arm the 40040 pair and send BOTH members again at this clock delta - "
                         "the move --selection-final-delta makes on 40050, which carries the "
                         "selection phase past its own hash")
    ap.add_argument("--selection-final-delta", type=lambda s: int(s, 0), default=0,
                    help="after the selection HASH is answered, send the 40050 pair AGAIN - both "
                         "members - at this clock delta. nxldn-lab's `selection_final_delta` is 9 "
                         "(nxldn-lab's `selection_final_delta`). --rpc-pair latches per "
                         "envelope, so the second pair needs the latch cleared. 0 is off")
    ap.add_argument("--open-content-offer", action="store_true",
                    help="make --open-content send our PK8 on the 10000-base holder instead of an "
                         "empty `ping`. The ping opens content 50 and is taken as our Pokemon: "
                         "the console reaches the confirmation phase and asks the player to trade "
                         "theirs for an egg. Same moment, same holder, a Pokemon in it")
    ap.add_argument("--box-on-accept", default=None, metavar="N,N,...",
                    help="send these box commands the moment MIGRATION_START arrives - the only "
                         "signal that says the player pressed accept. The console keeps acking "
                         "for about five seconds after it")
    ap.add_argument("--box-period", type=float, default=0.0,
                    help="seconds between the queued post-offer payloads. Spread them so the "
                         "sweep spans the accept: the console tears down on the accept, not on a "
                         "timer, so commands sent inside a couple of seconds all land before it")
    ap.add_argument("--selection-offer", action="store_true",
                    help="when the console follows its selection-phase Pokemon with the status "
                         "whose body ends `0100`, offer OUR Pokemon on that content's 10000-base "
                         "holder (id 10050) on reliable port 0 and answer the status on port 1")
    ap.add_argument("--pair-after-hash", type=int, default=None, metavar="N",
                    help="once a hash body has been answered, open content N's phase by sending "
                         "the two-member RPC pair for it (40 is the confirmation). A pair is the "
                         "only shape that opens a phase on this console: 40030 opened the offer "
                         "and 40050 the selection. A bare content ping (`382700000a00`) and a bare "
                         "sync-120 ping (`780000000a00`) are both ignored")
    ap.add_argument("--sync-after-offer", type=int, default=None, metavar="N",
                    help="queue a sync on holder N right behind our selection offer, in "
                         "the branch that actually runs when --selection-offer is on. "
                         "--sync-after-hash cannot fire there: this one can")
    ap.add_argument("--sync-field", type=int, default=1, choices=(1, 2, 3),
                    help="which SyncPingDataHolder field --sync-after-hash sends: 1 ping, "
                         "2 pingReply, 3 pingSynced (`780000001a00`, the one the trace records)")
    ap.add_argument("--sync-after-hash", type=int, default=None, metavar="N",
                    help="once a hash body has been answered, send `ping` on sync holder N (120 "
                         "is the confirmation's) on port 0. The console drives 97, 60000, 110 "
                         "and 130 itself and opens the selection phase when 130's pingSynced "
                         "lands; it never sends 120. A phase follows its sync, not a content ping")
    ap.add_argument("--open-after-hash", type=int, default=None, metavar="N",
                    help="once a hash body has been answered, `ping` content N's 10000-base holder "
                         "on port 0 to open the next phase - 40 is the confirmation, so this sends "
                         "`382700000a00`. The console stops sending 40050 once the hash answer "
                         "lands and says nothing further; Pia retransmits anything it still waits "
                         "on, so that silence means satisfied and the next phase needs opening")
    ap.add_argument("--rpc-bodies", action="store_true",
                    help="answer every DISTINCT (envelope, base, field-5 body) in the 40000 band "
                         "once, on top of the opening pair. The clock advances on every message so "
                         "the payload cannot be the key, but the body can: `00000000` and "
                         "`000018fc` are the openers and anything else is new. A per-envelope "
                         "guard stops answering at the hash body and stalls there")
    ap.add_argument("--rpc-pair", action="store_true",
                    help="answer the console's 40030 RPC as the PAIR it is: collect both members "
                         "one per base, 10000 then 20000, keyed on the BASE FIELD. "
                         "`payload[5] in (0x19, 0x1A)` is the inner length and moves with the "
                         "sender's station-id varint (0x1A/0x1B on some consoles). Send both once "
                         "in that order and nothing more on this window; `said_by_port` keeps only "
                         "the last payload, so a mirror sends one member repeatedly and never the "
                         "other")
    ap.add_argument("--open-early", default=None, metavar="N,N,...",
                    help="`ping` content N's 10000-base holder at the 0x84 snapshot ack, before "
                         "either side offers. The console's box send is gated on a ready bool at "
                         "content+0x4c that only `0x010ce040` sets, on a zero result code; until "
                         "then every command the game tries to send is parked in content+0x48. A "
                         "parked command that does not match the next one sets the error byte "
                         "+0x4d, and `0x010c9bb0` turns that into trade state 9: abort, with "
                         "nothing on the application layer")
    ap.add_argument("--box-open", default=None, metavar="N,N,...",
                    help="send these box commands as soon as the console acks our 0x84 snapshot - "
                         "BEFORE either side offers a Pokemon. The game sends command 3 exactly "
                         "once, on the first frame after its trade session is built and only when "
                         "the role bit at session+0x419 is clear (0x010c9bb0), so one of the two "
                         "sides owes the other an opener before anything else happens. Sent "
                         "after both offers instead, the console leaves while the player is still "
                         "picking")
    ap.add_argument("--box-commands", default=None, metavar="N,N,...",
                    help="after our offer is acknowledged, send boxSyncStateCommand{data:N} on the "
                         "trade holder for each N in turn, one per acknowledged sequence. 20030 is "
                         "a BoxSyncStateDataHolder and its field 2 is a command enum; this project "
                         "1 offers and 2 withdraws; 4 confirms and 5 withdraws the confirmation")
    ap.add_argument("--snapshot-account", action="store_true",
                    help="replace the three ids at the front of the snapshot's profile (pseudo "
                         "device id, account Uid, network service account id). They are the "
                         "console's own, handed back unchanged otherwise")
    ap.add_argument("--selection-offer-data", action="store_true",
                    help="with --selection-offer, answer the console's selection status with our "
                         "PK8 in field 5 (`body`) of a 40050 Data carrying OUR ownerId, on the RPC "
                         "port, instead of a PokemonTradeDataHolder on 10050 port 0. Content "
                         "50's receive handler resolves the sender to a station index and drops "
                         "silently when it cannot; the holder shape carries no owner")
    ap.add_argument("--selection-offer-sweep", action="store_true",
                    help="send our PK8 as a Data on elementId 10000 and as a holder on the "
                         "30000-base id (30050), which every content registers. More than one "
                         "variable at once")
    ap.add_argument("--selection-offer-high", action="store_true",
                    help="with --selection-offer, answer the selection status with our PK8 as a "
                         "PokemonTradeDataHolder on the 20000-base holder (id 20050), which is "
                         "where the BOX phase's own Pokemon rides one content over. Overrides "
                         "--selection-offer-mirror and --selection-offer-data")
    ap.add_argument("--selection-offer-mirror", action="store_true",
                    help="with --selection-offer, answer the selection status with our PK8 in a "
                         "40050 carrying the console's OWN field set - syncId, clock, body, and "
                         "neither elementId nor ownerId, which is how its own selection offer "
                         "decodes. Overrides --selection-offer-data")
    ap.add_argument("--offer-echo", action="store_true",
                    help="offer back the exact PK8 the console just offered us, unchanged, instead "
                         "of one out of --send-snapshot. These bytes came out of its own save, "
                         "so a run that still aborts rules the record out")
    ap.add_argument("--offer-on-50", action="store_true",
                    help="put our PK8 in field 5 of the 40050 pair's second member. Content 50 is "
                         "PokemonTradeDataHolder, the transfer; content 30 is the box exchange. "
                         "A 344-byte PK8 rides that field")
    ap.add_argument("--send-selection", default=None, choices=("offer", "migration"),
                    help="WHEN to open the selection phase with a 40050 pair on 0x7c port 1. "
                         "\"offer\" sends it as soon as our offer is acknowledged, the only "
                         "window the console is still reading in; \"migration\" sends it on the "
                         "migration start, after the console has stopped. The pair is the same "
                         "envelope as the console's own 40030 at offset 50 with our station id; "
                         "the builder reproduces its 40030 pair byte for byte")
    ap.add_argument("--update-mesh", action="store_true",
                    help="once the migration makes us the host, broadcast UPDATE_MESH the way the "
                         "console did: its own last one with the host index set to ours. The "
                         "console stops sending these once it hands the role over, and the mesh is "
                         "gone about 1.3 s later if nothing takes over")
    ap.add_argument("--update-mesh-period", type=float, default=1.0,
                    help="how often to broadcast it; the console sent one about every 2 s")
    ap.add_argument("--migration-period", type=float, default=0.3,
                    help="how often to retransmit the migration response until it is acked")
    ap.add_argument("--answer-once", action="store_true",
                    help="answer each payload the console sends ONCE instead of re-deriving an "
                         "answer to its last payload every period. `said` never clears, so "
                         "without this an offer goes out hundreds of times. The console sends each "
                         "of its own messages once")
    ap.add_argument("--offer-slot", type=lambda s: int(s, 0), default=0,
                    help="which party slot of --send-snapshot to offer back, 1-6; 0 offers "
                         "nothing and only records what the console offers us")
    ap.add_argument("--offer-file", action="append", default=[], metavar="FILE",
                    help="a .pk8 to put in --offer-slot in place of the snapshot's record: stored "
                         "or party form, encrypted or PKHeX's decrypted export. Its OT name and "
                         "ids become the snapshot's unless --offer-file-as-is. Repeatable, one per "
                         "trade on the session: the console's player picks again from the box; the "
                         "last serves every later trade")
    ap.add_argument("--fresh-pid", action="store_true",
                    help="draw a new encryption constant and PID for every offered Pokemon")
    ap.add_argument("--offer-file-as-is", action="store_true",
                    help="keep the file's own OT name and trainer ids")
    ap.add_argument("--offer-species", type=lambda s: int(s, 0), default=None,
                    help="build the record in --offer-slot instead of sending it as it came: this "
                         "national dex number, in the party record the snapshot advertises AND in "
                         "the offer, so the two still tell one story")
    ap.add_argument("--offer-ability", type=lambda s: int(s, 0), default=None,
                    help="the ability id of the built record; --offer-species leaves the "
                         "template's ability where it was")
    ap.add_argument("--offer-level", type=lambda s: int(s, 0), default=None,
                    help="the level byte at 0x148 of the built record, 1..100; the experience "
                         "word is left alone unless --offer-experience is given")
    ap.add_argument("--offer-experience", type=lambda s: int(s, 0), default=None,
                    help="the experience word at 0x10 of the built record")
    ap.add_argument("--offer-moves", default=None,
                    help="four move ids, comma-separated; 0 empties a slot. PP is left as the "
                         "template had it")
    ap.add_argument("--offer-nickname", default=None,
                    help="the nickname of the built record; sets the nicknamed flag")
    ap.add_argument("--offer-ot", default=None,
                    help="the original trainer name of the built record")
    ap.add_argument("--offer-ivs", default=None,
                    help="six IVs, comma-separated, in PKHeX's HP,ATK,DEF,SPE,SPA,SPD order")
    ap.add_argument("--save-offer", default=None, metavar="FILE",
                    help="write the PK8 we will offer to this file, before the radio is touched")
    ap.add_argument("--save-offered", default=None, metavar="FILE",
                    help="write the PK8 the console offers to this file; trade N > 1 writes FILE-N")
    ap.add_argument("--rpc-clock-delta", type=lambda s: int(s, 0), default=5,
                    help="how far to advance a trade RPC's clock in our answer. 5 is nxldn-lab's "
                         "and is the one number in this path nothing here has measured")
    ap.add_argument("--rpc-pair-advance", type=lambda s: int(s, 0), default=0,
                    help="after answering an RPC pair, send BOTH members again with the clock "
                         "advanced by this much. The console advances its own pair's clock by 2 "
                         "each burst (b41c, b61c, b81c). A repeated clock is a repeated state, "
                         "so an answer that carries one clock never moves ours. 0 is off")
    ap.add_argument("--selection-start", action="store_true",
                    help="send our own 40050 pair the moment the console says id 130 pingSynced, "
                         "before its own selection burst. nxldn-lab's client opens the selection "
                         "phase this way and nothing here has ever opened one; the console sends "
                         "820000001a00 in our own captures 0.3 s before its 40050 burst")
    ap.add_argument("--ack-snapshot", action="store_true",
                    help="ACK the console's 0x84 fragments (kind 0x21, a contiguous base and a "
                         "bitmask). Nothing here has ever acked this protocol, which is why the "
                         "console retransmits one snapshot 19142 times and never moves on")
    ap.add_argument("--send-snapshot", default=None, metavar="FILE|live",
                    help="a 3456-byte trade snapshot to send back on 0x84 once the console sends "
                         "its own, or live (the default under --preset trade) for the console's own "
                         "from this session. A short "
                         "2965-byte payload is inflated first. The identity is rewritten by "
                         "--snapshot-name/-tid/-sid")
    ap.add_argument("--snapshot-name", default="POKELDN")
    ap.add_argument("--snapshot-tid", type=lambda s: int(s, 0), default=12345)
    ap.add_argument("--snapshot-sid", type=lambda s: int(s, 0), default=54321)
    ap.add_argument("--snapshot-port", default="0",
                    help="Pia port(s) for our 0x84 messages; the console sends on 0")
    ap.add_argument("--snapshot-period", type=float, default=0.05,
                    help="between our own fragments")
    ap.add_argument("--snapshot-repeat", type=float, default=2.0,
                    help="between whole re-sends; the console retransmits its own until acked")
    ap.add_argument("--sync-answers", action="store_true",
                    help="answer with `pokeldn.swsh.trade.SYNC_ANSWERS` instead of echoing one "
                         "payload: the ping, and the three other sync holders the console is "
                         "expected to raise after the trade snapshot. A payload with no rule is "
                         "REPORTED and left unanswered - that report is the point of the run")
    ap.add_argument("--send-mirror", action="store_true",
                    help="send back whatever the console last said on this protocol, rather than "
                         "the fixed --send-data. --send-data is still the first payload, before "
                         "the console has said anything")
    ap.add_argument("--send-count", type=lambda s: int(s, 0), default=1,
                    help="how many sequence ids of ours to send in all; 0 has no limit. One "
                         "message does not hold the console's state; it sends its own heartbeat "
                         "about 580 times in 180 s")
    ap.add_argument("--send-period", type=float, default=1.0,
                    help="the retransmit interval. A window retransmits until it is acked")
    ap.add_argument("--send-seconds", type=float, default=60.0,
                    help="how long to keep retransmitting if nothing acknowledges it; 0 sends "
                         "until the run ends")
    ap.add_argument("--hold", type=float, default=30.0)
    ap.add_argument("--grace", type=float, default=300.0,
                    help="seconds past --hold to keep a session whose trade is under way: the "
                         "console has offered and the ladder has not finished")
    ap.add_argument("--capture", default=None)
    return ap


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    preset = build_parser().parse_known_args(argv)[0].preset
    if preset:
        argv = shlex.split(PRESETS[preset]) + argv
    args = build_parser().parse_args(argv)
    if preset == "trade" and not args.send_snapshot:
        args.send_snapshot = "live"
    args.connect_station_first = int(_expand(args.connect_station)[0], 0)
    try:
        offer_edits(args)
    except ValueError as e:
        build_parser().error(str(e))
    if args.offer_file:
        edits = offer_edits(args)
        args.offer_file = [pokemon_service.prepare_file(
            "swsh", path, fresh=args.fresh_pid,
            transform=lambda raw: swsh_pokemon.build_from(raw, **edits)) for path in args.offer_file]
        args.offer_file_as_is = True
        for key in ("species", "ability", "level", "experience", "nickname", "ot", "ivs", "moves"):
            setattr(args, "offer_" + key, None)
    args.validate_offer = True
    if not args.ip_join and needs_root():
        build_parser().error("must run as root (LDN needs the raw radio)")
    try:
        return trio.run(main_async, args)
    except BaseException as e:
        print(f"[cx] {type(e).__name__}: {e}")
        for sub in getattr(e, "exceptions", ()) or ():
            print(f"[cx]   caused by: {type(sub).__name__}: {sub}")
        if not args.ip_join:
            cleanup()
        raise


if __name__ == "__main__":
    sys.exit(main())
