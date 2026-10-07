#!/usr/bin/env python3
"""Builds the GB-Link Team Wonder Cards for the supported Switch FireRed/LeafGreen cartridges into
pokeldn/frlg/data/team_cards.json [docs/frlg_gift.md, GB-Link Team cards].

A port of GB-Link-Switch-LDN `cards/build.mjs` (GPL-3.0): the same script commands, cards and texts;
the ARM sources are vendor/gblink-cards/*.s. Changes: all six language pairs (vendor/gblink-cards/symbols.json),
the script copy and menu list moved below pokeldn's resident hooks, and the cards pokeldn already
makes its own way left out. Needs arm-none-eabi binutils.

    ./.venv/bin/python scripts/gen_team_cards.py
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SRC = ROOT / "vendor" / "gblink-cards"
OUT = ROOT / "pokeldn" / "frlg" / "data" / "team_cards.json"
# GBLINK_REFERENCE=DIR builds from their unmodified cards/ at their addresses, for comparing with their payloads.
REFERENCE = os.environ.get("GBLINK_REFERENCE")
ROMS = json.loads((SRC / "symbols.json").read_text())

WONDER_CARD_BYTES = 332
RAM_SCRIPT_BYTES = 995
VIRTUAL_BASE = 0x08000000
TEXT_BUFFER = 0x0201C000            # gDecompressionBuffer, unused while a field script runs
# newlib's malloc state, which only the unused AGBPrintf reaches; pokeldn's resident hooks own
# 0x0203FBB4..0x02040000 [docs/frlg_rom.md, Where a payload can live].
RELOCATED = 0x0203F768
MENU_LIST = 0x0203FB50              # 80 bytes after RELOCATED's 996 (menu.inc)
if REFERENCE:
    SRC_ASM, RELOCATED, MENU_LIST = pathlib.Path(REFERENCE), 0x0203FC00, 0x0203FBB0
else:
    SRC_ASM = SRC
CONTEXT_DATA = 0x64                 # the script context's data registers, which hold the trampoline
ROM_GAME, ROM_LANGUAGE, ROM_REVISION = 0x080000AE, 0x080000AF, 0x080000BC
HOOK_STATE = 0x0203FF60             # first byte 1 while a V-blank hook card is on
RESIDENT = 0x0203FC00
LANGUAGE_IDS = {"J": 1, "E": 2, "F": 3, "I": 4, "D": 5, "S": 7}     # include/constants/global.h

VAR_TEMP_1, VAR_TEMP_2, VAR_TEMP_3, VAR_TEMP_4 = 0x4001, 0x4002, 0x4003, 0x4004
VAR_0x8004, VAR_0x8005, VAR_0x8006, VAR_RESULT = 0x8004, 0x8005, 0x8006, 0x800D
MENU_B = 127
UNSET, EQ, GT, GE, NE = 0, 1, 2, 4, 5
ITEM_RARE_CANDY, ITEM_COIN_CASE = 68, 260
PARTY_SIZE, SPECIES_EGG, SPECIES_UNOWN, SPECIES_EEVEE, MAX_MON_MOVES = 6, 412, 201, 133, 4
FADE_FROM_BLACK, FADE_TO_BLACK, FADE_FROM_WHITE, FADE_TO_WHITE = 0, 1, 2, 3
MON_GIVEN_TO_PC, MON_CANT_GIVE = 1, 2

SB1_SCRIPT = 0x3624                 # the RAM script in SaveBlock1
FAMILY_SYMBOLS = {"DAYCARE": 0x2F80, "GIFT_RIBBONS": 0x309C, "PC_SPECIAL": 0x3C}
SPECIALS = dict(
    choosePartyMon=0x9F, eggHatch=0xC2, changePokemonNickname=0x9E, getPartyMonSpecies=0x147,
    chooseMonForMoveRelearner=0xDB, teachMoveRelearnerMove=0xE0, isSelectedMonEgg=0x148,
    getNumMovesSelectedMonHas=0xDF, chooseMoveToForget=0xDC, moveDeleterForgetMove=0xDD,
    bufferMoveDeleterNicknameAndMove=0xDE, slotMachineId=0x11E)
FLAGS = dict(nationalDex=0x840, ribbons=0x83B, mysteryGiftDone=0x3D8, pendingDaycareEgg=0x266,
             gotCoinCase=0x243, tutors=[*range(0x2C0, 0x2CF), *range(0x2DE, 0x2E1)])
VAR_REPEL_STEPS = 0x4020
SONG_GIFT_MON, SONG_GAME_CORNER = 257, 273


def u16(v):
    return [v & 0xFF, (v >> 8) & 0xFF]


def u32(v):
    return [(v >> s) & 0xFF for s in (0, 8, 16, 24)]


# ---- script commands
def end(): return [0x02]
def loadword(i, v): return [0x0F, i, *u32(v)]
def writebytetoaddr(v, a): return [0x11, v, *u32(a)]
def setvar(var, v): return [0x16, *u16(var), *u16(v)]
def addvar(var, v): return [0x17, *u16(var), *u16(v)]
def setflag(f): return [0x29, *u16(f)]
def clearflag(f): return [0x2A, *u16(f)]
def checkflag(f): return [0x2B, *u16(f)]
def additem(item, n=1): return [0x44, *u16(item), *u16(n)]
def removeitem(item, n=1): return [0x45, *u16(item), *u16(n)]
def checkitemspace(item, n=1): return [0x46, *u16(item), *u16(n)]
def checkitem(item, n=1): return [0x47, *u16(item), *u16(n)]
def compare_addr(a, v): return [0x1F, *u32(a), ord(v) if isinstance(v, str) else v]
def copyvar(to, frm): return [0x19, *u16(to), *u16(frm)]
def compare_var(var, v): return [0x21, *u16(var), *u16(v)]
def callnative(a): return [0x23, *u32(a)]
def special(i): return [0x25, *u16(i)]
def specialvar(var, i): return [0x26, *u16(var), *u16(i)]
def waitstate(): return [0x27]
def delay(frames): return [0x28, *u16(frames)]
def waitmessage(): return [0x66]
def message(a): return [0x67, *u32(a)]
def closemessage(): return [0x68]
def lock(): return [0x6A]
def faceplayer(): return [0x5A]
def getpartysize(): return [0x43]
def bufferspeciesname(i, var): return [0x7D, i, *u16(var)]
def bufferpartymonnick(i, var): return [0x7F, i, *u16(var)]
def buffernumberstring(i, var): return [0x83, i, *u16(var)]
def release(): return [0x6C]
def waitbuttonpress(): return [0x6D]
def yesnobox(): return [0x6E, 20, 8]
def fadescreen(mode): return [0x97, mode]
def setvaddress(a): return [0xB8, *u32(a)]
def vgoto(label): return [0xB9, {"label": label}]
def vgoto_if(cond, label): return [0xBB, cond, {"label": label}]
def vmessage(label): return [0xBD, {"label": label}]
def giveegg(var): return [0x7A, *u16(var)]
def addmoney(amount): return [0x90, *u32(amount), 0]
def checkcoins(var): return [0xB3, *u16(var)]
def addcoins(n): return [0xB4, *u16(n)]
def playbgm(song, save=0): return [0x33, *u16(song), save]
def playslotmachine(var): return [0x89, *u16(var)]
def playfanfare(song): return [0x31, *u16(song)]
def waitfanfare(): return [0x32]
def define(label): return [{"define": label}]
def say(label): return [*vmessage(label), *waitmessage(), *waitbuttonpress(), *closemessage(), *release(), *end()]
def native(routine): return [{"native": routine}]
# Moves the script to RELOCATED; setvaddress then points the relative addresses at the copy.
def relocate(): return [*native("relocate"), {"define": "relocated"}, 0xB8, {"label": "relocated"}]


CHARSET = {" ": 0x00, "&": 0x2D, "é": 0x1B, "!": 0xAB, "?": 0xAC, ".": 0xAD, "-": 0xAE, "…": 0xB0, "’": 0xB4,
           "'": 0xB4, ",": 0xB8, "×": 0xB9, "¥": 0xB7, "/": 0xBA, ":": 0xF0, "¶": 0xFB, "\n": 0xFE}
CHARSET.update({str(i): 0xA1 + i for i in range(10)})
CHARSET.update({chr(65 + i): 0xBB + i for i in range(26)})
CHARSET.update({chr(97 + i): 0xD5 + i for i in range(26)})
PLACEHOLDERS = {"PLAYER": [0xFD, 0x01], "STR_VAR_1": [0xFD, 0x02], "STR_VAR_2": [0xFD, 0x03],
                "STR_VAR_3": [0xFD, 0x04], "RIVAL": [0xFD, 0x06]}


def encode_text(text, tokens=PLACEHOLDERS):
    out, i = [], 0
    while i < len(text):
        if text[i] == "{":
            j = text.index("}", i)
            out += tokens[text[i + 1:j]]
            i = j + 1
            continue
        out.append(CHARSET[text[i]])
        i += 1
    return out + [0xFF]


def text_items(texts):
    return [x for label, text in texts.items() for x in (*define(label), *encode_text(text))]


# ---- the cards
FOOTER = ("GB-Link Team", "")
VISIT = ("Visit the deliveryman on 2F", "of a POKéMON CENTER.")
SPEEDS = {
    "0-5": (dict(TEXT_EXTRA=0, OW_EXTRA=0, BATTLE_EXTRA=0, SLOW_PERIOD=2),
            "Press R to play at half speed!\nPress R again to play normally."),
    "0-75": (dict(TEXT_EXTRA=0, OW_EXTRA=0, BATTLE_EXTRA=0, SLOW_PERIOD=4),
             "Press R to play a little slower!\nPress R again to play normally."),
    "2": (dict(TEXT_EXTRA=1, OW_EXTRA=1, BATTLE_EXTRA=1, SLOW_PERIOD=0),
          "Press R for double speed!\nPress R again to play normally."),
    "3": (dict(TEXT_EXTRA=2, OW_EXTRA=2, BATTLE_EXTRA=2, SLOW_PERIOD=0),
          "Press R for triple speed!\nPress R again to play normally."),
    "4": (dict(TEXT_EXTRA=4, OW_EXTRA=3, BATTLE_EXTRA=3, SLOW_PERIOD=0),
          "Press R to speed the game up!\nPress R again to play normally."),
}
SPEED_SUBTITLE = "R turns it on and off!"


def speed_script(text):
    return dict(body=[*native("install"), *say("message_text")], texts={"message_text": text})


def asking_script(entry, ask, done, declined, flash=False):
    return dict(body=[
        *vmessage("ask_text"), *waitmessage(), *yesnobox(),
        *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "declined"),
        *([*closemessage(), *fadescreen(FADE_TO_WHITE)] if flash else []),
        *native(entry),
        *(fadescreen(FADE_FROM_WHITE) if flash else []),
        *say("done_text"),
        *define("declined"),
        *say("declined_text"),
    ], texts={"ask_text": ask, "done_text": done, "declined_text": declined})


def party_mon_script(which, steps, texts, egg=None):
    """Asks for a party Pokemon (its name in STR_VAR_1), then `steps`; an Egg gets `egg` instead."""
    return dict(body=[
        *vmessage("which_text"), *waitmessage(), *waitbuttonpress(),
        *relocate(),
        *special(SPECIALS["choosePartyMon"]), *waitstate(),
        *compare_var(VAR_0x8004, PARTY_SIZE), *vgoto_if(GE, "done"),
        *([*specialvar(VAR_RESULT, SPECIALS["getPartyMonSpecies"]),
           *compare_var(VAR_RESULT, SPECIES_EGG), *vgoto_if(EQ, "egg")] if egg else []),
        *bufferpartymonnick(0, VAR_0x8004),
        *steps,
        *([*define("egg"), *say("egg_text")] if egg else []),
        *define("done"),
        *closemessage(), *release(), *end(),
    ], texts={"which_text": which, **({"egg_text": egg} if egg else {}), **texts})


# judge.s placeholders: FD 00 nickname, FD 01 nature, FD 10+n value n (FD 1C the EV total), FD 30/31 lines
JUDGE_TOKENS = {"name": [0xFD, 0x00], "nature": [0xFD, 0x01], "hp": [0xFD, 0x10], "attack": [0xFD, 0x11],
                "defense": [0xFD, 0x12], "speed": [0xFD, 0x13], "sp_atk": [0xFD, 0x14], "sp_def": [0xFD, 0x15],
                "ev_total": [0xFD, 0x1C], "ivs": [0xFD, 0x30], "evs": [0xFD, 0x31]}


def event_mon_script(name, choose=(), texts=None):
    """An event Pokemon (eventmon.s): once per card, into the party or the PC."""
    return dict(body=[
        *checkflag(FLAGS["mysteryGiftDone"]), *vgoto_if(EQ, "already"),
        *choose,
        *getpartysize(),
        *native("give_mon"),
        *compare_var(VAR_RESULT, MON_CANT_GIVE), *vgoto_if(EQ, "full"),
        *setflag(FLAGS["mysteryGiftDone"]),
        *playfanfare(SONG_GIFT_MON), *vmessage("received_text"), *waitmessage(), *waitfanfare(),
        *waitbuttonpress(),
        *compare_var(VAR_RESULT, MON_GIVEN_TO_PC), *vgoto_if(EQ, "pc"),
        *closemessage(), *release(), *end(),
        *define("pc"), *say("pc_text"),
        *define("already"), *say("already_text"),
        *define("full"), *say("full_text"),
        *([*define("declined"), *say("declined_text")] if choose else []),
    ], texts={
        "received_text": f"{{PLAYER}} received {name or '{STR_VAR_1}'}!",
        "pc_text": "It was sent to the PC.",
        "already_text": f"Receive the card again for\nanother {name or 'one'}!",
        "full_text": "Your party and the PC are full!",
        **({"declined_text": "Come back any time!"} if choose else {}),
        **(texts or {}),
    })


# Offers the card's Pokemon in turn, their names in STR_VAR_1, until one is taken: VAR_0x8004.
OFFER_MON = [
    *setvar(VAR_0x8004, 0),
    *define("offer"),
    *native("offer"),
    *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "declined"),
    *bufferspeciesname(0, VAR_0x8006),
    *vmessage("offer_text"), *waitmessage(), *yesnobox(),
    *compare_var(VAR_RESULT, 1), *vgoto_if(EQ, "chosen"),
    *addvar(VAR_0x8004, 1),
    *vgoto("offer"),
    *define("chosen"),
]


def card(flag, number, icon, bg, title, subtitle, body):
    return dict(flagId=flag, idNumber=number, iconSpecies=icon, bgType=bg, title=title, subtitle=subtitle,
                body=list(body), footer=list(FOOTER))


def hook_toggle(ask, on, keep, off, off_native=None):
    """A V-blank hook card: the first talk asks and installs, a later one offers to turn it off."""
    return dict(body=[
        *compare_addr(HOOK_STATE, 1), *vgoto_if(EQ, "active"),
        *vmessage("ask_text"), *waitmessage(), *yesnobox(),
        *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "declined"),
        *native("install"),
        *say("on_text"),
        *define("active"),
        *vmessage("keep_text"), *waitmessage(), *yesnobox(),
        *compare_var(VAR_RESULT, 1), *vgoto_if(EQ, "declined"),
        *(native(off_native) if off_native else writebytetoaddr(0, HOOK_STATE)),
        *say("off_text"),
        *define("declined"),
        *say("declined_text"),
    ], texts={"ask_text": ask, "on_text": on, "keep_text": keep, "off_text": off,
              "declined_text": "Come back any time!"})


CARDS = [
    *[dict(id=f"custom-speed-{key}", source="speed.s", symbols={**symbols, "TOGGLE": 1},
           subtitle=SPEED_SUBTITLE, script=speed_script(text)) for key, (symbols, text) in SPEEDS.items()],
    dict(id="custom-gender-swap", source="gender.s",
         card=card(1013, 13, 132, 2, "NEW TRAINER NAME/GENDER", "A new name, a new look!",
                   ("New name? New look? Visit the", "deliveryman on the 2nd floor",
                    "of a POKéMON CENTER to rename", "or swap between BOY and GIRL.")),
         script=dict(body=[
             *vmessage("name_text"), *waitmessage(), *yesnobox(),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "gender"),
             *relocate(),
             *closemessage(), *fadescreen(FADE_TO_BLACK),
             *native("rename"), *waitstate(),
             *native("update_ot"),
             *vmessage("named_text"), *waitmessage(), *waitbuttonpress(),
             *define("gender"),
             *vmessage("ask_text"), *waitmessage(), *yesnobox(),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "declined"),
             *closemessage(), *fadescreen(FADE_TO_WHITE),
             *native("swap"),
             *fadescreen(FADE_FROM_WHITE),
             *say("done_text"),
             *define("declined"),
             *say("declined_text"),
         ], texts={
             "name_text": "Would you like a new name?",
             "named_text": "Nice to meet you, {PLAYER}!",
             "ask_text": "Shall I swap you between\nBOY and GIRL?",
             "done_text": "Ta-da! Talk to me again any\ntime to swap back.",
             "declined_text": "Come back any time!",
         })),
    dict(id="custom-pokerus", source="pokerus.s",
         card=card(1014, 14, 113, 5, "POKéRUS", "Achoo!",
                   ("A tiny virus that helps", "POKéMON grow stronger. Visit", "the deliveryman on the 2nd",
                    "floor of a POKéMON CENTER.")),
         script=asking_script(
             "infect",
             "POKéRUS is a tiny virus that\nhelps POKéMON grow stronger.¶Want your party POKéMON\nto catch it?",
             "Achoo! Your party POKéMON\ncaught POKéRUS!", "Stay healthy out there!")),
    dict(id="custom-instant-eggs", source="eggs.s",
         card=card(1016, 16, 412, 1, "INSTANT EGGS", "Hatch now, or get one now",
                   ("Hatch the EGGS you carry, or", "get the DAY CARE’s EGG right", "away. Visit the deliveryman",
                    "on 2F of a POKéMON CENTER.")),
         # Each Egg hatches with the game's own scene; the delay lets the overworld fade back in.
         script=dict(body=[
             *native("prepare"),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "daycare"),
             *vmessage("ask_text"), *waitmessage(), *yesnobox(),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "daycare"),
             *closemessage(),
             *relocate(),
             *define("next"),
             *native("next_egg"),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "hatched"),
             *special(SPECIALS["eggHatch"]), *waitstate(),
             *delay(16),
             *vgoto("next"),
             *define("hatched"),
             *say("hatched_text"),
             *define("daycare"),
             *vmessage("daycare_text"), *waitmessage(), *yesnobox(),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "declined"),
             *checkflag(FLAGS["pendingDaycareEgg"]), *vgoto_if(EQ, "waiting"),
             *native("daycare_egg"),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "no_pair"),
             *say("ready_text"),
             *define("waiting"), *say("waiting_text"),
             *define("no_pair"), *say("no_pair_text"),
             *define("declined"), *say("declined_text"),
         ], texts={
             "ask_text": "You have EGGS with you!\nShall I hatch them right now?",
             "hatched_text": "Take good care of them!",
             "daycare_text": "Shall I have the DAY CARE’s\nEGG ready for you right away?",
             "ready_text": "The DAY CARE has an EGG\nready for you now!",
             "waiting_text": "The DAY CARE already has an\nEGG waiting for you!",
             "no_pair_text": "Leave two POKéMON that get\nalong at the DAY CARE first!",
             "declined_text": "Come back any time!",
         })),
    dict(id="custom-friendship", source="friendship.s",
         card=card(1017, 17, 172, 4, "FRIENDSHIP CHECKER", "How close are you?",
                   ("See how friendly a POKéMON is,", "then make it or your party as", "friendly as can be. Visit the",
                    "deliveryman on 2F of a CENTER.")),
         data={"max_items": "THIS POKéMON", "max_party": "WHOLE PARTY", "max_no": "NO THANKS"},
         script=party_mon_script(
             "Whose friendship should I\ncheck?",
             [*native("check"), *buffernumberstring(1, VAR_0x8005),
              *vmessage("value_text"), *waitmessage(), *waitbuttonpress(),
              *vmessage("ask_text"), *waitmessage(),
              *native("max_menu"), *waitstate(),
              *compare_var(VAR_RESULT, 2), *vgoto_if(GE, "declined"),
              *native("befriend"),
              *compare_var(VAR_RESULT, 0), *vgoto_if(NE, "party"),
              *say("one_text"),
              *define("party"), *say("party_text"),
              *define("declined"), *say("declined_text")],
             {"value_text": "{STR_VAR_1}’s friendship is\n{STR_VAR_2} out of 255.",
              "ask_text": "Shall I make it as friendly\nas can be?",
              "one_text": "{STR_VAR_1} adores you now!",
              "party_text": "Your whole party adores you\nnow!",
              "declined_text": "Come back any time!"},
             egg="An EGG hasn’t made friends yet!")),
    dict(id="custom-stat-judge", source="judge.s",
         card=card(1019, 19, 178, 6, "IV/EV STAT JUDGE", "IVs, EVs and nature",
                   ("Curious about your POKéMON?", "The deliveryman on the 2nd", "floor of a POKéMON CENTER can",
                    "show its IVs, EVs and nature.")),
         data={"template": "{name}’s nature is {nature}.\nHere are its IVs, out of 31:¶{ivs}¶Its EVs add up to "
                           "{ev_total} of 510:¶{evs}",
               "stat_lines": "HP {hp}, ATTACK {attack}, DEFENSE {defense}\nSP. ATK {sp_atk}, SP. DEF {sp_def}, "
                             "SPEED {speed}"},
         tokens=JUDGE_TOKENS,
         # The party menu leaves the chosen slot in VAR_0x8004, or PARTY_SIZE + 1 when cancelled.
         script=dict(body=[
             *vmessage("ask_text"), *waitmessage(), *waitbuttonpress(),
             *relocate(),
             *special(SPECIALS["choosePartyMon"]), *waitstate(),
             *compare_var(VAR_0x8004, PARTY_SIZE), *vgoto_if(GE, "done"),
             *native("judge"),
             *message(TEXT_BUFFER), *waitmessage(), *waitbuttonpress(), *closemessage(),
             *define("done"),
             *release(), *end(),
         ], texts={"ask_text": "Which POKéMON should I judge?"})),
    dict(id="custom-no-encounters", source="encounters.s",
         card=card(1020, 20, 41, 7, "NO ENCOUNTERS & REPEL", "Wild POKéMON, stay away!",
                   ("Keep all wild POKéMON away,", "or only the weaker ones. Visit", "the deliveryman on the 2nd",
                    "floor of a POKéMON CENTER.")),
         data={"choice_items": "ALL OF THEM", "choice_weaker": "WEAKER ONES", "choice_none": "NONE"},
         script=None),          # filled in below: it names the build's sWildEncountersDisabled
    dict(id="custom-nickname", source="nickname.s",
         card=card(1021, 21, 201, 3, "NICKNAME CHANGE", "A new name, or none at all",
                   ("Give a POKéMON a new nickname", "or its species name back. Visit", "the deliveryman on the 2nd",
                    "floor of a POKéMON CENTER.")),
         script=dict(body=[
             *vmessage("which_text"), *waitmessage(), *waitbuttonpress(),
             *relocate(),
             *special(SPECIALS["choosePartyMon"]), *waitstate(),
             *compare_var(VAR_0x8004, PARTY_SIZE), *vgoto_if(GE, "done"),
             *specialvar(VAR_RESULT, SPECIALS["getPartyMonSpecies"]),
             *compare_var(VAR_RESULT, SPECIES_EGG), *vgoto_if(EQ, "egg"),
             *bufferpartymonnick(0, VAR_0x8004),
             *vmessage("rename_text"), *waitmessage(), *yesnobox(),
             *compare_var(VAR_RESULT, 1), *vgoto_if(EQ, "rename"),
             *native("nicknamed"),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "declined"),
             *vmessage("remove_text"), *waitmessage(), *yesnobox(),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "declined"),
             *native("unname"),
             *bufferpartymonnick(0, VAR_0x8004),
             *say("removed_text"),
             *define("rename"),
             *closemessage(), *fadescreen(FADE_TO_BLACK),
             *special(SPECIALS["changePokemonNickname"]), *waitstate(),
             *bufferpartymonnick(0, VAR_0x8004),
             *say("renamed_text"),
             *define("egg"), *say("egg_text"),
             *define("declined"), *say("declined_text"),
             *define("done"),
             *release(), *end(),
         ], texts={
             "which_text": "Whose nickname shall I change?",
             "rename_text": "Give {STR_VAR_1} a new nickname?",
             "remove_text": "Should {STR_VAR_1} go back to\nits species name instead?",
             "removed_text": "Done! It’s {STR_VAR_1} again.",
             "renamed_text": "From now on, it’s {STR_VAR_1}!",
             "egg_text": "An EGG doesn’t have a name yet!",
             "declined_text": "Come back any time!",
         })),
    dict(id="custom-shiny-hunting", source="shiny.s", symbols={"STATE": HOOK_STATE},
         card=card(1022, 22, 130, 0, "SHINY HUNTING", "Shiny POKéMON, more often",
                   ("Catch or defeat one POKéMON", "again and again to meet it", "shiny. Visit the deliveryman",
                    "on 2F of a POKéMON CENTER.")),
         data={"chain_text": "{STR_VAR_1} chain: {STR_VAR_2}!"},
         # The first talk turns it on, until the game is reset; talking again says so.
         script=dict(body=[
             *compare_addr(HOOK_STATE, 1), *vgoto_if(EQ, "active"),
             *native("install"),
             *define("active"),
             *say("on_text"),
         ], texts={"on_text": "On until you reset!\nR shows your chain."})),
    dict(id="custom-nature-mint", source="nature.s",
         card=card(1023, 23, 43, 3, "NATURE MINT", "A fresh new nature",
                   ("Pick the stat a POKéMON’s", "nature raises and the one it", "lowers. Visit the deliveryman",
                    "on 2F of a POKéMON CENTER.")),
         # The first choice waits in VAR_0x8005 while the second is made.
         script=party_mon_script(
             "Whose nature should I change?",
             [*vmessage("raise_text"), *waitmessage(),
              *native("stat_menu"), *waitstate(),
              *compare_var(VAR_RESULT, MENU_B), *vgoto_if(EQ, "done"),
              *copyvar(VAR_0x8005, VAR_RESULT),
              *vmessage("lower_text"), *waitmessage(),
              *native("stat_menu"), *waitstate(),
              *compare_var(VAR_RESULT, MENU_B), *vgoto_if(EQ, "done"),
              *native("change_nature"),
              *say("changed_text")],
             {"raise_text": "Raise which stat?", "lower_text": "Lower which stat?",
              "changed_text": "{STR_VAR_1} is {STR_VAR_2} now!"})),
    dict(id="custom-ability-capsule", source="ability.s",
         card=card(1024, 24, 233, 6, "ABILITY CAPSULE", "Try its other ability",
                   ("Switch a POKéMON to the other", "ability its species can have.", *VISIT)),
         script=party_mon_script(
             "Whose ability should I switch?",
             [*native("switch_ability"),
              *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "one"),
              *say("done_text"),
              *define("one"), *say("one_text")],
             {"done_text": "{STR_VAR_1}’s ability is now\n{STR_VAR_2}!",
              "one_text": "{STR_VAR_1} has only one\nability."},
             egg="An EGG can’t switch abilities!")),
    dict(id="custom-poke-ball-changer", source="ball.s",
         card=card(1064, 64, 100, 5, "POKé BALL CHANGER", "A new home for a POKéMON",
                   ("Move a POKéMON into the POKé", "BALL of your choice. Visit", "the deliveryman on the 2nd",
                    "floor of a POKéMON CENTER.")),
         data={"more_items": "MORE…"},
         # VAR_0x8006 is the page of balls; B on the second goes back to the first.
         script=party_mon_script(
             "Which POKéMON should get a\nnew POKé BALL?",
             [*setvar(VAR_0x8006, 0),
              *define("menu"),
              *vmessage("ball_text"), *waitmessage(),
              *native("ball_menu"), *waitstate(),
              *compare_var(VAR_RESULT, MENU_B), *vgoto_if(EQ, "back"),
              *native("set_ball"),
              *compare_var(VAR_RESULT, 0), *vgoto_if(NE, "menu"),
              *say("done_text"),
              *define("back"),
              *compare_var(VAR_0x8006, 0), *vgoto_if(EQ, "declined"),
              *setvar(VAR_0x8006, 0),
              *vgoto("menu"),
              *define("declined"), *say("declined_text")],
             {"ball_text": "Which POKé BALL would it like?",
              "done_text": "{STR_VAR_1} now calls its\n{STR_VAR_2} home!",
              "declined_text": "Come back any time!"},
             egg="An EGG hasn’t been caught in a\nPOKé BALL!")),
    dict(id="custom-pokemon-gender", source="mongender.s",
         card=card(1025, 25, 32, 4, "POKéMON GENDER CHANGE", "For the perfect pair",
                   ("Switch a POKéMON between male", "and female. Visit the", "deliveryman on the 2nd floor",
                    "of a POKéMON CENTER.")),
         script=party_mon_script(
             "Which POKéMON should switch\ngender?",
             [*native("switch_gender"),
              *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "one"),
              *compare_var(VAR_RESULT, 2), *vgoto_if(EQ, "female"),
              *say("male_text"),
              *define("female"), *say("female_text"),
              *define("one"), *say("one_text")],
             {"male_text": "{STR_VAR_1} is now male!", "female_text": "{STR_VAR_1} is now female!",
              "one_text": "{STR_VAR_1}’s gender can’t\nbe switched."},
             egg="Let’s wait for the EGG to\nhatch first!")),
    dict(id="custom-pp-max", source="ppmax.s",
         card=card(1027, 27, 36, 7, "PP MAX", "Moves at full power",
                   ("Every move in your party gets", "the most PP it can have. Visit", "the deliveryman on the 2nd",
                    "floor of a POKéMON CENTER.")),
         script=asking_script("max_pp", "Shall I raise the PP of every\nmove in your party to the max?",
                              "Done! Every move has the most\nPP it can have.", "Come back any time!")),
    dict(id="custom-max-conditions", source="conditions.s",
         card=card(1028, 28, 329, 1, "MAX CONDITIONS", "Contest ready!",
                   ("COOL, BEAUTY, CUTE, SMART and", "TOUGH to the max: a FEEBAS",
                    "then evolves at its next level.", "Visit 2F of a POKéMON CENTER.")),
         script=party_mon_script(
             "Which POKéMON should I get\nready for contests?",
             [*native("max_conditions"), *say("done_text")],
             {"done_text": "{STR_VAR_1} is in top condition!¶A FEEBAS in this condition will\n"
                           "evolve at its next level."},
             egg="An EGG can’t enter contests!")),
    dict(id="custom-hidden-power", source="hiddenpower.s", symbols={"PICK": 0},
         card=card(1029, 29, 201, 2, "HIDDEN POWER & IVS", "Check it, then max it",
                   ("See a POKéMON’s HIDDEN POWER,", "then raise all its IVs to 31", "if you like. Visit the 2F",
                    "deliveryman of a CENTER.")),
         script=party_mon_script(
             "Whose HIDDEN POWER should I\ncheck?",
             [*native("hidden_power"), *buffernumberstring(2, VAR_0x8005),
              *vmessage("power_text"), *waitmessage(), *waitbuttonpress(),
              *vmessage("ask_text"), *waitmessage(), *yesnobox(),
              *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "declined"),
              *native("max_ivs"),
              *native("hidden_power"), *buffernumberstring(2, VAR_0x8005),
              *say("trained_text"),
              *define("declined"), *say("declined_text")],
             {"power_text": "{STR_VAR_1}’s HIDDEN POWER is\n{STR_VAR_2}-type, power {STR_VAR_3}.",
              "ask_text": "Shall I raise all its IVs to\n31? Its nature may change.",
              "trained_text": "All its IVs are 31 now!¶Its HIDDEN POWER is\n{STR_VAR_2}-type, power {STR_VAR_3}.",
              "declined_text": "Come back any time!"},
             egg="An EGG keeps its power hidden!")),
    dict(id="custom-hidden-power-type", source="hiddenpower.s", symbols={"PICK": 1},
         card=card(1057, 57, 201, 6, "HIDDEN POWER TYPE", "Any type, power 70",
                   ("Give a POKéMON’s HIDDEN POWER", "the type you choose. Visit", "the deliveryman on the 2nd",
                    "floor of a POKéMON CENTER.")),
         data={"kind_items": "PHYSICAL", "kind_special": "SPECIAL"},
         script=party_mon_script(
             "Whose HIDDEN POWER should I\nchange?",
             [*vmessage("kind_text"), *waitmessage(),
              *native("kind_menu"), *waitstate(),
              *compare_var(VAR_RESULT, MENU_B), *vgoto_if(EQ, "declined"),
              *copyvar(VAR_0x8006, VAR_RESULT),
              *vmessage("type_text"), *waitmessage(),
              *native("type_menu"), *waitstate(),
              *compare_var(VAR_RESULT, MENU_B), *vgoto_if(EQ, "declined"),
              *native("set_type"),
              *say("done_text"),
              *define("declined"), *say("declined_text")],
             {"kind_text": "A physical or a special type?", "type_text": "Which type?",
              "done_text": "Done! {STR_VAR_1}’s HIDDEN POWER\nis {STR_VAR_2}-type, power 70.",
              "declined_text": "Come back any time!"},
             egg="An EGG keeps its power hidden!")),
    dict(id="custom-unown-letters", source="unown.s",
         card=card(1056, 56, 201, 6, "UNOWN LETTER CHANGER", "From A to ?",
                   ("Give an UNOWN any of its 28", "letters. It keeps its nature.", *VISIT)),
         script=party_mon_script(
             "Which UNOWN?",
             [*specialvar(VAR_RESULT, SPECIALS["getPartyMonSpecies"]),
              *compare_var(VAR_RESULT, SPECIES_UNOWN), *vgoto_if(NE, "not_unown"),
              *vmessage("type_text"), *waitmessage(), *waitbuttonpress(),
              *define("naming"),
              *closemessage(), *fadescreen(FADE_TO_BLACK),
              *native("type_letter"), *waitstate(),
              *native("change_letter"),
              *bufferpartymonnick(0, VAR_0x8004),
              *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "declined"),
              *compare_var(VAR_RESULT, 2), *vgoto_if(EQ, "one_letter"),
              *say("done_text"),
              *define("one_letter"),
              *vmessage("one_letter_text"), *waitmessage(), *waitbuttonpress(),
              *vgoto("naming"),
              *define("not_unown"), *say("not_unown_text"),
              *define("declined"), *say("declined_text")],
             {"type_text": "Type its new letter:\nA to Z, ! or ?",
              "one_letter_text": "One letter, please:\nA to Z, ! or ?",
              "done_text": "{STR_VAR_1} is the letter\n{STR_VAR_2} now!",
              "not_unown_text": "That’s not an UNOWN!",
              "declined_text": "Come back any time!"})),
    dict(id="custom-ev-training", source="evs.s",
         card=card(1030, 30, 106, 0, "EV TRAINING", "Train without battling",
                   ("Reset a POKéMON’s EVs or max", "the stats you choose. Visit", "the deliveryman on the 2nd",
                    "floor of a POKéMON CENTER.")),
         script=party_mon_script(
             "Which POKéMON should I train?",
             [*vmessage("reset_text"), *waitmessage(), *yesnobox(),
              *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "train"),
              *native("reset_evs"),
              *define("train"),
              *vmessage("stat_text"), *waitmessage(),
              *native("ev_menu"), *waitstate(),
              *compare_var(VAR_RESULT, MENU_B), *vgoto_if(EQ, "finish"),
              *native("max_ev"),
              *buffernumberstring(2, VAR_0x8005),
              *vmessage("trained_text"), *waitmessage(), *waitbuttonpress(),
              *vgoto("train"),
              *define("finish"),
              *native("recalculate"),
              *say("done_text")],
             {"reset_text": "Reset all of {STR_VAR_1}’s\nEVs to 0 first?",
              "stat_text": "Which EVs should I max?\nPress B when you’re done.",
              "trained_text": "{STR_VAR_2} EVs: {STR_VAR_3}.",
              "done_text": "All done! Good luck,\n{STR_VAR_1}!"},
             egg="An EGG can’t train yet!")),
    dict(id="custom-trainer-ids", source="ids.s",
         card=card(1031, 31, 63, 6, "TRAINER ID REVEAL", "Both of your IDs",
                   ("Learn your TRAINER ID and the", "SECRET ID the game hides.", *VISIT)),
         script=dict(body=[*native("buffer_ids"), *say("ids_text")], texts={
             "ids_text": "Your TRAINER ID is {STR_VAR_1}\nand your SECRET ID is {STR_VAR_2}.¶Together they "
                         "decide which\nPOKéMON you meet are shiny."})),
    dict(id="custom-rival-name", source="rival.s",
         card=card(1037, 37, 133, 4, "RENAME YOUR RIVAL", "Smell ya later!",
                   ("Give your rival a new name.", "Visit the deliveryman on the", "2nd floor of a POKéMON",
                    "CENTER.")),
         # The naming screen returns to the field, so the script moves first.
         script=dict(body=[
             *vmessage("ask_text"), *waitmessage(), *yesnobox(),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "declined"),
             *relocate(),
             *closemessage(), *fadescreen(FADE_TO_BLACK),
             *native("rename_rival"), *waitstate(),
             *say("renamed_text"),
             *define("declined"), *say("declined_text"),
         ], texts={"ask_text": "Would you like to give your\nrival a new name?",
                   "renamed_text": "From now on, your rival is\n{RIVAL}!",
                   "declined_text": "Come back any time!"})),
    dict(id="custom-gift-ribbons", source="ribbons.s",
         card=card(1038, 38, 358, 0, "GIFT RIBBONS", "Seven RIBBONS to show off",
                   ("Your party gets the gift", "RIBBONS once only given at", "events. Visit the deliveryman",
                    "on 2F of a POKéMON CENTER.")),
         script=dict(body=[
             *vmessage("ask_text"), *waitmessage(), *yesnobox(),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "declined"),
             *native("give_ribbons"),
             *setflag(FLAGS["ribbons"]),
             *say("done_text"),
             *define("declined"), *say("declined_text"),
         ], texts={"ask_text": "Shall I give your party POKéMON\nthe gift RIBBONS?",
                   "done_text": "Your POKéMON got all seven gift\nRIBBONS! Take a look.",
                   "declined_text": "Come back any time!"})),
    # The speed hook with extra text printer runs only, every frame; R keeps its own use.
    dict(id="custom-fast-text", source="speed.s",
         symbols=dict(TEXT_EXTRA=8, OW_EXTRA=0, BATTLE_EXTRA=0, SLOW_PERIOD=0, HELP_R_DISABLE=0, TOGGLE=0),
         card=card(1039, 39, 315, 6, "FAST TEXT", "No more waiting",
                   ("All text prints at top speed", "until you turn off your game.", *VISIT)),
         script=speed_script("All text prints at top speed\nnow, until you turn off the game.")),
    dict(id="custom-move-tutor", source="movetutor.s",
         card=card(1040, 40, 235, 5, "MOVE RELEARNER & DELETER", "And the tutors teach again",
                   ("Relearn a move, forget one,", "or let the move tutors teach", "again. Visit the deliveryman",
                    "on 2F of a POKéMON CENTER.")),
         # The game's own relearner and deleter; both return to the field.
         script=dict(body=[
             *relocate(),
             *vmessage("remember_text"), *waitmessage(), *yesnobox(),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "forget"),
             *vmessage("which_text"), *waitmessage(), *waitbuttonpress(),
             *special(SPECIALS["chooseMonForMoveRelearner"]), *waitstate(),
             *compare_var(VAR_0x8004, PARTY_SIZE), *vgoto_if(GE, "done"),
             *special(SPECIALS["isSelectedMonEgg"]),
             *compare_var(VAR_RESULT, 1), *vgoto_if(EQ, "egg"),
             *compare_var(VAR_0x8005, 0), *vgoto_if(EQ, "no_moves"),
             *special(SPECIALS["teachMoveRelearnerMove"]), *waitstate(),
             *define("done"),
             *closemessage(), *release(), *end(),
             *define("forget"),
             *vmessage("forget_text"), *waitmessage(), *yesnobox(),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "tutors"),
             *vmessage("which_text"), *waitmessage(), *waitbuttonpress(),
             *special(SPECIALS["choosePartyMon"]), *waitstate(),
             *compare_var(VAR_0x8004, PARTY_SIZE), *vgoto_if(GE, "done"),
             *special(SPECIALS["isSelectedMonEgg"]),
             *compare_var(VAR_RESULT, 1), *vgoto_if(EQ, "egg"),
             *bufferpartymonnick(0, VAR_0x8004),
             *special(SPECIALS["getNumMovesSelectedMonHas"]),
             *compare_var(VAR_RESULT, 1), *vgoto_if(EQ, "one_move"),
             *vmessage("which_move_text"), *waitmessage(), *waitbuttonpress(),
             *fadescreen(FADE_TO_BLACK),
             *special(SPECIALS["chooseMoveToForget"]), *waitstate(),
             *fadescreen(FADE_FROM_BLACK),
             *compare_var(VAR_0x8005, MAX_MON_MOVES), *vgoto_if(EQ, "done"),
             *special(SPECIALS["bufferMoveDeleterNicknameAndMove"]),
             *vmessage("confirm_text"), *waitmessage(), *yesnobox(),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "declined"),
             *special(SPECIALS["moveDeleterForgetMove"]),
             *say("forgot_text"),
             *define("egg"), *say("egg_text"),
             *define("no_moves"), *say("no_moves_text"),
             *define("one_move"), *say("one_move_text"),
             *define("tutors"),
             *vmessage("tutors_text"), *waitmessage(), *yesnobox(),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "declined"),
             *[b for f in FLAGS["tutors"] for b in clearflag(f)],
             *say("tutored_text"),
             *define("declined"), *say("declined_text"),
         ], texts={
             "remember_text": "Shall I help a POKéMON\nremember a move?",
             "forget_text": "Or shall I make one forget\na move?",
             "which_text": "Which POKéMON should it be?",
             "which_move_text": "Which move should it forget?",
             "confirm_text": "Make {STR_VAR_1} forget\n{STR_VAR_2}?",
             "forgot_text": "{STR_VAR_1} forgot {STR_VAR_2}!",
             "egg_text": "An EGG doesn’t know any\nmoves yet!",
             "no_moves_text": "There’s no move for it to\nremember.",
             "one_move_text": "{STR_VAR_1} knows only one\nmove!",
             "tutors_text": "Or shall I let the move tutors\nteach their moves again?",
             "tutored_text": "Done! Every move tutor will\nteach again.",
             "declined_text": "Come back any time!",
         })),
    dict(id="custom-trade-evolution", source="tradeevo.s",
         card=card(1041, 41, 65, 2, "TRADE EVOLUTION", "No trading partner needed",
                   ("Evolve a POKéMON that evolves", "by trading, right away. Visit", "the deliveryman on the 2nd",
                    "floor of a POKéMON CENTER.")),
         script=party_mon_script(
             "Which POKéMON should evolve?",
             [*native("trade_evolve"),
              *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "cant"),
              *waitstate(),
              *say("done_text"),
              *define("cant"), *say("cant_text")],
             {"done_text": "Take good care of it!",
              "cant_text": "{STR_VAR_1} doesn’t evolve by\ntrading.¶Some POKéMON need to hold an\n"
                           "item when they’re traded."},
             egg="An EGG can’t evolve!")),
    dict(id="custom-espeon-umbreon", source="espeon.s",
         card=card(1063, 63, 196, 3, "ESPEON & UMBREON", "Day or night, no clock needed",
                   ("A friendly EEVEE evolves into", "ESPEON or UMBREON, your pick.", *VISIT)),
         data={"form_items": "ESPEON", "form_umbreon": "UMBREON"},
         # FireRed/LeafGreen stop an evolution past MEW without the National Pokedex.
         script=party_mon_script(
             "Which EEVEE should evolve?",
             [*native("check"),
              *compare_var(VAR_RESULT, 1), *vgoto_if(EQ, "not_eevee"),
              *checkflag(FLAGS["nationalDex"]), *vgoto_if(UNSET, "no_dex"),
              *compare_var(VAR_RESULT, 2), *vgoto_if(EQ, "not_friendly"),
              *vmessage("form_text"), *waitmessage(),
              *native("form_menu"), *waitstate(),
              *compare_var(VAR_RESULT, MENU_B), *vgoto_if(EQ, "declined"),
              *closemessage(),
              *native("evolve"), *waitstate(),
              *specialvar(VAR_RESULT, SPECIALS["getPartyMonSpecies"]),
              *compare_var(VAR_RESULT, SPECIES_EEVEE), *vgoto_if(EQ, "declined"),
              *say("done_text"),
              *define("not_eevee"), *say("not_eevee_text"),
              *define("no_dex"), *say("no_dex_text"),
              *define("not_friendly"),
              *buffernumberstring(1, VAR_0x8005),
              *say("not_friendly_text"),
              *define("declined"), *say("declined_text")],
             {"form_text": "Which form should it take?",
              "done_text": "Take good care of it!",
              "not_eevee_text": "{STR_VAR_1} isn’t an EEVEE!",
              "no_dex_text": "It needs the NATIONAL POKéDEX\nfirst.",
              "not_friendly_text": "{STR_VAR_1}’s friendship is\n{STR_VAR_2}. It evolves at 220.",
              "declined_text": "Come back any time!"},
             egg="An EGG can’t evolve!")),
    dict(id="custom-roamer", source="roamer.s", symbols={"STATE": HOOK_STATE},
         card=card(1042, 42, 245, 4, "ROAMING POKéMON", "Find it, then lure it",
                   ("Find out where the roaming", "POKéMON is and lure it to you.", *VISIT)),
         script=dict(body=[
             *native("roamer_info"),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "none"),
             *vmessage("where_text"), *waitmessage(), *waitbuttonpress(),
             *compare_addr(HOOK_STATE, 1), *vgoto_if(EQ, "following"),
             *vmessage("ask_text"), *waitmessage(), *yesnobox(),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "declined"),
             *native("install"),
             *say("on_text"),
             *define("following"),
             *vmessage("keep_text"), *waitmessage(), *yesnobox(),
             *compare_var(VAR_RESULT, 1), *vgoto_if(EQ, "declined"),
             *writebytetoaddr(0, HOOK_STATE),
             *say("off_text"),
             *define("none"), *say("none_text"),
             *define("declined"), *say("declined_text"),
         ], texts={
             "where_text": "{STR_VAR_1} is roaming\n{STR_VAR_2} right now.",
             "ask_text": "Shall I lure it to you? It will\nfollow you along its routes.",
             "on_text": "Done! Look for it in tall grass\nand on the water.",
             "keep_text": "It’s following you.\nKeep luring it?",
             "off_text": "It will roam on its own again.",
             "none_text": "No POKéMON is roaming right\nnow.",
             "declined_text": "Come back any time!",
         })),
    dict(id="custom-legendary-respawn", source="respawn.s",
         card=card(1043, 43, 150, 7, "LEGENDARY RESPAWN", "A second chance",
                   ("Legendary POKéMON you beat", "but didn’t catch come back.", *VISIT)),
         script=dict(body=[
             *vmessage("ask_text"), *waitmessage(), *yesnobox(),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "declined"),
             *native("respawn"),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "none"),
             *buffernumberstring(0, VAR_RESULT),
             *say("done_text"),
             *define("none"), *say("none_text"),
             *define("declined"), *say("declined_text"),
         ], texts={
             "ask_text": "Shall I bring back the legendary\nPOKéMON you didn’t catch?",
             "done_text": "Done! {STR_VAR_1} legendary POKéMON\ncame back.",
             "none_text": "No legendary POKéMON needs to\ncome back.",
             "declined_text": "Come back any time!",
         })),
    dict(id="custom-travel-anywhere", source="fly.s", symbols={"STATE": HOOK_STATE},
         card=card(1044, 44, 18, 1, "TRAVEL ANYWHERE", "FLY with R, BIKE indoors",
                   ("Press R outdoors to FLY, no", "HM needed, and run and BIKE", "anywhere. Visit the deliveryman",
                    "on 2F of a POKéMON CENTER.")),
         script=hook_toggle("Shall I let you FLY with R and\nrun and BIKE anywhere?",
                            "Done! Outdoors, press R to FLY.\nIt lasts until you reset.",
                            "Travel anywhere is on.\nKeep it on?", "Back to normal travel!", "uninstall")),
    dict(id="custom-pc-anywhere", source="pc.s", symbols={"STATE": HOOK_STATE},
         card=card(1066, 66, 137, 3, "PC ANYWHERE", "Your boxes, one button away",
                   ("Press R in the field to use", "your PC’s POKéMON boxes. Visit", "the deliveryman on the 2nd",
                    "floor of a POKéMON CENTER.")),
         script=hook_toggle("Shall I let you open the PC\nwith R, wherever you are?",
                            "Done! Press R in the field to\nuse the PC, until you reset.",
                            "PC Anywhere is on.\nKeep it on?", "Back to the PCs in POKéMON\nCENTERS!", "uninstall")),
    dict(id="custom-hm-moves", source="fieldmoves.s", symbols={"STATE": HOOK_STATE},
         card=card(1068, 68, 131, 0, "HM MOVES, NO HMs", "Your badges are enough",
                   ("CUT, SURF, STRENGTH and more,", "no POKéMON needs to know them.", *VISIT)),
         script=hook_toggle("Want to use HM moves without\nteaching them?",
                            "Done! Your badges are all you\nneed, until you reset.",
                            "No HMs needed now.\nKeep it that way?", "Back to teaching HMs!")),
    dict(id="custom-reusable-tms", source="tm.s", symbols={"STATE": HOOK_STATE},
         card=card(1045, 45, 137, 6, "REUSABLE TMs", "Teach a TM again and again",
                   ("Teaching a move with a TM no", "longer uses the TM up. Visit", "the deliveryman on the 2nd",
                    "floor of a POKéMON CENTER.")),
         script=hook_toggle("Shall I make your TMs last\nforever?",
                            "Done! Teaching a move won’t use\nup the TM until you reset.",
                            "Your TMs last forever.\nKeep it that way?", "TMs get used up again.", "uninstall")),
    dict(id="custom-physical-special-split", source="split.s", symbols={"STATE": HOOK_STATE},
         card=card(1062, 62, 357, 7, "GEN 4 PHYSICAL/SPECIAL SPLIT", "Moves hit as in later games",
                   ("Each move is physical or", "special on its own, not by its", "type. Visit the deliveryman",
                    "on 2F of a POKéMON CENTER.")),
         script=hook_toggle("Want the physical/special\nsplit?", "Done! On until you reset.",
                            "The split is on.\nKeep it on?", "Back to the old way!")),
    dict(id="custom-exp-share", source="expshare.s", symbols={"STATE": HOOK_STATE},
         card=card(1067, 67, 242, 4, "EXP. SHARE FOR ALL", "The whole party grows",
                   ("Every POKéMON in your party", "gets EXP. from each battle.", *VISIT)),
         script=hook_toggle("Shall your whole party get EXP.\nfrom every battle?",
                            "Done! Those that battle get all\nthe EXP., the rest get half.¶It lasts until you reset.",
                            "Your whole party gets EXP.\nKeep it that way?", "Back to the old way!")),
    # Event Pokemon PKHeX's table leaves out (eggs, Japanese releases): EVENT picks one in eventmon.s.
    *[dict(id=f"custom-{key}", source="eventmon.s", symbols={"EVENT": event},
           card=card(1069 + event - 11, 69 + event - 11, icon, bg, title, subtitle, body),
           script=event_mon_script(name) if name else event_mon_script(None, OFFER_MON, texts))
      for key, event, icon, bg, name, title, subtitle, body, texts in (
          ("box-eggs", 12, 412, 4, None, "POKéMON BOX EGGS", "EGGS with special moves",
           ("SWABLU, ZIGZAGOON, SKITTY or", "PICHU with a special move:", "choose one on 2F of a", "POKéMON CENTER."),
           {"offer_text": "Would you like a {STR_VAR_1}\nEGG?", "received_text": "{PLAYER} received an EGG!",
            "already_text": "Receive the card again for\nanother EGG!"}),
          ("colosseum-pikachu", 13, 25, 5, "PIKACHU", "COLOSSEUM PIKACHU", "From Japan’s BONUS DISC",
           ("The PIKACHU of the Japanese", "COLOSSEUM BONUS DISC.", *VISIT), None),
          ("ageto-celebi", 14, 251, 3, "CELEBI", "AGETO CELEBI", "From Japan’s BONUS DISC",
           ("The CELEBI of the Japanese", "COLOSSEUM BONUS DISC.", *VISIT), None),
          ("mattle-ho-oh", 15, 250, 7, "HO-OH", "MATTLE HO-OH", "The MT. BATTLE prize",
           ("The HO-OH COLOSSEUM gave for", "winning 100 MT. BATTLE fights.", *VISIT), None))],
    dict(id="custom-gift-box",
         card=card(1061, 61, 113, 2, "GIFT BOX", "Money, candy and more",
                   ("¥100,000, 99 RARE CANDIES and", "1,000 COINS. Visit the", "deliveryman on the 2nd floor",
                    "of a POKéMON CENTER.")),
         # Once per card. RARE CANDIES need room in the bag, COINS a COIN CASE.
         script=dict(body=[
             *checkflag(FLAGS["mysteryGiftDone"]), *vgoto_if(EQ, "already"),
             *setflag(FLAGS["mysteryGiftDone"]),
             *addmoney(100000),
             *playfanfare(SONG_GIFT_MON), *vmessage("money_text"), *waitmessage(), *waitfanfare(),
             *waitbuttonpress(),
             *checkitemspace(ITEM_RARE_CANDY, 99),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "no_room"),
             *additem(ITEM_RARE_CANDY, 99),
             *vmessage("candy_text"), *waitmessage(), *waitbuttonpress(),
             *define("coins"),
             *checkitem(ITEM_COIN_CASE),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "done"),
             *addcoins(1000),
             *compare_var(VAR_RESULT, 0), *vgoto_if(NE, "done"),
             *vmessage("coins_text"), *waitmessage(), *waitbuttonpress(),
             *define("done"),
             *closemessage(), *release(), *end(),
             *define("no_room"),
             *vmessage("no_room_text"), *waitmessage(), *waitbuttonpress(),
             *vgoto("coins"),
             *define("already"), *say("already_text"),
         ], texts={
             "money_text": "{PLAYER} received ¥100,000!",
             "candy_text": "{PLAYER} received 99 RARE\nCANDIES!",
             "no_room_text": "There’s no room in your bag\nfor 99 RARE CANDIES!",
             "coins_text": "{PLAYER} received 1,000 COINS!",
             "already_text": "Receive the card again for\nanother GIFT BOX!",
         })),
    # RAF's Pocket Casino. The slot machine returns to the field, which moves SaveBlock1, so the
    # script moves first.
    dict(id="custom-pocket-casino", source="casino.s",
         script=dict(body=[
             *setvar(VAR_TEMP_1, 0), *setvar(VAR_TEMP_4, 0),
             *checkflag(FLAGS["gotCoinCase"]), *vgoto_if(EQ, "case"),
             *setflag(FLAGS["gotCoinCase"]), *setvar(VAR_TEMP_4, 1),
             *define("case"),
             *checkitem(ITEM_COIN_CASE),
             *compare_var(VAR_RESULT, 0), *vgoto_if(NE, "coins"),
             *checkitemspace(ITEM_COIN_CASE),
             *compare_var(VAR_RESULT, 0), *vgoto_if(EQ, "coins"),
             *additem(ITEM_COIN_CASE), *setvar(VAR_TEMP_1, 1),
             *define("coins"),
             *setvar(VAR_TEMP_3, 0),
             *checkcoins(VAR_TEMP_2),
             *compare_var(VAR_TEMP_2, 3), *vgoto_if(GE, "greet"),
             *addcoins(100), *setvar(VAR_TEMP_3, 1),
             *define("greet"),
             *compare_var(VAR_TEMP_1, 1), *vgoto_if(EQ, "lent"),
             *compare_var(VAR_TEMP_3, 1), *vgoto_if(EQ, "given"),
             *vmessage("play_text"), *vgoto("play"),
             *define("lent"),
             *compare_var(VAR_TEMP_3, 1), *vgoto_if(EQ, "lent_given"),
             *vmessage("lent_text"), *vgoto("play"),
             *define("lent_given"),
             *vmessage("lent_given_text"), *vgoto("play"),
             *define("given"),
             *vmessage("given_text"),
             *define("play"),
             *waitmessage(), *waitbuttonpress(), *closemessage(),
             *playbgm(SONG_GAME_CORNER),
             *specialvar(VAR_RESULT, SPECIALS["slotMachineId"]),
             *relocate(),
             *playslotmachine(VAR_RESULT),
             *compare_var(VAR_TEMP_4, 1), *vgoto_if(NE, "flag_kept"),
             *clearflag(FLAGS["gotCoinCase"]),
             *define("flag_kept"),
             *compare_var(VAR_TEMP_1, 1), *vgoto_if(NE, "done"),
             *removeitem(ITEM_COIN_CASE),
             *vmessage("return_text"), *waitmessage(), *waitbuttonpress(), *closemessage(),
             *define("done"),
             *release(), *end(),
         ], texts={
             "lent_given_text": "A COIN CASE and 100 COINS,\njust for this game.",
             "lent_text": "You can borrow a COIN CASE,\njust for this game.",
             "given_text": "Here are 100 COINS to play.",
             "play_text": "Heh heh, looks like someone\nwants to play some slots.",
             "return_text": "I will take the COIN CASE back.\nYour COINS stay with you.",
         })),
]


def no_encounters_script(symbols):
    """sWildEncountersDisabled, which the game clears only at boot and after the recap on Continue;
    and a REPEL's step count."""
    return dict(body=[
        *vmessage("ask_text"), *waitmessage(),
        *native("choice_menu"), *waitstate(),
        *compare_var(VAR_RESULT, 1), *vgoto_if(EQ, "weaker"),
        *compare_var(VAR_RESULT, 2), *vgoto_if(EQ, "none"),
        *compare_var(VAR_RESULT, 0), *vgoto_if(NE, "declined"),
        *writebytetoaddr(1, symbols["WILD_ENCOUNTERS_DISABLED"]),
        *say("all_text"),
        *define("weaker"),
        *writebytetoaddr(0, symbols["WILD_ENCOUNTERS_DISABLED"]),
        *setvar(VAR_REPEL_STEPS, 0xFFFF),
        *say("weaker_text"),
        *define("none"),
        *writebytetoaddr(0, symbols["WILD_ENCOUNTERS_DISABLED"]),
        *setvar(VAR_REPEL_STEPS, 0),
        *say("none_text"),
        *define("declined"),
        *say("declined_text"),
    ], texts={
        "ask_text": "Which wild POKéMON should\nstay away?",
        "all_text": "None will appear until you\nturn off your game.",
        "weaker_text": "Like a REPEL that lasts\n65,535 steps!",
        "none_text": "Wild POKéMON are back to\nnormal!",
        "declined_text": "Come back any time!",
    })


# struct WonderCard text: title, subtitle, four body lines, two footer lines, 40 bytes each from byte 10.
CARD_TEXT_AT, CARD_TEXT_BYTES = 10, 40


def set_card_text(data, field, text):
    encoded = encode_text(text)
    if len(encoded) > CARD_TEXT_BYTES:
        raise ValueError(f"card text too long: {text}")
    at = CARD_TEXT_AT + CARD_TEXT_BYTES * field
    data[at:at + CARD_TEXT_BYTES] = bytes(encoded) + b"\xff" * (CARD_TEXT_BYTES - len(encoded))


def wonder_card(spec):
    data = bytearray(b"\xff" * WONDER_CARD_BYTES)
    data[0:10] = bytes([*u16(spec["flagId"]), *u16(spec["iconSpecies"]), *u32(spec["idNumber"]),
                        spec["bgType"] << 2, 0])
    for field, text in enumerate([spec["title"], spec["subtitle"], *spec["body"], *spec["footer"]]):
        set_card_text(data, field, text)
    data[330] = data[331] = 0
    return bytes(data)


def kept_card(card_id, subtitle):
    """A card kept from the original file (kept/), its footer replaced, and the subtitle when given."""
    data = bytearray((SRC / "kept" / f"{card_id}.card").read_bytes())
    for i, text in enumerate(FOOTER):
        set_card_text(data, 6 + i, text)
    if subtitle:
        set_card_text(data, 1, subtitle)
    return bytes(data)


def _run(*args):
    subprocess.run(args, check=True, capture_output=True)


def assemble(source, symbols, work, data=None):
    """-> (bytes, {label: offset}) for a source in vendor/gblink-cards; `data` becomes data.inc."""
    if data:
        strings, tokens = data
        include = "".join(f"    .align 2\n{label}:\n    .byte {', '.join(map(str, encode_text(text, tokens)))}\n"
                          for label, text in strings.items())
        (work / "data.inc").write_text(include + "    .align 2\n")
    obj, elf, binary = work / "out.o", work / "out.elf", work / "out.bin"
    defsyms = [x for key, value in symbols.items() for x in ("--defsym", f"{key}={value}")]
    _run("arm-none-eabi-as", "-mcpu=arm7tdmi", "-mthumb", "-I", str(SRC_ASM), "-I", str(work), *defsyms,
         "-o", str(obj), str(SRC_ASM / source))
    _run("arm-none-eabi-ld", "-Ttext=0", "-o", str(elf), str(obj))
    _run("arm-none-eabi-objcopy", "-O", "binary", str(elf), str(binary))
    labels = {}
    nm = subprocess.run(["arm-none-eabi-nm", str(elf)], check=True, capture_output=True, text=True).stdout
    for line in nm.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[1] in "tT":
            value, _, name = fields
            labels[name] = int(value, 16)
    return binary.read_bytes(), labels


def layout(items, base):
    """Bytes, {define} labels, {label} (4-byte address from `base`), {align} and {u16_from} items."""
    def size(item, at):
        if isinstance(item, dict):
            if "label" in item:
                return 4
            if "align" in item:
                return -at & (item["align"] - 1)
            return item.get("size", 1)
        return 1
    labels, at = {}, 0
    for item in items:
        if isinstance(item, dict) and "define" in item:
            if item["define"] in labels:
                raise ValueError(f"label {item['define']} defined twice")
            labels[item["define"]] = at
        else:
            at += size(item, at)
    out = bytearray()
    for item in items:
        if isinstance(item, dict):
            if "define" in item:
                continue
            if "label" in item:
                out += bytes(u32(base + labels[item["label"]]))
            elif "align" in item:
                out += bytes(size(item, len(out)))
            else:
                out += bytes(item["bytes"](labels, len(out)))
        else:
            out.append(item)
    return bytes(out)


def build_script(card_def, rom_id, work):
    rom = ROMS[rom_id]
    symbols = {**rom["symbols"], **FAMILY_SYMBOLS, "JAPANESE": int(rom["language"] == "J"), "GAME_LANGUAGE": LANGUAGE_IDS[rom["language"]]}
    script = card_def["script"] or no_encounters_script(symbols)
    code = None
    if card_def.get("source"):
        data_text = card_def.get("data")
        if data_text and rom["language"] == "J":
            data_text = {key: text.replace("é", "e") for key, text in data_text.items()}
        data = (data_text, card_def.get("tokens", PLACEHOLDERS)) if data_text else None
        code = assemble(card_def["source"], {**symbols, **card_def.get("symbols", {}), "TEXT_BUFFER": TEXT_BUFFER,
                                             "RELOCATED": RELOCATED, "MENU_LIST": MENU_LIST,
                                             "SCRIPT_IN_SB1": SB1_SCRIPT}, work, data)
        labels = code[1]
        # A hook's copy must end below its STATE (0x0203FF60), which sits below pokeldn's at 0x0203FF80.
        if "resident" in labels and RESIDENT + labels["resident_end"] - labels["resident"] > HOOK_STATE:
            raise ValueError(f"{card_def['id']}: the resident copy runs past {HOOK_STATE:#x}")
    trampoline = assemble("trampoline.s", {}, work)[0] if code else b""
    load_trampoline = [b for i in range(len(trampoline) // 4)
                       for b in loadword(i, int.from_bytes(trampoline[4 * i:4 * i + 4], "little"))]

    def expand(item):
        # callnative to the trampoline, then the routine's distance from callnative's operand + 2.
        if not (isinstance(item, dict) and "native" in item):
            return [item]
        routine = code[1][item["native"]]
        return [*callnative(rom["symbols"]["SCRIPT_CONTEXT"] + CONTEXT_DATA + 1),
                {"size": 2, "bytes": lambda labels, at, r=routine: u16(labels["code"] + r + 1 - (at - 2))}]

    texts = {**script["texts"], "wrong_rom_message": ("Wrong game." if rom["language"] == "J"
             else "This gift doesn’t work with\nthis version of the game.")}
    if rom["language"] == "J" and "which_text" in texts:
        texts["which_text"] = "Choose a POKEMON."
    if rom["language"] == "J":
        from pokeldn.frlg.text import charmap
        texts = {key: charmap.japanese_roman_message(text, page_break="¶")
                 for key, text in texts.items()}
    items = [
        *setvaddress(VIRTUAL_BASE), *lock(), *faceplayer(),
        # The ROM header must name exactly this cartridge: game letter, language, revision.
        *compare_addr(ROM_GAME, rom["game"]), *vgoto_if(NE, "wrong_rom"),
        *compare_addr(ROM_LANGUAGE, rom["language"]), *vgoto_if(NE, "wrong_rom"),
        *compare_addr(ROM_REVISION, rom["revision"]), *vgoto_if(NE, "wrong_rom"),
        *load_trampoline,
        *script["body"],
        *define("wrong_rom"), *say("wrong_rom_message"),
        *text_items(texts),
        *([{"align": 4}, {"define": "code"}, *code[0]] if code else []),
    ]
    out = layout([x for item in items for x in expand(item)], VIRTUAL_BASE)
    if len(out) > RAM_SCRIPT_BYTES:
        raise ValueError(f"{card_def['id']} {rom_id}: the script is {len(out)} bytes, over {RAM_SCRIPT_BYTES}")
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reference", nargs="?", type=pathlib.Path,
                        help="with GBLINK_REFERENCE set: the directory of their built .bin payloads")
    args = parser.parse_args()
    if REFERENCE and args.reference is None:
        parser.error("GBLINK_REFERENCE needs the directory of their payloads")
    if REFERENCE:
        ref = args.reference
        bad = 0
        with tempfile.TemporaryDirectory() as tmp:
            for card_def in CARDS:
                theirs = (ref / f"{card_def['id']}.bin").read_bytes()
                ours = build_script(card_def, "BPRE", pathlib.Path(tmp))
                card_ok = "card" not in card_def or wonder_card(card_def["card"]) == theirs[:WONDER_CARD_BYTES]
                same = theirs[336:336 + len(ours)] == ours and card_ok
                bad += not same
                print(card_def["id"], "same" if same else f"DIFFERS card_ok={card_ok}")
        sys.exit(bad)
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        for card_def in CARDS:
            card_bytes = (wonder_card(card_def["card"]) if "card" in card_def
                          else kept_card(card_def["id"], card_def.get("subtitle")))
            scripts = {rom_id: build_script(card_def, rom_id, pathlib.Path(tmp)).hex() for rom_id in ROMS}
            out[card_def["id"]] = {"card": card_bytes.hex(), "scripts": scripts}
            print(card_def["id"], *(len(s) // 2 for s in scripts.values()), file=sys.stderr)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
