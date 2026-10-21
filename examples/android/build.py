"""Builds the Android app: the local wheels, the native helpers (build_native.py, once), the staged
sources (stage.py), then the APK. Run with the repository's .venv Python from the repository root:

    ./.venv/bin/python examples/android/build.py [--release] [--install DEVICE]
    .venv\\Scripts\\python.exe examples\\android\\build.py         (Windows)
"""
import argparse
import glob
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
WHEELS = HERE / 'wheels'
# Pure-Python wheels the Android build installs from files: sdists it cannot build, and msgpack
# without its C extension (build.gradle).
LOCAL = (('python-netlink==0.0.15', {}), ('esptool==5.4.0', {}), ('esp-pylib==1.1.5', {}),
         ('intelhex==2.3.0', {}), ('reedsolo==1.7.0', {}),
         ('msgpack==1.2.3', {'MSGPACK_PUREPYTHON': '1'}))


def android_home() -> str:
    """ANDROID_HOME, else ANDROID_SDK_ROOT, else where Android Studio puts the SDK on this system."""
    found = os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT')
    if found:
        return found
    if sys.platform == 'win32':
        return str(Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'Android/Sdk')
    return str(Path.home() / ('Library/Android/sdk' if sys.platform == 'darwin' else 'Android/Sdk'))


def gradle() -> str:
    """AGP 8.13 needs Gradle 8.13 to 9.5: GRADLE, else the newest 9.5 or older wrapper download, else PATH."""
    if os.environ.get('GRADLE'):
        return os.environ['GRADLE']
    script = 'gradle.bat' if sys.platform == 'win32' else 'gradle'
    found = sorted(glob.glob(str(Path.home() / '.gradle/wrapper/dists/gradle-*-bin/*/gradle-*/bin' / script)))
    def version(path):
        return tuple(int(n) for n in Path(path).parents[1].name.removeprefix('gradle-').split('.') if n.isdigit())
    usable = sorted((g for g in found if (8, 13) <= version(g) < (9, 6)), key=version)
    return usable[-1] if usable else shutil.which('gradle') or 'gradle'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--release', action='store_true', help='assembleRelease instead of assembleDebug')
    parser.add_argument('--native', action='store_true', help='rebuild PKHeX and Unicorn even when present')
    parser.add_argument('--install', metavar='DEVICE', help='adb install the APK on this device')
    args = parser.parse_args()
    env = dict(os.environ)
    env['ANDROID_HOME'] = android_home()
    WHEELS.mkdir(exist_ok=True)
    for spec, extra in LOCAL:
        name = spec.split('==')[0].replace('-', '_')
        if not list(WHEELS.glob(f'{name}-*.whl')):
            subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-binary', ':all:',
                            '-w', str(WHEELS), spec], check=True, env={**env, **extra})
    libs = HERE / 'jniLibs' / 'arm64-v8a'
    if args.native or not all((libs / n).is_file() for n in ('libpokeldn_pkhex.so', 'libunicorn.so')):
        subprocess.run([sys.executable, str(HERE / 'build_native.py')], check=True, env=env)
    subprocess.run([sys.executable, str(HERE / 'stage.py')], check=True, env=env)
    env.setdefault('POKELDN_ANDROID_BUILD_PYTHON', sys.executable)
    task = 'assembleRelease' if args.release else 'assembleDebug'
    subprocess.run([gradle(), '-p', str(HERE), '--no-daemon', '--console=plain', task], check=True, env=env)
    kind = 'release' if args.release else 'debug'
    apk = HERE / 'build' / 'outputs' / 'apk' / kind / f'pokeldn-{kind}.apk'
    print('APK:', apk)
    if args.install:
        subprocess.run(['adb', '-s', args.install, 'install', '-r', str(apk)], check=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
