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

- A substituted greeting name on a console's screen
  ([The name in the greeting](bdsp_protocol.md#the-name-in-the-greeting)). How `StartupSessionJob`
  fills the own station's record at +0x480 from the startup setting is untraced.
- Whether a 0x08 to a console that has never recruited a battle faults it on hardware. The code
  writes through a null model, and no 0x08 has reached `SetNetData` on a console
  ([Being talked to](bdsp_protocol.md#being-talked-to)). Whether leaving the Union Room destroys the
  `UnionRoomManager` is unread (`UnionRoomManager$$OnDestroy` `0x1e4c540` exists; its caller is not
  known).
- Whether a retail console that is not the Grand Underground session host adopts a 0x61 from
  pokeldn. Every Underground session measured had the console as host, and pokeldn does not host an
  Underground session. A sender filter in the shared `NetUseManager` receive path was not searched.
- Where the Unity player takes `Screen.width` from. The 2D grid positions rest on it being the
  1280 x 720 default that `0x6062e8` keeps when `/Data/rawsettings` +0x1c is 0
  ([the protocol page](bdsp_protocol.md#the-grand-underground)); another source, such as the
  player settings in `globalgamemanagers`, has not been excluded.
- Whether any scene places a `UnionRoomManager` or a `UgNetworkManager` as a component. The code's
  only `AddComponent` of each is read; a scene-placed instance would live outside those paths.
