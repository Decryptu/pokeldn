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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tera-finder", required=True, type=Path)
    parser.add_argument("--pkhex", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    tf = args.tera_finder
    pk = args.pkhex
    raid_data = tf / "TeraFinder.Core/Resources/raid_default"
    core = pk / "PKHeX.Core"
    result = {
        "source": {
            "tera_finder": revision(tf),
            "pkhex": revision(pk),
            "license": "GPL-3.0",
        },
        "encounters": encounters(raid_data),
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
