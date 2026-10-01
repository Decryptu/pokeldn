"""Versioned Mystery Gift files and native-format conversion. See docs/gifts.md."""

import hashlib
import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

FORMAT = "pokeldn.gift"
VERSION = 1
EXTENSION = "pokegift"
MAX_FILE_SIZE = 256 * 1024
ADAPTERS = {"frlg": "pokeldn.frlg.gift.file", "swsh": "pokeldn.swsh.gift_file"}


def adapter(game):
    if game not in ADAPTERS:
        raise ValueError(f"Mystery Gift files do not support game {game!r}.")
    return importlib.import_module(ADAPTERS[game])


@dataclass(frozen=True)
class Variant:
    data: dict
    options: dict | None = None

    def __post_init__(self):
        if not self.data or any(not isinstance(k, str) or not isinstance(v, bytes)
                                for k, v in self.data.items()):
            raise ValueError("Gift components must be named byte records.")
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))
        options = dict(self.options or {})
        for key, value in options.items():
            if not isinstance(key, str) or not isinstance(value, (str, tuple)):
                raise ValueError("Gift options must be text or tuples of integers.")
            if isinstance(value, tuple) and any(type(v) is not int for v in value):
                raise ValueError("Gift option lists must contain integers.")
        object.__setattr__(self, "options", MappingProxyType(options))


@dataclass(frozen=True)
class Gift:
    game: str
    name: str
    variants: dict[str, Variant]

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 180:
            raise ValueError("A gift name must contain 1 to 180 characters.")
        if not self.variants or len(self.variants) > 16 or any(
                not isinstance(k, str) or not isinstance(v, Variant) for k, v in self.variants.items()):
            raise ValueError("A gift needs 1 to 16 named variants.")
        object.__setattr__(self, "variants", MappingProxyType(dict(self.variants)))
        adapter(self.game).validate(self)

    @property
    def summary(self):
        return f"{self.name} · {self.game.upper()} · {', '.join(self.variants)}"


def dumps(gift):
    adapter(gift.game).validate(gift)
    variants = {target: {"data": {key: {"hex": value.hex(),
                "sha256": hashlib.sha256(value).hexdigest()} for key, value in variant.data.items()},
                "options": dict(variant.options)} for target, variant in gift.variants.items()}
    return json.dumps({"format": FORMAT, "version": VERSION, "game": gift.game,
                       "name": gift.name, "variants": variants}, indent=2, sort_keys=True) + "\n"


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate gift field {key!r}.")
        result[key] = value
    return result


def _fields(value, required):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError(f"Expected gift fields: {', '.join(required)}.")


def loads(source, *, game=None):
    if len(source.encode("utf-8") if isinstance(source, str) else source) > MAX_FILE_SIZE:
        raise ValueError("Gift file exceeds 256 KiB.")
    try:
        root = json.loads(source, object_pairs_hook=_unique)
        _fields(root, ("format", "version", "game", "name", "variants"))
        if root["format"] != FORMAT or type(root["version"]) is not int or root["version"] != VERSION:
            raise ValueError("Unsupported gift file format or version.")
        if not isinstance(root["game"], str):
            raise ValueError("A gift game must be text.")
        if game is not None and root["game"] != game:
            raise ValueError(f"This gift is for {root['game']}, not {game}.")
        if not isinstance(root["variants"], dict):
            raise ValueError("Gift variants must be an object.")
        variants = {}
        for target, value in root["variants"].items():
            _fields(value, ("data", "options"))
            if not isinstance(value["data"], dict) or not isinstance(value["options"], dict):
                raise ValueError("Gift data and options must be objects.")
            data = {}
            for key, component in value["data"].items():
                _fields(component, ("hex", "sha256"))
                if not isinstance(component["hex"], str) or not isinstance(component["sha256"], str):
                    raise ValueError("Gift component bytes and hashes must be text.")
                raw = bytes.fromhex(component["hex"])
                if hashlib.sha256(raw).hexdigest() != component["sha256"]:
                    raise ValueError(f"Gift component {key!r} failed its SHA-256 check.")
                data[key] = raw
            options = {k: tuple(v) if isinstance(v, list) else v for k, v in value["options"].items()}
            variants[target] = Variant(data, options)
        return Gift(root["game"], root["name"], variants)
    except (UnicodeError, json.JSONDecodeError, TypeError, RecursionError) as exc:
        raise ValueError(f"Invalid gift file: {exc}") from exc


def load(path, *, game=None):
    path = Path(path).expanduser()
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_SIZE + 1)
    if len(raw) > MAX_FILE_SIZE:
        raise ValueError("Gift file exceeds 256 KiB.")
    if path.suffix.lower() == ".pokegift" or raw.lstrip().startswith(b"{"):
        return loads(raw, game=game)
    if game == "swsh" or path.suffix.lower() == ".wc8":
        if game not in (None, "swsh"):
            raise ValueError(f"This gift is for swsh, not {game}.")
        return adapter("swsh").from_record(raw, name=path.stem)
    raise ValueError("Choose a .pokegift file, or a .wc8 file for Sword/Shield.")


def save(path, gift):
    source = dumps(gift)
    if len(source.encode("utf-8")) > MAX_FILE_SIZE:
        raise ValueError("Gift file exceeds 256 KiB.")
    Path(path).expanduser().write_text(source, encoding="utf-8")


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="validate and describe a gift")
    inspect.add_argument("file")
    convert = commands.add_parser("import", help="convert native gift records to .pokegift")
    convert.add_argument("--game", choices=tuple(ADAPTERS), required=True)
    convert.add_argument("--record", help="Sword/Shield .wc8")
    convert.add_argument("--card", help="FRLG WonderCard.bin")
    convert.add_argument("--script", help="FRLG Script.bin")
    convert.add_argument("--build", help="FRLG cartridge game code, e.g. BPRF")
    convert.add_argument("--name")
    convert.add_argument("-o", "--out", required=True)
    export = commands.add_parser("export", help="export native records from a gift")
    export.add_argument("file")
    export.add_argument("--build", help="FRLG cartridge game code")
    export.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            if args.game == "swsh":
                if not args.record or args.card or args.script or args.build:
                    raise ValueError("Sword/Shield import requires --record only.")
                gift = load(args.record, game="swsh")
                if args.name:
                    gift = Gift(gift.game, args.name, dict(gift.variants))
            else:
                if not args.card or not args.script or not args.build or args.record:
                    raise ValueError("FRLG import requires --card, --script and --build.")
                gift = adapter("frlg").from_bins(Path(args.card).read_bytes(),
                    Path(args.script).read_bytes(), build=args.build,
                    name=args.name or Path(args.card).stem)
            save(args.out, gift)
            print(f"Saved {args.out}: {gift.summary}")
        else:
            gift = load(args.file)
            if args.command == "inspect":
                print(gift.summary)
            else:
                for path in adapter(gift.game).export_native(gift, args.out_dir, build=args.build):
                    print(f"Saved {path}")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
