"""Mystery Gift server script interpreter [decomp:src/mystery_gift_server.c]; we are link player 0.
run() advances until it blocks and publishes ``action`` as ("send", ident, payload, size),
("recv", ident) or ("done", server_msg_id); the caller acknowledges with on_sent()/on_received()."""

from pokeldn.frlg.gift import ereader_trainer, mg_script, wonder_news
from pokeldn.frlg.rom import buffer_script, builds, mystery_event
from pokeldn.frlg.save import readout
from pokeldn.frlg.text import charmap, easychat
from pokeldn.frlg.gift.mystery_gift import (
    MG_LINKID_CARD, MG_LINKID_CLIENT_SCRIPT, MG_LINKID_DYNAMIC_MSG,
    MG_LINKID_EREADER_TRAINER, MG_LINKID_GAME_DATA, MG_LINKID_NEWS, MG_LINKID_RAM_SCRIPT,
    MG_LINKID_READY_END, MG_LINKID_RESPONSE, MG_LINKID_STAMP,
)
from pokeldn.frlg.gift.wonder_card import WONDER_CARD_SIZE

# [decomp:include/mystery_gift_server.h:17]
SVR_RETURN = "SVR_RETURN"
SVR_SEND = "SVR_SEND"
SVR_RECV = "SVR_RECV"
SVR_GOTO = "SVR_GOTO"
SVR_GOTO_IF_EQ = "SVR_GOTO_IF_EQ"
SVR_COPY_GAME_DATA = "SVR_COPY_GAME_DATA"
SVR_CHECK_GAME_DATA = "SVR_CHECK_GAME_DATA"
SVR_CHECK_EXISTING_CARD = "SVR_CHECK_EXISTING_CARD"
SVR_READ_RESPONSE = "SVR_READ_RESPONSE"
SVR_LOAD_CARD = "SVR_LOAD_CARD"
SVR_LOAD_NEWS = "SVR_LOAD_NEWS"
SVR_LOAD_RAM_SCRIPT = "SVR_LOAD_RAM_SCRIPT"
SVR_LOAD_CLIENT_SCRIPT = "SVR_LOAD_CLIENT_SCRIPT"
SVR_LOAD_MSG = "SVR_LOAD_MSG"
SVR_CHECK_RALLY_CARD = "SVR_CHECK_RALLY_CARD"
SVR_CHECK_EXISTING_STAMPS = "SVR_CHECK_EXISTING_STAMPS"
SVR_LOAD_STAMP = "SVR_LOAD_STAMP"
SVR_LOAD_ACTIVATION = "SVR_LOAD_ACTIVATION"
SVR_LOAD_EREADER_TRAINER = "SVR_LOAD_EREADER_TRAINER"
SVR_LOAD_MEVENT = "SVR_LOAD_MEVENT"
SVR_CHECK_QUESTIONNAIRE = "SVR_CHECK_QUESTIONNAIRE"
SVR_GET_CARD_STAT = "SVR_GET_CARD_STAT"
SVR_LOAD_DENIED_MSG = "SVR_LOAD_DENIED_MSG"
SVR_READ_MEVENT_STATUS = "SVR_READ_MEVENT_STATUS"
SVR_LOAD_BUFFER_SCRIPT = "SVR_LOAD_BUFFER_SCRIPT"
SVR_LOAD_BUFFER_LEAD = "SVR_LOAD_BUFFER_LEAD"
SVR_READ_BUFFER_STATUS = "SVR_READ_BUFFER_STATUS"
SVR_LOAD_BUFFER_VERDICT_MSG = "SVR_LOAD_BUFFER_VERDICT_MSG"
SVR_READ_BUFFER_DUMP = "SVR_READ_BUFFER_DUMP"

# [decomp:include/mystery_gift_server.h:56]
SVR_MSG_NOTHING_SENT = 0
SVR_MSG_RECORD_UPLOADED = 1
SVR_MSG_CARD_SENT = 2
SVR_MSG_NEWS_SENT = 3
SVR_MSG_STAMP_SENT = 4
SVR_MSG_HAS_CARD = 5
SVR_MSG_HAS_STAMP = 6
SVR_MSG_HAS_NEWS = 7
SVR_MSG_NO_ROOM_STAMPS = 8
SVR_MSG_CLIENT_CANCELED = 9
SVR_MSG_CANT_SEND_GIFT_1 = 10
SVR_MSG_COMM_ERROR = 11
SVR_MSG_GIFT_SENT_1 = 13

SERVER_RESULT_NAMES = {
    SVR_MSG_NOTHING_SENT: "nothing sent",
    SVR_MSG_CARD_SENT: "Wonder Card sent",
    SVR_MSG_NEWS_SENT: "Wonder News sent",
    SVR_MSG_HAS_NEWS: "the console already had this news",
    SVR_MSG_STAMP_SENT: "stamp sent",
    SVR_MSG_HAS_CARD: "the console already had this card",
    SVR_MSG_HAS_STAMP: "the console already had this stamp",
    SVR_MSG_NO_ROOM_STAMPS: "the console's stamp card is full",
    SVR_MSG_CLIENT_CANCELED: "the player kept their existing card",
    SVR_MSG_CANT_SEND_GIFT_1: "the console's game data was rejected",
    SVR_MSG_COMM_ERROR: "communication error",
    SVR_MSG_GIFT_SENT_1: "gift sent",
}

# Native never sets ramScriptSize [decomp:src/mystery_gift_server.c:275]: the RAM script travels as
# a full 1024-byte message.
FULL_BUFFER = 0


# ctx->data[2] as the stock opcodes leave it; anything else came from our own setstatus.
MEVENT_STATUS_NAMES = {
    0: "untouched - no opcode set a status",
    mystery_event.STATUS_FAILED: "failed: setenigmaberry invalid, or a checksum/crc mismatch",
    mystery_event.STATUS_SUCCESS: "success",
    mystery_event.STATUS_INCOMPATIBLE: "incompatible, or givepokemon found a full party",
}


NUM_QUESTIONNAIRE_WORDS = 4     # [decomp:include/constants/global.h:68]

DEFAULT_DENIED_MESSAGE = charmap.encode("That is not the phrase.") + b"\xff"

# buffer_expect: the payload reads gSaveBlock2Ptr, the game data was assembled by the ROM, so a
# trainer id match proves the payload ran and read the real save.
BUFFER_EXPECT_TRAINER_ID = buffer_script.EXPECT_TRAINER_ID

# Window 1 of sMainWindows is 28x4 tiles, two lines [decomp:src/mystery_gift_menu.c:97,524]; the
# ROM's longest line is 31 characters [decomp:src/strings.c:1291]. A 47-character line wrapped
# around the window's pixel buffer on the console.
MAX_MESSAGE_LINES = 2
MAX_MESSAGE_LINE_CHARS = 31


def _encode_message(text, default):
    """A CLI_COPY_MSG payload, from a str, ready bytes, or the default. `\n` becomes 0xFE:
    charmap.encode drops characters it does not know, newline included."""
    if text is None:
        return default
    if isinstance(text, (bytes, bytearray)):
        encoded = bytes(text)
    else:
        lines = text.split("\n")
        if len(lines) > MAX_MESSAGE_LINES:
            raise MysteryGiftServerError(
                f"the console's message window holds {MAX_MESSAGE_LINES} lines, got {len(lines)}")
        for line in lines:
            if len(line) > MAX_MESSAGE_LINE_CHARS:
                raise MysteryGiftServerError(
                    f"line {line!r} is {len(line)} characters; the window fits about "
                    f"{MAX_MESSAGE_LINE_CHARS} and a longer one wraps around inside it")
        encoded = b"\xFE".join(charmap.encode(line) for line in lines) + b"\xff"
    if len(encoded) > mg_script.CLIENT_MAX_MSG_SIZE:
        raise MysteryGiftServerError(
            f"the message encodes to {len(encoded)} bytes; the console copies only "
            f"{mg_script.CLIENT_MAX_MSG_SIZE}")
    return encoded


DEFAULT_BUFFER_SUCCESS_MESSAGE = _encode_message(
    "The code ran and read your\nTRAINER ID correctly.", None)
DEFAULT_BUFFER_FAILURE_MESSAGE = _encode_message(
    "The code ran but read the\nwrong value.", None)


class MysteryGiftServerError(Exception):
    """The console sent something the server script cannot proceed from."""


# sServerScript_CantSend [decomp:src/mystery_gift_scripts.c:98]
_SCRIPT_CANT_SEND = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_CANT_ACCEPT),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_CANT_SEND_GIFT_1),
)

# Every distribution opens the same way [decomp:src/mystery_gift_scripts.c:174,:185]; named once so
# a gate can be spliced after it.
_GAME_DATA_PREFIX = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SEND_GAME_DATA),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_GAME_DATA),
    (SVR_COPY_GAME_DATA,),
    (SVR_CHECK_GAME_DATA,),
    (SVR_GOTO_IF_EQ, False, _SCRIPT_CANT_SEND),
)

# sServerScript_HasCard [decomp:src/mystery_gift_scripts.c:160]
_SCRIPT_HAS_CARD = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_HAD_CARD),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_HAS_CARD),
)

# gServerScript_ClientCanceledCard [decomp:src/union_room_message.c:569]; unlike the News cancel
# path it pushes a live message for the console to display.
_SCRIPT_CLIENT_CANCELED = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_DYNAMIC_ERROR),
    (SVR_SEND,),
    (SVR_LOAD_MSG, mg_script.TEXT_CANCELED_READING_CARD),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_CLIENT_CANCELED),
)

# sServerScript_HasNews [decomp:src/mystery_gift_scripts.c:119]
_SCRIPT_HAS_NEWS = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_HAD_NEWS),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_HAS_NEWS),
)

# sServerScript_SendNews [decomp:src/mystery_gift_scripts.c:126]. The response is the console's
# verdict: TRUE means it kept what it had, so only FALSE continues to success.
_SCRIPT_SEND_NEWS = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SAVE_NEWS),
    (SVR_SEND,),
    (SVR_LOAD_NEWS,),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_RESPONSE),
    (SVR_READ_RESPONSE,),
    (SVR_GOTO_IF_EQ, True, _SCRIPT_HAS_NEWS),
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_NEWS_RECEIVED),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_NEWS_SENT),
)

# gMysteryGiftServerScript_SendWonderNews [decomp:src/mystery_gift_scripts.c:174] minus
# SVR_COPY_SAVED_NEWS: the news comes from configuration.
SCRIPT_SEND_WONDER_NEWS = (
    *_GAME_DATA_PREFIX,
    (SVR_GOTO, _SCRIPT_SEND_NEWS),
)

# sServerScript_SendCard [decomp:src/mystery_gift_scripts.c:140]
_SCRIPT_SEND_CARD = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SAVE_CARD),
    (SVR_SEND,),
    (SVR_LOAD_CARD,),
    (SVR_SEND,),
    (SVR_LOAD_RAM_SCRIPT,),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_CARD_SENT),
)

_SCRIPT_HAS_STAMP = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_HAD_STAMP),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_HAS_STAMP),
)

_SCRIPT_NO_ROOM_STAMPS = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_NO_ROOM_STAMPS),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_NO_ROOM_STAMPS),
)

_SCRIPT_SEND_STAMP_ONLY = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SAVE_STAMP),
    (SVR_SEND,),
    (SVR_LOAD_STAMP,),
    (SVR_SEND,),
    (SVR_LOAD_ACTIVATION, False),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_STAMP_SENT),
)

_SCRIPT_INSTALL_CARD_AND_STAMP = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_INSTALL_CARD_AND_STAMP),
    (SVR_SEND,),
    (SVR_LOAD_CARD,),
    (SVR_SEND,),
    (SVR_LOAD_RAM_SCRIPT,),
    (SVR_SEND,),
    (SVR_LOAD_STAMP,),
    (SVR_SEND,),
    (SVR_LOAD_ACTIVATION, True),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_STAMP_SENT),
)

_SCRIPT_STAMP_TOSS_PROMPT = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_ASK_TOSS),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_RESPONSE),
    (SVR_READ_RESPONSE,),
    (SVR_GOTO_IF_EQ, False, _SCRIPT_INSTALL_CARD_AND_STAMP),
    (SVR_GOTO, _SCRIPT_CLIENT_CANCELED),
)

# MysteryGift_CheckStamps results. Native checks full before duplicate; this host checks duplicate
# first so a collected stamp is reported accurately on a full card.
STAMPS_FULL = 1
STAMP_NEW = 2
STAMP_ALREADY_PRESENT = 3

SCRIPT_SEND_STAMP_EVENT = (
    *_GAME_DATA_PREFIX,
    (SVR_CHECK_RALLY_CARD,),
    (SVR_GOTO_IF_EQ, mg_script.HAS_DIFF_CARD, _SCRIPT_STAMP_TOSS_PROMPT),
    (SVR_GOTO_IF_EQ, mg_script.HAS_NO_CARD, _SCRIPT_INSTALL_CARD_AND_STAMP),
    (SVR_CHECK_EXISTING_STAMPS,),
    (SVR_GOTO_IF_EQ, STAMP_ALREADY_PRESENT, _SCRIPT_HAS_STAMP),
    (SVR_GOTO_IF_EQ, STAMPS_FULL, _SCRIPT_NO_ROOM_STAMPS),
    (SVR_GOTO, _SCRIPT_SEND_STAMP_ONLY),
)

# The visiting trainer: no native script sends one over the wireless link
# [MysteryEventScript_VisitingTrainer, data/mystery_event_msg.s:113]; these are ours.
_SCRIPT_SEND_CARD_AND_TRAINER = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SAVE_CARD_AND_TRAINER),
    (SVR_SEND,),
    (SVR_LOAD_CARD,),
    (SVR_SEND,),
    (SVR_LOAD_RAM_SCRIPT,),
    (SVR_SEND,),
    (SVR_LOAD_EREADER_TRAINER,),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_GIFT_SENT_1),
)

# HAS_SAME_CARD: the console keeps its card and takes the trainer again.
_SCRIPT_SEND_TRAINER_ONLY = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SAVE_TRAINER),
    (SVR_SEND,),
    (SVR_LOAD_EREADER_TRAINER,),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_GIFT_SENT_1),
)

_SCRIPT_TOSS_PROMPT_TRAINER = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_ASK_TOSS),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_RESPONSE),
    (SVR_READ_RESPONSE,),
    (SVR_GOTO_IF_EQ, False, _SCRIPT_SEND_CARD_AND_TRAINER),
    (SVR_GOTO, _SCRIPT_CLIENT_CANCELED),
)

SCRIPT_SEND_VISITING_TRAINER = (
    *_GAME_DATA_PREFIX,
    (SVR_CHECK_EXISTING_CARD,),
    (SVR_GOTO_IF_EQ, mg_script.HAS_DIFF_CARD, _SCRIPT_TOSS_PROMPT_TRAINER),
    (SVR_GOTO_IF_EQ, mg_script.HAS_NO_CARD, _SCRIPT_SEND_CARD_AND_TRAINER),
    (SVR_GOTO, _SCRIPT_SEND_TRAINER_ONLY),
)

# The Mystery Event VM: no native script reaches it over the wireless link, so these are ours.
# MG_LINKID_RESPONSE after the mevent send carries the script's status back.
_SCRIPT_MEVENT_TAIL = (
    (SVR_RECV, MG_LINKID_RESPONSE),
    (SVR_READ_MEVENT_STATUS,),
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_MEVENT_DONE),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_CARD_SENT),
)

_SCRIPT_SEND_CARD_AND_MEVENT = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SAVE_CARD_AND_MEVENT),
    (SVR_SEND,),
    (SVR_LOAD_CARD,),
    (SVR_SEND,),
    (SVR_LOAD_RAM_SCRIPT,),
    (SVR_SEND,),
    (SVR_LOAD_MEVENT,),
    (SVR_SEND,),
    (SVR_GOTO, _SCRIPT_MEVENT_TAIL),
)

# HAS_SAME_CARD: the console keeps its card and only runs the event.
_SCRIPT_SEND_MEVENT_ONLY = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_RUN_MEVENT),
    (SVR_SEND,),
    (SVR_LOAD_MEVENT,),
    (SVR_SEND,),
    (SVR_GOTO, _SCRIPT_MEVENT_TAIL),
)

_SCRIPT_TOSS_PROMPT_MEVENT = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_ASK_TOSS),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_RESPONSE),
    (SVR_READ_RESPONSE,),
    (SVR_GOTO_IF_EQ, False, _SCRIPT_SEND_CARD_AND_MEVENT),
    (SVR_GOTO, _SCRIPT_CLIENT_CANCELED),
)

SCRIPT_SEND_MYSTERY_EVENT = (
    *_GAME_DATA_PREFIX,
    (SVR_CHECK_EXISTING_CARD,),
    (SVR_GOTO_IF_EQ, mg_script.HAS_DIFF_CARD, _SCRIPT_TOSS_PROMPT_MEVENT),
    (SVR_GOTO_IF_EQ, mg_script.HAS_NO_CARD, _SCRIPT_SEND_CARD_AND_MEVENT),
    (SVR_GOTO, _SCRIPT_SEND_MEVENT_ONLY),
)


# Native code: CLI_RUN_BUFFER_SCRIPT. No card and no toss prompt; the verdict is decided here from
# client->param and told to the console in a message we compose.
_SCRIPT_BUFFER_SUCCESS = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_BUFFER_SUCCESS),
    (SVR_SEND,),
    (SVR_LOAD_BUFFER_VERDICT_MSG,),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_GIFT_SENT_1),
)

# CLI_MSG_BUFFER_FAILURE exit: our message prints and the console returns to the menu, no save.
_SCRIPT_BUFFER_FAILURE = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_DYNAMIC_ERROR),
    (SVR_SEND,),
    (SVR_LOAD_BUFFER_VERDICT_MSG,),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_NOTHING_SENT),
)

# The payload repoints the console's outgoing message, so MG_LINKID_RESPONSE carries the region
# asked for.
SCRIPT_DUMP_MEMORY = (
    *_GAME_DATA_PREFIX,
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_DUMP_MEMORY),
    (SVR_SEND,),
    (SVR_LOAD_BUFFER_SCRIPT,),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_RESPONSE),
    (SVR_READ_BUFFER_DUMP,),
    (SVR_GOTO_IF_EQ, True, _SCRIPT_BUFFER_SUCCESS),
    (SVR_GOTO, _SCRIPT_BUFFER_FAILURE),
)


def script_dump_memory(blocks=1, leads=0):
    """-> the host script for a dump of `blocks` consecutive kilobytes in ONE session, after `leads`
    payloads sent and run first; one MG_LINKID_RESPONSE per block, which SVR_READ_BUFFER_DUMP
    appends."""
    if blocks == 1 and not leads:
        return SCRIPT_DUMP_MEMORY
    return (
        *_GAME_DATA_PREFIX,
        (SVR_LOAD_CLIENT_SCRIPT, mg_script.client_script_dump_memory(blocks, leads)),
        (SVR_SEND,),
        *[step for index in range(leads)
          for step in ((SVR_LOAD_BUFFER_LEAD, index), (SVR_SEND,))],
        (SVR_LOAD_BUFFER_SCRIPT,),
        (SVR_SEND,),
        *[step for _ in range(blocks)
          for step in ((SVR_RECV, MG_LINKID_RESPONSE), (SVR_READ_BUFFER_DUMP,))],
        (SVR_GOTO_IF_EQ, True, _SCRIPT_BUFFER_SUCCESS),
        (SVR_GOTO, _SCRIPT_BUFFER_FAILURE),
    )

SCRIPT_RUN_BUFFER_SCRIPT = (
    *_GAME_DATA_PREFIX,
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_RUN_BUFFER),
    (SVR_SEND,),
    (SVR_LOAD_BUFFER_SCRIPT,),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_RESPONSE),
    (SVR_READ_BUFFER_STATUS,),
    (SVR_GOTO_IF_EQ, True, _SCRIPT_BUFFER_SUCCESS),
    (SVR_GOTO, _SCRIPT_BUFFER_FAILURE),
)


def script_run_buffer_script(leads=0):
    """-> SCRIPT_RUN_BUFFER_SCRIPT with `leads` payloads sent and run first, in one session (a
    save-write before install-kept); the verdict is the last payload's answer."""
    if not leads:
        return SCRIPT_RUN_BUFFER_SCRIPT
    return (
        *_GAME_DATA_PREFIX,
        (SVR_LOAD_CLIENT_SCRIPT, mg_script.client_script_run_buffer(leads)),
        (SVR_SEND,),
        *[step for index in range(leads)
          for step in ((SVR_LOAD_BUFFER_LEAD, index), (SVR_SEND,))],
        (SVR_LOAD_BUFFER_SCRIPT,),
        (SVR_SEND,),
        (SVR_RECV, MG_LINKID_RESPONSE),
        (SVR_READ_BUFFER_STATUS,),
        (SVR_GOTO_IF_EQ, True, _SCRIPT_BUFFER_SUCCESS),
        (SVR_GOTO, _SCRIPT_BUFFER_FAILURE),
    )


# sServerScript_TossPrompt [decomp:src/mystery_gift_scripts.c:151]
_SCRIPT_TOSS_PROMPT = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_ASK_TOSS),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_RESPONSE),
    (SVR_READ_RESPONSE,),
    (SVR_GOTO_IF_EQ, False, _SCRIPT_SEND_CARD),
    (SVR_GOTO, _SCRIPT_CLIENT_CANCELED),
)

# gMysteryGiftServerScript_SendWonderCard [decomp:src/mystery_gift_scripts.c:185] minus its
# SVR_COPY_SAVED_*; DisableWonderCardSending is deliberately not applied.
SCRIPT_SEND_WONDER_CARD = (
    *_GAME_DATA_PREFIX,
    (SVR_CHECK_EXISTING_CARD,),
    (SVR_GOTO_IF_EQ, mg_script.HAS_DIFF_CARD, _SCRIPT_TOSS_PROMPT),
    (SVR_GOTO_IF_EQ, mg_script.HAS_NO_CARD, _SCRIPT_SEND_CARD),
    (SVR_GOTO, _SCRIPT_HAS_CARD),
)


# Questionnaire gate: all four Poke Mart words, exactly [MysteryGift_DoesQuestionnaireMatch,
# decomp:src/mystery_gift.c:422]. No native script uses it. The ids are per-language slots: read a
# French phrase off a real console first [easychat_french.py].
_SCRIPT_QUESTIONNAIRE_DENIED = (
    (SVR_LOAD_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_DYNAMIC_ERROR),
    (SVR_SEND,),
    (SVR_LOAD_DENIED_MSG,),
    (SVR_SEND,),
    (SVR_RECV, MG_LINKID_READY_END),
    (SVR_RETURN, SVR_MSG_NOTHING_SENT),
)


def gate_on_questionnaire(script):
    """Splice a questionnaire check after the game-data prefix."""
    if tuple(script[:len(_GAME_DATA_PREFIX)]) != _GAME_DATA_PREFIX:
        raise MysteryGiftServerError(
            "only a script that opens with the standard game-data prefix can be gated")
    return (_GAME_DATA_PREFIX
            + ((SVR_CHECK_QUESTIONNAIRE,),
               (SVR_GOTO_IF_EQ, False, _SCRIPT_QUESTIONNAIRE_DENIED))
            + tuple(script[len(_GAME_DATA_PREFIX):]))


class MysteryGiftServer:
    # The console saves only sizeof(RamScriptData.script) bytes of the 1024-byte message
    # [decomp:src/script.c:578]; a longer delivery script is truncated mid-bytecode.
    MAX_RAM_SCRIPT_SIZE = 995

    def __init__(self, card=None, ram_script=None, *, news=None, stamp=None,
                 activation_script=None, install_activation_script=None, trainer=None,
                 mevent=None, buffer_code=None, buffer_lead=(), buffer_expect=None,
                 buffer_dump_size=None,
                 buffer_dump_blocks=1, buffer_dump_address=0, buffer_dump_addresses=(),
                 buffer_decode=None, buffer_reference=None,
                 buffer_success_message=None, buffer_failure_message=None,
                 questionnaire=None, denied_message=None, expect_console=None,
                 script=None, per_build=None, log=lambda *a: None):
        self.expect_console = None if expect_console is None else str(expect_console).lower()
        if self.expect_console not in (None, "firered", "leafgreen"):
            raise MysteryGiftServerError(
                f"expect_console is 'firered' or 'leafgreen', got {expect_console!r}")
        self.console_mismatch = None
        self.news = None if news is None else bytes(news)
        if self.news is not None:
            if card is not None or ram_script is not None:
                raise MysteryGiftServerError(
                    "a Wonder News session carries no Wonder Card and no RAM script")
            if len(self.news) not in (wonder_news.WONDER_NEWS_SIZE, wonder_news.JAPANESE_WONDER_NEWS_SIZE):
                raise MysteryGiftServerError(
                    f"Wonder News must be exactly 224 or {wonder_news.WONDER_NEWS_SIZE} bytes, "
                    f"got {len(self.news)}")
            if not wonder_news.validate(self.news):
                raise MysteryGiftServerError(
                    "news id 0 fails ValidateWonderNews; the console would keep nothing")
        elif buffer_code is None and (card is None or ram_script is None):
            raise MysteryGiftServerError(
                "a Mystery Gift session needs a Wonder Card and RAM script, or news, or a "
                "buffer script")
        self.card = None if card is None else bytes(card)
        self.ram_script = None if ram_script is None else bytes(ram_script)
        if self.news is None and buffer_code is None:
            if len(self.ram_script) > self.MAX_RAM_SCRIPT_SIZE:
                raise MysteryGiftServerError(
                    f"delivery RAM script is {len(self.ram_script)} bytes; the console "
                    f"only saves the first {self.MAX_RAM_SCRIPT_SIZE}")
            if len(self.card) not in (WONDER_CARD_SIZE, 164):
                raise MysteryGiftServerError(
                    f"Wonder Card must be exactly 164 or {WONDER_CARD_SIZE} bytes, got {len(self.card)}")
        self.stamp = None if stamp is None else bytes(stamp)
        self.activation_script = (None if activation_script is None
                                  else bytes(activation_script))
        self.install_activation_script = (
            None if install_activation_script is None
            else bytes(install_activation_script))
        extras = (self.stamp, self.activation_script, self.install_activation_script)
        if any(value is not None for value in extras):
            if any(value is None for value in extras):
                raise MysteryGiftServerError(
                    "stamp flow requires a stamp and both activation scripts")
            if len(self.stamp) != 4:
                raise MysteryGiftServerError("stamp must be exactly four bytes")
        self.trainer = None if trainer is None else bytes(trainer)
        if self.trainer is not None:
            if len(self.trainer) != ereader_trainer.TRAINER_SIZE:
                raise MysteryGiftServerError(
                    f"a visiting trainer is {ereader_trainer.TRAINER_SIZE} bytes, "
                    f"got {len(self.trainer)}")
            if not ereader_trainer.validate(self.trainer):
                raise MysteryGiftServerError(
                    "the visiting trainer fails ValidateEReaderTrainer; the console would "
                    "silently clear it")
            if self.stamp is not None:
                raise MysteryGiftServerError(
                    "a stamp rally and a visiting trainer cannot share one session")
        if self.news is not None and (self.stamp is not None or self.trainer is not None):
            raise MysteryGiftServerError(
                "Wonder News cannot share a session with a stamp rally or a visiting trainer")
        self.mevent = None if mevent is None else bytes(mevent)
        if self.mevent is not None:
            if len(self.mevent) > mystery_event.MAX_SCRIPT_SIZE:
                raise MysteryGiftServerError(
                    f"Mystery Event script is {len(self.mevent)} bytes; the console's receive "
                    f"buffer is {mystery_event.MAX_SCRIPT_SIZE}")
            if not mystery_event.decode(self.mevent):
                raise MysteryGiftServerError("Mystery Event script is empty")
            if mystery_event.decode(self.mevent)[-1][0] not in mystery_event.TERMINAL_OPCODES:
                raise MysteryGiftServerError(
                    "Mystery Event script has no terminal command; the console would carry on "
                    "decoding the rest of its receive buffer")
            if self.news is not None or self.stamp is not None or self.trainer is not None:
                raise MysteryGiftServerError(
                    "a Mystery Event script cannot share a session with news, a stamp rally or a "
                    "visiting trainer")
        # A CLI_RUN_BUFFER_SCRIPT payload [buffer_script.py] shares a session with nothing else.
        self.buffer_code = None if buffer_code is None else bytes(buffer_code)
        if self.buffer_code is not None:
            buffer_script.validate(self.buffer_code)
            if any(other is not None for other in
                   (self.card, self.news, self.stamp, self.trainer, self.mevent)):
                raise MysteryGiftServerError(
                    "a buffer script runs on its own: no card, news, stamp rally, visiting "
                    "trainer or Mystery Event script in the same session")
        # Payloads run before buffer_code in the same session; their answers are not read.
        self.buffer_lead = tuple(bytes(code) for code in buffer_lead)
        for code in self.buffer_lead:
            buffer_script.validate(code)
        if self.buffer_lead and self.buffer_code is None:
            raise MysteryGiftServerError("payloads run ahead of the last one, and there is none")
        self.buffer_dump_size = None if buffer_dump_size is None else int(buffer_dump_size)
        # Only memory-dump-multi uses these; every other payload answers once.
        self.buffer_dump_blocks = int(buffer_dump_blocks)
        self.buffer_dump_address = int(buffer_dump_address)
        # memory-dump-scatter: a block's address is the table's entry, not `first + n * size`.
        self.buffer_dump_addresses = tuple(int(a) for a in buffer_dump_addresses)
        if not 1 <= self.buffer_dump_blocks <= mg_script.MAX_DUMP_BLOCKS:
            raise MysteryGiftServerError(
                f"a session carries 1..{mg_script.MAX_DUMP_BLOCKS} blocks, got "
                f"{self.buffer_dump_blocks}")
        if self.buffer_dump_size is not None:
            if self.buffer_code is None:
                raise MysteryGiftServerError(
                    "a memory dump needs the payload that repoints the send")
            if not 0 < self.buffer_dump_size <= buffer_script.MAX_BUFFER_SCRIPT_SIZE:
                raise MysteryGiftServerError(
                    f"a dump is 1..{buffer_script.MAX_BUFFER_SCRIPT_SIZE} bytes "
                    f"(MG_LINK_BUFFER_SIZE), got {self.buffer_dump_size}")
        self.buffer_decode = buffer_decode
        if self.buffer_decode == buffer_script.MEMORY_SCAN \
                and self.buffer_dump_size != buffer_script.SCAN_ANSWER_SIZE:
            raise MysteryGiftServerError(
                f"a memory scan answers with exactly {buffer_script.SCAN_ANSWER_SIZE} bytes, "
                f"got {self.buffer_dump_size}")
        if self.buffer_decode == buffer_script.ROM_CHECKSUM \
                and self.buffer_dump_size != buffer_script.ROM_CHECKSUM_ANSWER_SIZE:
            raise MysteryGiftServerError(
                f"a rom checksum answers with exactly {buffer_script.ROM_CHECKSUM_ANSWER_SIZE} "
                f"bytes, got {self.buffer_dump_size}")
        # rom-checksum: the ROM image its sums are compared with, read when the answer lands.
        self.buffer_reference = buffer_reference
        if self.buffer_decode == buffer_script.STRING_GATHER \
                and self.buffer_dump_size != buffer_script.GATHER_ANSWER_SIZE:
            raise MysteryGiftServerError(
                f"a string gather answers with exactly {buffer_script.GATHER_ANSWER_SIZE} bytes, "
                f"got {self.buffer_dump_size}")
        if self.buffer_decode == buffer_script.CREATE_MON \
                and self.buffer_dump_size != buffer_script.CREATE_MON_ANSWER_SIZE:
            raise MysteryGiftServerError(
                f"create-mon answers with exactly {buffer_script.CREATE_MON_ANSWER_SIZE} bytes, "
                f"got {self.buffer_dump_size}")
        if self.buffer_decode == buffer_script.CALL \
                and self.buffer_dump_size != buffer_script.CALL_ANSWER_SIZE:
            raise MysteryGiftServerError(
                f"a call answers with exactly {buffer_script.CALL_ANSWER_SIZE} bytes, "
                f"got {self.buffer_dump_size}")
        if self.buffer_decode == buffer_script.RNG_TRACE:
            asked = buffer_script.trace_parameters(self.buffer_code)
            if self.buffer_dump_size != buffer_script.trace_answer_size(asked["samples"]):
                raise MysteryGiftServerError(
                    f"a trace of {asked['samples']} samples answers with "
                    f"{buffer_script.trace_answer_size(asked['samples'])} bytes, "
                    f"got {self.buffer_dump_size}")
        self.buffer_expect = buffer_expect
        if not (buffer_expect is None or buffer_expect == BUFFER_EXPECT_TRAINER_ID
                or isinstance(buffer_expect, int)):
            raise MysteryGiftServerError(
                f"buffer_expect is a u32, {BUFFER_EXPECT_TRAINER_ID!r} or None, "
                f"got {buffer_expect!r}")
        self.buffer_success_message = _encode_message(
            buffer_success_message, DEFAULT_BUFFER_SUCCESS_MESSAGE)
        self.buffer_failure_message = _encode_message(
            buffer_failure_message, DEFAULT_BUFFER_FAILURE_MESSAGE)
        self.questionnaire = None if questionnaire is None else tuple(
            int(word) & 0xFFFF for word in questionnaire)
        if self.questionnaire is not None and len(self.questionnaire) != NUM_QUESTIONNAIRE_WORDS:
            raise MysteryGiftServerError(
                f"a questionnaire phrase is exactly {NUM_QUESTIONNAIRE_WORDS} Easy Chat words, "
                f"got {len(self.questionnaire)}")
        # A refusal message wraps inside the window too.
        self.denied_message = _encode_message(denied_message, DEFAULT_DENIED_MESSAGE)
        self.questionnaire_matched = None
        self.is_mevent_distribution = self.mevent is not None
        self.mevent_status = None
        self.is_buffer_distribution = self.buffer_code is not None
        self.buffer_status = None
        self.buffer_matched = None
        self.buffer_dump = None
        # One entry per block that arrived.
        self.buffer_blocks = []
        self.is_stamp_distribution = self.stamp is not None
        self.is_trainer_distribution = self.trainer is not None
        self.is_news_distribution = self.news is not None
        self.log = log
        self.info = getattr(log, "info", log)
        if script is not None:
            self.script = script
        elif self.is_news_distribution:
            self.script = SCRIPT_SEND_WONDER_NEWS
        elif self.is_stamp_distribution:
            self.script = SCRIPT_SEND_STAMP_EVENT
        elif self.is_trainer_distribution:
            self.script = SCRIPT_SEND_VISITING_TRAINER
        elif self.is_mevent_distribution:
            self.script = SCRIPT_SEND_MYSTERY_EVENT
        elif self.is_buffer_distribution:
            self.script = (script_dump_memory(self.buffer_dump_blocks, len(self.buffer_lead))
                           if self.buffer_dump_size is not None
                           else script_run_buffer_script(len(self.buffer_lead)))
        else:
            self.script = SCRIPT_SEND_WONDER_CARD
        if self.questionnaire is not None and script is None:
            self.script = gate_on_questionnaire(self.script)
        # {game code: server keywords, or why it could not be built}, chosen at SVR_COPY_GAME_DATA
        # before anything build-dependent is sent [builds.py]. None: any console.
        self.build = None
        self.build_refused = None
        self._build_servers = None
        if per_build is not None:
            self._build_servers = {}
            for code, chosen in dict(per_build).items():
                if isinstance(chosen, str):
                    self._build_servers[str(code)] = chosen
                    continue
                other = MysteryGiftServer(**chosen, script=script)
                if other.script != self.script:
                    raise MysteryGiftServerError(
                        f"the {code} payload runs another server script; one session is one kind "
                        "of payload")
                self._build_servers[str(code)] = other
        self.cmdidx = 0
        self.param = None
        self.action = None
        self.result = None
        self.game_data = None
        self.messages_sent = 0
        self.messages_received = 0
        self.trace = []

        self._loaded = None
        self._received = b""

    @property
    def done(self):
        return self.action is not None and self.action[0] == "done"

    @property
    def card_flag_id(self):
        if self.card is None:
            raise MysteryGiftServerError("this session carries no Wonder Card")
        return int.from_bytes(self.card[0:2], "little")

    def run(self):
        while self.action is None:
            self._step()
        return self.action

    def on_sent(self):
        if self.action is None or self.action[0] != "send":
            raise MysteryGiftServerError("on_sent called with no send in flight")
        self.messages_sent += 1
        self.action = None
        self._loaded = None

    def on_received(self, ident, payload):
        if self.action is None or self.action[0] != "recv":
            raise MysteryGiftServerError("on_received called with no recv in flight")
        expected = self.action[1]
        if ident != expected:
            raise MysteryGiftServerError(
                f"expected ident {expected}, console sent {ident}")
        self.messages_received += 1
        self._received = bytes(payload)
        self.action = None

    def _step(self):
        if self.cmdidx >= len(self.script):
            raise MysteryGiftServerError("server script ran off the end without SVR_RETURN")
        command = self.script[self.cmdidx]
        self.cmdidx += 1
        instr, args = command[0], command[1:]
        handler = getattr(self, "_do_" + instr.lower(), None)
        if handler is None:
            raise MysteryGiftServerError(f"unimplemented server opcode {instr}")
        self.trace.append(instr)
        handler(*args)

    def _goto(self, script):
        self.script = script
        self.cmdidx = 0

    def _do_svr_return(self, message_id):
        self.result = message_id
        self.action = ("done", message_id)
        self.info("Mystery Gift server finished: "
                  + SERVER_RESULT_NAMES.get(message_id, f"result {message_id}"))

    def _do_svr_send(self):
        if self._loaded is None:
            raise MysteryGiftServerError("SVR_SEND with no message loaded")
        self.action = ("send",) + self._loaded

    def _do_svr_recv(self, ident):
        self.action = ("recv", ident)

    def _do_svr_goto(self, script):
        self._goto(script)

    def _do_svr_goto_if_eq(self, value, script):
        if self.param == value:
            self._goto(script)

    def _do_svr_copy_game_data(self):
        self.game_data = mg_script.parse_link_game_data(self._received)
        self.info("Console identified itself: " + self.game_data.describe())
        self._check_expected_console()
        self._select_build()
        for line in self.game_data.describe_extras():
            self.info(line)

    def _check_expected_console(self):
        """Refuse a run aimed at the other cartridge, before anything is sent."""
        if self.expect_console is None or self.game_data is None:
            return
        got = self.game_data.version_name.lower()
        if got == self.expect_console:
            return
        self.console_mismatch = (self.expect_console, got)
        raise MysteryGiftServerError(
            f"THIS RUN IS FOR {self.expect_console.upper()} AND THE CONSOLE THAT JOINED IS "
            f"{got.upper()}. Nothing was sent. Put the other cartridge on the Mystery Gift "
            "search screen and launch again, or drop --expect-console if the run does not care.")

    BUILD_FIELDS = ("card", "ram_script", "news", "stamp", "activation_script",
                    "install_activation_script", "trainer", "mevent", "buffer_code", "buffer_lead",
                    "buffer_expect", "buffer_dump_size", "buffer_dump_blocks",
                    "buffer_dump_address", "buffer_dump_addresses", "buffer_decode",
                    "buffer_reference")

    def _select_build(self):
        """Take the payload built for the console's own game code, before anything is sent:
        another build's addresses land on other variables [builds.py]."""
        if self._build_servers is None:
            return
        raw = bytes(self.game_data.game_code)
        code = raw.decode("ascii", "replace")
        chosen = self._build_servers.get(code)
        if not isinstance(chosen, MysteryGiftServer):
            self.build_refused = code
            why = (chosen if isinstance(chosen, str) else
                   f"this run was built for {', '.join(sorted(self._build_servers))}")
            raise MysteryGiftServerError(
                f"THE CONSOLE IS {code!r} AND NOTHING WAS SENT: {why}. The payload names "
                "cartridge addresses, and another build's land on other variables.")
        for name in self.BUILD_FIELDS:
            setattr(self, name, getattr(chosen, name))
        self.build = builds.for_game_code(raw)
        self.info(f"Console build {code} ({self.build.name}): sending the bytes built for it.")

    def _do_svr_check_game_data(self):
        self.param = mg_script.validate_link_game_data(self.game_data)
        if not self.param:
            self.info("Console game data failed MysteryGift_ValidateLinkGameData; "
                      "declining to send the card.")

    def _do_svr_check_existing_card(self):
        self.param = mg_script.compare_card_flags(self.card_flag_id, self.game_data)
        self.trace.append(("existing_card", self.param))

    def _do_svr_check_rally_card(self):
        expected_icon = int.from_bytes(self.card[2:4], "little")
        if not self.game_data.has_card:
            self.param = mg_script.HAS_NO_CARD
        elif (self.game_data.flag_id == self.card_flag_id
              and self.game_data.max_stamps == self.card[9]
              and self.game_data.metadata_icon_species
              == expected_icon):
            self.param = mg_script.HAS_SAME_CARD
        else:
            self.param = mg_script.HAS_DIFF_CARD
        self.trace.append(("rally_card", self.param))
        result = {
            mg_script.HAS_NO_CARD: "no card",
            mg_script.HAS_SAME_CARD: "matching rally",
            mg_script.HAS_DIFF_CARD: "different card",
        }[self.param]
        self.info(
            "Rally card check: console "
            f"flagId={self.game_data.flag_id}, maxStamps={self.game_data.max_stamps}, "
            f"metadataIcon={self.game_data.metadata_icon_species}, "
            f"stamps={self.game_data.stamps}; expected flagId={self.card_flag_id}, "
            f"maxStamps={self.card[9]}, metadataIcon={expected_icon} -> {result}.")

    def _do_svr_check_existing_stamps(self):
        species = int.from_bytes(self.stamp[0:2], "little")
        stamp_id = int.from_bytes(self.stamp[2:4], "little")
        slots = range(min(self.game_data.max_stamps, len(self.game_data.stamp_ids)))
        if any(self.game_data.stamp_species[i] == species
               or self.game_data.stamp_ids[i] == stamp_id for i in slots):
            self.param = STAMP_ALREADY_PRESENT
        elif not any(self.game_data.stamp_species[i] == 0
                     and self.game_data.stamp_ids[i] == 0 for i in slots):
            self.param = STAMPS_FULL
        else:
            self.param = STAMP_NEW
        self.trace.append(("existing_stamps", self.param))

    def _do_svr_read_response(self):
        # The raw u32 [decomp:src/mystery_gift_server.c:193]; TRUE means the player kept the old
        # card, so FALSE gifts.
        self.param = int.from_bytes(self._received[:4], "little")

    def _do_svr_load_client_script(self, script):
        self._loaded = (MG_LINKID_CLIENT_SCRIPT, script, len(script))

    def _do_svr_load_news(self):
        self._loaded = (MG_LINKID_NEWS, self.news, len(self.news))

    def _do_svr_load_card(self):
        self._loaded = (MG_LINKID_CARD, self.card, len(self.card))

    def _do_svr_load_ram_script(self):
        self._loaded = (MG_LINKID_RAM_SCRIPT, self.ram_script, FULL_BUFFER)

    def _do_svr_load_stamp(self):
        self._loaded = (MG_LINKID_STAMP, self.stamp, len(self.stamp))

    def _do_svr_load_activation(self, install):
        payload = (self.install_activation_script if install
                   else self.activation_script)
        self._loaded = (MG_LINKID_RAM_SCRIPT, payload, len(payload))

    def _do_svr_load_ereader_trainer(self):
        self._loaded = (MG_LINKID_EREADER_TRAINER, self.trainer, len(self.trainer))

    def _do_svr_check_questionnaire(self):
        """Port of MysteryGift_DoesQuestionnaireMatch [decomp:src/mystery_gift.c:422]: all four
        word ids, exactly, in order."""
        typed = tuple(self.game_data.questionnaire_words)
        self.param = typed == self.questionnaire
        self.trace.append(("questionnaire", self.param))
        self.questionnaire_matched = bool(self.param)
        self.info("Questionnaire gate: console typed "
                  + easychat.describe_words(typed) + "; we require "
                  + easychat.describe_words(self.questionnaire)
                  + (" -> MATCH" if self.param else " -> no match, declining the gift"))

    def _do_svr_get_card_stat(self, stat):
        """MysteryGift_GetCardStatFromLinkData [decomp:src/mystery_gift_server.c:200]: a counter the
        console keeps for the card it holds. Never used by a native send script."""
        self.param = mg_script.card_stat(self.game_data, stat)
        self.trace.append(("card_stat", stat, self.param))
        self.info(f"Wonder Card stat {mg_script.CARD_STAT_NAMES.get(stat, stat)}: {self.param}")

    def _do_svr_load_denied_msg(self):
        self._loaded = (MG_LINKID_DYNAMIC_MSG, self.denied_message, len(self.denied_message))

    def _do_svr_load_mevent(self):
        self._loaded = (MG_LINKID_RAM_SCRIPT, self.mevent, len(self.mevent))
        self.info("Mystery Event script: " + mystery_event.describe(self.mevent))

    def _do_svr_read_mevent_status(self):
        # ctx->data[2] as MEventScript_Run left it, relayed by CLI_LOAD_TOSS_RESPONSE.
        self.mevent_status = int.from_bytes(self._received[:4], "little")
        self.param = self.mevent_status
        self.trace.append(("mevent_status", self.mevent_status))
        self.info(f"Mystery Event script status: {self.mevent_status} "
                  f"({MEVENT_STATUS_NAMES.get(self.mevent_status, 'set by our own setstatus')})")

    def _do_svr_load_buffer_lead(self, index):
        code = self.buffer_lead[index]
        self._loaded = (MG_LINKID_RAM_SCRIPT, code, len(code))
        self.info(f"buffer script {index + 1} of {len(self.buffer_lead) + 1} (native ARM code): "
                  + buffer_script.describe(code))

    def _do_svr_load_buffer_script(self):
        self._loaded = (MG_LINKID_RAM_SCRIPT, self.buffer_code, len(self.buffer_code))
        self.info("buffer script (native ARM code): "
                  + buffer_script.describe(self.buffer_code))

    def _do_svr_read_buffer_status(self):
        """Read what the payload left in client->param and decide the verdict. With
        buffer_expect=None any answer counts: the payload returned 1 to get here."""
        self.buffer_status = int.from_bytes(self._received[:4], "little")
        refusal = buffer_script.flash_refusal(self.buffer_status)
        if refusal and buffer_script.describe(self.buffer_code).startswith(
                (buffer_script.FLASH_WRITE, buffer_script.FLASH_PATCH)):
            self.info(f"Buffer script status: 0x{self.buffer_status:08X}, {refusal}")
        expected, mask, why = self._expected_buffer_status()
        installer = buffer_script.describe(self.buffer_code).startswith(
            (buffer_script.INSTALL_KEPT, buffer_script.INSTALL_RESIDENT))
        if expected is None and installer and self.buffer_status == buffer_script.INSTALL_REFUSED:
            # Nothing installed: a kept blob that did not sum, or no handler to chain to. The
            # failure exit does not save [mystery_gift_menu.c:1379].
            self.buffer_matched = False
            self.info(f"Buffer script status: 0x{self.buffer_status:08X} - nothing was installed")
        elif expected is None:
            self.buffer_matched = True
            self.info(f"Buffer script status: 0x{self.buffer_status:08X} "
                      f"({self.buffer_status}) - the payload returned 1 and answered")
        else:
            self.buffer_matched = (self.buffer_status & mask) == (expected & mask)
            verdict = "MATCHES" if self.buffer_matched else "DOES NOT MATCH"
            self.info(f"Buffer script status: 0x{self.buffer_status:08X} {verdict} "
                      f"0x{expected:08X} ({why})")
            if self.buffer_expect == BUFFER_EXPECT_TRAINER_ID:
                # playerTrainerId: TID low half, SID high half. The SID travels in no link message.
                self.info(f"  Trainer ID {self.buffer_status & 0xFFFF}, "
                          f"Secret ID {self.buffer_status >> 16}")
        self.param = self.buffer_matched
        self.trace.append(("buffer_status", self.buffer_status, self.buffer_matched))

    def _expected_buffer_status(self):
        """(expected, comparison mask, what the expectation is) for the configured oracle."""
        if self.buffer_expect is None:
            return None, 0xFFFFFFFF, "no expectation"
        if self.buffer_expect != BUFFER_EXPECT_TRAINER_ID:
            return int(self.buffer_expect) & 0xFFFFFFFF, 0xFFFFFFFF, "the value we asked for"
        if self.game_data is None:
            raise MysteryGiftServerError(
                "buffer_expect=trainer-id needs the console's game data, which this script "
                "never read")
        expected = self.game_data.trainer_id & 0xFFFFFFFF
        if self.game_data.trainer_id_is_reliable:
            return expected, 0xFFFFFFFF, "the trainer id from the console's own game data"
        # The name's terminator ate playerTrainerId[0] in the game data
        # [decomp:src/mystery_gift.c:364]: compare the top three bytes.
        return expected, 0xFFFFFF00, ("the trainer id from the game data, low byte excluded: "
                                      "a 7-character player name overwrote it")

    def block_address(self, index):
        """-> where block `index` was read from: the scatter table's entry, else base + n * size."""
        if self.buffer_dump_addresses:
            if index < len(self.buffer_dump_addresses):
                return self.buffer_dump_addresses[index]
            return self.buffer_dump_addresses[-1]
        return self.buffer_dump_address + index * (self.buffer_dump_size or 0)

    def _do_svr_read_buffer_dump(self):
        """The region itself, not the 4-byte return channel. With --dump-blocks this runs once per
        block and appends; a short block means the payload did not repoint that pass's send."""
        block = bytes(self._received)
        matched = len(block) == self.buffer_dump_size
        if matched:
            self.buffer_blocks.append(block)
        self.buffer_dump = b"".join(self.buffer_blocks) if self.buffer_blocks else block
        self.buffer_matched = matched and len(self.buffer_blocks) == self.buffer_dump_blocks
        self.param = matched
        self.trace.append(("buffer_dump", len(block)))
        if not matched:
            self.info(f"Buffer script dump: block {len(self.buffer_blocks) + 1} came back "
                      f"{len(block)} bytes, expected {self.buffer_dump_size}; the payload did not "
                      "repoint the send")
            return
        if self.buffer_dump_blocks > 1:
            self.info(f"Buffer script dump: block {len(self.buffer_blocks)}"
                      f"/{self.buffer_dump_blocks}, {len(block)} bytes, "
                      f"0x{self.block_address(len(self.buffer_blocks) - 1):08X}")
            if len(self.buffer_blocks) < self.buffer_dump_blocks:
                return
        head = self.buffer_dump[:16].hex()
        self.info(f"Buffer script dump: {len(self.buffer_dump)} bytes of console memory, "
                  f"head {head}")
        if self.buffer_decode == buffer_script.RNG_TRACE:
            for line in buffer_script.describe_rng_trace(self.buffer_dump):
                self.info(f"  {line}")
            trace = buffer_script.read_rng_trace(self.buffer_dump)
            self.trace.append(("buffer_trace", trace["taken"], trace["address"]))
            return
        if self.buffer_decode == buffer_script.CALL:
            # For SeedRng the watched word after the call must equal the first argument
            # [decomp:src/random.c:15]; nothing else is predicted.
            asked = buffer_script.call_parameters(self.buffer_code)
            expected = (asked["args"][0] & 0xFFFF
                        if asked["function"] == ((self.build or builds.DEFAULT).seed_rng | 1)
                        and asked["args"]
                        else None)
            for line in buffer_script.describe_call(self.buffer_dump, expected):
                self.info(f"  {line}")
            got = buffer_script.read_call(self.buffer_dump)
            self.trace.append(("buffer_call", got["function"], got["returned"]))
            return
        if self.buffer_decode == buffer_script.CALL_CHAIN:
            asked = buffer_script.chain_parameters(self.buffer_code)
            for line in buffer_script.describe_call_chain(self.buffer_dump, asked["steps"]):
                self.info(f"  {line}")
            chained = buffer_script.read_call_chain(self.buffer_dump)
            self.trace.append(("buffer_chain", chained["executed"], chained["refused"]))
            return
        if self.buffer_decode == buffer_script.SLOOP_SVC:
            got = buffer_script.parse_sloop_svc(self.buffer_dump)
            for number, regs in got["calls"]:
                self.info(f"  0x{number:02X}: r0..r3 " + " ".join(f"{v:08X}" for v in regs))
            if not got["returned"]:
                self.info(f"  the calls stopped after {len(got['calls'])}")
            self.info(f"  data after the last call: {got['data']!r}")
            self.trace.append(("buffer_sloop_svc", got["calls"], got["data"]))
            return
        if self.buffer_decode == buffer_script.CREATE_MON:
            asked = buffer_script.create_mon_parameters(self.buffer_code)
            for line in buffer_script.describe_create_mon(self.buffer_dump, asked):
                self.info(f"  {line}")
            created = buffer_script.read_create_mon(self.buffer_dump)
            self.trace.append(("buffer_create_mon", created["built_at"],
                               created["destination"]))
            return
        if self.buffer_decode == buffer_script.STRING_GATHER:
            gathered = buffer_script.read_gather(self.buffer_dump)
            asked = buffer_script.gather_parameters(self.buffer_code)
            for line in buffer_script.describe_gather(
                    self.buffer_dump, asked["src"], asked["stride"], asked["count"]):
                self.info(f"  {line}")
            self.trace.append(("buffer_gather", gathered["copied"], gathered["next"],
                               gathered["reason"]))
            return
        if self.buffer_decode == buffer_script.TABLE_SCAN:
            asked = buffer_script.table_scan_parameters(self.buffer_code)
            table = buffer_script.read_table_scan(
                self.buffer_dump, asked["start"], asked["end"])
            for line in buffer_script.describe_table_scan(
                    self.buffer_dump, asked["delta"], asked["runlen"],
                    asked["start"], asked["end"]):
                self.info(f"  {line}")
            self.trace.append(("buffer_table_scan", table["found"], table["cursor"],
                               table["calls"]))
            return
        if self.buffer_decode == buffer_script.ROM_CHECKSUM:
            asked = buffer_script.rom_checksum_parameters(self.buffer_code)
            reference = None
            if self.buffer_reference is not None:
                try:
                    with open(self.buffer_reference, "rb") as handle:
                        reference = handle.read()
                except OSError as exc:
                    self.info(f"  no reference ROM to compare with: {exc}")
            for line in buffer_script.describe_rom_checksum(
                    self.buffer_dump, asked["start"], asked["end"], asked["block"],
                    reference, self.buffer_reference):
                self.info(f"  {line}")
            got = buffer_script.read_rom_checksum(self.buffer_dump)
            self.trace.append(("buffer_rom_checksum", got["stored"], got["cursor"],
                               got["calls"]))
            return
        if self.buffer_decode == buffer_script.MEMORY_SCAN:
            scan = buffer_script.read_scan(self.buffer_dump)
            asked = buffer_script.scan_parameters(self.buffer_code)
            for line in buffer_script.describe_scan(
                    self.buffer_dump, asked["needle"], asked["start"], asked["end"]):
                self.info(f"  {line}")
            self.trace.append(("buffer_scan", scan["found"], scan["cursor"], scan["calls"]))
            return
        if self.buffer_dump_size == buffer_script.ANCHORS_SIZE:
            for line in buffer_script.describe_anchors(self.buffer_dump):
                self.info(f"  {line}")
        if buffer_script.describe(self.buffer_code).startswith(buffer_script.SAVE_DUMP + " "):
            asked = buffer_script.save_dump_parameters(self.buffer_code)
            for line in readout.describe(asked["block"], asked["offset"], self.buffer_dump,
                    language=1 if self.game_data and self.game_data.game_code.endswith(b"J") else None):
                self.info(f"  {line}")

    def _do_svr_load_buffer_verdict_msg(self):
        text = (self.buffer_success_message if self.buffer_matched
                else self.buffer_failure_message)
        self._loaded = (MG_LINKID_DYNAMIC_MSG, text, len(text))

    def _do_svr_load_msg(self, text):
        self._loaded = (MG_LINKID_DYNAMIC_MSG, text, len(text))
