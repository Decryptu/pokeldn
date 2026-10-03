#!/usr/bin/env python3
"""Play a trade and a Mystery Gift on the board's screen. No radio traffic, no console.

    ./.venv/bin/python tools/ldn/esp32_screen.py --port PORT [--offer 25] [--receive 150] [--gift 151]

Opening the port resets the board. Sprites come from PokeAPI through the app's cache
(pokeldn.app.screen). docs/hardware_esp32.md, The screen.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.app.screen import sprite_bits  # noqa: E402
from pokeldn.ldn import esp32  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", required=True)
    ap.add_argument("--offer", type=int, default=25, help="national dex number")
    ap.add_argument("--receive", type=int, default=150)
    ap.add_argument("--gift", type=int, default=151)
    ap.add_argument("--names", default="Pikachu,Mewtwo,Mew", help="the three names shown")
    ap.add_argument("--title", default="Sw/Sh")
    args = ap.parse_args(argv)
    offer_name, receive_name, gift_name = args.names.split(",")
    radio = esp32.Radio.open_serial(args.port)

    def display(payload, what):
        print(what, flush=True)
        radio.request(esp32.CMD_DISPLAY, payload, esp32.MSG_RESULT)

    try:
        radio.hello()
        time.sleep(3)
        display(esp32.display_sprite_payload("ours", sprite_bits(args.offer) or []), f"offer #{args.offer}")
        display(esp32.display_show_payload("trade", 0, args.title, offer_name), "trade")
        time.sleep(6)
        display(esp32.display_sprite_payload("theirs", sprite_bits(args.receive) or []), f"receive #{args.receive}")
        display(esp32.display_show_payload("traded", 30, args.title, receive_name), "traded")
        time.sleep(8)       # the console's animation, cut short as a console that finished
        display(esp32.display_show_payload("arrived"), "arrived")
        time.sleep(8)
        display(esp32.display_sprite_payload("gift", sprite_bits(args.gift, 40) or []), f"gift #{args.gift}")
        display(esp32.display_show_payload("gift", 0, "Mystery Gift", f"{gift_name} from the event"), "gift")
        time.sleep(6)
        display(esp32.display_show_payload("gifted", 6, "", gift_name), "gifted")
        time.sleep(7)
    finally:
        radio.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
