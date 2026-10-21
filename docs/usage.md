---
title: Command-line usage
---

# Command-line usage

This page lists the command-line entry points for each title. Run them from the repository root.
Source tools need Python 3.11+, Switch `prod.keys`
(default `~/.switch/prod.keys`, or `--keys PATH`) and a flashed ESP32 board.
See [supported boards](hardware_esp32.md#supported-boards) and
[building and flashing](hardware_esp32.md#building-and-flashing).

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
dotnet build -c Release services/pkhex
export POKELDN_RADIO=esp32:auto
python -m pokeldn --list
python -m pokeldn --radio esp32:auto swsh-host --offer-file offer.pk8
```

Trade tools need the .NET 10 SDK. The PyPI `ldn` package is a different library. On Windows use
`.venv\Scripts\Activate.ps1` and `$env:POKELDN_RADIO = "esp32:auto"`. `esp32:auto` picks the only
USB serial port; `esp32:PORT` names one ([radio settings](hardware_esp32.md#running)). Each entry
point accepts `--help`.

## FireRed and LeafGreen

Unlock the Direct Corner on the console and prepare at least two `.pk3` party members.

```bash
./.venv/bin/python bin/frlg_trade_join.py --live -o output.pk3 PARTY1.pk3 PARTY2.pk3   # join the Switch's trade
./.venv/bin/python bin/frlg_trade_host.py -o output.pk3 PARTY1.pk3 PARTY2.pk3          # host a Direct Corner trade
```

The host offers `PARTY2.pk3` and writes what it receives to `output.pk3`. Defaults come from
`config/host.toml`, then `config/host.local.toml`; flags override both
(`--print-effective-config`). After `Hosting Direct Corner`: Direct Corner, Join Group, pokeldn's
trainer, pick and confirm. `--trades N` (1 to 6) offers slots 0 to N-1, one per trade; after the last,
CANCEL, YES.

| flag | purpose |
|---|---|
| `--keys PATH` | `prod.keys` location |
| `--slot N` | zero-based party member offered |
| `--capture FILE` | JSONL diagnostic capture |
| `--config` / `--local-config` / `--no-local-config` | replace or disable a config layer |
| `--ot NAME`, `--version firered\|leafgreen`, `--id TID[:SID]` | per-run trainer overrides (0..65535 each; the LinkPlayer ID is `(SID << 16) \| TID`) |
| `--verbose` | per-packet output; with `--replay` only, it stalls a live link |

`DEFAULT_TRAINER` in [`pokeldn/config.py`](../pokeldn/config.py) holds the other defaults. Protocol:
[The link protocol](frlg_link.md).

### Union Room

`--union-room` serves the middle NPC; the console connects after about 10 s. A link carries one
trade (`union_room.c:1744`). `--board-type normal` registers on the trading board, `--union-room-chat`
with `--chat-message` / `--chat-file` chats, `--union-room-battle --battle-fight` battles (two
non-egg Pokémon at level 30 or lower).

```bash
./.venv/bin/python bin/frlg_trade_host.py --union-room --union-room-keepalive 120 PARTY1.pk3 PARTY2.pk3
```

### Mystery Gift

`bin/frlg_mg_host.py` sends a Wonder Card and delivery script on Mystery Gift, Wonder Cards, Friend.
`--make-artifact` writes a `.ram.lst` of the bytes sent. Catalogue: [Mystery Gift](frlg_gift.md).

```bash
./.venv/bin/python -u bin/frlg_mg_host.py --gift beast-cutscene --flag-id 1005 --capture mystery-gift.jsonl
```

The beast follows the starter (Bulbasaur Suicune, Squirtle Entei, Charmander Raikou).

### Wonder News

`--news` serves Mystery Gift, Wonder News, Friend. A console keeps news only if it differs from
what it holds; `--news-id N` forces a new one.

```bash
./.venv/bin/python -u bin/frlg_mg_host.py --news berry --news-id 7
```

### Save backup and restore

The Friend path copies the 128 KB save to a `.sav` (about four minutes) or writes one back; an
unfinished restore leaves the save as it was ([details](frlg_gift.md#save-backup-and-restore)).

```bash
./.venv/bin/python -u bin/frlg_mg_host.py --live --save-backup backup.sav --save-resume-dir partial
./.venv/bin/python -u bin/frlg_mg_host.py --live --save-restore backup.sav
```

### Console save

`save-dump` reads the live save; `flash-patch` rewrites named bytes of one sector with its checksum
and counter. Read [Composing a sector](frlg_rom.md#composing-a-sector-from-a-ram-snapshot) before a
write. Payloads: [Code on the console](frlg_rom.md).

```bash
./.venv/bin/python -u bin/frlg_mg_host.py --buffer-script save-dump --dump-block sav2 --dump-size 64 --dump-file dump.bin
./.venv/bin/python tools/frlg/dump_read.py dump.bin --block sav2
./.venv/bin/python -u bin/frlg_mg_host.py --buffer-script flash-patch --flash-id 0 \
  --flash-patch-offset 0x00 --flash-patch-hex cac9c5bfc6bec8ff --write-unsafe
```

## Let's Go Pikachu and Eevee

pokeldn hosts or joins. Both offer a 232-byte PB7 (`pokeldn.lgpe.pb7`; `--offer echo` returns the
console's); the host's `--first echo` echoes the console's identity message. The host's `--next-offer`
and the joiner's repeated `--offer` queue later trades; `--leave-after S` makes the joiner leave.

```bash
./.venv/bin/python bin/lgpe_host.py --seconds 600 --player-name POKELDN \
  --first echo --our-trainer 41234:12345 --offer offer.pb7
./.venv/bin/python bin/lgpe_join.py --connect --connect-seconds 300 \
  --ack-peer-clock --ack-re-announce \
  --our-trainer 41234:12345 --offer offer.pb7
```

Console: Communiquer, Communication locale, Échange, link code Pikachu ×3, wait on the search
screen. An emulated console: `lgpe_host.py --ip-host --our-ip IP`. See [Let's Go](lgpe.md).

## Sword and Shield

Console: Y-Comm, Link Trade, local communication, A on both messages, wait on the search screen.

```bash
# join the console's session and trade: the console's own party snapshot is sent back, rewritten
POKELDN_RADIO=esp32:auto ./.venv/bin/python bin/swsh_connect.py --keys PROD_KEYS \
  --preset trade --offer-slot 1 [--offer-file your.pk8 --offer-file next.pk8 --fresh-pid] \
  --save-offered received.pk8

# or host, and let the console join: its snapshot is taken from this trade
POKELDN_RADIO=esp32:auto ./.venv/bin/python bin/swsh_host.py --keys PROD_KEYS \
  --offer-file your.pk8 --fresh-pid --received received.pk8 --channel 6 --seconds 900
```

`--code 12345678` hosts for a Link Code search. A repeated `--offer-file` queues one per trade; trade N
writes with suffix `-N`. Details: [Trading](swsh_trade.md).

Mystery Gift: Mystery Gift, receive a gift, via local wireless.

```bash
./.venv/bin/python bin/swsh_gift_host.py --species 25 --level 25 \
  --move1 84 --move2 45 --move3 86 --move4 98 --nickname POKELDN --ot POKELDN --seconds 300
./.venv/bin/python bin/swsh_gift_host.py --record card.wc8 --seconds 300
```

`--set FIELD=VALUE` sets a record field (`shiny_type=3`, `held_item=236`), `--ribbon N` adds a ribbon,
`--dump FILE` writes the record without a radio. An item id with no table row aborts the game when
its bag row is shown. See [Mystery Gift](swsh_gift.md).

## Brilliant Diamond and Shining Pearl

pokeldn joins the console's Union Room as a character. Console: any Pokémon Center, 2F, left
attendant, plain "yes" (the first option), then wait in the Union Room clear of the
walls.

```bash
./.venv/bin/python tools/ldn/ldn_scan.py --channels 1,6,11 --dwell 0.8      # see the session
./.venv/bin/python bin/bdsp_connect.py --channels 1,6,11 --count 9 --connect 5 --join 6 \
  --hold 420 --reliable-ack --reliable-sweep 3 --room-walk 15 --room-pattern fixed \
  --room-walk-steps 0 --join-avatar 0 --answer-requests --state 0 --recruiting 0 \
  --answer-talk --can-talk 0 --initiate-talk --initiate-delay 3 \
  --after-approach 0x06:0001000000 --trade-reply --complete-trade \
  --trade-template offer.pb8 --trade-nickname POKELDN --src-var 0x2B7F4C12
```

On `Connect failed with status code 1`, retry ([Session](bdsp_session.md)). A repeated
`--trade-template` queues trades, the last offered again. Use a fresh `--src-var` every run.
`--complete-trade` lets the console save; without it the trade stops at the last confirmation. Once
the character has walked in: Y, communication menu, trade Pokémon.

To host, start the host first; the player enters the room the same way and chooses Y,
communication menu, trade Pokémon:

```bash
./.venv/bin/python bin/bdsp_host.py --offer offer.pb8 --complete-trade --capture host.jsonl
```

`--offer` is a legal PB8 whose PID the save lacks; repeated, it queues trades. `--password 00000000`
hosts a password room. See [Brilliant Diamond and Shining Pearl](bdsp.md).

## Legends Arceus

`bin/pla_host.py` hosts for the console's link code; `bin/pla_join.py` joins its search, with a
repeated `--offer` per trade, and takes the host role when handed it ([Legends Arceus](pla.md)).

```bash
./.venv/bin/python bin/pla_host.py --code 00000000 --channel 6 --seconds 1800 \
  --session-update --sustain --clock --data-exchange --data-exchange-name POKELDN \
  --data-exchange-id 11223344 --game-channel --trade-box --trade-box-record offer.pa8 \
  --offer-out received.pa8
./.venv/bin/python bin/pla_host.py --ip-host --our-ip 172.16.86.128 --code 00000000 ...   # emulated console, no radio
```

Console: Simona at Jubilife Village, trade, someone nearby, the same eight-digit code, offer a
Pokémon and confirm. `--offer-out` gets each received record (`-2` and on), `--trade-box-collect DIR`
every record the console shows; a repeated `--trade-box-record` queues trades. `pokeldn.pla.pokemon`
builds a record.

## Scarlet and Violet

pokeldn hosts (`bin/sv_host.py`) or joins (`bin/sv_join.py`).

```bash
./.venv/bin/python bin/sv_host.py --seconds 240 --player-name POKELDN \
  --rtt-probe --net-property --clock --net-stations 4 --scarlet-response \
  --record-delay 0.17 --announce --announce-delay 5.25 \
  --send-at 6.00:0x7c:1:b90101b902b90280800001 \
  --trade-offer offer.hex --offer-after-open 8
```

Console: X, Poké Portal, Link Trade, offline, no code, search. A repeated `--trade-offer`
queues trades. See [Scarlet and Violet](sv.md).

Tera Raids: `--raid-seed` hosts one (Poké Portal, Tera Raid Battle, Link Code 4970), `--raid-reward
ITEM:QUANTITY` replaces rewards, `--raid-pokemon` is pokeldn's Pokémon, `--raid-event FOLDER` uses a
Poké Portal News event from Project Pokemon's
[EventsGallery](https://github.com/projectpokemon/EventsGallery), `--raid-players N` (up to 3)
waits for N consoles, `--raid-partner TRAINER` picks NPC partners for empty slots.
`bin/sv_join.py --raid-pokemon FILE` joins a console's raid. See [Tera Raids](sv_raid.md).

## Legends Z-A

Console: Link Trade, local communication, search with code 00000000.

```bash
# host: start it first, then search on the console
POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/za_host.py --keys prod.keys --trade-offer offer.bin --capture zh.jsonl
# join
./.venv/bin/python bin/za_join.py --channels 1,6,11 --dwell 0.35 --seconds 900 \
  --hold 450 --quiet-seat 25 --connect-timeout 6 --game --trade-offer offer.bin --offer-delay 4
```

A repeated `--trade-offer` queues trades; B on the console ends the session. `--offer-out FILE` keeps
what the console offered. Emulated console: `--ip-host --our-ip IP --comm-id ffffffffffffffff`
(host) or `--ip-join --host-ip IP --our-ip IP --comm-id ffffffffffffffff` (join). The offer file is
354 bytes (9-byte header, 344-byte record, 1 trailing byte); `pokeldn.gen9.build` composes the
record. See [Legends Z-A](za.md).

## Diagnostics

- `tools/ldn/ldn_scan.py` lists discoverable LDN networks; `esp32_sniff.py` makes a second board an
  air sniffer for one MAC on one channel.
- `POKELDN_ESP32_TRACE=FILE` records the board's serial traffic and counters; `--capture FILE` on
  every entry point writes the protocol trace as JSONL.
- [Host implementation](frlg_host.md): component layout, protocol flow, timing, shutdown.

