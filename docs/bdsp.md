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

- Whether `07 0002 12 00`, sent after the console's greeting when the console's player approached
  the client's character, opens the trade. The talker's receive path has no state test and leads to
  `TransitionTradePoke` ([the protocol page](bdsp_protocol.md#the-console-approaching)); the
  recruiter's yes has not been sent. Unread: whether anything between the 0x64 and the 0x07 writes
  `onlinePlayerSelectState` or `targetStationIndex`, and whether trade message 9 or 10 closes by
  itself or waits for A. The capture that settles it shows the console's ack moving past the 0x07's
  own sequence id (the 0x07 under the id after the 0x64's, never the 0x64's), then its
  `NetDataTradeTranerData` (0x24).
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
- The 2D grid positions assume the grid's world scale is 1: `Initialize` [`0x1e909b0`] divides
  world-space position differences by a local-space step. The 1.3.0 `/Data/rawsettings` u32 at +0x1c
  is 0. Unread: the Unity player's read of that file (`0x2c16f8..0x2c1758`, into `0x4eed08c`) and its
  default-resolution switch (`0x6062e8`, byte table `0x3deab6c`, handlers `0x2c2a1c` and `0x2c2af0`);
  the `Canvas` and `CanvasScaler` fields above each grid in the `uiresidentwindow` prefabs (`Seal`,
  `SealTemplate`); `UIManager$$ScreenScaled` `0x1bf7c40`; and which of `Initialize`'s two step
  branches a retail view takes (cell size plus spacing, or `Rect$$get_size` at `0x1e90b40`).
- Whether a console that backed out of a round (`NetDataReturnSelectData{1}`) waits for the
  partner's `{0}` before its player can pick again, and what a `{0}` arriving after the re-pick
  does. The reading that settles it: `onCancelSelect` `0x1c28620` and `BoxWindow$$ToNextPhase`
  `0x2125020`, the phase test in `ReciveReturnSelectPoke` (`0x1c280fc`), and what
  `PokeSelectWait` `0x1c26070` and `UnionTradeManager$$RecivePokeData` `0x1c33e80` wait on. On a
  console: a hosted trade in which the player backs out with B on the full-screen view and picks
  again, with no `{0}` sent; the capture shows its `45 0001 01`, then whether a second
  `NetTradePokeData` follows.
