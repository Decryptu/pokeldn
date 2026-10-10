#!/usr/bin/env python3
"""Builds pokeldn/sv/data/raid_base.json, the standard and black-crystal Tera Raid tables of Scarlet
and Violet 4.0.0 [docs/sv_raid.md, The seed].

Sources, all GPL-3.0 or the game itself:
  --tera-finder  a Tera-Finder checkout: the encounter lists (`encounter_gem_*.pkl`, PKHeX's layout
                 extended with the reward table ids), both reward tables, the material per species
  --pkhex        a PKHeX checkout: the species enum the materials are named by; the personal table,
                 move PP and names are scripts/gen_sv_species_data.py's
  --raid-enemy   the eighteen `raid_enemy_XX_array` tables of the game's RomFS
                 (arc/worlddataraidraid_gem_item_reward_boostdata.bin.trpak), decoded to JSON with
                 numeric enums by flatc against their own .bfbs schemas: each record's `bossDesc`
                 is the RaidPoint's 37-word action profile, its `gemType` the Tera rule, its
                 `bossPokePara` level and effort values the battle's, its `captureLv` the catch
A retail record and its encounter are joined by the record's `no`; the script refuses a record
that does not join or whose extra moves differ from the encounter's.

    ./.venv/bin/python scripts/gen_sv_raid_data.py --tera-finder DIR --pkhex DIR --raid-enemy DIR
"""

import argparse
import json
import pathlib
import re
import struct
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "pokeldn" / "sv" / "data" / "raid_base.json"
MAPS = {"paldea": "raid", "kitakami": "su1_raid", "blueberry": "su2_raid"}
CONTENTS = ("standard", "black")
ENCOUNTER_SIZE = 0x3C
PERSONAL_SIZE = 0x50


def revision(path):
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def encounters(folder):
    """-> {map_content: [row]} from Tera-Finder's 0x3c-byte records; constant fields are checked."""
    out = {}
    for map_name in MAPS:
        for content in CONTENTS:
            raw = (folder / f"encounter_gem_{map_name}_{content}.pkl").read_bytes()
            rows = []
            for offset in range(0, len(raw), ENCOUNTER_SIZE):
                r = raw[offset:offset + ENCOUNTER_SIZE]
                # gender, shiny, index and held item are 0 in every standard and black record.
                if r[3] or r[6] or r[0x11] or struct.unpack_from("<I", r, 0x2C)[0]:
                    raise ValueError(f"{map_name}_{content} {offset}: an unexpected fixed field")
                rows.append({
                    "species": struct.unpack_from("<H", r, 0)[0], "form": r[2], "ability": r[4],
                    "flawless_ivs": r[5], "level": r[7], "moves": list(struct.unpack_from("<4H", r, 8)),
                    "tera": r[0x10], "stars": r[0x12], "rate": r[0x13],
                    "rate_min": dict(zip(("scarlet", "violet"), struct.unpack_from("<2h", r, 0x14))),
                    "identifier": struct.unpack_from("<I", r, 0x18)[0],
                    "fixed_rewards": str(struct.unpack_from("<Q", r, 0x1C)[0]),
                    "lottery_rewards": str(struct.unpack_from("<Q", r, 0x24)[0]),
                    "extra_moves": list(struct.unpack_from("<6H", r, 0x30)),
                })
            out[f"{map_name}_{content}"] = rows
    return out


def boss_profile(desc):
    """-> the 37 RaidPoint words of a record's bossDesc, in the RaidPoint's order."""
    words = [desc[k] for k in ("hpCoef", "powerChargeTrigerHp", "powerChargeTrigerTime",
                               "powerChargeLimitTime", "powerChargeCancelDamage",
                               "powerChargePenaltyTime", "powerChargePenaltyAction",
                               "powerChargeDamageRate", "powerChargeGemDamageRate",
                               "powerChargeChangeGemDamageRate")]
    for i in range(1, 7):
        a = desc[f"extraAction{i}"]
        words += [a["action"], a["timming"], a["value"], a["wazano"]]
    return words + [desc["doubleActionTrigerHp"], desc["doubleActionTrigerTime"],
                    desc["doubleActionRate"]]


def join_retail(tables, folder):
    """Adds each row's `boss_desc`, the retail Tera rule (gemType 0 the species' own types, 1 any
    of 18, 2+ a fixed type), its battle level and effort values (HP Atk Def Spe SpA SpD) and its
    capture level, which is Tera-Finder's level."""
    retail = {}
    for map_name, prefix in MAPS.items():
        for stars in range(1, 7):
            data = json.loads((folder / f"{prefix}_enemy_{stars:02}_array.json").read_text())
            for value in data["values"]:
                info = value["raidEnemyInfo"]
                retail[(map_name, info["no"])] = info
    joined = set()
    for name, rows in tables.items():
        map_name = name.split("_")[0]
        for row in rows:
            info = retail[(map_name, row["identifier"])]
            row["boss_desc"] = boss_profile(info["bossDesc"])
            if row["boss_desc"][13:34:4] != row.pop("extra_moves"):
                raise ValueError(f"{map_name} {row['identifier']}: extra moves differ")
            para = info["bossPokePara"]
            row["tera"] = para["gemType"]
            if row["level"] != info["captureLv"]:
                raise ValueError(f"{map_name} {row['identifier']}: capture level differs")
            row["capture_level"], row["level"] = row["level"], para["level"]
            ev = para["effortValue"]
            row["evs"] = [ev[k] for k in ("hp", "atk", "def", "agi", "spAtk", "spDef")]
            joined.add((map_name, row["identifier"]))
    if joined != set(retail):
        raise ValueError(f"retail records with no encounter: {sorted(set(retail) - joined)}")


def reward_tables(path, lottery):
    out = {}
    for row in json.loads(path.read_text())["Table"]:
        key = str(row["TableName"])
        if key in out:
            continue
        entries = []
        for index in range(30 if lottery else 15):
            item = row.get(f"RewardItem{index:02d}")
            if item is None:
                break
            entry = {"category": int(item.get("Category", 0)), "item": int(item.get("ItemID", 0)),
                     "amount": int(item.get("Num", 0)),
                     "probability": int(item.get("Rate", 0)) if lottery else 100}
            if entry["item"] or entry["category"]:
                entries.append(entry)
        out[key] = entries
    return out


def read_enum(path):
    body = re.sub(r"//.*", "", path.read_text(encoding="utf-8-sig"))
    body = body[body.index("{") + 1:body.rindex("}")]
    out, value = {}, -1
    for token in (t.strip() for t in body.split(",")):
        if not token:
            continue
        name, _, raw = (s.strip() for s in token.partition("="))
        value = int(raw, 0) if raw else value + 1
        out[name] = value
    return out


def materials(reward_util, species_enum):
    """-> {species: material item} from Tera-Finder's GetMaterial switch."""
    species = read_enum(species_enum)
    text = reward_util.read_text(encoding="utf-8-sig")
    text = re.sub(r"\s+", " ", text[text.index("private static int GetMaterial"):])
    text = text[:text.index("_ => 0")]
    out = {}
    for names, item in re.findall(r"((?:Species\.[^=]+?))\s*=>\s*(\d+)", text):
        for name in re.findall(r"Species\.(\w+)", names):
            out[str(species[name])] = int(item)
    return out


def personal(path, wanted):
    """-> {"species/form": [base stats x6, type 1, type 2, gender ratio, friendship, growth,
    abilities x3]} for the raid bosses only."""
    raw = path.read_bytes()
    out = {}
    for species, form in sorted(wanted):
        base = raw[species * PERSONAL_SIZE:(species + 1) * PERSONAL_SIZE]
        first, forms = struct.unpack_from("<H", base, 0x18)[0], base[0x1A]
        index = first + form - 1 if 0 < form < forms and first else species
        e = raw[index * PERSONAL_SIZE:(index + 1) * PERSONAL_SIZE]
        out[f"{species}/{form}"] = [*e[:8], e[0x0C], e[0x0E], e[0x0F], *struct.unpack_from("<3H", e, 0x12)]
    return out


def move_pp(path):
    text = path.read_text(encoding="utf-8-sig")
    start = text.index("[", text.index("public static ReadOnlySpan<byte> PP"))
    return [int(v) for v in re.findall(r"\b\d+\b", text[start + 1:text.index("];", start)])]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tera-finder", required=True, type=pathlib.Path)
    ap.add_argument("--pkhex", required=True, type=pathlib.Path)
    ap.add_argument("--raid-enemy", required=True, type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path, default=OUT)
    args = ap.parse_args()
    data = args.tera_finder / "TeraFinder.Core" / "Resources" / "raid_default"
    core = args.pkhex / "PKHeX.Core"
    tables = encounters(data)
    join_retail(tables, args.raid_enemy)
    rows = [row for table in tables.values() for row in table]
    result = {
        "source": {"tera_finder": revision(args.tera_finder), "pkhex": revision(args.pkhex),
                   "game": "Scarlet 4.0.0 RomFS raid_enemy tables", "license": "GPL-3.0"},
        "encounters": tables,
        "fixed_rewards": reward_tables(data / "raid_fixed_reward_item_array.json", False),
        "lottery_rewards": reward_tables(data / "raid_lottery_reward_item_array.json", True),
        "material_items": materials(args.tera_finder / "TeraFinder.Core" / "Utils" / "RewardUtil.cs",
                                    core / "Game" / "Enums" / "Species.cs"),
    }
    args.out.write_text(json.dumps(result, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{args.out}: {len(rows)} encounters")


if __name__ == "__main__":
    main()
