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

A trade is complete against a retail Let's Go Pikachu in both directions: with this project as
the joiner of the console's session, and with the console joining a session `bin/lgpe_host.py`
hosts. A box structure built here goes into the retail save as sent: a shiny level-100 Imposter
Ditto with 31 in every IV and 200 in every AV reads back on the console's summary screen, and the
game checks none of its fields on receipt. Every layer runs: association with the 64-byte
passphrase, the session key, the version-3 Pia header, the 22-byte message framing, the version-9
station connection handshake, the mesh join, the Sync Clock and RTT protocols, the Clone Protocol
through the take-over exchange that passes the game's `0x11b080` gate, and the Reliable Protocol
carrying the game's messages: identity, offer, commit, and the kind 4 that follows the trade.
`pokeldn.lgpe.pb7` reads and writes the 232-byte box structure the offer and kind 4 carry.

Leaving is clean both ways. A joiner backs out with `--leave-after` the way a console does, and a
host answers the console's Retour, so the player lands on the menu with no error. The commit stage
of the host is pinned against a scripted console by `tests/test_lgpe_host_commit.py`, because a
host that gets it wrong leaves the console on its confirmation screen and its save's trade lock
set, refusing trades for 600 seconds of foreground play. `docs/lgpe_session.md` has every layout.

## Unresolved

- Whether any code outside the clone protocol reads a received `ClockAndCount` message's bytes
  `+0x21..+0x23` with a wider load; within `0x516000..0x526000` nothing does.
- Whether a sync save aborted with result 2 always reaches the fatal error sequence and a restart
  of the software; the link from the parent's result to that sequence is untraced. A later save of
  the running game would commit the counter's 0.
- The call rate of `0x13c944`, which the 600-second reading of the lock assumes is at least once a
  second through the 20-call gate; the lock's wall-clock length has not been timed on a console.
- That the console which refused a trade after a host answered its withdrawn vote with A 2 had
  started its sync save on status 4 is consistent with the code and unchecked against the capture.
- Which of `[parent+0x88]+8` and `+0x10` is the station's own Pokemon in `0x838660`'s species rule
  rests on `0x838800` applying `+0x10` as the arriving one, and `mgr+0x128c` meaning the session host
  on a reading of `0x59e920`.
- Whether kind 4 is the offer channel of a next trade round, the re-created party-offer object's
  channel, which would put a second trade in one session on kind 4 for offers and kind 5 for the
  commit; which of `0x8869f0` and `0x886c70` destroys the object after a trade is unread.
- Which feature the senders in `0x9dce94..0x9dede8` belong to, the only code that sends a non-zero
  tag; it registers a channel of its own (`0x9dce1c`), which shifts the numbering in a session where
  it runs first.
