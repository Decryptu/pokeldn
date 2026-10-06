---
title: Let's Go Pikachu and Eevee
nav_order: 7
has_children: true
---

# Let's Go Pikachu and Eevee

In Pokemon Let's Go Pikachu and Let's Go Eevee (2018), Pia is statically linked into `main` (269
`nn::pia` classes in the RTTI) and the game's C++ code sits on it with protocol-buffer messages
through `gflnet3`, the middleware Sword and Shield use a year later.

The static reading is Let's Go Pikachu 1.0.2 (`010003f003a34000`, update NSP `v131072`, SDK
5.4.151.0); hardware measurements are against a French Let's Go Pikachu and a Let's Go Eevee. Let's
Go Eevee uses Pikachu's local communication id, so both roles trade with an Eevee unchanged.

Local trading and battling ask both players for a link code: three Pokemon in order from a fixed ten,
shown in two rows: Pikachu, Eevee, Bulbasaur, Charmander, Squirtle; Pidgey, Caterpie, Rattata,
Jigglypuff, Diglett. The code sets the advertisement's scene id
([the session page](lgpe_session.md#the-link-code)); hosting and joining both work under any code.

## Pages

| page | contents |
|---|---|
| [The Let's Go cartridge and session](lgpe_session.md) | what the title is built from, the LDN passphrase and Pia game key, Pia header version 3, the session key, the station and clone protocols as a real session runs them, the gate that starts the game's own messages, and the four game messages of a trade |

## What works

`bin/lgpe_join.py` joins a console's session and `bin/lgpe_host.py` hosts one the console joins. A
seat carries one trade after another: after each
trade's normal save the trade dispatcher goes from state 7 back to state 1 unless the save reports
that the link ends (`0x886908`), and the save re-creates the party-offer object on a new channel
(`0x8375a4`) ([the session page](lgpe_session.md#the-trade-dispatcher)). Both launchers take a queue
of records, one per trade on the seat. The game checks no field of a received box structure: a shiny
level-100 Imposter Ditto with 31 in every IV and 200 in every AV reads back on the summary screen.
The Clone Protocol's take-over exchange passes the game's `0x11b080` gate, and the Reliable Protocol
carries identity, offer, commit and kind 4 (the next trade's selection); `pokeldn.lgpe.pb7` reads and
writes the 232-byte box structure the offer and kind 4 carry.

Three queued trades complete on one seat in both roles. Each completed entry is saved as a
checksummed 260-byte file, and the host exits with code 0 after the console leaves. A record built by
`pokeldn.pokemon` (level, gender, nature, ball, IVs and AVs chosen) and offered by `bin/lgpe_host.py
--fresh-pid` shows those fields on the receiving summary screen.

A console leaves the seat when its player presses Retour. `bin/lgpe_join.py --leave-after SECONDS`
runs the same exit that long after its first answered trade step, and `bin/lgpe_host.py` answers a
console's Retour ([A joiner leaving](lgpe_session.md#a-joiner-leaving)).
`tests/test_lgpe_host_commit.py` pins the host's commit stage against a scripted console: a wrong
commit leaves the console on its confirmation screen with the save's trade lock set (no trades for
ten minutes of counted play time), then the fatal error screen.

## Unresolved

- How counted play time relates to wall time, so how long the lock lasts on a clock: the rate of
  the gated call `0x13c944` and whether the frame period stays at 33.3 ms are unread. Trying Link
  Trade at play time P + 9 and P + 11 minutes after an aborted commit, against a stopwatch, measures
  both.
- What leaves a console's clone protocol silent on the host's `0xa1` on clone type 4, while its radio
  acknowledges every frame, after a host answers its withdrawn vote with A 2. `0x51c110`
  drops such a message silently in `0x522a60` while the sender's bit is in the `+0xc0` mask, and
  earlier at the destination check, the per-sender count filter or a length check; the message's own
  bytes (destination `0x0002`, count 69 after a highest earlier host count of 63) pass the first two
  for in-order delivery. What held the silence is unknown; the capture shows no
  severity-4 error (`0x4d8a80`, result 2 and the fatal error screen). An `0xa1` repeated until
  answered separates a pending mask (a later copy answered) from a message that never reaches the
  clone protocol (none answered); a sniffing board records what arrived independently of the host.
- Which process the trade dispatcher's child is, and whether the sync save's commit channel at
  `seq+0xb8` is released after an aborted commit.
- Whether the dispatcher's modes 1 and 2 are link battles. The reading rests on the scene they build;
  a capture of a link battle's session, with the mode word `+0x8c`, settles it.
