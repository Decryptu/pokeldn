from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BIN))

from pokeldn import gen9
from pokeldn.ldn import reliable5
from pokeldn.sv import raid, raid_generation, streams
from sv_raid_bootstrap_codec import (
    build_application, build_raid_boss_pk9, build_seed_bootstrap_raw,
)


class RaidStageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        generated = raid_generation.generate_seed_raid(0xBD13FB43)
        cls.metadata = generated["metadata"]
        cls.profile = generated["profile"]
        cls.host_pk9 = build_raid_boss_pk9(cls.profile)
        raw = build_seed_bootstrap_raw(
            0xBD13FB43, point_name="RaidPoint_12_1_11", players=(cls.host_pk9,))
        cls.application = build_application(raw, message_value=0x010F)

    def stage(self):
        return raid.RaidStage(
            self.metadata, self.profile, self.host_pk9, self.application)

    def test_generated_sequence_contains_the_complete_protocol_opening(self):
        events = self.stage().events()
        self.assertEqual([event[1] for event in events], list(range(1, 21)))
        plain = {
            sequence: (streams.decompress(payload)
                       if flags & reliable5.FLAG_ZLIB else payload)
            for _, sequence, flags, _, payload in events
        }
        self.assertEqual(plain[1], raid.descriptor(self.metadata, self.profile))
        self.assertEqual(plain[2], raid.state(0x0106, 0x18, initial=True))
        self.assertEqual(plain[3], raid.pokemon(0x0107, self.host_pk9))
        self.assertEqual(plain[11] + plain[12], self.application)
        self.assertEqual(plain[13], raid.load_transition("load"))
        self.assertEqual(plain[14], raid.load_transition("battle"))
        self.assertEqual(tuple(plain[index] for index in range(15, 21)),
                         raid.battle_handoff())

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

    def test_generated_joiner_messages_have_the_complete_protocol_shape(self):
        stage = raid.JoinerRaidStage(self.host_pk9)
        messages = stage.lobby() + stage.ready()
        actual = [streams.decompress(message.payload)
                  if message.flags & reliable5.FLAG_ZLIB else message.payload
                  for message in messages]
        self.assertEqual(actual, [
            raid.state(1, 0x18),
            raid.pokemon(2, self.host_pk9),
            raid.state(3, 0x01),
        ])
        start = stage.start_ack()[0]
        start_plain = streams.decompress(start.payload)
        self.assertEqual(int.from_bytes(start_plain[4:6], "little"), 4)
        self.assertEqual(int.from_bytes(start_plain[34:38], "little"), 0x0D)

    def test_generated_joiner_transitions_are_idempotent(self):
        stage = raid.JoinerRaidStage(self.host_pk9)
        self.assertEqual(len(stage.lobby()), 2)
        self.assertEqual(stage.lobby(), [])
        self.assertEqual(len(stage.ready()), 1)
        self.assertEqual(stage.ready(), [])
        self.assertEqual(len(stage.start_ack()), 1)
        self.assertEqual(stage.start_ack(), [])


if __name__ == "__main__":
    unittest.main()
