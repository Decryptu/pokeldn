#!/usr/bin/env python3
"""Build a desktop bundle, including PKHeX and the required radio firmware."""
import os
import importlib.util
import platform
import plistlib
import shutil
import tempfile
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pokeldn import __version__
from gui.flet_client import CLIENT, MARKER, platform_key

FIRMWARE = ROOT / "gui" / "firmware" / "pokeldn-radio.bin"
FIRMWARE_S3 = ROOT / "gui" / "firmware" / "pokeldn-radio-s3.bin"
FIRMWARE_C3 = ROOT / "gui" / "firmware" / "pokeldn-radio-c3.bin"
FIRMWARE_C6 = ROOT / "gui" / "firmware" / "pokeldn-radio-c6.bin"
APP_ID = "io.github.decryptu.pokeldn"

# These files are part of the Tera Raid host feature, but may be untracked while
# developing or testing a local build.  The desktop packer otherwise stages only
# `git ls-files`, which makes the dynamically loaded helpers disappear from the
# packaged application.
RUNTIME_EXTRAS = (
    "bin/sv_raid_bootstrap_codec.py",
    "bin/sv_raid_host.py",
    "bin/sv_raid_reward_donor.bin",
    "bin/sv_raid_rewards.py",
    "bin/sv_raid_start_gate.py",
    "docs/sv_raid.md",
)


def runtime_id() -> str:
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    return {"darwin": f"osx-{arch}", "win32": f"win-{arch}"}.get(sys.platform, f"linux-{arch}")


def runtime_files() -> list[str]:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    folders = ("bin/", "pokeldn/", "vendor/LDN/ldn/", "docs/", "gui/assets/")
    files = {name for name in tracked if (name.startswith(folders) or name in
             ("config/host.toml", "gui/guide.md", "LICENSE", "vendor/LDN/LICENSE")) and (ROOT / name).is_file()}
    files.update(name for name in RUNTIME_EXTRAS if (ROOT / name).is_file())
    return sorted(files)


def platform_excludes():
    excluded = ["pytest", "PyInstaller", "flet_cli", "pip", "setuptools",
                "pycparser.lextab", "pycparser.yacctab"]
    if sys.platform != "win32":
        excluded += ["serial.tools.list_ports_windows", "serial.serialwin32", "serial.win32",
                     "flet_desktop.win_taskbar", "click._winconsole"]
    if sys.platform != "darwin":
        excluded.append("serial.tools.list_ports_osx")
    if not sys.platform.startswith("linux"):
        excluded.append("serial.tools.list_ports_linux")
    return excluded


def clear_cfg(exe: Path) -> None:
    """PyInstaller's Windows bootloader enables Control Flow Guard; Unicorn faults in a CFG process
    (unicorn-engine/unicorn#2281), python.exe has it off. Clear GUARD_CF in DllCharacteristics."""
    with exe.open("r+b") as f:
        f.seek(0x3C)
        pe = int.from_bytes(f.read(4), "little")
        f.seek(pe)
        assert f.read(4) == b"PE\0\0", exe
        field = pe + 24 + 70
        f.seek(field)
        flags = int.from_bytes(f.read(2), "little")
        f.seek(field)
        f.write((flags & ~0x4000).to_bytes(2, "little"))


def main() -> int:
    firmware = (FIRMWARE, FIRMWARE_S3, FIRMWARE_C3, FIRMWARE_C6)
    missing = [str(path) for path in firmware if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing firmware: {', '.join(missing)}. Build all four images "
                         "as described in docs/gui.md before packing.")
    client = CLIENT / platform_key()
    if not (client / MARKER).is_file():
        raise SystemExit("Missing the Flet client that takes file drops. Build it with "
                         "python scripts/build_client.py (needs Flutter) before packing.")
    if importlib.util.find_spec("PyInstaller") is None:
        raise SystemExit("Install desktop build dependencies: python -m pip install -r gui/requirements.txt")
    service = ROOT / "services" / "pkhex"
    subprocess.run(["dotnet", "publish", str(service), "-c", "Release", "-r", runtime_id(),
                    "-o", str(service / "dist"), "-warnaserror"], check=True)
    executable = service / "dist" / ("pokeldn-pkhex.exe" if sys.platform == "win32" else "pokeldn-pkhex")
    icon = {"darwin": "icon.icns", "win32": "icon.ico"}.get(sys.platform, "icon.png")
    with tempfile.TemporaryDirectory(prefix="pokeldn-pack-") as folder:
        stage = Path(folder)
        for name in runtime_files():
            dest = stage / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, dest)
        dependencies = stage / "dependencies"
        if sys.platform == "darwin":
            import serial
            shutil.copytree(Path(serial.__file__).parent, dependencies / "serial",
                            ignore=shutil.ignore_patterns("__pycache__"))
            ports = dependencies / "serial/tools/list_ports_osx.py"
            source = ports.read_text().replace("import ctypes\n", "import ctypes\nimport ctypes.util\n")
            for framework in ("IOKit", "CoreFoundation"):
                source = source.replace(f"'/System/Library/Frameworks/{framework}.framework/{framework}'",
                                        f"ctypes.util.find_library('{framework}')")
            ports.write_text(source)
        data = [(stage / name, name) for name in
                ("bin", "pokeldn", "vendor/LDN/ldn", "docs", "config", "gui/assets")]
        data += [(stage / "gui/guide.md", "gui"), (executable, "services/pkhex/dist")]
        data += [(stage / "LICENSE", "."), (stage / "vendor/LDN/LICENSE", "vendor/LDN")]
        data += [(path, "gui/firmware") for path in firmware]
        # PyInstaller's library patterns miss Linux's libunicorn.so.2; unicorn looks in its own lib/.
        import unicorn
        data += [(path, "unicorn/lib") for path in (Path(unicorn.__file__).parent / "lib").iterdir()
                 if path.suffix in (".dll", ".dylib") or ".so" in path.suffixes]
        args = [sys.executable, str(ROOT / "scripts/pack_flet.py"), "pack", str(ROOT / "gui" / "main.py"),
                "--name", "pokeldn", "-y",
                "--distpath", str(ROOT / "dist"), "--product-name", "pokeldn",
                "--product-version", __version__, "--file-version", f"{__version__}.0",
                "--bundle-id", APP_ID, "--add-data",
                *[f"{src}{os.pathsep}{dest}" for src, dest in data]]
        if sys.platform in ("darwin", "win32"):
            args += ["--icon", str(ROOT / "gui" / "assets" / icon)]
        scripts = sorted(p.stem for p in (stage / "bin").glob("*.py"))
        console = ["--console", "--hide-console=hide-early"] if sys.platform == "win32" else []
        for option in (f"--paths={dependencies}", f"--paths={ROOT}", f"--paths={ROOT / 'bin'}", f"--paths={ROOT / 'vendor' / 'LDN'}",
                       *console,
                       *[f"--hidden-import={s}" for s in scripts],
                       *[f"--exclude-module={m}" for m in platform_excludes()], "--collect-all=esptool", "--collect-submodules=unicorn",
                       "--collect-all=esp_pylib", "--collect-submodules=pokeldn",
                       "--collect-submodules=ldn"):
            args.append(f"--pyinstaller-build-args={option}")
        result = subprocess.run(args, cwd=stage, env=dict(os.environ, FLET_VIEW_PATH=str(client))).returncode
        expected = ROOT / "dist" / ({"darwin": "pokeldn.app", "win32": "pokeldn.exe"}.get(sys.platform, "pokeldn"))
        if result == 0 and not expected.exists():
            raise SystemExit("The packer produced no desktop application.")
        if result == 0 and sys.platform == "darwin":
            info_path = expected / "Contents/Info.plist"
            with info_path.open("rb") as source:
                info = plistlib.load(source)
            info.update(CFBundleShortVersionString=__version__, CFBundleVersion=__version__)
            with info_path.open("wb") as dest:
                plistlib.dump(info, dest)
            subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(expected)], check=True)
        if result == 0 and sys.platform == "win32":
            clear_cfg(expected)
        if result == 0 and sys.platform.startswith("linux"):
            (ROOT / "dist" / f"{APP_ID}.desktop").unlink(missing_ok=True)
        return result


if __name__ == "__main__":
    sys.exit(main())
