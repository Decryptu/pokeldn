"""Configuration for the first, trade-disabled FRLG LAN probe."""

from dataclasses import dataclass, field
import ipaddress
import math


DEFAULT_PORT = 24873
PROBE_CAPABILITY = "frlg-direct-trade-probe-v1"


@dataclass(frozen=True)
class RemoteTradeConfig:
    """One explicitly addressed LAN endpoint. The room key is never part of repr/logging."""

    role: str
    port: int = DEFAULT_PORT
    listen: str | None = None
    connect: str | None = None
    channel: int = 1
    discovery_name: str = "LDN-A"
    room_key: bytes = field(default=b"", repr=False, compare=False)
    connect_timeout: float = 30.0
    probe_only: bool = True

    def __post_init__(self):
        if self.role not in ("host", "join"):
            raise ValueError("role must be 'host' or 'join'")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if self.role == "host":
            if self.listen is None or self.connect is not None:
                raise ValueError("host requires --listen and cannot use --connect")
            _check_lan_address(self.listen, "listen")
        else:
            if self.connect is None or self.listen is not None:
                raise ValueError("join requires --connect and cannot use --listen")
            _check_lan_address(self.connect, "connect")
        if type(self.channel) is not int or not (
                1 <= self.channel <= 14 or self.channel in (36, 40, 44, 48)):
            raise ValueError("channel must be 1..14 or one of 36, 40, 44, 48")
        if (not isinstance(self.discovery_name, str) or not self.discovery_name
                or len(self.discovery_name.encode("ascii", errors="ignore")) != len(self.discovery_name)
                or len(self.discovery_name) > 7):
            raise ValueError("discovery_name must be 1..7 ASCII characters")
        if not isinstance(self.room_key, bytes) or len(self.room_key) < 16:
            raise ValueError("room_key must contain at least 128 bits")
        if (type(self.connect_timeout) not in (int, float)
                or not math.isfinite(self.connect_timeout) or self.connect_timeout <= 0):
            raise ValueError("connect_timeout must be positive")
        if self.probe_only is not True:
            raise ValueError("the initial LAN implementation is permanently probe-only")


def _check_lan_address(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an explicit LAN IP address")
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an explicit IPv4 or IPv6 address") from exc
    if address.is_unspecified or address.is_multicast:
        raise ValueError(f"{label} must identify a specific interface, not a wildcard")
    if address.version == 4:
        allowed_networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                            "169.254.0.0/16", "127.0.0.0/8")
    else:
        allowed_networks = ("fc00::/7", "fe80::/10", "::1/128")
    if not any(address in ipaddress.ip_network(network) for network in allowed_networks):
        raise ValueError(f"{label} must be private, link-local or loopback")
