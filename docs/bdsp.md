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
- Record mixing, ball capsules and a battle lobby driven to the point where the console sends its
  record, its capsule and its six chosen Pokemon.
- A character walking on the Grand Underground floor, and the console's secret base read out.

## Pages

| page | contents |
|---|---|
| [Joining and the Pia layer](bdsp_session.md) | the advertisement, the passphrase, the seat, the packet format, the key hierarchy, the mesh handshakes, and hosting |
| [The game protocol](bdsp_protocol.md) | the 65 messages BDSP speaks, the Union Room, and controlling a character |
| [Trading](bdsp_trade.md) | the trade flow, the PB8, the save, and the disconnect penalty |

## Unresolved

- One payload never on the wire. Twelve of the 65 message structs hold a C# string, an array or a
  list; `netdata.OPAQUE` names them. The executable's `Il2CppTypeDefinitionSizes` decides the size
  and packing of all twelve; eleven have been on the wire and match (`room.MEASURED`). The twelfth,
  `NetDigGroupIdData` (0x29), has no sender in 1.3.0 ([the protocol page](bdsp_protocol.md)).
- The Session Protocol (0x94) sits above the reliable transport and has never carried a byte in any
  capture.
- Whether the console reads a `NetCharacterStateData` answer. The answers are accepted by the
  transport, land on the right stream with the right bytes, and have no observable effect.
- The name the game shows for a talked-to character. No `NetPlayerNameData` and no trainer card
  went out in the run that produced it.
- Where a ball capsule received in the exchange goes. The console applies it ("Seuls les sceaux
  que vous possédez ont été collés") and leaves the exchange; the player's collection did not
  show it on one look ([the protocol page](bdsp_protocol.md)).
- `NetDataSelectData`'s index. The two runs that swept it declined the conversation before the index
  could matter; it is unmeasured.
