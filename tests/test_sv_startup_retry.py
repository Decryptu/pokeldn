"""Offline regression checks for sv_host's actual nested startup send functions."""
import ast
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BIN))

import sv_host
from pokeldn import gen9
from pokeldn.ldn import reliable5
from pokeldn.sv import raid_generation
from sv_raid_bootstrap_codec import (
    build_application, build_raid_boss_pk9, build_seed_bootstrap_raw,
    decode_application,
)


class StartupRetryTests(unittest.TestCase):
    def setUp(self):
        self.env = dict(vars(sv_host))
        self.sent = []
        self.records = []
        self.ip = '169.254.1.2'
        players = tuple(
            build_raid_boss_pk9(raid_generation.generate_seed_raid(seed)["profile"])
            for seed in (1, 2, 3, 4)
        )
        self.original = build_seed_bootstrap_raw(0xBD13FB43, players=players)
        application = build_application(self.original, message_value=0x010F)
        boundary = 1395
        replay = [
            (0.2, 11, 0x02, 11, application[:boundary]),
            (0.3, 12, 0x04, 11, application[boundary:]),
        ]
        self.env.update(
            args=SimpleNamespace(raid_replay_client_gated=True, record_set='records'),
            disconnect_after_stop=5,
            stop_after_seq=20,
            transport=SimpleNamespace(our_ip='169.254.1.1', broadcast='169.254.1.255',
                                      send=lambda packet, ip: self.sent.append((packet, ip))),
            keys=None, build_reply=lambda keys, ip, body, *a, **kw: body,
            station_ids={self.ip: {'console_var': 42, 'host_const': bytes.fromhex(
                'cc6d5aeb38a40000')}},
            pending_raid_bootstrap={}, pending_late={}, pending_records={},
            pending_raid_replay=[
                (10 + delay, self.ip, sequence, flags, lowest, payload)
                for delay, sequence, flags, lowest, payload in replay],
            raid_replay_events=replay, raid_guest_pokemon={}, raid_guest_waits={self.ip},
            identity_window=reliable5.SendWindow(.25),
            channel_window=reliable5.SendWindow(.25),
            raid_window=reliable5.SendWindow(.5),
            host_seq={}, stream_high={}, last_ack={}, raid_replay_started_at={},
            last_raid_replay_sent={}, scripted_disconnect_due={},
            record=lambda **kw: self.records.append(kw),
        )
        tree = ast.parse(Path(sv_host.__file__).read_text())
        for name in ('schedule_raid_opening', 'install_raid_guest_pokemon',
                     'outbound_lowest', 'send_ack', 'send_raid_replay'):
            node = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef) and n.name == name)
            exec(compile(ast.Module(body=[node], type_ignores=[]),
                         sv_host.__file__, 'exec'), self.env)

    def test_raid_opening_is_scheduled_relative_to_session_ack(self):
        acknowledged_at = 12.5
        self.assertEqual(self.env['pending_raid_bootstrap'], {})
        self.assertEqual(self.env['pending_late'], {})
        self.assertEqual(self.env['pending_records'], {})

        self.env['schedule_raid_opening'](self.ip, acknowledged_at)

        self.assertEqual(self.env['pending_raid_bootstrap'][self.ip], acknowledged_at)
        self.assertEqual(
            {key: due for key, (due, _) in self.env['pending_late'].items()},
            {(self.ip, 'raid0'): acknowledged_at,
             (self.ip, 'raid1'): acknowledged_at,
             (self.ip, 'raid2'): acknowledged_at})
        self.assertEqual(self.env['pending_records'][self.ip], acknowledged_at + 0.02)
        self.assertEqual(self.records[-1]['rec'], 'raid_session_ready')

    def test_guest_lobby_pokemon_late_binds_pending_bootstrap(self):
        original = self.original
        guest = original[:gen9.SIZE_PARTY]

        self.env['install_raid_guest_pokemon'](self.ip, guest)

        fragments = {
            sequence: payload
            for _, peer, sequence, _, _, payload in self.env['pending_raid_replay']
            if peer == self.ip and sequence in (11, 12)
        }
        changed = decode_application(fragments[11] + fragments[12])
        self.assertEqual(
            changed[gen9.SIZE_PARTY:2 * gen9.SIZE_PARTY], guest)
        self.assertEqual(changed[:gen9.SIZE_PARTY], original[:gen9.SIZE_PARTY])
        self.assertEqual(self.env['raid_guest_pokemon'][self.ip], guest)
        self.assertNotIn(self.ip, self.env['raid_guest_waits'])
        self.assertEqual(self.records[-1]['pending_fragments'], 2)

    def test_startup_ack_cannot_skip_unacknowledged_open(self):
        for protocol, port, window in ((0x81, 1, 'channel_window'),
                                       (0x81, 5, 'channel_window'),
                                       (0x80, 2, 'channel_window'),
                                       (0x80, 0, 'raid_window')):
            key = (self.ip, protocol, port)
            self.env['host_seq'][key] = 2
            w = self.env[window]
            w.sent(key, 1, b'original', 0)
            w.acked(key, 1)
            self.env['send_ack'](self.ip, protocol, port, 42, 'test')
            self.assertEqual(reliable5.parse(self.sent[-1][0])['lowest_pending'], 1)
            self.assertEqual(w.due(1)[0][1:], (1, b'original'))
            w.acked(key, 2)
            self.env['send_ack'](self.ip, protocol, port, 42, 'test')
            self.assertEqual(reliable5.parse(self.sent[-1][0])['lowest_pending'], 2)
            self.assertEqual(w.due(2), [])

    def test_replay_retry_preserves_cursor_and_handoff_deadline(self):
        send = self.env['send_raid_replay']
        send(self.ip, 19, 7, b'previous', 'raid replay', remember=True)
        send(self.ip, 20, 7, b'last', 'raid replay', remember=True)
        cursor = self.env['last_raid_replay_sent'][self.ip]
        deadline = self.env['scripted_disconnect_due'][self.ip]
        send(self.ip, 19, 7, b'previous', 'raid retry', remember=False)
        self.assertEqual(self.env['last_raid_replay_sent'][self.ip], cursor)
        send(self.ip, 20, 7, b'last', 'raid retry', remember=False)
        self.assertEqual(self.env['scripted_disconnect_due'][self.ip], deadline)
        packet = reliable5.parse(self.sent[-1][0])
        self.assertEqual(packet['sequence_id'], 20)
        self.assertEqual(packet['lowest_pending'], 19)


if __name__ == '__main__':
    unittest.main()
