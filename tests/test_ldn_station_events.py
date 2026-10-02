"""The station's event loop against what a retail Sword sent after authenticating."""
import trio

import ldn
from ldn import wlan


class _Interface:
    def __init__(self, events):
        self._events = list(events)

    async def next_event(self):
        if self._events:
            return self._events.pop(0)
        await trio.sleep_forever()


def test_an_ldn_frame_after_authentication_is_not_taken_for_a_disconnect():
    # A retail Sword answered a resent authentication request with a 480-byte frame, then sent a
    # 224-byte 0x88B7 frame 43 ms later (bytes unrecorded); the loop raised on it, losing the seat.
    host = wlan.MACAddress(bytes.fromhex("48f1eb209b22"))
    late = bytes.fromhex("0022aa0101") + bytes(219)
    disconnect = ldn.DisconnectFrame()
    disconnect.reason = 3
    sta = ldn.STANetwork.__new__(ldn.STANetwork)
    sta._interface = _Interface([wlan.CustomFrameEvent(host, late),
                                 wlan.CustomFrameEvent(host, disconnect.encode())])
    sta._events = ldn.queue.create()

    async def main():
        async with trio.open_nursery() as nursery:
            nursery.start_soon(sta._process_events)
            with trio.fail_after(2):
                event = await sta._events.get()
            nursery.cancel_scope.cancel()
        return event

    event = trio.run(main)
    assert isinstance(event, ldn.DisconnectEvent) and event.reason == 3
