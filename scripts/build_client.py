#!/usr/bin/env python3
"""Build Flet's desktop client with gui/flet_drop, so files dragged from the desktop reach the app.

Flet's own client takes no file drops. This checks out Flet's source at the installed version, adds
the extension, and builds the client into gui/client/<platform>; gui/main.py runs it and
scripts/pack_app.py bundles it. Needs Flutter on PATH, the version `flet --version --json` names.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gui.drop import CLIENT, MARKER, platform_key  # noqa: E402

SOURCE = CLIENT / "flet"
EXTENSION = ROOT / "gui" / "flet_drop"


def flet_versions() -> tuple[str, str]:
    import flet_cli  # noqa: F401  (the version command lives there)
    out = subprocess.check_output([sys.executable, "-m", "flet_cli.cli", "--version", "--json"], text=True)
    found = json.loads(out)
    return found["flet"], found["flutter"]


def strip(path: Path, *blocks: str) -> None:
    """Drops the marked blocks Flet's own CI removes for its light client."""
    lines, out, skip = path.read_text().splitlines(keepends=True), [], None
    for line in lines:
        if skip is None and any(f"--{b}_START--" in line for b in blocks):
            skip = next(b for b in blocks if f"--{b}_START--" in line)
        if skip is None:
            out.append(line)
        elif f"--{skip}_END--" in line:
            skip = None
    path.write_text("".join(out))


MACOS_FLOOR = "12.0"   # Xcode 27 builds nothing older; Flet's client asks for 11.0


def raise_macos_floor(client: Path) -> None:
    podfile = client / "macos" / "Podfile"
    text = podfile.read_text().replace("platform :osx, '11.0'", f"platform :osx, '{MACOS_FLOOR}'")
    anchor = "    flutter_additional_macos_build_settings(target)\n"
    assert anchor in text, "Flet's client Podfile changed shape"
    podfile.write_text(text.replace(anchor, anchor + "    target.build_configurations.each { |c| "
                                    f"c.build_settings['MACOSX_DEPLOYMENT_TARGET'] = '{MACOS_FLOOR}' }}\n", 1))
    project = client / "macos" / "Runner.xcodeproj" / "project.pbxproj"
    project.write_text(project.read_text().replace("MACOSX_DEPLOYMENT_TARGET = 11.0;",
                                                   f"MACOSX_DEPLOYMENT_TARGET = {MACOS_FLOOR};"))


def patch(client: Path, light: bool) -> None:
    subprocess.run(["git", "checkout", "--", "pubspec.yaml", "lib/main.dart", "macos/Podfile",
                    "macos/Runner.xcodeproj/project.pbxproj"], cwd=client, check=True)
    if sys.platform == "darwin":
        raise_macos_floor(client)
    pubspec, main = client / "pubspec.yaml", client / "lib" / "main.dart"
    for path in (pubspec, main):
        if light:
            strip(path, "FAT_CLIENT")
    text = pubspec.read_text()
    anchor = "dependencies:\n  flutter:\n    sdk: flutter\n"
    assert anchor in text, "Flet's client pubspec changed shape"
    pubspec.write_text(text.replace(anchor, anchor + f"  flet_drop:\n    path: {EXTENSION.as_posix()}\n", 1))
    text = main.read_text()
    anchor = "List<FletExtension> extensions = [\n"
    assert anchor in text, "Flet's client main.dart changed shape"
    text = text.replace(anchor, anchor + "    flet_drop.Extension(),\n", 1)
    main.write_text("import 'package:flet_drop/flet_drop.dart' as flet_drop;\n" + text)


def main() -> int:
    if not shutil.which("flutter"):
        raise SystemExit("Install Flutter first: https://docs.flutter.dev/get-started/install")
    flet, flutter = flet_versions()
    have = subprocess.check_output(["flutter", "--version", "--machine"], text=True, shell=os.name == "nt")
    if json.loads(have)["frameworkVersion"] != flutter:
        print(f"Warning: Flet {flet} is built with Flutter {flutter}, this is "
              f"{json.loads(have)['frameworkVersion']}.", file=sys.stderr)
    tag = f"v{flet}"
    if not (SOURCE / ".git").is_dir():
        CLIENT.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", "--branch", tag,
                        "https://github.com/flet-dev/flet.git", str(SOURCE)], check=True)
    else:
        found = subprocess.check_output(["git", "describe", "--tags", "--exact-match"], cwd=SOURCE, text=True)
        if found.strip() != tag:
            subprocess.run(["git", "fetch", "--depth", "1", "origin", "tag", tag], cwd=SOURCE, check=True)
            subprocess.run(["git", "checkout", "-f", tag], cwd=SOURCE, check=True)
    client = SOURCE / "client"
    key = platform_key()
    patch(client, light=key == "linux")
    flutter_cmd = ["flutter", "build", key, "--release", f"--build-name={flet}"]
    subprocess.run(flutter_cmd, cwd=client, check=True, shell=os.name == "nt")
    out = CLIENT / key
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    if key == "macos":
        built = client / "build/macos/Build/Products/Release/Flet.app"
        subprocess.run(["ditto", str(built), str(out / "Flet.app")], check=True)
    elif key == "windows":
        built = client / "build/windows/x64/runner/Release"
        shutil.copytree(built, out / "flet")
        system = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32"
        for dll in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
            shutil.copy2(system / dll, out / "flet")
    else:
        arch = "arm64" if os.uname().machine in ("aarch64", "arm64") else "x64"
        shutil.copytree(client / f"build/linux/{arch}/release/bundle", out / "flet", symlinks=True)
    (out / MARKER).write_text(f"flet {flet}\n")
    print(f"Built {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
