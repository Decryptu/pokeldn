#!/usr/bin/env python3
"""Extract Sword/Shield's 0x84 party snapshot from a swsh_connect.py JSONL capture.

Usage: ./.venv/bin/python tools/switch/swsh_snapshot.py CAPTURE.jsonl SNAPSHOT.bin
The capture must include the three 0x84 fragments from a local Link Trade session.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pokeldn.ldn import broadcast4
from pokeldn.swsh import trade_payload


def extract(path):
    fragments = {}
    total = None
    with open(path) as capture:
        for line in capture:
            row = json.loads(line)
            if row.get("rec") != "rx":
                continue
            for msg in row.get("msgs", ()):
                if msg.get("protocol") != broadcast4.PROTOCOL:
                    continue
                packet = broadcast4.parse(bytes.fromhex(msg["payload"]))
                if packet["is_control"]:
                    total = packet["total"]
                elif packet["is_data"]:
                    fragments.setdefault(packet["index"], packet["body"])
            if all(i in fragments for i in range(trade_payload.FRAGMENT_COUNT)):
                if total is not None and total != trade_payload.PAYLOAD_LENGTH:
                    raise ValueError(f"console announced {total} bytes, expected "
                                     f"{trade_payload.PAYLOAD_LENGTH}")
                return trade_payload.reassemble(
                    [fragments[i] for i in range(trade_payload.FRAGMENT_COUNT)])
    raise ValueError(f"incomplete 0x84 snapshot: fragments {sorted(fragments)}, expected "
                     f"0..{trade_payload.FRAGMENT_COUNT - 1}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capture", help="JSONL file written by swsh_connect.py --capture")
    ap.add_argument("output", help="where to write the 3456-byte snapshot")
    args = ap.parse_args()
    payload = extract(args.capture)
    Path(args.output).write_bytes(payload)
    print(f"wrote {args.output} ({len(payload)} bytes)")


if __name__ == "__main__":
    main()
