"""pokeldn.switch.cartridge's choices; reading a real package is tools/frlg/extract_cartridges.py's run."""
import pytest

from pokeldn.switch import cartridge


def test_a_bare_image_is_read_and_anything_else_is_named(tmp_path):
    (tmp_path / "game.GBA").write_bytes(b"cartridge")
    assert cartridge.read(tmp_path / "game.GBA") == b"cartridge"
    with pytest.raises(ValueError, match="neither a .gba"):
        cartridge.read(tmp_path / "game.txt")
    with pytest.raises(ValueError, match="needs prod.keys"):
        cartridge.read(tmp_path / "game.nsp")
