"""The GBA cartridge image inside a FireRed or LeafGreen title, read in place from its package, or a
bare `.gba` [docs/frlg_rom_map.md, The cartridge image]."""
import os

from pokeldn.switch.container import CtrSection, load_keys, program_nca
from pokeldn.switch.romfs import RomFs

PACKAGES = (".nsp", ".nsz", ".xci", ".xcz")


def _romfs_section(section):
    return section["fs_type"] == 0 and section["crypt"] == 3


def from_package(path, keys):
    """-> (RomFS file name, image) of the title in package `path`; `keys` is a load_keys dict."""
    container, offset, header, key = program_nca(str(path), keys, section=_romfs_section)
    try:
        section = next(s for s in header["sections"] if _romfs_section(s))
        romfs = RomFs(CtrSection(container, offset, section, key), section["data_offset"])
        name, data_offset, size = next(f for f in romfs.walk() if f[0].endswith(".gba"))
        return name.rsplit("/", 1)[-1], romfs.read_file(data_offset, size)
    finally:
        container.close()


def read(path, keys=None):
    """-> the cartridge image in `path`, a `.gba` or a package; a package needs the `prod.keys` path
    `keys`. ValueError names what is wrong with the file."""
    path = os.fspath(path)
    if path.lower().endswith(".gba"):
        with open(path, "rb") as handle:
            return handle.read()
    if not path.lower().endswith(PACKAGES):
        raise ValueError(f"{os.path.basename(path)} is neither a .gba nor a game package")
    if not keys:
        raise ValueError("reading a game package needs prod.keys")
    return from_package(path, load_keys(keys))[1]
