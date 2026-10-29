"""A Scarlet console leaving a seat is answered at its first departure message, in both roles
(docs/sv.md, Leaving)."""
import os
import struct

import pytest
import trio

import sv_host
import sv_join
from pokeldn import ldn, sv
from pokeldn.ldn import game_channel, pia6, pia_connect, reliable5
from pokeldn.sv import trade

HOST_IP, JOIN_IP = '127.0.0.2', '127.0.0.3'
HOST_MAC, JOIN_MAC = bytes.fromhex('02007f000002'), bytes.fromhex('02007f000003')
SSID = bytes.fromhex('7b744617795970bb6882b24ded4cae15')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(ROOT, 'scratchpad', 'sv', 'main.bin')            # Scarlet 4.0.0

# A retail console's first leave request to bin/sv_host.py after two trades, and the station it
# names (constant id, variable id 0x23ae).
RETAIL_LEAVE = bytes.fromhex('03775acfbaeb9b2220f1480000000023ae00a9fe1d023039')
CONSOLE_CID, CONSOLE_VAR = bytes.fromhex('eb9b2220f1480000'), 0x23ae
# A retail console hosting from its search, handing the host role to bin/sv_join.py (variable id
# 0xc493) once its player backed out after two trades; then its NetStartHostMigration.
RETAIL_TYPE7 = bytes.fromhex('07eb9b2220f14800000000822500a9fe1901303924c93ad134e600000000c4930001')
RETAIL_HOST_VAR = 0x8225
NET_START_HOST_MIGRATION = bytes.fromhex('01400000')

LEAVE_WAIT = 0.5          # LeaveMeshJob's wait for the answer, 0x1f4 ms at `0x6db6a0`
LEAVE_SENDS = 4           # its retry counter `[job+0x6c]` gives up past 2 (`0x6db8e8`)
DESTROY_RESEND = 0.3      # NetDestroyNetworkJob's resend, 0x12c ms at `0x6aca98`
DESTROY_LIMIT = 4.0       # and its wait for every client to leave, 0xfa0 ms at `0x6ac68c`


class Clock:
    def __init__(self):
        self.now = 100.0

    def time(self):
        return self.now

    monotonic = time


class LeavingConsole:
    """Joined to our host, the player quits: `LeaveMeshJob` sends the type-3 request, waits 500 ms
    for a 17-byte type 4 carrying its own location id (`0x6d7b10`), resends, four sends at most,
    then leaves the network answered or not."""

    def __init__(self, clock, quit_at):
        self.clock, self.quit_at = clock, quit_at
        self.keys = sv.session_keys(SSID)
        self.own = pia_connect._location_id(CONSOLE_CID, CONSOLE_VAR)
        self.queue, self.leave_sends = [], []
        self.answer = self.left_at = None
        join = pia6.build_session_join(CONSOLE_CID, CONSOLE_VAR, JOIN_IP,
                                       pia_connect.ldn_constant_id(HOST_MAC), 1, 'Player',
                                       bytes(4))
        self.queue.append(self.packet(join))

    def packet(self, body):
        return sv_join.build_out(self.keys, JOIN_IP, body, 1,
                                 protocol=sv_host.PROTO_SESSION, src_var=CONSOLE_VAR)

    def received(self, packet):
        _, plain, _ = pia6.parse_packet(self.keys.session_key, HOST_IP, self.keys.network_id,
                                        packet)
        for msg in pia6.parse_messages(plain):
            p = msg.payload
            if (msg.protocol == sv_host.PROTO_SESSION and self.leave_sends and self.left_at is None
                    and len(p) == 17 and p[0] == pia_connect.SESSION_LEAVE_RESPONSE
                    and p[5:17] == self.own):
                self.answer, self.left_at = bytes(p), self.clock.now

    def tick(self):
        self.clock.now += 0.05
        now = self.clock.now
        if now < self.quit_at or self.left_at is not None:
            return
        if self.leave_sends and now - self.leave_sends[-1] < LEAVE_WAIT:
            return
        if len(self.leave_sends) == LEAVE_SENDS:
            self.left_at = now
            return
        self.leave_sends.append(now)
        self.queue.append(self.packet(RETAIL_LEAVE))


def run_host(monkeypatch, extra=()):
    clock = Clock()
    console = LeavingConsole(clock, quit_at=clock.now + 1.0)

    class Transport:
        ssid, our_ip, our_mac = SSID, HOST_IP, HOST_MAC
        participants, join_events = [(JOIN_MAC, JOIN_IP)], 1

        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def set_application_data(self, _):
            pass

        def send(self, packet, _):
            console.received(packet)

        def wait_readable(self, _):
            console.tick()

        def recv(self):
            queued, console.queue = console.queue, []
            return [(packet, JOIN_IP) for packet in queued]

    monkeypatch.setattr(sv_host, 'time', clock)
    monkeypatch.setattr(sv_host, 'IpHostTransport', Transport)
    monkeypatch.setattr('sys.argv', [
        'sv_host', '--ip-host', '--seconds', '5', '--no-net-probe', '--scarlet-response',
        '--no-session-update', '--session-flags', '0x00', *extra])
    assert sv_host.main() == 0
    return console


def test_a_console_leaving_our_host_is_answered_at_its_first_request(monkeypatch):
    """Unanswered, a retail console sent four, the last 1.52 to 1.56 s after the first in four board
    sessions, and left the network 2.0 s after the first; answered, it sends one."""
    console = run_host(monkeypatch)
    assert console.answer is not None, "the host never answered the leave request"
    assert len(console.leave_sends) == 1
    assert console.left_at - console.leave_sends[0] < LEAVE_WAIT


@pytest.mark.skipif(not os.path.exists(MAIN), reason="needs the Scarlet 4.0.0 main")
def test_the_games_own_leave_job_accepts_the_hosts_answer(monkeypatch):
    """The host's answer goes through Scarlet's type-4 handler `0x6d7b10`, which sets the leave
    job's `+0x69` only for a 17-byte message carrying the station's own location id."""
    import sys
    sys.path.insert(0, os.path.join(ROOT, 'tools', 'switch'))
    from nso_run import Runner, SCRATCH, RETURN
    from unicorn.arm64_const import UC_ARM64_REG_PC
    console = run_host(monkeypatch)
    assert console.answer is not None, "the host never answered the leave request"
    runner = Runner(MAIN)
    holder = struct.unpack_from('<Q', runner.img, 0x46d0a08)[0]    # GOT read at `0x6d7b40`
    manager, reader, job, buf = (SCRATCH + 0x10000 + n * 0x1000 for n in range(4))

    def answered(message, job_state=2):
        runner.write(manager, bytes(0x400))
        runner.write(reader, bytes(0x200))
        runner.write(job, bytes(0x100))
        runner.write(holder, struct.pack('<Q', manager))
        runner.write(manager + 0x178 + 8, struct.pack('<Q', int.from_bytes(CONSOLE_CID, 'big')))
        runner.write(manager + 0x178 + 0x10, struct.pack('<H', CONSOLE_VAR))
        runner.write(reader + 0xb0, struct.pack('<Q', job))
        runner.write(job + 8, struct.pack('<I', job_state))     # running: `0x68cdf4`
        runner.write(buf, message)
        runner.call(0x6d7b10, (reader, buf, len(message)))
        assert runner.uc.reg_read(UC_ARM64_REG_PC) == RETURN
        return runner.uc.mem_read(job + 0x69, 1)[0] == 1

    assert answered(console.answer)
    assert not answered(console.answer, job_state=0)
    assert not answered(RETAIL_LEAVE)
    assert not answered(console.answer[:-1] + bytes([console.answer[-1] ^ 1]))


def test_the_joiner_leaves_at_the_consoles_first_net_start_host_migration(monkeypatch):
    """The console hands the host role over (Session type 7), then its NetDestroyNetworkJob resends
    NetStartHostMigration every 0.3 s until every client has left its network, for up to 4 s
    (13 sends over 3.5 to 4.1 s in 39 board seats the joiner held). Our joiner leaves at the first."""
    clock = Clock()
    keys = sv.session_keys(SSID)
    sent = []
    state = {'queue': [], 'first': None, 'destroys': 0, 'gone': False}

    def packet(body, protocol, flags=0):
        return sv_join.build_out(keys, HOST_IP, body, sv_join.OUR_VAR, protocol=protocol,
                                 flags=flags, src_var=RETAIL_HOST_VAR)

    state['queue'].append(packet(RETAIL_TYPE7, sv_join.PROTO_SESSION))
    start = clock.now

    def console_tick():
        clock.now += 0.05
        now = clock.now - start
        if state['gone'] or now < 0.11:
            return
        last = state['first'] + (state['destroys'] - 1) * DESTROY_RESEND if state['destroys'] else None
        if last is not None and now - state['first'] >= DESTROY_LIMIT:
            state['gone'] = True
            return
        if last is None or now - last >= DESTROY_RESEND:
            if state['first'] is None:
                state['first'] = now
            state['destroys'] += 1
            state['queue'].append(packet(NET_START_HOST_MIGRATION, sv_join.PROTO_NET, flags=0x11))

    class Socket:
        def sendto(self, packet, _):
            _, plain, _ = pia6.parse_packet(keys.session_key, JOIN_IP, keys.network_id, packet)
            sent.extend((m.protocol, bytes(m.payload)) for m in pia6.parse_messages(plain))

        def recvfrom(self, _):
            if state['queue']:
                return state['queue'].pop(0), (HOST_IP, sv.PIA_PORT)
            raise BlockingIOError

        def close(self):
            pass

    async def wait_readable(_):
        console_tick()
        await trio.lowlevel.checkpoint()

    rows = []
    monkeypatch.setattr(sv_join, 'time', clock)
    monkeypatch.setattr(sv_join, 'make_socket', lambda *a: Socket())
    monkeypatch.setattr(trio.lowlevel, 'wait_readable', wait_readable)
    args = sv_join.build_parser().parse_args([
        '--ip-join', '--hold', '10', '--no-clock', '--rtt-period', '0', '--answer-migration'])
    seat = trio.run(sv_join.run_session, args, keys, HOST_IP, HOST_MAC, JOIN_IP, JOIN_MAC,
                    lambda **row: rows.append(row))
    left = [r['t'] - start for r in rows if r['rec'] == 'left_on_host_migration']
    assert left, "the joiner held the seat through the console's NetStartHostMigration"
    assert state['destroys'] == 1
    assert left[0] - state['first'] < DESTROY_RESEND
    acks = [p for proto, p in sent if proto == sv_join.PROTO_SESSION and p[0] == 8]
    assert acks, "the type 7 went unanswered: the console resends it for up to 5 s (`0x6defb8`)"
    # With --take-host the run becomes bin/sv_host.py on the seat's channel, as bin/pla_join.py does.
    assert seat == {'handed': True, 'raided': False, 'circled': False}
    argv = sv_join.host_argv(args, 11, 30)
    host = sv_host.build_parser().parse_args(argv[argv.index('bin/sv_host.py') + 1:])
    assert (host.channel, host.seconds, host.code) == (11, 60, '')


def test_our_type_7_is_a_retail_hosts():
    """The raid host's handover names the console as a retail host named bin/sv_join.py."""
    assert pia_connect.build_session_migration_v11(
        CONSOLE_CID, RETAIL_HOST_VAR, "169.254.25.1", bytes.fromhex("24c93ad134e60000"), 0xC493,
        tail=1) == RETAIL_TYPE7


PAIR = os.path.join(ROOT, 'tests', 'data', 'sv_pair_trade.txt')


class TradingPeer:
    """The other side of a Scarlet trade, played by the other role's stage over 0x7C (pokeldn.sv.trade,
    pinned to a retail pair by tests/test_sv.py); answers a type-3 leave as a retail host does."""

    def __init__(self, clock, stage, own_ip, other_ip, own_var, other_var):
        self.clock, self.stage, self.own_ip, self.other_ip = clock, stage, own_ip, other_ip
        self.own_var, self.other_var = own_var, other_var
        self.keys = sv.session_keys(SSID)
        self.queue, self.seq, self.got, self.leaves = [], {}, set(), []

    def packet(self, body, protocol, port=0):
        return sv_join.build_out(self.keys, self.own_ip, body, self.other_var, protocol=protocol,
                                 port=port, src_var=self.own_var)

    def send_channel(self, port, payload):
        self.seq[port] = self.seq.get(port, 0) + 1
        self.queue.append(self.packet(game_channel.build_payload_message(payload, self.seq[port]),
                                      sv_join.PROTO_RELIABLE, port))

    def received(self, packet):
        _, plain, _ = pia6.parse_packet(self.keys.session_key, self.other_ip, self.keys.network_id,
                                        packet)
        for msg in pia6.parse_messages(plain):
            p = bytes(msg.payload)
            if msg.protocol == sv_join.PROTO_SESSION and p[:1] == bytes([pia_connect.SESSION_LEAVE_REQUEST]):
                self.leaves.append(self.clock.now)
                self.queue.append(self.packet(pia_connect.build_session_leave_response_v11(
                    p, random4=bytes(4)), sv_join.PROTO_SESSION))
            if msg.protocol != sv_join.PROTO_RELIABLE or len(p) < reliable5.HEADER_SIZE:
                continue
            rm = reliable5.parse(p)
            if not rm['flags'] & reliable5.FLAG_APPLICATION_DATA or (msg.port, rm['sequence_id']) in self.got:
                continue
            self.got.add((msg.port, rm['sequence_id']))
            for _delay, port, payload in self.stage.on_message(msg.port, rm['payload']):
                self.send_channel(port, payload)


def pair_offers(tmp_path):
    with open(PAIR, encoding='utf-8') as fh:
        rows = [line.split() for line in fh if line.strip()]
    host, joiner = bytes.fromhex(rows[2][2])[4:], bytes.fromhex(rows[3][2])[4:]
    (tmp_path / 'host.bin').write_bytes(host)
    (tmp_path / 'joiner.bin').write_bytes(joiner)
    return host, joiner


@pytest.mark.parametrize('extra, why, after', [
    (['--hold-after-trade', '2'], 'left_after_trade', 2.0),
    ([], 'left_at_hold', None),
])
def test_the_joiner_leaves_its_trade_seat_with_the_retail_leave(monkeypatch, tmp_path, extra, why, after):
    """The joiner sends the type-3 leave a retail station sends (`0x6db590`) when --hold ends, or
    --hold-after-trade seconds after its last queued trade, well inside --hold."""
    clock = Clock()
    start = clock.now
    host_offer, _ = pair_offers(tmp_path)
    host = TradingPeer(clock, trade.TradeStage(host_offer), HOST_IP, JOIN_IP, 1, 2)
    host.queue.append(host.packet(pia_connect.build_session_join_response_v11(
        pia_connect.ldn_constant_id(HOST_MAC), 1, pia_connect.ldn_constant_id(JOIN_MAC), 2,
        version=11, route=None), sv_join.PROTO_SESSION))
    host.send_channel(1, trade.table_update(trade.KEY_TRADE, True))
    for _delay, port, payload in host.stage.offer_first():
        host.send_channel(port, payload)

    class Socket:
        def sendto(self, packet, _):
            host.received(packet)

        def recvfrom(self, _):
            if host.queue:
                return host.queue.pop(0), (HOST_IP, sv.PIA_PORT)
            raise BlockingIOError

        def close(self):
            pass

    async def wait_readable(_):
        clock.now += 0.05
        await trio.lowlevel.checkpoint()

    rows = []
    monkeypatch.setattr(sv_join, 'time', clock)
    monkeypatch.setattr(ldn, '_time', clock)
    monkeypatch.setattr(ldn, '_done_at', None)
    monkeypatch.setattr(sv_join, 'make_socket', lambda *a: Socket())
    monkeypatch.setattr(trio.lowlevel, 'wait_readable', wait_readable)
    args = sv_join.build_parser().parse_args([
        '--ip-join', '--hold', '60', '--no-clock', '--rtt-period', '0',
        '--trade-offer', str(tmp_path / 'joiner.bin'), *extra])
    trio.run(sv_join.run_session, args, host.keys, HOST_IP, HOST_MAC, JOIN_IP, JOIN_MAC,
             lambda **row: rows.append(row))
    traded = [r['t'] for r in rows if r['rec'] == 'trade_done']
    left = [r for r in rows if r['rec'] == why]
    assert len(traded) == 1 and host.stage.done
    assert left and left[0]['answered'], "the joiner dropped its seat without the leave"
    assert len(host.leaves) == 1
    sent = host.leaves[0] - (traded[0] if after else start)
    assert (after or 60) <= sent < (after or 60) + 0.5
    assert left[0]['t'] - host.leaves[0] < 0.5


def test_the_host_closes_hold_after_trade_seconds_after_the_trade(monkeypatch, tmp_path):
    """With --hold-after-trade the host closes its session that long after the last queued trade
    while the console stays seated, well inside --seconds; the close is the one --seconds ends in."""
    clock = Clock()
    _, joiner_offer = pair_offers(tmp_path)
    console = TradingPeer(clock, trade.JoinerTradeStage(joiner_offer), JOIN_IP, HOST_IP,
                          CONSOLE_VAR, 1)
    console.queue.append(console.packet(pia6.build_session_join(
        CONSOLE_CID, CONSOLE_VAR, JOIN_IP, pia_connect.ldn_constant_id(HOST_MAC), 1, 'Player',
        bytes(4)), sv_host.PROTO_SESSION))
    stopped = []

    class Transport:
        ssid, our_ip, our_mac = SSID, HOST_IP, HOST_MAC
        participants, join_events = [(JOIN_MAC, JOIN_IP)], 1

        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            stopped.append(clock.now)

        def set_application_data(self, _):
            pass

        def send(self, packet, _):
            console.received(packet)
            if console.stage.opened and not console.stage.offered:
                for _delay, port, payload in console.stage.offer_first():
                    console.send_channel(port, payload)

        def wait_readable(self, _):
            clock.now += 0.05

        def recv(self):
            queued, console.queue = console.queue, []
            return [(packet, JOIN_IP) for packet in queued]

    done = []
    monkeypatch.setattr(sv_host, 'time', clock)
    monkeypatch.setattr(ldn, '_time', clock)
    monkeypatch.setattr(ldn, '_done_at', None)
    monkeypatch.setattr(sv_host, 'show_done', lambda: (done.append(clock.now), ldn.show_done()))
    monkeypatch.setattr(sv_host, 'IpHostTransport', Transport)
    monkeypatch.setattr(sv_host.pokemon_service, 'prepare_file', lambda game, path, **kw: path)
    start = clock.now
    monkeypatch.setattr('sys.argv', [
        'sv_host', '--ip-host', '--seconds', '120', '--no-net-probe', '--scarlet-response',
        '--no-session-update', '--session-flags', '0x00', '--no-identity',
        '--send-at', '0.5:0x7c:1:' + trade.table_update(trade.KEY_TRADE, True).hex(),
        '--trade-offer', str(tmp_path / 'host.bin'), '--hold-after-trade', '2'])
    assert sv_host.main() == 0
    assert len(done) == 1 and console.stage.done
    assert not console.leaves
    assert stopped and 2.0 <= stopped[0] - done[0] < 2.5
    assert stopped[0] - start < 120 / 2
