"""CLI wiring for the trade-disabled FRLG remote probe."""

import importlib.util
from pathlib import Path

from pokeldn.frlg import config as configmod


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "frlg_remote_trade", ROOT / "bin" / "frlg_remote_trade.py")
frlg_remote_trade = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(frlg_remote_trade)


def test_p0_cli_uses_six_ldn_participants(monkeypatch):
    parser = frlg_remote_trade.build_parser(configmod.HostFileConfig())
    args = parser.parse_args(["host", "--listen", "127.0.0.1"])

    monkeypatch.setattr(frlg_remote_trade, "_room_key", lambda _args: b"k" * 32)
    _app_config, lan_config = frlg_remote_trade.build_remote_config(parser, args)
    assert lan_config.probe_only is True
    assert _app_config.role.max_participants == frlg_remote_trade.P0_MAX_PARTICIPANTS == 6
