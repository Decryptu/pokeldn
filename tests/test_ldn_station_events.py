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


class _APInterface:
    def __init__(self):
        self.neighbors = []

    async def set_authorized(self, address):
        pass

    async def add_neighbor(self, ip, mac):
        self.neighbors.append(ip)


def test_a_resent_authentication_request_keeps_one_seat():
    # A console whose authentication response is lost sends the request again; upstream kinnay/LDN
    # 0833167b8. Registering it twice gave it two seats and a second JoinEvent.
    console = wlan.MACAddress(bytes.fromhex("48f1eb209b22"))
    ap = ldn.APNetwork.__new__(ldn.APNetwork)
    ap._network = ldn.NetworkInfo(3)
    ap._network.participants = [ldn.ParticipantInfo() for _ in range(8)]
    ap._network_id = 7
    ap._interface = _APInterface()
    ap._events = ldn.queue.create()
    ap._peers = []
    ap._update_nonce = lambda: None

    async def main():
        for _ in range(2):
            await ap._register_participant(console, b"POKELDN", 1, 0)

    trio.run(main)
    seats = [p for p in ap._network.participants if p.connected]
    assert len(seats) == 1 and ap._network.num_participants == 1
    assert ap._peers == [console] and ap._interface.neighbors == ["169.254.7.1"]
