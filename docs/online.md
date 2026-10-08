---
title: Online trade
---
# Online trade

An online trade joins two players far apart. Each player's board hosts a local trade with their own
console; the two apps meet through public Nostr relays and pass each console's offered Pokemon to
the other. Each console sees an ordinary local trade with a partner whose Pokemon is the far
console's. No server belongs to the project: the relays are public infrastructure, and a relay only
ever handles encrypted events. Code: `pokeldn/online/`; the launcher flags are `--online` and
`--online-code`.

## The room

Two apps meet when they run the same game with the same code. The room is

    sha256("pokeldn online 1|<game>|<code or 'open'>")

as 64 hex digits. An empty code is the open room: anyone trading that game online without a code.
FireRed and LeafGreen share `frlg`, Scarlet and Violet share `sv`, and so on per catalog game. The
code is the console's own link code where the game has one, so a player types it once on the
console and once in the app. Eight digits give 10^8 rooms: anyone who types a code meets whoever
else typed it, as in the game itself.

## The relays

Every event is a Nostr event (NIP-01) of kind 21059, which lies in the ephemeral range 20000-29999:
a relay forwards it to current subscribers and stores nothing. Each event carries the tag
`["t", <room>]`, and an event for one app also `["p", <its signing key>]`. One subscription per
app asks for kind 21059 with the room's tag from ten seconds before it started.

Each session signs with a fresh secp256k1 key (BIP-340 Schnorr, `pokeldn/online/schnorr.py`,
checked against the 19 BIP-340 test vectors), so two sessions share nothing. An app publishes every
event to every relay it holds and drops a second copy of an event id.

| relay | one event per 2 s, 8 sent |
|---|---|
| relay.primal.net, relay.snort.social, offchain.pub, relay.nostr.net, nostr.oxtr.dev, nostr-pub.wellorder.net | 8 delivered |
| relay.damus.io | 4 delivered; rate-limits an address, then bans it for a while |
| nos.lol, nostr.mom | refused as rate-limited, none delivered |
| nostr.wine | refuses (paid relay) |

The first row is the default set; `POKELDN_RELAYS` (comma-separated URLs) replaces it.
offchain.pub refuses a burst from a key it does not know ("not in our web of trust") and takes
paced events. Over these relays two apps pair 0.4 s after the second one arrives, and a 344-byte
record crosses in about 0.15 s.

A retail Scarlet and a retail Violet, each hosted by its own board, traded through the relays:
each console showed the other's offer, both confirmed, and each received the other's Pokemon with no
error on either screen. A retail FireRed and a retail LeafGreen did the same: both parties crossed
pair by pair, mail and ribbons included, in about 4 s, and after the trade the re-exchanged parties
reached the trade menu again.

Two consoles on one desk find each other directly: a Scarlet or Violet searching with the same code
as the other, a FireRed whose player chooses Become Leader. For such a test each console takes its
own local code (or Join Group on a board's group) and `--online-code` puts both boards in one room.

## Meeting

Every event's content is AES-256-GCM under the room key `sha256("pokeldn room key|" + room)`. Inside:

| message | sent | content |
|---|---|---|
| `here` | every 2.5 s, to the room | protocol 1, X25519 public key, trainer name, app version, busy |
| `invite` | to one app | trainer name |
| `yes` / `no` | the answer | trainer name |
| `bye` | to an app that is not one's partner | why |

An app invites only a free app whose signing key is greater than its own, the one it has seen
longest, and holds one invite at a time for up to 6 s; an app with an invite out answers any other
invite with `no`. A refused or unanswered invite skips that app for 10 s. Relays do not keep order,
so the partner's first channel message can arrive before its `yes`; it counts as the `yes`.

## The channel

A paired app's messages to its partner are sealed twice: the outer AES-GCM under the room key holds
the sender's X25519 key and an inner AES-GCM under

    sha256("pokeldn pair|" + room + "|" + sorted("<signing key>:<x25519 key>" of both) + shared secret)

Each message carries `s`, its number, and `a`, the highest number received in order. Unacknowledged
messages are sent again every 2 s; an ack goes out 0.3 s after a message arrives, so one ack covers
what arrives together. A ping every 4 s keeps the pair; a partner silent for 45 s is lost. A partner
lost before anything was offered on either side is replaced: the app looks for someone else.

| message | meaning |
|---|---|
| `hello` | trainer name and app version, once |
| `offer` | trade *r*: the local console offers this record (base64) |
| `withdraw` | trade *r*: the local console took its offer back |
| `accept` / `unaccept` | trade *r*: the local console confirmed, or took the confirmation back |
| `refused` | trade *r*: the partner's app refused our record, and why |
| `done` | trade *r* completed on the local console; the next trade is *r* + 1 |
| `ping`, `bye` | keepalive; leaving |

## What crosses

Only a console's offered record and the trade's state cross; never keys, saves or files. Each app
checks a received record with PKHeX before its console sees it (`pokeldn.online.session.checker`):

| PKHeX finds | the record |
|---|---|
| it cannot parse it, the checksum is wrong, the species or form is absent from the game, a move, item or ball id lies past the game's tables | refused; the sender's app shows why |
| a held item or move the game never released ("unreleased"; Sword's items stop at 1607) | refused |
| any other legality flag | offered, with PKHeX's flag shown to the receiving player |

A record a retail console traded can fail PKHeX's legality analysis, so a flag alone refuses
nothing.

## In a launcher

A host launcher run with `--online` offers nothing of its own: its offer is the partner's console's.

1. The local console offers: the record goes to the partner (`offer`).
2. The partner's record arrives: the launcher offers it to the local console. A withdrawn partner
   offer is withdrawn from the console.
3. The local console confirms: `accept`. The launcher sends its own confirmation only once both
   consoles have confirmed, so neither console passes the point of no return alone.
4. The trade completes: `done`, and the next trade starts from the box.

| title | our offer | the console takes its offer back | we take ours back | our confirmation, sent once both consoles confirmed |
|---|---|---|---|---|
| FireRed / LeafGreen | the partner's party blocks (three of 200 bytes, mail 220, ribbons 40), each sent as the console's own arrives; `SET_MONS_TO_TRADE` carrying the partner's cursor | `READY_CANCEL_TRADE` (answered `PLAYER_CANCEL_TRADE`), `REQUEST_CANCEL` | `PLAYER_CANCEL_TRADE` | `START_TRADE` |
| Let's Go | kind 2 with the partner's 232-byte record, answering the console's step | a withdrawn vote (state 2), a leave (state 4) | none | A 2 on the offered clone, the trailing word moved to 2 |
| Sword / Shield | 20030 with box command 1; the 0x84 snapshot's party slot keeps the console's own Pokemon | box command 2 (offer), 5 (confirmation) | box command 2 | box command 4 |
| Brilliant Diamond / Shining Pearl | 0x13 answering the console's | 0x45 `{1}` | 0x45 `{1}` | 0x21 `{0, 2}`; the security phase stays automatic |
| Legends Arceus | selector 4 answering the console's, under its counter; its showings (selector 2) answered with the partner's record once known | selector 6 | none | the mirror of the console's selector 5 |
| Scarlet / Violet | kind 2 with the partner's 348-byte body | kind 4 `8000040100` | kind 4 | kind 3 |
| Legends Z-A | a preview of the partner's pick, then the pick 0.5 s later | `0103` | `0103` under the next round | `0102`, then `0104` |

FireRed and LeafGreen exchange whole parties when the players sit down, so each console sees the
partner's party, as in a trade between two cartridges. Each host requests a party pair from its
console and holds its own block until the partner's console sent the same pair; the console waits
for both blocks with no timer [trade.c:1478], so neither host waits on the other. A party block
reaches the console only when PKHeX reads every Pokemon in it. The pick crosses as `pick` (the
console's cursor) before the offered record.

A partner that leaves, or goes silent for 45 s, counts as one that took its offer back: each host
withdraws the partner's Pokemon from its console, unless the trade is past its point of no return.
A FireRed or LeafGreen leader can only answer what its follower does, so a console whose partner
left gets `PLAYER_CANCEL_TRADE` ("Canceled", back to the menu) for its pick and for every later
pick, the answer of a leader that chose Cancel [trade.c:1712]; the menu's Cancel then leaves. A
party exchange the partner left half-way finishes with an empty party. A player who chooses Cancel
at the menu tells the partner at once. On a retail FireRed and LeafGreen pair: one player picked, the other
cancelled and left; the first console showed the cancel message, returned to the menu, and its
Cancel left the room.

A Sword's chained trades already offer records that differ from the snapshot's slot
([Sword trades](swsh_trade.md)), and the exchanged record is content 50's.

## Unresolved

- How each console answers a host taking its offer back while the console holds it: a Sword's box
  command 2 (a Sword hosting console whose player was on the confirmation screen began leaving four
  seconds after a joiner sent command 1 then 2), a Scarlet's kind 4, a Z-A's `0103`, a Brilliant
  Diamond's 0x45 after the console's pick. Let's Go and Legends Arceus hold instead.
- Whether a Z-A takes a pick with no preview sent before its own pick, and whether a Legends Arceus
  takes a second selector 4 over one it holds.
- How long a retail console waits at the box for the partner's offer and confirmation, beyond a
  minute.
