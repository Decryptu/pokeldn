"""The hosting side of a Dynamax Adventure (Max Lair) lobby: the snapshot exchange of a link trade,
then the id-7000 lobby messages on 0x80 port 0 as an emulated Shield host sent them, up to the
legendary (docs/swsh_raid.md, Dynamax Adventures). The host then leaves; `finished` says when. No
socket I/O here.
"""
import struct
import time
from pathlib import Path

from pokeldn.ldn import reliable4
from pokeldn.swsh import lair
from pokeldn.swsh.host_trade import HostTrade
from pokeldn.swsh.trade import field, field_varint, message

TIME_LIMIT_START = 180                # the emulated host's lobby counted down from 3:00
TIME_LIMIT_PERIOD = 1 / 3
# Sent compressed by the emulated host (reliable flag 0x10); the others went out plain.
COMPRESSED = (lair.PLAYER_INFO, lair.BATTLE_START, lair.PLAYER_NUMBER)
# An emulated Shield's Max Lair advertisement (activity 0xff, nothing after it), name and ids its own.
ADVERT = Path(__file__).with_name("data") / "lair_advert.bin"


def scalar(which, value):
    """A field whose holder carries a varint: the time limit and the two seeds."""
    return message(lair.CHIKA, field(which, field_varint(1, value)))


def battle_start(stations):
    """The human players' constant ids, the joined guest's first, in four u64 slots."""
    return lair.holder(lair.CHIKA, lair.BATTLE_START,
                       b"".join(struct.pack("<Q", s) for s in stations).ljust(32, b"\0"))


def player_number(stations):
    """Four constant ids, the host's first and zero for a computer partner, then indexes 0 to 3."""
    ids = list(stations) + [0] * (4 - len(stations))
    return lair.holder(lair.CHIKA, lair.PLAYER_NUMBER, struct.pack("<4Q", *ids) + bytes(range(4)) + bytes(4))


def big_boss_fixed(species):
    return lair.holder(lair.CHIKA, lair.BIG_BOSS_FIXED, struct.pack("<I", species))


class LairHost(HostTrade):
    """One joined guest's lobby. `send(protocol, port, payload, compress)`."""

    def __init__(self, self_id, peer_id, snapshot, our_pk8, send, send_broadcast, send_mesh,
                 legendary, seed, rental_seed, name="POKELDN", ready_after=1.0, leave_after=5.0,
                 log=print, record=None, snapshot_builder=None):
        super().__init__(self_id, peer_id, snapshot, our_pk8,
                         lambda protocol, port, payload: send(protocol, port, payload, False),
                         send_broadcast, send_mesh, log=log, record=record,
                         snapshot_builder=snapshot_builder)
        self._send_lobby = send
        self.stage = "snapshot"
        self.legendary, self.seed, self.rental_seed, self.name = legendary, seed, rental_seed, name
        self.ready_after, self.leave_after = ready_after, leave_after
        self.limit_last = 0.0
        self.lobby_at = self.fixed_at = None
        self.ready_sent = False
        self.finished = False
        self.guest = {"info": None, "pk8": None, "ready": False, "started": False}

    def lobby(self, which, payload):
        self._send_lobby(reliable4.BROADCAST_PROTOCOL, 0, payload, which in COMPRESSED)

    def on_data(self, protocol, port, payload, now=None):
        got = lair.parse(bytes(payload)) if protocol == reliable4.BROADCAST_PROTOCOL else None
        if got is None:
            return super().on_data(protocol, port, payload, now)
        which_id, which, data = got
        if which_id == lair.CHIKA and which == lair.PLAYER_INFO:
            self.guest["info"] = data
            self.log(f"[lair] <- the guest's PlayerInfo {data[12:38].decode('utf-16-le', 'replace')!r}")
        elif which_id == lair.CHIKA and which == lair.BATTLE_READY:
            self.guest["ready"], self.guest["started"] = data[8] == 1, data[12] == 1
            self.log(f"[lair] <- the guest's BattleReady ready={data[8]} started={data[12]}")
        elif which_id == lair.CHIKA and which == lair.SELECT_POKEMON:
            self.guest["pk8"] = data[12:12 + lair.PK8_PARTY]
            self.log(f"[lair] <- the guest takes rental {struct.unpack_from('<I', data, 8)[0]}")
        else:
            self.log(f"[lair] <- {which_id} field {which} {data.hex()[:64] if isinstance(data, bytes) else data}")
        self.record(rec="lair_rx", holder=which_id, field=which,
                    data=data.hex() if isinstance(data, bytes) else data)

    def _stage_snapshot(self, now):
        super()._stage_snapshot(now)
        if self.stage == "sync110":
            self.goto("lobby")

    def _time_limit(self, now):
        if now - self.limit_last >= TIME_LIMIT_PERIOD:
            self.limit_last = now
            self.lobby(lair.TIME_LIMIT, scalar(lair.TIME_LIMIT, max(0, TIME_LIMIT_START - int(now - self.lobby_at))))

    def _stage_lobby(self, now):
        if self.lobby_at is None:
            self.lobby_at = now
            self.lobby(lair.PLAYER_INFO, lair.player_info(self.name))
            self.lobby(lair.BATTLE_READY, lair.battle_ready())
            self.lobby(lair.BIG_BOSS, lair.big_boss())
            self.log("[lair] -> our PlayerInfo, BattleReady and BigBoss")
        self._time_limit(now)
        # The emulated host readied first and started once the guest had readied.
        if not self.ready_sent and now - self.lobby_at >= self.ready_after:
            self.ready_sent = True
            self.lobby(lair.BATTLE_READY, lair.battle_ready(True))
            self.log("[lair] -> ready")
        if self.ready_sent and self.guest["ready"]:
            stations = [self.self_id, self.peer_id]
            self.lobby(lair.BATTLE_START, battle_start(stations[::-1]))
            self.lobby(lair.BATTLE_SEED, scalar(lair.BATTLE_SEED, self.seed))
            self.lobby(lair.RENTAL_SEED, scalar(lair.RENTAL_SEED, self.rental_seed))
            self.lobby(lair.PLAYER_NUMBER, player_number(stations))
            self.log(f"[lair] -> BattleStart, seed {self.seed:#018x}, PlayerNumber")
            self.goto("start")

    def _stage_start(self, now):
        self._time_limit(now)
        if self.guest["started"]:
            self.lobby(lair.BATTLE_READY, lair.battle_ready(True, started=True))
            self.lobby(lair.BIG_BOSS_FIXED, big_boss_fixed(self.legendary))
            self.log(f"[lair] -> started, legendary {self.legendary}")
            self.fixed_at = now
            self.goto("leave")

    def _stage_leave(self, now):
        # A computer partner takes our seat once we are gone (docs/swsh_raid.md, Dynamax Adventures).
        # Rentals go in turns, the host's first: the guest's choice waits on ours (or our partner's).
        if now - self.fixed_at >= self.leave_after:
            if not self.finished:
                self.log("[lair] the adventure is set; leaving it to the console")
            self.finished = True

    def tick(self, now=None):
        now = time.time() if now is None else now
        getattr(self, "_stage_" + self.stage)(now)
