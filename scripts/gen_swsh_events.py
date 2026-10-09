#!/usr/bin/env python3
"""Builds pokeldn/swsh/data/events.json, the official Sword/Shield Wonder Cards the app offers, from a
folder of projectpokemon EventsGallery `.wc8` files [docs/swsh_gift.md, Official event cards].

Kept: a card the game's own validator 0x010b5de0 accepts (run from main under unicorn) and
the PKHeX gift check passes. Left out: simulated cards, ★ dummy items, and a card whose gift is the
same as one already kept (date and card id aside).

    ./.venv/bin/python scripts/gen_swsh_events.py DIR [--image scratchpad/swsh/main.bin]
"""

import argparse
import base64
import json
import os
import pathlib
import re
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "bin"), str(ROOT / "tools" / "switch")]

from pokeldn import pokemon                                     # noqa: E402
from pokeldn.swsh import events, wc8                           # noqa: E402

OUT = ROOT / "pokeldn" / "swsh" / "data" / "events.json"
GROUPS = {1: "Pokemon", 2: "Items", 3: "Battle Points", 4: "Clothing", 5: "Money"}


def label_of(name):
    """`0057a6675d__0519 SWSH - KIBO Pikachu.wc8` -> `KIBO Pikachu`; the species leads when the
    gallery opens with `(Trainer)` or a name in another script."""
    stem = re.sub(r"^[0-9a-f]+__\d+ ", "", pathlib.Path(name).stem)
    label = re.sub(r"^(SWSH|SW|SH) - ", "", stem).replace("  ", " ").strip()
    label = re.sub(r"^\(Trainer\) ", "", label)
    head, _, rest = label.partition(" ")
    return f"{rest} ({head})" if rest and not head.isascii() else label


def same_gift(raw):
    """What the card gives, without its date and card id."""
    return raw[0x0E:0x10] + raw[0x11:0x12] + (raw[0x20:0x80] if raw[0x11] != 1 else raw[0x14:0x2CC])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("folder")
    p.add_argument("--image", default=str(ROOT / "scratchpad" / "swsh" / "main.bin"))
    args = p.parse_args()
    import swsh_gift_host
    items = {n["id"]: n["name"] for n in pokemon.SERVICE.names("swsh", "items")}
    species = {n["id"]: n["name"] for n in pokemon.SERVICE.names("swsh", "species")}

    def named(kind, n):
        return (species if kind == "species" else items).get(int(n), f"{kind} #{n}")
    kept, seen, left = [], set(), {}
    for name in sorted(os.listdir(args.folder), key=label_of):
        raw = (pathlib.Path(args.folder) / name).read_bytes()
        label = label_of(name)
        why = None
        if "Simulated" in label:
            why = "simulated"
        elif not wc8.sealed(raw):
            why = "size or checksum"
        elif swsh_gift_host.validate(raw, args.image) != 0:
            why = "the game's validator"
        elif any(items.get(i, "").startswith("★") for i in events.item_ids(raw)):
            why = "a ★ dummy item"
        elif same_gift(raw) in seen:
            why = "a duplicate"
        else:
            try:
                pokemon.SERVICE.validate_gift(raw)
            except pokemon.BuilderError as exc:
                why = f"PKHeX: {exc}"
        if why:
            left[why] = left.get(why, 0) + 1
            continue
        seen.add(same_gift(raw))
        kind = raw[wc8.GIFT_KIND_AT]
        if kind == 2:
            label = ", ".join(f"{items[i]} x{q}" for i, q in events.item_pairs(raw))
        elif kind == 3:
            label = f"{struct.unpack_from('<I', raw, 0x20)[0]} Battle Points"
        summary = events.describe(raw, named)[1][0].removeprefix("Gives ").removeprefix("Adds ")
        if kind == 2:
            summary = "Into the bag"
        elif kind == 3:
            summary = "Added to the player's Battle Points"
        elif kind == 4:
            summary = summary.split(";")[0].removeprefix("Puts ").removesuffix(" in the wardrobe")
        kept.append({"label": label, "group": GROUPS[kind], "summary": summary[:1].upper() + summary[1:],
                     "record": base64.b64encode(raw).decode()})
    order = list(GROUPS.values())
    kept.sort(key=lambda e: (order.index(e["group"]), e["group"] == "Battle Points"
                             and int(e["label"].split()[0]), e["label"].casefold()))
    used = {}
    for e in kept:
        key = re.sub(r"[^a-z0-9]+", "-", e["label"].casefold()).strip("-") or "card"
        used[key] = used.get(key, 0) + 1
        e["key"] = key if used[key] == 1 else f"{key}-{used[key]}"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps([{k: e[k] for k in ("key", "label", "group", "summary", "record")} for e in kept],
                              ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"{len(kept)} cards -> {OUT.relative_to(ROOT)}; left out: {left}")


if __name__ == "__main__":
    main()
