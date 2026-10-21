"""Builds the app's two native helpers for Android arm64 into jniLibs, where Android installs them as
files: PKHeX (services/pkhex, compiled ahead of time for linux-bionic-arm64, run as an executable) and
Unicorn with its ARM engines only (the library scripts/build_unicorn.py builds for the desktop app).
Needs the .NET 10 SDK, CMake and the Android NDK."""
import os
from pathlib import Path
import shutil
import subprocess

from build import android_home

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sdk = Path(android_home())
ndk = Path(os.environ.get('ANDROID_NDK_HOME') or max((sdk / 'ndk').iterdir()))
toolchain = next((ndk / 'toolchains/llvm/prebuilt').iterdir())
libs = HERE / 'jniLibs' / 'arm64-v8a'
libs.mkdir(parents=True, exist_ok=True)

out = HERE / 'build' / 'pkhex'
subprocess.run(['dotnet', 'publish', str(ROOT / 'services/pkhex/pkhex.csproj'), '-c', 'Release',
                '-r', 'linux-bionic-arm64', '-o', str(out),
                '-p:PublishAot=true', '-p:PublishSingleFile=false', '-p:EnableCompressionInSingleFile=false',
                '-p:DisableUnsupportedError=true', '-p:PublishAotUsingRuntimePack=true',
                f'-p:CppCompilerAndLinker={toolchain}/bin/clang', f'-p:SysRoot={toolchain}/sysroot',
                f'-p:ObjCopyName={toolchain}/bin/llvm-objcopy', '-p:LinkerFlavor=lld'], check=True)
shutil.copy2(out / 'pokeldn-pkhex', libs / 'libpokeldn_pkhex.so')

# The desktop's Unicorn source (scripts/build_unicorn.py downloads it); its Python package is staged.
import unicorn
version = __import__('importlib.metadata').metadata.version('unicorn')
source = ROOT / 'gui' / 'unicorn' / f'unicorn-{version}'
if not (source / 'src' / 'CMakeLists.txt').is_file():
    raise SystemExit('Run scripts/build_unicorn.py first: it fetches the Unicorn source.')
build = HERE / 'build' / 'unicorn'
subprocess.run(['cmake', '-S', str(source / 'src'), '-B', str(build), '-DCMAKE_BUILD_TYPE=Release',
                f'-DCMAKE_TOOLCHAIN_FILE={ndk}/build/cmake/android.toolchain.cmake', '-DANDROID_ABI=arm64-v8a',
                '-DANDROID_PLATFORM=24', '-DUNICORN_BUILD_TESTS=off', '-DUNICORN_ARCH=arm;aarch64'], check=True)
subprocess.run(['cmake', '--build', str(build), '--parallel'], check=True)
subprocess.run([f'{toolchain}/bin/llvm-strip', '-o', str(libs / 'libunicorn.so'), str(build / 'libunicorn.so')], check=True)
print('Android helpers:', *sorted(p.name for p in libs.iterdir()))
