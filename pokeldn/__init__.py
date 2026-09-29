"""Speaking Nintendo Switch local wireless (LDN) to Pokemon games.

Layers: `ldn` (game-independent wireless), `gba` (the GBA adapter above Pia), one package per title.
Nothing in `ldn` imports a game package; imports are absolute so a layering mistake shows in the diff.
"""

import os

if not hasattr(os, "geteuid"):
    # Windows has no euid. Every bin/ entry point's root check reads `os.geteuid() != 0 and not
    # board_radio()`, so an ESP32/board run (which needs no root) must not crash on the attribute
    # before board_radio() is even checked. A Wi-Fi-card run still isn't privileged, and now fails
    # on its own, later, with its real error (no `iw`, no AF_PACKET, ...) instead of this one.
    os.geteuid = lambda: 0
