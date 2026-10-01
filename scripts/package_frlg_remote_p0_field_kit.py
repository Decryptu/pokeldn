#!/usr/bin/env python3
"""Build a source-pinned FRLG P0 field-test ZIP with a verified ESP32 radio image."""

import argparse
import hashlib
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parent.parent
FIRMWARE_ASSET = "pokeldn-radio.bin"
FIRMWARE_RELEASE = "v0.2.2"
FIRMWARE_RELEASE_URL = (
    "https://github.com/Decryptu/pokeldn/releases/download/v0.2.2/"
    "pokeldn-radio.bin")
TEMPLATE = ROOT / "tests" / "frlg_remote_p0_field_kit"


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()


def _release_digest(sums_path, asset):
    for line in sums_path.read_text(encoding="ascii").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == asset:
            return parts[0].lower()
    raise ValueError(f"official SHA256SUMS has no entry for {asset}")


def _archive_source(destination):
    payload = subprocess.check_output(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT)
    with tarfile.open(fileobj=BytesIO(payload), mode="r:") as source:
        source.extractall(destination, filter="data")


def _write_manifest(package_root):
    lines = []
    for path in sorted(p for p in package_root.rglob("*") if p.is_file()):
        if path.name == "MANIFEST.sha256":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(package_root).as_posix()}")
    (package_root / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="ascii")


def _write_zip(package_root, output):
    prefix = "frlg-p0-field-kit"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for path in sorted(p for p in package_root.rglob("*") if p.is_file()):
            relative = path.relative_to(package_root).as_posix()
            info = zipfile.ZipInfo(f"{prefix}/{relative}", date_time=(2026, 10, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED,
                             compresslevel=9)


def build(firmware_dir, output):
    tracked_changes = subprocess.run(
        ["git", "diff-index", "--quiet", "HEAD", "--"], cwd=ROOT).returncode
    if tracked_changes:
        raise ValueError("commit tracked source changes before creating the field-test package")
    commit = _git("rev-parse", "HEAD")
    firmware_dir = Path(firmware_dir).resolve()
    firmware = firmware_dir / FIRMWARE_ASSET
    release_sums = firmware_dir / "SHA256SUMS"
    if not firmware.is_file() or not release_sums.is_file():
        raise ValueError("firmware directory must contain pokeldn-radio.bin and SHA256SUMS")
    expected = _release_digest(release_sums, FIRMWARE_ASSET)
    actual = hashlib.sha256(firmware.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"{FIRMWARE_ASSET} does not match the release SHA-256")

    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="frlg-p0-field-kit-") as temp:
        workspace = Path(temp)
        package = workspace / "package"
        package.mkdir()
        (package / "source").mkdir()
        _archive_source(package / "source")
        for path in TEMPLATE.iterdir():
            if path.is_file():
                shutil.copy2(path, package / path.name)
        firmware_out = package / "firmware"
        firmware_out.mkdir()
        shutil.copy2(firmware, firmware_out / FIRMWARE_ASSET)
        (firmware_out / "SHA256SUMS").write_text(
            f"{expected}  {FIRMWARE_ASSET}\n", encoding="ascii")
        build_info = (
            f"PokeLDN source commit: {commit}\n"
            f"Source commit date: {_git('show', '-s', '--format=%cI', 'HEAD')}\n"
            f"Radio firmware release: {FIRMWARE_RELEASE}\n"
            f"Radio firmware URL: {FIRMWARE_RELEASE_URL}\n"
            "Supported radio: classic ESP32 only (not ESP32-C3, S3, or C6).\n"
            f"Radio firmware SHA-256: {expected}\n"
        )
        (package / "BUILD_INFO.txt").write_text(build_info, encoding="utf-8")
        _write_manifest(package)
        _write_zip(package, output)

    with zipfile.ZipFile(output) as archive:
        damaged = archive.testzip()
        if damaged:
            output.unlink(missing_ok=True)
            raise ValueError(f"ZIP integrity check failed for {damaged}")
    return output, hashlib.sha256(output.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware-dir", required=True,
                        help="directory containing the official radio binary and SHA256SUMS")
    parser.add_argument("--output", default=None,
                        help="output ZIP; defaults to dist/frlg-p0-field-kit-<commit>.zip")
    args = parser.parse_args(argv)
    commit = _git("rev-parse", "--short", "HEAD")
    output = args.output or ROOT / "dist" / f"frlg-p0-field-kit-{commit}.zip"
    try:
        path, digest = build(args.firmware_dir, output)
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        parser.error(str(exc))
    print(f"Created: {path}")
    print(f"SHA-256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
