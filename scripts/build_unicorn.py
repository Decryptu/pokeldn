#!/usr/bin/env python3
"""Build Unicorn with only the ARM and ARM64 engines, for scripts/pack_app.py to bundle.

The wheel's library carries every CPU family (16 MB on macOS); the app runs ARM and ARM64 code only
(3 MB). This builds the installed Unicorn's own release from source with CMake into gui/unicorn/lib,
under the file names the installed package loads. docs/gui.md, Build a desktop app.
"""
import importlib.metadata
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "gui" / "unicorn"
LIB = OUT / "lib"
ARCHS = "arm;aarch64"
MARKER = "pokeldn-unicorn"


def main() -> int:
    if not shutil.which("cmake"):
        raise SystemExit("Install CMake first: https://cmake.org/download/")
    import unicorn
    version = importlib.metadata.version("unicorn")
    names = sorted(p.name for p in (Path(unicorn.__file__).parent / "lib").iterdir()
                   if p.suffix in (".dll", ".dylib") or ".so" in p.suffixes)
    source = OUT / f"unicorn-{version}"
    if not (source / "src" / "CMakeLists.txt").is_file():
        OUT.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, "-m", "pip", "download", f"unicorn=={version}", "--no-binary", ":all:",
                        "--no-deps", "-d", str(OUT)], check=True)
        with tarfile.open(OUT / f"unicorn-{version}.tar.gz") as archive:
            archive.extractall(OUT, filter="data")
    build = source / "build-pokeldn"
    shutil.rmtree(build, ignore_errors=True)
    subprocess.run(["cmake", "-S", str(source / "src"), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release",
                    "-DUNICORN_BUILD_TESTS=off", f"-DUNICORN_ARCH={ARCHS}"], check=True)
    subprocess.run(["cmake", "--build", str(build), "--config", "Release", "--parallel"], check=True)
    shutil.rmtree(LIB, ignore_errors=True)
    LIB.mkdir(parents=True)
    for name in names:
        built = [p for p in build.rglob(name) if p.is_file()]
        if not built:
            raise SystemExit(f"The Unicorn build made no {name}.")
        shutil.copyfile(built[0].resolve(), LIB / name)
    (OUT / MARKER).write_text(f"unicorn {version} {ARCHS}\n")
    print(f"Built {', '.join(names)} into {LIB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
