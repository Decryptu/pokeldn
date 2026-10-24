"""Public plugin APIs only; normal command-line execution also works on older checkouts."""
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def show_progress(done, total):
    try:
        from pokeldn import progress
    except ImportError:
        return
    progress.show(done, total, "FRLG offline RNG candidates", "items")


def show_report(report):
    try:
        from pokeldn import panel
    except ImportError:
        return
    if report["kind"] == "offline_search":
        lines = [f"Source\tManual seed / offline", f"Candidates\t{report['candidates_tested']}",
                 f"Targets\t{len(report['targets'])}", "Console sync\tUnavailable", "Auto-A\tUnavailable"]
    else:
        lines = [f"Result\t{report['result']}", f"Candidates\t{len(report['candidates'])}",
                 "Timing profile\tUnverified; collect at least 20 consistent samples"]
    panel.show("rng-assist", "FRLG RNG Assist", lines, tone="info")


def save_report(report, output=None, *, no_save=False):
    report["created_at"] = datetime.now(timezone.utc).isoformat()
    report["plugin_version"] = "0.2.0"
    if no_save:
        return None
    if output is None:
        try:
            from pokeldn.plugins import library_folder
        except ImportError:
            raise ValueError("Use --output FILE or --no-save outside a supported PokeLDN plugin host") from None
        try:
            folder = library_folder("frlg-rng-assist")
        except LookupError:
            raise ValueError("Load the plugin first, or use --output FILE or --no-save") from None
        filename = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8] + ".json"
        output = folder / filename
    path = Path(output)
    # Exclusive creation makes accidental replacement of earlier calibration records impossible.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return path
