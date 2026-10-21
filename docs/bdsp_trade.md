---
title: The Union Room trade
parent: Brilliant Diamond and Shining Pearl
nav_order: 3
---

# The BDSP trade

A BDSP Union Room trade exchanges one Pokemon between two stations in five messages, then runs a
security phase that writes the save. The approach and the greeting are on
[The game protocol](bdsp_protocol.md). Addresses are 1.3.0 `main`.

## The message sequence

    NetDataTransitionData{transitionType: 18}     entering the trade
    NetDataTradeTranerData        32 B            who they are
    NetTradePokeData             328 B            the Pokemon
    NetDataTradePokeCheckOkData    1 B, value 1   "yours is fine"
    NetDataTradeReadyOkData        2 B            the last message before the exchange

Each is answered with one of the client's own. The console's check-ok is always 1; it never refuses
a Pokemon through this message.

In local wireless the console checks the player's own pick only for the save's illegal flag
([Duplicate detection](#duplicate-detection)). `SS_box_182` ("Un problème avec votre Pokémon rend
tout échange impossible.") refuses a flagged pick. Server validation runs only
when `UnionFrontDeskStateController.isGlobal` is set: `NetworkManager$$RequestValidateTrade`
[0x02251cb0] sends each `CoreParam` in a 0x148-byte request (`IlcaNetServerValidate.CheckRequestAutoAsync`
[0x027318c0]); the reply `ValidateResultID` is None, InvalidData, SignatureError or ProcessError, and
the last two raise an error dialog. `SS_box_181` refuses the partner's flagged Pokemon.

## The trade state machine

`UnionTradeManager.currentState` (+0x80) is
`TradeFlowState {NONE 0, SELECT_WINDOW 1, SECURIY_TRADE 2, PLAY_DEMO 3, END 4}`. A Pokemon is taken
only in SELECT_WINDOW. A ready-ok (0x21) goes in SELECT_WINDOW to
`TradeSelectPokeModel$$ReciveReadyOk` [0x1c27d40], in SECURIY_TRADE to
`TradeSecurityController$$ReciveState`, and is dropped elsewhere.

The console leaves SELECT_WINDOW when its own and the peer's `tradeState` (the 0x21's second byte)
are both 2 (`WAIT`), then sends its own 0x21 with `tradeState` 0. Only the peer's 0x21 moves it out.

### Box phases, and the messages that reset a round

`BoxWindow.NetTradePhase`:

    None 0, WaitSave 1, PlayerSelecting 2, WaitSend 3, OtherPokeConfirm 4, WaitOtherDecide 5,
    LastConfirm 6, WaitTrading 7, Complete 8, WaitClose 9, CancelOther 10, Error 11

The reset (`TradeSelectPokeModel$$ReciveReturnSelectPoke` [0x1c27f00]) clears both Pokemon and both
trade states; from phase 3 on the box returns to phase 2 and shows `SS_box_588` ("L'autre joueur a
choisi d'annuler l'échange."). A received `NetDataReturnSelectData{1}` is answered with `{0}`.

| message from the peer | box phase | what the console does |
|---|---|---|
| check-ok (0x46) | below 6 | records the peer's check |
| check-ok (0x46) | 6 `LastConfirm` or later | the reset |
| ready-ok (0x21), SELECT_WINDOW | phase 5 or below | the reset |
| ready-ok (0x21), SELECT_WINDOW | phase 6 or later | records the peer's state; later copies are dropped |
| return-select (0x45), either value | any, outside PLAY_DEMO | the reset |

The latch (+0x71, `<isLoadingBox>k__BackingField`; drop at [0x1c342e4], set at [0x1c3435c]) is
cleared by `Init`, `WaitBoxWindowComplete`, `Cancel`, `RecivePokeData` and `ReciveCancelData`; its
setter [0x1c33040] has no caller. The reset sets `UnionWork` +0x50 (`boxState`) to 6 `CANCEL_SELECT`
[0x1c28030], which `BoxWindow$$UpdateNetworkTrade` [0x2121628] consumes [0x2121c64].

When the player backs out (`onCancelSelect`, `b__54_5` 0x1c28620; send at [0x1c286a4]), the console sends `{1}` and waits for a fresh `NetTradePokeData`; the
partner's `{0}` does not release it.

- Answer each console check-ok once; a copy answered after `LastConfirm` resets the round. A
  receiver drops a reliable id already delivered (`pokeldn.ldn.reliable5.Reassembler`).
- Answer `45 0001 01` with `45 0001 00`. Never send a 0x45 after the replacement Pokemon has gone
  out or after the console's re-pick: it wipes the round.
- In the select window a 0x21 before the console's last confirmation is a cancel. Stop a
  security-state repeater before the console can be back in its select window.

## The security phase

`TradeStateModel` owns the save:

    NONE 0, INIT 1, WAIT 2, SEND_POKE 3, WAIT_POKE 4,
    SEND_READYOK 5, WAIT_READYOK 6, START_WRITE_SAVE 7, WRITEING_SAVE 8

In this phase the peer's Pokemon message only triggers the next step: the console uses the Pokemon
the player confirmed on the full-screen view, and WAIT_POKE never ends before that confirmation.

### Who leads: the rarer Pokemon

The role, PARENT or CHILD, is set when the peer's Pokemon arrives
(`TradeSecurityController$$CheckPokeRarity` [0x1c25060]) from each species' rarity:

| rarity | species |
|---|---|
| 3 | 151, 251, 385, 386, 489, 490, 491, 492, 493 (the mythicals) |
| 2 | 150, 249, 250, 382, 383, 384, 483, 484, 487 (the box legendaries) |
| 1 | 144, 145, 146, 243, 244, 245, 377-381, 480, 481, 482, 485, 486, 488 |
| 0 | anything else |

`Dpr.SubContents.Utils$$GetPokeRarityNum` [0x1cbe560] walks three `MonsNo[]` lists (rarity 3 at
0x1cbe614, 2 at 0x1cbe698, 1 at 0x1cbe71c, none 0x1cbe730) filled by `Utils$$.cctor` [0x1cbe9a0] from
`global-metadata.dat` `0x666aa6`, `0x666b06`, `0x667c39` (static fields +0x78, +0x80, +0x88). The rarer side is PARENT; on a tie the recruiter is PARENT. A Dialga offered against a console's Mew
leaves the console PARENT.

`TradeParentStateModel$$StateProc` [0x1c23350], table 0x3d80f2f, and
`TradeSecurityController$$ReciveState` [0x1c24f10], table 0x3d80f39, drive it:

    2 WAIT            peer at WAIT                           -> 3
    3 SEND_POKE       send the Pokemon                       -> 4
    4 WAIT_POKE       peer Pokemon confirmed                 -> 5
    5 SEND_READYOK    PARENT sends its state; CHILD waits for a peer 5 or 6   -> 6
    6 WAIT_READYOK    one more peer message                  -> 7
    7 START_WRITE_SAVE, 8 WRITEING_SAVE

A CHILD console at SEND_READYOK waits silently, so a client that echoes WAIT_POKE deadlocks it.
`room.mirror_trade_state` answers WAIT_POKE with SEND_READYOK, which works in either role
(`tests/test_bdsp_trade_states.py` models both functions under random latencies).

Send one message per reliable sequence id: later messages under one id look like retransmits and
are discarded.

## The completed trade

The console's state, then the client's answer:

    their READY-OK {tradeState 2}  ->  the client's READY-OK
    INIT          ->  WAIT
    WAIT          ->  WAIT
    SEND_POKE     ->  SEND_POKE, and its Pokemon
    WAIT_POKE     ->  WAIT_POKE
    SEND_READYOK  ->  SEND_READYOK
    WAIT_READYOK  ->  SEND_READYOK

The console then writes the save, plays the animation and sends only `NetCharacterStateData`. The
client repeats its state once a second only until the console's SEND_READYOK
(`room.repeats_trade_state`); a 0x21 after it lands in the next select window and resets the round.
The station must not leave in this window: a drop lands the console between `FirstSave` and
`SecondSave` ([The disconnect penalty](#the-disconnect-penalty)).

The animation starts about 2.7 s after `tradeState` 6, the received Pokemon appears at about 18.6 s
and the player has control at about 29 s. A completed trade ends with no message; the next round
starts with the console's next `NetTradePokeData`. Trades chain in one association in both roles.

## The Pokemon

`NetTradePokeData` carries 328 bytes, an encrypted PB8 in the format on
[the Sword/Shield page](swsh_protocol.md#the-pk8) (`pokeldn/gen8.py`, `pokeldn/bdsp/pokemon.py`).
The checksum at 0x06 cannot detect a wrong block order.

`NetDataTradeTranerData` ([Framing](bdsp_protocol.md#framing)):

    0x00  26  tranerName, UTF-16LE, NUL-terminated
    0x1a   4  tranerId, the full 32-bit id, secret id in its high half
    0x1e   1  cassetVersion, the save's version (49)
    0x1f   1  langId, the save's language (3)

The console sends it before any Pokemon; a gift made for the receiving player reads it
(`room.traner_trainer`, [Made for the receiving player](gift_simulated.md#made-for-the-receiving-player)).
It carries no gender. The trade screen names the partner from it; the greeting uses the Pia player
name ([the protocol page](bdsp_protocol.md#the-name-in-the-greeting)). The ten bytes after the
name's terminator are heap residue; `room.build_trade_traner` copies the console's own.

An offer is a real Pokemon with named fields changed (`pokemon.build_from`).

## What the console does to a received Pokemon

`TradeStateModel$$ReplacePoke` [0x1c29120] compares the Pokemon's OT gender, 32-bit id and OT name
with the receiving save (`CoreParam$$UpdateOwnerInfo` [0x2495920]):

| comparison | effect |
|---|---|
| all three match | the handler flag is cleared; `IsNicknamed` (0x08F bit 7) is set when the name differs from the species name |
| otherwise | handler set from the save: name 0x0A8, gender 0xC2, language 0x0C3, `CurrentHandler` 0x0C4 = 1, friendship 0x0C8 = species base, memories zeroed |

The checksum follows. `ot_name` and 0xC6 are untouched. The GTS, in-game trades and Mystery Gift
write the handler the same way. The game holds no Pokemon HOME code.

### Duplicate detection

`PokeDupeChecker` (1.3.0) flags a duplicated Pokemon: bit 0 of decrypted PB8 byte 0x52, PKHeX's
`PB8.IsDprIllegal`. A flagged Pokemon cannot be traded and the flag is never cleared.

The check (`UpdateIllegalFlagAll` [`0x01de5860`]) walks the party, boxes 1 to 40 and the daycare
in order, on save load and on each pick in the trade box; nothing runs when a trade is received.
It covers non-egg Brilliant Diamond and Shining Pearl Pokemon that are not in-game trades. A later
copy is flagged when all of these match an earlier one:

| field | accessor | PB8 offset |
|---|---|---|
| encryption constant | `GetPersonalRnd` | 0x00 |
| PID | `GetColorRnd` | 0x1C |
| trainer id (TID16, SID16) | `GetID` | 0x0C |
| nature | `GetSeikaku` | 0x20 |
| the six IVs | `GetTalentHp` .. | 0x8C |

Comparison: `IsDuplicatedPokemonParam` [`0x01de62f0`], per Pokemon `CheckDuplicate` [`0x01de59d0`];
in-game trade test `IsLocalKoukanPokemonParam` [`0x01de66d0`]; hyper-training check
`UpdateIllegalSpecialTraining` [`0x01de6830`]; trade-box call [`0x01c28310`]; flag setter
`CoreDataBlockA.set_dpr_illegal_flag` `0x027bb040`.

A Ninjask (291) and Shedinja (292) pair is never a duplicate. A BDSP Pokemon at level 99 or lower
with any hyper-training bit set is also flagged.

Never offer a BDSP record whose encryption constant, PID, trainer id, nature and IVs all match a
Pokemon in the receiving save. `bin/bdsp_host.py --fresh-pid` draws a new encryption constant and
PID, shiny state kept.

## The disconnect penalty

A station dropping out between `FirstSave` (penalty counter 30, time stored) and `SecondSave`
(counter 0) leaves the console refusing new local trades with "vous ne pouvez pas faire d'echange en
reseau pour le moment" (`UnionFrontDeskStateController$$CheckPenarty` 0x1fcc400). A penalty means
the console wrote its save.

The penalty clock (`UnionWork$$CheckDateTime` [0x1dd3e30], `SetPenartyTime` [0x1dd32d0]; `FirstSave`
0x1cd4fc0, `SecondSave` 0x1cd5030) is an unweighted sum, `Year + Month + Day + Hour + Minute + Second`, and clears
once it exceeds the stored sum by 30. The sum falls 58 when a minute or hour wraps, so a penalty
armed late in an hour can last until the next day or beyond.

Never change the console's clock or a system setting to clear it: BDSP detects the change and locks
time-based features for a day. Moving the clock back restores the penalty; only `SecondSave` zeroes
the counter.
