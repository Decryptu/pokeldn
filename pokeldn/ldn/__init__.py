"""The wireless layer, GAME-INDEPENDENT: LDN association, Pia, and the transport crypto.

Layers, bottom-up: UDP :12345 (`transport`) -> zstd + AES-GCM (`crypto`) -> Pia connection
(`pia_connect`, Pia 6.32+; `pia6`, Pia 6.16-6.30; `pia5`, Pia 5.27-5.45) -> Pia message + a
reliable sliding window (`reliable` for 6.32, `reliable5` for 5.29-5.43 - different header shapes,
do not confuse them).
`sead` is Nintendo's own RNG, which Pia's LDN session key is built on, and `local_protocol` is
Pia protocol 36 - the session bookkeeping a Union Room runs on, once its payloads decrypt.
Above it a 5.x station joins a mesh through `station_protocol` (0x14) and `mesh_protocol` (0x18)
and is then timed by `rtt_protocol` (0x58); a mesh message is acked on the STATION protocol, which
is why the two are not separable.
`host_pia` is the leader-side peer controller, `beacon`/`host_beacon` the advertisement a
console discovers us by, and `joyspot_discovery`/`joyspot_probe` the discovery-only paths.

Read `docs/ldn.md` and `docs/pia.md` before changing anything here. Do NOT put a game's
addresses or a game's payload shapes in this package - they go in that game's own.
"""

import os as _os

# POKELDN_RADIO=esp32:<serial port> puts every launcher's LDN calls on the ESP32 radio.
if _os.environ.get("POKELDN_RADIO", "").startswith("esp32:"):
    from pokeldn.ldn import esp32_wlan as _esp32_wlan
    _esp32_wlan.use_from_environment(log=print)
