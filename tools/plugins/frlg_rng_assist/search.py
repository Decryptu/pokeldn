"""Offline candidate search. No network, payload installation or controller calls."""
import argparse
import json

from frlg_rng_assist_core.arguments import add_common, hex_word, ivs
from frlg_rng_assist_core.compat import backend
from frlg_rng_assist_core.model import Criteria, search
from frlg_rng_assist_core.reporting import save_report, show_progress, show_report


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    add_common(parser)
    parser.add_argument("--seed", required=True, type=hex_word)
    parser.add_argument("--tid", required=True, type=int)
    parser.add_argument("--sid", required=True, type=int)
    parser.add_argument("--method", type=int, choices=(1, 2, 4), default=1)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--advances", type=int, default=100000)
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--any-shininess", action="store_true")
    parser.add_argument("--nature", help="English name or index 0..24")
    parser.add_argument("--pid", type=hex_word, help="Exact PID filter; never written to the console")
    parser.add_argument("--iv-min", type=ivs, default=(0, 0, 0, 0, 0, 0))
    parser.add_argument("--offset", type=int, help="Measured HIT-to-pre-PID RNG advances; no frame conversion")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        nature = None
        if args.nature is not None:
            _, countdown = backend()
            names = [name.lower() for name in countdown.NATURE_NAMES]
            nature = names.index(args.nature.lower()) if args.nature.lower() in names else int(args.nature)
        criteria = Criteria(not args.any_shininess, nature, args.pid, args.iv_min)
        report = search(args.seed, args.tid, args.sid, build=args.build, encounter=args.encounter,
                        method=args.method, advances=args.advances, start=args.start,
                        max_results=args.max_results, criteria=criteria, offset=args.offset,
                        progress=None if args.json else show_progress)
        path = save_report(report, args.output, no_save=args.no_save)
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(2, f"RNG Assist: {exc}\n")
    if args.json:
        print(json.dumps(report))
    else:
        print(f"Offline: {report['candidates_tested']} candidates; {len(report['targets'])} targets. "
              "No live synchronization or Auto-A.")
        for hit in report["targets"]:
            print(f"+{hit['predicted_generation_index']} advances | "
                  f"seed {hit['predicted_generation_seed']:08X} | PID {hit['pid']:08X} | "
                  f"{hit['nature_name']} | IVs {'/'.join(map(str, hit['ivs']))}")
            if hit["trigger_index"] is not None:
                print(f"  Predicted trigger: +{hit['trigger_index']} advances | "
                      f"seed {hit['trigger_seed']:08X} | unverified timing")
            else:
                print(f"  Trigger: {hit['trigger_status']}")
        if path:
            print(f"Report: {path}")
        show_report(report)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
