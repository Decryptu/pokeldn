"""Arceus channel opening payloads; framing is shared by Pia 6 games."""
from pokeldn.ldn.game_channel import *

# The two opens, off a reference pair that reached the trade screen.
HOST_OPEN_PAYLOAD = bytes.fromhex("00000000000000000100")
JOINER_OPEN_PAYLOAD = bytes.fromhex("b90101b902b902000001")
