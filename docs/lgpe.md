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
carrying the game's messages: identity, offer, commit, and kind 4, which follows the trade.
`pokeldn.lgpe.pb7` reads and writes the 232-byte box structure the offer and kind 4 carry.

Leaving is clean both ways. A joiner backs out with `--leave-after` the way a console does, and a
host answers the console's Retour, so the player lands on the menu with no error. The commit stage
of the host is pinned against a scripted console by `tests/test_lgpe_host_commit.py`, because a
host that gets it wrong leaves the console on its confirmation screen and its save's trade lock
set, refusing trades for ten minutes of counted play time, and ends it on the fatal
error screen. `docs/lgpe_session.md` has every layout.

## Unresolved

- The text of the fatal error message `0x191615296121e064` an aborted trade commit shows. It lives in
  the romfs message archives; extracting them from the Let's Go Pikachu NSP and finding the label
  whose FNV-1a-64 is that id settles it.
- How counted play time relates to wall time, and so how long the lock lasts on a clock. The rate of
  the gated call `0x13c944` and whether the frame period stays at 33.3 ms are unread. After an
  aborted commit, noting the play time P and trying Link Trade at P + 9 and P + 11 minutes with a
  wall stopwatch running measures both the lock and the rate.
- Why the console that refused a trade after a host answered its withdrawn vote with A 2 left the
  host's `0xa1` on clone type 4 unanswered, when its radio acknowledged every frame. `0x51c110`
  drops such a message silently in `0x522a60` while the sender's bit is in the `+0xc0` mask, and
  earlier at the destination check, the per-sender count filter or a length check; the message's own
  bytes (destination `0x0002`, count 69 after a highest earlier host count of 63) pass the first two
  for in-order delivery. What held the silence is unknown, and nothing in the capture shows the
  severity-4 error (`0x4d8a80`) that would give result 2 and the fatal error screen. An `0xa1` repeated until answered
  separates a pending mask (a later copy answered) from a message that never reaches the clone
  protocol (none answered); a second board sniffing the air records what arrived independently of
  the host's radio.
- A second trade in one session has not been run. By registration order its offers ride kind 4 and
  its commit kind 5, a third trade's kinds 6 and 7. The party-offer object that owned kind 2 is
  destroyed before the trade demo, so a peer that keeps offering on kind 2 and committing on kind 3
  after a first trade addresses channels the console has dropped. After a first trade a retail
  console published its state record (`4 3 1`, backing out) on the second clone of the host's next
  pair, clone 6 after clones 5 and 6 were announced, as the first round's votes rode clone 3. The
  captures end 4.6 to 11.4 s after the console's kind 4, so no second-round offer has been seen. A session kept after a first trade, with
  the player picking again, settles it: the console's offers on kind 4 and a kind 5 exchange.
- Whether a partner leaving during the sync save reaches the code 0xe abort. The pump fails when
  `+0x1e6` is 1 or less, but the recount runs only under the guards on `[s+0xd8]`, `[s+0xd4]` and
  `0x52abf0`, whose values in a trade are unread, and the local station's own record (the other
  callers of `0x5a9430`, `0x581f20` and `0x583b90`) is untraced.
- What calls the session's slots 11 to 13 (`0x349880`, `0x3498e0`, `0x349940`), and which results
  reach slot 10 at `0x4da38c` inside `0x4da294`.
- Whether the dispatcher's modes 1 and 2 are link battles. The reading rests on the scene they build;
  a capture of a link battle's session, with the mode word `+0x8c`, settles it.
- Whether game record 476 counts local trades and 477 trades made while the internet connection is
  up. `0x838800` picks 477 when `0x115860` is true; the chain that sets its byte `0x1614076`
  (`0x1157f0`, `0x115830`, `0x119a90`) and its callers beside `InternetConnectThread` are unread.
  Reading them settles it offline; the record's value in a save before and after a local trade
  settles it on a console.
