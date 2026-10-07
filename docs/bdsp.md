---
title: Brilliant Diamond and Shining Pearl
nav_order: 5
has_children: true
---

# Brilliant Diamond and Shining Pearl

Brilliant Diamond and Shining Pearl are built in Unity by ILCA, with IL2CPP game code directly on
Pia.

Measured against a French Shining Pearl, version 1.3.0, in the Union Room (Pokemon Center 2F, the
left attendant, the plain "yes") and in the Grand Underground.

## Status

Working on retail hardware:

- A seat in the console's session with only `prod.keys` and the LDN passphrase; every packet
  decrypted; the send path byte-exact against the console's own ciphertext.
- The Local, Mesh Station and Mesh Protocol handshakes, the RTT timer and the reliable transport
  in both directions.
- A character walking in a retail Union Room, showing a trade emote, and running the game's own
  greeting dialogue with the player.
- A complete trade: the console's offer, an assembled Pokemon accepted, the save written; trades
  chain in one association ([Trading](bdsp_trade.md#the-completed-trade)).
- Hosting: a console entering the Union Room joins a room pokeldn hosts, draws its character, and
  completes a trade with it ([Hosting](bdsp_session.md#hosting)).
- A composed ball capsule exchanged in the Union Room; the console stores it in its collection with
  the seals the player has in stock ([the protocol page](bdsp_protocol.md)).
- Record mixing and a battle lobby, up to the console's record and its six chosen Pokemon.
- A character walking on the Grand Underground floor, and the console's secret base read out.

## Pages

| page | contents |
|---|---|
| [Joining and the Pia layer](bdsp_session.md) | the advertisement, the passphrase, the seat, the packet format, the key hierarchy, the mesh handshakes, and hosting |
| [The game protocol](bdsp_protocol.md) | the 65 messages BDSP speaks, the Union Room, and controlling a character |
| [Trading](bdsp_trade.md) | the trade flow, the PB8, the save, and the disconnect penalty |

## Unresolved

- A substituted greeting name on a console's screen
  ([The name in the greeting](bdsp_protocol.md#the-name-in-the-greeting)). How `StartupSessionJob`
  fills the own station's record at +0x480 from the startup setting is untraced.
- Whether a 0x08 to a console that has never recruited a battle faults it on hardware. The code
  writes through a null model; no 0x08 has reached that path, because those sent went out under
  sequence ids the reliable window had already seen ([The battle
  ladder](bdsp_protocol.md#the-battle-ladder)).
- Whether a retail console that is not the Grand Underground session host adopts a 0x61 from
  pokeldn; the Underground sessions measured had the console as host, and pokeldn does not host one.
  The common dispatch and the `UgNetworkManager` handler have no sender filter
  ([the protocol page](bdsp_protocol.md#the-grand-underground)).
- What makes a console in the Union Room stop advertising with no change on screen
  ([Taking a seat](bdsp_session.md#taking-a-seat)).
