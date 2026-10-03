---
title: The Union Room trade
parent: Brilliant Diamond and Shining Pearl
nav_order: 3
---

# The BDSP trade

A retail Shining Pearl trades with a character pokeldn invented, takes a Pokemon pokeldn assembled
and writes its save. The approach and the greeting are on [The game protocol](bdsp_protocol.md).

## The message sequence

    NetDataTransitionData{transitionType: 18}     entering the trade
    NetDataTradeTranerData        32 B            who they are
    NetTradePokeData             328 B            the Pokemon
    NetDataTradePokeCheckOkData    1 B, value 1   "yours is fine"
    NetDataTradeReadyOkData        2 B            the last message before the exchange

Each is answered with one of the client's own.

The console's only live check-ok sender is `TradeSelectPokeModel.<OpenTradeBoxWindow>b__54_2`
[1.3.0 main 0x1c28520], the `onDecide` of `BoxWindow$$Open(otherName, msgLangId, onSelected,
onDecide, onConfirm, onComplete, onCancelSelect, ...)` (lambdas `b__54_1` to `b__54_5`). It sets its own check state (+0x80) to 6, sends `{isCheckOk: 1}` to
`tradeTargetIndex` (+0x48), and sets `isWaitingOK` (+0x7b) 1 and `isWaitingSelect` (+0x7c) 0
[0x1c285a4]. `isCheckOk` is always 1: the console never refuses a Pokemon through this message
(`SendTradePokeCheckOk` [0x1c27cb0] has no caller). `BoxWindow$$OnTradeContextMenu` invokes
`onDecide` [0x212e99c], then advances the box's trade phase by one [0x212e9dc].

`TradeSelectPokeModel$$PokeSelectWait` [0x1c26070] shows the peer's Pokemon once the box phase is
past 2 and both the received (+0x78) and own-pick (+0x79) flags are set; nothing checks it. `TradePokeCheckOkWait` [0x1c25f50] moves on when both check states
(+0x80 own, +0x84 peer) are 6. A Pokemon the reliable window acknowledges and never delivers leaves
the player on "en attente d'une réponse" with no error
([The Pia layer](pia.md#what-the-receiver-discards-in-silence)).

In local wireless the player's own pick is checked only for the save's illegal flag
(`CoreParam$$GetDprIllegalFlag`); `NetworkManager$$RequestValidateTrade` runs only when
`UnionFrontDeskStateController.isGlobal` is set.

## The trade state machine

`UnionTradeManager.currentState` (+0x88; +0x80 in 1.3.0) is
`TradeFlowState {NONE 0, SELECT_WINDOW 1, SECURIY_TRADE 2, PLAY_DEMO 3, END 4}`:

    UnionTradeManager$$RecivePokeData          0x1dd2800   currentState == SELECT_WINDOW only
    UnionTradeManager$$SetTargetTranerParam    0x1dd2130   TargetTranerParam{uint id, string name}
    UnionTradeManager$$ReciveTradeReadyOkData  0x1dd2a70   routed on the same field

A Pokemon is taken only in SELECT_WINDOW, into `tradeSelectModel.targetPokemonParam` with
`isRecivePokeParam` set. A `NetDataTradeReadyOkData` (0x21) goes in SELECT_WINDOW to
`TradeSelectPokeModel$$ReciveReadyOk` ([Box phases](#box-phases-and-the-messages-that-reset-a-round)),
in SECURIY_TRADE to `TradeSecurityController$$ReciveState` (in 1.3.0 [0x1c34290] only when the
controller's `GetCurrentState` is non-zero; at 0 it calls `SettingSecurityControllerParam`
[0x1c343f4] and drops the message), and is dropped elsewhere.

`ReciveReadyOk` [1.3.0 0x1c27d40] copies the message's second byte, `tradeState`, into
`targetTradeState` (+0x78; +0x84 in 1.3.0, where a received check-ok also writes 6); `isTradeOk` is
never read. `UnionTradeManager.<WaitBoxWindowComplete>d__24` waits until `myTradeState` (+0x74, set
by the player's `MyReadyOk`) and `targetTradeState` are both 2 (`WAIT`), then sets `currentState` to
SECURIY_TRADE, clears the select model and sends its own 0x21 with `tradeState` 0. Only the peer's
0x21 moves the console out of SELECT_WINDOW.

### Box phases, and the messages that reset a round

`BoxWindow.NetTradePhase`:

    None 0, WaitSave 1, PlayerSelecting 2, WaitSend 3, OtherPokeConfirm 4, WaitOtherDecide 5,
    LastConfirm 6, WaitTrading 7, Complete 8, WaitClose 9, CancelOther 10, Error 11

`WaitSave` writes nothing: `BoxWindow.<WaitTradeSave>d__203` counts `FieldCommonParam[0xEB]` * 0.001
seconds down against `Time.deltaTime`.

The reset is `TradeSelectPokeModel$$ReciveReturnSelectPoke` [1.3.0 main 0x1c27f00]. For
`isReturnSelect` 1 it answers `NetDataReturnSelectData{0}` [0x1c27f48], so a console answers every
`{1}` with a `{0}`. In every case it clears `isWaitingOK`/`isWaitingSelect` [0x1c27fb0],
`isRecivePokeParam`/`isSendPokeParam` [0x1c2803c] and both trade states [0x1c28040], and sets
`UnionWork` static +0x50 (`boxState`) to 6, `CANCEL_SELECT` [0x1c28030]. At box phase 3 or later, or
with no box, it then calls `CloseOverUIWindows` [0x1c28168].

`BoxWindow$$UpdateNetworkTrade` [0x2121628] takes and clears `CANCEL_SELECT` [0x2121c64]: at phase 2
it drops an unconfirmed highlight; at any other [0x21225b0] it closes its windows, sets phase 2 and
shows `SS_box_588` ("L'autre joueur a choisi d'annuler l'échange.").

| message from the peer | box phase | what the console does |
|---|---|---|
| check-ok (0x46) | no box, or below 6 | peer check state (+0x84) = 6 (`ReciveTradePokeCheckOk` 0x1c34630) |
| check-ok (0x46) | 6 `LastConfirm` or later | the reset as for `{1}` [0x1c34718], then `securityController?.ResetTradeState()` |
| ready-ok (0x21), SELECT_WINDOW | latch +0x71 set | dropped [0x1c342e4] |
| ready-ok (0x21), SELECT_WINDOW | box present, phase 5 or below | the reset as for `{1}` [0x1c3440c], then `ResetTradeState()` |
| ready-ok (0x21), SELECT_WINDOW | phase 6 or later, or no box | `ReciveReadyOk`, latch +0x71 = 1 [0x1c3435c] |
| return-select (0x45), either value | 2 `PlayerSelecting` | the reset; the box drops an unconfirmed highlight |
| return-select (0x45), either value | 3 or later | the reset; the box returns to phase 2 and shows `SS_box_588` |
| return-select (0x45) | any, in PLAY_DEMO | no reset; [0x1c345c0] clears `targetDemoPokemonParam` |

The latch (+0x71, `<isLoadingBox>k__BackingField`) is cleared by `Init`, `WaitBoxWindowComplete`,
`Cancel`, `RecivePokeData` and `ReciveCancelData`; its setter [0x1c33040] has no caller. The console sends its own
ready-ok when its box closes after the last confirmation (`b__54_4` -> `BoxCloseComplete` ->
`MyReadyOk` 0x1c26d90 -> `SendReadyOk` 0x1c26f14).

The console's own back-out, `onCancelSelect` (`b__54_5` 0x1c28620), sets the box to phase 2
(`ToNextPhase(box, 2)`; a non-zero argument is stored at `[[box+0x390]+0x50]`, 0 adds one), sends
`NetDataReturnSelectData{1}` [0x1c286a4] and clears the waiting flags, the Pokemon flags and both
trade states, without setting `CANCEL_SELECT`. It then waits for a fresh `NetTradePokeData` (the
only setter of `isRecivePokeParam` is `UnionTradeManager$$RecivePokeData`, in SELECT_WINDOW, any
phase [0x1c33e9c]); the partner's `{0}` does not release it.

- Answer each console check-ok once. A copy answered after the first answer moved the box to
  `LastConfirm` resets the round. The reliable window keeps the first message for an id
  ([the Pia page](pia.md#what-the-receiver-discards-in-silence)); the 322 repeated ids among 12858
  console reliable messages captured were byte-identical copies. A receiver drops an id already
  delivered; `pokeldn.ldn.reliable5.Reassembler` does, and `bin/bdsp_connect.py` uses it.
- Answer a console's `45 0001 01` with `45 0001 00`; a `{1}` back is a back-out of the client's own.
  Never send a 0x45 after the replacement Pokemon has gone out or after the console's re-pick: it
  wipes the round.
- In the select window a 0x21 before the console's last confirmation is a cancel, and after it only
  the first counts. Stop a security-state repeater before the console can be back in its select
  window.

## The security phase

Then `TradeSecurityController` -> `CreateTradeStateModel` -> `TradeStateModel`, which owns the save:

    TradeStateModel.TradeState
    NONE 0, INIT 1, WAIT 2, SEND_POKE 3, WAIT_POKE 4,
    SEND_READYOK 5, WAIT_READYOK 6, START_WRITE_SAVE 7, WRITEING_SAVE 8

`TradeStateModel$$InitState` calls `PlayerSave` first. `WriteSaveData` tail-calls `ReplacePoke`; both
are reached only as registered delegates. `FirstSave` arms the disconnect penalty before it writes.

The security phase's Pokemon message is a trigger. `UnionRoomManager$$RecivePokeData` in
SECURIY_TRADE drops the decoded Pokemon and calls `SetSecurityTradeParam()`, which feeds
`manager.targetPokemonParam` (+0x48, set when the player confirms on the full-screen view) to the
security controller. Until the player confirms it is null and WAIT_POKE never ends.

### Who leads: the rarer Pokemon

`CreateTradeStateModel` [1.3.0 main.bin 0x1c24620] builds a `TradeParentStateModel` for both roles
(`TradeChildStateModel`'s overrides are bare `ret`s). The role is `tradeParent` (+0x94),
`TradeParent {NONE 0, PARENT 1, CHILD 2}`, written by `TradeSecurityController$$CheckPokeRarity`
[0x1c25060] when the peer's Pokemon arrives (`UnionTradeManager$$SetSecurityTradeParam` [0x1c34750])
from `Dpr.SubContents.Utils$$GetPokeRarityNum` [0x1cbe560] of the two species:

    POKE_RARITY_VERY_RARE 3, POKE_RARITY_LEGEND_RARE 2, POKE_RARITY_SUB_LEGEND_RARE 1, anything else 0
    mine > theirs   PARENT
    mine < theirs   CHILD
    equal           PARENT if isRecruiment (+0x38), else CHILD
    species -1      no role set (to 0x1c25120)

`GetPokeRarityNum` walks three static `MonsNo[]` lists in order (0x1cbe614, 0x1cbe698, 0x1cbe71c;
none 0x1cbe730), filled by `Utils$$.cctor` [0x1cbe9a0] from 1.3.0's `global-metadata.dat`:

| static field | rarity | metadata | species |
|---|---|---|---|
| `very_rare_monsno` +0x78 | 3 | `0x666aa6` | 151, 251, 385, 386, 489, 490, 491, 492, 493 (the mythicals) |
| `legend_rare_monsno` +0x80 | 2 | `0x666b06` | 150, 249, 250, 382, 383, 384, 483, 484, 487 (the box legendaries) |
| `sub_legend_rare_monsno` +0x88 | 1 | `0x667c39` | 144, 145, 146, 243, 244, 245, 377-381, 480, 481, 482, 485, 486, 488 |

A Dialga offered against a console's Mew leaves the console PARENT.

`TradeParentStateModel$$StateProc` [0x1c23350], table at 0x3d80f2f:

    2 WAIT            targetState == WAIT                    -> 3
    3 SEND_POKE       waitRndTime runs out; SendPokeData     -> 4
    4 WAIT_POKE       targetPokeData non-null                -> 5
    5 SEND_READYOK    PARENT only: send own state            -> 6
    6 WAIT_READYOK    targetIsTradeReadyOk; PARENT sends     -> 7
    7 START_WRITE_SAVE  WriteSaveData                        -> 8
    8 WRITEING_SAVE     CheckReplacePokeData                 -> 10

`TradeSecurityController$$ReciveState` [0x1c24f10] switches on the console's own state, table at
0x3d80f39:

    1 INIT            -> WAIT, send own state
    3 SEND_POKE       send own state
    5 SEND_READYOK    CHILD only: peer 5 -> send, go to 6; peer 6 -> send, go to 6, set targetIsTradeReadyOk
    6 WAIT_READYOK    set targetIsTradeReadyOk
    every case        targetState = the peer's byte

`TradeStateModel$$SetTragetPokeData` [0x1c24d70] ends by sending the console's state, WAIT_POKE. A
CHILD console then moves to SEND_READYOK and waits silently for a peer state of 5 or 6, so a client
that echoes WAIT_POKE deadlocks it. `room.mirror_trade_state` answers WAIT_POKE with SEND_READYOK,
which `ReciveState` takes in either role: a CHILD at its SEND_READYOK (case 5), a PARENT at
WAIT_READYOK (case 6). `tests/test_bdsp_trade_states.py` runs both functions as a model against the
client's policy under random latencies.

Send one message per reliable sequence id: `their_ack_id` moves only when the console acknowledges,
so later messages under one id look like retransmits and are discarded. `bdsp_connect` keeps its
own counter.

## The completed trade

The security states in order, the console as recruiter and PARENT (the console's state, then the
client's answer):

    their READY-OK {isTradeOk 0, tradeState 2}  ->  the client's READY-OK
    INIT          ->  WAIT
    WAIT          ->  WAIT
    SEND_POKE     ->  SEND_POKE, and its Pokemon
    WAIT_POKE     ->  WAIT_POKE
    SEND_READYOK  ->  SEND_READYOK
    WAIT_READYOK  ->  SEND_READYOK

After WAIT_READYOK the console writes the save, plays the animation and runs `ReplacePoke`, sending
only `NetCharacterStateData`. Leaving WAIT_READYOK needs one more message from the peer. The console
reports SEND_READYOK as it enters WAIT_READYOK in either role (a PARENT from `StateProc` case 5, a
CHILD from `ReciveState` case 5), so the client's answer to that report arrives inside it. In 25 of
25 retail trades, in both roles, the console's next reliable message followed its SEND_READYOK by
0.16 to 0.24 s, before any repeat; a PARENT's WAIT_READYOK report followed it by 0.02 to 0.06 s
(19 of 19). The client repeats its state once a second only before the console's SEND_READYOK
(`room.repeats_trade_state`): before it, a CHILD's SEND_READYOK ends only on a message arriving
inside it. The station must not leave in this window: a drop lands the console between `FirstSave`
and `SecondSave`. The same sequence runs with the console as the room's joiner and pokeldn as host.

Measured once with a retail BDSP joining `bin/bdsp_host.py`, from the console's `tradeState` 6: the
animation started at about 2.7 s, the received Pokemon appeared at about 18.6 s (hand-pressed
marks, up to 2 s late), and the player had control at about 29 s.

A completed trade ends with no message. The client counts it when it answers the console's
SEND_READYOK; the next round starts with the console's next `NetTradePokeData`.

`NetDataReturnSelectData` (0x45), `45 00 01 00` (`{isReturnSelect: 0}`), is the console's answer to
a reset ([Box phases](#box-phases-and-the-messages-that-reset-a-round)): a `{1}`, or a 0x21 landing
in its select window at box phase 5 or below, which resets through the same path [0x1c3440c] and
shows `SS_box_588`. It asks for no answer (a `{1}` answer draws a `{0}` and a reset of an already
clear round). In 26 of 26 captured trades whose client repeated its state once a second through the
animation, a `{0}` followed one of the client's 0x21 by 25 to 300 ms, and the player saw
`SS_box_588`; with no 0x21 after the console's SEND_READYOK, in 5 of 5 retail trades in both roles
(two queued in one association in each), the console sent no 0x45 and showed no cancel. `TradeSelectPokeModel$$SendReturnSelectPoke` [0x01c27c20] builds it (`isReturnSelect` = not
its argument, to `tradeTargetIndex` +0x48); it has no direct `bl` caller.

Trades chain in one association, each looping from the select window with no second approach or
trainer record: a retail console traded three times back to back with `bin/bdsp_connect.py`, and
its box screen came back after every trade, and two queued trades completed in one association
with `bin/bdsp_host.py` hosting. `TradeStateModel$$ReturnTradePokeSelectWindow`
[0x01c29590] runs `PlayerSave`, then the model's callback at +0x80; its caller is not traced. A
second trade reads back what the console stored. A SEND_READYOK (5) 0x21 landing while the player
picks (box phase 5 or below) resets the round, so no repeat follows the console's SEND_READYOK.

## The Pokemon

`NetTradePokeData` carries 328 bytes, Gen 8 `SIZE_STORED`: an encrypted PB8, the format on
[the Sword/Shield page](swsh_protocol.md#the-pk8) (`pokeldn/gen8.py`; `pokeldn/bdsp/pokemon.py` the
PB8 view). The checksum at 0x06 sums the decrypted body, so decoding a built Pokemon back verifies
it, except for a wrong block order, which a sum of 16-bit words cannot see.

`NetDataTradeTranerData` is the marshalled struct `string tranerName; uint tranerId; byte
cassetVersion; byte langId` ([Framing](bdsp_protocol.md#framing)):

    0x00  26  tranerName, UTF-16LE, NUL-terminated
    0x1a   4  tranerId, the full 32-bit id, secret id in its high half
    0x1e   1  cassetVersion, the Pokemon's version (49)
    0x1f   1  langId, the Pokemon's language (3)

The trade screen names the partner from this record, not from the Pia player name the greeting uses
([the protocol page](bdsp_protocol.md#the-name-in-the-greeting)): the 0x24 branch of
`UnionRoomManager$$SetNetData` [1.3.0 main.bin 0x1e51940] takes all four fields from the message and
only the font language from `GetGamerData(...).nameStringLanguage`, wraps the name in
`MessageHelper$$SurroundFontTag` and hands it to `UnionTradeManager$$SetTargetTranerParam`
[0x1c33330].

The ten bytes between the name's terminator and the id are heap residue (`AllocHGlobal` does not
clear; the word at 0x14 varies). `room.build_trade_traner` carries the console's own residue, byte
for byte.

An offer is a real Pokemon with named fields changed (`pokemon.build_from`); met data, ribbons,
handler records and language are non-zero on a console's own.

## What the console does to a received Pokemon

Received back by its original trainer, two bytes change: `IsNicknamed` (0x08F bit 7, IV32 bit 31) is
set when the name differs from the species name in the game's language, and the checksum follows.
The name string is untouched; a species name stays a species name.

Received by another trainer, eleven bytes change and `ot_name` is not touched:

    0x0A8..0x0B2   HandlingTrainerName, UTF-16LE
    0x0C3          HandlingTrainerLanguage (3, French)
    0x0C4          CurrentHandler, 0 -> 1
    0x0C8          HandlingTrainerFriendship, 50
    0x006..0x007   the checksum

0xC6 (PKHeX's `HandlingTrainerID`, "unused?") stays zero. PKHeX's `IsUntraded` (`Data[0xA8] == 0`)
turns false.

### Duplicate detection

`PokeDupeChecker` (added in 1.3.0) sets an illegal flag on a duplicated Pokemon. The flag is bit 0
of decrypted PB8 byte 0x52 (block A + 0x4A, `CoreDataBlockA.set_dpr_illegal_flag` `0x027bb040`);
PKHeX reads it as `PB8.IsDprIllegal`. A flagged Pokemon cannot be traded on ("Un probleme avec votre
Pokemon rend tout echange impossible.").

`UpdateIllegalFlagAll` [`0x01de5860`] runs `CheckDuplicate` [`0x01de59d0`] over the party, boxes 1
to 40 and the daycare, in that order. A Pokemon takes part when its origin game is Brilliant Diamond
or Shining Pearl (`version & ~1 == 0x30`), it is not an egg, its flag is clear, and it is not an
in-game trade Pokemon (`IsLocalKoukanPokemonParam` [`0x01de66d0`]: met location 30001 with trainer
id, encryption constant and nature matching a `LocalKoukanData` entry). Each one is compared with
every earlier one; the first copy stays clean and every later copy is flagged.

`IsDuplicatedPokemonParam` [`0x01de62f0`] matches on all of:

| field | accessor | PB8 offset |
|---|---|---|
| encryption constant | `GetPersonalRnd` | 0x00 |
| PID | `GetColorRnd` | 0x1C |
| trainer id (TID16, SID16) | `GetID` | 0x0C |
| nature | `GetSeikaku` | 0x20 |
| the six IVs | `GetTalentHp` .. | 0x8C |

A Ninjask (291) and Shedinja (292) pair is never a duplicate. Species, form, nickname and OT name
are not compared.

`UpdateIllegalSpecialTraining` [`0x01de6830`] flags a Brilliant Diamond or Shining Pearl Pokemon at
level 99 or lower with any hyper-training bit set.

The check runs on save load (`PlayerWork.OnPostLoad_NeedMD`), on each pick in the trade box
(`TradeSelectPokeModel` [`0x01c28310`]) and before the Wonder Trade save (`Dpr.GMS`); nothing runs
when a trade is received. A flagged pick in a local trade sets `UnionWork.boxState` to
`INVALID_DATA` and the box refuses it; an online trade sends the pick to
`NetworkManager.RequestValidateTrade` instead. `ClearIllegalFlagAll` has no caller, so a flag is
never cleared.

Never offer a Brilliant Diamond or Shining Pearl record whose encryption constant, PID, trainer id,
nature and IVs all match a Pokemon in the receiving save. `bin/bdsp_host.py --fresh-pid` draws a new
encryption constant and PID, shiny state kept; a record traded that way into a save holding the
original carried no flag.

## The disconnect penalty

A station dropping out between `FirstSave` and `SecondSave` leaves the penalty armed, and the
console refuses a new local trade with "vous ne pouvez pas faire d'echange en reseau pour le moment"
until it clears:

    TradeStateModel$$FirstSave    0x1cd4fc0   SetPenartyCounter(30); SetPenartyTime(now)
    TradeStateModel$$SecondSave   0x1cd5030   SetPenartyCounter(0)
    UnionFrontDeskStateController$$CheckPenarty  0x1fcc400   counter >= 1 AND not CheckDateTime()

A completed trade clears it; a penalty means `FirstSave` ran and the console wrote.
`UnionWork$$CheckDateTime` [0x1dd3e30] and `SetPenartyTime` [0x1dd32d0] use an unweighted sum:

    w8 = Year + Month + Day + Hour + Minute + Second
    cset w0, mi            ... on  (stored + 30.0) < w8

The sum rises 1 a second and falls 58 when the minute or the hour wraps (18:45:20 is 2125, 19:20:00
is 2081); only Day carries forward. `Hour+Minute+Second` spans 0..141, so armed late in an hour the
wait runs to the next day or beyond. There is no duration in the code.

Never change the console's clock or a system setting to clear it: BDSP detects the change and locks
time-based features for a day. Moving the clock back restores the penalty; only `SecondSave` zeroes
the counter.
