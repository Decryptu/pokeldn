"""An `ldn.wlan` factory backed by the ESP32 radio, so `ldn.scan`, `ldn.connect` and
`ldn.create_network` run unchanged with the board in place of an nl80211 adapter.

The board hands over Ethernet frames. LDN's authentication frames (EtherType 0x88B7) become the
interface events the LDN library expects; everything else goes to an L2 port: a kernel TAP on
Linux, so sockets bound to the interface keep working, or a `MemoryPort` for tests and for a
host without TAP. `use()` installs the backend for every later `ldn` call in the process.
"""

import contextlib
import math
import os
import random
import struct

import trio

from ldn import wlan

from pokeldn.ldn import esp32

ETH_P_LDN = 0x88B7
BROADCAST = wlan.MACAddress("ff:ff:ff:ff:ff:ff")


def _random_mac() -> wlan.MACAddress:
    b = bytearray(random.randbytes(6))
    b[0] = (b[0] & 0xFC) | 0x02
    return wlan.MACAddress(bytes(b))


def _ethernet(target, source, protocol: int, payload: bytes) -> bytes:
    return esp32.mac_bytes(target) + esp32.mac_bytes(source) + struct.pack(">H", protocol) + payload


class MemoryPort:
    """An L2 port with no kernel behind it. Frames the radio delivers are read with `received`;
    frames written with `transmit` go to the radio. Addresses and neighbours are recorded."""

    def __init__(self, name: str, address: wlan.MACAddress):
        self._name = name
        self._address = address
        self._to_host_send, self._to_host_recv = trio.open_memory_channel(math.inf)
        self._to_air_send, self._to_air_recv = trio.open_memory_channel(math.inf)
        self.addresses: list[tuple[str, str]] = []
        self.neighbors: dict[str, wlan.MACAddress] = {}

    def name(self) -> str:
        return self._name

    def index(self) -> int:
        return 0

    def address(self) -> wlan.MACAddress:
        return self._address

    async def up(self) -> None:
        pass

    def disable_ipv6(self) -> None:
        pass

    async def update_link(self, address: wlan.MACAddress) -> None:
        self._address = address

    async def add_address(self, local: str, broadcast: str, prefix: int = 24) -> None:
        self.addresses.append((local, broadcast))

    async def add_neighbor(self, ipaddr: str, macaddr: wlan.MACAddress) -> None:
        self.neighbors[ipaddr] = macaddr

    async def remove_neighbor(self, ipaddr: str, macaddr: wlan.MACAddress) -> None:
        self.neighbors.pop(ipaddr, None)

    # the radio side
    async def write(self, frame: bytes) -> None:
        self._to_host_send.send_nowait(frame)

    async def read(self) -> bytes:
        return await self._to_air_recv.receive()

    # the host side
    async def received(self) -> bytes:
        return await self._to_host_recv.receive()

    def transmit(self, frame: bytes) -> None:
        self._to_air_send.send_nowait(frame)


class _Router:
    """Carries the radio's reader-thread callbacks into trio channels, one per consumer."""

    def __init__(self, radio: esp32.Radio):
        self.radio = radio
        self._token = trio.lowlevel.current_trio_token()
        self.mgmt_send, self.mgmt = trio.open_memory_channel(math.inf)
        self.control_send, self.control = trio.open_memory_channel(math.inf)
        self.data_send, self.data = trio.open_memory_channel(math.inf)
        radio.subscribe(self._callback)

    def close(self) -> None:
        self.radio.unsubscribe(self._callback)

    def _callback(self, msg_type: int, payload: bytes) -> None:
        if msg_type == esp32.MSG_RX_MGMT:
            target = self.mgmt_send
        elif msg_type == esp32.MSG_RX_ETH:
            is_control = len(payload) >= 14 and payload[12:14] == b"\x88\xb7"
            target = self.control_send if is_control else self.data_send
        elif msg_type in (esp32.MSG_LINK, esp32.MSG_STA_JOINED, esp32.MSG_STA_LEFT):
            target = self.control_send
        else:
            return
        try:
            self._token.run_sync_soon(target.send_nowait, (msg_type, payload))
        except trio.RunFinishedError:
            pass


def _action_event(payload: bytes) -> tuple[wlan.ActionFrame, int] | None:
    mgmt = esp32.ManagementFrame.parse(payload)
    action = wlan.ActionFrame()
    try:
        action.decode(mgmt.frame)
    except Exception:
        return None
    return action, wlan.Channels.get(mgmt.channel, 0)


class EspMonitor:
    """Scanning, and the access point's raw path: action frames out, data frames in and out."""

    def __init__(self, factory: "EspFactory", address: wlan.MACAddress):
        self._factory = factory
        self._address = address
        self._filter = None

    def name(self) -> str:
        return "esp32-monitor"

    def address(self) -> wlan.MACAddress:
        return self._address

    def set_filter(self, filter) -> None:
        self._filter = wlan.MACAddress(filter) if isinstance(filter, str) else filter

    async def set_channel(self, channel: int) -> None:
        await trio.to_thread.run_sync(self._factory.radio.set_channel, channel)

    async def recv(self) -> wlan.RadiotapFrame:
        while True:
            _, payload = await self._factory.router.mgmt.receive()
            mgmt = esp32.ManagementFrame.parse(payload)
            radiotap = wlan.RadiotapFrame(mgmt.frame)
            radiotap.frequency = wlan.Channels.get(mgmt.channel)
            radiotap.channel_flags = 0
            if radiotap.frequency is not None:
                return radiotap

    async def recv_frame(self):
        while True:
            _, payload = await self._factory.router.data.receive()
            ethernet = wlan.EthernetFrame()
            ethernet.decode(payload)
            snap = wlan.SNAPHeader()
            snap.protocol = ethernet.protocol
            snap.payload = ethernet.payload
            frame = wlan.DataFrame()
            frame.target = ethernet.target
            frame.source = ethernet.source
            frame.bssid = self._address
            frame.tods = True
            frame.payload = snap.encode()
            return frame

    async def send_frame(self, frame, *, encrypt: bool = False) -> None:
        radio = self._factory.radio
        if isinstance(frame, wlan.DataFrame):
            if frame.protected:
                # The board encrypts with the key it holds; undo the library's software CCMP.
                frame.decrypt(self._factory.ap_key)
            snap = wlan.SNAPHeader()
            snap.decode(frame.payload)
            radio.send_ethernet(_ethernet(frame.target, frame.source, snap.protocol, snap.payload))
        else:
            radio.send_raw(frame.encode())


class EspStation:
    def __init__(self, factory: "EspFactory", port, address: wlan.MACAddress, ssid: str,
                 channel: int, key: bytes, bssid: wlan.MACAddress):
        self._factory = factory
        self._port = port
        self._address = address
        self._ssid = ssid
        self._channel = channel
        self._key = key
        self._bssid = bssid
        self._events_send, self._events = trio.open_memory_channel(math.inf)

    def name(self) -> str:
        return self._port.name()

    def index(self) -> int:
        return self._port.index()

    def address(self) -> wlan.MACAddress:
        return self._address

    async def next_event(self):
        return await self._events.receive()

    async def send_custom_frame(self, addr: wlan.MACAddress, frame: bytes) -> None:
        self._factory.radio.send_ethernet(_ethernet(addr, self._address, ETH_P_LDN, frame))

    async def set_authorized(self) -> None:
        pass

    async def add_address(self, local: str, broadcast: str, prefix: int = 24) -> None:
        await self._port.add_address(local, broadcast, prefix)

    async def add_neighbor(self, ipaddr: str, macaddr: wlan.MACAddress) -> None:
        await self._port.add_neighbor(ipaddr, macaddr)

    async def remove_neighbor(self, ipaddr: str, macaddr: wlan.MACAddress) -> None:
        await self._port.remove_neighbor(ipaddr, macaddr)

    @contextlib.asynccontextmanager
    async def connect(self):
        radio, router = self._factory.radio, self._factory.router
        await trio.to_thread.run_sync(
            radio.sta_join, self._channel, self._bssid, self._ssid, self._key, self._address)
        with trio.fail_after(self._factory.join_timeout):
            while True:
                msg_type, payload = await router.control.receive()
                if msg_type != esp32.MSG_LINK:
                    continue
                link = esp32.Link.parse(payload)
                if not link.up:
                    raise ConnectionError(f"the board could not join (reason {link.reason:#x})")
                break
        try:
            async with trio.open_nursery() as nursery:
                nursery.start_soon(self._pump_control)
                nursery.start_soon(self._pump_mgmt)
                nursery.start_soon(self._pump_data_in)
                nursery.start_soon(self._pump_data_out)
                try:
                    yield
                finally:
                    nursery.cancel_scope.cancel()
        finally:
            with trio.CancelScope(shield=True):
                await trio.to_thread.run_sync(radio.stop)

    async def _pump_control(self) -> None:
        while True:
            msg_type, payload = await self._factory.router.control.receive()
            if msg_type == esp32.MSG_RX_ETH:
                ethernet = wlan.EthernetFrame()
                ethernet.decode(payload)
                self._events_send.send_nowait(wlan.CustomFrameEvent(ethernet.source, ethernet.payload))
            elif msg_type == esp32.MSG_LINK and not esp32.Link.parse(payload).up:
                self._events_send.send_nowait(wlan.DisassociationEvent(self._bssid))

    async def _pump_mgmt(self) -> None:
        while True:
            _, payload = await self._factory.router.mgmt.receive()
            event = _action_event(payload)
            if event is not None:
                self._events_send.send_nowait(wlan.ActionFrameEvent(*event))

    async def _pump_data_in(self) -> None:
        while True:
            _, payload = await self._factory.router.data.receive()
            await self._port.write(payload)

    async def _pump_data_out(self) -> None:
        while True:
            frame = await self._port.read()
            self._factory.radio.send_ethernet(frame)


class EspAccessPoint:
    def __init__(self, factory: "EspFactory", address: wlan.MACAddress, ssid: str, channel: int,
                 key: bytes, max_stations: int):
        self._factory = factory
        self._address = address
        self._ssid = ssid
        self._channel = channel
        self._key = key
        self._max_stations = max_stations
        self._events_send, self._events = trio.open_memory_channel(math.inf)

    def name(self) -> str:
        return "esp32-ap"

    def address(self) -> wlan.MACAddress:
        return self._address

    async def next_event(self):
        return await self._events.receive()

    async def send_custom_frame(self, addr: wlan.MACAddress, frame: bytes) -> None:
        self._factory.radio.send_ethernet(_ethernet(addr, self._address, ETH_P_LDN, frame))

    async def remove_station(self, addr: wlan.MACAddress) -> None:
        await trio.to_thread.run_sync(self._factory.radio.kick, addr)

    async def set_authorized(self, addr: wlan.MACAddress) -> None:
        pass

    async def add_neighbor(self, ipaddr: str, macaddr: wlan.MACAddress) -> None:
        if self._factory.tap is not None:
            await self._factory.tap.add_neighbor(ipaddr, macaddr)

    async def remove_neighbor(self, ipaddr: str, macaddr: wlan.MACAddress) -> None:
        if self._factory.tap is not None:
            await self._factory.tap.remove_neighbor(ipaddr, macaddr)

    @contextlib.asynccontextmanager
    async def create(self):
        if self._key is None:
            raise NotImplementedError("the ESP32 access point runs protected networks only")
        radio, router = self._factory.radio, self._factory.router
        self._factory.ap_key = self._key
        await trio.to_thread.run_sync(
            radio.ap_start, self._channel, self._address, self._ssid, self._key,
            self._max_stations, self._factory.ap_flags)
        with trio.fail_after(5):
            while True:
                msg_type, payload = await router.control.receive()
                if msg_type == esp32.MSG_LINK:
                    if not esp32.Link.parse(payload).up:
                        raise ConnectionError("the board could not start the access point")
                    break
        try:
            async with trio.open_nursery() as nursery:
                nursery.start_soon(self._pump_control)
                try:
                    yield
                finally:
                    nursery.cancel_scope.cancel()
        finally:
            with trio.CancelScope(shield=True):
                await trio.to_thread.run_sync(radio.stop)

    async def _pump_control(self) -> None:
        while True:
            msg_type, payload = await self._factory.router.control.receive()
            if msg_type == esp32.MSG_RX_ETH:
                ethernet = wlan.EthernetFrame()
                ethernet.decode(payload)
                self._events_send.send_nowait(wlan.CustomFrameEvent(ethernet.source, ethernet.payload))
            elif msg_type == esp32.MSG_STA_JOINED:
                joined = esp32.StationJoined.parse(payload)
                self._events_send.send_nowait(wlan.AssociationEvent(wlan.MACAddress(joined.mac)))
            elif msg_type == esp32.MSG_STA_LEFT:
                left = esp32.StationLeft.parse(payload)
                self._events_send.send_nowait(
                    wlan.DisassociationEvent(wlan.MACAddress(left.mac), left.reason, "deauthentication"))


class EspFactory:
    """Stands in for `wlan.Factory`. `port_factory(name, address)` returns an async context
    manager yielding the L2 port; the default is a kernel TAP."""

    def __init__(self, radio: esp32.Radio, port_factory=None, join_timeout: float = 20.0,
                 ap_flags: int = 0):
        self.radio = radio
        self.router = _Router(radio)
        self.port_factory = port_factory or kernel_tap
        self.join_timeout = join_timeout
        self.ap_flags = ap_flags
        self.tap = None
        self.ap_key = None
        self._ap_address = None

    @contextlib.asynccontextmanager
    async def create_monitor(self, phyname: str, ifname: str, channel: int | None = None):
        address = self._ap_address or wlan.MACAddress(bytes(self.radio.hello().sta_mac))
        monitor = EspMonitor(self, address)
        if channel is not None:
            await monitor.set_channel(channel)
        yield monitor

    @contextlib.asynccontextmanager
    async def connect_network(self, phyname: str, ifname: str, ssid: str, channel: int,
                              key: bytes | None, bssid: wlan.MACAddress | None = None):
        if key is None or bssid is None:
            raise NotImplementedError("the ESP32 station joins protected networks by BSSID")
        address = _random_mac()
        async with self.port_factory(ifname, address) as port:
            station = EspStation(self, port, address, ssid, channel, key, bssid)
            async with station.connect():
                yield station

    @contextlib.asynccontextmanager
    async def create_ap(self, phyname: str, ifname: str, ssid: str, channel: int,
                        key: bytes | None, max_stations: int):
        self._ap_address = _random_mac()
        access_point = EspAccessPoint(self, self._ap_address, ssid, channel, key, max_stations)
        async with access_point.create():
            yield access_point

    @contextlib.asynccontextmanager
    async def create_tap(self, ifname: str, address: wlan.MACAddress):
        async with self.port_factory(ifname, address) as port:
            self.tap = port
            try:
                yield port
            finally:
                self.tap = None


@contextlib.asynccontextmanager
async def memory_port(name: str, address: wlan.MACAddress):
    yield MemoryPort(name, address)


@contextlib.asynccontextmanager
async def kernel_tap(name: str, address: wlan.MACAddress):
    """A Linux TAP named `name` carrying the radio's frames, so sockets bound to it work."""
    from netlink import route
    async with route.connect() as router:
        factory = wlan.Factory.__new__(wlan.Factory)
        factory._router = router
        factory._wlan = None
        async with wlan.Factory.create_tap(factory, name, address) as tap:
            await tap.up()
            tap.disable_ipv6()
            yield tap


_radio: esp32.Radio | None = None


def use(port: str | None = None, *, radio: esp32.Radio | None = None, port_factory=None,
        ap_flags: int = 0, log=None) -> esp32.Radio:
    """Routes every later `ldn.scan` / `ldn.connect` / `ldn.create_network` through the board.
    The serial port is opened once and kept, since opening it can reset the board."""
    global _radio
    if radio is None:
        if _radio is None:
            _radio = esp32.Radio.open_serial(port, log=log)
        radio = _radio
    else:
        _radio = radio

    @contextlib.asynccontextmanager
    async def factory():
        esp = EspFactory(radio, port_factory=port_factory, ap_flags=ap_flags)
        try:
            yield esp
        finally:
            esp.router.close()

    wlan.set_factory(factory)
    return radio


def use_from_environment(log=None) -> esp32.Radio | None:
    """`POKELDN_RADIO=esp32:/dev/cu.usbserial-0001` selects the board for the whole process."""
    spec = os.environ.get("POKELDN_RADIO", "")
    if not spec.startswith("esp32:"):
        return None
    return use(spec[len("esp32:"):], log=log)
