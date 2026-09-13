---
title: Let's Go Pikachu and Eevee
nav_order: 7
has_children: true
---

# Let's Go Pikachu and Eevee

Pokemon Let's Go Pikachu and Let's Go Eevee are native Switch titles from 2018. Pia is the game's
own transport, statically linked into `main` (269 `nn::pia` classes in the RTTI), and the game's
code sits on it in C++ with protocol-buffer messages through `gflnet3`, the same middleware Sword and
Shield use a year later.

The static reading is taken from Let's Go Pikachu 1.0.2 (`010003f003a34000`, update NSP
`v131072`, SDK 5.4.151.0). Hardware measurements are against a French Let's Go Pikachu.

Local trading and battling ask both players for a link code: three Pokemon chosen in order from a
fixed set. The sessions here use Pikachu, Pikachu, Pikachu.

## Pages

| page | contents |
|---|---|
| [The Let's Go cartridge and session](lgpe_session.md) | what the title is built from, the LDN passphrase and Pia game key, Pia header version 3, the session key, the station and clone protocols as a real session runs them, the gate that starts the game's own messages, and the four game messages of a trade |

## What works

A trade is complete against a retail Let's Go Pikachu, with this project as the joiner, and against
an emulated host over `ldn_mitm`: a Pokemon built here is in the retail save. Every layer runs:
association with the 64-byte passphrase, the session key, the version-3 Pia header, the 22-byte
message framing, the version-9 station connection handshake, the mesh join, the Sync Clock and RTT
protocols, the Clone Protocol through the take-over exchange that passes the game's `0x11b080` gate,
and the Reliable Protocol carrying the game's four message kinds: identity, offer, commit and result.
`pokeldn.lgpe.pb7` reads and writes the 232-byte box structure the offer and the result carry.

As a host, `bin/lgpe_host.py` advertises the title on LDN protocol 1 with the fixed session id; the
console finds it, joins, seats in the mesh and runs the clone protocol for as long as the session is
held. `docs/lgpe_session.md`.

## Unresolved

- A trade with this project as the host. The console joining a hosted session announces clone id 1,
  takes over the host's, and never publishes its own copy on clone type 2, so its game sends nothing
  (`lgpe_session.md`, "Where a retail console stops when we host"). The host runs the joiner's clone
  participant with its take-over corrections off, one take-over per clone and an acknowledgement
  carrying the peer's announcement clock; nothing has been hosted with them on.
- How the three-Pokemon link code becomes the password. Its CRC32 at application-data +4 was 0 on a
  session hosted with the code Pikachu, Pikachu, Pikachu, so the code does not reach the Pia
  password field. Where the game checks it is unread.
- What the game checks in an offered box structure. The one Pokemon traded in was a donor the game
  itself wrote, with the trainer id and original trainer changed; a structure built from nothing,
  an illegal move set, a species outside the Kanto set and a shiny are unmeasured.
- The three-byte value after the count in the `0xaN` clone messages. For a clone both stations hold
  it is the same on both sides; for clone type 3 id 0 the two stations send different values that
  match neither announcement, and what it is computed from is unread.
- The flag halfword in the game message header, `0x0000ff00` on every message seen. Nothing has
  varied it.
