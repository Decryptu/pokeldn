"""The live SV senders recover a missing identity chunk without declaring it obsolete."""
import pytest
import trio

import sv_host
import sv_join
from pokeldn import sv
from pokeldn.ldn import pia6, pia_connect, reliable5
from pokeldn.sv import streams

HOST_IP, JOIN_IP = '127.0.0.2', '127.0.0.3'
HOST_MAC, JOIN_MAC = bytes.fromhex('02007f000002'), bytes.fromhex('02007f000003')
SSID = bytes.fromhex('7b744617795970bb6882b24ded4cae15')


class Clock:
    def __init__(self):
        self.now = 100.0

    def time(self):
        return self.now

    monotonic = time


class Peer:
    def __init__(self, clock, sender_index, lost):
        self.clock, self.sender_index, self.lost = clock, sender_index, lost
        self.keys = sv.session_keys(SSID)
        self.queue, self.received, self.records, self.retries = [], set(), set(), []
        self.dropped, self.initialized, self.low = False, False, 1
        self.ip = HOST_IP if sender_index == 1 else JOIN_IP
        self.sender_ip = JOIN_IP if sender_index == 1 else HOST_IP

    def packet(self, body, protocol, port=0):
        return sv_join.build_out(self.keys, self.ip, body, 2 if self.sender_index == 1 else 1,
                                 protocol=protocol, port=port,
                                 src_var=1 if self.sender_index == 1 else 2)

    def send(self, packet):
        _, plain, _ = pia6.parse_packet(self.keys.session_key, self.sender_ip,
                                        self.keys.network_id, packet)
        for msg in pia6.parse_messages(plain):
            if msg.protocol != 0x81 or msg.port != self.sender_index:
                continue
            rm = reliable5.parse(msg.payload)
            self.low = max(self.low, rm['lowest_pending'])
            self.received.update(range(1, self.low))
            if rm['flags'] & reliable5.FLAG_APPLICATION_DATA:
                seq = rm['sequence_id']
                if seq == self.lost and not self.dropped:
                    self.dropped = True
                    continue
                if msg.message_flags & 0x40:
                    self.retries.append(seq)
                if rm['flags'] & reliable5.FLAG_IS_INITIALIZED:
                    self.initialized = True
                if not self.initialized:
                    continue
                if seq >= self.low:
                    self.records.add(seq)
                    self.received.add(seq)
            through, mask = streams.ack_position(self.received)
            ack = streams.build_ack({self.sender_index: through}, 2, 1 - self.sender_index,
                                     masks={self.sender_index: mask})
            self.queue[:] = [(self.packet(ack, 0x81, self.sender_index), (self.ip, sv.PIA_PORT))]

    def wait(self):
        self.clock.now += 0.05


@pytest.mark.parametrize('lost', [1, 10, None])
def test_joiner_identity_survives_loss(monkeypatch, tmp_path, lost):
    clock = Clock()
    peer = Peer(clock, 1, lost)
    ids = [1, 2, 3, 4, 7, 8, 10, 46]
    for seq in ids:
        (tmp_path / f'{seq:03d}.bin').write_bytes(streams.compress(bytes([1, seq])))
    response = pia_connect.build_session_join_response_v11(
        pia_connect.ldn_constant_id(HOST_MAC), 1, pia_connect.ldn_constant_id(JOIN_MAC), 2,
        version=11, route=None)
    peer.queue.append((peer.packet(response, sv_join.PROTO_SESSION), (HOST_IP, sv.PIA_PORT)))

    class Socket:
        def sendto(self, packet, _):
            peer.send(packet)

        def recvfrom(self, _):
            if peer.queue:
                return peer.queue.pop(0)
            raise BlockingIOError

        def close(self):
            pass

    async def wait_readable(_):
        peer.wait()
        await trio.lowlevel.checkpoint()

    monkeypatch.setattr(sv_join, 'time', clock)
    monkeypatch.setattr(sv_join, 'make_socket', lambda *a: Socket())
    monkeypatch.setattr(trio.lowlevel, 'wait_readable', wait_readable)
    args = sv_join.build_parser().parse_args([
        '--ip-join', '--hold', '2', '--record-set', str(tmp_path), '--record-delay', '0',
        '--no-clock', '--rtt-period', '0'])
    trio.run(sv_join.run_session, args, peer.keys, HOST_IP, HOST_MAC, JOIN_IP, JOIN_MAC,
             lambda **row: None)
    assert peer.records == set(ids)
    assert peer.low == 47
    expected = ids if lost == 1 else [] if lost is None else [lost]
    assert sorted(peer.retries) == sorted(expected)


@pytest.mark.parametrize('lost', [1, 10, None])
def test_host_identity_survives_loss(monkeypatch, tmp_path, lost):
    clock = Clock()
    peer = Peer(clock, 0, lost)
    ids = [1, 2, 3, 46, 4, 7, 10, 8]
    for seq in ids:
        (tmp_path / f'{seq:03d}.bin').write_bytes(streams.compress(bytes([1, seq])))
    (tmp_path / 'order').write_text('\n'.join(map(str, ids)))
    join = pia6.build_session_join(pia_connect.ldn_constant_id(JOIN_MAC), 2, JOIN_IP,
                                   pia_connect.ldn_constant_id(HOST_MAC), 1, 'Player', bytes(4))
    peer.queue.append((peer.packet(join, sv_host.PROTO_SESSION), (JOIN_IP, sv.PIA_PORT)))

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
            peer.send(packet)

        def wait_readable(self, _):
            peer.wait()

        def recv(self):
            queued, peer.queue = peer.queue, []
            return [(packet, addr[0]) for packet, addr in queued]

    monkeypatch.setattr(sv_host, 'time', clock)
    monkeypatch.setattr(sv_host, 'IpHostTransport', Transport)
    monkeypatch.setattr('sys.argv', [
        'sv_host', '--ip-host', '--seconds', '2', '--record-set', str(tmp_path),
        '--record-delay', '0', '--no-net-probe', '--records-per-packet', '3',
        '--scarlet-response', '--no-session-update'])
    assert sv_host.main() == 0
    assert peer.records == set(ids)
    assert peer.low == 47
    expected = ids if lost == 1 else [] if lost is None else [lost]
    assert sorted(peer.retries) == sorted(expected)
