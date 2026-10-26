---
title: Online trade
---
# Online trade

An online trade joins two players far apart: each board hosts a local trade with its own console,
and the two apps pass each console's offered Pokemon through public Nostr relays, which only see
encrypted events. Code: `pokeldn/online/`; launcher flags `--online` and `--online-code`.

## The room

Two apps meet when they run the same game with the same code:

    room = sha256("pokeldn online 1|<game>|<code or 'open'>")     64 hex digits

Paired versions share a game key (`frlg`, `sv`). The code is the console's own link code where the
game has one. Two consoles on one desk find each other directly; to test on one desk, give each
console its own local code and put both boards in one room with `--online-code`.

## The relays

Every event is a NIP-01 event of ephemeral kind 21059, tagged `["t", <room>]` and, for one app,
`["p", <its signing key>]`. Each app subscribes to kind 21059 with the room's tag from 10 s before it
started, publishes to every relay and drops duplicate event ids. Each session signs with a fresh
secp256k1 key (BIP-340, `pokeldn/online/schnorr.py`).

| relay | 8 events, one per 2 s |
|---|---|
| relay.primal.net, relay.snort.social, offchain.pub, relay.nostr.net, nostr.oxtr.dev, nostr-pub.wellorder.net | 8 delivered; the default set |
| relay.damus.io | 4 delivered, then bans the address for a while |
| nos.lol, nostr.mom | none (rate-limited) |
| nostr.wine | refuses (paid) |

`POKELDN_RELAYS` (comma-separated URLs) replaces the default set. offchain.pub refuses a burst from an
unknown key and takes paced events. Two apps pair 0.4 s after the second arrives; a 344-byte record
crosses in about 0.15 s.

### Stored events

Measured on relay.primal.net, relay.nostr.net, nostr.oxtr.dev, nos.lol, nostr.mom, offchain.pub and
nostr-pub.wellorder.net:

| event | result |
|---|---|
| from a fresh key | accepted and served back |
| 30402 with a NIP-40 `expiration` | served until expiry, not after |
| 30402 republished with the same `d` | only the newer one served within a minute |
| kind 5 naming a 30402 | only the kind 5 served within a minute |
| kind 1059 read by its `p` key | served by six; relay.nostr.net demands AUTH and refuses it |

## Meeting

Every event's content is AES-256-GCM under `sha256("pokeldn room key|" + room)`.

| message | sent | content |
|---|---|---|
| `here` | every 2.5 s, to the room | protocol 1, X25519 key, trainer name, app version, busy |
| `invite` | to one app | trainer name |
| `yes` / `no` | the answer | trainer name |
| `bye` | to a non-partner | why |

An app invites only the longest-seen free app whose signing key is greater than its own, one invite
at a time for up to 6 s, and answers other invites `no` meanwhile. A refused or unanswered invite
skips that app for 10 s. A partner's first channel message counts as its `yes`.

## The channel

Partner messages carry, inside the room-key layer, the sender's X25519 key and an inner AES-GCM under

    sha256("pokeldn pair|" + room + "|" + sorted("<signing key>:<x25519 key>" of both) + shared secret)

Each carries `s`, its number, and `a`, the highest received in order. Unacknowledged messages are
resent every 2 s; acks go 0.3 s after arrival; pings every 4 s. A partner silent for 45 s is lost,
and replaced if nothing was offered yet.

| message | meaning |
|---|---|
| `hello` | trainer name and app version, once |
| `offer` / `withdraw` | trade *r*: the local console offers this record (base64), or took it back |
| `accept` / `unaccept` | trade *r*: the local console confirmed, or took it back |
| `refused` | trade *r*: the receiver refused the sender's record, and why |
| `done` | trade *r* completed; the next is *r* + 1 |
| `ping`, `bye` | keepalive; leaving |

## What crosses

Only the offered record and the trade's state. PKHeX checks a received record before the console
sees it (`pokeldn.online.session.checker`):

| PKHeX finds | the record |
|---|---|
| unparseable, bad checksum, species or form absent from the game, an id past the game's tables | refused, with the reason shown to the sender |
| an unreleased item or move (Sword's items stop at 1607) | refused |
| any other legality flag | offered, flag shown to the receiver |

## In a launcher

A host launcher with `--online` offers the partner's console's record. The local console's offer
goes out as `offer`; the partner's is offered to the local console; the launcher confirms only once
both consoles confirmed; `done` starts the next trade from the box.

| title | launcher's offer | console takes its offer back | launcher takes its back | launcher's confirmation |
|---|---|---|---|---|
| FireRed / LeafGreen | the partner's party blocks (three of 200 bytes, mail 220, ribbons 40), each sent as the console's own arrives; `SET_MONS_TO_TRADE` with the partner's cursor | `READY_CANCEL_TRADE` (answered `PLAYER_CANCEL_TRADE`), `REQUEST_CANCEL` | `PLAYER_CANCEL_TRADE` | `START_TRADE` |
| Let's Go | kind 2 with the partner's 232-byte record, answering the console's step | a withdrawn vote (state 2), a leave (state 4) | none | A 2 on the offered clone, the trailing word moved to 2 |
| Sword / Shield | 20030 with box command 1; the 0x84 snapshot's party slot keeps the console's own Pokemon | box command 2 (offer), 5 (confirmation) | box command 2 | box command 4 |
| Brilliant Diamond / Shining Pearl | 0x13 answering the console's | 0x45 `{1}` | 0x45 `{1}` | 0x21 `{0, 2}`; the security phase stays automatic |
| Legends Arceus | selector 4 answering the console's, under its counter; selector 2 showings answered with the partner's record once known | selector 6 | none | the mirror of the console's selector 5 |
| Scarlet / Violet | kind 2 with the partner's 348-byte body | kind 4 `8000040100` | kind 4 | kind 3 |
| Legends Z-A | a preview of the partner's pick, then the pick 0.5 s later | `0103` | `0103` under the next round | `0102`, then `0104` |

FireRed and LeafGreen exchange whole parties. Each host holds its own block until the partner's
console sent the same pair; the console waits with no timer [trade.c:1478]. A block reaches the
console only when PKHeX reads every Pokemon in it. The cursor crosses as `pick` before the record.

A partner that leaves or goes silent 45 s counts as a withdrawal, unless the trade is past its point
of no return. A FireRed or LeafGreen console whose partner left gets `PLAYER_CANCEL_TRADE` for every
pick [trade.c:1712]; a half-done party exchange finishes with an empty party. On Sword the exchanged
record is content 50's ([Sword trades](swsh_trade.md)).

## The GTS

The GTS trades banked Pokemon between players never online together: a player lists a Pokemon from
the [bank](gui.md#the-bank) against up to three wanted species, a level range and optionally a shiny, another answers with one of
theirs, and the lister's app trades when next open. Code: `pokeldn/online/gts.py`,
`pokeldn/app/gts.py`, the app's GTS page.

| event | kind | signed by | content |
|---|---|---|---|
| listing | 30402 (NIP-99), `d` a random id | a per-listing key | JSON: protocol 1, game, the Pokemon as PKHeX reads it, the record's SHA-256, `wants` and `also` (below), trainer name, status, winning offer |
| offer | 1059, `p` the listing key | a per-offer key | sealed: the listing's `d`, game, record, trainer name |
| answer | 1059, `p` the offer key | the listing key | sealed: offer id and the listed record, or a refusal and why |
| deletion | 5 (NIP-09) | the named event's key | none |

A listing is tagged `pokeldn-gts`, `pokeldn-gts-has-<species>` and `pokeldn-gts-wants-<species>` for each wanted species,
carries NIP-99's `title`, `summary`, `status`, `published_at`, and expires (NIP-40) after 30 days. A
sealed body is AES-256-GCM under `sha256("pokeldn gts|" + x)`, x the ECDH x coordinate
(`schnorr.shared_x`). Every stored event's id and signature are checked.

A want is `{"species", "name", "min_level", "max_level"}`, plus `"shiny": true` when only a shiny
answers. `wants` holds the first; `also`, present only with more than one, holds up to two more, and an
offer matching any one of them answers. Both fields are additions to protocol 1: an app from 0.40.0 or
earlier ignores them, shows a listing as asking for its first want alone, and an offer it sends that
misses the shiny requirement is refused by the lister's app and returns.

| step | what happens |
|---|---|
| deposit | the Pokemon must be legal; it leaves the bank and the listing is published |
| offer | legal and matching one want's species, levels and shiny requirement; it leaves the bank, sealed to the listing key; one app holds one waiting offer per listing, which stays open to other players' offers until the lister's app answers; the page marks it with a clock |
| the lister's app opens | stored offers are answered oldest first; the first valid one is traded, the rest refused |
| a trade | the answer carries the listed record; the listing is republished as traded; the received record is banked |
| the offering app opens | the record is checked against the listing's SHA-256 and banked; a refusal, a lost race or a withdrawn listing returns its own Pokemon; it deletes its offer |
| a listing ends | after 30 days its Pokemon returns; an offer's returns once relays have sent every stored answer one hour after the end |
| taken down | republished as withdrawn; its Pokemon returns; later offers are refused |

Each listing and offer is a folder in `Documents/pokeldn/GTS` (`POKELDN_DATA/GTS` when set) holding
`state.json` (secret key, signed events, answers sent) and the record. An answer is written before it
is published and every live event is resent to each relay that connects. Finished folders are
deleted after 60 days. A round takes about 30 s.

The relays are those of [Stored events](#stored-events); `POKELDN_GTS_RELAYS` replaces them.
A modified app can keep an offered Pokemon or list one it does not hold; the SHA-256 shows it only
afterwards. A fair exchange with no trusted third party is impossible (Pagnia and Gaertner, 1999).

## Unresolved

- How long a relay keeps an event beyond 24 hours, or one with no expiration.
- How a console answers a host taking its offer back while it holds it: Sword box command 2 (a
  hosting Sword on the confirmation screen began leaving 4 s after command 1 then 2), Scarlet kind 4,
  Z-A `0103`, Brilliant Diamond 0x45 after the console's pick. Let's Go and Legends Arceus hold.
- Whether a Z-A takes a pick with no preview, and whether a Legends Arceus takes a second selector 4.
- How long a retail console waits at the box for the partner, beyond a minute.
