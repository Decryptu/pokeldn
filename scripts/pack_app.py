#!/usr/bin/env python3
"""Build a desktop bundle, including PKHeX and the required radio firmware."""
import argparse
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
UNICORN = ROOT / "gui" / "unicorn"
MARKER_UNICORN = "pokeldn-unicorn"


def runtime_id() -> str:
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    return {"darwin": f"osx-{arch}", "win32": f"win-{arch}"}.get(sys.platform, f"linux-{arch}")


def runtime_files() -> list[str]:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    folders = ("bin/", "pokeldn/", "vendor/LDN/ldn/", "docs/", "gui/assets/")
    return [name for name in tracked if (name.startswith(folders) or name in
            ("config/host.toml", "gui/guide.md", "LICENSE", "vendor/LDN/LICENSE")) and (ROOT / name).is_file()]


def platform_excludes():
    excluded = ["pytest", "_pytest", "PyInstaller", "flet_cli", "pip", "setuptools",
                "pycparser.lextab", "pycparser.yacctab",
                # Flet's web server, auth and raw-image extras; the desktop view uses none of them.
                "flet_web", "fastapi", "starlette", "uvicorn", "uvloop", "httptools", "watchfiles",
                "pydantic", "pydantic_core", "httpx", "httpcore", "oauthlib", "yaml", "PIL",
                # rich's syntax highlighting, Markdown and tracebacks (Pygments, markdown-it, pydoc): esptool
                # prints through rich and rich-click and reaches none of them. No code starts processes.
                "pygments", "rich.syntax", "rich.markdown", "rich.traceback", "rich.__main__",
                "multiprocessing", "_pydecimal"]
    if sys.platform != "win32":
        excluded += ["serial.tools.list_ports_windows", "serial.serialwin32", "serial.win32",
                     "flet_desktop.win_taskbar", "click._winconsole"]
    if sys.platform != "darwin":
        excluded.append("serial.tools.list_ports_osx")
    else:
        # East Asian codecs: macOS Python reads and writes UTF-8 whatever the locale.
        excluded += ["_multibytecodec", *(f"_codecs_{c}" for c in ("cn", "hk", "iso2022", "jp", "kr", "tw"))]
    if not sys.platform.startswith("linux"):
        excluded.append("serial.tools.list_ports_linux")
    return excluded


def strip_local_symbols(app: Path, keep: set[Path]) -> None:
    """Drops local symbols from the bundle's Mach-O libraries (1 to 2 MB); the exports stay. Never the
    executable or the PKHeX helper: both carry an archive after their Mach-O image."""
    for path in app.rglob("*"):
        if path.is_file() and not path.is_symlink() and path not in keep:
            with path.open("rb") as f:
                if f.read(4) not in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
                    continue
            subprocess.run(["strip", "-x", str(path)], check=True, capture_output=True)


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
    argparse.ArgumentParser(description=__doc__).parse_args()
    firmware = (FIRMWARE, FIRMWARE_S3, FIRMWARE_C3, FIRMWARE_C6)
    missing = [str(path) for path in firmware if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing firmware: {', '.join(missing)}. Build all four images "
                         "as described in docs/gui.md before packing.")
    client = CLIENT / platform_key()
    if not (client / MARKER).is_file():
        raise SystemExit("Missing the Flet client that takes file drops. Build it with "
                         "python scripts/build_client.py (needs Flutter) before packing.")
    if not (UNICORN / MARKER_UNICORN).is_file():
        raise SystemExit("Missing the ARM-only Unicorn. Build it with python scripts/build_unicorn.py "
                         "(needs CMake) before packing.")
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
        # scripts/build_unicorn.py's ARM-only library, not the wheel's; unicorn looks in its own lib/.
        data += [(path, "unicorn/lib") for path in (UNICORN / "lib").iterdir()]
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
        # A single file unpacks all of itself at every launch and every run (docs/gui.md). Flet's own
        # --onedir refuses macOS; this later PyInstaller flag wins over the --onefile Flet passes.
        onedir = ["--onedir"]
        for option in (f"--paths={dependencies}", f"--paths={ROOT}", f"--paths={ROOT / 'bin'}", f"--paths={ROOT / 'vendor' / 'LDN'}",
                       *console, *onedir,
                       *[f"--hidden-import={s}" for s in scripts],
                       *[f"--exclude-module={m}" for m in platform_excludes()], "--collect-all=esptool", "--collect-submodules=unicorn",
                       "--collect-all=esp_pylib", "--collect-submodules=pokeldn",
                       "--collect-submodules=ldn"):
            args.append(f"--pyinstaller-build-args={option}")
        result = subprocess.run(args, cwd=stage, env=dict(os.environ, FLET_VIEW_PATH=str(client))).returncode
        expected = ROOT / "dist" / (("pokeldn.app" if sys.platform == "darwin" else "pokeldn"))
        if result == 0 and not expected.exists():
            raise SystemExit("The packer produced no desktop application.")
        if result == 0 and sys.platform == "darwin":
            info_path = expected / "Contents/Info.plist"
            with info_path.open("rb") as source:
                info = plistlib.load(source)
            # The Flet viewer is the window; a one-folder Python process never checks in with the Dock and
            # bounces there forever (docs/gui.md). The single-file bootloader ran as background-only.
            info.update(CFBundleShortVersionString=__version__, CFBundleVersion=__version__, LSBackgroundOnly=True)
            with info_path.open("wb") as dest:
                plistlib.dump(info, dest)
            strip_local_symbols(expected, {expected / "Contents/MacOS/pokeldn",
                                           expected / "Contents/Frameworks/services/pkhex/dist" / executable.name})
            subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(expected)], check=True)
        if result == 0 and sys.platform == "win32":
            clear_cfg(expected / "pokeldn.exe")
        if result == 0 and sys.platform.startswith("linux"):
            (ROOT / "dist" / f"{APP_ID}.desktop").unlink(missing_ok=True)
        return result


if __name__ == "__main__":
    sys.exit(main())
