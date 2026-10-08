"""Offline regression checks for sv_host's actual nested startup send functions."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

import sv_host
from pokeldn.ldn import reliable5


class StartupRetryTests(unittest.TestCase):
    def setUp(self):
        self.env = dict(vars(sv_host))
        self.sent = []
        self.records = []
        self.ip = '169.254.1.2'
        self.env.update(
            args=SimpleNamespace(raid_replay_client_gated=True),
            disconnect_after_stop=5,
            stop_after_seq=20,
            transport=SimpleNamespace(our_ip='169.254.1.1', broadcast='169.254.1.255',
                                      send=lambda packet, ip: self.sent.append((packet, ip))),
            keys=None, build_reply=lambda keys, ip, body, *a, **kw: body,
            station_ids={self.ip: {'console_var': 42}},
            identity_window=reliable5.SendWindow(.25),
            channel_window=reliable5.SendWindow(.25),
            raid_window=reliable5.SendWindow(.5),
            host_seq={}, stream_high={}, last_ack={}, raid_replay_started_at={},
            last_raid_replay_sent={}, scripted_disconnect_due={},
            record=lambda **kw: self.records.append(kw),
        )
        tree = ast.parse(Path(sv_host.__file__).read_text())
        for name in ('outbound_lowest', 'send_ack', 'send_raid_replay'):
            node = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef) and n.name == name)
            exec(compile(ast.Module(body=[node], type_ignores=[]),
                         sv_host.__file__, 'exec'), self.env)

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
