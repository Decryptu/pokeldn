---
title: Max Raid Battles
parent: Sword and Shield
nav_order: 5
---

# Max Raid Battles

A local Max Raid Battle is a Sword/Shield session of up to four stations on LDN scene 60006. The
host opens it from a den with "Invite Others"; a guest finds it in its Y-Comm list and joins with
"Start Battle" over the host's name. The lobby runs on the reliable broadcast protocol 0x80, the
battle on 0x7C. `bin/swsh_connect.py --scene 60006 --raid-join --offer-slot N` takes a guest seat
in a console's lobby; the lobby shows it with the chosen Pokemon.

## The network

| field | value |
|---|---|
| LDN scene id | 60006 (65535 in the overworld) |
| participants | 1 of 4 when opened |
| advertise data byte `0x97` | `0x11` |
| Pia session maximum | 4 (`0x0110e5e0`, called from the den lobby at `0x01031c74`) |

The den lobby's code sits among `View_NestHole`, `StateGuestReady` and `StateHostReady`
(`0x0102aba4..0x010370cc`). Dynamax Adventures match through `ChikaMatchingState*`
(`0x00bd1978..0x00bda158`), which calls the same Pia session maximum from `0x00bd9b30`.

A guest's Y-Comm list leaves out a raid whose advertisement carries the guest's own trainer: two
consoles with the same save, or the same user id and trainer id, do not see each other's raids.

## The lobby messages

Every lobby message is id 2000, `net_contents.nesthole.protocol_buffers.NestholeAsyncDataHolder`
(descriptors at `0x1bfde43` and `0x20677b0` in `main`). Each field is a holder with one `bytes`
field 1.

| field | name | size | content |
|---|---|---|---|
| 1 | NestholeTimeLimit | 4 | u32 seconds left; the host sends it three times a second |
| 2 | NestholePlayerInfo | 40 | 8 zero bytes, u32 (0x11 retail Sword, 0x12 emulated Shield), UTF-16 name in 13 characters, `00 03` |
| 3 | NestholeBattleReady | 16 | byte 8 is 1 once the player pressed ready; byte 12 is 1 once the battle starts |
| 4 | NestholeSelectPokemon | 352 | 8 zero bytes, then the chosen Pokemon as an encrypted party PK8 (0x158) |
| 5 | NestholeBattleStart | 32 | the participants' station ids |
| 6 | NestholeBossPokemon | 364 | the boss |
| 7 | NestholeRewards | 120 | u32 pairs: item id, count |
| 8 | NestholeBattleSeed | 16 | the battle's seed |

PlayerInfo goes out zlib-compressed with a 4 KB window (header `48 4b`) under reliable flag 0x10;
the others go out plain. `pokeldn/swsh/raid.py` builds fields 2, 3 and 4; its output equals an
emulated guest's bytes.

## The guest's sequence

Recorded between two emulated Shields, a whole raid won:

1. The snapshot exchange on 0x84, as in a link trade.
2. PlayerInfo, BattleReady (zero) and SelectPokemon on 0x80 port 0, sequences 1 to 3.
3. BattleReady with byte 8 set when the player presses ready.
4. Once every player is ready, the host sends BattleStart, its SelectPokemon again, BossPokemon,
   Rewards, BattleSeed and BattleReady with bytes 8 and 12 set.
5. The guest answers with its SelectPokemon again, then BattleReady with bytes 8 and 12 set.
6. The battle starts on 0x7C: sync ping 80 on port 0, framework messages 40000 on port 1, then
   10000 and 20000 messages on port 0 for every turn.

Against a retail Sword host, a guest that stops after BattleReady with byte 8 set leaves the host's
player on "Connexion en cours" after the host's own ready, ending in error 2-ALZAA-0016.

## The battle

The host runs the battle; a guest answers on 0x7C. `pokeldn/swsh/raid_battle.py` is the guest's side,
built from an emulated Shield guest; `bin/swsh_connect.py --raid-join` with it fought a whole raid as
a guest of an emulated host, to a won raid.

Before the battle, from the mesh join, the guest runs SyncClockProtocol 0x1C (a request a second)
and sends one ClockProtocol 0x77 request (`00` x16 then `00 6f`), both to destination bitmap 1.

| port | message | the guest |
|---|---|---|
| 0 | sync 80: ping, pingReply, pingSynced | answers ping with ping and pingReply, pingSynced with pingSynced |
| 1 | 40000, content 0's framework: field 2 base (10000 or 20000, absent for 0), 3 station constant id, 4 clock, 5 body | after its pingSynced sends three base-10000 / base-20000 pairs (bodies `00000000`, `000018fc`), then mirrors each host base-20000 body under its own station id |
| 0 | 10000, field 3 {1 station, 2 slot, 3 version} | sent once the host lists its own seat (base 0, 16-byte body: constant id, slot, version byte 0x6e) |
| 0 | 10000, field 1 empty | sent after the host's base-8 message (24-byte body, the battle's seed) |
| 0 | 20000, field 1 {1 sender, 2 slot, 3 counter, 4 data} | answers every host command |
| 0 | 20000, field 3 {1 state, 2 slot} | sends {1: 2, 2: slot} before its action |

A host command's data opens with four u16: serial, type, length, a tag. The guest answers with the
same serial, type and tag, length 4 and four zero bytes, except:

| type | the guest sends |
|---|---|
| 0x02 | the state message, then its action: serial, 0x02, 0x58, tag, then 88 bytes |
| 0x21 | the end: sender 1, data `0000 1e00 0000 2f00` |

Types seen from a host: 0x01, 0x0d, 0x07 (123 bytes), 0x0e, 0x02, 0x10 (47 bytes), 0x09 (the turn's
log, zlib, 0.4 to 2.4 KB), 0x04, 0x11 and 0x0a after the guest's Pokemon fainted, 0x21 at the end.

### The action

The 88-byte action is eleven 8-byte entries. Only entry 2 changed between four moves of one guest:
as a little-endian u24 it is `move id << 13 | target << 8 | 0xc1`.

| move | entry 2 | target |
|---|---|---|
| Pound (1) | `c1 28 00` | 8 |
| Bind (20) | `c1 88 02` | 8 |
| Growl (45) | `c1 a2 05` | 2 |
| Water Gun (55) | `c1 e8 06` | 8 |

Growl hits every foe and carries target 2; the single-target moves carry 8. A turn on which the
guest could not act sent entry 2 as zero. `raid_battle.action(move, target)` builds it;
`--raid-move N` picks the move slot of the guest's Pokemon.

The 0x7C acknowledgement carries 32 slots; only slot 0 tracks the guest's stream, the others hold
stale ids (34460 seen). A resend gated on the maximum over slots never resends.

## Leaving

Once its player leaves the reward screens, a retail Sword host closes the network with
START_HOST_MIGRATION every 0.33 s for 10 s, as after a link trade ([Leaving](swsh_session.md#leaving)).
A guest that does not leave holds the host's player frozen in the overworld until the timeout;
`--leave-with-host` leaves on the first one.

## Unresolved

- The meaning of PlayerInfo's u32 and final bytes.
- The action's other ten entries, Dynamax, and the target codes beyond 8 and 2. Replayed unchanged, a
  recorded Water Gun action makes any guest Pokemon use Water Gun, on a retail Sword host too.
- Dynamax Adventures over local communication: the matching code shares the session layer; the
  messages are unread.
