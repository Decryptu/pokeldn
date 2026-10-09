"""Speaking Nintendo Switch local wireless (LDN) to Pokemon games.

Layers: `ldn` (game-independent wireless), `gba` (the GBA adapter above Pia), one package per title.
Nothing in `ldn` imports a game package; imports are absolute so a layering mistake shows in the diff.
"""

__version__ = "0.18.2"
