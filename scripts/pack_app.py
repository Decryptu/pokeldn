#!/usr/bin/env python3
"""Build the desktop app for this OS into dist/: the PKHeX service, then one PyInstaller bundle.

    ./.venv/bin/python scripts/pack_app.py

Needs the .NET 10 SDK and `pip install -r gui/requirements.txt`. gui/firmware/pokeldn-radio.bin,
if present, is bundled for the Board page (the release workflow builds it from firmware/esp32).
"""
import os
import platform
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def runtime_id() -> str:
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    return {"darwin": f"osx-{arch}", "win32": f"win-{arch}"}.get(sys.platform, f"linux-{arch}")


def main() -> int:
    subprocess.run(["dotnet", "publish", os.path.join(ROOT, "gui", "pkhex"), "-c", "Release",
                    "-r", runtime_id(), "-o", os.path.join(ROOT, "gui", "pkhex", "dist")], check=True)
    icon = {"darwin": "icon.icns", "win32": "icon.ico"}.get(sys.platform, "icon.png")
    data = ["bin", "pokeldn", "vendor/LDN/ldn", "docs", "config", "gui/assets", "gui/pkhex/dist"]
    # Either image is enough to bundle the folder: this fork's esp32s3 build ships without a
    # classic-ESP32 one when it's the only firmware built locally.
    if any(os.path.isfile(os.path.join(ROOT, "gui", "firmware", name))
           for name in ("pokeldn-radio.bin", "pokeldn-radio-s3.bin")):
        data.append("gui/firmware")
    args = [sys.executable, "-m", "flet_cli.cli", "pack", os.path.join(ROOT, "gui", "main.py"),
            "--name", "pokeldn", "--icon", os.path.join(ROOT, "gui", "assets", icon), "-y",
            "--distpath", os.path.join(ROOT, "dist"), "--product-name", "pokeldn", "--bundle-id", "io.github.decryptu.pokeldn",
            "--add-data", *[f"{os.path.join(ROOT, d)}{os.pathsep}{d}" for d in data],
            f"{os.path.join(ROOT, 'gui', 'guide.md')}{os.pathsep}gui"]
    # The entry points run from the bundle as scripts; naming them as hidden imports makes
    # PyInstaller collect every module they import.
    scripts = sorted(f[:-3] for f in os.listdir(os.path.join(ROOT, "bin")) if f.endswith(".py"))
    for option in (f"--paths={os.path.join(ROOT, 'bin')}", f"--paths={os.path.join(ROOT, 'vendor', 'LDN')}",
                   *[f"--hidden-import={s}" for s in scripts], "--collect-all=esptool", "--collect-all=esp_pylib",
                   "--collect-submodules=pokeldn", "--collect-submodules=ldn"):
        args.append(f"--pyinstaller-build-args={option}")
    # `python -m`, not the flet console script: the script's own folder (the venv's bin) would lead
    # sys.path, and pip's esptool.py wrapper there would shadow the esptool package.
    return subprocess.run(args, cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
