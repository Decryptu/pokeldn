"""Capture the live FRLG RNG word without writing game memory."""
from __future__ import annotations

import argparse
from pathlib import Path

from frlg_rng_assist_core.live import (
    add_live_arguments, build_info, host_common, read_trace, run_host, save_json,
    timestamp_path,
)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    add_live_arguments(parser)
    parser.add_argument("--samples", type=int, default=60,
                        help="Frames to sample (the host caps this at its trace capacity)")
    parser.add_argument("--trace-call", type=lambda value: int(value, 0), default=0,
                        help="Advanced: optional THUMB ROM call between the two reads; default 0")
    return parser


def _summary_path(capture: Path) -> Path:
    suffix = capture.suffix + ".json" if capture.suffix else ".json"
    return capture.with_suffix(suffix)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        build = str(args.build).upper()
        build_info(build)
        if not 1 <= args.samples <= 96:
            raise ValueError("samples must be 1..96")
        capture = timestamp_path(".trace.bin", args.output)
        host_args = host_common(build, keys=args.keys)
        host_args += ["--buffer-script", "rng-trace", "--trace-address",
                      hex(build_info(build).rng), "--trace-call", hex(args.trace_call),
                      "--trace-samples", str(args.samples), "--dump-file", str(capture)]
        print("连接主机：请在掌机上选择 Mystery Gift -> Wonder Cards -> Friend。")
        if args.trace_call:
            print(f"警告：将调用 ROM 0x{args.trace_call:08X}；它可能推进 gRngValue，不能视为纯只读。")
        else:
            print(f"只读采样 gRngValue @ 0x{build_info(build).rng:08X}，{args.samples} 帧；不写内存。")
        rc = run_host(host_args, radio=args.radio)
        if rc != 0 and not capture.is_file():
            return rc
        if not capture.is_file():
            print("主机未返回采样文件。")
            return rc or 1
        raw = capture.read_bytes()
        trace = read_trace(raw)
        try:
            from pokeldn.frlg.rom import buffer_script
            evidence = buffer_script.describe_rng_trace(raw)
        except (ImportError, AttributeError, ValueError):
            evidence = []
        report = {"schema": 1, "kind": "live_rng_trace", "plugin_version": "0.2.0",
                  "build": build, "address": trace["address"], "function": trace["function"],
                  "calls": trace["calls"], "taken": trace["taken"],
                  "trace_call": args.trace_call, "mutates_rng": bool(args.trace_call),
                  "samples": [list(pair) for pair in trace["samples"]], "evidence": evidence,
                  "seed_before_first_sample": (trace["samples"][0][0]
                                                if trace["samples"] else None),
                  "seed_after_first_sample": (trace["samples"][0][1]
                                               if trace["samples"] else None)}
        report_path = save_json(report, str(_summary_path(capture)))
        if args.trace_call:
            print("采样完成；主机未写存档，但 ROM 调用可能已经推进游戏 RNG。")
        else:
            print("采样完成；主机未执行游戏写入。")
        print("\n".join(evidence))
        print(f"Raw capture: {capture}")
        print(f"Report: {report_path}")
        return rc
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(2, f"RNG Assist live trace: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
