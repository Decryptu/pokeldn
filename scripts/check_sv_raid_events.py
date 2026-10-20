#!/usr/bin/env python3
"""Checks event Tera Raids against the descriptor beside their files [docs/sv_raid.md, Event raids].

For every delivery folder under the paths given (an EventsGallery event holds its tables in `Files`
and pkNX's text of them in `Encounters.txt`), the encounters `pokeldn.sv.raid_event` reads are
compared with the text field by field, then raids generated from seeds in every version, story
stage and delivery group are checked against the encounter they drew: its moves and levels, the
IVs, ability, gender, nature, shiny state, scale and Tera type its rules allow, its fixed drops in
order and lottery draws from its bonus list, and a bootstrap built from it.

    ./.venv/bin/python scripts/check_sv_raid_events.py "EventsGallery/Released/Gen 9/SV/Raid Events"

Names come from the PKHeX helper. The exit status is 1 when anything differs.
"""

import argparse
import os
import random
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pokeldn import pokemon                                      # noqa: E402
from pokeldn.sv import raid, raid_encounter, raid_event          # noqa: E402

TYPES, NATURES = raid_encounter.TERA_TYPES, raid_encounter.NATURES
# What pkNX writes for a Tokusei rule, its older words and its newer ones.
ABILITY = {"1/2": 0, "Any (1/2)": 0, "1/2/H": 1, "Any (1/2/H)": 1, "1 Only": 2, "2 Only": 3,
           "Hidden Only": 4}
ABILITY_SLOT = {"(1)": 2, "(2)": 3, "(H)": 4}
SCALE_RANGES = {"0-15": 1, "16-47": 2, "48-207": 3, "208-239": 4, "240-255": 5}
SUBJECTS = {"": 0, "Only Host": 1, "Only Guests": 2, "Only Once": 3}
EV_NAMES = ("HP", "Atk", "Def", "Spe", "SpA", "SpD")         # a row's EV order
ACTIONS = {1: "Reset Raid Boss' Stat Changes", 2: "Reset Player's Stat Changes",
           4: "Reduce Tera Orb Charge"}
PROGRESS = ("tera", "3star", "4star", "6star")              # one per event stage


class Names:
    def __init__(self):
        lists = {kind: {e["id"]: e["name"] for e in pokemon.SERVICE.names("sv", kind)}
                 for kind in ("species", "moves", "items")}
        self.species, self.moves, self.items = lists["species"], lists["moves"], lists["items"]

    def move(self, move):
        return self.moves.get(move, f"move {move}")

    def item(self, item):
        return self.items.get(item, f"item {item}")

    def reward(self, entry, row):
        """-> the names pkNX may give a reward row: an item's (a TM's with its move after it), a
        material's or `TM Material`, a shard's with its fixed type or `Tera Shard`."""
        if entry["item"]:
            return {self.item(entry["item"])}
        if entry["category"] == raid_encounter.REWARD_MATERIAL:
            material = raid_encounter.tables()["material_items"].get(str(row["species"]))
            return {"TM Material"} | ({self.item(int(material))} if material else set())
        gem = {"Tera Shard"}
        if row["tera"] >= 2:
            gem.add(f"{TYPES[row['tera'] - 2]} Tera Shard")
        return gem


def named(text, names):
    """-> whether pkNX's `text` is one of `names`, a TM's name standing before its move's."""
    return text in names or any(n.startswith("TM") and text.startswith(n + " ") for n in names)


def parse(text):
    """-> (identifier, [encounter]) of an Encounters.txt: each encounter its header, its
    `Key: value` lines and its sections' lines."""
    identifier, blocks, section = None, [], None
    for line in text.splitlines():
        if not line.strip():
            continue
        depth, body = len(line) - len(line.lstrip("\t")), line.strip()
        if depth == 0 and body.startswith("Event Raid Identifier:"):
            identifier = int(body.split(":")[1])
        elif depth == 0:
            blocks.append({"head": body, "fields": {}, "sections": {}})
        elif depth == 1:
            key, _, value = body.partition(": ")
            blocks[-1]["fields"][key] = value
        elif depth == 2:
            section = body.rstrip(":")
            blocks[-1]["sections"][section] = []
        else:
            blocks[-1]["sections"][section].append(body)
    return identifier, blocks


def ability_rule(text):
    if text in ABILITY:
        return ABILITY[text]
    return ABILITY_SLOT.get(text.rsplit(" ", 1)[-1])


def extra_actions(row, names):
    """-> pkNX's lines for a row's valid extra actions (TeraRaidRipper.GetExtraActionInfo)."""
    out = []
    for i in range(6):
        action, timing, value, move = row["boss_desc"][10 + 4 * i:14 + 4 * i]
        if not action or not value or (action == 3 and not move):
            continue
        when = f"at {value}% {'Time' if timing == 1 else 'HP'} Remaining"
        out.append(f"Use {names.move(move)} {when}" if action == 3 else f"{ACTIONS[action]} {when}")
    return out


def compare_row(row, block, event, names):
    """-> [difference] between a row and pkNX's text of it."""
    fields, sections, out = block["fields"], block["sections"], []
    newer = "Extra Moves" not in sections        # pkNX's later text: gender, shield and actions

    def same(label, ours, theirs):
        if ours != theirs:
            out.append(f"{label}: ours {ours!r}, text {theirs!r}")

    head = re.match(r"(\d)-Star (.+?)(?:-(\d+))?(?: \(.*\))?$", block["head"])
    same("stars", row["stars"], int(head.group(1)))
    same("species", names.species.get(row["species"]), head.group(2))
    if head.group(3):                           # "-N" follows a form other than 0 that has a name
        same("form", row["form"], int(head.group(3)))
    same("version", row["rom"], {"Scarlet": 1, "Violet": 2}.get(fields.get("Version"), 0))
    tera = fields["Tera Type"]
    same("Tera type", row["tera"], {"Default": 0, "Random": 1}.get(tera, TYPES.index(tera) + 2
                                                                    if tera in TYPES else tera))
    same("battle level", row["level"], int(fields.get("Battle Level", fields["Capture Level"])))
    same("capture level", row["capture_level"], int(fields["Capture Level"]))
    same("ability", row["ability"], ability_rule(fields["Ability"]))
    same("nature", row["nature"], NATURES.index(fields["Nature"]) if "Nature" in fields else None)
    if newer:
        same("gender", row["gender"], {"Male": 0, "Female": 1}.get(fields.get("Gender")))
    ivs = fields["IVs"]
    if ivs.endswith("Flawless"):
        count = int(ivs.split()[0])
        same("IVs", row["ivs"] or row["flawless_ivs"], [31] * 6 if row["ivs"] else count)
    else:
        same("IVs", row["ivs"], [int(v) for v in ivs.split("/")])
    evs = dict((name, value) for name, value in zip(EV_NAMES, row["evs"]) if value)
    same("EVs", evs, {n: int(v) for v, n in (p.split() for p in fields["EVs"].split(" / "))}
         if "EVs" in fields else {})
    same("shiny", row["shiny"], {"Never": 1, "Always": 2}.get(fields.get("Shiny"), 0))
    scale = fields.get("Scale")
    if scale is None:
        same("scale", row["scale_type"], raid_encounter.SCALE_RANDOM)
    elif scale in SCALE_RANGES:
        same("scale", row["scale_type"], SCALE_RANGES[scale])
    else:
        same("scale", (row["scale_type"], row["scale"]), (raid_encounter.SCALE_VALUE, int(scale)))
    if "HP Multiplier" in fields:
        hp = float(re.sub(r"[x×]", "", fields["HP Multiplier"]).replace(",", "."))
        same("HP multiplier", row["boss_desc"][0] / 100, hp)
    same("held item", names.item(row["held_item"]) if row["held_item"] else None, fields.get("Held Item"))
    same("capture", row["capture_rate"], {"Only Once": 2, "Never": 0, "0": 0}.get(fields.get("Catchable"), 1))
    # A move newer than the pkNX that wrote the text has no name there.
    moves = [names.move(m) for i, m in enumerate(row["moves"]) if m or not i]
    same("moves", moves, [m[2:] or ours for m, ours in zip(sections["Moves"], moves + [""] * 4)])
    if "Extra Moves" in sections:
        listed = [m[2:] for m in sections["Extra Moves"] if m != "None!"]
        moves = [names.move(m) for m in row["boss_desc"][13:34:4] if m]
        same("extra moves", moves, listed)
    if "Extra Actions" in sections:
        same("extra actions", extra_actions(row, names), [m[2:] for m in sections["Extra Actions"]])
    shield = row["boss_desc"][1:3]
    if newer:
        same("shield", [f"{shield[0]}% HP Remaining", f"{shield[1]}% Time Remaining"] if all(shield) else [],
             [m[2:] for m in sections.get("Shield Activation", [])])
    fixed = event.fixed.get(row["fixed_rewards"], [])
    drops = [re.match(r"(\d+) × (.+?)(?: \((Only \w+)\))?$", d).groups() for d in sections["Item Drops"]]
    same("item drops", len(fixed), len(drops))
    for entry, (amount, name, subject) in zip(fixed, drops):
        if (entry["amount"], entry["subject"]) != (int(amount), SUBJECTS[subject or ""]) \
                or not named(name, names.reward(entry, row)):
            out.append(f"item drop {entry} against {amount} × {name} ({subject})")
    lottery = event.lottery.get(row["lottery_rewards"], [])
    total = sum(e["probability"] for e in lottery)
    bonus = [re.match(r"([\d.,]+)%\s+(\d*)\s*× (.+)$", d).groups() for d in sections["Bonus Drops"]]
    same("bonus drops", len(lottery), len(bonus))
    for entry, (rate, amount, name) in zip(lottery, bonus):
        if not total or abs(entry["probability"] / total * 100 - float(rate.replace(",", "."))) > 0.006 \
                or str(entry["amount"]) != amount or not named(name, names.reward(entry, row)):
            out.append(f"bonus drop {entry} against {rate}% {amount} × {name}")
    return out


def check_raid(found, block, event, names):
    """-> [difference] between a raid generated from a seed and the encounter's text."""
    row, boss, out = found.row, found.boss, []
    _, types, *_ = raid_encounter.personal(row["species"], row["form"])
    ivs = (boss["ivs"][0], boss["ivs"][1], boss["ivs"][2], boss["ivs"][4], boss["ivs"][5], boss["ivs"][3])
    if row["ivs"] and list(ivs) != row["ivs"] or ivs.count(31) < row["flawless_ivs"]:
        out.append(f"IVs {ivs}")
    slot = boss["ability_number"].bit_length() - 1
    if slot not in {0: (0, 1), 1: (0, 1, 2), 2: (0,), 3: (1,), 4: (2,)}[row["ability"]]:
        out.append(f"ability slot {slot}")
    for key in ("nature", "gender"):
        if row[key] is not None and boss[key] != row[key]:
            out.append(f"{key} {boss[key]}")
    if row["shiny"] and found.is_shiny != (row["shiny"] == raid_encounter.SHINY_ALWAYS):
        out.append(f"shiny {found.is_shiny}")
    band = raid_encounter.SCALE_BANDS.get(row["scale_type"])
    if band and not band[1] <= boss["scale"] < sum(band) or \
            row["scale_type"] == raid_encounter.SCALE_VALUE and boss["scale"] != row["scale"]:
        out.append(f"scale {boss['scale']}")
    if row["tera"] == 0 and found.tera_type not in types or row["tera"] >= 2 and found.tera_type != row["tera"] - 2:
        out.append(f"Tera type {found.tera_type}")
    if (list(boss["moves"]), boss["level"]) != (row["moves"], row["level"]):
        out.append(f"moves {boss['moves']} level {boss['level']}")
    # The fixed rows come first, each with a quantity that names an item, a shard or the species'
    # material, as `raid_encounter.rewards` keeps them.
    material = raid_encounter.tables()["material_items"].get(str(row["species"]))
    shown = [re.match(r"(\d+) × (.+?)(?: \(Only \w+\))?$", d).groups() for d in block["sections"]["Item Drops"]]
    fixed = [(int(q), text) for e, (q, text) in zip(event.fixed.get(row["fixed_rewards"], []), shown)
             if e["amount"] and (e["item"] or e["category"] == raid_encounter.REWARD_SHARD
                                 or e["category"] == raid_encounter.REWARD_MATERIAL and material)]
    given = [(names.item(i), q) for i, q in found.rewards]
    for (name, quantity), (amount, text) in zip(given, fixed):
        if quantity != amount or not named(text, {name, "Tera Shard", "TM Material"}):
            out.append(f"fixed reward {name} x{quantity} against {amount} × {text}")
    bonus = [re.sub(r"^[\d.,]+%\s+", "", d).split(" × ", 1) for d in block["sections"]["Bonus Drops"]]
    drawn = given[len(fixed):]
    for name, quantity in drawn:
        if not any(int(q) == quantity and named(text, {name, "Tera Shard", "TM Material"}) for q, text in bonus):
            out.append(f"lottery reward {name} x{quantity} is not a bonus drop")
    if len(drawn) > raid_encounter.REWARD_SLOTS[found.stars - 1][-1]:
        out.append(f"{len(drawn)} lottery rewards")
    plain = raid.bootstrap(found, ())
    if len(plain) != raid.BOOTSTRAP_SIZE:
        out.append("bootstrap size")
    return out


def folders(paths):
    for path in paths:
        for folder in raid_event.deliveries(path):
            if os.path.isfile(os.path.join(folder, "Encounters.txt")):
                yield folder


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="event folders, or folders holding them")
    ap.add_argument("--seeds", type=int, default=50, help="seeds per version, stage and group")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    names = Names()
    rng = random.Random(0)
    bad = raids = encounters = 0
    for folder in folders(args.paths):
        event = raid_event.load(folder)
        with open(os.path.join(folder, "Encounters.txt"), encoding="utf-8-sig") as fh:
            identifier, blocks = parse(fh.read())
        if not blocks:                  # the game's own placeholder table, 000 Base Data
            print(f"{folder}: its text lists no encounter; skipped")
            continue
        problems = [] if identifier == event.identifier else [f"identifier {event.identifier} against {identifier}"]
        if len(blocks) != len(event.rows):
            problems.append(f"{len(event.rows)} encounters against {len(blocks)}")
        by_row = {}
        for row, block in zip(event.rows, blocks):
            by_row[id(row)] = block
            problems += [f"{row['stars']}* {names.species.get(row['species'])}: {p}"
                         for p in compare_row(row, block, event, names)]
        encounters += len(blocks)
        for version in raid_encounter.VERSIONS:
            for progress in PROGRESS:
                for group in event.groups(version, progress):
                    for _ in range(args.seeds):
                        found = raid_event.generate(event, rng.getrandbits(32), version, progress, group)
                        raids += 1
                        problems += [f"{found.seed:08X} {version} {progress} group {group}: {p}"
                                     for p in check_raid(found, by_row[id(found.row)], event, names)]
        name = os.path.relpath(folder, args.paths[0]) if len(args.paths) == 1 else folder
        if problems:
            bad += 1
            print(f"{name}: {len(problems)} differences")
            for p in problems[:None if args.verbose else 5]:
                print(f"    {p}")
        elif args.verbose:
            print(f"{name}: {len(blocks)} encounters agree")
    print(f"{encounters} encounters and {raids} raids checked; {bad} events differ")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
