"""The ESP32 radio's host side: its framing, and the unchanged LDN library running on it, host and
station, across two simulated boards."""

import contextlib
import contextvars
import os
import struct

import pytest
import trio

import ldn
from ldn import wlan

from pokeldn.ldn import esp32, esp32_sim, esp32_wlan


def test_cobs_round_trip():
    for n in (0, 1, 253, 254, 255, 256, 509, 1600):
        for data in (bytes(n), os.urandom(n), b"\x01" * n):
            encoded = esp32.cobs_encode(data)
            assert 0 not in encoded
            assert esp32.cobs_decode(encoded) == data


def test_reader_resynchronises_after_boot_text():
    frame = esp32.encode_frame(esp32.MSG_RX_ETH, b"\x00abc\x00")
    reader = esp32.FrameReader()
    corrupt = bytearray(frame)
    corrupt[2] ^= 0x40
    frames = list(reader.feed(b"ets Jun  8 2016 rst:0x1\r\n\x00" + bytes(corrupt) + frame))
    assert frames == [(esp32.MSG_RX_ETH, b"\x00abc\x00")]
    assert reader.rejected == 2


def test_radio_commands_against_the_simulated_board():
    board = esp32_sim.SimulatedBoard(esp32_sim.Air())
    radio = esp32.Radio(board.host_stream())
    try:
        info = radio.hello()
        assert info.version == esp32.PROTOCOL_VERSION and info.sta_mac == board.sta_mac
        radio.set_channel(11)
        assert board.channel == 11
        with pytest.raises(esp32.RadioError):
            radio.kick(b"\x02" * 6)
    finally:
        radio.close()


KEYS = {name: os.urandom(16) for name in (
    "aes_kek_generation_source", "aes_key_generation_source", "master_key_00", "master_key_12")}

_radio = contextvars.ContextVar("radio")


@contextlib.contextmanager
def _two_boards():
    air = esp32_sim.Air()
    host_board, station_board = esp32_sim.SimulatedBoard(air), esp32_sim.SimulatedBoard(air)
    radios = esp32.Radio(host_board.host_stream()), esp32.Radio(station_board.host_stream())
    ports = {}

    @contextlib.asynccontextmanager
    async def port_factory(name, address):
        port = esp32_wlan.MemoryPort(name, address)
        ports[name] = port
        yield port

    @contextlib.asynccontextmanager
    async def factory():
        esp = esp32_wlan.EspFactory(_radio.get(), port_factory=port_factory, join_timeout=5)
        try:
            yield esp
        finally:
            esp.router.close()

    wlan.set_factory(factory)
    try:
        yield radios, ports, host_board
    finally:
        wlan.set_factory(None)
        for radio in radios:
            radio.close()


def _udp_frame(target: bytes, source: bytes, payload: bytes) -> bytes:
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 28 + len(payload), 0, 0, 64, 17, 0,
                     bytes([169, 254, 1, 2]), bytes([169, 254, 1, 1]))
    return target + source + b"\x08\x00" + ip + struct.pack(">HHHH", 12345, 12345, 8 + len(payload), 0) + payload


def test_ldn_host_and_station_run_on_simulated_boards():
    async def main():
        with _two_boards() as ((host_radio, station_radio), ports, host_board):
            host_up = trio.Event()
            joined = []
            received = []

            async def host():
                _radio.set(host_radio)
                param = ldn.CreateNetworkParam(
                    keys=KEYS, channel=6, local_communication_id=0x0100ABCD00000000,
                    name=b"PkCamp", app_version=1, application_data=b"esp32 test")
                async with ldn.create_network(param) as network:
                    host_up.set()
                    event = await network.next_event()
                    joined.append(event)
                    received.append(await ports["ldn-tap"].received())
                    await trio.sleep(0.3)

            async def station():
                _radio.set(station_radio)
                await host_up.wait()
                networks = await ldn.scan(KEYS, channels=[6], dwell_time=0.5)
                assert len(networks) == 1
                network = networks[0]
                assert network.application_data == b"esp32 test"
                param = ldn.ConnectNetworkParam(network=network, keys=KEYS, name=b"Board", app_version=1)
                async with ldn.connect(param) as sta:
                    port = ports["ldn"]
                    assert port.addresses == [(sta.participant().ip_address, sta.broadcast_address())]
                    host_mac = esp32.mac_bytes(network.address)
                    port.transmit(_udp_frame(host_mac, esp32.mac_bytes(sta.participant().mac_address),
                                             b"pia"))
                    with trio.fail_after(5):
                        while not received:
                            await trio.sleep(0.05)

            with trio.fail_after(20):
                async with trio.open_nursery() as nursery:
                    nursery.start_soon(host)
                    nursery.start_soon(station)

            assert isinstance(joined[0], ldn.JoinEvent) and joined[0].participant.name == b"Board"
            assert received[0].endswith(b"pia")
            assert any(f[24:28] == b"\x7f\x00\x22\xaa" for f in host_board.sent_raw)

    trio.run(main)
