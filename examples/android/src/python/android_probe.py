import importlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import sys
import time
import traceback


class AndroidStream:
    def __init__(self, usb):
        self.usb = usb

    def read(self, size):
        return bytes(self.usb.read(size))

    def write(self, data):
        return self.usb.write(data)

    def close(self):
        self.usb.close()


def run(usb, ui):
    log = ui.report
    import android_compat
    android_compat.install()
    log('PASS native interface name/index lookup')
    import pokeldn
    root = Path(pokeldn.__file__).resolve().parent.parent
    os.environ['POKELDN_DATA'] = str(Path(os.environ['HOME']) / 'pokeldn')
    os.environ['POKELDN_RADIO'] = 'esp32:android'
    log('Python ' + sys.version.replace('\n', ' '))
    failed = []
    modules = ('Crypto.Cipher.AES', 'trio', 'zstandard', 'serial', 'netlink', 'ldn',
               'pokeldn.ldn.esp32_wlan', 'pokeldn.ldn.userspace_ip',
               'pokeldn.frlg.link.host_app', 'pokeldn.swsh.host_trade',
               'pokeldn.bdsp.host', 'pokeldn.lgpe.local_host', 'pokeldn.pla.joiner',
               'pokeldn.sv.session', 'pokeldn.za.host', 'pokeldn.online.session')
    for name in modules:
        try:
            module = importlib.import_module(name)
            log('IMPORT OK ' + name + ' ' + str(getattr(module, '__version__', '')))
        except Exception as exc:
            failed.append(name)
            log('IMPORT FAILED ' + name + ': ' + repr(exc))
            traceback.print_exc()

    from Crypto.Cipher import AES
    key = bytes.fromhex('000102030405060708090a0b0c0d0e0f')
    plaintext = bytes.fromhex('00112233445566778899aabbccddeeff')
    assert AES.new(key, AES.MODE_ECB).encrypt(plaintext).hex() == '69c4e0d86a7b0430d8cdb78070b4c55a'
    log('PASS AES known-answer vector')

    import trio
    async def scheduler():
        left, right = trio.open_memory_channel(1)
        await left.send(b'android-trio')
        assert await right.receive() == b'android-trio'
        await trio.sleep(0.001)
    trio.run(scheduler)
    log('PASS Trio scheduler and channel')

    import android_test_esp32 as radio_tests
    radio_tests.test_userspace_stack_carries_udp_both_ways_on_simulated_boards()
    log('PASS simulated LDN host/station with bidirectional fragmented UDP')
    import android_test_host_end_to_end as trade_tests
    trade_tests.test_queued_trades_survive_loss_duplicate_reordering_and_close_cleanly(2)
    log('PASS two FRLG trades against scripted console with packet loss, duplicates and reordering')

    from pokeldn.ldn import esp32
    radio = esp32.Radio(AndroidStream(usb))
    try:
        times = []
        for attempt in range(10):
            started = time.monotonic()
            try:
                radio.info = esp32.Info.parse(radio.request(esp32.CMD_HELLO, b'', esp32.MSG_INFO, timeout=1))
                break
            except esp32.RadioError:
                if attempt == 9:
                    raise
        log('PYTHON HELLO ' + radio.info.text)
        assert radio.info.version == esp32.PROTOCOL_VERSION
        for _ in range(100):
            started = time.monotonic()
            info = esp32.Info.parse(radio.request(esp32.CMD_HELLO, b'', esp32.MSG_INFO))
            assert info == radio.info
            times.append((time.monotonic() - started) * 1000)
        log('PASS 100 Python HELLO replies: median %.2f ms, max %.2f ms' %
            (statistics.median(times), max(times)))
        result = radio.bench(2_000_000, timeout=30)
        log('BENCH_RESULT_JSON=' + json.dumps(result, sort_keys=True))
        log('BOARD_STATUS=' + radio.status())
        assert result['bytes'] == 1429 * 1400, result
        assert result['missing'] == 0 and result['rejected'] == 0, result
        assert result['board_seconds'] > 0, 'Missing completion marker'
        log('PASS 2 MB board-to-Python transfer: %.1f KB/s' % (result['rate'] / 1000))
        def counters():
            return dict(part.split('=', 1) for part in radio.status().split() if '=' in part)
        before = counters()
        assert before['mode'] == '0', 'Uplink test must run with the radio idle'
        frame = b'\xff' * 6 + bytes.fromhex('0200000000be') + b'\x08\x00' + bytes(range(200))
        started = time.monotonic()
        for index in range(5000):
            radio.send_ethernet(frame)
            if index % 200 == 199:
                assert radio.drain(10), 'Uplink queue did not drain'
        assert radio.drain(10)
        after = counters()
        received = sum(int(after[name]) - int(before[name]) for name in ('tx_eth', 'tx_eth_failed'))
        uplink = {'sent': 5000, 'board_counted': received, 'tx_dropped': radio.tx_dropped,
                  'flow_resyncs': radio.flow_resyncs, 'seconds': time.monotonic() - started,
                  'wire_bad_delta': int(after['wire_rx_bad']) - int(before['wire_rx_bad'])}
        log('UPLINK_RESULT_JSON=' + json.dumps(uplink, sort_keys=True))
        assert received == 5000 and radio.tx_dropped == 0 and radio.flow_resyncs == 0, uplink
        assert uplink['wire_bad_delta'] == 0, uplink
        log('PASS 5000 Python-to-board commands, no drops, resynchronisation or bad frames')
        log('PYTHON_PROBE_RESULT=' + json.dumps({'failed_imports': failed, 'hello_count': 100,
            'hello_median_ms': statistics.median(times), 'hello_max_ms': max(times), 'bench': result,
            'uplink': uplink}))
        if failed:
            log('USB/Python passed; remaining import failures: ' + ', '.join(failed))
        else:
            log('PASS Python runtime, game imports, radio transport and throughput.')
    finally:
        radio.close()
