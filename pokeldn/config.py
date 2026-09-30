"""Shared radio settings and tracked TOML defaults."""
from dataclasses import dataclass, replace
from pathlib import Path
import tomllib
from typing import Any, Mapping

@dataclass(frozen=True)
class LdnConfig:
    password: bytes | None = None
    phy: str = "phy0"
    # Resolved to a concrete phy at runtime when ``phy`` is "auto".
    adapter: str | None = None
    keys_path: str = "~/.switch/prod.keys"
    local_comm_id: int | None = None
    capture_path: str | None = None

    def __post_init__(self):
        if self.password is not None and not isinstance(self.password, bytes):
            raise ValueError("password must be bytes or None")
        if self.adapter is not None and (
                not isinstance(self.adapter, str) or not self.adapter):
            raise ValueError("adapter must be a non-empty string or None")
        if self.local_comm_id is not None and (
                type(self.local_comm_id) is not int
                or not 0 <= self.local_comm_id <= 0xFFFFFFFFFFFFFFFF):
            raise ValueError("local_comm_id must fit in 64 bits")


HOST_CONFIG_FILENAME = "host.toml"
HOST_LOCAL_CONFIG_FILENAME = "host.local.toml"


@dataclass(frozen=True)
class HostFileConfig:
    """Strict ``[host]`` / ``[ldn]`` TOML sections; the local file overrides the tracked one."""

    live: bool = True
    adapter: str = "tplink-archer-t3u"
    trust_pia: bool = True
    channel: int = 1
    scene_id: int | None = None
    max_participants: int = 6
    skip_preflight: bool = False
    skip_encryption: bool = True
    accept_decrypted_ccmp: bool = True
    native_nonce_sequence: bool = True
    session_response_first: bool = True
    phy: str = "auto"
    keys_path: str = "~/.switch/prod.keys"
    local_comm_id: int | None = None
    capture_path: str | None = None

    def __post_init__(self):
        _require_bool("host.live", self.live)
        _require_nonempty_string("host.adapter", self.adapter)
        _require_bool("host.trust_pia", self.trust_pia)
        if self.channel not in (36, 40, 44, 48):
            _require_int_range("host.channel", self.channel, 1, 14)
        if self.scene_id is not None:
            _require_int_range("host.scene_id", self.scene_id, 0, 0xFFFF)
        _require_int_range("host.max_participants", self.max_participants, 2, 8)
        _require_bool("host.skip_preflight", self.skip_preflight)
        _require_bool("host.skip_encryption", self.skip_encryption)
        _require_bool("host.accept_decrypted_ccmp", self.accept_decrypted_ccmp)
        _require_bool("host.native_nonce_sequence", self.native_nonce_sequence)
        _require_bool("host.session_response_first", self.session_response_first)
        _require_nonempty_string("ldn.phy", self.phy)
        _require_nonempty_string("ldn.keys_path", self.keys_path)
        if self.local_comm_id is not None:
            _require_int_range("ldn.local_comm_id", self.local_comm_id, 0,
                               0xFFFFFFFFFFFFFFFF)
        if self.capture_path is not None:
            _require_nonempty_string("ldn.capture_path", self.capture_path)

    def to_host_options(self):
        from pokeldn.frlg.config import HostOptions
        return HostOptions(
            channel=self.channel,
            scene_id=self.scene_id,
            max_participants=self.max_participants,
            skip_preflight=self.skip_preflight,
            skip_encryption=self.skip_encryption,
            accept_decrypted_ccmp=self.accept_decrypted_ccmp,
            native_nonce_sequence=self.native_nonce_sequence,
            session_response_first=self.session_response_first,
        )

    def to_ldn_config(self):
        return LdnConfig(
            phy=self.phy,
            adapter=self.adapter,
            keys_path=self.keys_path,
            local_comm_id=self.local_comm_id,
            capture_path=self.capture_path,
        )

    def with_overrides(self, overrides: Mapping[str, Mapping[str, Any]] | None):
        return _apply_host_config_layer(self, overrides, source="overrides")


_HOST_TOML_FIELDS = frozenset({
    "live", "adapter", "trust_pia", "channel", "scene_id",
    "max_participants", "skip_preflight", "skip_encryption",
    "accept_decrypted_ccmp", "native_nonce_sequence",
    "session_response_first",
})
_LDN_TOML_FIELDS = frozenset({
    "phy", "keys_path", "local_comm_id", "capture_path",
})
_TOP_LEVEL_TOML_SECTIONS = frozenset({"host", "ldn"})


def project_config_directory():
    return Path(__file__).resolve().parent.parent / "config"


def default_host_config_path():
    return project_config_directory() / HOST_CONFIG_FILENAME


def default_host_local_config_path():
    return project_config_directory() / HOST_LOCAL_CONFIG_FILENAME


def load_host_file_config(config_path, *, local_path=None, overrides=None):
    """Layers: builtin < config_path (required) < local_path (optional) < overrides."""
    result = BUILTIN_HOST_FILE_CONFIG
    result = _apply_host_config_layer(
        result, _read_host_toml(Path(config_path), required=True),
        source=str(config_path))
    if local_path is not None:
        local_path = Path(local_path)
        if local_path.is_file():
            result = _apply_host_config_layer(
                result, _read_host_toml(local_path, required=False),
                source=str(local_path))
        elif local_path.exists():
            raise ValueError(f"host local configuration is not a file: {local_path}")
    return _apply_host_config_layer(result, overrides, source="overrides")


def load_project_host_file_config(*, overrides=None):
    return load_host_file_config(
        default_host_config_path(),
        local_path=default_host_local_config_path(),
        overrides=overrides,
    )


def _read_host_toml(path, *, required):
    if not path.is_file():
        if required:
            raise ValueError(f"host configuration file does not exist: {path}")
        return {}
    try:
        with path.open("rb") as source:
            raw = tomllib.load(source)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid TOML in host configuration {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"host configuration must be a TOML table: {path}")
    return raw


def _apply_host_config_layer(base, layer, *, source):
    if layer is None:
        return base
    if not isinstance(layer, Mapping):
        raise ValueError(f"{source} host configuration must be a mapping")

    unexpected = set(layer) - _TOP_LEVEL_TOML_SECTIONS
    if unexpected:
        raise ValueError(
            f"{source} has unknown host configuration section(s): "
            f"{', '.join(sorted(unexpected))}")

    values = {}
    for section, allowed in (("host", _HOST_TOML_FIELDS), ("ldn", _LDN_TOML_FIELDS)):
        section_values = layer.get(section, {})
        if not isinstance(section_values, Mapping):
            raise ValueError(f"{source} [{section}] must be a TOML table")
        unexpected = set(section_values) - allowed
        if unexpected:
            raise ValueError(
                f"{source} [{section}] has unknown key(s): "
                f"{', '.join(sorted(unexpected))}")
        values.update(section_values)
    try:
        return replace(base, **values)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {source} host configuration: {exc}") from exc


def _require_bool(name, value):
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")


def _require_nonempty_string(name, value):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_int_range(name, value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{name} must be an integer between {lower} and {upper}")


BUILTIN_HOST_FILE_CONFIG = HostFileConfig()



def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)
    from pokeldn.frlg import config
    return getattr(config, name)
