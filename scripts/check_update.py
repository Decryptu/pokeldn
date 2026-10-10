#!/usr/bin/env python3
"""Update a packed app in place from a release served on 127.0.0.1, end to end (docs/gui.md, Updates).

    python scripts/check_update.py ARCHIVE FOLDER [--admin] [--busy]

Installs the app from ARCHIVE (a release workflow's pokeldn-*.zip or .tar.gz) in FOLDER, serves the
same app with a marker file as release 99.0.0, and runs the installed app's own update code through
`--run`; the dialog's Update now calls the same functions. Passes when the marker is in FOLDER, the
new app has read the outcome, and no `.old` copy is left. `--admin` takes the Windows administrator
path (POKELDN_UPDATE_ADMIN); `--busy` keeps a second process running from the installed folder.
Needs a desktop session (xvfb-run on Linux): the helper and the new app open windows.
"""
import argparse
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pokeldn.app import update  # noqa: E402
from pokeldn.app.paths import DATA  # noqa: E402

MARKER = "UPDATED-BY-CHECK"
DRIVER = """
import sys
from pokeldn.app import update
release = update.check()
assert release and release.installable, release
root = update.install_root()
reason = update.blocker(root)
assert not reason, reason
admin = update.needs_admin(root)
print("root", root, "admin", admin, flush=True)
new = update.prepare(release)
update.start_swap(new, root, release.version, admin=admin)
print("helper ready", update.wait_for(update.READY.exists, 60.0), flush=True)
"""
SLEEPER = "import time\ntime.sleep(900)\n"


def unpack(archive: Path, folder: Path) -> Path:
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive) as tar:
            tar.extractall(folder, filter="tar")
    else:
        with zipfile.ZipFile(archive) as z:
            z.extractall(folder)
    return folder / "pokeldn"


def repack(app: Path, dest: Path) -> None:
    if dest.name.endswith(".tar.gz"):
        with tarfile.open(dest, "w:gz") as tar:
            tar.add(app, arcname="pokeldn")
    else:
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for path in sorted(app.rglob("*")):
                z.write(path, Path("pokeldn") / path.relative_to(app))


def serve(folder: Path) -> str:
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(folder), **k)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


def stop_all(target: Path) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/IM", "pokeldn.exe"], capture_output=True)
    else:
        subprocess.run(["pkill", "-f", str(target)], capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("archive", type=Path)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--admin", action="store_true")
    parser.add_argument("--busy", action="store_true")
    args = parser.parse_args()

    scratch = Path(tempfile.mkdtemp(prefix="pokeldn-update-check-"))
    source = unpack(args.archive.resolve(), scratch / "source")
    target = args.folder.resolve() / "pokeldn"
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target, symlinks=True)
    (source / MARKER).write_text("99.0.0")
    files = scratch / "serve"
    files.mkdir()
    repack(source, files / args.archive.name)
    digest = hashlib.sha256((files / args.archive.name).read_bytes()).hexdigest()
    (files / "SHA256SUMS").write_text(f"{digest}  {args.archive.name}\n")
    base = serve(files)
    (files / "latest").write_text(json.dumps({
        "tag_name": "v99.0.0", "html_url": base + "/page", "draft": False, "prerelease": False,
        "assets": [{"name": name, "browser_download_url": f"{base}/{name}"}
                   for name in (args.archive.name, "SHA256SUMS")]}))
    (scratch / "driver.py").write_text(DRIVER)
    (scratch / "sleeper.py").write_text(SLEEPER)

    env = dict(os.environ, POKELDN_UPDATE_URL=base + "/latest")
    if args.admin:
        env["POKELDN_UPDATE_ADMIN"] = "1"
    exe = update.executable_in(target)
    work, outcome = DATA / "update", DATA / "update" / "outcome.json"
    shutil.rmtree(work, ignore_errors=True)
    print(f"installed {target}, data {DATA}, serving {base}", flush=True)
    busy = subprocess.Popen([str(exe), "--run", str(scratch / "sleeper.py")], env=env) if args.busy else None
    started = time.monotonic()
    driver = subprocess.run([str(exe), "--run", str(scratch / "driver.py")], env=env, cwd=str(target),
                            capture_output=True, text=True, timeout=300)
    print(driver.stdout, driver.stderr, f"driver exit {driver.returncode}", sep="\n", flush=True)

    def done() -> bool:
        # work/new goes only when the new app has read the outcome (update.finish).
        return (target / MARKER).is_file() and not outcome.exists() and not (work / "new").exists()
    ok = driver.returncode == 0 and update.wait_for(done, 240.0)
    elapsed = time.monotonic() - started
    left = sorted(p.name for p in target.parent.iterdir() if p.name.startswith(".pokeldn"))
    print(f"marker {(target / MARKER).is_file()}, outcome left {outcome.exists()}, "
          f"unpacked copy left {(work / 'new').exists()}, old copies {left}, "
          f"{elapsed:.1f} s", flush=True)
    if busy:
        print(f"busy process ended: {busy.poll() is not None}", flush=True)
    for log in (work / "helper.log",):
        if log.exists():
            print(f"--- {log}\n{log.read_text(errors='replace')}", flush=True)
    if (work / "new").exists():
        # What keeps the unpacked copy: its files and, on Windows, the processes running from it.
        remaining = [p for p in (work / "new").rglob("*") if p.is_file()]
        print(f"unpacked copy: {len(remaining)} files left, e.g. {[str(p) for p in remaining[:5]]}", flush=True)
        for pid in update.running_from(work / "new"):
            image = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                   capture_output=True, text=True).stdout.strip()
            print(f"running from it: {image}", flush=True)
        if sys.platform == "win32":
            listing = subprocess.run(["tasklist", "/V", "/FO", "CSV"], capture_output=True, text=True).stdout
            print("\n".join(line for line in listing.splitlines() if "pokeldn" in line.lower()
                            or "flet" in line.lower()), flush=True)
    ok = ok and not left and (busy is None or busy.poll() is not None)
    stop_all(target)
    print("PASS" if ok else "FAIL", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
