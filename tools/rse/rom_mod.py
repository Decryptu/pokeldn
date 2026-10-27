#!/usr/bin/env python3
"""Put a ROM in place of a FireRed/LeafGreen title's cartridge as a LayeredFS mod over its RomFS file,
in Ryujinx or on an Atmosphere SD card [docs/rse_switch_build.md, Running it]. The title's own files
and saves are untouched; removing the mod restores the game.

    ./.venv/bin/python tools/rse/rom_mod.py install ROM --title 0100554023408000
    ./.venv/bin/python tools/rse/rom_mod.py install ROM --title 0100554023408000 --sd /Volumes/SWITCH
    ./.venv/bin/python tools/rse/rom_mod.py remove --title 0100554023408000 [--sd ...]
    ./.venv/bin/python tools/rse/rom_mod.py status [--sd ...]

The ROM must be built for the title's cartridge (emerald_switch_build.py --cart): BPRE for English
FireRed. --data names a Ryujinx data folder other than the default.
"""
import argparse
import os
import shutil
import sys

# title id -> (RomFS file, cartridge) [docs/frlg_rom_map.md, The cartridge image]
TITLES = {"0100554023408000": ("FireRed_e.gba", "BPRE"),
          "010034D02340E000": ("LeafGreen_e.gba", "BPGE"),
          "01004B3023412000": ("FireRed_f.gba", "BPRF"),
          "010087C02342E000": ("LeafGreen_f.gba", "BPGF")}
MOD = "pokeldn_rom"
DEFAULT_DATA = {"darwin": "~/Library/Application Support/Ryujinx",
                "win32": "~/AppData/Roaming/Ryujinx"}.get(sys.platform, "~/.config/Ryujinx")


def mod_dir(args, title):
    """Ryujinx: mods/contents/<title>/<mod>/romfs. Atmosphere: atmosphere/contents/<TITLE>/romfs."""
    if args.sd:
        return os.path.join(os.path.expanduser(args.sd), "atmosphere", "contents", title.upper())
    return os.path.join(os.path.expanduser(args.data), "mods", "contents", title.lower(), MOD)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("install", "remove", "status"))
    ap.add_argument("rom", nargs="?")
    ap.add_argument("--title", default="0100554023408000", choices=sorted(TITLES))
    ap.add_argument("--data", default=DEFAULT_DATA, help="Ryujinx data folder")
    ap.add_argument("--sd", help="root of an Atmosphere SD card, instead of Ryujinx")
    args = ap.parse_args()

    if args.action == "status":
        for title, (name, cart) in sorted(TITLES.items()):
            path = os.path.join(mod_dir(args, title), "romfs", name)
            print(f"{title} {cart}: {'ROM ' + path if os.path.exists(path) else 'the original game'}")
        return
    target = mod_dir(args, args.title)
    name, cart = TITLES[args.title]
    if args.action == "remove":
        path = os.path.join(target, "romfs", name)
        if os.path.exists(path):
            os.remove(path)
        if not args.sd:
            shutil.rmtree(target, ignore_errors=True)
        print(f"removed {path}")
        return
    if not args.rom:
        sys.exit("install needs the ROM")
    rom = open(args.rom, "rb").read()
    if len(rom) > 0x2000000 or rom[0xAC:0xB0] != b"BPEE":
        print(f"warning: {args.rom} is not an English Emerald ROM (game code {rom[0xAC:0xB0]!r})")
    if cart not in os.path.basename(args.rom):
        print(f"warning: this title's cartridge is {cart}; a ROM built for another one has no wireless")
    os.makedirs(os.path.join(target, "romfs"), exist_ok=True)
    shutil.copyfile(args.rom, os.path.join(target, "romfs", name))
    print(f"installed {args.rom} as {name} in {target}")


if __name__ == "__main__":
    main()
