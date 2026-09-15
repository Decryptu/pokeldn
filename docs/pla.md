---
title: Legends Arceus
nav_order: 8
has_children: true
---

# Legends Arceus

Pokemon Legends: Arceus (2022, title id `01001f5010dfa000`) is a native Switch title with Pia
statically linked into `main`. Nothing above the packet header has been read yet; no packet from a
console has been captured.

Addresses below are offsets into the decompressed `main` of update 1.1.1, as
`tools/switch/nso_read.py` lays it out (text `0x0..0x32a5690`, rodata from `0x32a6000`, data from
`0x401a000`).

## The wireless layer

| | value |
|---|---|
| Pia header version | 11, the wiki's Pia 6.16 to 6.23 band; a fourth band next to Sword's 4, BDSP's 9 and the GBA app's 15/16 |
| header size | 0x1C |
| GCM tag on the wire | 8 bytes, truncated from 16 |
| LDN passphrase | byte-identical to Sword/Shield's (the `HGhG` spelling; the wiki's Legends Arceus row has `HGHG` and does not match the binary) |
| Pia game key | `p1frXqxmeCZWFv0X`, the same ASCII literal as Sword/Shield and Scarlet/Violet |

The game key and the passphrase sit together in rodata at `0x3985308` and `0x3985319`, each
NUL-terminated.

The header initializer at `0x6f0744` stores the magic `0x32AB9864` at `+8` of its object and the
byte `0x0b` at `+0xc`; the validator at `0x6f07d0` checks the magic and `(byte & 0x7f) == 11`, then
requires the packet length minus 0x1C to be below 0x5a5. The wiki's 6.16 to 6.30 layout:

    0x00  4  magic 0x32AB9864, big-endian
    0x04  1  0x80 (encrypted) | version (0x7F) = 11
    0x05  2  destination variable id
    0x07  2  source variable id
    0x09  2  packet id
    0x0B  1  footer size
    0x0C  8  AES-GCM nonce
    0x14  8  AES-GCM tag, truncated from 16
    0x1C     ciphertext; the footer is outside the encryption in this band

No module in `pokeldn/ldn/` speaks version 11. `pia_connect.py` (15/16) is the nearest: 2-byte
variable ids and the 6.16 to 6.42 message header are shared, the packet header offsets and the
unencrypted footer are not.

## Unresolved

- The local communication id the console advertises, and the LDN protocol version. A passive
  capture of the console's local-trade screen (`tools/ldn/sniff.py`) gives both.
- Everything above the packet header: session key derivation for this band, the station handshake,
  and the game's own message layer.
