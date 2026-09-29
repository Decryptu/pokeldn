"""The Union Room battle [src/union_room_battle.c, src/battle_main.c, src/battle_controllers.c].

The host sends version signature 0x200 so the console elects itself master [battle_main.c:886] and
runs the battle; this is the non-master's controller. See docs/frlg_link.md "The link battle".
"""

from pokeldn.frlg.link import battle_link as bl
from pokeldn.frlg.save import battle_mon, mon as monmod

ACCEPT_BLOCK_SIZE = 0x20
ACCEPT = 0x51                   # ACTIVITY_ACCEPT | 0x40 [union_room_battle.c:143]
DECLINE = 0x52                  # ACTIVITY_DECLINE | 0x40

HEADER_SIZE = 31                # LinkBattlerHeader: 4 + sizeof(BattleEnigmaBerry) 0x1B, all u8
VERSION_NON_MASTER = 0x200      # below 0x201 and not 0x100: the console makes itself master
VERSION_FIRERED = 0x201         # what the game itself sends (lo=1, hi=2)

PARTY_BLOCK_COUNT = 3

# RFU block counts [Rfu_InitBlockSend, link_rfu_2.c:1349]. Selection block and header share a count;
# they are told apart by position in the sequence.
COUNT_ACCEPT = 3
COUNT_HEADER = 3


def accept_block(accepted=True):
    """The 0x20-byte selection block; the rest is zero [CB2_UnionRoomBattle case 3]."""
    out = bytearray(ACCEPT_BLOCK_SIZE)
    out[0] = ACCEPT if accepted else DECLINE
    return bytes(out)


def read_accept_block(data):
    """-> True for accept, False for decline."""
    if len(data) < 1:
        raise ValueError("empty selection block")
    if data[0] == ACCEPT:
        return True
    if data[0] == DECLINE:
        return False
    raise ValueError(f"selection block starts 0x{data[0]:02x}, expected 0x51 or 0x52")


def vs_screen_flags(count):
    """Two bits per party slot [BUFFER_PARTY_VS_SCREEN_STATUS, battle_main.c:718]: 1 healthy,
    2 egg or statused, 3 fainted, 0 an empty slot. Trap: 0 draws six empty balls on the console."""
    flags = 0
    for i in range(count):
        flags |= 1 << (i * 2)
    return flags


def battler_header(version=VERSION_NON_MASTER, vs_flags=None, party_count=2):
    """struct LinkBattlerHeader; the enigma berry tail stays zero."""
    vs_screen_flags_value = vs_screen_flags(party_count) if vs_flags is None else vs_flags
    out = bytearray(HEADER_SIZE)
    out[0] = version & 0xFF
    out[1] = (version >> 8) & 0xFF
    out[2] = vs_screen_flags_value & 0xFF
    out[3] = (vs_screen_flags_value >> 8) & 0xFF
    return bytes(out)


def party_blocks(mons, *, limit=2):
    """The three 200-byte blocks of state 3/7/11. The Union Room keeps two mons
    [union_room_battle.c:47]; the colosseum fights the whole party with limit=6."""
    if len(mons) > limit:
        raise ValueError(f"this battle sends at most {limit} mons a side")
    return monmod.party_blocks(monmod.build_player_party(mons))


class BattleController:
    """Our half of the link battle, as the non-master. Every BUFFER_A command is acked, for both
    battlers, or the master waits forever [battle_util.c:185-201]."""

    def __init__(self, mons, *, multiplayer_id=0, forfeit=True, move_slot=0, log=None):
        self.mons = list(mons)
        self.multiplayer_id = multiplayer_id
        self.forfeit = forfeit
        if not 0 <= move_slot < 4:
            raise ValueError("move slot must be 0..3")
        self.move_slot = move_slot
        self.log = log
        self.our_battler = bl.OUR_BATTLER
        self.active_index = 0       # gBattlerPartyIndexes[our battler]; slot 0 at battle start
        self.commands = []          # (battler, cmd) in arrival order, for the run classifier
        self.outcome = None         # set by ENDLINKBATTLE
        self.done = False

    def _info(self, msg):
        if self.log is not None:
            self.log(msg)

    def _mon_data(self, request_id, mon_to_check):
        """PlayerHandleGetMonData [battle_controller_player.c:1495]: mon_to_check 0 is the active
        mon, else a party bitmask whose answers are concatenated."""
        if request_id != bl.REQUEST_ALL_BATTLE:
            raise ValueError(f"GETMONDATA request {request_id} is not implemented; only "
                             f"REQUEST_ALL_BATTLE ({bl.REQUEST_ALL_BATTLE}) is sent at battle start")
        if mon_to_check == 0:
            indexes = [self.active_index]
        else:
            indexes = [i for i in range(6) if mon_to_check & (1 << i)]
        out = bytearray()
        for i in indexes:
            if i < len(self.mons):
                out += battle_mon.from_mon(self.mons[i])
            else:
                out += bytes(battle_mon.SIZE)
        return bytes(out)

    def feed(self, block):
        """One inbound link buffer block -> the blocks to send, in order."""
        rec = bl.parse(block)
        if rec["buffer_id"] != bl.BUFFER_A:
            return []
        battler, cmd = rec["active_battler"], rec["cmd"]
        self.commands.append((battler, cmd))
        if cmd == bl.SWITCHINANIM and battler == self.our_battler:
            # payload[1] is the incoming party slot [BtlController_EmitSwitchInAnim, :652], the only
            # record of which mon is active; CHOOSEPOKEMON after a faint needs it.
            self.active_index = rec["payload"][1]
            self._info(f"Union Room battle: our party slot {self.active_index} is now out.")
        out = []
        if battler == self.our_battler and cmd in bl.NEEDS_REPLY:
            reply = self._reply(rec)
            if reply is not None:
                out.append(reply)
        if cmd == bl.ENDLINKBATTLE:
            self.outcome = rec["payload"][1] if len(rec["payload"]) > 1 else None
            self.done = True
            self._info(f"Union Room battle: the console ended it, outcome {self.outcome}.")
        out.append(bl.ack(battler, self.multiplayer_id))
        return out

    def _reply(self, rec):
        battler, cmd, payload = rec["active_battler"], rec["cmd"], rec["payload"]
        if cmd == bl.GETMONDATA:
            data = self._mon_data(payload[1], payload[2])
            self._info(f"Union Room battle: sending our mon: {battle_mon.describe(data)}")
            return bl.data_transfer(battler, data)
        if cmd == bl.CHOOSEACTION:
            if self.forfeit:
                self._info("Union Room battle: choosing RUN, which forfeits a link battle.")
                return bl.two_return_values(battler, bl.B_ACTION_RUN, 0)
            return bl.two_return_values(battler, bl.B_ACTION_USE_MOVE, 0)
        if cmd == bl.CHOOSEMOVE:
            # low byte move slot, high byte target battler [battle_controller_player.c:342]
            return bl.two_return_values(battler, bl.RET_CHOSEN_MOVE,
                                        self.move_slot | (bl.MASTER_BATTLER << 8))
        if cmd == bl.CHOOSEPOKEMON:
            # The colosseum fights the whole party, so walk it [union_room_battle.c:47].
            slot = next((i for i in range(len(self.mons)) if i != self.active_index),
                        1 if self.active_index == 0 else 0)
            self._info(f"Union Room battle: sending out our party slot {slot}.")
            return bl.chosen_mon_return_value(battler, slot)
        if cmd == bl.OPENBAG:
            return bl.one_return_value(battler, 0)      # ITEM_NONE: we carry no bag
        return None
