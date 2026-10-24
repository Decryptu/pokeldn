"""Install the read-only resident RNG tracker until the next soft reset."""
from __future__ import annotations

import argparse

from frlg_rng_assist_core.live import (
    DEFAULT_STATE, add_live_arguments, build_info, host_common, run_host, timestamp_path,
    validate_state_address,
)
from frlg_rng_assist_core.arguments import hex_word


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    add_live_arguments(parser)
    parser.add_argument("--state-address", type=lambda value: int(value, 0), default=DEFAULT_STATE,
                        help="64-byte volatile state address (default 0x0203FF80)")
    parser.add_argument("--trigger-index", type=lambda value: int(value, 0), default=0,
                        help="Optional exact tracked index for Auto-A; normally set by arm tool")
    parser.add_argument("--offset", type=int, default=0,
                        help="Calibrated RNG advances from trigger to target (0..255)")
    parser.add_argument("--target-pid", type=hex_word, default=0)
    parser.add_argument("--target-nature", type=int, default=0)
    parser.add_argument("--mode", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--enable-auto-a", action="store_true",
                        help="Explicitly arm one-shot A immediately; default is observer-only")
    return parser


def _param(name, value):
    return f"{name}=0x{int(value) & 0xFFFFFFFF:X}"


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        build = str(args.build).upper()
        build_info(build)
        validate_state_address(args.state_address)
        if not 0 <= args.trigger_index <= 0xFFFFFFFF:
            raise ValueError("trigger-index must be 0..0xFFFFFFFF")
        if not 0 <= args.offset <= 0xFF:
            raise ValueError("offset must be 0..255 advances")
        if not 0 <= args.target_pid <= 0xFFFFFFFF:
            raise ValueError("target-pid must be a 32-bit hexadecimal PID")
        if not 0 <= args.target_nature <= 24:
            raise ValueError("target-nature must be 0..24")
        if not 0 <= args.mode <= 0xFFFFFFFF:
            raise ValueError("mode must be a 32-bit value")
        capture = timestamp_path(".install.bin", args.output)
        host_args = host_common(build, keys=args.keys)
        host_args += ["--buffer-script", "install-resident", "--resident", "rng-assist",
                      "--write-unsafe", "--dump-file", str(capture),
                      "--resident-param", _param("state", args.state_address),
                      "--resident-param", _param("trigger_index", args.trigger_index),
                      "--resident-param", _param("offset", args.offset),
                      "--resident-param", _param("target_pid", args.target_pid),
                      "--resident-param", _param("target_nature", args.target_nature),
                      "--resident-param", _param("mode", args.mode),
                      "--resident-param", _param("auto_a", 1 if args.enable_auto_a else 0)]
        print("连接主机：请在掌机上选择 Mystery Gift -> Wonder Cards -> Friend。")
        print("安装 rng-assist 驻留观察器；只写易失 RAM，软复位后消失，不写存档。")
        if args.enable_auto_a:
            print("警告：本次安装已显式启用一次性 A；请确认 trigger-index/offset 来自同一会话。")
        else:
            print("Auto-A 默认关闭；安装后先用‘读取状态’确认跟踪，再用‘配置一次性 A’。")
        rc = run_host(host_args, radio=args.radio)
        if rc == 0:
            print("Resident rng-assist 已安装；现在可运行‘读取状态’查看 seed/index。")
        elif capture.is_file():
            print(f"主机返回码 {rc}，但已留下安装回应：{capture}")
        return rc
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(2, f"RNG Assist install: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
