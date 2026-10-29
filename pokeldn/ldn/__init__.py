"""The wireless layer, independent of any game: LDN association, Pia, and the transport crypto.

See docs/ldn.md and docs/pia.md. A game's addresses and payload shapes belong in its own package."""

import os as _os
import time as _time

_done: dict[str, int] = {}
_done_at: float | None = None
_radio_lost = ""


def radio_lost() -> str:
    """Why the radio left this process, or "": a run that ends in KeyboardInterrupt tells a lost
    board from the player's Stop by it (docs/plugins.md, The API)."""
    return _radio_lost


def show_done(kind: str = "trade") -> bool:
    """Prints `[done] trade N complete`, the line the app counts against its trade queue
    (pokeldn.app.received.DONE), and flashes the ESP32 board's LED; False with no board."""
    global _done_at
    _done[kind] = _done.get(kind, 0) + 1
    _done_at = _time.monotonic()
    print(f"[done] {kind} {_done[kind]} complete", flush=True)
    if not _os.environ.get("POKELDN_RADIO", "").startswith("esp32:"):
        return False
    from pokeldn.ldn import esp32_wlan
    return esp32_wlan.show_done()


LINK_PREFIX = "[link] "
_waiting = False


def show_link(state: str) -> None:
    """Prints `[link] STATE` for the app's run status (pokeldn.app.failure): `waiting` once, when the radio
    first hosts or scans for a console, then `joined` and `left` as one joins and leaves. Only a run the
    app started prints it."""
    global _waiting
    if _os.environ.get("POKELDN_MANAGED_RUN") != "1" or (state == "waiting" and _waiting):
        return
    _waiting = _waiting or state == "waiting"
    print(f"{LINK_PREFIX}{state}", flush=True)


def trades_done() -> int:
    """Trades this process completed, as show_done counted them."""
    return _done.get("trade", 0)


def hold_after_trade_over(seconds: float | None, queue_done: bool = True) -> bool:
    """True once `seconds` (--hold-after-trade) have passed since the last show_done and no queued
    offer is left; the launcher then leaves its seat or closes its session (docs/architecture.md)."""
    return (seconds is not None and queue_done and _done_at is not None
            and _time.monotonic() - _done_at >= seconds)


def left_after_trade(seated) -> bool:
    """A host's run is over once a trade has completed and no console is seated; a console that
    leaves before any trade may come back (docs/architecture.md, Ending a run)."""
    return trades_done() > 0 and not seated
