"""The Board page's report: every section comes back, whatever fails, and a board's own answers land in it."""
import os
import sys
import threading

import pytest

from gui import board_report
from pokeldn.ldn import esp32_sim


def test_a_port_that_does_not_open_still_gives_a_whole_report():
    text = board_report.report("/dev/pokeldn-no-such-port", activity="[app] Checking the board")
    for heading in ("== This computer", "== USB serial ports", "== Drivers", "== Opening the port",
                    "== pokeldn firmware", "== ESP32 bootloader", "== Activity"):
        assert heading in text
    assert "open failed: " in text and "[app] Checking the board" in text


@pytest.mark.skipif(sys.platform == "win32", reason="a pseudo-terminal stands in for the board's port")
def test_a_simulated_boards_hello_and_status_land_in_the_report():
    master, slave = os.openpty()
    board = esp32_sim.SimulatedBoard(esp32_sim.Air())
    board.version = "1.8.0"
    stop = threading.Event()

    def host_to_board():
        while not stop.is_set():
            try:
                data = os.read(master, 4096)
            except OSError:
                return
            board._from_host(data)

    def board_to_host():
        while not stop.is_set():
            data = board.stream.read(4096)
            if data:
                os.write(master, data)

    threads = [threading.Thread(target=f, daemon=True) for f in (host_to_board, board_to_host)]
    for thread in threads:
        thread.start()
    try:
        text = board_report.firmware(os.ttyname(slave))
    finally:
        stop.set()
        os.close(slave)
        os.close(master)
    assert text[0] == "HELLO: pokeldn-radio simulated version=1.8.0"
    assert any(line.startswith("STATUS: mode=") for line in text)
