"""The wireless layer, independent of any game: LDN association, Pia, and the transport crypto.

See docs/ldn.md and docs/pia.md. A game's addresses and payload shapes belong in its own package."""

import os as _os

_done: dict[str, int] = {}


def show_done(kind: str = "trade") -> bool:
    """Prints `[done] trade N complete`, the line the app counts against its trade queue
    (pokeldn.app.received.DONE), and flashes the ESP32 board's LED; False with no board."""
    _done[kind] = _done.get(kind, 0) + 1
    print(f"[done] {kind} {_done[kind]} complete", flush=True)
    if not _os.environ.get("POKELDN_RADIO", "").startswith("esp32:"):
        return False
    from pokeldn.ldn import esp32_wlan
    return esp32_wlan.show_done()
