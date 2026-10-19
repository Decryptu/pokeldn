"""The hosting side of a Sword/Shield Max Raid den lobby: the snapshot exchange of a link trade,
then the id-2000 lobby messages on 0x80 port 0 as an emulated Shield host sent them
(docs/swsh_raid.md, The guest's sequence). No socket I/O here.
"""
import time

from pokeldn.ldn import reliable4
from pokeldn.swsh import pokemon, raid, raid_battle
from pokeldn.swsh.host_trade import HostTrade

TIME_LIMIT_START = 0xA0               # seconds the emulated host counted down from
TIME_LIMIT_PERIOD = 1 / 3             # the host sends the time limit three times a second
# Sent compressed by the emulated host (reliable flag 0x10); the others went out plain.
COMPRESSED = (raid.PLAYER_INFO, raid.BATTLE_START, raid.REWARDS)


class RaidParty:
    """The consoles of one hosted lobby, up to three: they ready, start and fight together. The
    battle's client sends through the member whose console a message is for."""

    def __init__(self, our_id, console_serves=False, log=print):
        self.our_id, self.console_serves, self.log = our_id, console_serves, log
        self.members = []                 # RaidHost, in join order
        self.battle = None

    def add(self, member):
        self.members.append(member)

    def remove(self, member):
        if member in self.members:
            self.members.remove(member)

    def lobby(self):
        return [m for m in self.members if m.stage != "snapshot"]

    def ready(self):
        # A console still in its snapshot exchange holds the start back.
        return bool(self.members) and all(m.stage != "snapshot" and m.guest["ready"]
                                          for m in self.members)

    def started(self):
        return all(m.guest["started"] for m in self.lobby())

    def order(self):
        consoles = [m.peer_id for m in self.lobby()]
        return consoles + [self.our_id] if self.console_serves else [self.our_id] + consoles

    def send(self, port, payload, dst):
        for m in self.lobby():
            if dst is None or m.peer_id == dst:
                m._send_lobby(reliable4.PROTOCOL, port, payload, False)

    def start_battle(self, clock, action):
        consoles = [m.peer_id for m in self.lobby()]
        self.battle = raid_battle.Master(self.our_id, consoles, clock=clock, log=self.log,
                                         action=action)
        for port, msg, dst in self.battle.start():
            self.send(port, msg, dst)

    def on_battle_data(self, src, port, payload):
        for port_out, msg, dst in self.battle.receive(port, payload, src):
            self.send(port_out, msg, dst)


class RaidHost(HostTrade):
    """The lobby a hosting Sword runs for one joined guest, up to the battle on 0x7C.
    `send(protocol, port, payload, compress)`; `on_battle(self)` is called once both sides have
    sent BattleReady with the start byte set."""

    STAGES = ("snapshot", "lobby", "start", "battle")

    def __init__(self, self_id, peer_id, snapshot, our_pk8, boss_pk8, send, send_broadcast,
                 send_mesh, rewards=(), seed=0, name="POKELDN", ready_after=1.0, log=print,
                 record=None, snapshot_builder=None, on_battle=None, console_serves=False,
                 party=None):
        super().__init__(self_id, peer_id, snapshot, our_pk8,
                         lambda protocol, port, payload: send(protocol, port, payload, False),
                         send_broadcast, send_mesh, log=log, record=record,
                         snapshot_builder=snapshot_builder)
        self._send_lobby = send
        self.stage = "snapshot"
        self.boss_pk8, self.rewards, self.seed, self.name = bytes(boss_pk8), list(rewards), seed, name
        self.ready_after = ready_after
        self.on_battle = on_battle or (lambda host: None)
        self.limit_last = 0.0
        self.lobby_at = None
        self.ready_sent = self.start_sent = False
        self.guest = {"info": None, "pk8": None, "ready": False, "started": False}
        # The console first in BattleStart and in framework object 0, so it serves the battle and we
        # answer as client 1 (docs/swsh_raid.md, Which station serves).
        self.party = party or RaidParty(self_id, console_serves, log)
        self.party.console_serves = console_serves
        self.party.add(self)

    def lobby(self, which, payload):
        self._send_lobby(reliable4.BROADCAST_PROTOCOL, 0, payload, which in COMPRESSED)

    def on_data(self, protocol, port, payload, now=None):
        if protocol == reliable4.PROTOCOL and self.party.battle is not None:
            self.party.on_battle_data(self.peer_id, port, bytes(payload))
            return
        got = raid.parse(bytes(payload)) if protocol == reliable4.BROADCAST_PROTOCOL else None
        if got is None:
            return super().on_data(protocol, port, payload, now)
        which, data = got
        if which == raid.PLAYER_INFO:
            self.guest["info"] = data
            self.log(f"[raid] <- the guest's PlayerInfo {data[12:38].decode('utf-16-le', 'replace')!r}")
        elif which == raid.SELECT_POKEMON:
            self.guest["pk8"] = data[8:]
            self.log(f"[raid] <- the guest selects EC {data[8:12].hex()}")
        elif which == raid.BATTLE_READY:
            self.guest["ready"], self.guest["started"] = data[8] == 1, data[12] == 1
            self.log(f"[raid] <- the guest's BattleReady ready={data[8]} started={data[12]}")
        else:
            self.log(f"[raid] <- field {which} {data.hex()[:64]}")
        self.record(rec="raid_rx", field=which, data=data.hex())

    def _stage_snapshot(self, now):
        super()._stage_snapshot(now)
        if self.stage == "sync110":
            self.goto("lobby")

    def _time_limit(self, now):
        if now - self.limit_last >= TIME_LIMIT_PERIOD:
            self.limit_last = now
            left = max(0, TIME_LIMIT_START - int(now - self.lobby_at))
            self.lobby(raid.TIME_LIMIT, raid.time_limit(left))

    def _stage_lobby(self, now):
        if self.lobby_at is None:
            self.lobby_at = now
            self.lobby(raid.PLAYER_INFO, raid.player_info(self.name))
            self.lobby(raid.BATTLE_READY, raid.battle_ready())
            self.lobby(raid.SELECT_POKEMON, raid.select_pokemon(self.offer_pk8))
            self.log("[raid] -> our PlayerInfo, BattleReady and SelectPokemon")
        self._time_limit(now)
        if not self.ready_sent and now - self.lobby_at >= self.ready_after:
            self.ready_sent = True
            self.lobby(raid.BATTLE_READY, raid.battle_ready(True))
            self.log("[raid] -> ready")
        if self.ready_sent and self.party.ready():
            for member in self.party.lobby():
                if member.stage == "lobby":
                    member.goto("start")

    def _stage_start(self, now):
        if not self.start_sent:
            self.start_sent = True
            self.lobby(raid.BATTLE_START, raid.battle_start(self.party.order()))
            self.lobby(raid.SELECT_POKEMON, raid.select_pokemon(self.offer_pk8))
            self.lobby(raid.BOSS_POKEMON, raid.boss_pokemon(self.boss_pk8))
            self.lobby(raid.REWARDS, raid.rewards(self.rewards))
            self.lobby(raid.BATTLE_SEED, raid.battle_seed(self.seed))
            self.lobby(raid.BATTLE_READY, raid.battle_ready(True, started=True))
            self.log("[raid] -> BattleStart, BossPokemon, Rewards, BattleSeed, started")
        self._time_limit(now)
        if self.guest["started"]:
            self.goto("battle")
            self.on_battle(self)
            if (self.party.console_serves and self.party.battle is None and self.party.started()
                    and all(m.stage == "battle" for m in self.party.lobby())):
                # Our Pokemon's first move; the recorded action named Water Gun for any Pokemon.
                move = next((m for m in pokemon.read(self.offer_pk8)["moves"] if m), 55)
                self.party.start_battle(self.clock, raid_battle.action(move))

    def _stage_battle(self, now):
        pass

    def tick(self, now=None):
        now = time.time() if now is None else now
        getattr(self, "_stage_" + self.stage)(now)
