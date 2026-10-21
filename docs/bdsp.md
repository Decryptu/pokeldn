---
title: Brilliant Diamond and Shining Pearl
nav_order: 5
has_children: true
---

# Brilliant Diamond and Shining Pearl

Brilliant Diamond and Shining Pearl are Unity titles by ILCA whose IL2CPP game code speaks directly
on Pia. The pages describe version 1.3.0, in the Union Room (Pokemon Center 2F, the left attendant,
the plain "yes") and the Grand Underground.

## Status

Working on retail hardware:

| feature | detail |
|---|---|
| a seat in the console's session | needs only `prod.keys` and the LDN passphrase; every packet decrypts; the send path matches the console's ciphertext byte for byte |
| transport | the Local, Mesh Station and Mesh Protocol handshakes, the RTT timer, the reliable transport in both directions |
| a character in the Union Room | walks, shows a trade emote, runs the game's greeting dialogue |
| trade | an assembled Pokemon accepted and saved; trades chain in one association ([Trading](bdsp_trade.md#the-completed-trade)) |
| hosting | a console entering the Union Room joins a hosted room and trades ([Hosting](bdsp_session.md#hosting)) |
| ball capsule | a composed capsule lands in the collection with the seals the player holds ([the protocol page](bdsp_protocol.md)) |
| record mixing, battle lobby | up to the console's record and its six chosen Pokemon |
| Grand Underground | a character walks on the floor; the console's secret base is read out |

## Pages

| page | contents |
|---|---|
| [Joining and the Pia layer](bdsp_session.md) | the advertisement, the passphrase, the seat, the packet format, the key hierarchy, the mesh handshakes, and hosting |
| [The game protocol](bdsp_protocol.md) | the 65 messages BDSP speaks, the Union Room, and controlling a character |
| [Trading](bdsp_trade.md) | the trade flow, the PB8, the save, and the disconnect penalty |

## Unresolved

- A substituted greeting name on a console's screen
  ([The name in the greeting](bdsp_protocol.md#the-name-in-the-greeting)).
- What a retail console shows when a 0x08 reaches it with no battle recruited. The code stores to
  address 0x18 with no null check and the game's module has no user exception handler
  ([The battle ladder](bdsp_protocol.md#the-battle-ladder)).
- Whether a retail console that is not the Grand Underground session host adopts a 0x61 from
  pokeldn. The common dispatch and the `UgNetworkManager` handler have no sender filter
  ([the protocol page](bdsp_protocol.md#the-grand-underground)).
