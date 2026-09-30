#!/usr/bin/env python3
"""Run the experimental FRLG LAN data probe (P0; trade start is disabled)."""

import argparse
from dataclasses import replace
import getpass
import os
import secrets
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

BUNDLED_LDN = os.path.join(PROJECT_ROOT, "vendor", "LDN")
if os.path.isdir(os.path.join(BUNDLED_LDN, "ldn")):
    sys.path.insert(0, BUNDLED_LDN)

from pokeldn.host_support import needs_root  # noqa: E402
from pokeldn.frlg import config as configmod, host_cli  # noqa: E402
from pokeldn.frlg.link import trade_runtime  # noqa: E402
from pokeldn.frlg.remote.app import RemoteAppConfig, RemoteProbeApplication  # noqa: E402
from pokeldn.frlg.remote.config import DEFAULT_PORT, RemoteTradeConfig  # noqa: E402
from pokeldn.frlg.remote.transport import RemoteTransport, TransportError  # noqa: E402

HOST_TICK_HZ = 59.727


def build_parser(file_config=None, *, shared_path=None, local_path=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    if file_config is None:
        file_config = configmod.load_project_host_file_config()
    commands = parser.add_subparsers(dest="remote_role", required=True)
    defaults = replace(file_config.to_host_options(), max_participants=2)
    ldn_defaults = file_config.to_ldn_config()
    for role in ("host", "join"):
        command = commands.add_parser(role, help=f"LAN {role} for one local Switch")
        if role == "host":
            command.add_argument("--listen", required=True,
                                 help="explicit private LAN IP for the TCP listener")
        else:
            command.add_argument("--connect", required=True,
                                 help="private LAN IP of the room host")
        command.add_argument("--port", type=int, default=DEFAULT_PORT)
        command.add_argument("--bridge-name", default="LDN-A" if role == "host" else "LDN-B",
                             help="short local discovery name shown by the Switch")
        command.add_argument("--config", metavar="PATH",
                             default=str(shared_path) if shared_path else None,
                             help="shared host TOML (default: config/host.toml)")
        local = command.add_mutually_exclusive_group()
        local.add_argument("--local-config", metavar="PATH",
                           default=str(local_path) if local_path else None,
                           help="optional machine-local TOML")
        local.add_argument("--no-local-config", action="store_true",
                           help="do not load host.local.toml")
        command.add_argument("--verbose", action="store_true",
                             help="show detailed local wireless milestones")
        command.add_argument("--password", default="",
                             help="local LDN passphrase hex; default uses project settings")
        command.add_argument("--phy", default=ldn_defaults.phy,
                             help="Wi-Fi phy; explicit phyN overrides --adapter")
        command.add_argument("--adapter", default=ldn_defaults.adapter,
                             help="named Wi-Fi adapter profile")
        command.add_argument("--keys", default=ldn_defaults.keys_path)
        command.add_argument("--comm-id", default=(
            None if ldn_defaults.local_comm_id is None else f"{ldn_defaults.local_comm_id:x}"),
            help="LDN local_communication_id in hexadecimal")
        command.add_argument("--capture", metavar="FILE", default=ldn_defaults.capture_path,
                             help="optional local LDN/Pia diagnostic capture")
        command.add_argument("--channel", type=int, default=defaults.channel,
                             choices=[*range(1, 15), 36, 40, 44, 48],
                             help="local Switch access-point channel")
        command.add_argument("--scene", type=int, default=defaults.scene_id,
                             help="LDN scene; default is the known Direct Corner scene")
        command.add_argument("--skip-preflight", action=argparse.BooleanOptionalAction,
                             default=defaults.skip_preflight)
        command.add_argument("--skip-encryption", action=argparse.BooleanOptionalAction,
                             default=defaults.skip_encryption,
                             help="delegate CCMP to a compatible local Wi-Fi driver")
        command.add_argument("--accept-decrypted-ccmp", action=argparse.BooleanOptionalAction,
                             default=defaults.accept_decrypted_ccmp,
                             help="accept hardware-decrypted CCMP from a compatible adapter")
        command.add_argument("--native-nonce-sequence", action=argparse.BooleanOptionalAction,
                             default=defaults.native_nonce_sequence)
        command.add_argument("--session-response-first", action=argparse.BooleanOptionalAction,
                             default=defaults.session_response_first)
    return parser


def _room_key(args):
    if args.remote_role == "host":
        key = secrets.token_bytes(32)
        print("One-time LAN room key (share through a trusted private channel):")
        print(key.hex())
        return key
    raw = getpass.getpass("LAN room key (64 hex characters): ").strip()
    try:
        key = bytes.fromhex(raw)
    except ValueError as exc:
        raise ValueError("room key must be hexadecimal") from exc
    if len(key) != 32:
        raise ValueError("room key must contain exactly 64 hex characters")
    return key


def build_remote_config(parser, args):
    try:
        args.ot = args.bridge_name
        args.version = None
        args.language = None
        args.id = None
        args.card_flag_id = None
        args.trust_pia = True
        args.max_participants = 2
        args.tick_hz = HOST_TICK_HZ
        args.live = True
        profile, ldn, role = host_cli.build_host_config(parser, args)
        bridge_name = args.bridge_name
        if not bridge_name.isascii() or not 1 <= len(bridge_name) <= 7:
            raise ValueError("bridge-name must contain 1..7 ASCII characters")
        # This profile is used only for local LDN/Pia discovery. The FRLG LinkPlayer and trainer
        # card sent to the Switch are taken from the other real console by the probe policy.
        random_tid = secrets.randbelow(0x10000)
        random_sid = secrets.randbelow(0x10000)
        profile = configmod.profile_from_overrides(
            ot=bridge_name, trainer_id=(random_tid, random_sid), base=profile)
        config = RemoteTradeConfig(
            role=args.remote_role,
            port=args.port,
            listen=getattr(args, "listen", None),
            connect=getattr(args, "connect", None),
            channel=role.channel,
            discovery_name=bridge_name,
            room_key=_room_key(args),
        )
        return RemoteAppConfig(profile=profile, ldn=ldn, role=role), config
    except ValueError as exc:
        parser.error(str(exc))


def main(argv=None):
    try:
        file_config, shared_path, local_path = \
            host_cli.load_host_file_config_from_argv(argv)
    except (ValueError, SystemExit) as exc:
        print(f"bin/frlg_remote_trade.py: error: {exc}", file=sys.stderr)
        return 2
    parser = build_parser(file_config, shared_path=shared_path, local_path=local_path)
    args = parser.parse_args(argv)
    if needs_root():
        parser.error("live LDN hosting requires elevated radio permissions")
    app_config, lan_config = build_remote_config(parser, args)
    transport = RemoteTransport(lan_config, log=print)
    try:
        transport.start()
        print("LAN pair ready. Start both Switches at Join Group only after both PCs report ready.")
        app = RemoteProbeApplication(
            app_config, transport, log=trade_runtime.ConsoleLog(args.verbose))
        joined = app.run()
        return 0 if joined else 130
    except (OSError, TransportError, ValueError, RuntimeError) as exc:
        print(f"bin/frlg_remote_trade.py: error: {exc}", file=sys.stderr)
        return 2
    finally:
        transport.close()


if __name__ == "__main__":
    sys.exit(main())
