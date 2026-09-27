---
title: Brilliant Diamond and Shining Pearl
nav_order: 5
has_children: true
---

# Brilliant Diamond and Shining Pearl

Brilliant Diamond and Shining Pearl are built in Unity by ILCA. Pia is the game's own transport
and IL2CPP game code sits directly on it.

Measured against a French Shining Pearl, version 1.3.0, in the Union Room (Pokemon Center 2F, the
left attendant, the plain "yes") and in the Grand Underground.

## Status

Proven on retail hardware, end to end:

- LDN association and a seat in the console's session, needing only `prod.keys` and the title's LDN
  passphrase.
- Every packet decrypted, and the send path proven byte-exact against the console's own ciphertext.
- The Local Protocol, Mesh Station Protocol and Mesh Protocol handshakes; a station in the console's
  mesh; its round-trip timer answered; its reliable transport acknowledged in both directions.
- A character of pokeldn's own choosing walking in a retail Union Room, showing a trade emote, and
  running the game's own greeting dialogue with the player.
- A complete trade: the console opened its trade screen for that character, offered a Pokemon,
  accepted one pokeldn assembled, wrote its save, and offered the select window again.
- Hosting: a console entering the Union Room joins a room pokeldn hosts, draws its character, and
  completes a trade with it ([Hosting](bdsp_session.md#hosting)).
- A ball capsule composed by pokeldn exchanged in the Union Room: the console stores it in its
  collection with the seals the player has in stock ([the protocol page](bdsp_protocol.md)).
- Record mixing and a battle lobby driven to the point where the console sends its record and its
  six chosen Pokemon.
- A character walking on the Grand Underground floor, and the console's secret base read out.

## Pages

| page | contents |
|---|---|
| [Joining and the Pia layer](bdsp_session.md) | the advertisement, the passphrase, the seat, the packet format, the key hierarchy, the mesh handshakes, and hosting |
| [The game protocol](bdsp_protocol.md) | the 65 messages BDSP speaks, the Union Room, and controlling a character |
| [Trading](bdsp_trade.md) | the trade flow, the PB8, the save, and the disconnect penalty |

## Unresolved

- Whether a console acknowledges a reliable Session Protocol (0x94) message before the handler
  drops it. Its windows run the same receive and update functions as the game stream's, which a
  console acknowledges ([Joining and the Pia layer](bdsp_session.md#joining-the-mesh)); the ack
  emission itself is untraced and no 0x94 has been sent.
- Whether `07 0002 12 00`, sent after the console's greeting when the console's player approached
  the client's character, opens the trade. The greeting and its park on "one second!" have run on a
  retail console; the recruiter's yes has not been sent
  ([the protocol page](bdsp_protocol.md#the-console-approaching)).
- The texts of `DP_CHARACTERS_247` and `DP_CHARACTERS_206`, and a substituted greeting name on a
  console's screen. The path from a console's `IlcaNetSessionSetting.nameStringLanguage` into the
  PlayerInfo byte it transmits is untraced.
- Whether a 0x08 to a console that has never recruited a battle faults it on hardware. The code
  writes through a null model, yet the runs in
  [Being talked to](bdsp_protocol.md#being-talked-to) that sent `NetDataSelectData` did not crash:
  either that player had recruited a battle earlier in the visit, or the 0x08 arrived under a stale
  sequence id and was dropped. When a `UnionStateController` is recreated is unread.
- Whether a retail console that is not the Grand Underground session host adopts a 0x61 from
  pokeldn. Every Underground session measured had the console as host. Whether `UgNetworkManager`
  is recreated per Underground visit is unread.
- The 2D grid positions assume the grid's world scale is 1: `Initialize` divides world-space
  position differences by a local-space step, and the canvas scale was not read.
- Whether a console that backed out of a round (`NetDataReturnSelectData{1}`) waits for the
  partner's `{0}` before its player can pick again.
