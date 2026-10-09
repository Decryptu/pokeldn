"""Portable shared launchers and release contents."""
import os
import subprocess
import sys
from pathlib import Path
import threading

from pokeldn.app import runner
from pokeldn.app.command import limit_error
from pokeldn.app.catalog import Field


def test_headless_entry_point_runs_without_gui_dependencies():
    result = subprocess.run(runner.command("--run", "bin/pla_join.py", "--help"),
                            capture_output=True, text=True, check=True)
    assert "--offer" in result.stdout
    assert "flet" not in result.stderr


def test_cli_uses_the_shared_catalog():
    result = subprocess.run([sys.executable, "-m", "pokeldn", "--list"], capture_output=True,
                            text=True, check=True)
    assert "swsh-host" in result.stdout and "za-join" in result.stdout


def test_source_ui_can_introspect_the_raid_launcher_without_bin_on_sys_path():
    """main.py loads entry points as modules; direct script execution adds bin implicitly."""
    root = Path(__file__).resolve().parents[1]
    code = (f"import sys; sys.path.insert(0, {str(root)!r}); "
            "from pokeldn.app.introspect import parser_of; "
            "parser_of('bin/sv_raid_host.py')")
    subprocess.run([sys.executable, "-I", "-c", code], check=True, capture_output=True, text=True)


def test_limits_apply_to_hexadecimal_values():
    field = Field("--set", "items", limits=(("held_item", 1607, "unsafe"),))
    assert limit_error(field, "held_item=0xffff") == "unsafe"
    assert not limit_error(field, "held_item=0x100")


def test_packer_uses_tracked_defaults_and_requires_firmware(monkeypatch, tmp_path):
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "scripts" / "pack_app.py"
    spec = importlib.util.spec_from_file_location("pack_app", path)
    pack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pack)
    files = pack.runtime_files()
    assert "config/host.toml" in files
    assert "LICENSE" in files and "vendor/LDN/LICENSE" in files
    assert {
        "bin/sv_raid_bootstrap_codec.py",
        "bin/sv_raid_host.py",
        "bin/sv_raid_start_gate.py",
        "bin/ESP32_RETAIL_RAID_GUEST.md",
        "docs/sv_raid.md",
        "docs/sv_raid_guest.md",
        "pokeldn/sv/raid_guest.py",
        "pokeldn/sv/data/raid_guest.json",
    } <= set(files)
    assert not any("scratchpad" in p or "host.local.toml" in p or "__pycache__" in p for p in files)
    assert not any(p.startswith("docs/research/") for p in files)
    monkeypatch.setattr(pack, "FIRMWARE", tmp_path / "absent.bin")
    monkeypatch.setattr(pack, "FIRMWARE_S3", tmp_path / "absent-s3.bin")
    monkeypatch.setattr(pack, "FIRMWARE_C3", tmp_path / "absent-c3.bin")
    monkeypatch.setattr(pack, "FIRMWARE_C6", tmp_path / "absent-c6.bin")
    import pytest
    with pytest.raises(SystemExit, match="Missing"):
        pack.main()
    # A release missing any target must fail before invoking the packer.
    images = (pack.FIRMWARE, pack.FIRMWARE_S3, pack.FIRMWARE_C3, pack.FIRMWARE_C6)
    for missing in images:
        for present in images:
            if present != missing:
                present.write_bytes(b"firmware")
        with pytest.raises(SystemExit, match=missing.name):
            pack.main()
        for present in images:
            present.unlink(missing_ok=True)
    # So must one without the Flet client that takes file drops.
    for present in images:
        present.write_bytes(b"firmware")
    monkeypatch.setattr(pack, "CLIENT", tmp_path / "client")
    with pytest.raises(SystemExit, match="Flet client"):
        pack.main()


def test_board_backend_does_not_require_unix_user_ids(monkeypatch):
    from pokeldn.host_support import needs_root
    from pokeldn.ldn import transport
    monkeypatch.delattr(os, "geteuid", raising=False)
    monkeypatch.setattr(transport, "board_radio", lambda: True)
    assert not needs_root()


def test_vendor_import_does_not_require_linux_fcntl():
    subprocess.run([sys.executable, "-c", "import sys; sys.modules['fcntl'] = None; import ldn.wlan"],
                   check=True, capture_output=True)


def test_managed_process_logs_utf8_and_stops_on_stdin_close(tmp_path):
    script = tmp_path / "session.py"
    script.write_text("import time\nprint('Pokémon prêt 🎮')\ntry:\n"
                      "    while True: time.sleep(0.02)\nexcept KeyboardInterrupt:\n"
                      "    print('stopped')\n", encoding="utf-8")
    lines, exits = [], []
    ready, done = threading.Event(), threading.Event()

    def line(value):
        lines.append(value)
        ready.set()

    def exit(code):
        exits.append(code)
        done.set()

    process = runner.Process(["--run", str(script)], str(tmp_path),
                             dict(os.environ, POKELDN_MANAGED_RUN="1", PYTHONIOENCODING="ascii"),
                             line, exit)
    try:
        assert ready.wait(5)
        assert lines == ["Pokémon prêt 🎮"]
    finally:
        process.stop()
        assert done.wait(5)
    assert exits == [0] and lines[-1] == "stopped"
