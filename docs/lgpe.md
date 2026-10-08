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

- What left a retail console silent on the host's `0xa1` on clone type 4 after a host answered its
  withdrawn vote with A 2. In that capture the console announced its commit clone 5.0 s after the
  A 2; the host answered with `82, 91, 91, 84, 81, a1, a1` in one datagram, and the console reacted
  to the `0x82` (it re-announced the clone on clone type 1) but answered neither the `0x81` on clone
  type 2 nor the `0xa1` on clone type 4. Its radio acknowledged every one of the 6923 unicast frames
  of the session. The per-sender count filter (`0x51c1e0`) passes every host message (counts 14 to
  71, strictly rising). In the game's code the only silent outcome left for that `0xa1` is
  `0x522a60` returning 2 (the sender's bit in `[[x0+0x30]+0xc0]`), and no mask-setting event
  (state `0x22` or `0x42`, a join in state `0x22` or `0x31`) appears on the wire. An emulated Let's
  Go 1.0.2 given the same withdrawal, the same A 2 and the same burst announced its commit clone 3.4 s
  after the A 2, answered the host's `0xa1` with `0xa2` and completed the trade; breakpoints on the four `+0xc0` writers, the clear
  site `0x51c3b4` and the silent return `0x522a9c` never fired. What differs on retail is unknown.
