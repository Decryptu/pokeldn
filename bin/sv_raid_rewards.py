#!/usr/bin/env python3
"""Create, validate, inspect, and encode Scarlet/Violet raid reward profiles."""

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sv_raid_bootstrap_codec import (
    REWARD_PROFILE_FORMAT,
    REWARD_PROFILE_TEMPLATE,
    decode_application,
    encode_reward_profile_application,
    extract_retail_bootstrap,
    inspect_avalugg_rewards,
    load_reward_profile,
    parse_reward_profile,
)


def _reward(value):
    try:
        item_text, quantity_text = value.split(":", 1)
        item_id = int(item_text, 0)
        quantity = int(quantity_text, 0)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("reward must be ITEM_ID:QUANTITY") from exc
    return {"item_id": item_id, "quantity": quantity}


def _profile_json(profile):
    return {
        "format": profile.format,
        "template": profile.template,
        "mode": profile.mode,
        **({"name": profile.name} if profile.name else {}),
        "rewards": [
            {"item_id": reward.item_id, "quantity": reward.quantity}
            for reward in profile.rewards
        ],
    }


def _write_json(path, value, force=False):
    text = json.dumps(value, indent=2) + "\n"
    if str(path) == "-":
        sys.stdout.write(text)
        return
    output = Path(path)
    if output.exists() and not force:
        raise ValueError(f"refusing to overwrite {output}; pass --force")
    try:
        output.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot write {output}: {exc}") from exc


def _write_bytes(path, value, force=False):
    output = Path(path)
    if output.exists() and not force:
        raise ValueError(f"refusing to overwrite {output}; pass --force")
    try:
        output.write_bytes(value)
    except OSError as exc:
        raise ValueError(f"cannot write {output}: {exc}") from exc


def _check_outputs(paths, force=False):
    for path in paths:
        if path is not None and Path(path).exists() and not force:
            raise ValueError(f"refusing to overwrite {path}; pass --force")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="create a version-1 exact reward profile")
    create.add_argument("--reward", action="append", required=True, type=_reward,
                        metavar="ITEM_ID:QUANTITY",
                        help="add one reward in display order; repeat up to 16 times")
    create.add_argument("--name", default="")
    create.add_argument("--output", "-o", default="-", metavar="JSON",
                        help="output path, or - for stdout")
    create.add_argument("--force", action="store_true")

    validate = subparsers.add_parser("validate", help="validate and normalize a profile")
    validate.add_argument("profile", type=Path)

    inspect = subparsers.add_parser("inspect", help="inspect all known donor reward slots")
    inspect.add_argument("--trace", required=True, type=Path, metavar="JSONL")

    encode = subparsers.add_parser("encode", help="encode a profile into a donor application")
    encode.add_argument("profile", type=Path)
    encode.add_argument("--trace", required=True, type=Path, metavar="JSONL")
    encode.add_argument("--application-out", required=True, type=Path, metavar="BIN")
    encode.add_argument("--raw-out", type=Path, metavar="BIN",
                        help="also write the decoded 0xAA0-byte result")
    encode.add_argument("--force", action="store_true")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "create":
            value = {
                "format": REWARD_PROFILE_FORMAT,
                "template": REWARD_PROFILE_TEMPLATE,
                "mode": "exact",
                **({"name": args.name} if args.name else {}),
                "rewards": args.reward,
            }
            profile = parse_reward_profile(value)
            _write_json(args.output, _profile_json(profile), args.force)
        elif args.command == "validate":
            print(json.dumps(_profile_json(load_reward_profile(args.profile)), indent=2))
        elif args.command == "inspect":
            application = extract_retail_bootstrap(args.trace)
            raw = decode_application(application)
            value = {
                "application_size": len(application),
                "raw_size": len(raw),
                "records": inspect_avalugg_rewards(raw),
            }
            print(json.dumps(value, indent=2))
        elif args.command == "encode":
            _check_outputs((args.application_out, args.raw_out), args.force)
            profile = load_reward_profile(args.profile)
            application = extract_retail_bootstrap(args.trace)
            changed = encode_reward_profile_application(application, profile)
            _write_bytes(args.application_out, changed, args.force)
            if args.raw_out:
                _write_bytes(args.raw_out, decode_application(changed), args.force)
            print(json.dumps({
                "profile": profile.name,
                "reward_count": len(profile.rewards),
                "original_application_size": len(application),
                "encoded_application_size": len(changed),
                "application_out": str(args.application_out),
                "raw_out": str(args.raw_out) if args.raw_out else None,
            }, indent=2))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
