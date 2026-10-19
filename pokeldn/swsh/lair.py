"""A Dynamax Adventure's (Max Lair, `chika`) messages on 0x80 port 0: the lobby holder id 7000
`ChikaAsyncDataHolder` and the between-battle holder id 8000 `UndergroundAsyncDataHolder`, each field
a holder of one field 1. `Guest` answers a host as an emulated Shield guest did (docs/swsh_raid.md,
Dynamax Adventures); the battles are `raid_battle.Guest`'s."""
import json
import random
import struct
from pathlib import Path

from pokeldn.swsh.trade import _read_fields, field, message

CHIKA, UNDERGROUND = 7000, 8000
# id 7000's fields
TIME_LIMIT, PLAYER_INFO, BATTLE_READY, SELECT_POKEMON, BATTLE_START = 1, 2, 3, 4, 5
BATTLE_SEED, RENTAL_SEED, PLAYER_NUMBER, BIG_BOSS, BIG_BOSS_FIXED = 8, 9, 11, 12, 13
# id 8000's fields
WAY_SELECT, WAY_RESULT, TRADE_WANT, TRADE_RESULT = 1, 3, 4, 6
RAID_CAPTURE, RAID_WANT, RAID_RESULT, UG_TIME_LIMIT = 10, 11, 12, 14
CHOICES = (WAY_SELECT, TRADE_WANT, RAID_CAPTURE, RAID_WANT)
NAME_CHARS = 13
PK8_PARTY = 0x158
# The rental an emulated Shield guest chose (Grimmsnarl, level 65, OT Scientist), encrypted party form.
RENTAL = Path(__file__).with_name("data") / "lair_rental.ek8"
POKEMON = Path(__file__).with_name("data") / "lair_pokemon.json"   # scripts/gen_swsh_lair_data.py
OFFER, ENCOUNTERS = 6, 10
# PlayerInfo's bytes after the name, the same from two emulated Shields; unread.
PLAYER_INFO_TAIL = bytes.fromhex("0002000000002d000000")


def holder(which_id, which, data):
    return message(which_id, field(which, field(1, data)))


def parse(payload):
    """-> (holder id, field, value) for an id-7000 or id-8000 payload, value bytes or int; or None."""
    if len(payload) < 5:
        return None
    which_id = struct.unpack_from("<I", payload, 0)[0]
    if which_id not in (CHIKA, UNDERGROUND):
        return None
    outer = _read_fields(payload[4:])
    if len(outer) != 1:
        return None
    (which, inner), = outer.items()
    value = _read_fields(inner).get(1, b"") if isinstance(inner, bytes) else inner
    return which_id, which, value


def player_info(name):
    """48 bytes: 12 zero, the UTF-16 name in 13 characters, then the tail two emulated Shields sent."""
    raw = name.encode("utf-16-le")
    if len(raw) > 2 * (NAME_CHARS - 1):
        raise ValueError(f"{name!r} is longer than {NAME_CHARS - 1} characters")
    return holder(CHIKA, PLAYER_INFO, bytes(12) + raw.ljust(2 * NAME_CHARS, b"\0") + PLAYER_INFO_TAIL)


def battle_ready(ready=False, started=False):
    body = bytearray(16)
    body[8], body[12] = int(ready), int(started)
    return holder(CHIKA, BATTLE_READY, bytes(body))


def big_boss():
    """Byte 12 is 1 from both emulated players; unread."""
    return holder(CHIKA, BIG_BOSS, bytes(12) + b"\x01" + bytes(3))


def select_pokemon(pk8, choice):
    """8 zero bytes, u32 (0 from the host, 2 from the guest: the rental's place in the offer, read
    from one adventure), the rental as an encrypted party PK8, four zero bytes."""
    pk8 = bytes(pk8)
    if len(pk8) != PK8_PARTY:
        raise ValueError(f"{len(pk8)} bytes is not a party PK8 ({PK8_PARTY:#x})")
    return holder(CHIKA, SELECT_POKEMON, bytes(8) + struct.pack("<I", choice) + pk8 + bytes(4))


def choice(which, station, index, value):
    """WaySelect, TradeWant, RaidCapture or RaidWant: constant id, player index, the choice."""
    return holder(UNDERGROUND, which, struct.pack("<QBB", station, index, value) + bytes(6))


def parse_choice(data):
    """-> (constant id, player index, choice) of a 16-byte choice record."""
    return struct.unpack_from("<QBB", data, 0)


def pokemon_result(which, data):
    """-> (player index or None, encrypted party PK8) of a RaidResult or TradeResult."""
    if which == RAID_RESULT:
        index, at = data[8], 10
    else:
        index, at = data[8], 11
    return (None if index == 0xFF else index), bytes(data[at:at + PK8_PARTY])


class Guest:
    """Feed every host id-7000/8000 payload to `receive`; it returns payloads to send in order.
    `start()` is the guest's first three. Each choice answers the host player's own choice of the
    same kind: the host's path, catch prompt 1, never taking or swapping a caught Pokemon."""

    def __init__(self, station, pk8=None, name="POKELDN", rental_choice=None, log=print, rand=None):
        """`pk8` and `rental_choice` fix the rental sent; by default it is the first place of the
        offer the seed gives that the host did not take, built as the game builds one."""
        self.station, self.pk8, self.name = station, pk8 and bytes(pk8), name
        self.rand = rand
        self.seed = None
        self.partners = 2
        self.rental_choice, self.log = rental_choice, log
        self.host = None
        self.index = None
        self.ready_sent = self.started_sent = self.selected = False
        self.legendary = None
        self.battle = 0
        self.taken = []                  # (player index or None, PK8) per RaidResult / TradeResult

    def start(self):
        return [player_info(self.name), battle_ready(), big_boss()]

    def _select(self, taken):
        place = self.rental_choice
        if place is None:
            place = next(p for p in range(3) if p != taken)
        if self.pk8 is None:
            if self.seed is None:
                raise ValueError("no BattleSeed before the host's rental")
            offer, _ = adventure(self.seed, self.partners)
            self.pk8 = rental_pk8(offer[place], self.rand)
            self.log(f"[lair] the host took offer place {taken}; we take place {place}, "
                     f"species {offer[place][0]}")
        return select_pokemon(self.pk8, place)

    def receive(self, payload):
        got = parse(payload)
        if got is None:
            return []
        which_id, which, value = got
        out = []
        if which_id == CHIKA:
            if which == BATTLE_READY and value[8] and not self.ready_sent:
                self.ready_sent = True
                self.log("[lair] the host is ready; so are we")
                out.append(battle_ready(True))
            elif which == BATTLE_SEED:
                self.seed = value
            elif which == PLAYER_NUMBER:
                ids = struct.unpack_from("<4Q", value, 0)
                self.partners = ids.count(0)
                self.host = ids[0]
                self.index = value[32 + ids.index(self.station)] if self.station in ids else None
                self.log(f"[lair] players {[hex(i) for i in ids]}, we are index {self.index}")
                if not self.started_sent:
                    self.started_sent = True
                    out.append(battle_ready(True, started=True))
            elif which == BIG_BOSS_FIXED:
                self.legendary = struct.unpack_from("<I", value, 0)[0]
                self.log(f"[lair] the legendary is species {self.legendary}")
            elif which == SELECT_POKEMON and not self.selected:
                # Rentals go in turns, the host's first (docs/swsh_raid.md, Hosting an adventure).
                self.selected = True
                out.append(self._select(struct.unpack_from("<I", value, 8)[0]))
            return out
        if which in CHOICES:
            station, index, picked = parse_choice(value)
            if station == 0 or station == self.station or index != 0 or self.index is None:
                return out
            mine = {WAY_SELECT: picked, RAID_CAPTURE: 1, RAID_WANT: 0, TRADE_WANT: 0}[which]
            out.append(choice(which, self.station, self.index, mine))
            self.log(f"[lair] host field {which} chose {picked}; we answer {mine}")
        elif which == WAY_RESULT:
            self.log(f"[lair] path {value[0] if isinstance(value, bytes) and value else value}")
        elif which in (RAID_RESULT, TRADE_RESULT):
            index, pk8 = pokemon_result(which, value)
            self.taken.append((index, pk8))
            if which == TRADE_RESULT and index == self.index:
                self.pk8 = pk8
            self.log(f"[lair] field {which}: player {index} takes the caught Pokemon")
        return out


def table():
    """-> the adventure's rows [species, form, legendary, level, type 1, type 2, moves...]."""
    return json.loads(POKEMON.read_text())["rows"]


def legendaries():
    return sorted({row[0] for row in table() if row[2]})


MASK64 = (1 << 64) - 1


class _Xoroshiro:
    def __init__(self, seed):
        self.s0, self.s1 = seed & MASK64, 0x82A2B175229D6A5B

    def next(self):
        s0, s1 = self.s0, self.s1
        out = (s0 + s1) & 0xFFFFFFFF
        s1 ^= s0
        self.s0 = ((s0 << 24 | s0 >> 40) ^ s1 ^ (s1 << 16)) & MASK64
        self.s1 = (s1 << 37 | s1 >> 27) & MASK64
        return out

    def draw(self, top):
        return _draw(self.next, top, (1 << top.bit_length()) - 1)


def _draw(next32, top, mask):
    """A value in 0..top: masked outputs, redrawn while above."""
    while True:
        value = next32() & mask
        if value <= top:
            return value


def _mt19937(seed):
    state = [seed]
    for i in range(1, 624):
        state.append((1812433253 * (state[-1] ^ state[-1] >> 30) + i) & 0xFFFFFFFF)
    while True:
        for i in range(624):
            y = (state[i] & 0x80000000) | (state[(i + 1) % 624] & 0x7FFFFFFF)
            state[i] = state[(i + 397) % 624] ^ y >> 1 ^ (0x9908B0DF if y & 1 else 0)
        for y in state:
            y ^= y >> 11
            y ^= y << 7 & 0x9D2C5680
            y ^= y << 15 & 0xEFC60000
            yield y ^ y >> 18


def adventure(seed, partners=2, rows=None):
    """-> (offer, encounters): the six rental rows and the ten encounter rows ChikaBattleSeed `seed`
    gives with `partners` computer partners (docs/swsh_raid.md, The adventure seed)."""
    rows = table() if rows is None else rows
    rng, picked = _Xoroshiro(seed), []

    def pick():
        mt = _mt19937(rng.next()).__next__
        order = list(range(len(rows)))
        for i in range(len(order)):
            j = i + _draw(mt, len(order) - i - 1, 0x1FF)
            order[i], order[j] = order[j], order[i]
        taken = {(r[0], r[1]) for r in picked}
        row = next(rows[i] for i in order if not rows[i][2] and (rows[i][0], rows[i][1]) not in taken)
        picked.append(row)
        return row

    if partners > 2:
        rng.draw(27)
    for _ in range(4):
        pick()
    for threshold in (2, 1, 0):
        if partners > threshold:
            rng.draw(2)
        if threshold:
            pick()
    rng.draw(2)
    rng.draw(9)
    for _ in range(ENCOUNTERS):
        if pick()[4] != picked[-1][5]:
            rng.next()
    return picked[:OFFER], picked[OFFER:]


RENTAL_FLAWLESS_IVS = 4               # every recorded rental and catch had four IVs of 31


def rental_pk8(row, rand=None, template=None):
    """-> the encrypted party record of the rental `row` as the game makes one, on the recorded
    rental: OT Scientist, Poke Ball, met at level 65, the row's moves, four IVs of 31, a random
    nature, ability slot 1 or 2, gender, PID and encryption constant (docs/swsh_raid.md)."""
    from pokeldn import gen8
    from pokeldn.sv import raid_encounter as encounter
    from pokeldn.swsh import raid_event

    rand = rand or random.SystemRandom()
    species, form, level, moves = row[0], row[1], row[3], tuple(row[6:10])
    base, ratio, growth, abilities = raid_event.personal(species, form)
    plain = gen8.decrypt(template if template is not None else RENTAL.read_bytes())
    ivs = [None] * 6
    for k in rand.sample(range(6), RENTAL_FLAWLESS_IVS):
        ivs[k] = 31
    ivs = tuple(rand.randrange(32) if iv is None else iv for iv in ivs)
    nature, slot = rand.randrange(25), rand.randrange(2)
    gender = (2 if ratio == 0xFF else 1 if ratio == 0xFE else 0 if ratio == 0
              else int(rand.randrange(100) < encounter.GENDER_CUTOFF.get(ratio, ratio * 100 // 253)))
    stats = encounter.stats(base, ivs, level, nature)
    pp = raid_event.tables()["move_pp"]
    out = bytearray(gen8.write(
        plain, species=species, form=form, level=level, experience=encounter.experience(level, growth),
        moves=moves, move_pp=tuple(pp.get(str(m), 0) if m else 0 for m in moves), move_pp_ups=(0,) * 4,
        ability=abilities[slot], ivs=ivs, evs=(0,) * 6, nature=nature, gender=gender,
        pid=rand.getrandbits(32), encryption_constant=rand.getrandbits(32), held_item=0, stats=stats))
    out[raid_event.OFF_ABILITY_NUMBER] = (out[raid_event.OFF_ABILITY_NUMBER] & ~0x07) | 1 << slot
    struct.pack_into("<H", out, raid_event.OFF_HP_CURRENT, stats[0])
    return gen8.encrypt(bytes(out))
