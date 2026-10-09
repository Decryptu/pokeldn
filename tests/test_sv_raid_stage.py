import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
RESEARCH = ROOT / "docs" / "research" / "sv" / "fixtures"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BIN))

from pokeldn import gen9
from pokeldn.ldn import reliable5
from pokeldn.sv import raid, streams


class RaidStageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows = [json.loads(line) for line in
                (RESEARCH / "tera_raid_retail_victory_full.jsonl").read_text().splitlines()]
        cls.capture = {}
        for row in rows:
            if (row.get("rec") == "data" and row.get("protocol") == 0x80
                    and row.get("port") == 0 and str(row.get("src", "")).endswith(".1")
                    and 1 <= row.get("seq", 0) <= 20):
                cls.capture.setdefault(row["seq"], row)

    def plain(self, sequence):
        row = self.capture[sequence]
        payload = bytes.fromhex(row["payload"])
        return (streams.decompress(payload)
                if row["reliable_flags"] & reliable5.FLAG_ZLIB else payload)

    def stage(self):
        host_pk9 = gen9.decrypt(self.plain(3)[18:])
        application = self.plain(11) + self.plain(12)
        metadata = {"species": 58, "stars": 2, "tera_type": 11,
                    "encounter_identifier": 2007}
        profile = {"form": 0, "gender": 0}
        return raid.RaidStage(metadata, profile, host_pk9, application)

    def test_generated_sequence_plaintexts_match_successful_opening(self):
        events = self.stage().events()
        self.assertEqual([event[1] for event in events], list(range(1, 21)))
        for _, sequence, flags, _, payload in events:
            generated = streams.decompress(payload) if flags & reliable5.FLAG_ZLIB else payload
            self.assertEqual(generated, self.plain(sequence), f"sequence {sequence}")

    def test_stage_transitions_are_idempotent(self):
        stage = self.stage()
        self.assertEqual(len(stage.lobby()), 10)
        self.assertEqual(stage.lobby(), [])
        self.assertEqual(len(stage.bootstrap()), 2)
        self.assertEqual(stage.bootstrap(), [])
        self.assertEqual(len(stage.loaded()), 1)
        self.assertEqual(stage.loaded(), [])
        self.assertEqual(len(stage.battle_ready()), 1)
        self.assertEqual(stage.battle_ready(), [])
        self.assertEqual(len(stage.handoff()), 6)
        self.assertEqual(stage.handoff(), [])

    def test_descriptor_fields_are_generated(self):
        payload = raid.descriptor(
            {"species": 280, "stars": 5, "tera_type": 17,
             "encounter_identifier": 1234},
            {"form": 2, "gender": 1})
        body = payload[18:]
        self.assertEqual(int.from_bytes(body[4:8], "little"), 280)
        self.assertEqual(int.from_bytes(body[8:12], "little"), 2)
        self.assertEqual(int.from_bytes(body[16:20], "little"), 5)
        self.assertEqual(int.from_bytes(body[20:24], "little"), 17)
        self.assertEqual(int.from_bytes(body[24:28], "little"), 1)
        self.assertEqual(int.from_bytes(body[28:32], "little"), 1234)

    def test_generated_joiner_messages_match_successful_capture(self):
        fixture = json.loads(
            (ROOT / "pokeldn/sv/data/raid_guest.json").read_text())
        captured = fixture["lobby"] + [fixture["ready"]]
        party = gen9.decrypt(bytes.fromhex(fixture["lobby"][1]["payload"])[18:])
        stage = raid.JoinerRaidStage(party)
        messages = stage.lobby() + stage.ready()
        self.assertEqual(len(messages), 3)
        for message, row in zip(messages, captured):
            expected = bytes.fromhex(row["payload"])
            expected = (streams.decompress(expected)
                        if row["flags"] & reliable5.FLAG_ZLIB else expected)
            actual = (streams.decompress(message.payload)
                      if message.flags & reliable5.FLAG_ZLIB else message.payload)
            self.assertEqual(actual, expected)
        start = stage.start_ack()[0]
        start_plain = streams.decompress(start.payload)
        self.assertEqual(int.from_bytes(start_plain[4:6], "little"), 4)
        self.assertEqual(int.from_bytes(start_plain[34:38], "little"), 0x0D)

    def test_generated_joiner_transitions_are_idempotent(self):
        party = gen9.decrypt(self.plain(3)[18:])
        stage = raid.JoinerRaidStage(party)
        self.assertEqual(len(stage.lobby()), 2)
        self.assertEqual(stage.lobby(), [])
        self.assertEqual(len(stage.ready()), 1)
        self.assertEqual(stage.ready(), [])
        self.assertEqual(len(stage.start_ack()), 1)
        self.assertEqual(stage.start_ack(), [])


if __name__ == "__main__":
    unittest.main()
