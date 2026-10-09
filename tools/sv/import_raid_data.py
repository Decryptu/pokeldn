#!/usr/bin/env python3
"""Build PokéLDN's compact SV raid data file from Tera Finder and PKHeX checkouts.

Both upstream projects are GPLv3. The generated file records the exact revisions used and keeps
the network host independent of either .NET project at runtime.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import re
import struct
import subprocess


MAPS = ("paldea", "kitakami", "blueberry")
CONTENTS = ("standard", "black")
ENCOUNTER_SIZE = 0x3C
RAID_TABLE_PREFIX = {
    "paldea": "raid",
    "kitakami": "su1_raid",
    "blueberry": "su2_raid",
}
RAID_ACTION = {
    "NONE": 0,
    "BOSS_STATUS_RESET": 1,
    "PLAYER_STATUS_RESET": 2,
    "WAZA": 3,
    "GEM_COUNT": 4,
}
RAID_TIMING = {"NONE": 0, "TIME": 1, "HP": 2}


def revision(path: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def read_enum(path: Path) -> dict[str, int]:
    text = re.sub(r"//.*", "", path.read_text(encoding="utf-8-sig"))
    body = text[text.index("{") + 1:text.rindex("}")]
    result: dict[str, int] = {}
    value = -1
    for token in body.split(","):
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            name, raw = map(str.strip, token.split("=", 1))
            value = int(raw, 0)
        else:
            name = token
            value += 1
        result[name] = value
    return result


def material_map(reward_util: Path, species_enum: Path) -> dict[str, int]:
    species = read_enum(species_enum)
    text = reward_util.read_text(encoding="utf-8-sig")
    body = text[text.index("private static int GetMaterial"):]
    body = body[:body.index("_ => 0")]
    body = re.sub(r"\s+", " ", body)
    result: dict[str, int] = {}
    for names, item in re.findall(r"((?:Species\.[^=]+?))\s*=>\s*(\d+)", body):
        for name in re.findall(r"Species\.([\w\u0080-\uffff]+)", names):
            result[str(species[name])] = int(item)
    return result


def move_pp(path: Path) -> list[int]:
    text = path.read_text(encoding="utf-8-sig")
    start = text.index("public static ReadOnlySpan<byte> PP")
    start = text.index("[", start)
    end = text.index("];", start)
    return [int(value) for value in re.findall(r"\b\d+\b", text[start + 1:end])]


def reward_tables(path: Path, lottery: bool) -> dict[str, list[dict]]:
    rows = json.loads(path.read_text(encoding="utf-8"))["Table"]
    result: dict[str, list[dict]] = {}
    for row in rows:
        key = str(row["TableName"])
        if key in result:
            continue
        entries = []
        for index in range(30 if lottery else 15):
            item = row.get(f"RewardItem{index:02d}")
            if item is None:
                break
            category = int(item.get("Category", 0))
            item_id = int(item.get("ItemID", 0))
            probability = int(item.get("Rate", 0)) if lottery else 100
            if not (item_id or category or probability):
                continue
            entries.append({
                "category": category,
                "item": item_id,
                "amount": int(item.get("Num", 0)),
                "probability": probability,
                "subject": 2 if lottery else int(item.get("SubjectType", 0)),
            })
        result[key] = entries
    return result


def encounters(directory: Path) -> dict[str, list[dict]]:
    result = {}
    for map_name in MAPS:
        for content in CONTENTS:
            path = directory / f"encounter_gem_{map_name}_{content}.pkl"
            raw = path.read_bytes()
            if len(raw) % ENCOUNTER_SIZE:
                raise ValueError(f"{path} is not a sequence of 0x3c-byte encounters")
            rows = []
            for offset in range(0, len(raw), ENCOUNTER_SIZE):
                row = raw[offset:offset + ENCOUNTER_SIZE]
                rows.append({
                    "species": struct.unpack_from("<H", row, 0)[0],
                    "form": row[2],
                    "gender": row[3],
                    "ability": row[4],
                    "flawless_ivs": row[5],
                    "shiny": row[6],
                    "level": row[7],
                    "moves": list(struct.unpack_from("<4H", row, 8)),
                    "tera": row[0x10],
                    "index": row[0x11],
                    "stars": row[0x12],
                    "rate": row[0x13],
                    "rate_min": dict(zip(
                        ("scarlet", "violet"), struct.unpack_from("<2h", row, 0x14))),
                    "identifier": struct.unpack_from("<I", row, 0x18)[0],
                    "fixed_rewards": str(struct.unpack_from("<Q", row, 0x1C)[0]),
                    "lottery_rewards": str(struct.unpack_from("<Q", row, 0x24)[0]),
                    "held_item": struct.unpack_from("<I", row, 0x2C)[0],
                    "extra_moves": list(struct.unpack_from("<6H", row, 0x30)),
                })
            result[f"{map_name}_{content}"] = rows
    return result


def csharp_enum(path: Path, prefix: str) -> dict[str, int]:
    """Read explicit integer members from a flatc-generated C# enum."""
    return {
        name: int(value)
        for name, value in re.findall(
            rf"^\s+({re.escape(prefix)}[A-Z0-9_]+) = (\d+),$",
            path.read_text(encoding="utf-8-sig"), re.M)
    }


def boss_desc_values(desc: dict, moves: dict[str, int]) -> list[int]:
    """Serialize a retail RaidBossData record in RaidPoint word order."""
    result = [
        desc["hpCoef"],
        desc["powerChargeTrigerHp"],
        desc["powerChargeTrigerTime"],
        desc["powerChargeLimitTime"],
        desc["powerChargeCancelDamage"],
        desc["powerChargePenaltyTime"],
        moves[desc["powerChargePenaltyAction"]],
        desc["powerChargeDamageRate"],
        desc["powerChargeGemDamageRate"],
        desc["powerChargeChangeGemDamageRate"],
    ]
    for index in range(1, 7):
        action = desc[f"extraAction{index}"]
        result.extend((
            RAID_ACTION[action["action"]],
            RAID_TIMING[action["timming"]],
            action["value"],
            moves[action["wazano"]],
        ))
    result.extend((
        desc["doubleActionTrigerHp"],
        desc["doubleActionTrigerTime"],
        desc["doubleActionRate"],
    ))
    if len(result) != 37:
        raise AssertionError("RaidBossData did not produce 37 RaidPoint words")
    return result


def add_boss_desc(encounter_tables: dict[str, list[dict]], directory: Path,
                  waza_enum: Path) -> None:
    """Join flatc-decoded retail raid enemy tables to compact encounters by record number."""
    moves = csharp_enum(waza_enum, "WAZA_")
    profiles: dict[tuple[str, int], list[int]] = {}
    for map_name, prefix in RAID_TABLE_PREFIX.items():
        for stars in range(1, 7):
            table = json.loads(
                (directory / f"{prefix}_enemy_{stars:02}.json").read_text(encoding="utf-8"))
            for row in table["values"]:
                info = row["raidEnemyInfo"]
                key = (map_name, int(info["no"]))
                if key in profiles:
                    raise ValueError(f"duplicate retail raid profile {key}")
                profiles[key] = boss_desc_values(info["bossDesc"], moves)

    matched = set()
    for table_name, rows in encounter_tables.items():
        map_name, _content = table_name.split("_", 1)
        for row in rows:
            key = (map_name, row["identifier"])
            try:
                row["boss_desc"] = profiles[key]
            except KeyError as exc:
                raise ValueError(f"retail raid profile {key} is missing") from exc
            if row["boss_desc"][13:34:4] != row["extra_moves"]:
                raise ValueError(f"retail raid profile {key} has mismatched extra moves")
            matched.add(key)
    unmatched = sorted(set(profiles) - matched)
    if unmatched:
        raise ValueError(f"unmatched retail raid profiles: {unmatched}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tera-finder", required=True, type=Path)
    parser.add_argument("--pkhex", required=True, type=Path)
    parser.add_argument("--raid-enemy-json", required=True, type=Path,
                        help="directory containing flatc-decoded raid_enemy_01..06, "
                             "su1_raid_enemy_01..06, and su2_raid_enemy_01..06 JSON files")
    parser.add_argument("--waza-enum", required=True, type=Path,
                        help="flatc-generated pml/common/WazaID.cs from a raid enemy BFBS")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    tf = args.tera_finder
    pk = args.pkhex
    raid_data = tf / "TeraFinder.Core/Resources/raid_default"
    core = pk / "PKHeX.Core"
    encounter_tables = encounters(raid_data)
    add_boss_desc(encounter_tables, args.raid_enemy_json, args.waza_enum)
    result = {
        "source": {
            "tera_finder": revision(tf),
            "pkhex": revision(pk),
            "license": "GPL-3.0",
        },
        "encounters": encounter_tables,
        "fixed_rewards": reward_tables(raid_data / "raid_fixed_reward_item_array.json", False),
        "lottery_rewards": reward_tables(raid_data / "raid_lottery_reward_item_array.json", True),
        "material_items": material_map(
            tf / "TeraFinder.Core/Utils/RewardUtil.cs", core / "Game/Enums/Species.cs"),
        "personal_sv": base64.b64encode(
            (core / "Resources/byte/personal/personal_sv").read_bytes()).decode("ascii"),
        "move_pp": move_pp(core / "Moves/MoveInfo9.cs"),
        "species_names": (core / "Resources/text/other/en/text_Species_en.txt").read_text(
            encoding="utf-8-sig").splitlines(),
        "item_names": (core / "Resources/text/items/text_Items_en.txt").read_text(
            encoding="utf-8-sig").splitlines(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    main()
