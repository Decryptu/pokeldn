"""An event Tera Raid from its Poke Portal News delivery (docs/sv_raid.md, Event raids): the four
FlatBuffers tables a delivery holds (`raid_enemy_array`, `fixed_reward_item_array`,
`lottery_reward_item_array`, `raid_priority_array`) and its `event_raid_identifier`, as Project
Pokemon's EventsGallery keeps them; the encounter a seed draws in a delivery group at a story stage;
and the boss and rewards `pokeldn.sv.raid_encounter` makes of it, a `Raid` the host stages as it
stages a standard one.
"""

from dataclasses import dataclass, replace
import os
import struct

from pokeldn import gen9
from pokeldn.sv import raid_encounter as encounter

# From 1.3.0 a delivery carries every table again under the patch it is for, the older copy dummied
# out; the newest the game reads wins [pkNX TeraRaidRipper.DumpDistributionRaids].
PATCHES = ("_3_0_0", "_2_0_0", "_1_3_0", "")
ENEMY, FIXED, LOTTERY, PRIORITY = ("raid_enemy_array", "fixed_reward_item_array",
                                   "lottery_reward_item_array", "raid_priority_array")

# The star levels an event encounter is drawn among at each story stage, and the stage of each
# progress [pkNX TeraRaidRipper.StageStars, Tera-Finder EventUtil.GetEventStageFromProgress].
STAGE_STARS = ((1, 2), (1, 2, 3), (1, 2, 3, 4), (3, 4, 5, 6, 7))
STAGES = {"beginning": 0, "tera": 0, "3star": 1, "4star": 2, "5star": 3, "6star": 3}
ROM_BOTH, ROM_SCARLET, ROM_VIOLET = 0, 1, 2
TALENT_RANDOM, TALENT_FLAWLESS, TALENT_VALUE = 0, 1, 2
# A record's CaptureRate: never caught, caught as any raid boss, or caught once per save, the save
# keeping the record numbers caught (PKHeX RaidSevenStar9; a rerun repeats its number).
CAPTURE_NEVER, CAPTURE_NORMAL, CAPTURE_ONCE = 0, 1, 2
CATCH_RULES = {CAPTURE_NEVER: "cannot be caught", CAPTURE_NORMAL: "caught as any raid boss",
               CAPTURE_ONCE: "caught once per save"}
# A record number is its delivery's date and a suffix, at most 14 in every delivery (2026-09-06); a
# catch-once record served as a normal one takes 99, which no save has caught.
STAND_IN = 99
MIGHTY = 7
# The save's raid content: the crystal word of the RaidPoint (docs/sv_raid.md, The battle bootstrap).
CONTENT_EVENT, CONTENT_MIGHTY = "event", "might"
GROUPS = 10

# The tables' FlatBuffers schemas [pkNX FlatBuffers/SV], fields in vtable order and named as
# EventsGallery's JSON names them: a struct format for a scalar, a tuple for a table, a one-item
# list for a vector of tables.
WAZA = (("WazaId", "H"), ("PointUp", "b"))
PARAMS = tuple((name, "i") for name in ("HP", "ATK", "DEF", "SPA", "SPD", "SPE"))
POKE = (("DevId", "H"), ("FormId", "h"), ("Sex", "i"), ("Item", "i"), ("Level", "i"),
        ("BallId", "i"), ("WazaType", "i"), ("Waza1", WAZA), ("Waza2", WAZA), ("Waza3", WAZA),
        ("Waza4", WAZA), ("GemType", "i"), ("Seikaku", "i"), ("Tokusei", "i"), ("TalentType", "i"),
        ("TalentValue", PARAMS), ("TalentVnum", "b"), ("EffortValue", PARAMS), ("RareType", "i"),
        ("ScaleType", "i"), ("ScaleValue", "h"))
SIZE = (("HeightType", "i"), ("HeightValue", "h"), ("WeightType", "i"), ("WeightValue", "h"),
        ("ScaleType", "i"), ("ScaleValue", "h"))
EXTRA = (("Timing", "h"), ("Action", "h"), ("Value", "h"), ("Wazano", "H"))
BOSS = (("HpCoef", "h"), ("PowerChargeTrigerHp", "b"), ("PowerChargeTrigerTime", "b"),
        ("PowerChargeLimitTime", "h"), ("PowerChargeCancelDamage", "b"),
        ("PowerChargePenaltyTime", "h"), ("PowerChargePenaltyAction", "H"),
        ("PowerChargeDamageRate", "b"), ("PowerChargeGemDamageRate", "b"),
        ("PowerChargeChangeGemDamageRate", "b"),
        *((f"ExtraAction{i}", EXTRA) for i in range(1, 7)),
        ("DoubleActionTriggerHp", "b"), ("DoubleActionTriggerTime", "b"), ("DoubleActionRate", "b"))
TIME = (("IsActive", "?"), ("GameLimit", "i"), ("ClientLimit", "i"), ("CommandLimit", "i"),
        ("PokeReviveTime", "i"), ("AiIntervalTime", "i"), ("AiIntervalRand", "i"))
INFO = (("RomVer", "h"), ("No", "i"), ("DeliveryGroupID", "b"), ("Difficulty", "i"), ("Rate", "b"),
        ("DropTableFix", "Q"), ("DropTableRandom", "Q"), ("CaptureRate", "b"), ("CaptureLv", "b"),
        ("BossPokePara", POKE), ("BossPokeSize", SIZE), ("BossDesc", BOSS), ("TimeDesc", TIME))
FIXED_ITEM = (("Category", "i"), ("SubjectType", "i"), ("ItemID", "i"), ("Num", "b"))
LOTTERY_ITEM = (("Category", "i"), ("ItemID", "i"), ("Num", "b"), ("Rate", "i"), ("RareItemFlag", "?"))
SCHEMAS = {
    ENEMY: (("Table", [(("Info", INFO),)]),),
    FIXED: (("Table", [(("TableName", "Q"),
                        *((f"RewardItem{i:02}", FIXED_ITEM) for i in range(15)))]),),
    LOTTERY: (("Table", [(("TableName", "Q"),
                          *((f"RewardItem{i:02}", LOTTERY_ITEM) for i in range(30)))]),),
    PRIORITY: (("Table", [(("VersionNo", "i"),
                           ("GroupID", tuple((f"GroupID{i:02}", "b") for i in range(1, GROUPS + 1))))]),),
}


def _table(buf, pos, schema):
    vtable = pos - struct.unpack_from("<i", buf, pos)[0]
    length = struct.unpack_from("<H", buf, vtable)[0]
    out = {}
    for index, (name, kind) in enumerate(schema):
        slot = 4 + 2 * index
        at = struct.unpack_from("<H", buf, vtable + slot)[0] if slot < length else 0
        if isinstance(kind, str):
            out[name] = struct.unpack_from("<" + kind, buf, pos + at)[0] if at else 0
            continue
        if not at:
            out[name] = None            # a table an older schema had no field for
            continue
        target = pos + at + struct.unpack_from("<I", buf, pos + at)[0]
        if isinstance(kind, list):
            count = struct.unpack_from("<I", buf, target)[0]
            items = (target + 4 + 4 * i for i in range(count))
            out[name] = [_table(buf, item + struct.unpack_from("<I", buf, item)[0], kind[0])
                         for item in items]
        else:
            out[name] = _table(buf, target, kind)
    return out


def decode(raw, name):
    """-> one of a delivery's tables, by its file name without the patch, as nested dicts."""
    raw = bytes(raw)
    return _table(raw, struct.unpack_from("<I", raw, 0)[0], SCHEMAS[name])


def paths(folder):
    """-> (patch, {table: path}) of a delivery's newest patch, in `folder` or its `Files`."""
    if os.path.isdir(os.path.join(folder, "Files")):
        folder = os.path.join(folder, "Files")
    for patch in PATCHES:
        found = {name: os.path.join(folder, name + patch) for name in (ENEMY, FIXED, LOTTERY, PRIORITY)}
        if os.path.isfile(found[ENEMY]):
            return patch, found
    raise FileNotFoundError(f"no {ENEMY} in {folder}")


def boss_profile(desc):
    """-> the RaidPoint's 37 words of a record's BossDesc (scripts/gen_sv_raid_data.py's order)."""
    words = [desc[k] for k in ("HpCoef", "PowerChargeTrigerHp", "PowerChargeTrigerTime",
                               "PowerChargeLimitTime", "PowerChargeCancelDamage",
                               "PowerChargePenaltyTime", "PowerChargePenaltyAction",
                               "PowerChargeDamageRate", "PowerChargeGemDamageRate",
                               "PowerChargeChangeGemDamageRate")]
    for i in range(1, 7):
        a = desc[f"ExtraAction{i}"]
        words += [a["Action"], a["Timing"], a["Value"], a["Wazano"]]
    return words + [desc["DoubleActionTriggerHp"], desc["DoubleActionTriggerTime"],
                    desc["DoubleActionRate"]]


def encounter_row(info):
    """-> a raid_enemy record as a `raid_encounter` row, with what the event table fixes: the game
    version (`rom`), delivery group, capture rate, IVs, gender, nature, shiny and scale rules,
    the held item and the battle's time limits."""
    para = info["BossPokePara"]
    ev, talent = para["EffortValue"], para["TalentValue"]
    return {
        "species": gen9.national(para["DevId"]), "form": para["FormId"], "ability": para["Tokusei"],
        "flawless_ivs": para["TalentVnum"] if para["TalentType"] == TALENT_FLAWLESS else 0,
        "level": para["Level"], "capture_level": info["CaptureLv"],
        "moves": [para[f"Waza{i}"]["WazaId"] for i in range(1, 5)], "tera": para["GemType"],
        "stars": info["Difficulty"], "rate": info["Rate"], "identifier": info["No"],
        "fixed_rewards": str(info["DropTableFix"]), "lottery_rewards": str(info["DropTableRandom"]),
        "boss_desc": boss_profile(info["BossDesc"]),
        "evs": [ev[k] for k in ("HP", "ATK", "DEF", "SPE", "SPA", "SPD")],
        "rom": info["RomVer"], "group": info["DeliveryGroupID"], "capture_rate": info["CaptureRate"],
        "ivs": ([talent[k] for k in ("HP", "ATK", "DEF", "SPA", "SPD", "SPE")]
                if para["TalentType"] == TALENT_VALUE else None),
        "gender": para["Sex"] - 1 if para["Sex"] else None,
        "nature": para["Seikaku"] - 1 if para["Seikaku"] else None,
        "shiny": para["RareType"], "scale_type": para["ScaleType"], "scale": para["ScaleValue"],
        "held_item": para["Item"], "time": time_words(info["TimeDesc"]),
    }


def time_words(time):
    """-> a record's TimeDesc as the RaidPoint's seven words, or None when it is inactive and the
    console uses its own limits (docs/sv_raid.md, The battle bootstrap)."""
    if not time or not time["IsActive"]:
        return None
    return [1, *(time[k] for k in ("GameLimit", "ClientLimit", "CommandLimit", "PokeReviveTime",
                                   "AiIntervalTime", "AiIntervalRand"))]


def reward_tables(table, lottery):
    """-> {name: [entry]} as raid_base.json holds them (scripts/gen_sv_raid_data.py), a fixed row
    with its subject: 0 every player, 1 the host, 2 the guests, 3 once. A lottery slot with a rate
    and nothing in it stays: it weighs in the total, and a draw that lands on it gives nothing."""
    out = {}
    for row in table["Table"]:
        entries = []
        for key, item in row.items():
            if not key.startswith("RewardItem") or item is None:   # None: an older, shorter table
                continue
            entry = {"category": item["Category"], "item": item["ItemID"], "amount": item["Num"],
                     "probability": item["Rate"] if lottery else 100}
            if not lottery:
                entry["subject"] = item["SubjectType"]
            if entry["item"] or entry["category"] or lottery and entry["probability"]:
                entries.append(entry)
        out.setdefault(str(row["TableName"]), entries)
    return out


@dataclass(frozen=True)
class Event:
    identifier: int
    patch: str            # the file suffix read, "" for a delivery older than 1.3.0
    rows: tuple           # every record with a species, table order; a rate of 0 is never drawn
    fixed: dict
    lottery: dict
    dens: tuple           # dens per delivery group 1 to 10 (raid_priority_array)

    def groups(self, version, progress):
        """-> the delivery groups with dens and an encounter that version draws at that progress."""
        return [g for g in range(1, GROUPS + 1) if self.dens[g - 1] and candidates(self, version, progress, g)]


def load(folder):
    """-> the Event a delivery folder holds (an EventsGallery event, or its Files); ValueError for
    tables that do not read. The identifier is the priority table's version number, which the
    identifier file repeats."""
    patch, found = paths(folder)

    def read(name):
        with open(found[name], "rb") as fh:
            return decode(fh.read(), name)

    try:
        priority = read(PRIORITY)["Table"][0]
        rows = [encounter_row(t["Info"]) for t in read(ENEMY)["Table"] if t["Info"]["BossPokePara"]["DevId"]]
        return Event(priority["VersionNo"], patch, tuple(rows), reward_tables(read(FIXED), False),
                     reward_tables(read(LOTTERY), True),
                     tuple(priority["GroupID"][f"GroupID{i:02}"] for i in range(1, GROUPS + 1)))
    except (struct.error, KeyError, IndexError, TypeError) as error:
        raise ValueError(f"{folder} holds no readable delivery ({error})") from error


def deliveries(base):
    """-> every folder under `base` that holds a delivery's Files, in name order."""
    for folder, dirs, _ in os.walk(base):
        dirs.sort()
        if "Files" in dirs:
            yield folder


def _rows(event, version, group):
    """-> the drawn records (a rate) of a delivery group in that version, either without one."""
    roms = (ROM_BOTH, ROM_SCARLET, ROM_VIOLET) if version is None else (
        ROM_BOTH, ROM_SCARLET if version == "scarlet" else ROM_VIOLET)
    return [r for r in event.rows if r["group"] == group and r["rate"] and r["rom"] in roms]


def candidates(event, version, progress, group):
    """-> the rows a den of `group` draws among at that progress in that version, in table order."""
    if version not in encounter.VERSIONS or progress not in STAGES:
        raise ValueError(f"no event stage for {version}/{progress}")
    stars = STAGE_STARS[STAGES[progress]]
    return [r for r in _rows(event, version, group) if r["stars"] in stars]


def select(event, seed, version, progress, group):
    """-> the row the seed draws in a den of `group`."""
    rows = candidates(event, version, progress, group)
    if not rows:
        raise ValueError(f"delivery group {group} has no {version} encounter at {progress} progress")
    return draw(rows, seed)


def draw(rows, seed):
    """-> the row of `candidates` the seed draws: the hundred-sided roll a standard crystal's stars
    take is drawn and dropped, then a draw under the rates' total picks the row [PKHeX
    EncounterDist9.GetIsPossibleSlot]."""
    total = sum(r["rate"] for r in rows)
    rand = encounter.Xoroshiro(seed)
    rand.next_int(100)
    choice = rand.next_int(total)
    for row in rows:
        if choice < row["rate"]:
            return row
        choice -= row["rate"]
    raise AssertionError("the draw is under the total")


def generate(event, seed, version="violet", progress="6star", group=None):
    """-> the Raid a den of `group` makes of the seed; without a group, the first that has dens and
    an encounter there."""
    seed &= 0xFFFFFFFF
    if group is None:
        groups = event.groups(version, progress)
        if not groups:
            raise ValueError(f"event {event.identifier} has no {version} encounter at {progress} progress")
        group = groups[0]
    row = select(event, seed, version, progress, group)
    stars = row["stars"]
    return encounter.Raid(seed, version, "paldea", progress,
                          CONTENT_MIGHTY if stars == MIGHTY else CONTENT_EVENT, stars, row,
                          encounter.boss_fields(seed, row),
                          tuple(encounter.rewards(seed, row, stars, event.fixed, event.lottery)))


@dataclass(frozen=True)
class Den:
    """What an event's dens of one delivery group can hold in a game version."""
    group: int
    content: str          # CONTENT_EVENT, or CONTENT_MIGHTY for a seven-star group
    stars: tuple          # the star levels drawn, lowest first
    species: tuple        # the bosses, table order

    @property
    def label(self):
        """-> "7 stars: Charizard", "4-5 stars: Florges, Mimikyu"."""
        names = encounter.tables()["species_names"]
        low, high = self.stars[0], self.stars[-1]
        stars = f"{low} star{'s' if low > 1 else ''}" if low == high else f"{low}-{high} stars"
        return f"{stars}: {', '.join(names[str(s)] for s in self.species)}"


def dens(event, version=None):
    """-> the delivery groups with dens and an encounter in that version (either, without one)."""
    out = []
    for group in range(1, GROUPS + 1):
        rows = _rows(event, version, group)
        if event.dens[group - 1] and rows:
            stars = tuple(sorted({r["stars"] for r in rows}))
            out.append(Den(group, CONTENT_MIGHTY if stars == (MIGHTY,) else CONTENT_EVENT, stars,
                           tuple(dict.fromkeys(r["species"] for r in rows))))
    return out


def versions(event):
    """-> the game versions the event has an encounter in."""
    return [v for v in encounter.VERSIONS if dens(event, v)]


def progresses(event, version, group):
    """-> the story progresses at which a den of `group` draws an encounter in that version."""
    return [p for p in encounter.PROGRESS if candidates(event, version, p, int(group))]


def constrain(event, context):
    """-> the nearest raid context the event can spawn: the version kept if it has an encounter,
    then the group, then the progress (the furthest, failing that); the region is Paldea, the
    crystal the group's. Tera-Finder places every event encounter in Paldea, and the draw never
    reads the region."""
    allowed = versions(event)
    if not allowed:
        raise ValueError(f"event {event.identifier} has no encounter")
    version = context.get("version") if context.get("version") in allowed else allowed[0]
    by_group = {d.group: d for d in dens(event, version)}
    group = context.get("group")
    group = int(group) if str(group).isdigit() and int(group) in by_group else next(iter(by_group))
    stages = progresses(event, version, group)
    progress = context.get("progress") if context.get("progress") in stages else stages[-1]
    return {"version": version, "map_name": "paldea", "progress": progress,
            "content": by_group[group].content, "group": group}


def bosses(rows):
    """-> the species names of the records, each once, in table order."""
    names = encounter.tables()["species_names"]
    return list(dict.fromkeys(names[str(r["species"])] for r in rows))


def catch_once(event):
    """-> the names of the bosses the event lets a save catch once."""
    return bosses(r for r in event.rows if r["rate"] and r["capture_rate"] == CAPTURE_ONCE)


def catch_rule(found):
    """-> how a raid's boss can be caught, in words."""
    return CATCH_RULES[found.row.get("capture_rate", CAPTURE_NORMAL)]


def stand_in(identifier):
    """-> the record number the lobby shows for a record served as a normal catch."""
    return identifier - identifier % 100 + STAND_IN


def caught_normally(found):
    """-> the raid with a catch-once record served as a normal catch: the RaidPoint's capture rate
    a normal one's, and the lobby descriptor's record number a stand-in, as a console that caught
    the record refuses its catch in the lobby by that number; any other raid as it is. The event's
    own row is left alone."""
    if found.row.get("capture_rate") != CAPTURE_ONCE:
        return found
    return replace(found, row={**found.row, "capture_rate": CAPTURE_NORMAL,
                               "identifier": stand_in(found.row["identifier"])})
