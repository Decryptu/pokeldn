#!/usr/bin/env python3
"""Check a frozen desktop app without keys or a connected board."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def check() -> None:
    from pokeldn import __version__
    from pokeldn import gifts, pokemon
    from pokeldn.app import paths, runner
    import gui.app
    import gui.views.games
    import gui.views.pokemon
    from serial.tools import list_ports

    assert getattr(sys, "frozen", False)
    root = Path(sys._MEIPASS)
    assert Path(pokemon.HERE) == root / "services/pkhex"
    assert (root / "gui/firmware/pokeldn-radio.bin").is_file()
    assert (root / "gui/firmware/pokeldn-radio-s3.bin").is_file()
    assert (root / "gui/firmware/pokeldn-radio-c3.bin").is_file()
    assert (root / "gui/firmware/pokeldn-radio-c6.bin").is_file()
    assert not (root / "config/host.local.toml").exists()
    assert not (root / "scratchpad").exists()
    assert (root / "LICENSE").is_file()
    assert (root / "vendor/LDN/LICENSE").is_file()
    from pokeldn.frlg.rom import custom_code
    # mov r0, #1; bx lr: Check offline runs it under the bundled Unicorn.
    assert custom_code.check(bytes.fromhex("0100a0e31eff2fe1")).frames == 1
    if sys.platform.startswith("linux"):
        import flet_desktop
        assert str(root) not in os.environ.get("LD_LIBRARY_PATH", ""), os.environ["LD_LIBRARY_PATH"]
        assert (Path(flet_desktop.get_package_bin_dir()) / flet_desktop.get_artifact_filename()).is_file()
    if sys.platform == "darwin":
        import plistlib
        import tarfile
        with tempfile.TemporaryDirectory(prefix="pokeldn-view-check-") as folder:
            with tarfile.open(root / "flet_desktop/app/flet-macos.tar.gz") as archive:
                archive.extractall(folder, filter="data")
            bundle, = Path(folder).glob("*.app")
            result = subprocess.run(["codesign", "--display", "--entitlements", "-", "--xml", str(bundle)],
                                    capture_output=True, check=True)
            entitlements = plistlib.loads(result.stdout) if result.stdout else {}
            assert entitlements.get("com.apple.security.files.user-selected.read-write"), entitlements
            subprocess.run(["codesign", "--verify", "--deep", "--strict", str(bundle)],
                           capture_output=True, check=True)
    trainer = {"ot": "POKELDN", "tid": 12345, "sid": 54321, "language": 2, "gender": 0}
    with tempfile.TemporaryDirectory(prefix="pokeldn-check-") as folder:
        pokemon.POKEMON = Path(folder)
        for game in pokemon.EXTENSIONS:
            result = pokemon.SERVICE.make(game, 25, trainer)
            assert result["legal"] and pokemon.SERVICE.check(game, result["file"])["legal"]
        for game, script, options in (
                ("frlg", "bin/frlg_mg_host.py", ("--gift", "celebi")),
                ("frlg-code", "bin/frlg_mg_host.py", ("--buffer-script", "save-dump", "--dump-size", "64")),
                ("swsh", "bin/swsh_gift_host.py", ("--species", "25"))):
            source, copy = Path(folder) / f"{game}.pokegift", Path(folder) / f"{game}-copy.pokegift"
            for args in ((*options, "--export-gift", str(source)),
                         ("--gift-file", str(source), "--export-gift", str(copy))):
                subprocess.run(runner.command("--run", script, *args),
                               capture_output=True, text=True, timeout=30, check=True)
            assert source.read_bytes() == copy.read_bytes()
            assert gifts.load(copy, game="frlg" if game == "frlg-code" else game).variants
        print("FRLG gifts, console code and Sword/Shield gift files verified")
    list(list_ports.comports())
    scripts = sorted((Path(paths.ROOT) / "bin").glob("*.py"))
    for path in scripts:
        result = subprocess.run(runner.command("--run", str(path), "--help"),
                                capture_output=True, text=True, timeout=30, check=True)
        assert "usage:" in result.stdout and not result.stderr, (path.name, result.stdout, result.stderr)
    result = subprocess.run(runner.command("--module", "esptool", "version"),
                            capture_output=True, text=True, timeout=30, check=True)
    assert "esptool" in result.stdout and not result.stderr, (result.stdout, result.stderr)
    result = subprocess.run(runner.command("--module", "gui.board", "--help"),
                            capture_output=True, text=True, timeout=30, check=True)
    assert "--firmware" in result.stdout and not result.stderr, (result.stdout, result.stderr)
    print(f"{len(scripts)} launchers and seven Pokemon formats verified")
    print(f"pokeldn {__version__}")


if __name__ == "__main__":
    if len(sys.argv) == 2:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from pokeldn import __version__

        result = subprocess.run([sys.argv[1], "--run", str(Path(__file__).resolve())],
                                capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, (hex(result.returncode & 0xFFFFFFFF), result.stdout, result.stderr)
        assert "seven Pokemon formats verified" in result.stdout, (result.stdout, result.stderr)
        assert not result.stderr, result.stderr
        assert f"pokeldn {__version__}\n" in result.stdout, result.stdout
        if sys.platform == "darwin":
            import plistlib
            executable = Path(sys.argv[1]).resolve()
            bundle = next((p for p in executable.parents if p.suffix == ".app"),
                          executable.parent / "pokeldn.app")
            with (bundle / "Contents/Info.plist").open("rb") as source:
                info = plistlib.load(source)
            assert info["CFBundleShortVersionString"] == __version__, info
            assert info["CFBundleVersion"] == __version__, info
        print(result.stdout, end="")
    else:
        check()
