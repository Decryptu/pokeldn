"""A retail Switch title's own files, read in place from the user's dump with their prod.keys:
containers and NCAs (`container`), RomFS (`romfs`), NSO modules (`nso`). Trinity packs are read by
`tools/switch/trpfs.py`.

Belongs here: formats true of any title. Nothing here carries a game's addresses or imports a game
package; nothing writes a game file anywhere but a path its caller passes.
"""
