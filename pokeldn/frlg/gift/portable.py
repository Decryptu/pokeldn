"""A FireRed/LeafGreen Mystery Gift the board keeps and hosts with no computer: the image
`pokeldn.ldn.portable.build_host` stores, with the records `firmware/esp32/main/gift.h` reads. The
board plays the session `bin/frlg_mg_host.py` plays; everything that host computes before the console
joins (the advertised activity, the LinkPlayer block, each cartridge's bytes) is computed here, by
the same code (docs/hardware_esp32.md, Portable beacon).
"""
import struct

from pokeldn.frlg.gift import host_mg_app, mg_server
from pokeldn.ldn import crypto, pia_connect, portable
from pokeldn.ldn.transport import GBA_APP_PASSPHRASE, HostTransport

RECORD_APP = 16
RECORD_APP_ACTIVE = 17
RECORD_LINK = 18
RECORD_TIMING = 19
RECORD_GAME = 20
RECORD_PROGRAM = 21
RECORD_PAYLOAD = 22
RECORD_BUILD = 23

# gift.h, the server program.
OP_RETURN, OP_SEND, OP_RECV, OP_GOTO, OP_GOTO_IF_EQ, OP_COPY_GAME_DATA = range(6)
OP_CHECK_GAME_DATA, OP_CHECK_EXISTING_CARD, OP_READ_RESPONSE, OP_LOAD = range(6, 10)
OP_CHECK_QUESTIONNAIRE, OP_CHECK_RALLY_CARD, OP_CHECK_EXISTING_STAMPS = range(10, 13)
_SIZES = {OP_RETURN: 2, OP_SEND: 1, OP_RECV: 2, OP_GOTO: 3, OP_GOTO_IF_EQ: 7,
          OP_COPY_GAME_DATA: 1, OP_CHECK_GAME_DATA: 2, OP_CHECK_EXISTING_CARD: 1,
          OP_READ_RESPONSE: 1, OP_LOAD: 2, OP_CHECK_QUESTIONNAIRE: 9, OP_CHECK_RALLY_CARD: 1,
          OP_CHECK_EXISTING_STAMPS: 1}
_PLAIN = {mg_server.SVR_SEND: OP_SEND, mg_server.SVR_COPY_GAME_DATA: OP_COPY_GAME_DATA,
          mg_server.SVR_CHECK_EXISTING_CARD: OP_CHECK_EXISTING_CARD,
          mg_server.SVR_READ_RESPONSE: OP_READ_RESPONSE,
          mg_server.SVR_READ_MEVENT_STATUS: OP_READ_RESPONSE,
          mg_server.SVR_CHECK_RALLY_CARD: OP_CHECK_RALLY_CARD,
          mg_server.SVR_CHECK_EXISTING_STAMPS: OP_CHECK_EXISTING_STAMPS}
_LOADS = {mg_server.SVR_LOAD_CARD, mg_server.SVR_LOAD_NEWS, mg_server.SVR_LOAD_RAM_SCRIPT,
          mg_server.SVR_LOAD_CLIENT_SCRIPT, mg_server.SVR_LOAD_MSG, mg_server.SVR_LOAD_STAMP,
          mg_server.SVR_LOAD_ACTIVATION, mg_server.SVR_LOAD_EREADER_TRAINER,
          mg_server.SVR_LOAD_MEVENT, mg_server.SVR_LOAD_DENIED_MSG}
GAME_FAMILY = {"frlg": 0, "emerald": 1}
EXPECT = {None: 0, "firered": 1, "leafgreen": 2, "emerald": 3}
ANY_BUILD = b"\x00" * 4


def _scripts(root):
    """Every script reachable from `root`, in a fixed order."""
    order, seen = [], set()

    def visit(script):
        if id(script) in seen:
            return
        seen.add(id(script))
        order.append(script)
        for command in script:
            if command[0] == mg_server.SVR_GOTO:
                visit(command[1])
            elif command[0] == mg_server.SVR_GOTO_IF_EQ:
                visit(command[2])
    visit(root)
    return order


def _op(command):
    name = command[0]
    if name in _PLAIN:
        return _PLAIN[name]
    if name in _LOADS:
        return OP_LOAD
    return {mg_server.SVR_RETURN: OP_RETURN, mg_server.SVR_RECV: OP_RECV,
            mg_server.SVR_GOTO: OP_GOTO, mg_server.SVR_GOTO_IF_EQ: OP_GOTO_IF_EQ,
            mg_server.SVR_CHECK_GAME_DATA: OP_CHECK_GAME_DATA,
            mg_server.SVR_CHECK_QUESTIONNAIRE: OP_CHECK_QUESTIONNAIRE}.get(name)


def compile_program(server):
    """-> (bytecode, loads): the server script as gift.h runs it, and each LOAD's command in slot
    order. A buffer script reads its answer on the computer and has no board form."""
    scripts = _scripts(server.script)
    address, at = {}, 0
    for script in scripts:
        address[id(script)] = at
        for command in script:
            op = _op(command)
            if op is None:
                raise ValueError(f"{command[0]} needs the computer; this gift cannot be kept on "
                                 "the board")
            at += _SIZES[op]
    code, loads = bytearray(), []
    for script in scripts:
        for command in script:
            op, args = _op(command), command[1:]
            code.append(op)
            if op == OP_RETURN:
                code.append(args[0])
            elif op == OP_RECV:
                code.append(args[0])
            elif op == OP_GOTO:
                code += struct.pack("<H", address[id(args[0])])
            elif op == OP_GOTO_IF_EQ:
                code += struct.pack("<IH", int(args[0]), address[id(args[1])])
            elif op == OP_CHECK_GAME_DATA:
                code.append(1 if server.news is not None else 0)
            elif op == OP_CHECK_QUESTIONNAIRE:
                code += struct.pack("<4H", *server.questionnaire)
            elif op == OP_LOAD:
                code.append(len(loads))
                loads.append(command)
    if len(loads) > 255 or len(code) > 0xFFFF:
        raise ValueError("the server script is too long for the board")
    return bytes(code), loads


def _loaded(server, command):
    """(ident, size, bytes) the server would send after `command`; size 0 is the 1024-byte buffer."""
    getattr(server, "_do_" + command[0].lower())(*command[1:])
    ident, payload, size = server._loaded
    server._loaded = None
    return ident, size, bytes(payload)


def _build_fields(server):
    card, stamp = server.card, server.stamp
    return struct.pack("<HHBHH",
                       int.from_bytes(card[0:2], "little") if card else 0,
                       int.from_bytes(card[2:4], "little") if card else 0,
                       card[9] if card else 0,
                       int.from_bytes(stamp[0:2], "little") if stamp else 0,
                       int.from_bytes(stamp[2:4], "little") if stamp else 0)


def server_records(server):
    """The program, the payload pool and one build record per cartridge served (gift.h)."""
    code, loads = compile_program(server)
    builds = ([(ANY_BUILD, server)] if server._build_servers is None else
              [(name.encode("ascii"), chosen) for name, chosen in sorted(server._build_servers.items())
               if isinstance(chosen, mg_server.MysteryGiftServer)])
    if not builds:
        raise ValueError("no cartridge can be served")
    pool, records = {}, []
    for name, chosen in builds:
        if chosen.questionnaire != server.questionnaire:
            raise ValueError("every cartridge's payload must ask the same questionnaire")
        slots = []
        for command in loads:
            payload = _loaded(chosen, command)
            if payload not in pool:
                pool[payload] = len(pool)
                records.append(portable.record(RECORD_PAYLOAD, struct.pack("<BH", payload[0], payload[1])
                                       + payload[2]))
            slots.append(pool[payload])
        if len(pool) > 255:
            raise ValueError("too many distinct payloads for the board")
        records.append(portable.record(RECORD_BUILD, name + _build_fields(chosen)
                               + bytes([len(slots)]) + bytes(slots)))
    game = struct.pack("<BB", GAME_FAMILY[server.game], EXPECT[server.expect_console])
    return [portable.record(RECORD_GAME, game), portable.record(RECORD_PROGRAM, code)] + records


def _timing(engine, peer):
    t = engine.timing
    flags = ((1 if peer.nonces.native else 0) | (2 if peer.response_first else 0)
             | (4 if engine.trust_pia else 0))
    tick_us = round(peer.protocol_tick_seconds * 1_000_000)
    return struct.pack("<8HBI", t.startup_standby_echo_frames, t.client_ready_idle_frames,
                       t.inter_block_gap_frames, t.player_ids_repeat_frames, t.block_repeat,
                       t.ram_script_block_repeat, t.close_retry_frames,
                       t.post_client_close_grace_frames, flags, tick_us)


class _Network:
    """What `HostApplication._build_components` hands its transport, kept instead of hosting."""

    def __init__(self, app_data=b"", password=None, nickname="EMU", local_comm_id=None,
                 scene_id=None, max_participants=2, channel=None, **_):
        self.app_data = bytes(app_data)
        self.password = password or GBA_APP_PASSPHRASE
        self.nickname = nickname
        self.local_comm_id = local_comm_id or HostTransport.LOCAL_COMMUNICATION_ID
        self.scene_id = scene_id if scene_id is not None else HostTransport.SCENE_ID
        self.max_participants = max_participants
        self.channel = channel


def application(config, plan):
    """The host application `bin/frlg_mg_host.py` would run, built but never started."""
    kind = (host_mg_app.WonderNewsHostApplication if plan.distribution.is_news
            else host_mg_app.BufferScriptHostApplication if plan.distribution.buffer_code is not None
            else host_mg_app.MysteryGiftHostApplication)
    app = kind(config, plan=plan, transport_factory=_Network, log=lambda *a: None)
    app._resolve_phy_and_keys = lambda: (None, None)
    app._build_components()
    return app


def build(config, plan, keys, *, display=()):
    """The image for `config` with prod.keys' `keys`; only keys derived for LDN protocol 3 go in."""
    app = application(config, plan)
    network = app.network
    if network.channel not in (1, 6, 11):
        raise ValueError(f"channel {network.channel}: the board hosts on 1, 6 or 11")
    engine, peer = app.session.activity, app.peer
    net, derivation, data_key = portable.network(
        keys, local_communication_id=network.local_comm_id, scene_id=network.scene_id,
        app_version=HostTransport.APPLICATION_VERSION, protocol=3, password=network.password,
        name=network.nickname.encode(), max_participants=network.max_participants,
        channel=network.channel)
    records = [
        portable.ldn_record(net, derivation),
        portable.pia_record(net, crypto.FRLG_GAME_KEY, app.profile.session_name,
                            pia_connect.DEFAULT_PLAYER_ID),
        portable.record(RECORD_APP, network.app_data),
        portable.record(RECORD_APP_ACTIVE, peer.active_app_data),
        portable.record(RECORD_LINK, engine._link_player_block + app.session.rfu.host_session_id),
        portable.record(RECORD_TIMING, _timing(engine, peer)),
        *server_records(engine.server),
    ]
    return portable.build_host(net, derivation, data_key, records, display=list(display))
