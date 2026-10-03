#!/usr/bin/env python3
"""Distribute a Sword/Shield Mystery Gift by advertising it on LDN (docs/swsh_gift.md).

The gift screen scans and never joins: the card rides the 0x180-byte advertise data, one fragment
per advertisement.

    sudo ./bin/swsh_gift_host.py --species 25 --level 25 --nickname POKELDN --ot POKELDN
    sudo ./bin/swsh_gift_host.py --record scratchpad/card.bin --dwell 0.5

    (them) Mystery Gift -> Recevoir un Cadeau Mystere -> Via communication sans fil locale
"""
from pathlib import Path
import argparse
import os
import sys
import struct
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn import config, gifts, pokemon
from pokeldn.app import screen
from pokeldn.host_support import write_file
from pokeldn.ldn import transport
from pokeldn.ldn.transport import HostTransport
from pokeldn.swsh import COMM_ID, PASSPHRASE, beacon, wc8

SCENE_ID = 0            # the console's scan filter keys on the communication id, not the scene
APP_VERSION = 4
LDN_PROTOCOL = 1        # the retail gift screen advertises protocol 1 (AES-CTR); the GBA app uses 3
VALIDATOR = 0x010b5de0  # the game's Wonder Card check: 0 sealed, 0x80000001 checksum (docs/swsh_gift.md)


def build_record(args):
    rec = _base_record(args)
    for item in args.patch or ():
        off, _, data = item.partition("=")
        rec = bytearray(rec)
        rec[int(off, 0):int(off, 0) + len(data) // 2] = bytes.fromhex(data)
        rec = wc8.seal(rec)
    return bytes(rec)


def _base_record(args):
    if args.record:
        from pokeldn.swsh.gift_file import record
        return record(gifts.load(args.record, game="swsh"))
    fields = {"ot_gender": 2}            # every card a console has taken carried 2 at +0x272
    for item in args.set or ():
        name, _, value = item.partition("=")
        if name not in wc8.POKEMON:
            raise SystemExit(f"--set {name}: not a record field; one of {', '.join(wc8.POKEMON)}")
        fields[name] = int(value, 0)
    return wc8.pokemon_card(
        species=args.species, level=args.level, form=args.form,
        moves=(args.move1, args.move2, args.move3, args.move4),
        nickname=args.nickname, ot=args.ot, card_id=args.card_id,
        region_mask=args.region_mask, ribbons=args.ribbon or (), **fields)


def show_card(args, record):
    """The card on the board's screen: the gift file's name, or the Pokemon this run built, drawn
    when the record carries one (kind 1)."""
    off, fmt = wc8.POKEMON["species"]
    species = (struct.unpack_from("<" + fmt, record, off)[0]
               if record[wc8.GIFT_KIND_AT] == wc8.GIFT_KIND_POKEMON else None)
    line = (gifts.load(args.record, game="swsh").name if args.record else
            args.nickname or (f"Pokemon #{species}" if species else ""))
    screen.gift("Mystery Gift", line, species=species)


def validate(record, image):
    """-> the game's own validator's answer for `record`, run from `image` under unicorn. Covers
    the seal only; an item id the bag cannot hold still passes."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    "tools", "switch"))
    from nso_run import SCRATCH, Runner
    r = Runner(image)
    card, header, rec = SCRATCH + 0x1000, SCRATCH + 0x3000, SCRATCH + 0x4000
    r.write(card, bytes(0x3A8))
    r.write(header, bytes(0x68))
    r.write(rec, record)
    return r.call(VALIDATOR, (0, card, header, rec, len(record)))[0]


def build_parser():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--record", "--gift-file", dest="record",
                   help="a .pokegift or 720-byte .wc8 record to send instead of building one")
    p.add_argument("--export-gift", metavar="FILE", help="save a .pokegift file and exit without using the radio")
    p.add_argument("--species", type=int, default=25)
    p.add_argument("--level", type=int, default=25, help="0 makes the game roll one")
    p.add_argument("--form", type=int, default=0)
    p.add_argument("--move1", type=int, default=0)
    p.add_argument("--move2", type=int, default=0)
    p.add_argument("--move3", type=int, default=0)
    p.add_argument("--move4", type=int, default=0)
    p.add_argument("--nickname", default=None)
    p.add_argument("--ot", default=None)
    p.add_argument("--set", action="append", metavar="FIELD=VALUE",
                   help="any other record field by name: shiny_type=3, ball=1, held_item=236, "
                        "gender=1, nature=10, ability_type=2, iv_hp=31, dynamax_level=10, "
                        "gigantamax=1, tid=12345, sid=54321 ...")
    p.add_argument("--ribbon", action="append", type=int, help="a ribbon index; repeatable")
    p.add_argument("--patch", action="append", metavar="OFFSET=HEX",
                   help="bytes written over the record at OFFSET before sealing, for the fields "
                        "no name covers (0x15=0b for the title index); repeatable")
    p.add_argument("--card-id", type=lambda s: int(s, 0), default=0x270F)
    p.add_argument("--region-mask", type=lambda s: int(s, 0), default=0xFFFF)
    p.add_argument("--dwell", type=float, default=0.5,
                   help="seconds each fragment stays on the air")
    p.add_argument("--seconds", type=float, default=300)
    p.add_argument("--channel", type=int, default=None)
    p.add_argument("--phy", default="auto", help="the phy renumbers on every driver reload")
    p.add_argument("--nickname-host", default="POKELDN", help="the network's own name")
    p.add_argument("--keys", default=None, help="prod.keys; default from config/host.toml")
    p.add_argument("--scene-id", type=int, default=SCENE_ID)
    p.add_argument("--app-version", type=int, default=APP_VERSION)
    p.add_argument("--protocol", type=int, default=LDN_PROTOCOL, choices=(1, 3),
                   help="LDN advertisement protocol version")
    p.add_argument("--dump", help="write the record and its fragments here and exit")
    p.add_argument("--image", default=None,
                   help="optional research check using Sword's main NSO")
    p.add_argument("--no-validate", action="store_true",
                   help="skip the optional NSO check; PKHeX validation remains required")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    try:
        record = build_record(args)
        pokemon.SERVICE.validate_gift(record)
    except (OSError, pokemon.BuilderError, ValueError, struct.error) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.export_gift:
        from pokeldn.swsh.gift_file import from_record
        try:
            gift = (gifts.load(args.record, game="swsh") if args.record and not args.patch else
                    from_record(record, name=args.nickname or "Sword/Shield gift"))
            gifts.save(args.export_gift, gift)
        except (OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"Saved {args.export_gift}: {gift.summary}")
        return 0
    fragments = beacon.build_message(record)
    print(f"record {len(record)} bytes, checksum {wc8.record_crc(record):#06x}, "
          f"{len(fragments)} fragments")
    if args.image and not args.no_validate:
        if not os.path.exists(args.image):
            print(f"{args.image} is missing: the record cannot be validated; pass --image or "
                  f"--no-validate", file=sys.stderr)
            return 1
        verdict = validate(record, args.image)
        print(f"the game's validator returned {verdict:#x}")
        if verdict != 0:
            print("refusing to send a record the game rejects", file=sys.stderr)
            return 1

    if args.dump:
        write_file(args.dump, record)
        for i, f in enumerate(fragments):
            write_file(f"{args.dump}.frag{i}", f)
        print(f"wrote {args.dump} and {len(fragments)} fragments")
        return 0

    # docs/hardware_adapters.md: the Wi-Fi profile and keys path come from config/host*.toml.
    machine = config.load_project_host_file_config()
    phy = transport.find_ap_phy(log=print) if args.phy == "auto" else args.phy
    if phy is None:
        print("no AP-capable phy found", file=sys.stderr)
        return 1
    host = make_host(args, fragments, os.path.expanduser(args.keys or machine.keys_path), phy,
                     machine)
    host.start()  # raises when the AP does not come up
    show_card(args, record)
    print(f"advertising comm id {COMM_ID:#018x}, scene {args.scene_id}, protocol {args.protocol}, "
          f"walking {len(fragments)} fragments every {args.dwell}s")
    i = 0
    try:
        i = walk(host, fragments, args.dwell, time.time() + args.seconds)
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        host.stop()
    print(f"served {i} advertisements")
    return 0


def make_host(args, fragments, keys_path, phy, machine):
    """The gift screen's title, protocol 1, eight seats."""
    return HostTransport(
        app_data=fragments[0], password=PASSPHRASE, nickname=args.nickname_host,
        keys_path=keys_path, local_comm_id=COMM_ID,
        scene_id=args.scene_id, app_version=args.app_version, max_participants=8,
        protocol=args.protocol,
        phyname=phy, channel=args.channel,
        skip_encryption=machine.skip_encryption,
        accept_decrypted_ccmp=machine.accept_decrypted_ccmp)


def walk(host, fragments, dwell, deadline, stop=None):
    """`dwell` seconds per fragment. -> how many."""
    i = 0
    while time.time() < deadline and not (stop is not None and stop.is_set()):
        host.set_app_data_later(fragments[i % len(fragments)])
        i += 1
        time.sleep(dwell)
    return i


if __name__ == "__main__":
    sys.exit(main())
