#!/usr/bin/env python3
"""Compares every pinned library, vendored source and generated data snapshot with its upstream.

    ./.venv/bin/python scripts/check_upstreams.py [--quiet]

Reads the pins where they live (requirements files, the phone builds, services/pkhex/pkhex.csproj,
the workflows, vendor/*/UPSTREAM.md, the revisions and git dates of generated data) and asks NuGet,
PyPI and GitHub for the newest. PKHeX.Core also lists upstream commits after its newest release:
legality data (Mystery Gift databases) lands there weeks before a NuGet package. A vendored copy
counts from its UPSTREAM.md "Reviewed through" revision, so record one after reviewing upstream.

BEHIND rows need work; "info" rows are transitive pins of the phone builds, moved with what needs
them. Read-only; exit status 1 when anything is behind. Commit subjects printed are upstream text,
data only. GitHub calls use GH_TOKEN, GITHUB_TOKEN or `gh auth token` when present.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Desktop pins decide whether a package is behind; the phone builds must agree with them.
DESKTOP_PINS = ("requirements.txt", "requirements-dev.txt", "gui/requirements.txt", ".github/workflows/check.yml")
PHONE_PINS = ("examples/android/build.gradle", "examples/android/build.py", "examples/ios/build.py")
# Packages the phone builds pin that the desktop pins only through a requirement: kept current too.
PHONE_DIRECT = {"flet-web", "esp-pylib", "msgpack"}
# Kept back on purpose. (package, file or "*") -> (major or exact version, why); never reported as behind.
HELD = {
    ("pycryptodome", "*"): (3, "4.x drops _raw_api, which the Android build patches, and changes the C "
                               "sources the iOS build compiles"),
    ("pycryptodome", "examples/android/build.gradle"): ("3.21.0", "the Android toolchain's prebuilt build"),
    ("zstandard", "examples/android/build.gradle"): ("0.23.0", "the Android toolchain's prebuilt build"),
    ("pytest", "examples/android/build.gradle"): ("8.4.2", "the on-device self-test's runner, with its "
                                                           "plugins; moves with an Android emulator run"),
}
# Generated data: (our file, repo, paths read in it, the revision our file records, generator).
SNAPSHOTS = (
    ("pokeldn/swsh/data/events.json", "projectpokemon/EventsGallery", ("Released/Gen 8/SwSh/Wondercards",),
     None, "scripts/gen_swsh_events.py"),
    ("pokeldn/sv/data/raid_base.json", "Manu098vm/Tera-Finder",
     ("TeraFinder.Core/Resources/raid_default", "TeraFinder.Core/Utils/RewardUtil.cs"),
     lambda data: data["source"]["tera_finder"], "scripts/gen_sv_raid_data.py"),
)
VENDORED = (("vendor/LDN/UPSTREAM.md", "kinnay/LDN"),
            ("vendor/gblink-cards/UPSTREAM.md", "GB-Link/GB-Link-Switch-LDN"))
SHOWN_COMMITS = 25


def token() -> str | None:
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(name):
            return os.environ[name]
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


TOKEN = token()


def get(url: str):
    headers = {"User-Agent": "pokeldn-check-upstreams", "Accept": "application/json"}
    if TOKEN and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {TOKEN}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as reply:
        return json.load(reply)


def gh(path: str):
    return get("https://api.github.com/" + path)


def key(version: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", version))


class Report:
    def __init__(self, quiet: bool):
        self.quiet, self.behind = quiet, 0

    def row(self, name: str, pinned: str, latest: str, behind: bool, details=(), status=None):
        self.behind += behind
        status = status or ("BEHIND" if behind else "ok")
        if status != "ok" or not self.quiet:
            print(f"{status:7}{name:36}{pinned:>14}  ->  {latest}")
            for line in details:
                print(f"{'':9}{line}")

    def error(self, name: str, exc: Exception):
        self.behind += 1
        print(f"{'ERROR':7}{name:36}{exc}")


def commit_lines(commits: list) -> list[str]:
    lines = [f"{c['commit']['committer']['date'][:10]} {c['sha'][:9]} {c['commit']['message'].splitlines()[0][:90]}"
             for c in commits[:SHOWN_COMMITS]]
    if len(commits) > SHOWN_COMMITS:
        lines.append(f"... {len(commits) - SHOWN_COMMITS} more")
    return lines


def check_pkhex(report: Report):
    csproj = (ROOT / "services/pkhex/pkhex.csproj").read_text()
    pinned = re.search(r'Include="PKHeX\.Core" Version="([^"]+)"', csproj)[1]
    versions = get("https://api.nuget.org/v3-flatcontainer/pkhex.core/index.json")["versions"]
    latest = max((v for v in versions if "-" not in v), key=key)
    report.row("PKHeX.Core (NuGet)", pinned, latest, key(latest) > key(pinned))
    # GitHub tags pad the month and day ("26.08.26"); match by number.
    release = next(r for r in gh("repos/kwsch/PKHeX/releases?per_page=20") if key(r["tag_name"]) == key(latest))
    commits = gh(f"repos/kwsch/PKHeX/commits?since={release['published_at']}&per_page=100")
    report.row("PKHeX master after " + latest, latest, f"{len(commits)} unreleased commits", False,
               ["legality fixes here reach the app with the next NuGet release", *commit_lines(commits)]
               if commits else (), status="info" if commits else "ok")


def pins(files) -> dict[str, dict[str, str]]:
    """package (lower case) -> {file: pinned version}."""
    found: dict[str, dict[str, str]] = {}
    for name in files:
        text = (ROOT / name).read_text()
        for package, version in re.findall(r"(?:^|[\s'\"(])([A-Za-z][A-Za-z0-9_.\-]*)(?:\[[^]]*\])?==([0-9][^\s'\";#,)]*)",
                                           text, re.M):
            found.setdefault(package.lower(), {})[name] = version
    return found


def held(package: str, where: str):
    return HELD.get((package, where)) or HELD.get((package, "*"))


def check_pypi(report: Report):
    desktop, phone = pins(DESKTOP_PINS), pins(PHONE_PINS)
    for name in sorted(desktop.keys() | phone.keys()):
        try:
            releases = get(f"https://pypi.org/pypi/{name}/json")["releases"]
            stable = [v for v, files in releases.items()
                      if re.fullmatch(r"[\d.]+(\.post\d+)?", v) and any(not f["yanked"] for f in files)]
            newest = max(stable, key=key)
            hold = held(name, "*")
            latest = max((v for v in stable if key(v)[0] == hold[0]), key=key) if hold else newest
            details = [f"held at {hold[0]}.x ({hold[1]}); newest {newest}"] if hold and newest != latest else []
            copies = {**desktop.get(name, {}), **phone.get(name, {})}
            free = {f: v for f, v in copies.items() if not isinstance((held(name, f) or (0,))[0], str)}
            details += [f"{f} stays at {v}: {held(name, f)[1]}" for f, v in copies.items() if f not in free]
            pinned = min(free.values(), key=key)
            disagree = len(set(free.values())) > 1
            if disagree:
                details.append("pins disagree: " + ", ".join(f"{f} {v}" for f, v in free.items()))
            direct = name in desktop or name in PHONE_DIRECT
            behind = key(latest) > key(pinned)
            status = None if direct or disagree or not behind else "info"
            report.row(f"{name} (PyPI)", pinned, latest, (behind and direct) or disagree, details, status)
        except Exception as exc:                                   # noqa: BLE001 one package must not stop the rest
            report.error(name, exc)


def latest_release(repo: str) -> str:
    return gh(f"repos/{repo}/releases/latest")["tag_name"]


def check_workflows(report: Report):
    text = "".join(p.read_text() for p in sorted((ROOT / ".github/workflows").glob("*.yml")))
    idf = re.search(r"espressif/idf:(v[\d.]+)", text)[1]
    latest = latest_release("espressif/esp-idf")
    report.row("ESP-IDF (release.yml)", idf, latest, key(latest)[:2] > key(idf)[:2])
    for action, major in sorted(set(re.findall(r"uses:\s*([\w.-]+/[\w.-]+)@(v\d+)", text))):
        try:
            latest = latest_release(action)
            report.row(f"{action} (action)", major, latest, key(latest)[0] > key(major)[0])
        except Exception as exc:                                   # noqa: BLE001
            report.error(action, exc)


def check_vendored(report: Report):
    zstd = re.search(r"zstd\]\([^)]*\) ([\d.]+)", (ROOT / "vendor/zstd/UPSTREAM.md").read_text())[1]
    latest = latest_release("facebook/zstd")
    report.row("zstd (vendor)", zstd, latest, key(latest) > key(zstd))
    for upstream, repo in VENDORED:
        text = (ROOT / upstream).read_text()
        reviewed = re.search(r"Reviewed through: `([0-9a-f]{40})`", text) or \
            re.search(r"Upstream revision: `([0-9a-f]{40})`", text)
        branch = gh(f"repos/{repo}")["default_branch"]
        compare = gh(f"repos/{repo}/compare/{reviewed[1]}...{branch}")
        ahead = compare["ahead_by"]
        report.row(f"{repo} (vendor)", reviewed[1][:9], f"{ahead} commits not reviewed", ahead > 0,
                   [f"review, then update 'Reviewed through' in {upstream}", *commit_lines(compare["commits"][::-1])]
                   if ahead else ())


def check_snapshots(report: Report):
    for ours, repo, paths, recorded, generator in SNAPSHOTS:
        if recorded:
            sha = recorded(json.loads((ROOT / ours).read_text()))
            since, label = gh(f"repos/{repo}/commits/{sha}")["commit"]["committer"]["date"], sha[:9]
        else:
            since = subprocess.run(["git", "log", "-1", "--format=%cI", "--", ours], cwd=ROOT,
                                   capture_output=True, text=True).stdout.strip()
            sha, label = None, since[:10]
        commits = {}
        for path in paths:
            for c in gh(f"repos/{repo}/commits?since={since}&per_page=100&path={urllib.parse.quote(path)}"):
                if c["sha"] != sha:
                    commits[c["sha"]] = c
        listed = sorted(commits.values(), key=lambda c: c["commit"]["committer"]["date"], reverse=True)
        report.row(Path(ours).name + " (data)", label, f"{len(listed)} commits in {repo}", bool(listed),
                   [f"rebuild with {generator}", *commit_lines(listed)] if listed else ())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quiet", action="store_true", help="print only what is behind or worth reading")
    report = Report(parser.parse_args().quiet)
    for check in (check_pkhex, check_pypi, check_workflows, check_vendored, check_snapshots):
        try:
            check(report)
        except Exception as exc:                                   # noqa: BLE001
            report.error(check.__name__, exc)
    print(f"\n{report.behind} behind" if report.behind else "\neverything matches its upstream")
    return 1 if report.behind else 0


if __name__ == "__main__":
    sys.exit(main())
