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
`v131072`, SDK 5.4.151.0). Hardware measurements are against a French Let's Go Pikachu.

Local trading and battling ask both players for a link code: three Pokemon chosen in order from a
fixed set. The sessions here use Pikachu, Pikachu, Pikachu.

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
carrying the game's four message kinds: identity, offer, commit and result. `pokeldn.lgpe.pb7`
reads and writes the 232-byte box structure the offer and the result carry.

Leaving is clean both ways. A joiner backs out with `--leave-after` the way a console does, and a
host answers the console's Retour, so the player lands on the menu with no error. The commit stage
of the host is pinned against a scripted console by `tests/test_lgpe_host_commit.py`, because a
host that gets it wrong leaves the console on its confirmation screen and its save refusing trades
for half an hour. `docs/lgpe_session.md` has every layout.

## Unresolved

- How the three-Pokemon link code becomes the password. Its CRC32 at application-data +4 was 0 on a
  session hosted with the code Pikachu, Pikachu, Pikachu, so the code does not reach the Pia
  password field. Where the game checks it is unread.
- The three-byte value after the count in the `0xaN` clone messages. For a clone both stations hold
  it is the same on both sides; for clone type 3 id 0 the two stations send different values that
  match neither announcement, and what it is computed from is unread.
- The flag halfword in the game message header, `0x0000ff00` on every message seen. Nothing has
  varied it.
- The console sent fourteen kind-4 results, one per party slot, after one trade and a single one
  after another; what decides the count is unread.
