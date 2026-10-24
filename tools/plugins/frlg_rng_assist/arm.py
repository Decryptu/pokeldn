"""Configure or disarm the resident one-shot A request with RAM-only writes."""
from __future__ import annotations

import argparse

from frlg_rng_assist_core.live import (
    DEFAULT_STATE, add_live_arguments, build_info, host_common, read_chain, resident_addresses,
    run_host, save_json, timestamp_path, validate_state_address,
)
from frlg_rng_assist_core.arguments import hex_word


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    add_live_arguments(parser)
    parser.add_argument("--trigger-index", type=lambda value: int(value, 0), default=0,
                        help="Exact tracked RNG-advance index at which to arm")
    parser.add_argument("--state-address", type=lambda value: int(value, 0), default=DEFAULT_STATE,
                        help="64-byte resident state address (must match install observer)")
    parser.add_argument("--offset", type=int, default=0,
                        help="Calibrated trigger-to-generation distance, 0..255")
    parser.add_argument("--target-pid", type=hex_word, default=0,
                        help="PID recorded beside the request (runtime does not search on-device)")
    parser.add_argument("--target-nature", type=int, default=0,
                        help="Nature index recorded beside the request, 0..24")
    parser.add_argument("--mode", type=lambda value: int(value, 0), default=0,
                        help="Host-visible mode value")
    parser.add_argument("--enable-auto-a", action="store_true",
                        help="Arm one-shot A; omit to write auto_a=0 and disarm")
    return parser


def _step(address, value):
    return f"write32:0x{int(address):08X},0x{int(value) & 0xFFFFFFFF:08X}"


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        build = str(args.build).upper()
        build_info(build)
        if not 0 <= args.trigger_index <= 0xFFFFFFFF:
            raise ValueError("trigger-index must be 0..0xFFFFFFFF")
        validate_state_address(args.state_address)
        if not 0 <= args.offset <= 0xFF:
            raise ValueError("offset must be 0..255 advances")
        if not 0 <= args.target_pid <= 0xFFFFFFFF:
            raise ValueError("target-pid must be a 32-bit hexadecimal PID")
        if not 0 <= args.target_nature <= 24:
            raise ValueError("target-nature must be 0..24")
        if not 0 <= args.mode <= 0xFFFFFFFF:
            raise ValueError("mode must be a 32-bit value")
        addresses = resident_addresses()
        values = {
            "p_auto_a": 1 if args.enable_auto_a else 0,
            "p_trigger_index": args.trigger_index,
            "p_offset": args.offset,
            "p_target_pid": args.target_pid,
            "p_target_nature": args.target_nature,
            "p_mode": args.mode,
        }
        capture = timestamp_path(".arm.bin", args.output)
        host_args = host_common(build, keys=args.keys)
        host_args += ["--buffer-script", "call-chain", "--write-unsafe", "--dump-file", str(capture)]
        # The resident copies these values only during its first initialization.  Write the
        # already-installed state as well, so arming after an observer has started actually takes
        # effect and a second arm clears the previous one-shot flags.
        state_values = {
            args.state_address + 0x14: args.trigger_index,
            args.state_address + 0x28: args.target_pid,
            args.state_address + 0x2C: args.target_nature,
            args.state_address + 0x38: args.mode,
            args.state_address + 0x34: 1,  # initialized; clear pending/fired/armed/missed
        }
        for name in ("p_trigger_index", "p_offset", "p_target_pid", "p_target_nature", "p_mode"):
            host_args += ["--chain-step", _step(addresses[name], values[name])]
        for address, value in state_values.items():
            host_args += ["--chain-step", _step(address, value)]
        host_args += ["--chain-step", _step(addresses["p_auto_a"], values["p_auto_a"])]
        print("连接主机：请在掌机上选择 Mystery Gift -> Wonder Cards -> Friend。")
        print("配置驻留参数；这些是易失 RAM 写入，不会写存档。")
        print(("已显式启用一次性 A；它只会在精确 trigger-index 且回调场景匹配时执行。"
               if args.enable_auto_a else "已关闭一次性 A；其余参数已更新。"))
        rc = run_host(host_args, radio=args.radio)
        report = {"schema": 1, "kind": "live_rng_arm", "plugin_version": "0.2.0",
                  "build": build, "addresses": addresses, "values": values,
                  "auto_a_enabled": bool(args.enable_auto_a)}
        if capture.is_file():
            try:
                report["readback"] = read_chain(capture.read_bytes())
            except (OSError, RuntimeError, ValueError) as exc:
                report["readback_error"] = str(exc)
        report_path = save_json(report, str(capture) + ".json")
        if rc == 0:
            print(f"配置完成；报告：{report_path}")
        return rc
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(2, f"RNG Assist arm: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
