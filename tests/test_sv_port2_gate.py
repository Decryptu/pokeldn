"""A console seated on our Scarlet host that never sends its port-2 join is named against the
BoxTrade gate holding it (docs/sv.md, Unresolved): state 1 while our identity is unacknowledged,
state 4 once all of it is."""
import pytest

import sv_host
import sv_join
from pokeldn import sv
from pokeldn.ldn import pia6, pia_connect, reliable5
from test_sv_departure import (Clock, CONSOLE_CID, CONSOLE_VAR, HOST_IP, HOST_MAC, JOIN_IP,
                               JOIN_MAC, SSID)


class SilentConsole:
    """Joins, takes the announcement and never answers it; acknowledges our 0x81 port 0 identity
    with the bulk ack a retail station sends, or not at all."""

    def __init__(self, clock, ack_identity):
        self.clock, self.ack_identity = clock, ack_identity
        self.keys = sv.session_keys(SSID)
        self.identity_high, self.queue = 0, []
        join = pia6.build_session_join(CONSOLE_CID, CONSOLE_VAR, JOIN_IP,
                                       pia_connect.ldn_constant_id(HOST_MAC), 1, 'Player',
                                       bytes(4))
        self.queue.append(sv_join.build_out(self.keys, JOIN_IP, join, 1,
                                            protocol=sv_host.PROTO_SESSION, src_var=CONSOLE_VAR))

    def received(self, packet):
        _, plain, _ = pia6.parse_packet(self.keys.session_key, HOST_IP, self.keys.network_id,
                                        packet)
        for msg in pia6.parse_messages(plain):
            if msg.protocol != sv_host.PROTO_STREAM_BROADCAST_RELIABLE or msg.port != 0:
                continue
            rm = reliable5.parse(msg.payload)
            if rm["flags"] & reliable5.FLAG_APPLICATION_DATA:
                self.identity_high = max(self.identity_high, rm["sequence_id"])

    def tick(self):
        self.clock.now += 0.05
        if self.ack_identity and self.identity_high:
            body = sv_host.build_bulk_ack({0: self.identity_high}, 1)
            self.queue.append(sv_join.build_out(
                self.keys, JOIN_IP, body, sv_host.PIA_HOST_VAR,
                protocol=sv_host.PROTO_STREAM_BROADCAST_RELIABLE, src_var=CONSOLE_VAR))


@pytest.mark.parametrize('ack_identity, gate', [(False, 'the state-1 gate'),
                                                (True, 'the state-4 gate')])
def test_a_held_console_is_named_against_its_gate(monkeypatch, capsys, ack_identity, gate):
    clock = Clock()
    console = SilentConsole(clock, ack_identity)

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
        'sv_host', '--ip-host', '--seconds', '30', '--no-net-probe', '--scarlet-response',
        '--no-session-update', '--session-flags', '0x00', '--announce'])
    assert sv_host.main() == 0
    out = capsys.readouterr().out
    assert console.identity_high > 1, "the host sent no identity"
    verdicts = [line for line in out.splitlines() if 'no port-2 join' in line]
    assert len(verdicts) == 1 and verdicts[0].endswith(gate), verdicts
