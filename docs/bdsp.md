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

- Whether a console acknowledges a reliable Session Protocol (0x94) message on its per-station
  window before the handler drops it. That an LDN session's joint-session job stays null rests on
  the two writers of session+0x70 found (`0x157c618`, `0x157cb54`); others were not enumerated
  ([Joining and the Pia layer](bdsp_session.md#joining-the-mesh)).
- Whether anything other than a received `NetCharacterStateData` writes a remote character's
  state, and the character's state before its first one.
- The console-initiated approach (a character at `{4, 1}`, the player pressing A facing it, the
  console's 0x63 answered with `64 0003 00 01 04`) has not been run against a retail console.
- Which PlayerInfo byte becomes the greeting name's language. If it is the byte at offset 122,
  `bin/bdsp_connect.py`'s default of 1 reads as Japanese, with a name limit of 6 and the Japanese
  font. Which station's cassette version `UnionWork.nowTargetCassetVersion` holds, and so which
  substitute name replaces a refused one, is unread. The replacement has not been measured on a
  console.
- Whether a `NetDataSelectData` (0x08) arriving with no battle recruitment model faults the
  console; the receiver does not test the model for null.
- Whether a console that is not the Grand Underground session host adopts a `NetDigTableData`
  (0x61) sent by pokeldn before its own table is ready.
- The ball-capsule 2D grid's extent beyond columns and rows -3..3 on the front; it comes from the
  UI layout ([the protocol page](bdsp_protocol.md)).
