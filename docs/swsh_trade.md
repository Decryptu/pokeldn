---
title: The Link Trade
parent: Sword and Shield
nav_order: 3
---

# Trading with a retail Sword and Shield

The Sword and Shield Link Trade, from the snapshot exchange to the save. Framing, content registration
and the PK8 are on [The sync framework](swsh_protocol.md).

## The sequence

    1  the console broadcasts its 3456-byte snapshot on protocol 0x84, port 0
    2  the client acknowledges the fragments (0x21) and the transfer (0x19 / 0x28)
    3  the client sends its own snapshot on 0x84 port 1 and reports it complete
    4  the trade screen opens
    5  the console sends the 40030 RPC pair on 0x7C port 1, several times a second
    6  the client answers the pair and sends `imReady` on 20030
    7  the console offers a Pokemon on 20030; the client offers one on 10050
    8  the player accepts (box command 4)
    9  the confirmation ladder runs on content 40
    10 the console writes its save

A hosting console does not ack a joiner's snapshot sent on port 0; the joiner's goes on port 1. Until
its 0x84 is answered the console sends nothing else and retransmits it indefinitely.
`pokeldn/ldn/broadcast4.py` implements all four kinds.

## The trade RPC

The ping, block messages and the offer use port 0, the 40030 pair port 1; an answer on the wrong port
is not read.

    id 40030 = 40000 + 30
      1  offset      30
      2  base        10000, and 20000 in the other member
      3  station id  the sender's, equal to the host_constant of the seat record
      4  clock       a counter advancing between messages
      5  bytes(4)    00000000 for the 10000 member, 000018fc for the 20000 one

`000018fc` is the sentinel `0xfc18` ([the step body](#the-step-body)). `3e4e000012020801` is 20030
carrying `imReady{isReady:true}`; a joining client sends it. The messages rebuild byte for byte from
the parsed fields (`pokeldn/swsh/trade.py`).

- Send each answer once (`--answer-once`); re-deriving answers on a timer resends the offer.
- Readers return `None` on a message that is not a trade message. A mesh message on a reliable window
  (`44 00 01`, [host migration](#host-migration)) that raises ends the receive task and the trade.

## Host migration

A hosting Sword that leaves the session requests host migration on protocol 0x18 port 1
(`nn::pia::mesh::LeaveWithHostMigrationJob`): reliable header `0f 00 00 03 00 01 00 01` then the mesh
message `44 00 01`, MIGRATION_START `[0x44, host index 0, new host index 1]`. The named client must
broadcast `MIGRATION_FINISH` on the reliable window of mesh port 1 ([The Pia layer](pia.md#host-migration)).
`--answer-migration --update-mesh` sends the finish and publishes mesh updates under the new host
index. Retaining a session after the handover is unverified.

A hosting retail Sword sends MIGRATION_START once, in two situations:

| when | condition |
|---|---|
| 0.8 s after its box command 3 | after a completed trade |
| a few seconds after the player accepted, before the console tears down with `2-ALZAA-0016` | a trade that failed before the ladder, the joiner sending no confirmation command |

`bin/swsh_host.py --migrate` ends its hosted trade with box command 3 and MIGRATION_START. By default
the host keeps the session.

## Hosting a trade

`bin/swsh_host.py` hosts and `pokeldn/swsh/host_trade.py` leads as a hosting Sword does. A retail
French Sword 1.3.2 and an emulated Shield 1.3.2 each join it and trade.

The host builds a station advertisement with a fresh network id, device id and account uid. On 0x84 it
acknowledges the joiner's three snapshot fragments, rewrites that live snapshot with its trainer
identity and the `--offer-file` PK8, then sends the result on port 0. The console's offered PK8 is
written to `--received`. `--advert FILE` and `--snapshot FILE` use saved records instead.

The station handshake is acked both ways, the host's request carrying the joiner's random byte at
[0x10]; unacked, the joiner repeats its request. The host answers the joiner's Sync Clock (0x1C, every two
seconds) and Clone Clock (0x77).

The application layer, after the [ping handshake](swsh_session.md) both ways:

    0x84  each side's snapshot on the port of its station index (joiner 1, host 0), each acked on the
          same port; a retail host sends first, `host_trade.py` second
    110   the joiner pings first once its trade screen is up; the host answers with its own ping
          and the reply (a host ping before that screen is acked and dropped)
    30    the host opens content 30; each side offers on 20030 and sends box command 1; each
          acceptance is box command 4
    130   the joiner pings first
    50    the host publishes its Pokemon as element 0 and relays the joiner's 10050 as element 1
    120   the host pings first
    40    the ladder: host commands as element 0, the joiner's 10040 as element 1, phases 0 to 4

## The trade animation

The console plays its trade animation after its last syncCommand 40 (`3`), with no trade message
during it. A retail Sword joining `bin/swsh_host.py` started it 1.2 s after that syncCommand and gave
the player control at about 24 s.

## Trades in a row on one session

A session carries one trade after another: trade state 9 sends event 7 (success) or 8 (failure), writes
state 0 and the player is back in the box. Content 30 and ping 110 live for the session (setup
`0x010c9280`); content 50 with ping 130 (trade state 1, `0x010d5440`) and content 40 with ping 120
(state 6, `0x010dabc0`) are rebuilt for every trade, each element minted with a new SyncPing. A SyncPing
that reached synced is never reset in place, so a ping 130 sent while a console has no content 50
reaches no holder.

The box screen's step machine (`0x00aa5160`, table `0x2059218`) reads the partner's box-command flags
set by the listener `0x00c8d900`. In step 3, on the partner's flag 1 (its offer), it clears flags 1 and
4 together (`0x00aa5688..0x00aa569c`); step 7 waits for flag 4 (`0x00aa5628`), and only step 10 issues
action 6, which starts trade state 1. A box command 4 sent in the same burst as the offer is erased and
the console waits in step 7 with "En attente d'une réponse". The partner's 4 must arrive after the
console has processed its offer: `pokeldn.swsh.host_trade` sends its 4 only after the joiner's 4, and
the joiner launcher sends its 4 in answer to the host's.

Step 7 ends only on the player pressing B (no timer): a press clears the partner's flags, sends box
command 5 (the acceptance withdrawn) and leaves the sequence (`0x00aa57d0`); in step 3 it sends box
command 2. A partner's offer and box command 1 sent before that box command 5 are cleared with its
flags, so `pokeldn.swsh.host_trade` and `bin/swsh_connect.py` send their offer and box command 1 again
after a box command 5. Without the second send the console stays on "En attente d'une réponse".

Every later trade repeats the trade's own part: both offers and box command 1, the two box command 4s
in that order, ping 130 (the joiner pings first), a new content 50 at phase 0, ping 120, a new content
40 from phase 0 to 4. No 0x84 snapshot, ping 97 or 110, box command 3 or content 30 publish comes
between trades. `bin/swsh_host.py` and `bin/swsh_connect.py` with a repeated `--offer-file` trade one
queued record per trade on one session with a retail Sword joiner and host respectively; the host
closes when the console leaves.

`bin/swsh_connect.py` takes the console's offer after a finished ladder (phase 4 on 40040) as the next
trade and clears its per-trade state; the 40030 pair and the ping answers carry over.
`bin/swsh_host.py --accept-first --lead SECONDS` plays a console host's player (accepts first, offers
its next queued record after a trade); the two launchers trade two records each way on one session on
simulated boards (`tests/test_esp32.py`).

When a retail joiner's player presses B in the box, the console sends box commands 2 and 3 and mesh
`0401` and deauthenticates with no error; its next search can join the same hosted network. A searching
console joins any network that passes the
[matching rules](swsh_session.md#how-a-searching-sword-finds-a-partner).

## The box state machine

Content 30 carries everything from the trade screen to the offer. `onBoxSyncStateCommand` `0x010ce180`
drops wire commands 0 and 7 and above and notifies every listener with event *N* for wire command *N*
(jump table `0x2067bec`). The listener `0x00c8d900` sets `[owner + 0x218 + code] = 1`; 1 offers, 2 withdraws the offer; 4 confirms, 5 withdraws a 4. The sender `0x010cda70(content, command)` is driven by the scene's jump table `0x00a96d10` on its
action `+0x78`:

    action 1  ->  command 3
    action 2  ->  the Pokemon (0x010ca430), then command 1
    action 3  ->  command 2
    action 4  ->  command 5
    action 5  ->  command 4
    action 6  ->  0x010ca640, which stores its Pokemon and sets the trade state to 1

A command is held in `[content+0x48]` until the channel-ready byte `[content+0x4c]` is set; a different
command arriving meanwhile sets the error byte `[content+0x4d]` and sends nothing.

Command 3 is sent by exactly one side: the setup `0x010c9280` sets `[session+0x419] = 0x00dceea0() & 1`
(from the player list) and the per-frame update `0x010c9bb0` sends it when that byte is clear.
`--box-open` sends box commands at the 0x84 ack.

## The trade state machine

`[session+0x140]`, range 1..10, table `0x2067b68`: 1 starts content 50 and sends its Pokemon (`0x010ca0a0`),
2 waits, 3 is the Pokemon exchange (`0x010d54b0`), 4 decides (`0x01109320`), 6 installs four delegates and
starts content 40 (`0x010ca1ac`), 8 releases it (`0x010dac90`), 9 is terminal (`[+0x144]` set means
failure; listeners get event 8). The box callback `0x010ca800` drops events unless the state is 0. State
2 ends in the delegate `0x010cc380`: the partner's Pokemon goes to `session+0x70`, a 0x60-byte record
(`0x010f5cc0`). When content 50's init `0x010d4d90` fails, the caller sets `[session+0x144] = 1`, state
9: the interrupted-communication message.

## The confirmation ladder

Content 40 is a barrier, one rung per command.

### The phase-to-state map

The state is `delegate+0x5c`. The machine `0x010dae70` dispatches `state - 1` into the table `0x2067ed0`;
states 2, 4, 7, 9 leave only through `0x010dbf40`, which ignores a u16 above 4 and otherwise indexes the
table `0x2067f4c`:

    phase 0  -> state 1              -> send(0), announcing 1     0x010db308
    phase 1  -> state 3              -> send(1), announcing 2     0x010db0b0
    phase 2  -> state 5 -> 6 or 8    -> send(2), announcing 3     0x010db0dc / 0x010db104
    phase 3  -> state 10 or 11 -> 12 -> send(3), announcing 4     0x010db16c
    phase 4  -> state 13 -> 14       -> 0x010db970 tears down, content+0x84 = 0xfc18; no send

`[delegate+0x58]` (`0x110e620(...) & 1`) is the role: state 7 sends 2 at once, state 9 after the
countdown `[delegate+0x60]`, an xorshift draw of 2..302. The init installs the delegate as the 10040
holder's listener (`0x010da6d0`) and its second interface at `[content+0x2c0]` (`0x010da6bc`).

### The pump

`0x010db3e0`, run by content 40's tick before the machine, is a 17-state machine on `[content+0x80]`
with a shared tail. The tail commits the content's phase `[content+0x17c]` through `0x010de310` (which
drops the pending body and empties the job queue `content+0x310`) and calls the delegate's state setter
when the phase equals the announced one, then runs the queued jobs `0x010ddf40` and the element update
`0x006d4b80(content+0xd0)`.

| field | meaning |
|---|---|
| `+0x84` | the committed phase; the constructor sets `0xfc18` |
| `+0x86` | the phase announced with the last command, `data + 1` at all five send sites (`0x010dbab0`) |
| `+0x17c` | the phase, `element+0xac` |

The ladder climbs when the phase reaches `+0x86`. Pump states (table `0x2067f08`; `[+0x1c0]` is the
element's `+0xf0` channel):

    1   element ready -> 2; delegate slot 0 with the phase (command 0, announcing 1)
    2   a pending body at +0x88 -> 3
    3   all ready, every pair's low half == phase: send the body -> 4
    4   0x006d3690 publishes the high half; the master goes to 8, others to 7
    8   every station has sent a command -> 9
    9   no resend byte set -> 10
    10  every high half == announced: the master writes shared value = announced -> 7
    11  clears every flag (a station left); [+0x374] ? 12 : 2
    14  the gated commit

States 8 to 10 run only on the master (`0x018407f0`); others follow the shared value. Content 40's
registrar stores 1 at `[+0x374]`: a station leaving goes 11, 12 and ends the ladder (`0x010dc720`).

### The phase is the element's field

The phase is `element+0xac` (`0xd0 + 0xac = 0x17c`): the registrar mints the 40040 element at
`content+0xd0` with `0x006d44e0(element, 0)`, and nothing in `0x010c0000..0x010e0000` stores to it.

It advances only in `0x006d4ca0`, the tail of the element update `0x006d4b80`: the phase becomes the
shared value `0x006d3260([element+0xf0])` (`0xfc18` when none) once that value is published as the
station's own low half, and the content is told.

`0x018407f0` is true on the console hosting Pia's mesh ([session](swsh_session.md#the-pia-session-object)).
Only it seeds the shared value, the `+0xf0` channel's 16-bit sub-element
([Sub-element kinds](swsh_protocol.md#sub-element-kinds)); every station adopts it. The other shapes
the content sends are [below](#shapes-the-confirmation-content-also-sends):

    0x006d3260  read            ready [sub+0x61] ? [sub+0x88] : 0xfc18
    0x006d33b0  write(v)        0x006d3570 when not ready or body != v
    0x006d3570  publish         body [sub+0x88] = v and queue it per station
    0x006d3060  all high == v   every pair's [sub+0x8a] == v

A write leaves the ready byte alone (only the receive `0x006d6a08` stores `+0x60`), so a read returns
`0xfc18` until a message arrives; on the master that message is its own.

### The step body

The four-byte body on content 40's elementId 20000, low half the phase, high half the last announced:

    0x006d3980(channel, v)   body = <u16 v><u16 [sub+0x8a]>    low; from the element update
    0x006d3690(channel, v)   body = <u16 [sub+0x88]><u16 v>    high; from pump state 4, [content+0x86]

An observed ladder:

    000018fc   phase 0, announced 0xfc18   the birth sentinel
    00000100   phase 0, announced 1        the cue; command 0 already sent
    01000100   phase 1, announced 1        caught up, committed
    01000200   phase 1, announced 2        state 3 sent command 1
    02000200   phase 2, announced 2        caught up
    02000300   phase 2, announced 3        committed, sent command 2
    04000400   phase 4                     the teardown rung

`trade.parse_sync_step`, `SYNC_LADDER` and `sync_announced_phase` decode it.

### The command

`SyncSaveDataHolder{syncCommand{data:N}}` on 10040, reliable port 0. The handler `0x010dbc90` drops a
sender `0x006b5850` cannot resolve (`0xfd`), passes the int32 at `[arg1+0x14]` to the relay `0x010dbe20`,
then always calls `0x006a24a0(obj, sender, 1)` on `[content+0x2a0]` (`0x010dbdf8..0x010dbe08`): the
value is never read by the ladder, so any command advances a rung. The state moves only through
`0x010dbf40`, called by the pump with its own phase.

`[content+0x2a0]` is a per-station flag map (`0x006a24a0` sets, `0x006a2840` is 1 when every listed
station is set, `0x006a2760` clears); state 8 waits on it and the commit and state 11 clear it. The flag
is set in the network update's drain `0x006db3b0`, which the frame `0x00f1df30` runs twice, around the
game update. Content 40's command tick `0x010dae70` runs between the two drains.

A rung takes one command reaching the master after the previous commit. In rung 0 any command counts,
the one on the cue `00000100` included; later, the command on the cue (`01000200`, `02000300`,
`03000400`) lands before the commit and is cleared, and the one on the caught-up body (`01000100`,
`02000200`, `03000300`) counts:

| commands, one per new body | last body |
|---|---|
| 1, on `00000100` | `01000200`: rung 0 |
| 4, `000018fc` to `01000200` | `02000300`: rungs 0 and 1 |
| 9, `000018fc` to `04000400` | `04000400`: the trade |

`--confirm-commands 0,1,2,3,0,1,2,3,0,1,2,3` pops one per new body, `000018fc` included; the queue must
not run dry. `answer_rpc` echoes the body and moves neither half; `--confirm-phase N` writes the low
half.

### The cancel and proceed messages

30040, the `SequenceDataHolder` ([the protocol page](swsh_protocol.md#the-30000-holder)), is stored at
`[content+0x2b8]` with listener `content+0x68` (vtable `0x02580030`):

| case | message | handler |
|---|---|---|
| 1 | CancelAccepted | `0x010dce70` |
| 2 | RequestCancel | `0x010dc920` |
| 3 | RequestCancelAll | `0x010dcaa0` |
| 4 | RequestForcedProceed | `0x010dc7b0` |

Each acts only when `currentSeqNo` equals the committed phase `(s16)[content+0x84]`. RequestCancel
answers the sender with `CancelAccepted{[+0x84], isForced: 0}` and clears its flag; RequestCancelAll
answers every listed station with `isForced: 1` and clears every flag. CancelAccepted re-runs states 2
to 4 and leaves the phase. RequestForcedProceed (job `0x010dd040`) writes
`0x006d33b0([content+0x1c0], targetSeqNo)`, state 10's write without states 8 and 9 or the master test.

RequestForcedProceed advances the shared phase without a `syncCommand` (an emulated Shield). A ladder
whose later commands are these requests stops at "Communicating" before the save.

### Shapes the confirmation content also sends

40040 envelopes with no ownerId and bodies other than four bytes:

    elementId 20000, no owner, 2 bytes   0000   then   0100
    elementId 1,     no owner, 4 bytes   00000000        after a syncCommand{data:0}
    no elementId,    no owner, 4 bytes   00000000  then  01000000

The pair's receive `0x006d6490` drops the two-byte ones (`cmp x2,#4`); they are the shared value
([The phase is the element's field](#the-phase-is-the-elements-field)).

## The League Card

After the trade each console asks whether to keep the partner's League Card, the TrainerCard at 0x924
of its snapshot ([protocol](swsh_protocol.md#the-party-payload-on-protocol-0x84)); the answer sends
nothing.

Oui files it unchanged in save block `0x28e707f5`: 300 slots of 0x1d0 from `album+0x230`, free while
`+0x1c8` is non-zero (`0x013fbab0` fills the first free one; `0x013fbc00` returns 1 when all are used).

`0x013fbc40(album, card)` skips the question when a used slot matches the card's u32 at 0x1C and eight
bytes at 0x1A8. 0x1C is PKHeX `TrainerCard8.TrainerID`, `(SID << 16 | TID) mod 10**6`; 0x1A8 is
`TimestampPrinted`, a Unix time. Against an emulated Shield, a changed trainer id or a changed byte at
0x1A8 asks again and files a second slot; a changed Pokédex count or name does not.
`pokeldn.swsh.league_card` maps a u32; `trade_payload.rewrite` sets the trainer id.

A retail Sword draws the date received, the logo of `game` (0x24), the three ASCII bytes at 0x39, a
Rotom-Dex crown for `dex_complete` (0x30), and `count + 1` of seven star panes with
`count = card[0x177] + (card[0x1b6] != 0) + (card[0x1b7] != 0)`. The builder `0x0158eef0` fills 0x177
(`DesignLevel`: 4 with `FSYS_GAME_CLEAR`, else 3, 2, 1, 0 for badges > 6, > 3, > 0, 0), 0x1B1
(`FSYS_SEED_CHALLENGE`), 0x1B3 (`FSYS_INPUT_SHIRT_NUMBER`) and the stars 0x1B6, 0x1B7
(`FSYS_R1_GAME_CLEAR`, `FSYS_R2_GAME_CLEAR`) from the save; flag keys are FNV-1a 64 of the names
([protocol](swsh_protocol.md#the-player-profile)).

`0x0158f5e0` rejects a card (DesignLevel 5, language 6, GlossIndex 9), which is replaced by a default.
`bin/swsh_host.py --card-set FIELD=VALUE` edits the sent card (`pokeldn.swsh.league_card` fields); a
fresh `trainer_id` makes the console ask again.

## The offered record

The offer on 20030 is the snapshot's party slot `--offer-slot`, edited in place, so the shown party and
the offer agree; the identity rewrite runs first and `party_matches_trainer` holds.
`pokeldn.swsh.pokemon.build_from` rewrites the checksum, reshuffles under the new encryption constant,
and keeps every unnamed byte. A built Pikachu traded to a retail Sword and back keeps level, nature,
ability, gender, ball, held item, IVs and EVs, and passes PKHeX legality.

A French Sword 1.3.2 accepted a record its save already held (same PID and EC) in four trades.
Shield 1.3.2 has no duplicate check on the paths read: the PID and encryption constant getters reach no
box walk, and the box code reads only species and the egg flag. Brilliant Diamond's illegal flag at PK8
byte 0x52 is read by no accessor ([the BDSP trade page](bdsp_trade.md#duplicate-detection)).
`--fresh-pid` on
`bin/swsh_host.py` and `bin/swsh_connect.py` draws a new encryption constant and PID.

    --offer-slot 1 --offer-nickname POKELDN --offer-ivs 31,31,31,31,31,31

| flag | effect |
|---|---|
| `--offer-nickname`, `--offer-ot` | 26-byte UTF-16 fields, at most 12 characters; a nickname sets the nicknamed flag, else the species name is drawn |
| `--offer-species` | the species word alone; everything else stays the template's |
| `--offer-ability ID`, `--offer-moves A,B,C,D` | the two fields; PP and relearn moves stay |
| `--offer-level N` | the level byte at 0x148 |
| `--offer-experience N` | the experience word at 0x10 |
| `--offer-ivs` | the six IVs |
| `--offer-file FILE` | a `.pk8` in any of four shapes (stored or party, encrypted or PKHeX's decrypted export, told apart by the header checksum); OT name and ids moved to the snapshot's trainer |
| `--offer-file-as-is` | keeps the file's OT |
| `--save-offer FILE` | writes the built record before the radio is touched |

A French Sword 1.3.2 does not check ability or moves against species, takes the level from the
experience word (0x10) and rebuilds stats from IVs, EVs, nature and hyper-training (0x126), shows an OT
id as `(SID << 16 | TID) mod 1000000`, compares no OT ids with MyStatus, and shows a PID high half of
`low ^ TID ^ SID` as shiny. A species with no data (152) is stored with Pikachu's model, a black Poke
Ball icon and zero base stats.

Unresolved: what other absent species draw, and whether the name is the name field or a failed lookup.

## The command line of a completed trade

`swsh_connect.py --preset trade` carries the flags a trade needs; a flag given after it overrides the
preset. With the console searching for a local Link Trade (Y-Comm, Link Trade, local, A on both
messages):

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/swsh_connect.py --keys PROD_KEYS \
        --preset trade --save-offered offered.pk8 --capture trade.jsonl

The snapshot sent back is the console's own from the same session (`--send-snapshot live`, the
preset's default): the three 0x84 fragments are reassembled, the trainer name, TID and SID are rewritten
to `--snapshot-name/-tid/-sid`, and it goes out once the console's has been reassembled.
`--send-snapshot FILE` sends a saved 3456-byte payload instead (`--preset capture`, then
`tools/switch/swsh_snapshot.py`, writes one).

`--offer-file FILE` puts a `.pk8` in the offered party slot. Repeated, it queues one record per trade
on the session; the last serves every later trade, under a new PID with `--fresh-pid`, and trade N
writes `--save-offered` with `-N`. A trade the console has offered and whose ladder has not finished
holds the session up to `--grace` seconds (300) past `--hold`. A stored-format record with no party
stats trades; the console computes the level from the experience.

## The penalty, and ending a run cleanly

A trade timing out with the link alive is a failed trade and locks the console out of trading
(`msg_ui_live_comm_app_alert_00`, line 331 of `/bin/message/French/common/live_comm.dat`); the lock's
length is unread. Cutting the link 15 s after `04000400`, during the save, shows the communication
error `2-ALZAA-0016`, takes no trade lock and starts a new local search at once.

`bin/swsh_connect.py --abort-on-stall SECONDS` drops the link once the ladder has started and SECONDS
pass with no new body. It stands down at phase 4, the silent teardown rung (`stall_abort()`,
`final_phase_seen`, `LADDER_FINAL_PHASE`), so the link is never cut during the save.

## Verifying a completed trade

A received Pokemon carries `CurrentHandler` 1 at 0xC4 and the receiver's name in `HandlingTrainerName`
at 0xA8 over the sender's original trainer. `--offer-echo` hands the console's own record back, so only
a different species proves a transfer.
