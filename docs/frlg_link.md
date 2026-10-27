---
title: The link protocol
parent: FireRed and LeafGreen
nav_order: 1
---

# The GBA link, and what runs on it

This page is the FireRed/LeafGreen link layer above Pia: RFU framing, the seat barrier, the Union
Room, battles and the colosseum. Citations are to [pret/pokefirered](https://github.com/pret/pokefirered).

# The RFU link layer

## One child slot per parent poll

`RfuMain2_Parent` keeps one child slot per poll and checks its rolling `childSendCmdId` tag is the
last `+1 mod 8` [link_rfu_2.c:876-892]. A bad tag increments `numChildRecvErrors[i]`; more than four
in a row calls `RfuSetErrorParams` and kills the link. A second slot inside one poll is a dropped
tag. A child emitting free-running or two slots per poll is dropped within 0.3 s of the room walk; at
one slot per poll every tag is in order. The rule holds in every phase, the seat walk included.

## Row one of the parent's table is the console's own command, mirrored back

This rule governs every stall while the console is sending.

`MGL_Send` chunks at 252 bytes and waits on `MGL_HasReceived(link->sendPlayerId)`, its own id 1,
before each chunk and at the end [mystery_gift_link.c:176,205; mystery_gift_client.c:33]: it waits
until its own block comes back complete through row one of the parent's `gRecvCmds`, which the host
mirrors [link_rfu_2.c:970,1125]. `HandleBlockSend` holds the INIT until mirrored, `SendLastBlock`
repeats the last fragment until mirrored, then every fragment missing from the mirrored bitmask is
re-queued [link_rfu_2.c:1366-1416].

`rfu_leader.ChildEcho`:

- never drops a distinct command; a dropped fragment costs a whole-block repeat and a second drop
  ends the link;
- coalesces a repeat still waiting (`SendLastBlock` resends every frame); a repeat after the mirror
  went out is answered.

The child sends one command per parent frame it receives [link_rfu_2.c:600], so the mirror queue
cannot grow on its own.

## A tile step is exactly 16 link updates

`FacingHandler_DpadMovement` sets `directionSequenceIndex = 16`, decremented once per link update
[overworld.c:3432-3470]. After N direction keys a scripted walk's gap needs `16 - (N mod 16)` updates.

## The player's inputs are not always transmitted

`UpdateHeldKeyCode` rewrites EMPTY, the DPAD codes, START and A to `LINK_KEY_CODE_NULL` while
`GetLinkSendQueueLength() > 1` [overworld.c:2786-2810]. `LINK_KEY_CODE_READY` (0x16) is exempt: gate
on 0x16, never on the absence of DPAD codes.

## The seat is a mutual barrier

`Task_EnterCableClubSeat` calls `SetInCableClubSeat()` (next key emission is READY) and spins on
`GetCableClubPartnersReady()` [cable_club.c:827-869], true only when every player is READY
[overworld.c:2988-2999]. `Task_StartWirelessTrade` then runs `SetLinkStandbyCallback()`
[cable_club.c:910-943]. Drive the standby rounds only once both players are READY; driving them at a
console in `CABLE_SEAT_WAITING` faults its seat state machine.

## What a real child sends, end to end

A retail French FireRed child; the IDLE counts are from one trade:

```
IDLE x8
SEND_BLOCK_INIT w1=0x0011 x4   + 17 fragments      (LinkPlayer)
IDLE x31
SEND_BLOCK_INIT w1=0x0009 x4   + 9 fragments       (trainer card)
IDLE x262   READY_EXIT_STANDBY w1=0x0000 x1
IDLE x72    READY_EXIT_STANDBY w1=0x0001 x1
IDLE x45    <room: SEND_HELD_KEYS 0x1b x24, EMPTY, 0x1a once, the walk, READY, then EMPTY x13>
IDLE x22    READY_EXIT_STANDBY w1=0x0002 x1
IDLE x28    READY_EXIT_STANDBY w1=0x0003 x1
IDLE x75    -> the host pulls the party
```

- Each standby round is one frame, retransmitted by Pia Reliable until it lands.
- Between rounds the child is all-zero IDLE. The leader's quiet-frame counter before the party
  exchange advances only on an exactly idle slot; an EMPTY keepalive deadlocks it.
- `LINK_KEY_CODE_IDLE` (0x1a) sets the peer's link state to IDLE [overworld.c:2755]; tile scripts run
  only for a player in that state.

## Both sides advance only when they have heard from the peer

`CB1_UpdateLinkState` runs `UpdateAllLinkPlayers` only when some `gRecvCmds` entry is non-zero
[link_rfu_2.c:787-800]; the loop settles into one exchange per round trip. The high byte of the
host's `SEND_HELD_KEYS` is `heldKeyCount`, one per prepared command.

## Post-seat standby gate and walk-out

After both sit, the console broadcasts its own `READY_EXIT_STANDBY` count=2 at mpId 0 after
reflecting the host's. It accepts a child count only when it equals its own [link_rfu_2.c:1577-1591].
Gate count=3 on the host's own mp0 count=2 and re-issue it, spaced by more than
`HostTradeTiming.entry_final_standby_quiet_frames` (75 slots, longer than the child's 60-frame
re-send [link_rfu_2.c:1529]).

The walk-out: the host emits `LINK_KEY_CODE_EXIT_ROOM` (0x17) and blocks until every player is
EXITING_ROOM [overworld.c:2962-2981]; the child answers with its own 0x17 on the held-keys stream.

## Leaving the room

A console that walks out of the Trade Center, before sitting or after a battle, sends held key 0x17
and waits on "Please wait" for every player [overworld.c:2977]. The host answers with its own 0x17 in
`H_ENTRY_SEAT`, `H_RETURN_FIELD` and the battle states (`host_trade._child_send_held_keys`).

### Quiet gate

While the console has sent nothing for `QUIET_GATE_SECONDS` (0.25 s), the host drops its own
retransmissions except one every `QUIET_RETRANSMIT_SECONDS` (1 s) (`tests/test_host_quiet_gate.py`).

## Cancel after a trade

`BufferTradeParties` clears received block flags after the gift-ribbon exchange [trade.c:1549],
before menu commands are read [1593-1633], so a cancel completed during it can be lost.
`bin/frlg_trade_join.py`, after choosing Cancel, re-sends `REQUEST_CANCEL` (`0xEEAA`) when the
leader's arrives (`trade.py`, `_on_linkcmd`). The follower sends `REQUEST_CANCEL` after YES and idles
until `BOTH_CANCEL_TRADE` [trade.c:2049, 1643]; the host answers a console's `REQUEST_CANCEL` at once.

## One-sided cancel returns both sides to the menu

`PLAYER_CANCEL_TRADE` / `PARTNER_CANCEL_TRADE` return to `CB_MAIN_MENU` [trade.c:2094-2113]; only
`BOTH_CANCEL_TRADE` ends the session [1715-1722]. Answering `REQUEST_CANCEL` with
`PARTNER_CANCEL_TRADE` loops the console on "votre ami veut échanger des Pokémon";
`bin/frlg_trade_host.py` answers with `BOTH_CANCEL_TRADE`. A leader's own pick sends nothing
[trade.c:1811-1828]. A joiner that sent `READY_TO_TRADE` first draws `PLAYER_CANCEL_TRADE` on the
leader's first Cancel; `bin/frlg_trade_join.py` then cancels at the menu.

## Version and language on the link

`IsTryingToTradeAcrossVersionTooSoon` [union_room.c:1499] fires only for a partner that is neither
FireRed nor LeafGreen. `ConvertInternationalString` special-cases Japanese names; a French FireRed
accepts an English Wonder Card. The Union Room search skips Japanese candidates [union_room.c:3726];
Mystery Gift's `Task_ListenForCompatiblePartners` does not. A Japanese cartridge uses other Wonder
Card and News activity numbers ([Japanese layout](frlg_rom_map.md#japanese-layout)) and leaves a host
advertising the international ones out of its Friend list. A host serving every cartridge advertises
the Japanese numbers only under `--language japanese`; the app passes the Mystery Gift tool's Language,
by default the trainer language in Settings. In the Mystery
Gift Friend list the console sends its ROM game code in GameData, and the host picks that
cartridge's addresses before delivery.

## The emulator can close the link on its own

`HandleLinkConnection` calls `svc_51` on the Switch build [link.c:1654]; non-zero means
`CloseLink()`, then a soft reset under Mystery Gift or `RfuReloadSave()` [link.c:1674]: Switch error
2318-0006. A death with the host clean at the RFU level points at LDN/Pia.

| SVC | called from | what it does |
|---|---|---|
| `swi 0x45` | librfu_rfu.c:667,749 | hands the emulator `gRfuLinkStatus` |
| `swi 0x49` | AgbRfu_LinkManager.c:657 | while non-zero, holds `connect_period` open during SEARCH_CHILD |
| `swi 0x4a` | AgbRfu_LinkManager.c:720 | the same, during SEARCH_PARENT |
| `swi 0x4b` | link_rfu_2.c:2114, union_room_player_avatar.c:518 | `SVC4B_EXIT_EARLY` bails out of SpawnGroupLeader; `SVC4B_RESEED_RNG` reseeds from the host's trainer id |
| `swi 0x51` | link.c:1654 | close the link now (soft reset under Mystery Gift) |
| `swi 0x53` | wireless_communication_status_screen.c:328 | emulator-driven exit from the status screen |

# The wireless layer, as this game exercises it

## The advertised rate set

An association response without 6, 9 and 12 Mbit/s makes the console leave LDN 2.9 to 3.9 s after
associating, once the Pia session has finalized: 42 of 76 such associations left, 0 of 284 with those
rates. Neither the beacon's nor the console's request rate set matters. Which of the rates the
console needs is unknown. The ESP32 softAP carries all twelve ([hardware_esp32.md](hardware_esp32.md)).

The host advertises the Switch rate set (1B 2B 5.5B 11B 6 9 12 18, extended 24 36 48 54). The
beacon head carries elements 0, 1 and 3 (41 bytes); the Switch's other elements are optional. A
beacon with WMM makes the console send QoS data frames, whose TID enters the CCMP nonce and AAD. A
probe response without RSN under a privacy capability leaves the console's association requests
unanswered. `host_pia` unicasts the type 5 Update Session.

## The console as a Pia child

- The console child needs the type 2 Join Response: on type 5 alone it re-sends its join request
  every 0.5 s and leaves 3.05-3.20 s after joining.
- A console hosting Mystery Gift answers a console child with type 5 within 50-66 ms; it answers
  `bin/frlg_mg_client.py` with no type 2 and a type 5 after 2.0 s, for an unknown reason. A console
  hosting a trade sends type 5 and type 2 within 34 ms.

A console hosting Mystery Gift, against the receive client, from its Net 0x11:

    0.000  Net 0x11 (once)
    0.006  client: Net 0x12 + Session join
    0.252  RTT request, then every 316ms
    2.038  Session type 5, no type 2
    2.040  client: type 6 (finalize); 2.159 reliable open
    4.63   host's own NI (the player's YES)
    6.82   SEND_PLAYER_IDS, 6.87 BLOCK_REQ
    8.15   Net 0x50 property update every ~0.5s, acked 0x51

## Leaving the Pia session

A console child leaves after its RFU `D` frame: a pause, the Session type-3 leave request, then its
LDN deauthentication (reason 3). With no type-4 answer:

| interval | measured |
|---|---|
| `D` to the first type 3 | 1.97-2.02 s |
| type 3 to type 3, four sends | 0.48-0.54 s |
| first type 3 to the LDN leave | 2.03-2.08 s |

    type 3, 22 bytes:  03 | random u32 | constant id (8) | variable id (2) | kind 0 | IPv4 | port
    type 4, 15 bytes:  04 | random u32 | the request's constant id and variable id

Offsets in the GBA app's `main`: `LeaveMeshJob` sends the request at `0xcacf4` with a 500 ms deadline;
`WaitLeaveResponse` (`0xcaf38`) ends on response flag `+0x99` or resends up to four times
(`0xcb06c`..`0xcb08c`). The type-4 case (`0xba028`, table `0x180fc9`) sets the flag for a 15-byte
message carrying the station's own ids. A host's type-3 handler (`0xbf2d4`) takes 22 or 34 bytes and
answers type 4 with the request's bytes 5 to 14 (`0xbf454`..`0xbf4e4`). `HostPeerProtocol` answers
every type 3 so, unicast, header `(console variable, 0x00C6)`, numbered on its unicast counter to
that console; a type 4 numbered below that counter is ignored. The console keeps one counter per
destination.

The pause is a fixed 120-tick countdown (60 ticks a second, `0x4ff64`). `TryDisconnectRfu` and
`LinkRfu_Shutdown` issue `swi 0x44` [link_rfu_2.c:1446-1455, 625]; handler `0x58b0c` posts disconnect
request 1 (`0x53d98` -> `0x4f0ec`, `+0x730`), the tick `0x4ee34` sets `+0x734 = 0x78` (`0x4ef00`) and
at zero calls slot `0x78` (`0x4ef60`), and `Session::LeaveAsync` (`0xb1060`, from `0x537e0`) sends the
type 3 ([pia.md](pia.md), Leaving a session). Nothing received shortens it; only request 2 or 3
(`swi 0x42`, or `swi 0x43` with PID 0) or a Pia error setting `+0x277c` does.

## 802.11 behaviour

- Console as station: no power save, RTS before every data frame, one deauthentication on leaving.
- A Switch host beacons at 11M and sends data at 48-54M.

## The Pia header nonce is a counter the console enforces

The console drops any datagram whose 8-byte header nonce is not strictly above the last accepted
one on that channel. `Sim._next_nonce` and the host both count.

## Carry-forward

Each reliable frame is repeated in the next 4 datagrams. Air loss is 1-2% and bursty; a hole holds
every later slot until its retransmit, which then fills the console's 8-deep RFU receive queue past its depth.
Without carry-forward one lost slot disconnects the console. The host de-duplicates by sequence.

## The console's acknowledgement lag is a 512 ms metronome

The console's cumulative ack is in the CTRL frame payload (`parse_bulk_ack`); the reliable header's
`ack` is the sender's lowest pending sequence. Every 16 or 17 slots of 512 ms (phase-locked to the
LDN join) the console stalls 50-70 ms, retransmits its last frames, then its ack jumps several
frames. Under load the stall lands on a full send window. Which emulator or Pia/LDN timer drives it
is unknown.

## The ident-25 stall: a hole plus an unbounded backlog

When a hole closes behind an unbounded backlog, the console delivers every held frame at once, its
8-deep RFU queue drops the ident-25 (`MG_LINKID_RAM_SCRIPT`) fragments, and it stays on
"Transmission..." with the link up. A parent block is never reflected, so the loss is invisible in a
capture. `HostSession` holds new frames while `HOST_OUTSTANDING_MAX` (6) are unacknowledged, and
`--ram-script-block-repeat 3` sends ident 25 three times. Whether air loss or the console's handoff
drops the fragment is unknown.

## Transmission-phase deaths after the card

Re-sending every unacked frame every tick after an ack stall kills the session. Checks, on by default:

- `HOST_RTX_LIMIT` caps Reliable retransmits per VBlank.
- `FRLG_ECHO_MAX` bounds the FIFO echo of the child's block slots.
- The transmit socket is non-blocking, and `FRLG_QUIET_GATE_MS` holds retransmits while the console
  is silent (about 0.5 s after accepting the card, its flash save).

## Datagrams held between the socket and the air

Host datagrams held 0.1-1.1 s before the air make the game show "erreur de connexion,
rapprochez-vous" [link_rfu_2.c:2312, link.c:1521]. On the ESP32 board the longest wait measured is
265 ms ([ESP32 radio](hardware_esp32.md), TX_DONE).

# The Union Room

## Getting listed: the advertised activity byte

A searching console keeps a candidate only if its activity is in its link group's accept list
[`IsPartnerActivityAcceptable`, union_room.c:1590; src/data/union_room.h:398-456]. In the Union Room
the console searches `{ACTIVITY_SEARCH, 0xFF}`, then `IN_UNION_ROOM | activity` (`IN_UNION_ROOM = 1 << 6`)
[union_room.c:2664]. Record byte 16 is the activity: 21 lists the host on the Wonder Cards screen, 22
on Wonder News.

## The connect: IN_UNION_ROOM, exactly and alone

`IsPartnerActivityIncompatible` requires `partner->activity == IN_UNION_ROOM` exactly
[link_rfu_2.c:2933]. 0x44 spawns the avatar but the connect is refused ("le DRESSEUR est occupé");
0x40 connects, and the trade intent is negotiated after the link is up.

## No parent NI, and the five-frame rule

The Union Room child sets a TYPE_UNI receive buffer, never TYPE_NI [link_rfu_2.c:2526, 533]. A
parent NI body is fatal: it fails with ERR_RECV_BUFF_OVER [librfu_rfu.c:2300] and ends in "erreur de
connexion" [link_rfu_2.c:2585]. `RFULeader(skip_parent_ni=True)` (`--union-room`) skips it.

The console disconnects on the fifth parent frame it left unanswered (`maxMFrame = 4`
[link_rfu_2.c:128]). `--union-room-keepalive N` (120 works) re-presents the first NI_START for N
VBlanks before UNI. The console then waits about eight seconds: `rfu_UNI_setSendData` fails with
ERR_SUBFRAME_SIZE while a NI_START is pending [librfu_rfu.c:2262, 1449] until `NI_failCounter_limit`,
480 frames after the last NI_START [link_rfu_2.c:139, AgbRfu_LinkManager.c:1328].

## What the console does once connected

Once linked, the console exchanges trainer cards [union_room.c:2858-2879] and shows Salut / Combat /
Tchat / Retour. Each choice sends one `SEND_PACKET` and waits [union_room.c:3151]:

| the console sends | activity | the host answers |
|---|---|---|
| 0x48 | CARD (Salut) | 0x51 ACCEPT |
| 0x44 | TRADE (trading board) | 0x51 ACCEPT |
| 0x41 | BATTLE (Combat) | 0x51 ACCEPT |
| 0x45 | CHAT (Tchat) | 0x51 ACCEPT |
| 0x40 | EXIT (Retour) | treat as the console's close |

After each activity both sides `SetLinkStandbyCallback` [union_room.c:2995, :3012]. The accepting
side is gated on `svc_CommsAllowedByParentalControls()` [union_room.c:3159, :3037]. Retour sends 0x40
then READY_CLOSE_LINK and disconnects normally.

## The trading board

The board reads record byte 18 (`type << 2`), 19 (`gameClear | level << 1`,
[The advertisement record](frlg_rom.md#the-advertisement-record)) and 22:24 (`tradeSpecies:10`)
[union_room.c:3400; include/link_rfu.h:107].

A board trade is one trade per link: `Task_StartUnionRoomTrade` saves `CB2_ReturnToField`
[union_room.c:1744], and `CB2_SaveAndEndTrade` keeps the link only for the trade centre's callback
[trade_scene.c:2722-2725]. Sequence: the console's Pokemon block (count 9), the host's, its mail block
(count 19), the host's, the animation, READY_FINISH, CONFIRM_FINISH, the save barriers,
READY_CLOSE_LINK both ways, disconnect. There is no party exchange, menu or room route.

## Chat

Chat rides `SendBlock(0, buf, 0x28)` (count 4), unsolicited, with no `BLOCK_REQ`
[union_room_chat.c:429, :823]:

    [0]      command: 0 NULL, 1 CHAT, 2 JOIN, 3 LEAVE, 4 DROP, 5 DISBAND
    [1..8]   player name, EOS-terminated
    [9]      multiplayer id            (JOIN / LEAVE / DROP / DISBAND)
    [9..39]  message text, EOS-terminated (CHAT)

[union_room_chat.c:1256-1283]. ACCEPT of 0x45 keeps the link [union_room.c:1938]; both members send
JOIN on entry. A line is 15 entries [union_room_chat.c:21]; the receiver draws more off screen, and
the host refuses an over-long line at start-up (`uroom_chat.entry_count`). On a LEAVE the leader must
drop the link [union_room_chat.c:596-660]: the host sends DROP 0.1 s after and closes. Lines appended
to `--chat-file` reach the console about 1.7 s after the write.

## The link battle (UR_BATTLE 0x41)

`HasAtLeastTwoMonsOfLevel30OrLower` [union_room.c:4565] requires two non-egg party mons at level 30
or lower on each side, checked on offer and accept [union_room.c:2923, 3176].

After both pick two mons, each sends one 0x20-byte block starting 0x51 (0x52 if cancelled), the rest
zero (`CB2_UnionRoomBattle`); anything else closes the link. The Switch path adds two link-task waits
with a standby between (cases 50-52). `StartUnionRoomBattle(BATTLE_TYPE_LINK | BATTLE_TYPE_TRAINER)`
[union_room.c:1811] sets `linkType = 0x2211` [link.h:92; battle_controllers.c:520]. Then
[battle_main.c:934]:

    state 1  SendBlock struct LinkBattlerHeader {versionSignatureLo, versionSignatureHi,
             vsScreenHealthFlagsLo, vsScreenHealthFlagsHi, struct BattleEnigmaBerry}
    state 3  SendBlock gPlayerParty[0..1]   200 bytes      state 4  recv -> gEnemyParty
    state 7  SendBlock gPlayerParty[2..3]   200 bytes      state 8  recv
    state 11 SendBlock gPlayerParty[4..5]   200 bytes      state 12 recv
    state 15 InitBattleControllers

### Master election

Only the `BATTLE_TYPE_IS_MASTER` side runs turn resolution, damage and RNG
[battle_controllers.c:141, :45]; the host as non-master is a battle controller.
`LinkBattleComputeBattleTypeFlags` [battle_main.c:886]: if `gBlockRecvBuffer[0][0] == 0x100` or both
signatures are equal, player 0 is master, else the highest version. The host sends 0x200, which makes
the console master.

### The link buffer protocol

Every controller command is one SendBlock with an 8-byte header [battle_controllers.c:401-435]:
`BUFFER_ID, ACTIVE_BATTLER, ATTACKER, TARGET, SIZE_LO, SIZE_HI, ABSENT_BATTLER_FLAGS, EFFECT_BATTLER`,
payload stored as `size - size % 4 + 4`. `bufferId` 0 = BUFFER_A (command), 1 = BUFFER_B (reply),
2 = exec-flag clear carrying the sender's multiplayer id [:566-594]. Battler 0 is the master's.

`MarkBattlerForControllerExec` sets bit `28+battler`; the command's returning block sets each
player's nibble, and each clears its own with bufferId 2 [battle_util.c:185-201]. The master
advances only on `gBattleControllerExecFlags == 0`.

Commands that need more than the ack [battle_controller_player.c]:

    CONTROLLER_GETMONDATA    -> EmitDataTransfer(BUFFER_B, size, data)   [player.c:1515]
    CONTROLLER_CHOOSEACTION  -> EmitTwoReturnValues(1, B_ACTION_*, 0)    [player.c:232-241]
    CONTROLLER_CHOOSEMOVE    -> EmitTwoReturnValues(1, 10, move | target << 8) [player.c:342]
    CONTROLLER_CHOOSEPOKEMON -> EmitChosenMonReturnValue(1, partyId, order)    [player.c:1316]
    CONTROLLER_OPENBAG       -> EmitOneReturnValue(1, itemId)            [player.c:1340]
    CONTROLLER_EXPUPDATE     -> EmitTwoReturnValues(1, RET_VALUE_LEVELED_UP, exp) [player.c:1051]
    CONTROLLER_ENDLINKBATTLE -> gBattleOutcome = payload[1], then ack     [player.c:2876]

`B_ACTION_USE_MOVE` 0, `USE_ITEM` 1, `SWITCH` 2, `RUN` 3 [battle.h:34]. The first `GETMONDATA` is
answered with a 0x58-byte `struct BattlePokemon` [pokemon.h:170]; recomputed fields may be zero.
BUFFER_B replies for battler 0 may be skipped [link_opponent.c:444]. A link battler may run with top
turn order [battle_main.c:3239, 3548-3560].

### Two rules not visible in the decomp

- Inside a battle the state routes a block, never its size: every ack and short command is a
  16-byte, two-fragment record.
- An ack must never overtake the echo of the block it acknowledges. A late echo sets the exec bit
  again [battle_util.c:193] and the console waits forever on `gBattleControllerExecFlags == 0`
  [battle_script_commands.c:2041]. `HostTradeEngine._echo_owed` holds a new block while a child
  command awaits its mirror, and `rfu_leader.echo_blocks` makes the ack wait for every fragment
  0..count-1 of the echo.

### The pace is the RFU VBlank budget

A battle step takes about a second: a command block spans about twenty frames at one RFU slot per
`HOST_VBLANK_SECONDS = 1/59.727`, plus the return leg. Consecutive `bufferA` commands are a median
800 ms apart.

## What two real consoles put on the air

A FireRed hosting over Direct Corner sends 25.5 frames/s to a LeafGreen and 161.8/s to the host. It
carries the Switch profile name in ASCII at offset 0x11 of `application_data`, not the trainer name.

## Host tick rate and the console's output rate

`--tick-hz` sets the host's RFU slots per second; the default is one per VBlank. At 20 Hz a trade
takes about twice as long and the console sends 80% more datagrams.

# The cable-club colosseum

`frlg_trade_host.py --colosseum` hosts Pokemon Center 2F, third NPC, Colosseum, Single Battle, JOIN.
Only `CB2_ReturnFromCableClubBattle` increments the Wonder Card's `battlesWon` [cable_club.c:792].

`Task_StartActivity` treats `ACTIVITY_BATTLE_SINGLE` like `ACTIVITY_TRADE` [union_room.c:1903]
except the map (`MAP_BATTLE_COLOSSEUM_2P` at (6, 8)) and `HealPlayerParty()`. Differences from the
trade path:

1. `LINK_GROUP_SINGLE_BATTLE` accepts `{ACTIVITY_BATTLE_SINGLE, 0xFF}` [src/data/union_room.h:398];
   `build_colosseum_app_data` changes that byte only.
2. The 2P seat scripts have no party check [data/scripts/cable_club.inc:576].
3. `Task_StartWirelessCableClubBattle` case 2 sends the bare 28-byte `struct LinkPlayer` unprompted
   from both sides [cable_club.c:701], then cases 4-6 add a standby before `CB2_InitBattle`.
4. The whole party fights [union_room_battle.c:47].

From `CB2_InitBattle` on it is the Union Room battle without the 0x51 selection block. The seat
needs the READY key alone and has no post-seat standby rounds; the console, parked in case 3, sends
`SEND_BLOCK_INIT` count 3 and `04 40 00 80 65 df | bb c8 ff 00 11 00 | 01 00 03 00 00 00`, whose
arrival finishes the entry. After the battle the host owes the exit key [overworld.c:2977].

## What decides whether a colosseum run counts

A forfeit is a win for the other side: `HandleAction_Run` sets `B_OUTCOME_WON` with
`B_OUTCOME_LINK_BATTLE_RAN` [battle_main.c:4300], cleared before the return [:3734]. The id counted is
the partner's 28-byte record trainer id [cable_club.c:794], once each, five per stat
[mystery_gift.c:630]. Three forfeits against three `--id` values earn the Battle Count Card's POTION:

    save 0x3434:  0100 0000 0000 2300    battlesWon 1, lost 0, trades 0, icon 35 CARD_TYPE_LINK_STAT

# Two host-side constraints

- The close timer runs inside `activity.tick()`, which `HostSession.tick` skips while the hole guard
  holds, so a console that stops acknowledging stalls it; the runtime stops once the console leaves
  LDN after a confirmed exit.
- An all-zero `easyChatProfile` prints "??? ???" on the trainer card [easy_chat.c:166-171]. A word is
  `(group & 0x7F) << 9 | (index & 0x1FF)` [easy_chat.h:1089], four per card; pad with
  `EC_WORD_UNDEFINED` (0xFFFF).
