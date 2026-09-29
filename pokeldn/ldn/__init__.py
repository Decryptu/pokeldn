"""The wireless layer, independent of any game: LDN association, Pia, and the transport crypto.

See docs/ldn.md and docs/pia.md. A game's addresses and payload shapes belong in its own package."""

import os as _os

# POKELDN_RADIO=esp32:<serial port> puts every launcher's LDN calls on the ESP32 radio.
if _os.environ.get("POKELDN_RADIO", "").startswith("esp32:"):
    from pokeldn.ldn import esp32_wlan as _esp32_wlan
    _esp32_wlan.use_from_environment(log=print)


def show_done() -> bool:
    """Flash the ESP32 board's LED for a completed trade or delivery; False with no board."""
    if not _os.environ.get("POKELDN_RADIO", "").startswith("esp32:"):
        return False
    from pokeldn.ldn import esp32_wlan
    return esp32_wlan.show_done()
