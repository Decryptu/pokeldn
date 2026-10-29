"""What the bin/ launchers share: the radio flags every one of them takes, the Linux-era interface
names, the emulated-console host pair, and the line a joiner prints for a network it scanned.

A flag's name, dest, default and type are what pokeldn/app/catalog.py builds command lines from;
a launcher whose default differs passes it here. The FireRed hosts take theirs from
pokeldn.frlg.host_cli, whose defaults come from config/host*.toml.
"""

KEYS_HELP = "the Switch's prod.keys; default keys_path from config/host.toml or host.local.toml"
PHY_HELP = "a Linux Wi-Fi card's phy (phyN), or auto; POKELDN_RADIO selects a board instead"
CAPTURE_HELP = "write every datagram here, one JSON line each"


def add_radio_arguments(ap, *, phy="auto", capture=CAPTURE_HELP):
    """--keys, --phy and --capture; `capture=None` leaves --capture out, a string is its help."""
    ap.add_argument("--keys", default=None, metavar="FILE", help=KEYS_HELP)
    ap.add_argument("--phy", default=phy, help=PHY_HELP)
    if capture is not None:
        ap.add_argument("--capture", default=None, metavar="FILE", help=capture)


def add_linux_arguments(ap, *, host=False):
    """The kernel interfaces a Linux Wi-Fi card is driven through; a board has none
    (docs/hardware_adapters.md)."""
    if not host:
        ap.add_argument("--ifname", default="ldnclient", help="Linux: the station interface")
        return
    ap.add_argument("--ifname", default="ldn-tap", help="Linux: the tap the host's Pia runs on")
    ap.add_argument("--ap-ifname", default="ldn", help="Linux: the access point interface")
    ap.add_argument("--mon-ifname", default="ldn-mon", help="Linux: the monitor interface")


def add_ip_host_arguments(ap, *, our_ip_help="with --ip-host, the address to advertise"):
    """--ip-host and --our-ip: host an emulated console over ldn_mitm on the LAN (docs/ldn.md)."""
    ap.add_argument("--ip-host", action="store_true",
                    help="host an emulated console over ldn_mitm on the LAN; no radio and no root")
    ap.add_argument("--our-ip", default=None, help=our_ip_help)


def add_hold_after_trade_argument(ap, *, host=False):
    """--hold-after-trade: leave the seat, or close the hosted session, N seconds after the last queued
    trade (pokeldn.ldn.hold_after_trade_over); by default the run waits for the console to leave."""
    what = "close the session" if host else "leave the seat"
    ap.add_argument("--hold-after-trade", type=float, default=None, metavar="SECONDS",
                    help=f"{what} this long after the last queued trade; by default the run keeps it "
                         "until the console leaves or the time limit ends")


def describe_network(net, name="", suffix=""):
    """One scanned network on one line; `name` is the title its communication id belongs to."""
    return (f"comm_id=0x{net.local_communication_id:016x}{f' ({name})' if name else ''} "
            f"scene={net.scene_id} version={net.version} app_version={net.app_version} "
            f"ch={net.channel} {net.num_participants}/{net.max_participants}{suffix}")
