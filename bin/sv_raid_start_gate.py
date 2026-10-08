"""Capture-derived startup gates for the known sequence-1..20 host replay."""


class RaidStartGate:
    def __init__(self):
        self.seen = {}
        self.sent = set()

    def observe(self, protocol, port, payload, now):
        key = None
        if protocol == 0x80 and port == 0:
            if payload[:4] == bytes.fromhex('80332e01'):
                key = 'guest_lobby'
            elif (len(payload) == 42 and payload[:4] == bytes.fromhex('80332d01')
                  and payload[34:38] == bytes.fromhex('0d000000') and 10 in self.sent):
                key = 'guest_start'
            elif payload[:4] == bytes.fromhex('32016e00') and 12 in self.sent:
                key = 'load_6e'
            elif payload[:4] == bytes.fromhex('32017300') and 12 in self.sent:
                key = 'load_73'
            elif payload[:4] == bytes.fromhex('80349301') and 13 in self.sent:
                key = 'battle_93'
        elif (protocol == 0x2c and len(payload) >= 8 and payload[:2] == b'\x01\x51'
              and 'net' in self.sent):
            if int.from_bytes(payload[4:8], 'big') == self.net_sequence:
                key = 'net_ack'
        elif (protocol == 0x98 and len(payload) >= 12 and payload[0] == 6
              and 'session' in self.sent and int.from_bytes(payload[-2:], 'big') == 1):
            key = 'session_ack'
        if key and key not in self.seen:
            self.seen[key] = now
            return key

    def requirement(self, stage):
        # A fast host can otherwise send the first replay records before retail has published
        # its lobby record. Retail ACKs those records, but can later remain on Communicating
        # after the sequence-11/12 bootstrap instead of emitting load_6e.
        return {1: 'guest_lobby', 7: 'guest_lobby', 10: 'guest_lobby', 'net': 'guest_start',
                'session': 'net_ack', 11: 'session_ack', 13: 'load_6e',
                14: 'load_73', 15: 'battle_93'}.get(stage)

    def allowed(self, stage, now):
        key = self.requirement(stage)
        return key is None or (key in self.seen and now >= self.seen[key] + 0.05)
