---
title: The Link Trade
parent: Sword and Shield
nav_order: 3
---

# Trading with a retail Sword and Shield

A Sword and Shield Link Trade from the snapshot exchange to the save. Framing, content registration
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

The hosting console does not ack a joiner's snapshot sent on port 0; the joiner's goes on port 1.
Until its 0x84 is answered the console sends nothing else and retransmits it indefinitely.
`pokeldn/ldn/broadcast4.py` implements all four kinds.

What follows the save is under [Hosting a trade](#hosting-a-trade) and
[Host migration](#host-migration).

## The trade RPC

The ping, block messages and the offer use port 0, the 40030 pair port 1; an answer on the wrong port
is not read.

    id 40030 = 40000 + 30
      1  offset      30
      2  base        10000, and 20000 in the other member
      3  station id  the sender's, equal to the host_constant of the seat record
      4  clock       a counter advancing between messages
      5  bytes(4)    00000000 for the 10000 member, 000018fc for the 20000 one

`000018fc` is the sentinel `0xfc18` ([the step body](#the-step-body)). The console's messages
rebuild byte for byte from the parsed fields (`pokeldn/swsh/trade.py`). `3e4e000012020801` is 20030
carrying `imReady{isReady:true}`. A joining client sends it; the console, as host, then shows the
offered Pokemon for confirmation. A hosting console has not been seen sending it.

- Send each answer once (`--answer-once`); re-deriving answers on a timer resends the offer.
- Readers must not raise: a mesh message on a reliable window (`44 00 01`,
  [host migration](#host-migration)) is not a trade message, and a reader that raises ends the
  receive task and the trade (`la communication avec l'autre joueur a été interrompue`). Readers in
  `trade.py` return `None`.

## Host migration

A hosting Sword that leaves the session requests host migration on protocol 0x18 port 1
(`nn::pia::mesh::LeaveWithHostMigrationJob`):

    0f 00 00 03 00 01 00 01   44 00 01
    ^ version 4's reliable header, sequence 1     ^ the mesh message

`44` is MIGRATION_START, `[0x44, host index 0, new host index 1]`: the console names the client next
host (`nn::pia::mesh::LeaveWithHostMigrationJob`). The named client must broadcast
`MIGRATION_FINISH` on the reliable window of mesh port 1
([The Pia layer](pia.md#host-migration)).

With `--answer-migration --update-mesh`, the client sends the finish and publishes mesh updates
under its new host index. Retaining a session after the handover is unverified.

A hosting retail Sword sends MIGRATION_START once, in two situations:

| when | condition |
|---|---|
| 0.8 s after its box command 3 | after a completed trade |
| a few seconds after the player accepted, before the console tears down with `2-ALZAA-0016` | a trade that failed before the ladder, the joiner sending no confirmation command |

`bin/swsh_host.py --migrate` ends its own hosted trade with box command 3 and MIGRATION_START; an
emulated Shield joiner then shows the interrupted-communication message after its save. By default
the host keeps the session.

## Hosting a trade

`bin/swsh_host.py` hosts and `pokeldn/swsh/host_trade.py` leads as a hosting Sword does. A retail
French Sword 1.3.2 and an emulated Shield 1.3.2 each join it and trade. The details below are read
from a trade between two emulated Shields 1.3.2.

The host builds a station advertisement with a fresh network id, device id and account uid. On 0x84
it acknowledges the joiner's three snapshot fragments, rewrites that live snapshot with its trainer
identity and the `--offer-file` PK8, then sends the result on port 0. The host writes the console's
offered PK8 to `--received`. `--advert FILE` and `--snapshot FILE` keep the saved-record path
available for comparison.

The station handshake, host side:

    joiner -> host   connection request, [1] a random byte per request
    host   -> joiner ack (05 000000 and the request's trailing id)
    host   -> joiner its own request, the joiner's [1] at [0x10]
    joiner -> host   ack, then its connection response
    host   -> joiner ack, then its response

Unacked, the joiner repeats its request and never answers the host's; a mismatched [0x10] is
ignored. After the mesh join the joiner sends Sync Clock (0x1C) every two seconds and one Clone
Clock (0x77); the host answers with the request's tick and the mesh clock in ms, and with 01,
request bytes 1 to 9 and the clone clock in ms.

The application layer, after the [ping handshake](swsh_session.md) both ways:

    0x84  each side's snapshot, the joiner's on port 1 and the host's on port 0; `host_trade.py`
          builds its own from the joiner's and sends it second, a retail host sends first
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
during it. A retail Sword joining `bin/swsh_host.py` started the animation 1.2 s after that
syncCommand and gave the player control at about 24 s. It sent no application message until the
player backed out of the box (box command 3).

## Trades in a row on one session

A session carries one trade after another. Trade state 9 sends event 7 (success) or 8 (failure)
and writes state 0 at `0x010ca360`, and the player is back in the box. Content 30 and ping 110 live
for the session (built once by the session setup `0x010c9280`); contents 50 and 40 and their pings
are rebuilt for every trade:

| object | lifetime | code |
|---|---|---|
| content 30, ping 110 | the session | `0x010c9280` -> `0x010cca10` |
| content 50, ping 130 | one trade | trade state 1 -> `0x010d5440` -> init `0x010d4d90` (new content, old one released), element minted at phase 0 `0x010d53fc`; torn down in state 3 by `0x010d54b0` |
| content 40, ping 120 | one trade | state 6 -> `0x010dabc0` -> init `0x010da470`; released in state 8 by `0x010dac90` |
| a content's SyncPing | its element | the mint `0x006d44e0` builds a new SyncPing with id offset + 0x50 (`0x006d46d0`), destroying the previous one (`0x006cd940`) |

A SyncPing that reached synced is never reset in place, so a ping 130 sent while a console has no
content 50 reaches no holder.

The box screen's step machine (`0x00aa5160`, table `0x2059218`) reads the partner's box-command flags
set by the listener `0x00c8d900`. In step 3, on the partner's flag 1 (its offer), it clears flags 1
and 4 together (`0x00aa5688..0x00aa569c`); step 7 waits for flag 4 (`0x00aa5628`), and only step 10
issues action 6, which starts trade state 1. A box command 4 sent in the same burst as the offer is
therefore erased, and the console waits in step 7 with "En attente d'une réponse". The partner's 4
must arrive after the console has processed its offer: `pokeldn.swsh.host_trade` sends its 4 only
after the joiner's 4, and the joiner launcher sends its 4 in answer to the host's.

Step 7 also ends on the player pressing B; no timer ends it. The step machine's ui is the View_Model
at `[this+0x80]` (`0x00aa4e78`, vtable `0x25376d8`). Its input handler `0x00aab0b0` (slot 16, called
from the UI dispatcher at `0x00efad28`) sets `ui+0x5cc = 1` when `ui+0x5d0` is armed and the
pressed-this-frame mask carries bit 49, which the remap table `0x02062928` produces from B alone.
Steps 2 and 6 arm it after the offer and the acceptance (`0x00aa5434`); every tick clears it
(`0x00aa5608`). In step 7 a press clears the partner's flags, sends box command 5 (the acceptance
withdrawn) and leaves the sequence (`0x00aa57d0`); in step 3 it sends box command 2.

Every later trade repeats the trade's own part: both offers and box command 1, the two box command
4s in that order, ping 130 (the joiner pings first), a new content 50 at phase 0, ping 120, a new
content 40 from phase 0 to 4. No 0x84 snapshot, ping 97 or 110, box command 3 or content 30 publish
comes between trades. `bin/swsh_host.py` and `bin/swsh_connect.py` with a repeated `--offer-file`
trade one queued record per trade on one session with a retail Sword joiner and host respectively;
the host closes when the console leaves.

`bin/swsh_connect.py` with a repeated `--offer-file` takes the console's offer after a finished
ladder (phase 4 on 40040) as the next trade. It answers that offer with its next record, so the
console's box sequence is already in step 3 holding its own offer, and clears its per-trade state:
the 40050 and 40040 pairs and bodies answered, the confirmation command queue, the selection-offer
latch. The 40030 pair and the ping answers carry over. `bin/swsh_host.py --accept-first --lead
SECONDS` plays a console host's player (accepts first, offers its next queued record from the box
after a trade), and the two launchers trade two records each way on one session on simulated boards
(`tests/test_esp32.py`).

When a retail joiner's player presses B in the box, the console sends box commands 2 and 3 and mesh
`0401` and deauthenticates with no error; its next search can join the same hosted network (same
network id). A searching console joins any network that passes the
[matching rules](swsh_session.md#how-a-searching-sword-finds-a-partner).

## The box state machine

Content 30 carries everything from the trade screen to the offer. `onBoxSyncStateCommand`
`0x010ce180`, slot 1 of the 0x50-byte wrapper at `session+0x120` (vtable group `0x2625808`):

1. ignore its own echo (`sender == [[0x2616a30]]+0xf0`);
2. `if ((msg->data - 1) > 5) return`: 0, 7 and above are dropped silently;
3. jump table `0x2067bec`: wire command *N* notifies every listener with event *N*.

Field 1, `boxSendPokemon`, goes to slot 0 `0x010ce080` as event 0. The dispatcher takes 0..6; the
sender emits 1..5.

The listener `0x00c8d900` sets `[owner + 0x218 + code] = 1`; code 2 first clears code 1's flag
(`+0x219`), code 5 code 4's (`+0x21c`). 1 offers, 2 withdraws the offer; 4 confirms, 5 withdraws a
4. A hosting console whose player is on the confirmation screen began leaving four seconds after
a joiner sent command 1 then 2.

The sender `0x010cda70(content, command)` sits behind wrappers `0x010cde90` .. `0x010cded0`
(commands 1 to 5), driven by the scene's jump table `0x00a96d10` on its action `+0x78`:

    action 1  ->  command 3
    action 2  ->  the Pokemon (0x010ca430), then command 1
    action 3  ->  command 2
    action 4  ->  command 5
    action 5  ->  command 4
    action 6  ->  0x010ca640, which stores its Pokemon and sets the trade state to 1

Two silent gates guard the send:

    [content+0x48] a pending command; a different one arriving sets the error byte [content+0x4d]
                   and sends nothing
    [content+0x4c] channel ready, set by 0x010ce040 on result 0; while clear the command waits in
                   +0x48 and never goes out

Command 3 is an opener. The per-frame update `0x010c9bb0` runs, before its state switch:

    if ([session+0x418]) { if (![session+0x419]) send command 3; [session+0x418] = 0; }

The setup `0x010c9280` sets `+0x418 = 1`, `+0x419 = 0x00dceea0() & 1` (from the player list):
exactly one side sends command 3. `--box-open` sends box commands at the 0x84 ack.

## The trade state machine

`[session+0x140]`, range 1..10, table `0x2067b68`:

    1  0x010c9c78  -> 0x010ca0a0: start content 50 and send its Pokemon; true -> 2, false -> 9
    2  wait        5  wait        7  wait
    3  0x010c9f60  the Pokemon exchange (0x010d54b0 on content 50), then 4, or 9 on error
    4  0x010c9c9c  0x01109320 decides; false -> 6
    6  0x010c9f84  -> 0x010ca1ac: install four delegates and start content 40
    8  0x010c9fa8  0x010dac90(content40, session+0x170, session+0x210): unhook from
                   [content+0x20]+0x60, [content+0x28]+0x60, release 0x010daac0; -> 9
    9  0x010c9ef4  terminal: [+0x144] set means failure; listeners get event 8
    10 0x010ca838

The box callback `0x010ca800` drops events unless the state is 0. State 2 ends in the delegate
`0x010cc380` (`session+0x2e0`): partner's Pokemon to `session+0x70`, a 0x60-byte record
(`0x010f5cc0`), state 3. Aborts start in state 1: when content 50's init `0x010d4d90` (`mov w2,
#0x32`) fails, its send `0x010d5440` does nothing and the caller sets `[session+0x144] = 1`, state 9:
the interrupted-communication message.

## The confirmation ladder

Content 40 is a barrier, one rung per command.

### The phase-to-state map

The state is `delegate+0x5c`, stored only by the init (0), four sites in the machine `0x010dae70`,
and `0x010dbf40`. The machine dispatches `state - 1` into the 14-entry table `0x2067ed0`; states 2,
4, 7, 9 (where sends leave it) take the default `0x010db38c`, the epilogue, and leave only through
`0x010dbf40`, which ignores a u16 above 4 and otherwise indexes the table `0x2067f4c`:

    phase 0  -> state 1              -> send(0), announcing 1     0x010db308
    phase 1  -> state 3              -> send(1), announcing 2     0x010db0b0
    phase 2  -> state 5 -> 6 or 8    -> send(2), announcing 3     0x010db0dc / 0x010db104
    phase 3  -> state 10 or 11 -> 12 -> send(3), announcing 4     0x010db16c
    phase 4  -> state 13 -> 14       -> 0x010db970 tears down, content+0x84 = 0xfc18; no send

`[delegate+0x58]` (`0x110e620(...) & 1`) is the role: state 7 sends 2 at once, state 9 after the
countdown `[delegate+0x60]`, an xorshift draw of 2..302.

Vtable group `0x257fe90`: primary `0x257fea0` (slot 0 the SyncCommand receive `0x010dbc90`, slot 3
`0x010dbf40`), offset-to-top −8 at `0x257fec8`, secondary `0x257fed8` whose slot 0 `0x010dbfd0` is
the same code on `+0x50`/`+0x54` (table `0x02067f60`, offsets `0x70 0x38 0x40 0x48 0x6c`), slot 4
`0x010dc070` tail-calls `0x010f8e30`, the rest `ret`. The init installs both:

    0x010da6bc   add x9, x19, #8       ->  [content+0x2c0] = delegate + 8     the second interface
    0x010da6d0   str x19, [x8, #0x168] ->  the 10040 holder's listener        the first

### The pump

`0x010db3e0`, run by content 40's tick before the machine, is a 17-state machine on
`[content+0x80]` with a shared tail:

    w1 = [content+0x17c]                    the content's PHASE
    if (w1 != [content+0x84] && w1 != [content+0x86])                     0x010db758..0x010db778
        { 0x010de310(content, w1); B->slot7(w1); }                        slot 7 is a ret
    w1 = [content+0x17c]
    if (w1 != [content+0x84] && w1 == [content+0x86])                     0x010db794..0x010db7b4
        { 0x010de310(content, w1); B->slot0(w1); }   <- the state setter
    0x010ddf40(content)                     the queued jobs                0x010db7d4
    0x006d4b80(content+0xd0)                the element update, last       0x010db7e8

`B` is `[content+0x2c0]` (`delegate+8`). The state switch runs first; state 0 (`0x010db740`) skips
the tail, state 16 (`0x010db730`) returns early when `0x006d4b30` is false. A phase neither
committed nor announced is committed silently (flags and jobs cleared, pump state 2).

| field | meaning | written by |
|---|---|---|
| `+0x84` | the committed phase | `0x010de310`, which also drops the pending body and empties the job queue `content+0x310` (`0x010de348..0x010de3a0`); called only from the tail (`0x010db778`, `0x010db7b4`) and state 14 (`0x010db6ac`), gated on phase != `+0x84` |
| `+0x86` | the phase announced with the last command | only `0x010dbab0`, `data + 1` at all five send sites |
| `+0x17c` | the phase, `element+0xac` | constructor `0x006d3ff8`, mint `0x006d4500`, adoption `0x006d4ccc` |

The ladder climbs when the phase reaches `+0x86`. The constructor sets `+0x84 = 0xfc18`
(`0x010dc228`, `0x010dc260`), `+0x86 = 0` (`0x010dc25c`); the registrar sets `+0x84` to 0
(`0x010da810`, `0x010daa78`), mints the element with 0 (`0x010daa7c`) and leaves `[content+0x80] =
1`; pump state 1 then calls the state setter outside the gate: command 0, announcing 1.

Pump states (table `0x2067f08`; `[+0x1c0]` is the element's `+0xf0` channel, `[+0x2a0]` the command
flags of [The command](#the-command)):

    1   0x010db418  element ready (0x006d4e70) -> 2; delegate slot 1, then slot 0 with the phase
    2   0x010db47c  a pending body at +0x88 -> 3
    3   0x010db48c  0x006d4f10 (all ready, every pair's low half == phase): send the body
                    (0x010de080) to station [[0x2616a30]+0xf8] -> 4
    4   0x010db4dc  0x006d3690([+0x1c0], [+0x86]) publishes the high half, must return 1;
                    then 0x018407f0 ? 8 : 7                                      cinc 0x010db514
    5   0x010db51c  the same through [+0x2b8] (0x008b7300) with [+0xa8] -> 6; dead in content 40
    8   0x010db594  0x006a2840([+0x2a0]): every station has sent a command -> 9
    9   0x010db5b4  0x006d4fb0 == 0: no resend byte set -> 10
    10  0x010db5d4  0x006d4da0 && 0x006d3060([+0x1c0], [+0x86]) (every high half == announced)
                    && 0x006d4f50; then 0x006d33b0 writes shared value = announced -> 7
    11  0x010db62c  0x006a2760([+0x2a0]) clears every flag; [+0x374] ? 12 : 2
    6, 7, 12        the default, the shared tail at 0x010db758
    14  0x010db68c  the gated commit (13, 15, 16 unread)

States 8 to 10 run only on the master (`0x018407f0`); others go 4 to 7 and follow the shared value.
Nothing in `0x010d9000..0x010df000` stores 5 to `[content+0x80]` or non-zero to `[content+0xa8]`
(clears only, `0x010db9ec`, `0x010dc530`, `0x010de3a4`). Other writers of `[content+0x80]`:

| site | function | state |
|---|---|---|
| `0x010dc234` | constructor | 0 |
| `0x010daa9c` | registrar | 1 |
| `0x010dbc70` | `0x010dbab0`, the command send (requires 2; writes `+0x86`) | 3 |
| `0x010de3c4` | `0x010de310`, the commit; clears every flag at `0x010de344` | 2 |
| `0x010dc7a0` | `0x010dc720` (slot `0x257ff70`), a station leaving: with `[+0x374]` tell delegate slot 4, else remove it from the element (`0x006d50e0`) and flags (`0x006a2140`) | 11 |
| `0x010dc6f4` | `0x010dc6c0` (slot `0x257ff68`), requires `[+0x374]` and `0x006a2a80([+0x2a0])` | 13 |
| `0x010dccec` | slot `0x257ff90` | 2 |
| `0x010dcee8` | `0x010dce70`, CancelAccepted (`x19 = content+0x68`), unless 16 | 2 |
| `0x010db998` | `0x010db970`, teardown | 16 |

Content 40's registrar stores `w2 = 1` (`0x010da6a8`) at `[+0x374]` (`0x010da800`): a station
leaving goes 11, 12 and ends the ladder.

### The phase is the element's field

Nothing in `0x010c0000..0x010e0000` stores to `content+0x17c`. The registrar builds the 40040
element at `content+0xd0` (`0x010daa4c`), adds the sub-element (`0x006d4ff0`) and mints it with
`0x006d44e0(element, w20)`, which opens `str wzr,[x0,#0xa8]; strh w1,[x0,#0xac]`: the phase is
`element+0xac` (`0xd0 + 0xac = 0x17c`), starting at the init's `wzr`.

It advances only in `0x006d4ca0`:

    w0  = 0x006d3260([element+0xf0])        the shared value; 0xfc18 when none
    if (w0 == [element+0xac]) done
    if (0x006d3980([element+0xf0], w0)) {   publish it as its own; on success
        [element+0xac] = w0                 the phase moves
        [element+0xa0]->vtable[0]()         and the content is told
    }

This is the tail of the element update `0x006d4b80` (every sync pump calls it last; content 40 at
`0x010db7e8`), run when `0x006ce5a0([element+0xb0])` returns 1. Before all stations are ready:

    if (!0x006d2e20(shared) && !0x006da180(hash channel)) {
        if (0x018407f0([[0x2616a30]]))  0x006d33b0(shared, [element+0xac])
        0x006da3d0(hash channel, element+0xa8); 0x006d3980(shared, [element+0xac])
        return
    }

`0x018407f0` is true on the console hosting Pia's mesh
([session](swsh_session.md#the-pia-session-object); backend call `+0xe0` on
`[x0 + 0x168 + [x0+0x162]*8]`). Only it seeds the shared value, the `+0xf0` channel's 16-bit
sub-element ([Sub-element kinds](swsh_protocol.md#sub-element-kinds)); every station adopts it:

    0x006d3260  read            ready [sub+0x61] ? [sub+0x88] : 0xfc18
    0x006d33b0  write(v)        0x006d3570 when not ready or body != v
    0x006d3570  publish         body [sub+0x88] = v; clock from 0x01766740 (-1: error 0x2c27);
                                [sub+0x80]->vtable[0] with (sub+0x88, 2, clock, [sub+0x62], [sub+0x68])
                                when [sub+0x80]->vtable[1]() or [sub+0x70] allows, resend byte
                                [sub+0x60] = !sent; else [sub+0x60] = 1
    0x006d2e20  all ready       the shared value and every pair
    0x006d2c20  all low == v    all ready, every pair's [sub+0x88] == v
    0x006d3060  all high == v   all ready, every pair's [sub+0x8a] == v

A write leaves the ready byte alone (only the receive `0x006d6a08` stores `+0x60`; the write is
`0x006d35b8 strh w8,[x20,#0x88]!`), so a read returns `0xfc18` until a message arrives; on the master
that message is its own. The publish reaches the element's slot 0 (`0x006d5730`), which queues the
body per station. The 149 client messages on 40040 in one completed trade all carried four-byte
bodies; the content's other shapes are [below](#shapes-the-confirmation-content-also-sends).

### The step body

The four-byte body on content 40's elementId 20000, low half the phase, high half the last
announced:

    0x006d3980(channel, v)   body = <u16 v><u16 [sub+0x8a]>    low; from the element update
    0x006d3690(channel, v)   body = <u16 [sub+0x88]><u16 v>    high; from pump state 4, [content+0x86]

Both find the own id (`[[0x2616a30]]+0xf0`) in the channel's `{ownerId, entry}` table, take
`[entry+0x60] - 0x50`, and call `0x006d3860` (`0x010dbe20` one layer down); `[content+0x1c0]` is
`[element+0xf0]`. An observed ladder:

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
sender `0x006b5850` cannot resolve (`0xfd`), takes the int32 at `[arg1+0x14]`, picks the subscriber
at `+0x38` by station index, passes the int32 to the relay `0x010dbe20` and the subscriber's `+0x18`,
then always:

    0x010dbdf8  ldr  x8, [x20, #0x18]
    0x010dbdfc  ldr  x0, [x8, #0x2a0]
    0x010dbe00  mov  w2, #1          <- a constant
    0x010dbe04  mov  x1, x19         <- keyed by the sender
    0x010dbe08  bl   #0x6a24a0

The value only reaches the relay (an elementId-1 body `00000000` echoes `syncCommand{data:0}`); the
state moves only through `0x010dbf40`, called by the pump with its own phase. Any command advances a
rung. `[content+0x2a0]` is a per-station flag object (`0x006a24a0` has 44 call sites):

    0x006a24a0(obj, id, flag)   map[id] = flag & 1; map at obj+0x1c0, find-or-insert
                                (0x006a24d0 hashes by udiv/msub on the bucket count at +0x10)
    0x006a2840(obj)             1 when every station listed at obj+0x100 (count +0x108) is set
    0x006a2760(obj)             clear(): frees nodes, zeroes buckets and the size at +0x270
    0x006a2480(obj)             obj+0xc0, the station list the registrar walks

State 8 waits on `0x006a2840`; the commit and state 11 clear the map. The flag is set in the
network update's drain, outside the pump: `0x006a9a20` calls Pia's dispatch `0x006a8380`
(`0x006a9a54`), then the drain `0x006db3b0` (`0x006a9a90`,
[routing](swsh_protocol.md#the-routing-path)). Of its callers `0x00ef4a9c`, `0x01109250`,
`0x01109308`, the frame `0x00f1df30` runs two, around the game update:

    0x00f1df30  bl 0x01109240     network update: 0x01109250 bl 0x006a9a20, the drain
                bl 0x00fa09a0
                bl 0x00f1cc60     the game update
                bl 0x00793ec0
                bl 0x011092f0     0x01109304 bl 0x01111db0, 0x01109308 bl 0x006a9a20, the drain again

Content 40's command tick `0x010dae70` runs in the trade scene task: `0x00c8c6b0` calls
`0x010c9bb0` at `0x00c8c6d8`, which calls the tick at `0x010c9c34`. The task dispatcher reaches
it through `0x00f19770` and `0x00f19080`. Emulator traces place this tick before
`0x01109250`, then `0x00f1cc60`, then `0x01109308`. A command drained there can be consumed by
the following scene tick.

RequestCancel and RequestCancelAll also read the map ([below](#the-cancel-and-proceed-messages)).

A rung takes one command reaching the master after the previous commit. In rung 0 any command
counts, the one on the cue `00000100` included; later, the command on the cue (`01000200`,
`02000300`, `03000400`) lands before the commit and is cleared, and the one on the caught-up body
(`01000100`, `02000200`, `03000300`) counts:

| commands, one per new body | last body |
|---|---|
| 1, on `00000100` | `01000200`: rung 0 |
| 4, `000018fc` to `01000200` | `02000300`: rungs 0 and 1 |
| 9, `000018fc` to `04000400` | `04000400`: the trade |

`--confirm-commands 0,1,2,3,0,1,2,3,0,1,2,3` pops one per new body, `000018fc` included; the queue
must not run dry. `answer_rpc` echoes the body and moves neither half; `--confirm-phase N` writes the
low half.

### The cancel and proceed messages

30040, the `SequenceDataHolder` ([the protocol page](swsh_protocol.md#the-30000-holder)), is stored
at `[content+0x2b8]` (`0x010da9b8`) with listener `content+0x68` (`0x010da9b4`, `0x010da9bc`;
vtable `0x02580030`, `0x010dc238`):

| case | message | handler |
|---|---|---|
| 1 | CancelAccepted | `0x010dce70` |
| 2 | RequestCancel | `0x010dc920`, through the thunk `0x010dcf20` |
| 3 | RequestCancelAll | `0x010dcaa0`, through `0x010dcf30` |
| 4 | RequestForcedProceed | `0x010dc7b0`, through `0x010dcf40` |

Each acts only when `currentSeqNo` equals the committed phase `(s16)[content+0x84]`:

- RequestCancel, when not every station is flagged (`0x006a2840`, `0x010dc954`): job `0x010dd0c0`
  sends `CancelAccepted{currentSeqNo: [+0x84], isForced: 0}` to the sender via `[content+0x2b8]`
  (`0x008b7230`) and clears its flag (`0x010dd114`).
- RequestCancelAll, same guards: job `0x010dd190` per listed station (`0x010dcaf4..0x010dcb1c`)
  sends `CancelAccepted{[+0x84], isForced: 1}`, then clears every flag (`0x010dd208`).
- CancelAccepted: with `isForced`, steps `[content+0x370]` mod 255 into `0x006db470`; pump state 2
  unless 16 (`0x010dcee8`); delegate slot 6 (`ret`). States 2 to 4 re-run; the phase stays.
- RequestForcedProceed: job `0x010dd040` `{content, u16 targetSeqNo, sender index}` runs at once
  (`0x010dc8a8`), queued on false (`0x010dc8bc`). After `0x006d4da0(content+0xd0)` it calls
  `0x006d33b0([content+0x1c0], targetSeqNo)`, state 10's write without states 8 and 9, the
  `0x006d3060`/`0x006d4f50` tests or the master test; the sender index is unread.

`RequestForcedProceed` advances the shared phase without a `syncCommand` (an emulated Shield). It
does not replace the confirmation commands: a ladder whose later commands are these requests stops
at "Communicating" before the save.

The job queue `content+0x310` (entries `+0x350`, count `+0x358`) runs in `0x010ddf40` from the pump
(`0x010db7d4`); a job returning true is removed. The commit empties it.

### Shapes the confirmation content also sends

40040 envelopes with no ownerId and bodies other than four bytes:

    elementId 20000, no owner, 2 bytes   0000   then   0100
    elementId 1,     no owner, 4 bytes   00000000        after a syncCommand{data:0}
    no elementId,    no owner, 4 bytes   00000000  then  01000000

The pair's receive `0x006d6490` drops the two-byte ones (`cmp x2,#4`); they are the shared value
([The phase is the element's field](#the-phase-is-the-elements-field)).

## The League Card

After the trade each console asks whether to keep the partner's League Card, the TrainerCard at
0x924 of its snapshot ([protocol](swsh_protocol.md#the-party-payload-on-protocol-0x84)); the answer
sends nothing.

Oui files it unchanged in save block `0x28e707f5`: 300 slots of 0x1d0 from `album+0x230`, loaded as
one `0x21fc0`-byte block (`0x013fad4c`), free while `+0x1c8` is non-zero. `0x013fbab0` fills the
first free slot: 0x1c4 bytes, `+0x1c8`/`+0x1c9` zeroed, year `+0x1ca` (`tm_year + 0x76c`), month + 1
`+0x1cc`, day `+0x1cd`, `+0x1ce`/`+0x1cf` from arguments (`00 00 ea 07 09 1a 02 00`: year 0x07ea, month 9, day 0x1a).
`0x013fbc00` returns 1 when all 300 are used.

`0x013fbc40(album, card)` (callers `0x00aa6414`, `0x0106612c`, `0x015253f0`, `0x01543868`) skips the
question when a used slot matches the card's u32 at 0x1C (`0x013fbc4c`) and eight bytes at 0x1A8
(`0x013fbc5c`, one 64-bit compare); emptying that slot brings the question back. 0x1C is PKHeX
`TrainerCard8.TrainerID`, `(SID << 16 | TID) mod 10**6` (848973 for 56909/48474); 0x1A8 is
`TimestampPrinted`, a Unix time (`9bc62a5e00000000`, 2020-01-24, in a retail card); the game compares
all eight bytes, `pokeldn.swsh.league_card` maps a u32. `trade_payload.rewrite` sets the trainer id.
Against an emulated Shield holding the host's card:

| the host's card | asked |
|---|---|
| unchanged | no |
| trainer id 848973 -> 111111 | yes; filed in a new slot beside the first |
| Pokédex count 400 -> 401 | no |
| the name, one letter added | no |
| timestamp_printed, only byte 0x1A8 changed | yes |

A retail Sword draws the date received, the logo of `game` (0x24, 0 Sword) top left, the three
ASCII bytes at 0x39 bottom left, a Rotom-Dex crown for `dex_complete` (0x30), and stars. The view
`0x01592e70` copies the card to `view+0x3c0`; `0x015a52f0(view, count)` lights `count + 1` of seven
panes (`view+0x618..+0x648`; the validator caps count at 6):

    count = card[0x177] + (card[0x1b6] != 0) + (card[0x1b7] != 0)      0x015930bc..0x015930dc

It also passes `card[0x24]` to `0x015a5260` and `card[0x1b3] != 0` to `0x015a50d0`. The builder
`0x0158eef0` (callers `0x00c77830`, `0x014be578`, `0x0156167c`, `0x01561b0c`, `0x01568f4c`,
`0x015691bc`) fills from the save:

| byte | value | site |
|---|---|---|
| 0x177 | `DesignLevel`: 4 with `FSYS_GAME_CLEAR` (`0x7d0b1ced4dbe8a87`), else 3, 2, 1, 0 for badges > 6, > 3, > 0, 0 | `0x0158f084`, `0x0158f484..0x0158f4dc`, `0x0158f0c4` |
| 0x1B1 | `FSYS_SEED_CHALLENGE` (`0xbd07c2b80232e9b0`) | `0x0158f564..0x0158f5a0` |
| 0x1B3 | `FSYS_INPUT_SHIRT_NUMBER` (`0xe44b16771524b07e`) | `0x0158f0fc` |
| 0x1B6 | `FSYS_R1_GAME_CLEAR` (`0x8f1a133dff5c0ecf`), a star | `0x0158f11c` |
| 0x1B7 | `FSYS_R2_GAME_CLEAR` (`0xd450875d834cfc30`), a star | `0x0158f12c` |

Flag keys are FNV-1a 64 of the names ([protocol](swsh_protocol.md#the-player-profile)), read by
`0x01410f30`; the badge count is `0x01438fb0`, a popcount of `[status+0x60]`. `DesignLevel` is the
`capture_data.prmb` column (hash `0x3bc4598485d2a2ef`, string `0x01c2a2e9`) stored by
`0x0158ead4..0x0158eb30`; `GlossIndex` is 0x178.

`0x0158f5e0` returns 1 to reject a card, which is then replaced by a default. Under unicorn it
accepts the card pokeldn sends (0x177 = 4, 0x1B3 = 1, language 3) and 0x1B6 or 0x1B7 set; it rejects
DesignLevel 5, language 6, GlossIndex 9. `bin/swsh_host.py --card-set FIELD=VALUE` edits the sent card
(`pokeldn.swsh.league_card` fields); a fresh `trainer_id` makes the console ask again.

## The offered record

A built Pikachu traded to a retail Sword and back keeps every requested offer option. The returned
PK8 has a valid checksum and passes PKHeX legality; PID, original trainer ids, IVs and EVs match
the outgoing offer.

| requested field | returned record |
|---|---|
| level | 30 |
| nature and stat nature | Adamant, 3 |
| ability | Lightning Rod, 31 |
| gender | female, 1 |
| ball | Ultra Ball, 2 |
| held item | Light Ball, 236 |
| selected IVs | HP 31, Attack 0, Speed 31 |
| EVs | HP 252, Speed 4, every other stat 0 |

The offer on 20030 is the snapshot's party slot `--offer-slot`, edited in place, so the shown party
and the offer agree; the identity rewrite runs first and `party_matches_trainer` holds.
`pokeldn.swsh.pokemon.build_from` rewrites the checksum, reshuffles under the new encryption
constant, and keeps every unnamed byte (ribbons, memories, met data, handler records).

A French Sword 1.3.2 accepted a record its save already held (same PID and EC) in four trades and
traded it on. No duplicate check exists on the paths read in Shield 1.3.2: the PID getter
(`0x0076bc20`, block A + 0x14) is called only by the shiny tests; the encryption constant getter
(`0x0077ec90`) is read at 12 sites, none of which walks the boxes; the box code
(`obj+0x60 + box*0x2850 + slot*0x158`) reads only species and the egg flag; and no accessor touches
PK8 byte 0x52, where Brilliant Diamond keeps its illegal flag
([the BDSP trade page](bdsp_trade.md#duplicate-detection)). `bin/swsh_host.py --fresh-pid` and
`bin/swsh_connect.py --fresh-pid` draw a new encryption constant and PID; on Sword this is a
precaution.

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

What a French Sword 1.3.2 does with an edited record:

| record sent | result |
|---|---|
| template, nickname, IVs 31 | accepted; unnamed fields stay the template's |
| species 93 with Gengar's ability 130 and moves | drawn as Haunter, trade-evolved: ability and moves are not checked |
| species 25 | stats rebuilt from IVs, EVs, nature and hyper-training 0x126; stat bytes at 0x14A discarded |
| level byte 0x148 = 50, experience at level 100 | level 100: level comes from experience (0x10); the party tail is rebuilt |
| OT moved to 12345/54321 | ID shown 993401, `(SID << 16 \| TID) mod 1000000` |
| the receiver's own OT under a foreign MyStatus | accepted as the player's own catch: OT ids are not compared with MyStatus |
| PID high half = `low ^ TID ^ SID` | shiny |
| species 152 (absent) | stored: Pikachu's model, the name field, black Poke Ball icon, growth group 0 and zero base stats; only current HP (0x8A) and the handler block (0xA8, 0xC2, 0xC3, 0xC8, 0xCB-0xCC) change |

Unmeasured: what other absent species draw, and whether the name is the name field or a failed
lookup.

## The command line of a completed trade

`swsh_connect.py --preset trade` carries the flags a trade needs; a flag given after it overrides
the preset. Let the console search for a local Link Trade
(Y-Comm, Link Trade, local, A on both messages) and run:

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/swsh_connect.py --keys PROD_KEYS \
        --preset trade --save-offered offered.pk8 --capture trade.jsonl

The snapshot sent back is the console's own from the same session (`--send-snapshot live`, the
preset's default): the three 0x84 fragments are reassembled as they arrive, the trainer name, TID and
SID are rewritten to `--snapshot-name/-tid/-sid`, and it goes out once the console's has been
reassembled, so no earlier capture session is needed. `--send-snapshot FILE` sends a
saved 3456-byte payload instead (`--preset capture`, then `tools/switch/swsh_snapshot.py`, writes one).

`--offer-file FILE` puts a `.pk8` in the offered party slot, its OT moved to the snapshot's trainer.
Repeated, it queues one record per trade on the session; the last serves every later trade, under a
new PID with `--fresh-pid`, and trade N writes `--save-offered` with `-N`. A trade the console has
offered and whose ladder has not finished holds the session up to `--grace` seconds (300) past
`--hold`.
A stored-format record with no party stats trades; the console computes the level from the
experience.

## The penalty, and ending a run cleanly

A trade timing out with the link alive is a failed trade and locks the console out of trading
(`msg_ui_live_comm_app_alert_00`, line 331 of `/bin/message/French/common/live_comm.dat`). The text
names no duration and the label is absent from `main.bin`; the lock's length is unread. Cutting
the link 15 s after `04000400`, during the save, shows the communication error `2-ALZAA-0016`,
takes no trade lock and starts a new local search at once.

`bin/swsh_connect.py --abort-on-stall SECONDS` drops the link once the ladder has started and SECONDS
pass with no new body. It stands down at phase 4, the silent teardown rung (`stall_abort()`,
`final_phase_seen`, `LADDER_FINAL_PHASE`), so the link is never cut during the save.

## Verifying a completed trade

A received Pokemon carries `CurrentHandler` 1 at 0xC4 and the receiver's name in
`HandlingTrainerName` at 0xA8 over the sender's original trainer. `--offer-echo` hands the console's
own record back, so only a different species proves a transfer.
