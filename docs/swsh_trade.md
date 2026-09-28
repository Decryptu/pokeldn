---
title: The Link Trade
parent: Sword and Shield
nav_order: 3
---

# Trading with a retail Sword and Shield

A retail Sword has completed a trade with pokeldn: it accepted a Pokemon, gave one of its own, wrote
its save and returned the player to the overworld, with no error and no penalty.

This page covers the trade from the snapshot exchange to the save. The message framing, the content
registration and the PK8 format are on [The sync framework](swsh_protocol.md).

## The sequence

    1  the console broadcasts its 3456-byte snapshot on protocol 0x84, port 0
    2  the client acknowledges the fragments (0x21) and the transfer (0x19 / 0x28)
    3  the client sends its own snapshot on 0x84, PORT 1, and reports it complete
    4  the trade screen opens on the console
    5  the console sends the 40030 RPC pair on 0x7C PORT 1, several times a second
    6  the client answers the pair and sends `imReady` on the trade holder (20030)
    7  the console offers a Pokemon on 20030; the client offers one back on 10050
    8  the player accepts; the console sends MIGRATION_START on protocol 0x18 port 1
    9  the confirmation ladder runs on content 40
    10 the console writes its save

Transport rules for steps 1-3:

- The two directions do not share a Pia port. The console sends its snapshot on port 0 and
  acknowledges the peer's on port 1; a snapshot sent on port 0 is never acknowledged.
- A receiver that never answers 0x84 never sees the console's other message kinds. The console
  retransmits one snapshot indefinitely (19142 messages in one run; 13 once the fragments were
  acknowledged). `pokeldn/ldn/broadcast4.py` implements all four kinds.

## The trade RPC

When the trade screen opens the console sends message id 40030 as a pair, several times a second, on
0x7C port 1. The ping, the block messages and the Pokemon offer arrive on port 0. An answer sent on
port 0 goes to a window the console does not read there.

    id 40030 = 40000 + 30
      1  offset      30            - the same 30 the id is built from
      2  base        10000, and 20000 in the other member of the pair
      3  station id  THE SENDER'S, byte-identical to the host_constant our own seat record holds
      4  clock       a counter that advances between messages
      5  bytes(4)    00000000 for the 10000 member, 000018fc for the 20000 one

The base and the offset travel as separate fields and 20000 + 30 is assembled on the wire.
`0x006d44e0` opens with `strh w1, [x0, #0xac]`, overwriting the `0xfc18` its constructor put there;
`0xfc18` is the `000018fc` one member of the pair carries in field 5.

Field 3 is a station id; both of the console's own messages rebuild byte for byte from the parsed
fields. `pokeldn/swsh/trade.py`.

The Pokemon offer is 20030, `PokemonTradeDataHolder{pokemon{serializePokemonParam}}` holding a
344-byte party-form PK8. 40030 is the envelope that precedes it.

`3e4e000012020801` is message 20030 carrying `imReady{isReady:true}`. The console never sends those
bytes; published clients wait for them before offering. With them sent, the console displays the
offered Pokemon and asks the player to confirm.

Send each answer once. A sender on a timer that re-derives an answer to a message already answered
produced 859 copies of one Pokemon offer over 259 seconds where the console had asked once; the
window advances a sequence only once the last is acked, so those collapse to roughly forty delivered
duplicates. The game processed the offer while being flooded. `--answer-once` answers each payload
once.

Readers must not raise. At the confirmation prompt the console sends a three-byte message (a mesh
message, see [host migration](#host-migration)); a reader that raised on it killed the receive task,
transmission stopped mid-trade, and the player saw `la communication avec l'autre joueur a été
interrompue`. Every reader in `pokeldn/swsh/trade.py` returns `None` instead.

## Host migration

Once the player accepts, the console sends twelve bytes on protocol 0x18 port 1 and never speaks on
the application layer again:

    0f 00 00 03 00 01 00 01   44 00 01
    ^ version 4's reliable header, sequence 1     ^ the mesh message

`44` is the mesh protocol's MIGRATION_START, `[0x44, host index 0, new host index 1]`, matching the
join response's `stations=2 host_index=0 our_index=1`: the console names the client as the next host
of its mesh. The answer is `[0x48, our own station index]`, two bytes. Mesh protocol port 1 is the
reliable port, so the mesh message rides inside the reliable window. Both handlers are on
[The Pia layer](pia.md#host-migration).

The console sends it once and never retransmits; one transport ack satisfies it. Pia's RTTI names
the operation `nn::pia::mesh::LeaveWithHostMigrationJob`.

## Hosting a trade

`bin/swsh_host.py` hosts, and `pokeldn/swsh/host_trade.py` leads the trade as a hosting Sword does. A
French Sword 1.3.2 joined it over the ESP32 board, traded, received the offered Ectoplasma and saved;
an emulated Shield 1.3.2 did the same over the LAN. The session and handshake details below were read off a trade between two
emulated Shields and reproduced by the host.

The station handshake, host side:

    joiner -> host   connection request, [1] a byte it draws per request
    host   -> joiner ack of that request (05 000000 and the request's trailing id)
    host   -> joiner its own request, with the joiner's [1] copied into [0x10]
    joiner -> host   ack, then its connection response
    host   -> joiner ack, then the host's response

Left unacked, the joiner repeats its request and never answers the host's. A request whose [0x10]
does not match is ignored.

After the mesh join the joiner sends Sync Clock (0x1C) every two seconds and one Clone Clock (0x77);
the host answers both, the first with the request's tick and the mesh clock in milliseconds, the
second with 01, bytes 1 to 9 of the request and the clone clock in milliseconds. Both precede any
application data.

The application layer, as the emulated pair ran it:

    97   the host pings; the joiner answers and pings back; pingSynced both ways
    60000 result{} on 0x7C and imReady on 0x80, both ways
    0x84  the joiner's snapshot on port 1, then the host's on port 0 (a retail host sent first)
    110  the joiner pings first, once its trade screen is up; the host answers with its own ping
         and the reply. A host ping sent before that screen is acknowledged and dropped
    30   the host opens content 30; each side offers on 20030 and sends box command 1; each
         player's acceptance is box command 4
    130  the joiner pings first
    50   the host publishes its Pokemon as element 0 and relays the joiner's 10050 as element 1
    120  the host pings first
    40   the ladder, one rung per command: host commands as element 0, the joiner's 10040 as
         element 1, phases 0 to 4

After phase 4 the host keeps the session. An emulated joiner returns to the trade screen with a
League Card offer; the retail Sword sent box command 3 and left the network by deauthentication,
with its save written. A retail Sword leading a pokeldn joiner instead sent box command 3 and MIGRATION_START; a
host that migrates after the save leaves the joiner with an interrupted-communication error.

## The box state machine

Everything from the trade screen to the offer runs on content 30, the box exchange.

Commands are 1..6. `onBoxSyncStateCommand` is `0x010ce180`, vtable slot 1 of the 0x50-byte wrapper
at `session+0x120` (vtable group `0x2625808`):

1. `if (sender == our own station) return`: it ignores its own echo, `[[0x2616a30]]+0xf0`.
2. `w8 = msg->data`, then `if ((w8 - 1) > 5) return`. 0, 7, 8 and anything higher are dropped
   silently.
3. A six-entry jump table at `0x2067bec`, one case per command, each notifying every listener with
   the command value unchanged. Wire command *N* becomes event *N*.

Field 1 of the same holder, `boxSendPokemon`, goes to vtable slot 0, `0x010ce080`, and notifies with
event 0. The receive dispatcher takes 0..6; the sender emits 1..5; 0 is the Pokemon.

The commands come in toggle pairs. The listener `0x00c8d900` keeps one flag byte per event in an
array at `+0x218`, `[owner + 0x218 + code] = 1`, and before setting the new flag it clears another:

    code 2 clears the flag for code 1        (+0x219)
    code 5 clears the flag for code 4        (+0x21c)

1 offers and 2 withdraws the offer; 4 confirms and 5 withdraws the confirmation. Measured: 1 then 2
made the console begin leaving four seconds later (a cancelled offer); 4, 5 and 6 into the
post-accept window retracted the 4 about a second after it landed.

The sender is `0x010cda70(content, command)`, reached through five one-line wrappers `0x010cde90` ..
`0x010cded0`, commands 1 to 5 in address order. The scene drives them from a six-way jump table at
`0x00a96d10` keyed on its own action field `+0x78`:

    action 1  ->  command 3
    action 2  ->  the Pokemon (0x010ca430), then command 1
    action 3  ->  command 2
    action 4  ->  command 5
    action 5  ->  command 4
    action 6  ->  0x010ca640, which stores our Pokemon and sets the trade state to 1

Two gates sit in front of the send and both fail silently:

    [content+0x48] holds a pending command; a DIFFERENT one arriving sets the error byte
                   [content+0x4d] and sends nothing at all
    [content+0x4c] is the channel-ready bool, set by 0x010ce040 on a zero result code; while it is
                   clear the command is parked in +0x48 and never goes out

Command 3 is an opener. The session's per-frame update `0x010c9bb0` does this before it switches on
the trade state:

    if ([session+0x418]) { if (![session+0x419]) send command 3; [session+0x418] = 0; }

`+0x418` is set to 1 by the setup at `0x010c9280` and `+0x419` to `0x00dceea0() & 1`, which walks the
player list. Exactly one of the two sides emits command 3 on its first frame after the trade session
is built; a role bit decides which. `--box-open` sends box commands at the 0x84 snapshot ack, before
either side offers anything.

None of the four published clients names a command value; they encode the holder only.

## The trade state machine

`[session+0x140]`, table at `0x2067b68`, seven live entries and a range of 1..10:

    1  0x010c9c78  -> 0x010ca0a0: start content 50 and send our Pokemon. true -> 2, false -> 9
    2  wait        5  wait        7  wait
    3  0x010c9f60  the Pokemon exchange - 0x010d54b0 on content 50 - then state 4, or 9 on error
    4  0x010c9c9c  0x01109320 decides; false goes to state 6
    6  0x010c9f84  -> 0x010ca1ac: install four delegates and START CONTENT 40
    8  0x010c9fa8  content 40's teardown - 0x010dac90 - then state 9
    9  0x010c9ef4  terminal: [+0x144] set means failure, and the listeners are told event 8
    10 0x010ca838

`[session+0x140]` also gates the box callback: `0x010ca800` drops every event unless the state is 0,
so once an error is recorded the session stops listening.

State 2 is left by a delegate the state-1 branch installs at `session+0x2e0`, `0x010cc380`: it takes
the object it is handed, stores it at `session+0x70` (the partner's Pokemon), builds a 0x60-byte
record from it (`0x010f5cc0`) and writes `[session+0x140] = 3`. The partner's Pokemon arriving
through content 50's own receive event moves the console out of state 2.

State 8 is content 40's teardown. `0x010c9fa8` calls `0x010dac90(content40, session+0x170,
session+0x210)`, which walks the listener vectors at `[content+0x20]+0x60` and `[content+0x28]+0x60`,
removes those two, and tail-calls `0x010daac0`, the release. The state after it is 9.

State 1 is where an abort originates. `0x010ca0a0` calls `0x010d5440`, content 50's send, which opens
with `bl 0x010d4d90` and does nothing if that returns false. `0x010d4d90` is content 50's own init,
the twin of content 40's `0x010da470`; it registers with `mov w2, #0x32`. On false the caller takes
`[session+0x144] = 1` and state 9: error, listeners told event 8, the interrupted-communication
message.

## The confirmation ladder

Content 40 runs the last phase as a barrier: one rung per command received.

### The phase-to-state map

The machine's state is `delegate+0x5c`. Every store to that offset in the 30/40/50 band is the init
(0), four inside the machine `0x010dae70`, and `0x010dbf40`. The dispatch is `state - 1` into a
14-entry table at `0x2067ed0`; states 2, 4, 7 and 9 (the four the sends leave the machine in) take
the table's shared default `0x010db38c`, the function's epilogue. The machine leaves an idle state
only through `0x010dbf40`.

`0x010dbf40` takes a u16, drops out with the state untouched if it is above 4, and otherwise indexes
a 5-entry table at `0x2067f4c`:

    phase 0  -> state 1             -> send(0), announcing phase 1     0x010db308
    phase 1  -> state 3             -> send(1), announcing phase 2     0x010db0b0
    phase 2  -> state 5 -> 6 or 8   -> send(2), announcing phase 3     0x010db0dc / 0x010db104
    phase 3  -> state 10 or 11 -> 12 -> send(3), announcing phase 4    0x010db16c
    phase 4  -> state 13 -> 14      -> 0x010db970 tears the holders down and writes the sentinel
                                       0xfc18 to content+0x84. Nothing more is sent.

The two ways of reaching a send of 2 are the two roles: `[delegate+0x58]`, set in the init from
`0x110e620(...) & 1`, picks state 7 (send at once) or state 9 (send after a countdown
`[delegate+0x60]`, seeded from an xorshift to a random 2..302).

`0x010dbf40` is slot 0 of a second interface. The vtable group at `0x257fe90` is a
multiple-inheritance group: a primary vtable at `0x257fea0` whose slot 0 is the SyncCommand receive
handler `0x010dbc90` and whose slot 3 is `0x010dbf40`, then an offset-to-top of −8 at `0x257fec8` and
a secondary vtable at `0x257fed8` whose slot 0 is `0x010dbfd0`, the same code against `+0x50`/`+0x54`
instead of `+0x58`/`+0x5c` (the thunk for a `this` adjusted by 8). The init installs both halves:

    0x010da6bc   add x9, x19, #8       ->  [content+0x2c0] = delegate + 8     the second interface
    0x010da6d0   str x19, [x8, #0x168] ->  the 10040 holder's listener        the first

`0x010dbfd0` and `0x010dbf40` are 36 instructions each, identical but for the field offsets and the
branch targets; `0x010dbfd0`'s own jump table at `0x02067f60` holds the same five offsets from its
function as `0x02067f4c` (`0x70 0x38 0x40 0x48 0x6c`). Both write `delegate+0x5c`. The secondary
vtable's other slots: 4 is `0x010dc070`, which tail-calls `0x010f8e30`; 1, 2, 3, 5, 6 and 7 are each
a single `ret`.

### The pump

`0x010db3e0`, called by content 40's per-frame tick before it runs the machine, is a 17-state machine
on `[content+0x80]`. Its shared tail:

    w1 = [content+0x17c]                    the content's PHASE
    if (w1 != [content+0x84] && w1 != [content+0x86])                     0x010db758..0x010db778
        { 0x010de310(content, w1); B->slot7(w1); }                        slot 7 is a ret
    w1 = [content+0x17c]
    if (w1 != [content+0x84] && w1 == [content+0x86])                     0x010db794..0x010db7b4
        { 0x010de310(content, w1); B->slot0(w1); }   <- the state setter
    0x010ddf40(content)                     the queued jobs                0x010db7d4
    0x006d4b80(content+0xd0)                the element update, last       0x010db7e8

`B` is `[content+0x2c0]`, `delegate+8`, whose slot 0 is `0x010dbfd0`. The state switch runs before
the tail; state 0 (`0x010db740`) returns without the tail, and state 16 (`0x010db730`) returns early
when `0x006d4b30` is false. A phase that reaches a value neither committed nor announced is committed
silently: the flags and the job queue are cleared, the pump goes to state 2, and the machine does not
move.

`0x010de310(content, phase)` writes `[content+0x84] = phase`, drops the content's pending body and
empties the job queue at `content+0x310` (`0x010de348..0x010de3a0`): `+0x84` is the phase the
content has committed to. It has three callers, all in the pump and all gated on the phase differing
from `+0x84`: the tail's two blocks (`0x010db778`, `0x010db7b4`) and state 14 (`0x010db6ac`, under the
second block's gate and followed by slot 0). Once the element is minted, the phase the gate compares
moves only by the element update's adoption: the only halfword stores to `element+0xac` in
`0x006c8000..0x006de000` are the element constructor (`0x006d3ff8`), the mint (`0x006d4500`) and the
adoption (`0x006d4ccc`).

`+0x86` is written in exactly one place in the band, `0x010dbab0`, with the `flag` argument, which is `data + 1` at all five send sites: `+0x86` is
the phase the console announced when it sent its last command. The ladder climbs when the content's
phase reaches it.

The console's opening move is the pump's: the registrar leaves `[content+0x80] = 1` and pump state 1
(`0x010db418`, table `0x2067f08`) calls the state setter with the phase unconditionally, outside the
`+0x84`/`+0x86` gate. Phase 0 -> state 1 -> command 0, announcing 1. The constructor writes `0xfc18`
to `+0x84` (`0x010dc228`, `0x010dc260`) and zeroes `+0x86` (`0x010dc25c`); the registrar replaces
`+0x84` with its `w1`, 0, before any pump runs (`0x010da810`, `0x010daa78`), and mints the element
with the same 0 (`0x010daa7c`). After registration the phase, the committed phase and the announced
phase are all 0, and the tail does nothing until the phase moves.

The pump's states (jump table `0x2067f08`, 17 entries; `[content+0x1c0]` is the element's `+0xf0`
channel, `[content+0x2a0]` the command flags of [The command](#the-command)):

    1   0x010db418  element ready (0x006d4e70) -> 2; delegate slot 1, then slot 0 with the phase
    2   0x010db47c  a pending body at +0x88 -> 3
    3   0x010db48c  0x006d4f10: all ready and every pair's low half == the phase; send the body
                    (0x010de080) to the station [[0x2616a30]+0xf8] -> 4
    4   0x010db4dc  0x006d3690([+0x1c0], [+0x86]) publishes the station's high half, must return 1;
                    then 0x018407f0 ? 8 : 7                                      cinc 0x010db514
    5   0x010db51c  the same through [+0x2b8] (0x008b7300) with [+0xa8] -> 6; unreachable in
                    content 40, below
    8   0x010db594  0x006a2840([+0x2a0]): every station has sent a command -> 9
    9   0x010db5b4  0x006d4fb0 == 0: no sub-element still has its resend byte set -> 10
    10  0x010db5d4  0x006d4da0 && 0x006d3060([+0x1c0], [+0x86]) (every pair's high half == the
                    announced phase) && 0x006d4f50; then 0x006d33b0([+0x1c0], [+0x86]) writes the
                    shared value = the announced phase, and on success -> 7
    11  0x010db62c  0x006a2760([+0x2a0]) clears every flag; [+0x374] ? 12 : 2
    6, 7, 12        the table's default, the shared tail at 0x010db758

States 8 to 10 run only on the station `0x018407f0` accepts; any other station goes from 4 to 7 and
its phase moves when the shared value moves. State 13 follows `0x010dc6c0` and 16 the teardown
(table below); state 14 (`0x010db68c`) is the gated commit above, and states 13, 15 and 16
themselves are unread. Nothing in `0x010d9000..0x010df000` stores 5 to `[content+0x80]` or a
non-zero value to `[content+0xa8]` (the only stores there are the clears at `0x010db9ec`,
`0x010dc530` and `0x010de3a4`), so state 5 and its send are dead in content 40.

The other writers of `[content+0x80]`:

| site | function | state |
|---|---|---|
| `0x010dc234` | the constructor | 0 |
| `0x010daa9c` | the registrar | 1 |
| `0x010dbc70` | `0x010dbab0`, the command send (requires state 2; writes `+0x86`) | 3 |
| `0x010de3c4` | `0x010de310`, the commit: `+0x84` = phase, then `0x006a2760([+0x2a0])` at `0x010de344` clears every station's flag | 2 |
| `0x010dc7a0` | `0x010dc720` (slot `0x257ff70`), a station leaving: with `[+0x374]` set the delegate's slot 4 is told, otherwise the station is removed from the element (`0x006d50e0`) and the flags (`0x006a2140`) | 11 |
| `0x010dc6f4` | `0x010dc6c0` (slot `0x257ff68`), requires `[+0x374]` and `0x006a2a80([+0x2a0])` | 13 |
| `0x010dccec` | slot `0x257ff90` | 2 |
| `0x010dcee8` | `0x010dce70`, CancelAccepted on 30040 (`str w8,[x19,#0x18]` with `x19 = content+0x68`), unless the state is 16 | 2 |
| `0x010db998` | `0x010db970`, the teardown | 16 |

Content 40's registrar is called with `w2 = 1` (`0x010da6a8`), stored at `[+0x374]` (`0x010da800`),
so a station leaving sends state 11 on to 12 and ends the ladder.

### The phase is the element's field

Nothing between `0x010c0000` and `0x010e0000` stores to `content+0x17c`. The registrar builds the
40040 element at `content+0xd0` (`0x010daa4c add x21, x19, #0xd0`, then `0x006d4ff0` to add the
sub-element and `0x006d44e0(element, w20)` to mint it), and `0x006d44e0` opens with
`str wzr,[x0,#0xa8]; strh w1,[x0,#0xac]`. `0xd0 + 0xac` is `0x17c`: the phase is `element+0xac`,
starting at the registrar's `w1`, which content 40's init passes as `wzr`.

The element advances it in one place, `0x006d4ca0`, with the mesh's permission:

    w0  = 0x006d3260([element+0xf0])        read the shared value; 0xfc18 when there is none
    if (w0 == [element+0xac]) done
    if (0x006d3980([element+0xf0], w0)) {   publish it as our own, and only if that succeeds
        [element+0xac] = w0                 the phase moves
        [element+0xa0]->vtable[0]()         and the content is told
    }

That block is the tail of the element update `0x006d4b80`, which every sync content's pump calls last
(content 40 at `0x010db7e8`) and which runs only when `0x006ce5a0([element+0xb0])` returns 1. Before
every station is ready it takes another branch:

    if (!0x006d2e20(shared) && !0x006da180(hash channel)) {        nothing is ready yet
        if (0x018407f0([[0x2616a30]]))  0x006d33b0(shared, [element+0xac])
        0x006da3d0(hash channel, element+0xa8); 0x006d3980(shared, [element+0xac])
        return
    }

`0x018407f0(station)` is true when the station's own id `+0xf0` is non-zero and equals `+0xf8`, and a
virtual call (`+0xe0`) on the network backend at `[x0 + 0x168 + [x0+0x162]*8]` agrees. The station
object is Pia's session object, the backend Pia's `nn::pia::local::LdnMatchmakeSession`, and `+0xf8`
the id of Pia's mesh host ([the session page](swsh_session.md#the-pia-session-object)): the test
picks the console that hosts the mesh. Only that station seeds the shared value with its own phase;
every station adopts the shared value.

The shared value is the 16-bit sub-element the `+0xf0` channel owns
([Sub-element kinds](swsh_protocol.md#sub-element-kinds)). The channel's methods:

    0x006d3260  read            ready byte [sub+0x61] ? [sub+0x88] : 0xfc18
    0x006d33b0  write(v)        calls 0x006d3570 when the sub-element is not ready or its body != v
    0x006d3570  publish         body [sub+0x88] = v; clock from 0x01766740 (-1 records error
                                0x2c27); [sub+0x80]->vtable[0] with (sub+0x88, 2, clock, [sub+0x62],
                                [sub+0x68]) when [sub+0x80]->vtable[1]() or [sub+0x70] allows,
                                and the resend byte [sub+0x60] = !sent; otherwise [sub+0x60] = 1
    0x006d2e20  all ready       the shared value and every station's pair are ready
    0x006d2c20  all low == v    all ready, and every pair's low half [sub+0x88] == v
    0x006d3060  all high == v   all ready, and every pair's high half [sub+0x8a] == v

A station's own write sets the body and the resend byte and leaves the ready byte alone: the only
halfword store to `+0x60` in the 16-bit class is its receive handler (`0x006d6a08`). `0x006d3260`
therefore reads `0xfc18` on a station that has only written it, until a message for that
sub-element arrives. On the master that message is its own: the receive slot `0x006d69f0` (`cmp
x2,#2`, then `strh [x0+0x88]`, `str x3,[x0+0x78]`, `strh [x0+0x60]`) sets the ready byte, and the
write path stores only the body (`0x006d35b8 strh w8,[x20,#0x88]!`). In a completed trade with the
client as joiner, all 149 of the client's messages on 40040 carried a four-byte body, none a
two-byte one, and the console's step body's low half followed each of its own shared values. The publish reaches the element's primary slot 0 (`0x006d5730`), which queues the body once per
station in `[element+0x70..+0x78]`.

### The step body

The four-byte body on the confirmation content's elementId 20000 has two halves with two publishers;
neither touches the other's half:

    0x006d3980(channel, v)   w8 = [sub+0x8a]; body = <u16 v><u16 w8>     writes the LOW half
                             called from the element's update with the value it just read
    0x006d3690(channel, v)   w8 = [sub+0x88]; body = <u16 w8><u16 v>     writes the HIGH half
                             called from content 40's pump, state 4, with [content+0x86]

Both resolve the sub-element by finding the station's own id (`[[0x2616a30]]+0xf0`) in the channel's
`{ownerId, entry}` table and taking `[entry+0x60] - 0x50`, and both hand the result to `0x006d3860`,
which is `0x010dbe20` one layer down. The pump reaches the channel as `[content+0x1c0]` and the
element's update as `[element+0xf0]`; `0xd0 + 0xf0` is `0x1c0`, the same object by two routes.

The low u16 is the phase and the high u16 is what the sender last announced. An observed ladder:

    000018fc   phase 0, announced 0xfc18   the sub-element's birth sentinel
    00000100   phase 0, announced 1        the cue - the console had already sent command 0
    01000100   phase 1, announced 1        the phase caught up, so the content committed
    01000200   phase 1, announced 2        it ran state 3, which sends command 1
    02000200   phase 2, announced 2        the phase caught up again
    02000300   phase 2, announced 3        it committed and sent command 2
    04000400   phase 4                     the teardown rung

`swsh_trade.parse_sync_step` decodes one; `swsh_trade.SYNC_LADDER` and `sync_announced_phase` carry
the mapping.

### The command

`SyncSaveDataHolder{syncCommand{data:N}}` on 10040, reliable port 0. The handler `0x010dbc90`
resolves the sender with `0x006b5850` and drops on `0xfd`; keeps the int32 from `[arg1+0x14]`;
indexes the subscriber slots at `+0x38` by the station index; hands the int32 to the relay
`0x010dbe20` and to the subscriber's vtable `+0x18`; and then, unconditionally:

    0x010dbdf8  ldr  x8, [x20, #0x18]
    0x010dbdfc  ldr  x0, [x8, #0x2a0]
    0x010dbe00  mov  w2, #1          <- the value recorded for this station is a constant
    0x010dbe04  mov  x1, x19         <- keyed by the sender
    0x010dbe08  bl   #0x6a24a0

The console files `1` against a station whatever number was sent. The int32 goes only to the relay:
an elementId-1 body of `00000000` appears right after a `syncCommand{data:0}`, the echo of the value.
The only thing that moves the content's state is `0x010dbf40`, whose sole caller is the pump, which
passes the content's own phase. A rung advances because a command arrives, not because of which of
0..3 it carries.

`[content+0x2a0]` is a per-station flag object; `0x006a24a0` has 44 call sites across the image.

    0x006a24a0(obj, id, flag)   map[id] = flag & 1; the map is at obj+0x1c0, find-or-insert
                                0x006a24d0 hashes by udiv/msub against the bucket count at +0x10
    0x006a2840(obj)             1 when every station in the list at obj+0x100 (count +0x108) has a
                                non-zero value; an absent id reads 0
    0x006a2760(obj)             clear(): frees the nodes, zeroes the buckets and the size at +0x270
    0x006a2480(obj)             obj+0xc0, the station list the registrar walks

Pump state 8 waits on `0x006a2840`, and both the commit `0x010de310` and state 11 clear the map, so a
flag set before the commit does not count towards the next state 8. The flag is set inside the
network update's message drain, outside the pump: `0x006a9a20` calls Pia's dispatch `0x006a8380`
(`0x006a9a54`) and then the manager's drain `0x006db3b0` (`0x006a9a90`), which drains every
registered port ([the routing path](swsh_protocol.md#the-routing-path)). The drain has three
callers, `0x00ef4a9c`, `0x01109250` and `0x01109308`; the frame function `0x00f1df30` runs two of
them, one on each side of the game update:

    0x00f1df30  bl 0x01109240     network update: 0x01109250 bl 0x006a9a20, the drain
                bl 0x00fa09a0
                bl 0x00f1cc60     the game update
                bl 0x00793ec0
                bl 0x011092f0     0x01109304 bl 0x01111db0, 0x01109308 bl 0x006a9a20, the drain again

Two more content-40 handlers read the map, RequestCancel and RequestCancelAll on 30040
([below](#the-cancel-and-proceed-messages)).

A rung takes one command that reaches the master after the previous commit: the flag is a boolean
and the commit clears it. In rung 0 no commit precedes state 8, so any command received after the
registrar counts, the one sent on the cue `00000100` included. In later rungs the command sent on
the cue (`01000200`, `02000300`, `03000400`) arrives before the commit that follows the adoption and
is cleared; the one sent when the low half catches up (`01000100`, `02000200`, `03000300`) serves
the rung. Measured with the command count as the only variable, each command sent on the body just
received:

| commands | sent on | last body |
|---|---|---|
| 1 | `00000100` | `01000200`: rung 0 |
| 4 | `000018fc`, `00000100`, `01000100`, `01000200` | `02000300`: rungs 0 and 1; the command on `01000200` cleared |
| 9 | every new body from `000018fc` to `04000400` | `04000400`: the trade |

The trigger pops a command on every four-byte body not seen before, the birth sentinel `000018fc`
included, so the queue must not run dry. `--confirm-commands 0,1,2,3,0,1,2,3,0,1,2,3` is the
working line.

`answer_rpc` copies the body it was handed, so an answer that echoes a step carries the console's own
two u16s back and moves neither half. `--confirm-phase N` writes the low half and keeps the high one.

### The cancel and proceed messages

Content 40's third holder is message 30040, the framework's `SequenceDataHolder`
([the protocol page](swsh_protocol.md#the-30000-holder)). The registrar stores it at
`[content+0x2b8]` (`0x010da9b8`) and makes `content+0x68` its listener (`0x010da9b4`,
`0x010da9bc`); the constructor puts the listener vtable `0x02580030` there (`0x010dc238`):

| case | message | handler |
|---|---|---|
| 1 | CancelAccepted | `0x010dce70` |
| 2 | RequestCancel | `0x010dc920`, through the thunk `0x010dcf20` |
| 3 | RequestCancelAll | `0x010dcaa0`, through `0x010dcf30` |
| 4 | RequestForcedProceed | `0x010dc7b0`, through `0x010dcf40` |

Each acts only when the message's `currentSeqNo` equals the committed phase `(s16)[content+0x84]`.

- RequestCancel, also only when not every station is flagged (`0x006a2840`, `0x010dc954`): queues a
  job, `0x010dd0c0`, that sends `CancelAccepted{currentSeqNo: [+0x84], isForced: 0}` to the sender
  through `[content+0x2b8]` (`0x008b7230`) and then clears the sender's flag, `map[sender] = 0`
  (`0x010dd114`).
- RequestCancelAll, under the same two guards: walks the flag object's station list
  (`0x010dcaf4..0x010dcb1c`) and queues one job, `0x010dd190`, per station. Each sends
  `CancelAccepted{[+0x84], isForced: 1}` to its station while that station is still listed, then
  clears every flag (`0x010dd208`).
- CancelAccepted: with `isForced` set, steps the generation counter `[content+0x370]` modulo 255 and
  hands it to `0x006db470` on the message manager; then sets pump state 2 unless the state is 16
  (`0x010dcee8`) and calls the delegate's slot 6, a `ret`. The phase does not move, and the pump
  re-runs states 2 to 4 with any pending body.
- RequestForcedProceed: builds a job `{content, u16 targetSeqNo, sender index}` with code
  `0x010dd040` and runs it at once (`0x010dc8a8`); a job that returns false is queued
  (`0x010dc8bc`). The job requires `0x006d4da0(content+0xd0)`, the element's hash current or
  republished, and then calls `0x006d33b0([content+0x1c0], targetSeqNo)`, the write pump state 10
  performs with the announced phase. It skips pump states 8 and 9, the `0x006d3060` and `0x006d4f50`
  tests and the master test `0x018407f0`; the sender index is kept in the job and not read.

The job queue at `content+0x310` (entries at `+0x350`, count at `+0x358`) is run by `0x010ddf40`
from the pump (`0x010db7d4`): every queued job is tried once per pump call, a job that returns true is
removed and one that returns false stays. The commit empties it.

### Shapes the confirmation content also sends

Alongside the pair, the console sends 40040 envelopes with no ownerId and bodies that are not four
bytes:

    elementId 20000, no owner, 2 bytes   0000   then   0100
    elementId 1,     no owner, 4 bytes   00000000        after a syncCommand{data:0}
    no elementId,    no owner, 4 bytes   00000000  then  01000000

The pair's receive handler `0x006d6490` drops the two-byte ones (`cmp x2,#4`); they match the shared
value, the element's 16-bit sub-element ([The phase is the element's field](#the-phase-is-the-elements-field)).

## The League Card

After the trade each console asks on the trade box whether to receive the partner's League Card
("Voulez-vous recevoir la carte de Ligue de votre partenaire d'échange ?", Oui / Non). The answer
sends nothing: between the end of the ladder and 80 s later, across both players answering Oui,
an emulated pair exchanged only Sync Clock, reliable acknowledgements and mesh keepalives. The card
is the TrainerCard both sides already sent at 0x924 of the 0x84 snapshot
([the protocol page](swsh_protocol.md#the-party-payload-on-protocol-0x84)).

A Oui files it in save block `0x28e707f5`: 139200 bytes, 300 slots of 464. The first free slot
takes the snapshot's 456 bytes byte for byte, then eight bytes: `00 00`, the year as a u16, the
month, the day, `02`, `00` (`00 00 ea 07 09 1a 02 00` on 2026-09-26). A console already holding
the partner's card does not ask: two sessions between the same two saves asked once, and emptying
that slot brought the question back.

The card a console files is whatever the partner's snapshot carries. An emulated Shield joining
`bin/swsh_host.py` asked, and filed the host's 456 bytes (the Sword snapshot renamed to PkCamp)
unchanged in its next free slot, with the save written at once.

The album keeps 300 slots of 0x1d0 bytes from `album+0x230`, loaded as one block of `0x21fc0` bytes
(`0x013fad4c`); a slot is free while its byte `+0x1c8` is non-zero. `0x013fbab0` files a card in the
first free slot: a `memcpy` of 0x1c4 bytes, then `+0x1c8` and `+0x1c9` zeroed, the year at `+0x1ca`
(`tm_year + 0x76c`), the month plus one at `+0x1cc`, the day at `+0x1cd`, and `+0x1ce`, `+0x1cf`
from its arguments. `0x013fbc00` returns 1 when all 300 slots are used.

The console skips the question when a card it holds matches the partner's on two fields.
`0x013fbc40(album, card)` (callers `0x00aa6414`, `0x0106612c`, `0x015253f0`, `0x01543868`) walks the
300 slots and returns 1 on the first used slot whose u32 at 0x1C equals the card's (`0x013fbc4c`)
and whose eight bytes at 0x1A8 equal the card's (`0x013fbc5c`, one 64-bit compare). 0x1C is the
trainer id (PKHeX `TrainerCard8.TrainerID`); 0x1A8 is PKHeX's `TimestampPrinted`, a Unix time:
`9bc62a5e00000000` (2020-01-24) in a retail Sword's card, `04b4a26a00000000` (2026-09-10, the same
day as its start date at 0x170) in an emulated Shield's. The game compares all eight bytes;
`pokeldn.swsh.league_card` maps the field as a u32. The trainer id is the six-digit one derived from MyStatus, `(SID << 16 | TID) mod
10**6`: 848973 for a retail Sword at 56909/48474, 491351 for an emulated Shield at 56983/22788.
`trade_payload.rewrite` sets it with the other identity fields. Measured against one emulated Shield holding the host's card:

| the host's card | asked |
|---|---|
| unchanged | no |
| trainer id 848973 -> 111111 | yes; filed in a new slot beside the first |
| Pokédex count 400 -> 401 | no |
| name PkCamp -> PkCampX | no |

A retail Sword hosted over the board asked and kept the host's card (id 993401): its League Card
list shows PkCamp dated the day received, the Sword logo top left (`game` 0), "3" bottom left (the
three ASCII bytes at 0x39 read `3`), a crown top right and five stars. The crown, a Rotom-Dex
icon, is `dex_complete` at 0x30: a second card with it cleared kept its five stars and lost the icon.

The card view `0x01592e70` copies the card it holds (`view+0x3c0`) and draws the front's stars with
`0x015a52f0(view, count)`, which clears seven panes (`view+0x618..+0x648`) and lights `count + 1`
of them, the first even for count 0:

    count = card[0x177] + (card[0x1b6] != 0) + (card[0x1b7] != 0)      0x015930bc..0x015930dc

A card with 4 at 0x177 and zero at 0x1B6 and 0x1B7 draws five stars. The validator below caps the
count at 6; a count of 7 would light `view+0x650`, outside the seven panes. The same function passes `card[0x24]`, the game, to `0x015a5260` and `card[0x1b3] != 0` to
`0x015a50d0`. The card builder `0x0158eef0` (callers `0x00c77830`, `0x014be578`, `0x0156167c`,
`0x01561b0c`, `0x01568f4c`, `0x015691bc`) fills those bytes from the save:

| byte | value | site |
|---|---|---|
| 0x177 | `DesignLevel`: 4 when `FSYS_GAME_CLEAR` (`0x7d0b1ced4dbe8a87`) is set; otherwise 3, 2, 1 or 0 for a badge count above 6, above 3, non-zero, zero | `0x0158f084`, `0x0158f484..0x0158f4dc`, stored `0x0158f0c4` |
| 0x1B1 | `FSYS_SEED_CHALLENGE` (`0xbd07c2b80232e9b0`) | `0x0158f564..0x0158f5a0` |
| 0x1B3 | `FSYS_INPUT_SHIRT_NUMBER` (`0xe44b16771524b07e`) | `0x0158f0fc` |
| 0x1B6 | `FSYS_R1_GAME_CLEAR` (`0x8f1a133dff5c0ecf`), one more star | `0x0158f11c` |
| 0x1B7 | `FSYS_R2_GAME_CLEAR` (`0xd450875d834cfc30`), one more star | `0x0158f12c` |

The flag names hash to these values under the game's FNV-1a 64 basis `0xcbf29ce484222645`
([the protocol page](swsh_protocol.md#the-player-profile)). The badge count is `0x01438fb0`, a
popcount of `[status+0x60]`; the flags are read by `0x01410f30`. The name `DesignLevel` is the
`capture_data.prmb` column the reader at `0x0158ead4..0x0158eb30` stores at 0x177 (hash
`0x3bc4598485d2a2ef`, string `0x01c2a2e9`, `strb w0,[x22,#0x177]`); `GlossIndex` follows at 0x178.
The retail Sword card pokeldn sends carries `04` at 0x177 and zero at 0x1B6 and 0x1B7.

The game checks a card with `0x0158f5e0` before showing it and replaces one it rejects with a
default; it returns 1 to reject. Run under unicorn on the card pokeldn sends (0x177 = 4, 0x1B3 = 1,
language 3) it accepts; DesignLevel 5, language 6 or GlossIndex 9 are rejected, DesignLevel 4 and
0x1B6 or 0x1B7 set to 1 accepted. A `--card-set` edit must stay inside those ranges.

`bin/swsh_host.py --card-set FIELD=VALUE` edits the card it sends (`pokeldn.swsh.league_card`
names the fields), so a fresh `trainer_id` makes the console offer to keep it.

## The record we offer

The Pokemon offered on 20030 is a party record out of the 0x84 snapshot the client sends, selected
by `--offer-slot`. The edit is applied to the slot inside the snapshot, so the party the console is
shown and the Pokemon it is offered are the same record. `party_matches_trainer` holds after it: the
identity rewrite runs first and the offer flags do not touch the trainer ids.

`pokeldn.swsh.pokemon.build_from` rewrites the checksum, reshuffles the four blocks under the new
encryption constant, and keeps every byte no flag names. The 0x158 party form carries ribbons,
memories, met data and handler records that nothing here reads.

A retail Sword takes a record its save already holds: the same Gengar, under the same PID and
encryption constant, traded into one save four times from `bin/swsh_host.py`. The Sword launchers
have no `--fresh-pid`; Brilliant Diamond flags a duplicate of a record its save holds as illegal
([the BDSP trade page](bdsp_trade.md)).

    --offer-slot 1 --offer-nickname PKCAMP --offer-ivs 31,31,31,31,31,31

| flag | effect |
|---|---|
| `--offer-nickname`, `--offer-ot` | 26-byte UTF-16 fields; at most 12 characters. A nickname sets the nicknamed flag; without it the console draws the species name |
| `--offer-species` | the species word alone; ability, moves, party stats, experience and met data stay the template's |
| `--offer-ability ID`, `--offer-moves A,B,C,D` | the two fields; PP and relearn moves stay |
| `--offer-level N` | the level byte at 0x148 |
| `--offer-experience N` | the experience word at 0x10 |
| `--offer-ivs` | the six IVs |
| `--offer-file FILE` | a `.pk8` from disk in any of its four shapes (stored or party, encrypted or PKHeX's decrypted export, told apart by whether the header checksum matches the raw body). Its OT name and ids are moved to the snapshot's trainer |
| `--offer-file-as-is` | keeps the file's OT |
| `--save-offer FILE` | writes the built record before the radio is touched |

Measured on a French Sword 1.3.2, one variable per run:

| record sent | result on the console |
|---|---|
| slot-1 Gengar template, nickname `PKCAMP`, six IVs of 31 | accepted, saved; summary read the nickname, level 100, `Potentiel exceptionnel`. Unnamed fields came through as the template's: female, ball 9, held item 281 (Boue Noire), met level 59, language 3, version 44 |
| the same with the species word set to 93 (Haunter), ability 130 (Cursed Body, which Haunter lacks), the Gengar's moves 164, 247, 482, 411 and stats | drawn as a Haunter named PKCAMP, saved, then trade-evolved to Gengar. Neither ability nor moves are checked against the species |
| the same with the species word set to 25 (Pikachu) | accepted. Summary: level 100, HP 211, Atk 131, Def 116, SpA 199, SpD 137, Spe 306: Pikachu's level-100 stats from the record's IVs (31, 31, 19, 6, 31, 31 in HP, Atk, Def, Spe, SpA, SpD order), EVs (0, 0, 0, 252, 252, 6), Timid nature and the hyper-training byte 0x24 at 0x126 (Def and Spe read as IV 31). The twelve stat bytes at 0x14A (the Gengar's 261/149/156/350/359/187) were discarded. Ability Cursed Body, item Black Sludge, moves Substitute, Shadow Ball, Sludge Wave, Focus Blast kept as sent |
| the Pikachu with the level byte at 0x148 set to 50 and experience left at 1059860 | drawn and received at level 100. The level comes from the experience word at 0x10; the party tail (level and stats) is discarded on receipt and rebuilt from the stored record |
| a PKHeX party-form export of a level-18 Flapple, OT moved to the snapshot's trainer (PkCamp, 12345/54321) | drawn as a level-18 Flapple, traded; summary read OT PkCamp, ID 993401 (`(54321 << 16 \| 12345) mod 1000000`, the six-digit Gen 7+ form), 9564 experience |
| the same file with its own OT kept (the receiving player's own name and ids, 56909/48474) under a MyStatus that says PkCamp | accepted and traded. Summary: the player's own OT name, ID 848973, met line as the player's own catch: level 18 on 26/11/2019 on Route 5 (the record's met date, level and location 40). The game does not compare the offered record's OT ids with the partner's MyStatus |
| the Flapple with the PID high half set to `low ^ TID ^ SID` against 12345/54321 (gender and nature bytes untouched; they are stored separately in Gen 8) | drawn shiny on the offer screen; shiny star on the summary after the trade |
| the Flapple file with the species word set to 152 (absent from the game) | climbed the whole ladder, landed in the PC. Offer screen: Pikachu's model, name Pomdrapi (the record's name field, nicknamed flag clear). Box icon a black Poke Ball, level 21: 9564 experience is level 21 on Medium Fast (21^3 = 9261, 22^3 = 10648), level 18 on Erratic, level 23 on Medium Slow. Traded back: level 21, stats 33/6/8/8/8/10 = base stats of zero at level 21 with the file's IVs (14, 7, 18, 17, 21, 24) and Adamant nature (HP `floor(14 * 21 / 100) + 31`, the rest `floor(IV * 21 / 100) + 5` with nature). The species entry for 152 is empty: zero base stats, growth group 0. Every other byte came back unchanged except current HP at 0x8A (55 to 33) and the handler block: the player's own name at 0xA8, gender at 0xC2, language 3 at 0xC3, friendship 0 at 0xC8, two memory bytes at 0xCB-0xCC |

Unmeasured: which model and name the game draws for other absent species, and whether the name
shown came from the record's name field or from a failed species-name lookup.

A record the console offers can be one an earlier run gave it. One 20030 offer carried the client's
own trainer ids, `PkCamp` as the original trainer and the slot-1 template's nickname and IVs, with
`CurrentHandler` 1 and `HandlingTrainerName` the console's player.

    ./.venv/bin/python scratchpad/sw_offer_check.py SNAPSHOT --offer-slot 1 --offer-nickname PKCAMP

builds the record offline, reads it back through `offered_pokemon`, and prints the party and the
identity consistency.

## The command line of a completed trade

`swsh_join.py --scan-only` records the network advertisement, not the party snapshot. To obtain
the snapshot for the first trade, let the console search for a local Link Trade and run the
connector through the snapshot receive stage. This uses the working transport flags without
sending a party or an offer:

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/swsh_connect.py --keys PROD_KEYS \
        --channels 1,6,11 --dwell 2.5 --listen-first 6 \
        --station-sweep 0 --ack-seconds 12 --connect --no-variable-id --request-platform 9 \
        --request-flags 0x09 --connect-station 0 --nat-flags 0 --nat-location 0 --respond \
        --respond-with theirs --join --answer-rtt --ack-reliable --send-data 610000000a00 \
        --sync-answers --send-protocol 0x7c --send-after 4 --send-count 1200 --send-period 0.3 \
        --send-seconds 350 --send2-data 60ea000012020801 --send2-trigger 60ea000012020801 \
        --send2-protocol 0x80 --ack-snapshot --hold 90 --capture scratchpad/swsh_first.jsonl

After the log shows fragments 0, 1 and 2, extract the 3456-byte payload:

    ./.venv/bin/python tools/switch/swsh_snapshot.py scratchpad/swsh_first.jsonl scratchpad/swsh_snapshot.bin

Use that file for `--send-snapshot` in the completed-trade line below. The console must be the
same one that supplied the snapshot.

`bin/swsh_connect.py` runs every layer of a trade. The line below completed one against a French
Sword 1.3.2, the client joining the console's Link Trade session; `SNAPSHOT` is a 3456-byte party
snapshot, the 0x84 payload of an earlier session against the same console, whose identity is
rewritten to the client's trainer before it is sent back.

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/swsh_connect.py --keys PROD_KEYS \
        --channels 1,6,11 --dwell 2.5 --listen-first 6 \
        --station-sweep 0 --ack-seconds 12 --connect --no-variable-id --request-platform 9 \
        --request-flags 0x09 --connect-station 0 --nat-flags 0 --nat-location 0 --respond \
        --respond-with theirs --join --answer-rtt --ack-reliable --send-data 610000000a00 \
        --sync-answers --send-protocol 0x7c --send-after 4 --send-count 1200 --send-period 0.3 \
        --send-seconds 350 --send2-data 60ea000012020801 --send2-trigger 60ea000012020801 \
        --send2-protocol 0x80 --ack-snapshot --send-snapshot SNAPSHOT --snapshot-port 1 \
        --rpc-port-answers --rpc-pair --rpc-bodies --selection-final-delta 9 --selection-offer \
        --offer-slot 1 --offer-nickname PKCAMP --open-content 30,50 --open-content-offer \
        --box-commands 1 --box-on-accept 4 --box-period 0.35 --save-offered offered.pk8 \
        --confirm-commands 0,1,2,3,0,1,2,3,0,1,2,3 --confirm-final-delta 9 --abort-on-stall 15 \
        --hold 240 --capture trade.jsonl

`--offer-file FILE` in place of `--offer-slot` puts a `.pk8` on the wire. On a Linux card, drop
`POKELDN_RADIO` and prime the kernel's BSS table with `iw dev IFACE scan` before the run
([The cartridge and the session](swsh_session.md)).

## The penalty, and ending a run cleanly

A trade that times out with the link still alive is reported by the game as a failed trade and
costs the console about an hour's lockout (measured by the player across two runs). The alert is
`msg_ui_live_comm_app_alert_00`, line 331 of `/bin/message/French/common/live_comm.dat`; the text
names no duration and the label does not appear in 1.3.2's `main.bin`.

A trade whose link disappears is reported as a plain communication error, `2-ALZAA-0016`, and a new
local search is available at once.

`bin/swsh_connect.py --abort-on-stall SECONDS` drops the link once the confirmation ladder has
produced its first step and SECONDS pass with no new body on it. The trigger keys on bodies not seen
before: the console repeats the step it is parked on.

The abort stands down at phase 4. Phase 4 is the teardown rung and its state sends nothing, so a
finished ladder is silent like a stalled one. `stall_abort()` takes `final_phase_seen`; a ladder that
has reached `LADDER_FINAL_PHASE` is done, and the run holds for the save, the summary and the
migration.

Never change the console's clock or any system setting to clear an in-game gate. BDSP detects a
clock change and locks time-based features for a day.

## Verifying a completed trade

A Pokemon the console received in a trade comes back with `CurrentHandler` 1 at 0xC4 and the
receiving player's name in `HandlingTrainerName` at 0xA8, over an original trainer that is still the
sender's.

With `--offer-echo` (the console's own record handed back) a completed trade and a returned Pokemon
look identical: the player receives the Applin they offered. Offering slot 1 of the advertised party
makes the species the proof: a player who offers an Applin and receives an Ectoplasma has seen the
transfer.
