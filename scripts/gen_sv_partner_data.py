#!/usr/bin/env python3
"""Builds pokeldn/sv/data/raid_partners.json, the Tera Raid NPC partner pools of Scarlet and Violet
4.0.0 [docs/sv_raid.md, Partners], from the game's own RomFS files:

    world/data/raid/raid_trainer_0N/raid_trainer_0N_array.{bin,bfbs}   N = 1, 2, 3: the pools
    world/data/trainer/trdata/trdata_array.{bin,bfbs}                   each trainer's Pokemon
    avalon/data/personal_array.bin                                      the gender rule's ratios

tools/switch/trpfs_read.py extracts them. The tables are FlatBuffers read through their own .bfbs
reflection schemas. A pool row names a trainer (`raid_assist_NPC_N`) whose `poke1` is the partner.

    ./.venv/bin/python scripts/gen_sv_partner_data.py --romfs scratchpad/sv/romfs
"""

import argparse
import json
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pokeldn import gen9                                    # noqa: E402

OUT = ROOT / "pokeldn" / "sv" / "data" / "raid_partners.json"
POOLS = ("raid_trainer_01", "raid_trainer_02", "raid_trainer_03")
SCALARS = {1: "<B", 2: "<?", 3: "<b", 4: "<B", 5: "<h", 6: "<H", 7: "<i", 8: "<I", 9: "<q", 10: "<Q",
           11: "<f", 12: "<d"}
SIZES = {1: 1, 2: 1, 3: 1, 4: 1, 5: 2, 6: 2, 7: 4, 8: 4, 9: 8, 10: 8, 11: 4, 12: 8}
STRING, VECTOR, OBJECT = 13, 14, 15
GENDER_FIELD = 12           # personal entry: {group, ratio}; group 1 male, 2 female, 3 genderless
# The converter 0x160ffd0 compares the ratio (percent female) with the record's unset encryption
# constant modulo 100: (2^64 - 1) mod 100 = 15. A 50% ratio takes the binding's fourth argument, 0.
UNSET_EC_MOD_100 = (2 ** 64 - 1) % 100


class Flat:
    """A FlatBuffers buffer: tables, fields by index, strings and vectors."""

    def __init__(self, data):
        self.b = data

    def u32(self, at):
        return struct.unpack_from("<I", self.b, at)[0]

    def ref(self, at):
        return at + self.u32(at)

    def field(self, table, index):
        vtable = table - struct.unpack_from("<i", self.b, table)[0]
        size = struct.unpack_from("<H", self.b, vtable)[0]
        if 4 + 2 * index >= size:
            return 0
        offset = struct.unpack_from("<H", self.b, vtable + 4 + 2 * index)[0]
        return table + offset if offset else 0

    def string(self, at):
        at = self.ref(at)
        return self.b[at + 4:at + 4 + self.u32(at)].decode()

    def vector(self, at):
        at = self.ref(at)
        return at + 4, self.u32(at)

    def tables(self, at):
        start, count = self.vector(at)
        return [self.ref(start + 4 * k) for k in range(count)]

    def scalar(self, at, fmt, default=0):
        return struct.unpack_from(fmt, self.b, at)[0] if at else default


def schema(data):
    """-> (objects, root name) of a .bfbs reflection schema; each object {name, struct, size, fields}."""
    r = Flat(data)
    root = r.ref(0)

    def obj(t):
        fields = []
        for f in r.tables(r.field(t, 1)):
            kind = r.ref(r.field(f, 1))
            fields.append({"name": r.string(r.field(f, 0)), "base": r.scalar(r.field(kind, 0), "<b"),
                           "element": r.scalar(r.field(kind, 1), "<b"),
                           "index": r.scalar(r.field(kind, 2), "<i", -1),
                           "id": r.scalar(r.field(f, 2), "<H"), "offset": r.scalar(r.field(f, 3), "<H"),
                           "default": r.scalar(r.field(f, 4), "<q")})
        return {"name": r.string(r.field(t, 0)), "struct": bool(r.scalar(r.field(t, 2), "<b")),
                "size": r.scalar(r.field(t, 4), "<i"), "fields": sorted(fields, key=lambda f: f["id"])}

    objects = [obj(t) for t in r.tables(r.field(root, 0))]
    return objects, obj(r.ref(r.field(root, 4)))["name"]


def decode(schema_bytes, data):
    """-> the root table of `data` as dicts and lists, enums as their numbers."""
    objects, root = schema(schema_bytes)
    d = Flat(data)

    def value(kind, at):
        base = kind["base"]
        if base in SCALARS:
            return d.scalar(at, SCALARS[base])
        if base == STRING:
            return d.string(at)
        if base == OBJECT:
            o = objects[kind["index"]]
            return struct_at(o, at) if o["struct"] else table(o, d.ref(at))
        if base == VECTOR:
            start, count = d.vector(at)
            element = {"base": kind["element"], "element": 0, "index": kind["index"]}
            if element["base"] == OBJECT:
                o = objects[kind["index"]]
                if o["struct"]:
                    return [struct_at(o, start + k * o["size"]) for k in range(count)]
                return [table(o, d.ref(start + 4 * k)) for k in range(count)]
            if element["base"] == STRING:
                return [d.string(start + 4 * k) for k in range(count)]
            return [value(element, start + k * SIZES[element["base"]]) for k in range(count)]
        raise ValueError(f"FlatBuffers type {base} is not read here")

    def struct_at(o, at):
        return {f["name"]: value(f, at + f["offset"]) for f in o["fields"]}

    def table(o, t):
        out = {}
        for f in o["fields"]:
            at = d.field(t, f["id"])
            if at:
                out[f["name"]] = value(f, at)
            elif f["base"] in SCALARS:
                out[f["name"]] = f["default"]
        return out

    return table(next(o for o in objects if o["name"] == root), d.ref(0))


def genders(path):
    """-> {(internal species, form): (group, percent female)} from personal_array.bin."""
    p = Flat(path.read_bytes())
    out = {}
    for entry in p.tables(p.field(p.ref(0), 0)):
        species, form = struct.unpack_from("<HH", p.b, p.field(entry, 0))
        at = p.field(entry, GENDER_FIELD)
        out[(species, form)] = (p.b[at], p.b[at + 1]) if at else (0, 0)
    return out


def gender(rule):
    """-> the PK9 gender (0 male, 1 female, 2 genderless) of a partner whose trainer data leaves it
    to the game (`sex` 0) [0x160ffd0, 0x1611d1c]."""
    group, ratio = rule
    if group in (1, 2, 3):
        return group - 1
    return int(ratio != 50 and UNSET_EC_MOD_100 <= ratio)


def partner(row, trainer, rules):
    poke = trainer["poke1"]
    if any(trainer[f"poke{k}"]["devId"] for k in range(2, 7)):
        raise ValueError(f"{row['raidTrainerInfo']}: more than one Pokemon")
    if poke["tokusei"] not in (2, 3, 4):
        raise ValueError(f"{row['raidTrainerInfo']}: an ability rule other than a fixed slot")
    talent, effort = poke["talentValue"], poke["effortValue"]
    sex = poke["sex"]
    return {
        "trid": row["raidTrainerInfo"], "name_label": row["nameTextLabel"],
        "npc_preset": row["npcPresetIndex"], "trainer_type": trainer["trainerType"],
        "species": gen9.national(poke["devId"]), "form": poke["formId"], "level": poke["level"],
        "ability_number": {2: 1, 3: 2, 4: 4}[poke["tokusei"]],
        "moves": [poke[f"waza{k}"]["wazaId"] for k in range(1, 5) if poke[f"waza{k}"]["wazaId"]],
        # gemType: 0 the species' default (0xe78418), 1 random, 2 + n Tera type n
        "tera": poke["gemType"] - 2 if poke["gemType"] >= 2 else None,
        "gender": sex - 1 if sex else gender(rules[(poke["devId"], poke["formId"])]),
        "nature": poke["seikaku"] - 1, "ball": poke["ballId"], "held_item": poke["item"],
        "ivs": [talent[k] for k in ("hp", "atk", "def", "agi", "spAtk", "spDef")],
        "evs": [effort[k] for k in ("hp", "atk", "def", "agi", "spAtk", "spDef")],
        "shiny": poke["rareType"], "scale_type": poke["scaleType"], "scale": poke["scaleValue"],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--romfs", required=True, type=pathlib.Path, help="an extracted RomFS root")
    args = ap.parse_args()
    trdata = args.romfs / "world" / "data" / "trainer" / "trdata" / "trdata_array"
    trainers = {t["trid"]: t for t in decode(trdata.with_suffix(".bfbs").read_bytes(),
                                              trdata.with_suffix(".bin").read_bytes())["values"]}
    rules = genders(args.romfs / "avalon" / "data" / "personal_array.bin")
    pools = {}
    for name in POOLS:
        path = args.romfs / "world" / "data" / "raid" / name / f"{name}_array"
        rows = decode(path.with_suffix(".bfbs").read_bytes(), path.with_suffix(".bin").read_bytes())["values"]
        pools[name] = [partner(row, trainers[row["raidTrainerInfo"]], rules) for row in rows]
    out = {"source": {"game": "Scarlet 4.0.0 RomFS: world/data/raid/raid_trainer_01..03, "
                              "world/data/trainer/trdata, avalon/data/personal_array"},
           "pools": pools}
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(f"{OUT}: {', '.join(f'{k} {len(v)}' for k, v in pools.items())}")


if __name__ == "__main__":
    main()
