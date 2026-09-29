"""The battle link buffer [src/battle_controllers.c]: an 8-byte header then the payload, built by
PrepareBufferDataTransferLink [:412] and read by Task_HandleCopyReceivedLinkBuffersData [:551].
Layout and the sync rule are in docs/frlg_link.md "The link buffer protocol"."""

HEADER = 8                      # LINK_BUFF_DATA [battle_controllers.c:409]

BUFFER_A = 0                    # a command from the master
BUFFER_B = 1                    # a reply to one
EXEC_CLEAR = 2                  # "this player has finished that battler's command"

MASTER_BATTLER = 0              # the console's mon
OUR_BATTLER = 1                 # ours

# Controller commands [include/battle_controllers.h:138].
(GETMONDATA, GETRAWMONDATA, SETMONDATA, SETRAWMONDATA, LOADMONSPRITE, SWITCHINANIM,
 RETURNMONTOBALL, DRAWTRAINERPIC, TRAINERSLIDE, TRAINERSLIDEBACK, FAINTANIMATION, PALETTEFADE,
 SUCCESSBALLTHROWANIM, BALLTHROWANIM, PAUSE, MOVEANIMATION, PRINTSTRING, PRINTSTRINGPLAYERONLY,
 CHOOSEACTION, UNKNOWNYESNOBOX, CHOOSEMOVE, OPENBAG, CHOOSEPOKEMON, CMD_23, HEALTHBARUPDATE,
 EXPUPDATE, STATUSICONUPDATE, STATUSANIMATION, STATUSXOR, DATATRANSFER, DMA3TRANSFER, PLAYBGM,
 CMD_32, TWORETURNVALUES, CHOSENMONRETURNVALUE, ONERETURNVALUE, ONERETURNVALUE_DUPLICATE,
 CLEARUNKVAR, SETUNKVAR, CLEARUNKFLAG, TOGGLEUNKFLAG, HITANIMATION, CANTSWITCH, PLAYSE,
 PLAYFANFARE, FAINTINGCRY, INTROSLIDE, INTROTRAINERBALLTHROW, DRAWPARTYSTATUSSUMMARY,
 HIDEPARTYSTATUSSUMMARY, ENDBOUNCE, SPRITEINVISIBILITY, BATTLEANIMATION, LINKSTANDBYMSG,
 RESETACTIONMOVESELECTION, ENDLINKBATTLE, TERMINATOR_NOP) = range(57)

NAMES = {
    GETMONDATA: "GETMONDATA", GETRAWMONDATA: "GETRAWMONDATA", SETMONDATA: "SETMONDATA",
    SETRAWMONDATA: "SETRAWMONDATA", LOADMONSPRITE: "LOADMONSPRITE", SWITCHINANIM: "SWITCHINANIM",
    RETURNMONTOBALL: "RETURNMONTOBALL", DRAWTRAINERPIC: "DRAWTRAINERPIC",
    TRAINERSLIDE: "TRAINERSLIDE", TRAINERSLIDEBACK: "TRAINERSLIDEBACK",
    FAINTANIMATION: "FAINTANIMATION", PALETTEFADE: "PALETTEFADE",
    SUCCESSBALLTHROWANIM: "SUCCESSBALLTHROWANIM", BALLTHROWANIM: "BALLTHROWANIM", PAUSE: "PAUSE",
    MOVEANIMATION: "MOVEANIMATION", PRINTSTRING: "PRINTSTRING",
    PRINTSTRINGPLAYERONLY: "PRINTSTRINGPLAYERONLY", CHOOSEACTION: "CHOOSEACTION",
    UNKNOWNYESNOBOX: "UNKNOWNYESNOBOX", CHOOSEMOVE: "CHOOSEMOVE", OPENBAG: "OPENBAG",
    CHOOSEPOKEMON: "CHOOSEPOKEMON", CMD_23: "CMD_23", HEALTHBARUPDATE: "HEALTHBARUPDATE",
    EXPUPDATE: "EXPUPDATE", STATUSICONUPDATE: "STATUSICONUPDATE",
    STATUSANIMATION: "STATUSANIMATION", STATUSXOR: "STATUSXOR", DATATRANSFER: "DATATRANSFER",
    DMA3TRANSFER: "DMA3TRANSFER", PLAYBGM: "PLAYBGM", CMD_32: "CMD_32",
    TWORETURNVALUES: "TWORETURNVALUES", CHOSENMONRETURNVALUE: "CHOSENMONRETURNVALUE",
    ONERETURNVALUE: "ONERETURNVALUE", ONERETURNVALUE_DUPLICATE: "ONERETURNVALUE_DUPLICATE",
    CLEARUNKVAR: "CLEARUNKVAR", SETUNKVAR: "SETUNKVAR", CLEARUNKFLAG: "CLEARUNKFLAG",
    TOGGLEUNKFLAG: "TOGGLEUNKFLAG", HITANIMATION: "HITANIMATION", CANTSWITCH: "CANTSWITCH",
    PLAYSE: "PLAYSE", PLAYFANFARE: "PLAYFANFARE", FAINTINGCRY: "FAINTINGCRY",
    INTROSLIDE: "INTROSLIDE", INTROTRAINERBALLTHROW: "INTROTRAINERBALLTHROW",
    DRAWPARTYSTATUSSUMMARY: "DRAWPARTYSTATUSSUMMARY",
    HIDEPARTYSTATUSSUMMARY: "HIDEPARTYSTATUSSUMMARY", ENDBOUNCE: "ENDBOUNCE",
    SPRITEINVISIBILITY: "SPRITEINVISIBILITY", BATTLEANIMATION: "BATTLEANIMATION",
    LINKSTANDBYMSG: "LINKSTANDBYMSG", RESETACTIONMOVESELECTION: "RESETACTIONMOVESELECTION",
    ENDLINKBATTLE: "ENDLINKBATTLE", TERMINATOR_NOP: "TERMINATOR_NOP",
}

# Commands that also want a BUFFER_B reply [battle_controller_player.c:110]. Trap: not EXPUPDATE; it
# replies only on a level-up [battle_controller_player.c:2513], and an unprompted answer reads back
# as a level-up decision.
NEEDS_REPLY = frozenset({GETMONDATA, CHOOSEACTION, CHOOSEMOVE, CHOOSEPOKEMON, OPENBAG,
                         GETRAWMONDATA})

# Actions for a CHOOSEACTION reply [include/battle.h:34].
B_ACTION_USE_MOVE = 0
B_ACTION_USE_ITEM = 1
B_ACTION_SWITCH = 2
B_ACTION_RUN = 3            # a forfeit in a link battle; allowed [battle_main.c:3239]

# GetMonData request ids we answer [include/constants/battle.h, REQUEST_*].
REQUEST_ALL_BATTLE = 0

# The ret8 CHOOSEMOVE replies use [battle_controller_player.c:342].
RET_CHOSEN_MOVE = 10


def aligned_size(size):
    """The size the header carries: `size - size % 4 + 4` [battle_controllers.c:417], always a
    whole word more, so a 4-byte payload is stored as 8."""
    return size - size % 4 + 4


def build(buffer_id, active_battler, payload, *, attacker=0, target=0, absent_flags=0,
          effect_battler=0):
    """One link buffer record, payload zero-padded to the aligned size."""
    payload = bytes(payload)
    size = aligned_size(len(payload))
    out = bytearray(HEADER + size)
    out[0] = buffer_id
    out[1] = active_battler
    out[2] = attacker
    out[3] = target
    out[4] = size & 0xFF
    out[5] = (size >> 8) & 0xFF
    out[6] = absent_flags
    out[7] = effect_battler
    out[HEADER:HEADER + len(payload)] = payload
    return bytes(out)


def parse(block):
    """-> a dict for one record; `payload` is the aligned span, `cmd` is payload[0]."""
    if len(block) < HEADER:
        raise ValueError(f"link buffer record is {len(block)} bytes, needs at least {HEADER}")
    size = block[4] | (block[5] << 8)
    if len(block) < HEADER + size:
        raise ValueError(f"link buffer record claims {size} payload bytes, has {len(block) - HEADER}")
    payload = block[HEADER:HEADER + size]
    return {
        "buffer_id": block[0],
        "active_battler": block[1],
        "attacker": block[2],
        "target": block[3],
        "size": size,
        "absent_flags": block[6],
        "effect_battler": block[7],
        "payload": payload,
        "cmd": payload[0] if payload else None,
    }


def ack(active_battler, multiplayer_id):
    """PlayerBufferExecCompleted [battle_controller_player.c:186]: a buffer_id 2 record clearing
    gBitTable[active_battler] << (id * 4). The reference sends size 4 for the one-byte id, so the
    record is 16 bytes on the wire; match it."""
    return build(EXEC_CLEAR, active_battler, bytes([multiplayer_id & 0xFF, 0, 0, 0]))


def data_transfer(active_battler, data):
    """A BUFFER_B reply carrying bytes [BtlController_EmitDataTransfer, battle_controllers.c:949].
    The payload is CONTROLLER_DATATRANSFER twice, the u16 size, then the data."""
    data = bytes(data)
    head = bytes([DATATRANSFER, DATATRANSFER, len(data) & 0xFF, (len(data) >> 8) & 0xFF])
    return build(BUFFER_B, active_battler, head + data)


def two_return_values(active_battler, ret8, ret16):
    """[BtlController_EmitTwoReturnValues, :1008]: a chosen action, or RET_CHOSEN_MOVE with
    ret16 = move slot | target << 8."""
    return build(BUFFER_B, active_battler,
                 bytes([TWORETURNVALUES, ret8 & 0xFF, ret16 & 0xFF, (ret16 >> 8) & 0xFF]))


def one_return_value(active_battler, ret16):
    """[BtlController_EmitOneReturnValue, :1030], the reply to OPENBAG."""
    return build(BUFFER_B, active_battler,
                 bytes([ONERETURNVALUE, ret16 & 0xFF, (ret16 >> 8) & 0xFF, 0]))


def chosen_mon_return_value(active_battler, party_id, party_order=b"\x00" * 3):
    """[BtlController_EmitChosenMonReturnValue, :1017]. The reference sends size 5, so only three
    order bytes travel."""
    order = bytes(party_order)[:3].ljust(3, b"\x00")
    return build(BUFFER_B, active_battler,
                 bytes([CHOSENMONRETURNVALUE, party_id & 0xFF]) + order)


def describe(rec):
    if rec["buffer_id"] == EXEC_CLEAR:
        return f"ack battler {rec['active_battler']} from player {rec['payload'][0]}"
    side = "A" if rec["buffer_id"] == BUFFER_A else "B"
    name = NAMES.get(rec["cmd"], f"0x{rec['cmd']:02x}" if rec["cmd"] is not None else "?")
    return f"buffer{side} battler {rec['active_battler']} {name} ({rec['size']} B)"
