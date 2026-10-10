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

- What left a retail console silent on both of the host's `0xa1` after a host answered its withdrawn
  vote with A 2. The host's publishes: A 2 with trailing word 1, then A 2 with trailing word 2 one
  second later; the console republished `0 2 3` under trailing word 2 and announced its commit clone
  5.0 s after the first A 2. The host answered the announcement with `82, 91, 91, 84, 81, a1, a1`,
  seven datagrams within 1 ms, all acknowledged by the console's radio. The console re-announced the
  clone on clone type 1 under a new clock, which only the `0x81` on clone type 2 does (`0x51ca48`
  -> `0x520c30`, after the `0x91` on clone type 2 unlinked the announcement at `0x520d30`; the `0x82`
  on clone type 1 reaches only `0x5223c0` and sends nothing). It answered neither `0xa1`. The clone
  type 1 `0xa1` handler (`0x51c714`, `0x522350`) sends on every outcome and `0x51e3d0` spends a
  message count before it can fail; the console spent none. Every gate before the handlers (the
  receive loop's station mask and frame-counter filter `0x51ae20..0x51ae84`, the destination check
  `0x51ce80`, the count filter `0x51c1e0`, the `+0x3c` mask `0x51c6b0`) passed for the `0x81` with
  the same sender, frame counter and mask. `0x522a60` returning 2 would silence the clone type 4
  `0xa1` alone. An emulated Let's Go 1.0.2 given the same inputs answered both `0xa1` with `0xa2`
  within 30 ms and completed the trade: it withdrew its vote (`2 2 3`) 0.81 s after its own `1 2 2`,
  the host published A 2 with trailing word 1 0.16 s later and trailing word 2 1.0 s after that, the
  console republished `0 2 3` under trailing word 2, announced its commit clone 5.4 s after the first
  A 2 and drew the same seven-message burst. The retail console runs 1.0.2 as well; what differs on
  retail is unknown.
