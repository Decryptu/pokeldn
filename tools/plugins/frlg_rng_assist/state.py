"""Read and decode the resident RNG Assist state block."""
from __future__ import annotations

import argparse
from pathlib import Path

from frlg_rng_assist_core.live import (
    DEFAULT_STATE, add_live_arguments, build_info, decode_state, host_common, print_state,
    run_host, save_json, timestamp_path, validate_state_address,
)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    add_live_arguments(parser)
    parser.add_argument("--state-address", type=lambda value: int(value, 0), default=DEFAULT_STATE,
                        help="Resident state address (default 0x0203FF80)")
    return parser


def _summary_path(capture: Path) -> Path:
    return capture.with_suffix(capture.suffix + ".json" if capture.suffix else ".json")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        build = str(args.build).upper()
        build_info(build)
        validate_state_address(args.state_address)
        capture = timestamp_path(".state.bin", args.output)
        host_args = host_common(build, keys=args.keys)
        host_args += ["--buffer-script", "memory-dump", "--dump-address",
                      hex(args.state_address), "--dump-size", "64", "--dump-file", str(capture)]
        print("连接主机：请在掌机上选择 Mystery Gift -> Wonder Cards -> Friend。")
        print(f"只读读取 resident state @ 0x{args.state_address:08X}（64 字节）。")
        rc = run_host(host_args, radio=args.radio)
        if rc != 0 and not capture.is_file():
            return rc
        if not capture.is_file():
            print("主机未返回状态文件。")
            return rc or 1
        state = decode_state(capture.read_bytes())
        report = {"schema": 1, "kind": "live_rng_state", "plugin_version": "0.2.0",
                  "build": build, "address": args.state_address, "state": state}
        report_path = save_json(report, str(_summary_path(capture)))
        print_state(state)
        print(f"Raw capture: {capture}")
        print(f"Report: {report_path}")
        return rc
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(2, f"RNG Assist state: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
