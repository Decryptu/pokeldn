"""Record one calibration sample; never mark a timing profile verified automatically."""
import argparse
import json

from frlg_rng_assist_core.arguments import add_common, hex_word, ivs
from frlg_rng_assist_core.model import calibrate
from frlg_rng_assist_core.reporting import save_report, show_report


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    add_common(parser)
    parser.add_argument("--hit-seed", type=hex_word, required=True)
    parser.add_argument("--pid", type=hex_word, required=True)
    parser.add_argument("--ivs", type=ivs, required=True)
    parser.add_argument("--max-offset", type=int, default=4096)
    parser.add_argument("--hit-boundary", choices=("unspecified", "post-vblank"), default="unspecified",
                        help="Choose post-vblank only for a verified reading after the original VBlank handler")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = calibrate(args.hit_seed, args.pid, args.ivs, build=args.build,
                           encounter=args.encounter, max_offset=args.max_offset, hit_boundary=args.hit_boundary)
        path = save_report(report, args.output, no_save=args.no_save)
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(2, f"RNG Assist: {exc}\n")
    if args.json:
        print(json.dumps(report))
    else:
        print(f"Calibration: {report['result']}; timing profile remains unverified.")
        for candidate in report["candidates"]:
            print(f"Method {candidate['method']} | pre-PID {candidate['generation_seed']:08X} | "
                  f"offset {candidate['offset_advances']} RNG advances")
        if path:
            print(f"Report: {path}")
        show_report(report)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
