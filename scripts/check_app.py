#!/usr/bin/env python3
"""Check a frozen desktop app without keys or a connected board."""
import subprocess
import sys
import tempfile
from pathlib import Path


def check() -> None:
    from pokeldn import pokemon
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
    assert not (root / "config/host.local.toml").exists()
    assert not (root / "scratchpad").exists()
    trainer = {"ot": "PkCamp", "tid": 12345, "sid": 54321, "language": 2, "gender": 0}
    with tempfile.TemporaryDirectory(prefix="pokeldn-check-") as folder:
        pokemon.POKEMON = Path(folder)
        for game in pokemon.EXTENSIONS:
            result = pokemon.SERVICE.make(game, 25, trainer)
            assert result["legal"] and pokemon.SERVICE.check(game, result["file"])["legal"]
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


if __name__ == "__main__":
    if len(sys.argv) == 2:
        result = subprocess.run([sys.argv[1], "--run", str(Path(__file__).resolve())],
                                capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert "seven Pokemon formats verified" in result.stdout, (result.stdout, result.stderr)
        assert not result.stderr, result.stderr
        print(result.stdout, end="")
    else:
        check()
