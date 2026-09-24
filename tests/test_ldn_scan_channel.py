"""The scan reports a console on the channel that carried most of its advertisements (docs/ldn.md,
Channels): an ESP32 beside a Sword host heard it twice on channel 1 and about 30 times on 6."""
import os
import sys
from types import SimpleNamespace

import trio

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "vendor", "LDN"))
import ldn  # noqa: E402


def run_scan(heard):
    """`heard` maps a channel to the (address, tag) advertisements received while tuned to it."""
    scanner = ldn.Scanner.__new__(ldn.Scanner)
    tuned = {"channel": None}
    inbox_send, inbox = trio.open_memory_channel(100)

    async def set_channel(channel):
        tuned["channel"] = channel
        for address, tag in heard.get(channel, []):
            inbox_send.send_nowait(SimpleNamespace(address=address, channel=channel, tag=tag))

    async def receive():
        return await inbox.receive()

    scanner._monitor = SimpleNamespace(set_channel=set_channel)
    scanner.receive = receive
    return trio.run(scanner.scan, [1, 6, 11], 0.01)


def test_the_busiest_channel_wins_over_the_first_heard():
    heard = {1: [("A", "a1")] * 2, 6: [("A", "a6")] * 30, 11: [("A", "a11")] * 2}
    (net,) = run_scan(heard)
    assert net.channel == 6


def test_two_consoles_keep_their_order_and_channels():
    heard = {1: [("A", "a1")] * 5 + [("B", "b1")], 6: [("B", "b6")] * 4, 11: [("A", "a11")]}
    nets = run_scan(heard)
    assert [(n.address, n.channel) for n in nets] == [("A", 1), ("B", 6)]


def test_a_tie_keeps_the_first_channel():
    heard = {1: [("A", "a1")] * 3, 6: [("A", "a6")] * 3}
    (net,) = run_scan(heard)
    assert net.channel == 1
