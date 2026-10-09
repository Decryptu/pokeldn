# Scarlet/Violet Pia host identity

## Result

The raid host has three distinct identities. They are serialized in different
protocol layers and are not copies of one another:

1. The six-byte Wi-Fi AP MAC appears in LDN network metadata.
2. Pia derives its eight-byte constant station ID from that MAC as
   `mac[2], mac[4], mac[5], mac[3], mac[1], mac[0], 0, 0`.
3. The Session `PlayerInfo` contains an independent 16-byte player ID.

The two retail Scarlet/Violet player IDs available in the controlled raid
capture are:

```text
10 00 36 df 3a 8d 57 68 7a 53 61 85 5a 63 77 a1
10 00 96 e8 aa 85 7f e0 be 9f e5 3f 54 4f ea b2
```

Both use a fixed `10 00` prefix followed by 14 apparently opaque bytes. The
Session parser treats the complete value as a 16-byte blob. It has no checksum
or MAC field on the wire.

Searching every decompressed record in both the 46-record retail raid-host
identity and the bundled application identity found no occurrence of either
retail player ID, either station MAC, or either Pia constant ID. The application
record stream is therefore not cryptographically or bytewise bound to these
network identities.

## Ghidra findings

Addresses refer to Violet 4.0.0 at image base `0x7100000000`.

- `FUN_710092faac` initializes `nn::account`, opens the selected user, and
  writes the user's 16-byte `nn::account::Uid` to `DAT_71047351f8`.
- `FUN_710092d224` copies that UID into the game's save/runtime initialization.
- No direct reference from that UID global reaches the Pia Session writer.
- `FUN_7101859f88` (InitializeLdn), `FUN_710185b8bc` (StartupSession), and
  `FUN_710185a5d0` (CreateSession) do not accept or copy a 16-byte player ID.
  The CreateSession path builds the game's session payload and invokes the Pia
  session object; identity construction remains below that boundary.
- `FUN_71006a7268`, reached by
  `LdnBackgroundProcessJob::StartUpdateHostPlayerName`, copies only the host
  name. It does not install or regenerate the player ID.
- Pia 6.20.1's Session `PlayerInfo` serializes the player ID as an opaque
  16-byte field, followed by the name length, encoding, and name. There is no
  checksum, MAC, account UID, or type discriminator beside the 16 bytes.
- `nn::oe::GetPseudoDeviceId` is used by unrelated telemetry/Titan setup paths;
  the observed call sites stringify it and do not establish it as the Session
  player-ID source.
- `FUN_710070c090`, in Pia-adjacent LDN code, seeds `nn::util::TinyMt`, emits
  four random 32-bit words, and XORs the resulting 16 bytes with an internal
  16-byte value at object offset `+0x238`. It is a credible identity/nonce
  candidate, but it is installed through a stripped vtable and has not been
  connected to the Session `PlayerInfo` writer. It is therefore evidence that
  Pia constructs opaque values internally, not proof of the player-ID formula.

Together, the call boundary and wire layout show that Scarlet/Violet does not
derive this value in its LDN session setup. These findings also rule out the MAC
and the application identity records as bytewise inputs to the player ID. They
do not prove why both SV capture values start with `10 00`. (A separate Pia
capture in the repository contains a `10 02` value, so `10 00` is not a
protocol-wide invariant.) Live testing subsequently showed that arbitrary
`10 00` plus 14 random bytes is rejected before the Session type-6 ACK, proving
that the suffix is not unconstrained despite the opaque wire representation.

## Implemented synthetic identity

`sv_raid_host.py` and the `sv_join.py --raid-guest` path now construct a
donor-free network/Session identity unless the caller overrides it:

- MAC: six random bytes with the multicast bit cleared and the locally
  administered bit set;
- Pia constant ID: derived automatically from that MAC by the existing Session
  code;
- player ID: Pia's anonymous/local value
  `00 00 00 00 00 00 00 01 00 00 00 00 00 00 00 00`;
- Pia player name: `POKELDN`;
- game lobby name: record 1 of the capture-backed application identity is
  decompressed, rewritten to UTF-16LE `POKELDN`, and recompressed. This is the
  name Scarlet/Violet actually displays in the raid lobby.

The automatic values eliminate reuse of the captured console's MAC and player
ID. For controlled experiments, `--mac`, `--host-player-id`, and
`--host-player-name` accept explicit values.

## Live validation

The controlled identity tests held the same locally administered MAC constant:

1. Random `10 00` ID: retail joined Wi-Fi and sent its Session join, but
   deauthenticated immediately after the host station list without sending the
   type-6 ACK.
2. Captured host ID: retail ACKed the station list and reached `battle_93`.
3. Pia anonymous/local ID: retail also ACKed the station list, accepted the
   generated bootstrap, reached `load_6e`, `load_73`, and `battle_93`, and the
   host completed its normal sequence-20 handoff. There were 234 authenticated
   datagrams and zero authentication failures.

This proves the synthetic MAC/constant-ID pair and anonymous player ID are
accepted together by retail Scarlet/Violet without a captured identity donor.
The displayed host participant name was also confirmed as `POKELDN`, proving
that rewriting both the Pia name and game identity record 1 reaches the UI.

The Join Raid preset now uses the same identity construction. Its capture still
supplies timing, the 46-record application identity, and lobby messages, but it
no longer supplies the runtime MAC or Session player ID. A live test against
retail lobby 4216 used synthetic MAC `ae:fe:0f:02:b5:4f`; the retail host
accepted the anonymous player ID in its station update, completed the raid
bootstrap, reached `battle_93` at reliable sequence 16, and accepted the planned
guest disconnect. All 252 received datagrams authenticated successfully.

## Next validation

1. Confirm the displayed participant name in additional Join Raid runs if the
   configured trainer name changes.
2. Capture additional retail-generated IDs if the authenticated `10 xx` format
   itself needs to be reproduced in the future.
