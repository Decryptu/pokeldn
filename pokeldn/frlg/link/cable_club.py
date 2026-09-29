"""The cable-club colosseum entry [src/cable_club.c, src/union_room.c:1903]: the trade centre's
handshake, then one bare 28-byte LinkPlayer before CB2_InitBattle [cable_club.c:683].
docs/frlg_link.md, The cable-club colosseum."""

from pokeldn.frlg.link import linkplayer

# struct LinkPlayer, sent bare [cable_club.c:701]: never add the entry block's GameFreak magics.
LOCAL_SIZE = linkplayer.LINK_PLAYER_SIZE          # 28
# `size / 12 + (size % 12 != 0)` [Rfu_InitBlockSend, link_rfu_2.c:1349].
COUNT_LOCAL = 3

# Assigned locally on both sides [cable_club.c:736] and tested by TryReceiveLinkBattleData
# [battle_controllers.c:520]; the value in the record we send is never the one the battle reads.
LINKTYPE_BATTLE = 0x2211
LINKTYPE_SINGLE_BATTLE = 0x2233


def local_link_player_block(link_player, *, name_pad=0x00):
    """The 28 bytes of case 2; its trainerId is what the card counter records, once per id
    [cable_club.c:794, mystery_gift.c:630]."""
    return link_player.pack(name_pad=name_pad)


def read_local_link_player(data):
    """-> LinkPlayer; raises if the block is short."""
    if len(data) < LOCAL_SIZE:
        raise ValueError(f"cable-club LinkPlayer block is {len(data)} bytes, expected {LOCAL_SIZE}")
    return linkplayer.LinkPlayer.unpack(data[:LOCAL_SIZE])
