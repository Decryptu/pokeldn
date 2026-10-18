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
| advertise `0xb0` and `0xd4` | the boss and the den record ([The den record](#the-den-record)) |

The den lobby's code sits among `View_NestHole`, `StateGuestReady` and `StateHostReady`
(`0x0102aba4..0x010370cc`). Dynamax Adventures match through `ChikaMatchingState*`
(`0x00bd1978..0x00bda158`), which calls the same Pia session maximum from `0x00bd9b30`.

A guest's Y-Comm list leaves out a raid whose advertisement carries the guest's own device id and
account uid ([The den record](#the-den-record)).

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
| 5 | NestholeBattleStart | 32 | the participants' Pia constant ids as four u64, the host's first, unused slots zero |
| 6 | NestholeBossPokemon | 364 | 19 zero bytes and `ff`, then the boss as an encrypted party PK8 |
| 7 | NestholeRewards | 120 | fifteen u32 pairs: item id, count; unused pairs zero |
| 8 | NestholeBattleSeed | 16 | u64 seed, then `00 ff ff ff 1e 00 03 00` |

PlayerInfo goes out zlib-compressed with a 4 KB window (header `48 4b`) under reliable flag 0x10;
the others go out plain. `pokeldn/swsh/raid.py` builds every field; its output equals the bytes of an
emulated guest (2, 3, 4) and an emulated host (5 to 8).

The boss record carries the boss in full: species, level, moves, IVs and PID. In two emulated
raids, the den's raid generator applied to the BattleSeed value gives neither the boss's
encryption constant nor its PID. What the seed feeds is unread.

## The guest's sequence

Recorded between two emulated Shields, a whole raid won:

1. The snapshot exchange on 0x84, as in a link trade; the host's snapshot went first.
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

### Which station serves

The server is the station whose ServerVersion record wins a table each console keeps; neither the
Pia host check (`0x110e620`, no caller in the battle or lobby code) nor BattleStart's order decides it.

ServerVersion is `btl.net.protocol_buffers.BtlDataHolder` (id 10000) field 3: station id u64, client
id u32, version u32. Every copy sends version `0x6e` (`0x8b1778`). A console keeps eight slots of
{station, client id, version, valid} (battle network object `+0x190 + 16 * i`); `0x8b4030` takes the
client id of the first valid slot whose version equals the highest seen, and `0x8b1990` (IsServer)
compares it with the console's own client id. The collecting station files a record in the slot of the
sender's Pia station index (`0x8b4440`, `0x6b5850`); every other console receives the slots as 40000
framework objects 0 to 7, the object number in field 2. In the recorded raid the host published object
0 (its own record, client id 0) and object 1 (the guest's, client id 1).

A console's client id is its position in BattleStart among the lobby's members (`0x1025120`,
`0x10253bc`). Removing a station clears its slot and reruns the choice (`0x8b3f70`), and every console
holds a standby server it promotes once IsServer turns true (`0x7f838c`, `0x7f87f0`).

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

## The den record

A den host's advertisement describes its raid; a guest's Y-Comm entry builder (`0x00fa1560`) reads it.

| offset | content |
|---|---|
| `0x5F` bit 1 | the host's version: clear Sword, set Shield |
| `0xAF` | activity kind: `0x11` at rank 0, `0x13 + 2 (rank - 1)` above; `0xFF` is never listed |
| `0xB0` | the boss shown: u16 species (bits 0 to 9) and form (10 to 15), a byte whose bits 4 and 5 are 1 normal, 2 Gigantamax, the u32 encryption constant |
| `0xD4` | the den record, the same eight-byte layout |
| `0xDC` | high nibble: the star rank, 0 to 4 |
| `0xDD` | bits 3 to 5: den kind, 0 for a normal den |
| `0xDE`, `0xE0` | u16 encounter table, counted among the host version's tables, and u16 slot |
| `0xE6` to `0xED` | CRC16s of files 8, 6, 7 and 9 of `bin/archive/field/resident/data_table.gfpak` |

With a non-zero species at `0xD4`, a guest lists the raid only when its own table CRCs match, the den
kind is 0, and table `0xDE` slot `0xE0` of the host's version holds that species, form and Gigantamax
flag (`0x00ea5160`, `0x00ea51d0`). A species of 0 skips those checks. The rank must not exceed the
guest's own rank, from its badge count, when the byte at `0x02510b2c` is 1 or 2 and the host is not a
friend. The record at `0xB0` is range-checked only. `pokeldn/swsh/data/nest_slots.json` holds the
1.3.2 slots (`scripts/gen_swsh_nest_data.py`); `raid.den_advert` points the den record at a slot
holding the boss, or zeroes it.

A guest drops a station whose device id and account uid (`0x1F` to `0x3E`) both equal its own
(`0x0111b160`).

### The boss record

A retail Sword guest left with 2-ALZAA-0016 on BossPokemon when the boss was a traded record (a
trainer, version, met data and ball) and when its party Dynamax type (`+0x156`) was 0; both recorded
den bosses have no trainer data and Dynamax type 1. A boss on a den boss's record with only the species
changed, and a level-20 boss built by `raid.boss_record` (the Pokemon's species, form, moves, IVs, EVs,
nature, ability, PID, encryption constant and party stats on a den boss's record), were accepted.

## Hosting

`bin/swsh_host.py --raid-boss PK8 --raid-console-serves` hosts a den lobby a console joins from its
Y-Comm list (`pokeldn/swsh/raid_host.py`). The advertisement and the snapshot are an emulated Shield
den host's, renamed and with no account ids (`pokeldn/swsh/data/raid_advert.bin`,
`raid_snapshot.bin`; `--advert` and `--snapshot` replace them). The advertisement goes out with a
fresh station profile, the board's name, the boss and a den record for it
([The den record](#the-den-record)); `--raid-boss` takes any PK8 and sends it through
`raid.boss_record`. The snapshot goes out before the guest's. `--raid-reward ITEM:COUNT` fills Rewards and `--raid-seed` BattleSeed.

The app's Max Raid (Host) tool runs these flags with a boss, our Pokemon and up to 15 reward rows;
without rows the host gives `raid.DEN_REWARDS`, an emulated den's.

With `--raid-console-serves` the joined console serves the battle and the host answers as client 1
(`raid_battle.Master`):

| step | the host |
|---|---|
| BattleStart | lists the console first, so the console's client id is 0 |
| 0x7C port 0 | sends ping; answers the console's ping and pingSynced |
| framework objects | publishes object 0 = the console's ServerVersion record, object 1 = its own |
| 0x7C port 0 | sends its own ServerVersion (client id 1) |
| base 20000 | publishes the counter and its own body, 0000 / 00000100, then 0100 / 01000100, 01000200, 0200 / 02000200, each once the console mirrors the last body |
| object 8 | the console publishes it (24 bytes, a seed); the host answers EmptyCommand (10000 field 1) |
| battle commands | answered as a guest answers them, the action naming the host's Pokemon's first move |

An emulated Shield guest and a retail Sword each served a whole raid this way, won it and received
the host's Rewards, then sent the mesh leave request.

## Leaving

Once its player leaves the reward screens, a retail Sword host closes the network with
START_HOST_MIGRATION every 0.33 s for 10 s, as after a link trade ([Leaving](swsh_session.md#leaving)).
A guest that does not leave holds the host's player frozen in the overworld until the timeout;
`--leave-with-host` leaves on the first one.

## Unresolved

- Whether a console that is not the Pia host would publish framework objects 0 to 7; in every
  recording and hosted raid the Pia host published them.

- The meaning of PlayerInfo's u32 and final bytes.
- The action's other ten entries, Dynamax, and the target codes beyond 8 and 2. Replayed unchanged, a
  recorded Water Gun action makes any guest Pokemon use Water Gun, on a retail Sword host too.
- Dynamax Adventures over local communication: the matching code shares the session layer; the
  messages are unread.
