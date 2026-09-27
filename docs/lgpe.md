---
title: Let's Go Pikachu and Eevee
nav_order: 7
has_children: true
---

# Let's Go Pikachu and Eevee

In Pokemon Let's Go Pikachu and Let's Go Eevee (2018), Pia is the game's
own transport, statically linked into `main` (269 `nn::pia` classes in the RTTI), and the game's
code sits on it in C++ with protocol-buffer messages through `gflnet3`, the same middleware Sword and
Shield use a year later.

The static reading is taken from Let's Go Pikachu 1.0.2 (`010003f003a34000`, update NSP
`v131072`, SDK 5.4.151.0). Hardware measurements are against a French Let's Go Pikachu and a
Let's Go Eevee. A searching Let's Go Eevee advertises Let's Go Pikachu's local communication id,
`010003f003a34000`, and joins a host advertising it; both roles trade with an Eevee unchanged.

Local trading and battling ask both players for a link code: three Pokemon chosen in order from a
fixed set of ten, shown in two rows: Pikachu, Eevee, Bulbasaur, Charmander, Squirtle; Pidgey,
Caterpie, Rattata, Jigglypuff, Diglett. Most sessions here use Pikachu, Pikachu, Pikachu. The code
sets the advertisement's scene id ([the session page](lgpe_session.md#the-link-code)); a
console hosting under any code trades with a joiner, and a searching console joins a host that
advertises its scene id on its channel.

## Pages

| page | contents |
|---|---|
| [The Let's Go cartridge and session](lgpe_session.md) | what the title is built from, the LDN passphrase and Pia game key, Pia header version 3, the session key, the station and clone protocols as a real session runs them, the gate that starts the game's own messages, and the four game messages of a trade |

## What works

A trade is complete against a retail Let's Go Pikachu in both directions: with `bin/lgpe_join.py`
as the joiner of the console's session, and with the console joining a session `bin/lgpe_host.py`
hosts. A box structure built here goes into the retail save as sent: a shiny level-100 Imposter
Ditto with 31 in every IV and 200 in every AV reads back on the console's summary screen, and the
game checks none of its fields on receipt. Every layer runs: association with the 64-byte
passphrase, the session key, the version-3 Pia header, the 22-byte message framing, the version-9
station connection handshake, the mesh join, the Sync Clock and RTT protocols, the Clone Protocol
through the take-over exchange that passes the game's `0x11b080` gate, and the Reliable Protocol
carrying the game's messages: identity, offer, commit, and kind 4, the next round's offer that
follows the trade.
`pokeldn.lgpe.pb7` reads and writes the 232-byte box structure the offer and kind 4 carry.

Leaving is clean both ways. A joiner backs out with `--leave-after` the way a console does, and a
host answers the console's Retour, so the player lands on the menu with no error. The commit stage
of the host is pinned against a scripted console by `tests/test_lgpe_host_commit.py`, because a
host that gets it wrong leaves the console on its confirmation screen and its save's trade lock
set, refusing trades for at least 600 seconds of foreground play, and ends it on the fatal
error screen. `docs/lgpe_session.md` has every layout.

## Unresolved

- The text of the fatal error message `0x191615296121e064` an aborted trade commit shows; it lives in
  the romfs message archives. Whether the dispatcher re-enters its state 3 under the pushed fatal
  process and pushes another on each pass depends on the stack runner `0x13a780`, unread.
- The call rate of `0x13c944`: the lock lasts exactly 600 s of foreground time only if the gated call
  comes at least once a second, the job at 20 Hz or more. The scheduler above `0x231a0` is unread,
  the relocation that reaches the setup `0x13b650` is unchecked, and the lock has not been timed on a
  console.
- Why the console that refused a trade after a host answered its withdrawn vote with A 2 sent
  nothing more on its commit clone after announcing it. A severity-4 error in its state 3
  (`0x4d8a80`) would give result 2 and the fatal error screen, which fits the warning it held, but
  nothing in the capture shows the error, and whether the host's own clone 4 messages reached the air
  is unknown.
- A second trade in one session has not been run. By registration order its offers ride kind 4 and
  its commit kind 5, a third trade's kinds 6 and 7. The party-offer object that owned kind 2 is
  destroyed before the trade demo, so a peer that keeps offering on kind 2 and committing on kind 3
  after a first trade addresses channels the console has dropped.
- After a host migration inside a session, the ordinary-case 2 would stay with the station that was
  host at session start, since `mgr+0x128c` is written only by `0x116890`; whether a migration runs
  that function again is unread.
- That the session's u16 at `+0x1e6` is its station count, which would make a partner leaving during
  the sync save a code 0xe abort, is a reading of `0x59ea70` and not traced. The triggers of
  the listener's other slots are untraced.
- Whether a wild battle registers the battle scene's channel depends on the switch on `[ctx+0x64]`
  in `0x9d2c30` (`0x9d2d80`), unread. That the dispatcher's modes 1 and 2 are link battles is read
  from the scene they build.
- In `0x838800`, the pair `0x728250` and `0x7282c0` applied to the arriving copy reads as the trade
  evolution check; it, `0x1cfe80` and `0x1ca840(0x1dc or 0x1dd, 1)` are unidentified.
