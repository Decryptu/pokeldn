---
title: Command-line usage
---

<a id="command-line-usage"></a>
# Command-line usage

Run commands from the repository root. Source tools need Python 3.11+, Switch `prod.keys`
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

Trade tools need the .NET 10 SDK for the PKHeX helper. Install the bundled LDN library through
`requirements.txt`; do not substitute the PyPI `ldn` package. On Windows, activate the venv with
`.venv\Scripts\Activate.ps1` in PowerShell and set the radio with
`$env:POKELDN_RADIO = "esp32:auto"`.

`esp32:auto` selects the only USB serial port present; use `esp32:PORT` to select one explicitly.
See [radio settings and diagnostics](hardware_esp32.md#running). Config files and default output
paths resolve against the working directory. Each entry point accepts `--help`.

<a id="firered-and-leafgreen"></a>
## FireRed and LeafGreen

Unlock the Direct Corner on the console and prepare at least two `.pk3` party members.

```bash
./.venv/bin/python bin/frlg_trade_join.py --live -o output.pk3 PARTY1.pk3 PARTY2.pk3   # join the Switch's trade
./.venv/bin/python bin/frlg_trade_host.py -o output.pk3 PARTY1.pk3 PARTY2.pk3          # host a Direct Corner trade
```

The host advertises the group and leads the trade. By default it offers `PARTY2.pk3` and writes what
it receives to `output.pk3`. Defaults come from `config/host.toml`, then the ignored
`config/host.local.toml`; flags override both; `--print-effective-config` shows the result.

1. Run the host and wait for `Hosting Direct Corner`.
2. On the Switch: Direct Corner, Join Group, pick pokeldn's trainer. Wait until the host reports
   that trade selection is active.
3. Select the Pokémon to trade away and confirm.
4. The console returns to the trade menu after each trade. `--trades N` (1 to 6) offers party
   slots 0 to N-1, one per trade, on the same link. After the last trade, wait for the host prompt,
   then **CANCEL**, **YES**; the room exit and disconnect follow on their own.

| flag | purpose |
|---|---|
| `--keys PATH` | `prod.keys` location |
| `--slot N` | zero-based party member offered |
| `--capture FILE` | JSONL diagnostic capture |
| `--config` / `--local-config` / `--no-local-config` | replace or disable a config layer |
| `--ot NAME`, `--version firered\|leafgreen`, `--id TID[:SID]` | per-run trainer overrides (0..65535 each; the LinkPlayer ID is `(SID << 16) \| TID`) |
| `--verbose` | per-packet output, logged synchronously inside the frame-timed loop; use it with `--replay` only |

`DEFAULT_TRAINER` in [`pokeldn/config.py`](../pokeldn/config.py) holds the defaults with no flag
(gender, language, National Dex). The link protocol is in [The link protocol](frlg_link.md).

**Union Room.** `--union-room` advertises on the middle NPC's path; the console shows itself
connected after the keepalive wait, about 10 s ([The link protocol](frlg_link.md)). A Union
Room link carries one trade, then the console returns to the field (`union_room.c:1744`).
`--board-type normal` registers the offered Pokémon on the trading board, `--union-room-chat` with
`--chat-message` / `--chat-file` chats, `--union-room-battle --battle-fight` battles (the console needs two non-egg Pokémon at level 30 or lower).

```bash
./.venv/bin/python bin/frlg_trade_host.py --union-room --union-room-keepalive 120 PARTY1.pk3 PARTY2.pk3
```

**Mystery Gift.** `bin/frlg_mg_host.py` advertises on the Friend path and sends a Wonder Card plus a
delivery script. On the Switch: **Mystery Gift → Wonder Cards → Friend**, then pokeldn's host; the
save must have Mystery Gift unlocked. `--make-artifact` writes a `.ram.lst` listing of the bytes sent.
The catalogue, authoring system and Friend path requirement are in [Mystery Gift](frlg_gift.md).

```bash
./.venv/bin/python -u bin/frlg_mg_host.py --gift beast-cutscene --flag-id 1005 --capture mystery-gift.jsonl
```

The beast follows the save's starter (Bulbasaur Suicune, Squirtle Entei, Charmander Raikou). A shared
Stamp Rally card is `--gift solrock-stamp` and `--gift lunatone-stamp`, in either order.

**Wonder News.** `--news` serves the console's second Mystery Gift column (**Mystery Gift → Wonder
News → Friend**): 444 bytes of title and body, rewarding a berry in Cerulean City. A console keeps
news only if it differs from what it holds; `--news-id N` forces a new one.

```bash
./.venv/bin/python -u bin/frlg_mg_host.py --news berry --news-id 7
```

**Save backup and restore.** The same Friend path copies the whole 128 KB save to a `.sav` file, or
writes a `.sav` back: beside the console's own save, every sector read back, then the game loads it
and saves; anything short of that leaves the console's save as it was. In the app, the Mystery Gift
tool's Your save tab keeps the backups, names them, imports and exports `.sav` files and edits the
trainer and party through PKHeX. A backup took about four minutes on a retail French FireRed; a
restore on a retail English FireRed loaded with CONTINUE, a French save included. [Save backup and restore](frlg_gift.md#save-backup-and-restore).

```bash
./.venv/bin/python -u bin/frlg_mg_host.py --live --save-backup backup.sav --save-resume-dir partial
./.venv/bin/python -u bin/frlg_mg_host.py --live --save-restore backup.sav
```

**Console save.** A Mystery Gift session runs native ARM code on the console. `save-dump` reads the
live save back (secret ID, every party Pokémon's PID, IVs and nature); nothing is written.
`flash-patch` edits one field: it reads the save sector, changes only the named bytes, recomputes the
checksum, writes the sector back and bumps a counter so the game loads it. It edits a real save; read
[Composing a sector from a RAM snapshot](frlg_rom.md#composing-a-sector-from-a-ram-snapshot) first. Payloads: [Code on the console](frlg_rom.md).

```bash
./.venv/bin/python -u bin/frlg_mg_host.py --buffer-script save-dump --dump-block sav2 --dump-size 64 --dump-file dump.bin
./.venv/bin/python tools/frlg/dump_read.py dump.bin --block sav2
./.venv/bin/python -u bin/frlg_mg_host.py --buffer-script flash-patch --flash-id 0 \
  --flash-patch-offset 0x00 --flash-patch-hex cac9c5bfc6bec8ff --write-unsafe
```

<a id="lets-go-pikachu-and-eevee"></a>
## Let's Go Pikachu and Eevee

The trade screen alternates hosting and scanning, so pokeldn can host or join. Both send a kind-1
identity message: the joiner the one `pokeldn.lgpe.reference` ships, the host the console's own back
(`--first echo`) or a file. Both offer a 232-byte PB7 (`pokeldn.lgpe.pb7`; `--offer echo` returns the
console's own). The host's `--next-offer` and the joiner's repeated `--offer` queue one record per
later trade on the same seat. The joiner's `--leave-after S` backs out S seconds after it answers
the first trade step, the way a player leaves the trade screen; without it the seat stays up for
later trades.

```bash
./.venv/bin/python bin/lgpe_host.py --seconds 600 --player-name POKELDN \
  --first echo --our-trainer 41234:12345 --offer offer.pb7
./.venv/bin/python bin/lgpe_join.py --connect --connect-seconds 300 \
  --ack-peer-clock --ack-re-announce \
  --our-trainer 41234:12345 --offer offer.pb7
```

Console: Communiquer, Communication locale, Échange, link code Pikachu ×3, wait on the search
screen. For an emulated console over the LAN, use `lgpe_host.py --ip-host --our-ip IP`. See
[Let's Go](lgpe.md).

<a id="sword-and-shield"></a>
## Sword and Shield

Console: Y-Comm → Link Trade → local communication, A on both messages, wait on the search screen.

```bash
# join the console's session and trade: the console's own party snapshot is sent back, rewritten
POKELDN_RADIO=esp32:auto ./.venv/bin/python bin/swsh_connect.py --keys PROD_KEYS \
  --preset trade --offer-slot 1 [--offer-file your.pk8 --offer-file next.pk8 --fresh-pid] \
  --save-offered received.pk8

# or host, and let the console join: its snapshot is taken from this trade
POKELDN_RADIO=esp32:auto ./.venv/bin/python bin/swsh_host.py --keys PROD_KEYS \
  --offer-file your.pk8 --fresh-pid --received received.pk8 --channel 6 --seconds 900
```

The host builds its own station advertisement and rewrites the joining console's live snapshot.
When hosting, the console joins from Y-Comm → Link Trade → trade, after A on both messages that
follow; `--received FILE` saves what it sends, `--code 12345678` hosts for a Link Code search.
`--advert` and `--snapshot` still accept saved records for comparison. The host and the joiner
take a repeated `--offer-file`, one per trade on the session, as the player picks again from the box;
trade N writes what it received with `-N`. Details: [Trading](swsh_trade.md).

Mystery Gift needs no session; the gift screen scans and a distributor advertises the card. Console:
Mystery Gift → receive a gift → via local wireless.

```bash
./.venv/bin/python bin/swsh_gift_host.py --species 25 --level 25 \
  --move1 84 --move2 45 --move3 86 --move4 98 --nickname POKELDN --ot POKELDN --seconds 300
./.venv/bin/python bin/swsh_gift_host.py --record card.wc8 --seconds 300
```

`--set FIELD=VALUE` sets any record field (`shiny_type=3`, `ball=1`, `held_item=236`, `iv_hp=31`,
`gigantamax=1`), `--ribbon N` adds a ribbon, `--dump FILE` writes the record without a radio. Item ids
are checked against the item table; an id with no row is accepted and then aborts the game when its
bag row is shown. See [Mystery Gift](swsh_gift.md).

<a id="brilliant-diamond-and-shining-pearl"></a>
## Brilliant Diamond and Shining Pearl

pokeldn joins the console's Union Room as a character. Console: any Pokémon Center → 2F → left
attendant → plain "yes" (not the password or group option), then wait in the Union Room clear of the
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

Association can fail (`Connect failed with status code 1`); retry the run before diagnosing
([Session](bdsp_session.md)). `--room-pattern fixed` sends joins until the console asks for the
character's state, at most `--room-walk` (15 above). A repeated `--trade-template` queues one
Pokémon per trade in the session; the last is offered again. Use a fresh
`--src-var` every run (the console keeps ids it has seen), and after a hand-stopped run the player
leaves and re-enters the room. `--complete-trade` lets the console write its save; without it the
trade stops at the last confirmation. Once the character has appeared and finished walking: Y →
communication menu → trade Pokémon.

To host instead, start the host first, then the player enters the room the same way and raises the
trade emote (Y → communication menu → trade Pokémon):

```bash
./.venv/bin/python bin/bdsp_host.py --offer offer.pb8 --complete-trade --capture host.jsonl
```

`--offer` must be a legal PB8 whose PID the save does not hold; repeated, it queues one per trade,
the last offered again. `--password 00000000` hosts a room
entered with that password. See [Brilliant Diamond and Shining Pearl](bdsp.md).

<a id="legends-arceus"></a>
## Legends Arceus

A console hosting a trade runs it with the station that joins, or hands that station the host role
when the join lands late ([Legends Arceus](pla.md)). `bin/pla_host.py` hosts and the console
joins by link code; `bin/pla_join.py` joins the console's search, trades one repeated `--offer` per
trade on the seat, and takes the host role when it is handed.

```bash
./.venv/bin/python bin/pla_host.py --code 00000000 --channel 6 --seconds 1800 \
  --session-update --sustain --clock --data-exchange --data-exchange-name POKELDN \
  --data-exchange-id 11223344 --game-channel --trade-box --trade-box-record offer.pa8 \
  --offer-out received.pa8
./.venv/bin/python bin/pla_host.py --ip-host --our-ip 172.16.86.128 --code 00000000 ...   # emulated console, no radio
```

Console: Simona at Jubilife Village → trade → someone nearby → the same eight-digit code, offer a
Pokémon and confirm. The host re-reads its record file between offers and writes the record the console
traded to `--offer-out` (`-2` and on for later trades); `--trade-box-collect DIR` keeps every record
the console shows or offers, its cursor included. A repeated `--trade-box-record` queues one record per trade in the
session, the last offered again. `pokeldn.pla.pokemon` reads, writes and `build`s a record from 376
zero bytes; `pokeldn.pla.stats` computes stats and size. See [Legends Arceus](pla.md).

<a id="scarlet-and-violet"></a>
## Scarlet and Violet

The offline Link Trade search alternates scanning and hosting, so pokeldn hosts (`bin/sv_host.py`) or
joins (`bin/sv_join.py`).

```bash
./.venv/bin/python bin/sv_host.py --seconds 240 --player-name POKELDN \
  --rtt-probe --net-property --clock --net-stations 4 --scarlet-response \
  --record-delay 0.17 --announce --announce-delay 5.25 \
  --send-at 6.00:0x7c:1:b90101b902b90280800001 \
  --trade-offer offer.hex --offer-after-open 8
```

Console: X → Poké Portal → Link Trade → offline, no code → search. A repeated `--trade-offer`
offers one record per trade in the same seat. The wire-level requirements
(identity message order, acknowledgement `lowest_pending`) are in [Scarlet and Violet](sv.md).

Both also run a local Tera Raid. `--raid-seed` hosts one the console joins (Poké Portal → Tera
Raid Battle, Link Code 4970): the seed and four context flags choose the boss, `--raid-reward
ITEM:QUANTITY` replaces its rewards, and `--raid-pokemon` is the Pokémon pokeldn's player brings.
`--raid-event FOLDER` draws the boss and rewards from a Poké Portal News delivery instead, an event
of Project Pokemon's [EventsGallery](https://github.com/projectpokemon/EventsGallery), which the app
downloads and updates on request. `--raid-players N` lets up to three consoles join one raid; it
starts once N consoles are in the lobby and each has pressed Ready, or when the lobby timer runs out.
`--raid-partner TRAINER`, up to once for each slot the consoles leave empty (two with one
console), chooses the NPC partners who fill them, which a console otherwise draws from the host's
story progress.
`bin/sv_join.py --raid-pokemon FILE` joins a raid the console hosts. In both, pokeldn's player
leaves as the battle starts and its Pokémon stays to fight beside the console's. The app's two
Tera Raid tools carry the flags; see [Tera Raids](sv_raid.md).

<a id="legends-z-a"></a>
## Legends Z-A

The Link Trade search alternates hosting and scanning, so pokeldn joins or hosts. Console: Link Trade →
local communication → search with code 00000000. The joiner rescans until it takes a seat.

```bash
# host: start it first, then search on the console
POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/za_host.py --keys prod.keys --trade-offer offer.bin --capture zh.jsonl
# join
./.venv/bin/python bin/za_join.py --channels 1,6,11 --dwell 0.35 --seconds 900 \
  --hold 450 --quiet-seat 25 --connect-timeout 6 --game --trade-offer offer.bin --offer-delay 4
```

Pick a Pokémon on the trade box and confirm when the other side's shows. Both roles answer another
offer in the same session; a repeated `--trade-offer` queues records, one per trade. Back out with
B when finished; the host closes when the console leaves.
`--offer-out FILE` keeps what the console offered. For an emulated console over the LAN, use
`za_host.py --ip-host --our-ip IP --comm-id ffffffffffffffff` and
`za_join.py --ip-join --host-ip IP --our-ip IP --comm-id ffffffffffffffff`. The offer file is 354 bytes
(nine-byte header, 344-byte record, one trailing byte); `pokeldn.gen9.build` composes the record
because Z-A's layout is Scarlet's. See [Legends Z-A](za.md).

<a id="diagnostics"></a>
## Diagnostics

- `tools/ldn/ldn_scan.py` lists discoverable LDN networks; `esp32_sniff.py` makes a second board an
  air sniffer for one MAC on one channel.
- `POKELDN_ESP32_TRACE=FILE` records the board's serial traffic and counters; `--capture FILE` on
  every entry point writes the protocol trace as JSONL.
- [Host implementation](frlg_host.md): component boundaries, protocol flow, timing, shutdown.

