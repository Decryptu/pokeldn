---
title: The link protocol
parent: FireRed and LeafGreen
nav_order: 1
---

# The GBA link, and what runs on it

Measured on retail hardware or read out of [pret/pokefirered](https://github.com/pret/pokefirered).

# The RFU link layer

## One child slot per parent poll

`RfuMain2_Parent` keeps one child slot per poll in `gRfu.childRecvBuffer[i]` and checks its rolling
`childSendCmdId` tag is the last kept `+1 mod 8` [link_rfu_2.c:876-892]. A bad tag increments
`numChildRecvErrors[i]`; `> 4` calls `RfuSetErrorParams` and kills the link; a good tag resets it, so
death needs five consecutive bad polls. A second slot inside one poll is a dropped tag. One walk
into the trade room per emission rate, measured on retail FireRed:

| child emission | the console stopped polling |
|---|---|
| free-running (~57/s against its ~55/s) | 0.10 s after the walk started |
| 2 slots per poll | 0.28 s after the walk started |
| 1 slot per poll | 5.8 s after the walk started |

At one slot per poll every tag is in order and `numChildRecvErrors` never increments; later walks at
that rate reached the seat, so the 5.8 s stop is not the tag check.

Nothing is exempt, including the seat walk.

## Row one of the parent's table is the console's own command, mirrored back

This rule governs every stall while the console is sending, in any activity.

`MGL_Send` chunks at 252 bytes and waits on `MGL_HasReceived(link->sendPlayerId)` before each chunk
and at the end [mystery_gift_link.c:176,205]. `sendPlayerId` is the console's own id 1
[mystery_gift_client.c:33], so it waits until its own block comes back complete through row one of the
parent's `gRecvCmds`, the copy the host mirrors. `RfuHandleReceiveCommand` reassembles blocks for
every player including the child itself [link_rfu_2.c:1125], and `RfuMain1_Child` fills `gRecvCmds`
from the parent's table, its own row included [:970].

The RFU block sender waits on the same mirror: `HandleBlockSend` holds the INIT until it sees it
mirrored, `SendLastBlock` repeats the last fragment until mirrored, then re-queues every fragment
missing from the mirrored bitmask [HandleSendFailure, link_rfu_2.c:1366-1416]. The console cannot name
a missing fragment; it resends everything.

`rfu_leader.ChildEcho` follows two rules:

- Never drop a distinct command; a dropped fragment is a blind repair round. A bounded echo queue
  drops commands from a burst (a 21-fragment chunk overflows a two-entry bound); the console then
  repeats the whole block, and a second drop ends in link loss.
- Coalesce a repeat still waiting (`SendLastBlock` resends every frame); one entry is enough. A repeat
  after the mirror went out is a new question and is answered.

The child sends one command per parent frame it receives (`childSendCount` increments only on
`recv.newDataFlag` [link_rfu_2.c:600]), so the mirror queue cannot grow on its own.

## A tile step is exactly 16 link updates

`FacingHandler_DpadMovement` sets `objEvent->directionSequenceIndex = 16`;
`MovementStatusHandler_TryAdvanceScript` decrements it once per link update while keys are ignored
(`MOVEMENT_MODE_FROZEN`) [overworld.c:3432-3470]. A run of N direction keys leaves `N mod 16` of its
last step spent, so a scripted walk's gap needs only `16 - (N mod 16)` updates; overshooting costs a
slot per update and nothing else.

## The player's inputs are not always transmitted

`UpdateHeldKeyCode` rewrites EMPTY, the four DPAD codes, START and A to `LINK_KEY_CODE_NULL` whenever
`GetLinkSendQueueLength() > 1` [overworld.c:2786-2810], and `SendKeysToRfu` sends nothing: a walking
player under queue pressure looks parked. `LINK_KEY_CODE_READY` (0x16) is exempt, so gate on 0x16,
never on the absence of DPAD codes.

## The seat is a mutual barrier

`Task_EnterCableClubSeat` shows "Please wait", calls `SetInCableClubSeat()` (the next held-key
emission becomes `LINK_KEY_CODE_READY`), then spins on `GetCableClubPartnersReady()`
[cable_club.c:827-869], which succeeds only when `AreAllPlayersInLinkState(PLAYER_LINK_STATE_READY)`
[overworld.c:2988-2999]. Then `Task_StartWirelessTrade` runs `SetLinkStandbyCallback()`
[cable_club.c:910-943], the source of the post-seat standby rounds. Drive those only once both players
are READY; driving them at a console still in `CABLE_SEAT_WAITING` faults its seat state machine.

## What a real child sends, end to end

One recorded trade, a retail French FireRed as child against the host. The order is the
protocol's; the IDLE counts are that trade's:

```
IDLE x8
SEND_BLOCK_INIT w1=0x0011 x4   + 17 fragments      (LinkPlayer, 0x11 = 17)
IDLE x31
SEND_BLOCK_INIT w1=0x0009 x4   + 9 fragments       (trainer card)
IDLE x262   READY_EXIT_STANDBY w1=0x0000 x1
IDLE x72    READY_EXIT_STANDBY w1=0x0001 x1
IDLE x45    <room: SEND_HELD_KEYS 0x1b x24, EMPTY, 0x1a once, the walk, READY, then EMPTY x13>
IDLE x22    READY_EXIT_STANDBY w1=0x0002 x1
IDLE x28    READY_EXIT_STANDBY w1=0x0003 x1
IDLE x75    -> the host pulls the party
```

- Each standby round is one frame, retransmitted by Pia Reliable until it lands. Repeating the count
  shows the host a round it already completed.
- Between rounds the child is fully IDLE (all-zero `gSendCmd`). The leader's quiet-frame counter
  before the party exchange advances only on an exactly idle slot, so an EMPTY keepalive deadlocks it.
- The room-load prefix (`0x1b` = HANDLE_RECV_QUEUE ×24, then `0x1a` = IDLE) is queue housekeeping.
  `LINK_KEY_CODE_IDLE` sets `sPlayerLinkStates[player] = IDLE` on the peer [overworld.c:2755], and
  `HandleLinkPlayerKeyInput` runs tile scripts only for a player in state IDLE.

## Both sides advance only when they have heard from the peer

`CB1_UpdateLinkState` runs `UpdateAllLinkPlayers` only when `!IsRfuRecvQueueEmpty()`, which returns
FALSE if any `gRecvCmds` entry is non-zero [link_rfu_2.c:787-800]. `MoveSendCmdToRecv` copies the
parent's own `gSendCmd` into `gRecvCmds[0]`, so the parent can self-sustain; in practice the loop
settles into one exchange per round trip (one capture: 182 out→in against 182 in→out, 22 in→in,
27 out→out).

The high byte of the host's `SEND_HELD_KEYS` is `heldKeyCount`, one per prepared command, so the last
value counts the link updates its trade room survived.

## Post-seat standby gate and walk-out

After both sit, the console broadcasts its own `READY_EXIT_STANDBY` count=2 at mpId 0 after
reflecting the host's (130 ms later in a recorded trade). It accepts a child count only when it equals its own (`Rfu_LinkStandby`
recv gate, link_rfu_2.c:1577-1591), so a count=3 sent on the reflection of the host's count=2 is
ignored: a reflection proves the parent saw the slot, not that the round completed. Gate count=3 on
the host's own mp0 count=2 and keep re-arming it, spaced by more than the host's quiet window before
`BufferTradeParties` (`HostTradeTiming.entry_final_standby_quiet_frames`, 75 slots, longer than the
child's 60-frame re-send of `READY_EXIT_STANDBY` [link_rfu_2.c:1529]).

The walk-out: the host emits `LINK_KEY_CODE_EXIT_ROOM` (0x17) and blocks in
`KeyInterCB_WaitForPlayersToExit` until `AreAllPlayersInLinkState(EXITING_ROOM)`
[overworld.c:2962-2981]. The child must answer with its own 0x17 on the held-keys stream; an all-zero
slot is not a key.

## Cancel after a trade

`BufferTradeParties` clears received block flags after the gift-ribbon exchange
[trade.c:1549], before `Leader_ReadLinkBuffer` reads menu commands [1593-1633]. A cancel
request completed during that exchange can be cleared before it sets the partner's selection.
The leader's own `REQUEST_CANCEL` (`0xEEAA`) proves that it is processing the Cancel input
[2049]. `bin/frlg_trade_join.py`, once its configured trades are done and it has chosen Cancel,
sends its `REQUEST_CANCEL` again when the leader's arrives (`pokeldn/frlg/link/trade.py`,
`_on_linkcmd`).
`BOTH_CANCEL_TRADE` clears any pending request before the exit standby rounds.

The follower sends `REQUEST_CANCEL` from its live menu after YES, prints "waiting for friend" and
idles until `BOTH_CANCEL_TRADE` [trade.c:2049, 1643]; a leader whose player chose Cancel answers
when it reads it [1715-1722]. The host answers a console's `REQUEST_CANCEL` in the final menu at
once.

## One-sided cancel returns both sides to the menu

`PLAYER_CANCEL_TRADE` / `PARTNER_CANCEL_TRADE` go through `CB_HandleTradeCanceled` → `CB_MAIN_MENU`
[trade.c:2094-2113]; only `BOTH_CANCEL_TRADE` ends the session [1715-1722]. The joiner re-enters
S4_PARTY and selects again after 60 frames. Answering every `REQUEST_CANCEL` with
`PARTNER_CANCEL_TRADE` loops the console on "votre ami veut échanger des Pokémon"; the leader cancels
on a second consecutive CANCEL, giving `BOTH_CANCEL_TRADE` and the exit path.

## Version and language are not gates

`IsTryingToTradeAcrossVersionTooSoon` [union_room.c:1499] fires only for a partner that is neither
FireRed nor LeafGreen, and prints a message without dropping the link; FR↔LG trading works on
hardware. The only language branch, `ConvertInternationalString`, special-cases Japanese; a French
FireRed accepts an English Wonder Card.

## The emulator can close the link on its own

`HandleLinkConnection` runs `svc_51` on the Switch build only [link.c:1654]:

    #if REVISION >= 0xA
        if (svc_51())
        {
            ...
            CloseLink();
        }
    #endif

`svc_51` (`swi 0x51`) is answered by the emulator [sloopsvc.c:120]. Non-zero means `CloseLink()`,
then `RfuSoftReset()` under `Task_MysteryGift`, else `RfuReloadSave()` [link.c:1674]: Switch error
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

An association response without 6, 9 and 12 Mbit/s makes the console leave the LDN network 2.9 to
3.9 s after it associates, after the Pia session has finalized, in any link phase: 42 of 76 such
first associations left, against 0 of 284 with those rates. A missing Pia type 2 Join Response gives
a leave at the same time ([The console as a Pia child](#the-console-as-a-pia-child)), as does a Linux
station the AP never marks authorized ([Host implementation](frlg_host.md), Failure handling). From
360 air captures of hosted FireRed and LeafGreen sessions, each run's first association against
whether the console left inside 6 s:

| association response | beacon | console's association request | left at 3 s | stayed |
|---|---|---|---|---|
| with 6, 9, 12 | with | with | 0 | 139 |
| with 6, 9, 12 | with | without | 0 | 84 |
| with 6, 9, 12 | without | with | 0 | 26 |
| with 6, 9, 12 | without | without | 0 | 35 |
| without | without | without | 42 | 34 |

Alternating only the response's rate set: 0 of 20 with, 4 of 8 without. The failing set was `1B 2B 5.5B 11B 18 24 36 54` (no 6, 9, 12, 48); which of
the four the console needs is unknown. The ESP32 softAP's association response carries all twelve
rates ([hardware_esp32.md](hardware_esp32.md), The access point's frames).

The host advertises the Switch rate set (1B 2B 5.5B 11B 6 9 12 18, extended 24 36 48 54). The
Switch's other elements (DTIM 2, ERP, capability 0x411, the Nintendo vendor element, HT/HE, WMM) are
not needed. The console builds its association request's rates from the beacon, so the beacon head
carries elements 0 (SSID), 1 (Supported Rates) and 3 (DS Params), a 41-byte subset. With the full
208-byte element set in the beacon of the Linux adapter, 0 of 5 Mystery Gift sessions completed: the
console joined and the traffic stalled before the gift.

`host_pia` unicasts the type 5 Update Session: on the Linux adapter the console received about one
broadcast frame in five. A beacon carrying WMM makes the console send QoS data frames (subtype 8),
which the host must decode; the vendored LDN decoder takes the TID into the CCMP nonce and AAD. With a
probe response that lacked RSN under a privacy capability, the console's three association requests
went unanswered (one Linux session).

## The console as a Pia child

- The console child needs the type 2 Join Response: on a type 5 alone it re-sends its join request
  every 0.5 s, ignores unicast type 5 copies, and leaves the network about 3 s after joining
  (3.05-3.20 s measured), the same symptom as a short rate set.
- A console hosting Mystery Gift answers a console child with type 5 within 50-66 ms of its Net 0x11.
  It answers `bin/frlg_mg_client.py` with no type 2 and a type 5 after 2.0 s; which field of the join
  request causes the difference is unknown. A console hosting a trade sends type 5 and type 2 within
  34 ms, RTT only after finalization.

One session, a console hosting Mystery Gift to the receive client, from its Net 0x11:

    0.000  Net 0x11 (once)
    0.006  us: Net 0x12 + Session join
    0.252  RTT request, then every 316ms (6 probes, nothing else)
    2.038  Session type 5, no type 2 ever
    2.040  us: type 6 (finalize); 2.159 reliable open
    2.318  host 'A' frame
    4.63   host's own NI (join status = the user's YES on the console)
    6.82   SEND_PLAYER_IDS, 6.87 BLOCK_REQ (2.2s after the YES)
    8.15   Net 0x50 property update every ~0.5s, acked 0x51

## Leaving the Pia session

A console child leaves in three steps after its RFU `D` frame: a pause, the Session type-3 leave
request, then its LDN deauthentication (reason 3). Across 33 hosted trade and Mystery Gift captures
with no type-4 answer, every one measured:

| interval | measured |
|---|---|
| `D` to the first type 3 | 1.97-2.02 s |
| type 3 to type 3, four sends | 0.48-0.54 s |
| first type 3 to the LDN leave | 2.03-2.08 s |
| `D` to the LDN leave | 4.02-4.08 s |

    type 3, 22 bytes:  03 | random u32 | constant id (8) | variable id (2) | kind 0 | IPv4 | port
    type 4, 15 bytes:  04 | random u32 | the request's constant id and variable id

Offsets are in the GBA app's `main`, from the image start. `LeaveMeshJob` sends the request at
`0xcacf4` with a 500 ms deadline, and `WaitLeaveResponse` (`0xcaf38`) ends on the job's
response flag `+0x99`, or at each deadline resends while its count is 2 or less (`0xcb06c`..
`0xcb08c`): four sends, then the job completes and the station leaves the network. The Session
dispatcher's type-4 case (`0xba028`, table `0x180fc9`) sets that flag for a 15-byte message whose
constant id at 5 and variable id at 13 are the station's own. A host's type-3 handler (`0xbf2d4`)
takes 22 or 34 bytes (kind 1 carries 18 address bytes, `0xbf3ac`) and answers 15 bytes: type 4, a
fresh random word, the request's bytes 5 to 14 (`0xbf454`..`0xbf4e4`). The host answers every
type 3 in that form (`pokeldn.ldn.host_pia.HostPeerProtocol`), unicast, header
`(console variable, 0x00C6)`.

What the console waits on during the two seconds before its first type 3 is unknown.

## 802.11 behaviour

- Console as station: no power save (PM bit 0 always), RTS before every data frame. When it leaves,
  it sends one deauthentication with no probe or null frame before it.
- A Switch host beacons at 11M and sends data at 48-54M. rtw88 (kernel 7.0) sends management frames
  at the lowest basic rate, beacons and injected action frames at 1M.
- On the Linux monitor vif the host's own frames are a software loopback emitted at TX status, a
  delayed copy (median 594 ms behind `sendto` in the captures measured, while the console acks within
  15 ms). Use those timestamps for ordering only.
- In the Linux captures a console host dropped about 40% of a child's Pia datagrams after MAC-acking
  them, across spacing, size and content. Repeating each reliable frame in the next few datagrams removes the
  in-order stalls; the host de-duplicates by sequence.

## The Pia header nonce is a counter the console enforces

The console keeps, per channel, the last accepted 8-byte header nonce (big-endian) and drops any
datagram not strictly above it, so a random nonce passes about half the time:

    random nonce:   ~1.1 duplicate outgoing reliable deliveries per unique frame, ~0.3 inbound
    counter nonce:  0.34 outgoing, 0.00 inbound

`Sim._next_nonce` and the host both count.

## Carry-forward

Each reliable frame is repeated in the next 4 datagrams, acknowledged about 17 ms after the
original. Air loss is 1-2% and bursty (the console's own retransmit rate is 0.01-0.02 per frame), Pia
delivers in order, and a hole holds every later slot until its retransmit, which then delivers them
together and overflows the console's 8-deep RFU receive queue. Measured with carry 0: one lost parent
slot and its 68 ms retransmit put ten slots into the console at once, and it disconnected 300 ms
later.

## The console's acknowledgement lag is a 512 ms metronome

The console's cumulative ack lives in the CTRL frame payload (`parse_bulk_ack`); the reliable
header's `ack` field is the sender's own lowest pending sequence.

The console stalls 50-70 ms at a time: inbound stops for 35-70 ms against a 15 ms baseline, it
retransmits its own last frames, then its cumulative ack jumps several frames:

    26.553 in   D1849 D1850 ACK next=919
    26.587 OUT  D919 D920 ACK next=1851
    26.617 in   D1849* D1850*        (retransmits, no ack)
    26.653 in   ACK next=924         (catches up five frames at once)

Over 42 intervals on both cartridges and three activities, every period is an integer number
of 512 ms slots within 16 ms (one frame). Observed counts are 16 and 17 slots, with one 18 and one 33
where a tick was skipped. The grid is phase-locked to the LDN join: twelve stalls over 103 s span 18
ms of phase. On an idle chat link the outstanding count reaches 5 harmlessly; under Mystery Gift or
trade load the stall lands on a full send window. The ROM has no 512 ms tick, so the timer belongs to
the emulator or the Pia/LDN layer; what it is remains unknown.

## The ident-25 stall: a hole plus an unbounded backlog

The console sometimes goes idle after the last delivery-script block (ident 25,
`MG_LINKID_RAM_SCRIPT`), never sends ident 20 (READY_END), and leaves. A parent block is never
reflected, so the lost fragment is invisible in the capture.

When a hole closes behind an unbounded backlog, the console hands every held frame to the game at
once, its 8-deep RFU queue drops the ident-25 fragments, and it stays on "Transmission..." with the
link up. In the capture that shows it, two consecutive frames were lost, the cumulative ack stalled
1.75 s while the host re-sent them in every datagram (about 100 copies) and added five new frames per
datagram, 97 frames reached the game in one datagram, and the console stayed on "Transmission..." for
150 s. The normal ack lag is 0-1 frames at 99% of acks.

`HostSession` holds new frames while `HOST_OUTSTANDING_MAX` (6) frames are unacknowledged, keeps
retransmitting the gap, and resumes when the ack catches up, so a closed hole releases at most 6.
`--ram-script-block-repeat 3` sends the ident-25 block three times: 5 of 5 sessions delivered on a
console that had been stalling there. With `--block-repeat 1`, the one LeafGreen session measured
stalled at ident 25. Whether air loss or the console's RFU-to-game handoff drops
the fragment is not established.

## Transmission-phase deaths after the card

On the Linux adapter, the sessions that died after the card showed host UDP output peaking at 52-519
datagrams per 0.25 s, against 23-36 in those that succeeded: a 250 ms to 3 s transmit stall in the
rtw88 USB path, then no acks, then every unacked frame re-sent every tick. The host's guards, all on
by default:

- `HOST_RTX_LIMIT` caps Reliable retransmits per VBlank.
- `FRLG_ECHO_MAX` bounds the FIFO echo of the child's block slots.
- The transmit socket is non-blocking, and `FRLG_QUIET_GATE_MS` holds retransmits and carry-forward
  while the console is silent (about 0.5 s after accepting the card, its flash save; a blocking send
  there froze the host 6-11 s).

The adapter stall is unexplained.

## Datagrams held between the socket and the air

On the Linux card the host's datagrams can be held 0.1-1.1 s below the UDP socket (no `EAGAIN`; in
the measured battle, released as one burst of 71 frames in 200 ms), long enough for the game to take
the link-loss path and show "erreur de connexion, rapprochez-vous" [link_rfu_2.c:2312 →
CB2_PrintErrorMessage, link.c:1521]. The vendored LDN library reads `ldn-tap` in Python and injects on
`ldn-mon` (`ldn/__init__.py:1795-1858`), bypassing the AP vif (`ieee80211_subif_start_xmit` 0 calls
against `tun_net_xmit` 17549); which stage held the frames is unknown. On the ESP32 board the longest
socket-to-acknowledgement wait measured over four FireRed trades was 265 ms, in the board's transmit
queue; all four trades completed ([ESP32 radio](hardware_esp32.md), TX_DONE).

# The Union Room

## Getting listed: the advertised activity byte

A searching console keeps a candidate only if its advertised activity is in the accept list of the
link group it searches [`IsPartnerActivityAcceptable`, union_room.c:1590; `sAcceptedActivityIds`,
src/data/union_room.h:398-456]; most lists hold one id. A console in the Union Room advertises
`ACTIVITY_SEARCH` (12) and searches `LINK_GROUP_UNION_ROOM_INIT`, list `{ACTIVITY_SEARCH, 0xFF}`
[src/data/union_room.h:419], so a trade host (`ACTIVITY_TRADE`, 4) or Mystery Gift host
(`ACTIVITY_WONDER_CARD`, 21) is filtered out by that byte alone. Inside the room the search is
`LINK_GROUP_UNION_ROOM_RESUME` [union_room.c:2664]: `IN_UNION_ROOM | activity`, `IN_UNION_ROOM = 1 << 6`
[include/constants/union_room.h:49].

Record byte 16 is the activity: 21 lists the host on the Wonder Cards screen, 22 on the Wonder News
screen, where the console joins it and completes a session.

## The connect: IN_UNION_ROOM, exactly and alone

`IsPartnerActivityIncompatible` [src/link_rfu_2.c:2925] tests

    else if (partner->activity != IN_UNION_ROOM)   // [link_rfu_2.c:2933]
        return TRUE;

as an exact equality. `IN_UNION_ROOM | ACTIVITY_TRADE` (0x44) spawns the avatar, but talking to it
prints "Communication avec PkCamp" then "le DRESSEUR est occupé" with no packet on the air: the connect
is refused inside `Task_TryConnectToUnionRoomParent` [link_rfu_2.c:2963]. The trade intent lives in
`sPlayerCurrActivity`, negotiated after the link is up. The bare `IN_UNION_ROOM` (0x40) connects. The
avatar tracks the beacon live: it walks out and back in when the host restarts.

## No parent NI, and the five-frame rule

The Union Room child expects no parent join-status NI: once its name NI succeeds
[AgbRfu_LinkManager.c:1203], `LinkManagerCB_UnionRoom` [link_rfu_2.c:2526] sets a TYPE_UNI receive
buffer, never TYPE_NI, and `Task_UnionRoomListen` [link_rfu_2.c:533] starts `Task_PlayerExchange` as
MODE_CHILD. Only the trade-centre callback [link_rfu_2.c:2364] adds a TYPE_NI buffer.

An NI body is fatal. `rfu_STC_NI_receive` takes LCOM_NI_START without a game buffer
[librfu_rfu.c:2202], but the body needs one: `rfu_STC_NI_initSlot_asRecvDataEntity` fails with
ERR_RECV_BUFF_OVER [librfu_rfu.c:2300] → `recvErrorFlag` → REQ error → `LMAN_MSG_REQ_API_ERROR` →
`RfuSetErrorParams` → "erreur de connexion, rapprochez-vous" [link_rfu_2.c:2585].
`RFULeader(skip_parent_ni=True)`, enabled by `--union-room`, skips it.

The console disconnects on the fifth parent frame it left unanswered (three captures agree):

    child NULL 28.361  host NI ts=8..12, K only   D 28.496   (NI_STARTs ts=6,7 were mirrored)
    child NULL 34.069  host NI ts=8..12, K only   D 34.199
    child NULL 36.527  host UNI ts=6..10, K only  D 36.628

From the child's NULL: 135/130/101 ms, the third two frames earlier for the two mirrors it lacked,
matching `maxMFrame = 4` [link_rfu_2.c:128]. Trade-centre captures that completed showed at most two.

`--union-room-keepalive N` (120 works) re-presents the first parent NI_START for N VBlanks before UNI,
so the console always has an acknowledgement to send. It then waits about eight seconds:
`Task_UnionRoomListen` retries `rfu_UNI_setSendData` every frame
and fails with ERR_SUBFRAME_SIZE while a NI_START is pending: the receive control takes 2 of the
child's 16 LL-frame bytes [librfu_rfu.c:2262] and the UNI subframe needs 16 [librfu_rfu.c:1449]. The
pending receive is released only by `NI_failCounter_limit`, 480 frames after the last NI_START
[link_rfu_2.c:139, AgbRfu_LinkManager.c:1328] (measured: the first UNI frame 482 frames after the
host's last). Nothing releases it early.

## What the console does once connected

[src/union_room.c:2858-2879]

    if (gReceivedRemoteLinkPlayers) {
        CreateTrainerCardInBuffer(gBlockSendBuffer, TRUE);
        CreateTask(Task_ExchangeCards, 5);
        uroom->state = UR_STATE_COMMUNICATING_WAIT_FOR_DATA;
    }
    ... then, if sPlayerCurrActivity == (ACTIVITY_TRADE | IN_UNION_ROOM),
        UR_STATE_SEND_TRADE_REQUST

The prompt reads "PkCamp: oh bonjour \<name>, vous désirez quelque chose ?" with Salut / Combat /
Tchat / Retour. Each choice sends one `SEND_PACKET` and waits
[UR_STATE_HANDLE_ACTIVITY_REQUEST, union_room.c:3151]:

| the console sends | activity | the host answers |
|---|---|---|
| 0x48 | CARD (Salut) | 0x51 ACCEPT |
| 0x44 | TRADE (trading board) | 0x51 ACCEPT |
| 0x41 | BATTLE (Combat) | 0x51 ACCEPT |
| 0x45 | CHAT (Tchat) | 0x51 ACCEPT |
| 0x40 | EXIT (Retour) | treat as the console's close |

After each activity both sides `SetLinkStandbyCallback` [union_room.c:2995, :3012] and the console
returns to its prompt. The Switch build also gates the accepting side on
`svc_CommsAllowedByParentalControls()` [union_room.c:3159, :3037, REVISION >= 0xA], so the console's
own parental controls can turn its request into a DECLINE. Salut shows the host's trainer card and
repeats; Retour sends 0x40 then READY_CLOSE_LINK, and once answered the console disconnects normally
and stays in the room with no error.

## The trading board

The board lists partners whose advertisement carries `tradeSpecies`, `tradeType` and `tradeLevel`
[union_room.c:3400]: record byte 18 (`type << 2`), 19 (`gender | level << 1`) and 22:24 (little-endian
`tradeSpecies:10` of `RfuGameData` [include/link_rfu.h:107]). Species 277 (Treecko; low byte alone 21,
Spearow) listed "PkCamp / NORMAL / ARCKO / 26", which measures byte 23.

A trading-board trade is one trade per link. `Task_StartUnionRoomTrade` sets `gMain.savedCallback =
CB2_ReturnToField` before `CB2_LinkTrade` [union_room.c:1744], and `CB2_SaveAndEndTrade` keeps the
link only when the saved callback is the trade centre's `CB2_StartCreateTradeMenu`
[trade_scene.c:2722-2725]; any other ends in `SetCloseLinkCallback`. The sequence: the console's
Pokemon block (count 9), the host's, its mail block (count 19), the host's, the animation, its
READY_FINISH, the host's CONFIRM_FINISH, the save barriers, READY_CLOSE_LINK both ways, its normal
disconnect back into the room. Another board trade is a new connection. The trade centre returns to
its trade menu instead [trade.c:2094-2113]. There is no party exchange, menu or room route. One
measured board trade took about 45 s from board pick to room (~10 s keepalive wait, ~32 s
animation).

## Chat

Chat rides `SendBlock`, not `Rfu_SendPacket`: every member calls `SendBlock(0, sendMessageBuffer,
0x28)` unsolicited, with no `BLOCK_REQ` [`ChatEntryRoutine_Join`, union_room_chat.c:429;
`ChatEntryRoutine_SendMessage`, :823]. A 0x28-byte block is `count` 4.

    [0]      command: 0 NULL, 1 CHAT, 2 JOIN, 3 LEAVE, 4 DROP, 5 DISBAND
    [1..8]   player name, PLAYER_NAME_LENGTH + 1 bytes, EOS-terminated
    [9]      multiplayer id            (JOIN / LEAVE / DROP / DISBAND)
    [9..39]  message text, EOS-terminated (CHAT)

[`PrepareSendBuffer_*`, union_room_chat.c:1256-1281; `ProcessReceivedChatMessage`, :1283]. On ACCEPT
of 0x45 the console enters `Task_StartActivity`'s chat branch [union_room.c:1938], which stops only new
connections (`rfu_LMAN_stopManager(FALSE)`) and keeps the link. Both members send JOIN on entry
without waiting; the host reacts to the console's JOIN.

A line is 15 entries (`MESSAGE_BUFFER_NCHAR` [union_room_chat.c:21]; the 31-byte buffer allows
0xF9 pairs [string_util.c:560]). The receiver copies whatever arrives [:1308] into one unclipped row,
so entry 16 onward runs off screen; the host refuses an over-long `--chat-message` or `--chat-file`
line at start-up (`uroom_chat.entry_count`).

The leader must close on a LEAVE: the leaver waits for the parent to drop the link
[`ChatEntryRoutine_AskQuitChatting` cases 2/4/5, union_room_chat.c:596-660], else it sits on "quit
the chat?". The host sends DROP 0.1 s after LEAVE and runs the close-link handshake. Lines appended
to `--chat-file` reached the console about 1.7 s after the write (measured).

## The link battle (UR_BATTLE 0x41)

`HasAtLeastTwoMonsOfLevel30OrLower` [union_room.c:4565] requires two non-egg party mons at level 30
or lower, checked when the console offers [union_room.c:2923] and when it accepts [union_room.c:3176,
sending DECLINE]; each side tests only its own `gPlayerParty`, and the refusal is a message on screen.

After both pick two mons, each sends one 0x20-byte block whose first byte is `ACTIVITY_ACCEPT | 0x40`
= 0x51 (0x52 if cancelled), the rest zero [union_room_battle.c, `CB2_UnionRoomBattle`]; anything else
closes the link with "refused". The Switch path then has two link-task waits with a standby between
(`#if REVISION >= 0xA` cases 50/51/52).

`SetUpPartiesAndStartBattle` keeps the two chosen mons, zeroes the other four, and calls
`StartUnionRoomBattle(BATTLE_TYPE_LINK | BATTLE_TYPE_TRAINER)` [union_room.c:1811], setting
`gLinkPlayers[0].linkType = LINKTYPE_BATTLE` (0x2211) [link.h:92], which `TryReceiveLinkBattleData`
tests exactly [battle_controllers.c:520]. Then [`CB2_HandleStartBattle`, battle_main.c:934]:

    state 1  SendBlock struct LinkBattlerHeader {versionSignatureLo, versionSignatureHi,
             vsScreenHealthFlagsLo, vsScreenHealthFlagsHi, struct BattleEnigmaBerry}
    state 3  SendBlock gPlayerParty[0..1]   200 bytes      state 4  recv -> gEnemyParty
    state 7  SendBlock gPlayerParty[2..3]   200 bytes      state 8  recv
    state 11 SendBlock gPlayerParty[4..5]   200 bytes      state 12 recv
    state 15 InitBattleControllers

The party exchange is the trades' 3 × 200-byte transfer (`mon.party_blocks`; `Rfu_InitBlockSend`
allows up to 252).

### Master election

In a link single battle only the `BATTLE_TYPE_IS_MASTER` side sets `gBattleMainFunc =
BeginBattleIntro`; the other keeps `BeginBattleIntroDummy` [`InitLinkBtlControllers`,
battle_controllers.c:141; `SetUpBattleVars`, :45]. The non-master runs no turn resolution, damage or
RNG: it receives BUFFER_A controller commands, displays them and answers, so the host as non-master
is a battle controller.

`LinkBattleComputeBattleTypeFlags` [battle_main.c:886], from the console at multiplayer id 1: if
`gBlockRecvBuffer[0][0] == 0x100` or both signatures are equal, player 0 is master; else the lowest
index with the highest version. A signature below 0x201 other than 0x100 makes the console master;
the host sends 0x200.

### The link buffer protocol

Every controller command is one SendBlock with an 8-byte header [battle_controllers.c:401-435]:
`LINK_BUFF_BUFFER_ID, ACTIVE_BATTLER, ATTACKER, TARGET, SIZE_LO, SIZE_HI, ABSENT_BATTLER_FLAGS,
EFFECT_BATTLER`, then the payload, stored as `alignedSize = size - size % 4 + 4` (a 4-byte payload
takes 8). `bufferId` 0 = BUFFER_A (command), 1 = BUFFER_B (reply), 2 = exec-flag clear, whose one
byte is the sender's multiplayer id [Task_HandleCopyReceivedLinkBuffersData:566-594]. Battler 0 is the
master's mon, battler 1 the host's.

The sync rule [battle_util.c:185-201]: `MarkBattlerForControllerExec` sets bit `28+battler`; when the
command's block returns, `MarkBattlerReceivedLinkData` sets `gBitTable[battler] << (i*4)` for every
player i and clears bit 28+battler; each player clears its nibble with bufferId 2. The master advances
only on `gBattleControllerExecFlags == 0`, so every command must be acknowledged for both battlers.

Of the 56 player-buffer commands [battle_controller_player.c:110], these need more than the ack:

    CONTROLLER_GETMONDATA    -> EmitDataTransfer(BUFFER_B, size, data)   [player.c:1515]
    CONTROLLER_CHOOSEACTION  -> EmitTwoReturnValues(1, B_ACTION_*, 0)    [player.c:232-241]
    CONTROLLER_CHOOSEMOVE    -> EmitTwoReturnValues(1, 10, move | target << 8) [player.c:342]
    CONTROLLER_CHOOSEPOKEMON -> EmitChosenMonReturnValue(1, partyId, order)    [player.c:1316]
    CONTROLLER_OPENBAG       -> EmitOneReturnValue(1, itemId)            [player.c:1340]
    CONTROLLER_EXPUPDATE     -> EmitTwoReturnValues(1, RET_VALUE_LEVELED_UP, exp) [player.c:1051]
    CONTROLLER_ENDLINKBATTLE -> gBattleOutcome = payload[1], then ack     [player.c:2876]

`B_ACTION_USE_MOVE` 0, `USE_ITEM` 1, `SWITCH` 2, `RUN` 3 [battle.h:34].

The first command is `GETMONDATA` `REQUEST_ALL_BATTLE` [battle_main.c:2519], answered with a 0x58-byte
`struct BattlePokemon` [pokemon.h:170] as `CopyPlayerMonData` builds it [player.c:1519];
`statStages`, `ability`, `type1`, `type2`, `status2` and `unknown` are recomputed, so zeros serve. BUFFER_B replies for battler 0 may be skipped: the console answers its own GETMONDATA
from `gEnemyParty` [link_opponent.c:444].

A link battler may run [battle_main.c:3239] with top turn order [:3548-3560], so answering the first
`CHOOSEACTION` with `B_ACTION_RUN` exercises the whole path and ends the battle.

### Two rules not visible in the decomp

A block's size does not decide its path. Every ack and short command (the first `GETMONDATA`
included) is a 16-byte, two-fragment record, so inside a battle the state routes a block, never its
size.

An ack must never overtake the echo of the block it acknowledges. The console sets the exec-flag bit
only when its own block returns [`MarkBattlerReceivedLinkData`, battle_util.c:193] and the host's ack
clears it [battle_controllers.c:585]; a two-fragment ack can pass a seven-fragment echo:

    104.268 console bufferA battler 0 PRINTSTRING (72 B)
    104.366 US      ack battler 0                     <-- ours first
    104.383 echo    bufferA battler 0 PRINTSTRING

The echo then set the bit and the console waited forever on `gBattleControllerExecFlags == 0`, which
gates `Cmd_waitmessage` [battle_script_commands.c:2041], frozen on the battle-end message with the link
alive. `HostTradeEngine._echo_owed` holds a new block while any child command awaits its mirror.

The ack also waits for every fragment of the echo. `rfu_leader.echo_blocks` keeps each echoed
`SEND_BLOCK_INIT` with the set of fragment indices emitted, and the ack waits for 0..count-1. An empty
echo queue is 24 times too slow; counting echoes, or watching only the last fragment, lets a re-sent
fragment's echo share a frame with the ack. No later message frees a console waiting on
`gBattleControllerExecFlags`; ending the host returns it to the room through the error screen.

### The pace is the RFU VBlank budget

A link battle step takes about a second against the host, in both directions. Datagram turnaround
is median 5.8 ms (p99 16.6 ms over 8204 replies; the console's median 8.1 ms). Consecutive `bufferA`
commands are a median 800 ms apart; a console block is echoed in 19 ms and the host's answering block
follows 355 ms later. `HostSession.tick` emits one RFU slot per call at `HOST_VBLANK_SECONDS =
1/59.727` = 16.74 ms (measured 17 ms × 5035, 16 ms × 413); a command block spans about twenty frames,
~340 ms, and a step is that plus the return leg. More than one slot per VBlank is not what the
hardware link does.

## What two real consoles put on the air

A passive capture of a trade between two real consoles (FireRed hosting through the third NPC,
LeafGreen joining). Monitor frame counts are a floor; the 802.11 sequence counter gives what the
monitor missed (19% of the hosting console's frames captured here, 43% in a capture against the
host). Sequence-corrected, same console `48:f1:eb:20:9b:22`:

| station | talking to the host | talking to a real console |
|---|---|---|
| the FireRed console | 161.8/s | 25.5/s |
| its peer | 58.9/s, the host at one slot per VBlank | 6.1/s, the LeafGreen |

In that passive capture of a console-to-console trade the stations sent 25 and 6 frames a second;
against the host's 59/s the same console sent 162/s. The 25.5/s figure rests on the softest capture.

A FireRed console hosting over Direct Corner carries the Switch profile name in plain ASCII at offset
0x11 of `application_data`; the in-game trainer name is absent from the advertisement.

## The console's output rate is its own, not an echo of ours

`--tick-hz` sets the host's RFU slots per second (default one per VBlank). One trade at each rate,
same console:

| | 59.727 Hz (the default) | 20 Hz |
|---|---|---|
| host datagrams out | 79.3/s | 39.3/s |
| console datagrams in | 61.8/s | 51.8/s |
| trade duration | 92 s | 197 s |
| console datagrams, whole session | 5663 | 10218 |

At 20 Hz the console's rate fell by a sixth, the trade took 197 s against 92 s, and the console sent
80% more datagrams. `--tick-hz` is an instrument; the default is one slot per VBlank.

# The cable-club colosseum

`frlg_trade_host.py --colosseum` hosts Pokemon Center 2F → third NPC (club sans fil) → Colosseum →
Single Battle → JOIN. Only `CB2_ReturnFromCableClubBattle` increments the Wonder Card's `battlesWon`
[src/cable_club.c:792]; the Union Room battle returns through `CB2_ReturnToField`.

`Task_StartActivity` treats `ACTIVITY_BATTLE_SINGLE` like `ACTIVITY_TRADE` [union_room.c:1903] except
for the map (`MAP_BATTLE_COLOSSEUM_2P` at (6, 8), not `MAP_TRADE_CENTER` at (5, 8)) and a
`HealPlayerParty()`, so the trainer-card exchange and `--card-flag-id` work unchanged. Four things
change:

1. The activity byte: `LINK_GROUP_SINGLE_BATTLE` accepts `{ACTIVITY_BATTLE_SINGLE, 0xFF}`
   [src/data/union_room.h:398]; `build_colosseum_app_data` changes that byte only.
2. `BattleColosseum_2P_EventScript_PlayerSpot0/1` has no party check [data/scripts/cable_club.inc:576]
   (the 4P `ChooseHalfPartyForBattle` has the selection step). The seat handshake is unchanged.
3. `Task_StartWirelessCableClubBattle` case 2 sends `SendBlock(0, &gLocalLinkPlayer,
   sizeof(gLocalLinkPlayer))` [cable_club.c:701]: the bare 28-byte `struct LinkPlayer`, without the
   entry block's GameFreak magics, unprompted from both sides; the console parks in case 3 until every
   record lands. Then 20 frames, `IsLinkTaskFinished`, `SetLinkStandbyCallback`, another wait (cases
   4-6, `REVISION >= 0xA`), `CB2_InitBattle`.
4. The whole party fights: `party_blocks` takes the party as it stands [union_room_battle.c:47].

From `CB2_InitBattle` on it is the Union Room battle, signature 0x200 included, without the 0x20-byte
0x51 selection block (`CB2_UnionRoomBattle` only).

The seat needs the READY key alone: with no movement sent the console proceeds to
`Task_StartWirelessCableClubBattle` (`GetCableClubPartnersReady` reads link states only
[overworld.c:2989]). There are no post-seat standby rounds; a host waiting for them deadlocks while the
console, parked in case 3, sends `SEND_BLOCK_INIT` count 3 and
`04 40 00 80 65 df | bb c8 ff 00 11 00 | 01 00 03 00 00 00` (version 0x4004 FireRed, `lp_field_2`
0x8000, its trainer id). That block's arrival finishes the entry.

The host owes the exit key after a battle too: the door waits for every player in
`PLAYER_LINK_STATE_EXITING_ROOM` [overworld.c:2977], else the console sits on *"conduire a la sortie
de la piece, veuillez patienter"* until the link errors.

## What decides whether a colosseum run counts

A forfeit is a win for the console: `HandleAction_Run` sets `B_OUTCOME_WON` for the side that did not
run, ORed with `B_OUTCOME_LINK_BATTLE_RAN` (1 << 7) [battle_main.c:4300], which
`HandleEndTurn_BattleWon` clears [battle_main.c:3734] before `CB2_ReturnFromCableClubBattle` switches on
it. The id recorded is `gLinkPlayers[GetMultiplayerId() ^ 1].trainerId` [cable_club.c:794], from the
28-byte record, counted once each (five remembered per stat) [mystery_gift.c:630]. Three forfeits
against three different `--id` values raise `battlesWon` to 3, which the Battle Count Card rewards
with its POTION. After one:

    save 0x3434:  0100 0000 0000 2300    battlesWon 1, lost 0, trades 0, icon 35 CARD_TYPE_LINK_STAT
    game data:    "1 battles won"

# Two host-side constraints

The close path depends on the hole guard: `done` comes from the disconnect path, gated on
`disconnect_requested`, set by `_tick_close_link` inside `activity.tick()`, which `HostSession.tick`
skips while the hole guard holds. A console that stops acknowledging latches the guard, so the close
timer stalls; the runtime stops once the console leaves LDN after a confirmed exit.

An all-zero `easyChatProfile` prints "??? ???" on the trainer card: word 0 is `EC_GROUP_POKEMON_2`
index 0 (`SPECIES_NONE`), which `IsECWordInvalid` rejects and `CopyEasyChatWord` replaces with
`gText_ThreeQuestionMarks` [easy_chat.c:166-171]. A word is `(group & 0x7F) << 9 | (index & 0x1FF)`
[easy_chat.h:1089], four per card [trainer_card.h:28]; pad a short phrase with `EC_WORD_UNDEFINED`
(0xFFFF), which prints nothing.
