# pokeldn

An ESP32 board on USB serial is the radio: pokeldn hosts or joins Nintendo Switch local wireless
(LDN) sessions with retail Pokémon games through it, from any computer that runs Python. Nothing is
installed on the Switch or Switch 2. Seven games are supported:

| | FRLG | LGPE | SwSh | BDSP | PLA | SV | PLZA |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Trade | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Mystery Gift | ✓ | ∅ | ✓ | ∅ | ∅ | ∅ | ✗ |
| Link battle | ✓ | ✗ | ✗ | ✗ | ∅ | ✗ | ✗ |
| Code on the console, save read and write | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |

✓ works on a retail console · ✗ not done · ∅ the game has no such feature over local wireless
FRLG FireRed/LeafGreen · LGPE Let's Go Pikachu/Eevee · SwSh Sword/Shield · BDSP Brilliant Diamond/Shining Pearl · PLA Legends Arceus · SV Scarlet/Violet · PLZA Legends Z-A

All games share the radio, LDN and Pia layers, and every one has completed a trade through the
ESP32 board. FireRed and LeafGreen also run the GBA link protocol
inside the Switch's emulator.

The full protocol documentation is at [decryptu.github.io/pokeldn](https://decryptu.github.io/pokeldn/).

`pokeldn.ldn` implements the shared wireless layer, `pokeldn.gba` the GBA adapter protocol, and
the game packages their own protocols. Entry points are named for the game they drive.

---

## Why?

This project demonstrates direct local wireless communication with retail Pokémon games and
documents the protocols for work such as an unofficial GTS or online battles. AI tools helped
reverse engineer the protocols and write parts of the code. Contributors can join the
[Discord](https://discord.gg/PyvaVYnpXC).

## Demonstration
https://github.com/user-attachments/assets/b0df878e-67f0-483d-ae81-583cfc2a8692

This demo was recorded before the ESP32 radio, with a Linux Wi-Fi card (ALFA AWUS036ACHM).

## Features

FireRed / LeafGreen

- Trading with a real game in both directions, with `.pk3` / `.ek3` input and output
- Mystery Gift in both directions: Wonder Cards with scripted deliveryman gifts, Wonder News, and a
  visiting Battle Tower trainer
- Union Room: greetings, trading-board trades, live chat, and full link battles
- Native code on the console through the gift link: reading and writing its save, mapping its ROM,
  calling its own functions, and building a Pokémon with its own `CreateMon`

Let's Go Pikachu / Eevee

- Trading in both directions; a box structure built here goes into the console's save as sent

Sword / Shield

- Trading in both directions: joining the console's Link Trade, or hosting one it joins; a PKHeX
  `.pk8` goes into the console's game
- Mystery Gift: Wonder Cards built from the command line or served from a published `.wc8`
  (Pokémon, eggs, items, Battle Points, clothing)

Brilliant Diamond / Shining Pearl

- Trading in both directions: joining the console's Union Room, or hosting a Union Room the
  console walks into; a character of pokeldn's own greets the player and trades through the game's
  own flow
- Record mixing, ball capsules and the battle lobby, up to the console sending its own records

Legends Arceus

- Trading into the console's save, hosting the session the console joins
- Any Pokémon the game has, composed from nothing: species, level, nature, ability, moves and their
  PP, mastered moves, alpha, shininess, nickname, individual and growth values, size, ball and met
  data, all from the game's own tables, and the stats the game itself would compute

Scarlet / Violet

- Trading in both directions: hosting the session the console joins, and joining the one it hosts
- A party record composed from nothing goes into the console's save as sent

Legends Z-A

- Trading into the console's save, joining the session the console hosts on its Link Trade search
- A record composed from nothing goes into the console's save; the game computes the level, the
  stats and the current HP itself

Every game

- An offline toolkit for reading a retail title's own code (`tools/switch/`)

## Requirements

- A classic ESP32 board on USB (tested: ESP32-D0WD-V3 on an ELEGOO board with a CP2102 bridge),
  flashed with [`firmware/esp32`](firmware/esp32). It is 2.4 GHz only.
- Python 3.11+, and a venv with `requirements.txt` installed. No root.
- A Switch or Switch 2 with one of the games above. FireRed / LeafGreen needs the Direct Corner
  unlocked (about 20 to 40 minutes of play) and at least two `.pk3` files as party members
- Switch `prod.keys` (default location `~/.switch/prod.keys`; `--keys PATH` elsewhere)

The LDN implementation in [`vendor/LDN`](vendor/LDN) is installed by `pip install -r requirements.txt`.
The PyPI `ldn` package of the same version lacks the compatibility fixes; do not substitute it.

## Setup

1. Create a Python venv and install `requirements.txt`.
2. Build and flash the firmware with ESP-IDF v6.1 ([ESP32 radio](docs/hardware_esp32.md) has the
   exact version), then check the board:

   ```bash
   cd firmware/esp32 && idf.py build && idf.py -p PORT flash && cd ../..
   ./.venv/bin/python tools/ldn/esp32_first_contact.py --port PORT
   ```

   `PORT` is the board's serial device (`/dev/cu.usbserial-*` on macOS, `/dev/ttyUSB*` on Linux); its
   name follows the USB socket.

   It prints the board's HELLO, its counters, and the LDN networks it hears on channels 1, 6 and 11.
3. Point every entry point at the board:

   ```bash
   export POKELDN_RADIO=esp32:auto
   ```

   `auto` takes the only USB serial port present and refuses to guess between several;
   `esp32:PORT` names one.

   `POKELDN_ESP32_TRACE=FILE` records every serial message both ways, with the board's counters
   every 5 s.

### Linux Wi-Fi cards

Before the ESP32, a Linux host drove an AP-capable Wi-Fi card directly (TP-Link Archer T3U, ALFA
AWUS036ACHM, Realtek RTL8821CE), as root, with NetworkManager kept off the LDN interfaces. That path
still works without `POKELDN_RADIO` and is no longer developed; [Adapters](docs/hardware_adapters.md)
has the cards and their configuration.

## Layout

| | |
|---|---|
| [`bin/`](bin) | what you run against a console. FireRed/LeafGreen: `frlg_mg_host.py` (Mystery Gift, Wonder News and native code), `frlg_mg_client.py` (receive a card from a console), `frlg_trade_host.py` (trade and Union Room host), `frlg_trade_join.py` (trade joiner). Let's Go: `lgpe_host.py`, `lgpe_join.py`. Sword/Shield: `swsh_connect.py` (trade, joining), `swsh_host.py` (trade, hosting), `swsh_gift_host.py` (Mystery Gift), `swsh_join.py` (scan). Brilliant Diamond/Shining Pearl: `bdsp_connect.py` (Union Room and trade, joining), `bdsp_host.py` (Union Room and trade, hosting), `bdsp_join.py`, `bdsp_pia_probe.py`. Legends Arceus: `pla_host.py` (trade), `pla_join.py`. Scarlet/Violet: `sv_host.py` (trade), `sv_join.py` (trade). Legends Z-A: `za_join.py` (trade) |
| [`tools/ldn/`](tools/ldn) | the radio, for any target: `esp32_first_contact.py`, `esp32_sniff.py` (a second board as an air sniffer), `ldn_scan.py`; for a Linux card, `sniff.py`, `joyspot_probe.py`, `ldn_debug_report.sh` |
| [`firmware/esp32/`](firmware/esp32) | the ESP32 radio's firmware (ESP-IDF v6.1) |
| [`tools/frlg/`](tools/frlg) | reading what a FireRed console sent back, offline: `dump_read.py`, `script_read.py`, `rom_functions.py`, `cartridge_pair.py`, `game_data_read.py`, `english_build.py` |
| [`tools/switch/`](tools/switch) | reading a retail Switch title's own code, offline: `xci_read.py`, `romfs_read.py`, `nso_read.py`, `nso_relocs.py`, `nso_imports.py`, `rtti_names.py`, `arm64_xref.py`, `arm64_dis.py` |
| [`pokeldn/`](pokeldn) | the package everything above is made of: `ldn/` the wireless layer, `gba/` the GBA link above it, `frlg/` `lgpe/` `swsh/` `bdsp/` `pla/` `sv/` `za/` the games, `gen8.py` the Pokémon format Sword/Shield and Brilliant Diamond/Shining Pearl share |
| [`asm/`](asm) | ARM sources for the payloads the console runs; `scripts/gen_buffer_scripts.py` assembles them into `pokeldn/frlg/rom/buffer_payloads.py` |
| [`scripts/`](scripts) | setup, deployment and code generation; never pointed at a console |
| [`config/`](config) | host profiles (`host.toml`, and `host.local.toml` for this machine) |
| [`docs/`](docs) | the protocol findings, each with its citations; published at [decryptu.github.io/pokeldn](https://decryptu.github.io/pokeldn/) |
| [`tests/`](tests) | `python -m pytest tests/ -q` |
| [`vendor/`](vendor) | the bundled LDN implementation and the mt7601u AP-mode driver |

Run the entry points from the repo root with `POKELDN_RADIO` set: `./.venv/bin/python -u
bin/frlg_mg_host.py ...`. They put the root on `sys.path` themselves; config files and default output
paths resolve against the working directory.

## Usage

### FireRed and LeafGreen

#### Join a Switch-hosted trade

```bash
./.venv/bin/python bin/frlg_trade_join.py --live -o output.pk3 PARTY1.pk3 PARTY2.pk3
```

#### Host a Direct Corner trade

```bash
./.venv/bin/python bin/frlg_trade_host.py -o output.pk3 PARTY1.pk3 PARTY2.pk3
```

pokeldn advertises the group and acts as the trade leader. With the default settings it offers the
second supplied party member (`PARTY2.pk3`) and writes the Pokémon received from the Switch to
`output.pk3`. Host defaults come from `config/host.toml`, then the optional ignored
`config/host.local.toml`; command-line flags override both.
`bin/frlg_trade_host.py --print-effective-config` inspects the resolved profile without a radio.

Then:

1. Run the host command and wait for `Hosting Direct Corner`.
2. On the Switch, enter the Direct Corner and choose Join Group.
3. Select pokeldn's trainer and join. The leader performs its room-entry route automatically; wait
   until the host reports that trade selection is active.
4. On the Switch, select the Pokémon to trade away and accept the confirmation.
5. After the trade and save sequence returns to the trade menu, wait for the host prompt, then select
   **CANCEL** and confirm **YES**.
6. Allow the automated room exit and disconnect to finish. The received Pokémon is saved to
   `output.pk3` (or the path passed to `--out`).

Some optional flags:

| flag | options | purpose |
|---|---|---|
| `--verbose` | | per-packet protocol output; for `--replay` of a capture only, on a live link it stalls the console |
| `--keys` | `/path/to/prod.keys` | non-default `prod.keys` location |
| `--slot` | zero-based party index | host party member offered in the trade |
| `--capture` | output path | JSONL diagnostic capture |
| `--config` | TOML path | replace the tracked shared host profile |
| `--local-config` / `--no-local-config` | TOML path / | select or disable the machine-local layer |
| `--print-effective-config` | | print the redacted resolved profile and exit |
| `--ot` | Gen III trainer name | override the default trainer name for this run |
| `--version` | `firered` or `leafgreen` | override the configured game version |
| `--id` | decimal `TID[:SID]` | override the trainer ID, and optionally the secret ID |

`--help` is the authoritative list for each entry point.

#### Host a Union Room

`--union-room` advertises on the middle NPC's path instead of the Direct Corner's; the console applies
a different accept list.

```bash
./.venv/bin/python bin/frlg_trade_host.py --union-room --union-room-keepalive 120 \
  PARTY1.pk3 PARTY2.pk3
```

The console takes about ten seconds to appear to itself as connected; the wait is the RFU library's.
Add `--board-type normal` to register the offered Pokémon on the trading board,
`--union-room-chat` with `--chat-message` or `--chat-file` for chat, and
`--union-room-battle --battle-fight` for a link battle. In a battle the console elects itself master
and computes everything; the host answers its controller commands. The console needs two non-egg
Pokémon at level 30 or lower in its own party or it refuses on its own screen.

See [The link protocol](docs/frlg_link.md) for the connect sequence, the activity bytes and the link
buffer protocol.

#### Trainer identity

All three entry points start from `DEFAULT_TRAINER` in [`pokeldn/config.py`](pokeldn/config.py). Use
`--ot`, `--version` and `--id` for per-run overrides; the ID format is decimal `TID[:SID]`:

```bash
# Set TID to 12345 and retain DEFAULT_TRAINER.sid
./.venv/bin/python bin/frlg_trade_join.py --live --id=12345 PARTY1.pk3 PARTY2.pk3

# Set TID to 12345 and SID to 34567 while hosting
./.venv/bin/python bin/frlg_trade_host.py --live --id=12345:34567 PARTY1.pk3 PARTY2.pk3
```

Each component must be between 0 and 65535, and the resulting 32-bit LinkPlayer ID is
`(SID << 16) | TID`. The resolved profile is used consistently by discovery, Pia Session, RFU game
data, LinkPlayer and trainer-card identity. Edit `DEFAULT_TRAINER` for gender, language, National Dex
or game-completion defaults that have no CLI flag.

#### Distribute a Mystery Gift

`bin/frlg_mg_host.py` advertises on the Friend path and sends a Wonder Card plus a delivery RAM
script. The default payload is the repeatable legendary-beast cutscene.

```bash
./.venv/bin/python -u bin/frlg_mg_host.py \
  --gift beast-cutscene --flag-id 1005 \
  --capture mystery-gift.jsonl
```

On the Switch choose **Mystery Gift → Wonder Cards → Friend**, then select pokeldn's host. The save
must already have Mystery Gift unlocked. `--make-artifact` writes a `.ram.lst` audit listing of the
exact card and delivery-script bytes a run sent.

The beast depends on the receiving save's starter: Bulbasaur gives Suicune, Squirtle gives Entei,
Charmander gives Raikou. The live host also distributes the two halves of a shared Stamp Rally card
(`--gift solrock-stamp` and `--gift lunatone-stamp`, in either order).

See [Mystery Gift](docs/frlg_gift.md) for the protocol flow, the gift catalogue, the authoring system,
and the Friend path requirement.

#### Distribute Wonder News

The console's Mystery Gift menu has a second column, and `--news` serves it. Wonder News is 444 bytes
of title and body with no flag ID, no delivery script and no gift attached: the reward is a berry from
the man in the house in Cerulean City. On the Switch choose **Mystery Gift → Wonder News → Friend**. A
Wonder Card host is not listed on that screen, and vice versa.

```bash
./.venv/bin/python -u bin/frlg_mg_host.py --news
./.venv/bin/python -u bin/frlg_mg_host.py --news berry --news-id 7
```

A console keeps news only when it differs from what it already holds; `--news-id N` makes the same
text land again.

#### Read the console's save

A Mystery Gift session can run native ARM code on the console and read its live save back, including
the secret ID and every party Pokémon's PID, IVs and nature.

```bash
./.venv/bin/python -u bin/frlg_mg_host.py \
  --buffer-script save-dump --dump-block sav2 --dump-size 64 --dump-file dump.bin

./.venv/bin/python tools/frlg/dump_read.py dump.bin --block sav2
```

The console stays on its Mystery Gift menu, nothing is written and no Wonder Card changes hands. See
[Code on the console](docs/frlg_rom.md) for the mechanism and the other payloads.

#### Change a field of the console's save

The same session can edit the save instead of reading it. `flash-patch` reads the save sector a
field lives in off the flash chip, changes the bytes it means to, recomputes the game's checksum and
writes the sector back, then bumps one counter so the game loads the edited slot.

```bash
./.venv/bin/python -u bin/frlg_mg_host.py \
  --buffer-script flash-patch --flash-id 0 --flash-patch-offset 0x00 \
  --flash-patch-hex cac9c5bfc6bec8ff --write-unsafe
```

Nothing is rebuilt from RAM, which is the point: a sector composed from the live save block loses the
encryption key and the saved map view, because the game writes both only as it saves. Every byte the
patch does not name is the byte the game itself put there. This edits a real save; see
[A RAM snapshot is not a save](docs/frlg_rom.md) before pointing it at one you care about.

### Let's Go Pikachu and Eevee

The console's trade screen alternates hosting and scanning, so pokeldn can host and let the console
join, or join the console's session. Both need a captured kind-1 identity message for `--first` /
`--reliable-payload` and a 232-byte PB7 box structure to offer (`pokeldn.lgpe.pb7` reads and writes
one; `--offer echo` hands the console its own back).

```bash
# host: the console finds PkCamp and joins
./.venv/bin/python bin/lgpe_host.py --seconds 600 --player-name PkCamp \
  --first identity.bin --our-trainer 41234:12345 --offer offer.pb7

# join the console's session, trade, and leave the way a console does
./.venv/bin/python bin/lgpe_join.py --connect --connect-seconds 300 \
  --reliable-payload identity.bin --ack-peer-clock --ack-re-announce \
  --our-trainer 41234:12345 --offer offer.pb7 --leave-after 15
```

On the console: menu → Communiquer → Communication locale → Échange, link code Pikachu, Pikachu,
Pikachu, then wait on the search screen. See [Let's Go](docs/lgpe.md).

### Sword and Shield

Trading joins the console's Link Trade session. The console hosts on Y-Comm → Link Trade over
local communication; its local communication id is filled at runtime, so the first run is a scan:

```bash
./.venv/bin/python bin/swsh_join.py --scan-only
```

Everything each advertisement carries is written to `scratchpad/swsh_net_facts.json`. The trade
itself is `bin/swsh_connect.py`, which walks the station handshake, the mesh join, the party
snapshot exchange and the confirmation ladder; `--offer-file FILE` puts a PKHeX `.pk8` on the wire
in place of a party slot. The flags a completed trade takes are on [Trading](docs/swsh_trade.md).

Hosting is `bin/swsh_host.py`; the console joins it from Y-Comm → Link Trade → trade, after A on
both messages that follow (the search starts only after the second):

```bash
POKELDN_RADIO=esp32:auto ./.venv/bin/python bin/swsh_host.py --keys PROD_KEYS \
  --advert scratchpad/swsh_net_facts.json --scene-id 60001 --channel 6 --seconds 900
```

It offers party slot 1 of `--snapshot` under the trainer `--trainer-name` and writes the Pokémon it
receives to `--received FILE`.

Mystery Gift needs no session: the gift screen scans, and a distributor advertises a network whose
advertise data carries the card.

```bash
./.venv/bin/python bin/swsh_gift_host.py --species 25 --level 25 \
  --move1 84 --move2 45 --move3 86 --move4 98 --nickname PKCAMP --ot POKELDN --seconds 300
./.venv/bin/python bin/swsh_gift_host.py --record card.wc8 --seconds 300
```

On the console: Mystery Gift → receive a gift → via local wireless. `--set FIELD=VALUE`
sets any record field by name (`shiny_type=3`, `ball=1`, `held_item=236`, `iv_hp=31`,
`gigantamax=1`), `--ribbon N` adds a ribbon, `--dump FILE` writes the record without a radio.
A kind-2 card's item ids are checked against the item table before serving: an id the game has no
row for is accepted and then aborts the game whenever its bag row is on screen. See
[Mystery Gift](docs/swsh_gift.md).

### Brilliant Diamond and Shining Pearl

pokeldn joins the console's Union Room as a character of its own. On the console: any Pokémon
Center → 2F → the left attendant → the plain "yes" (not the password or group option), then wait
in the Union Room, standing clear of the walls.

```bash
# see the session without joining it
./.venv/bin/python tools/ldn/ldn_scan.py --channels 1,6,11 --dwell 0.8

# walk in, greet the player, and trade
./.venv/bin/python bin/bdsp_connect.py --channels 1,6,11 --count 9 --connect 5 --join 6 \
  --hold 420 --reliable-ack --reliable-sweep 3 --room-walk 15 --room-pattern fixed \
  --room-walk-steps 8 --join-avatar 0 --answer-requests --state 0 --recruiting 0 \
  --answer-talk --can-talk 0 --initiate-talk --initiate-delay 3 \
  --after-approach 0x06:0001000000 --trade-reply --complete-trade \
  --trade-template offer.pb8 --trade-nickname PKCAMP --src-var 0x2B7F4C12
```

A join is about a one-in-eight shot per attempt and `--room-pattern fixed` bursts fifteen. Use a
fresh `--src-var` on every run: the console keeps an id it has seen as one of its stations. After a
run is stopped by hand, the player leaves and re-enters the Union Room before the next one.
`--complete-trade` lets the console write its save; without it the trade stops at the last
confirmation. When the character has appeared and finished walking, the player
opens Y → the communication menu → trade Pokémon, and the greeting comes up on its own.

A console entering the Union Room looks for a room before it opens its own, so pokeldn can host
one instead. Start the host first, then the player enters the Union Room the same way:

```bash
./.venv/bin/python bin/bdsp_host.py --offer offer.pb8 --complete-trade --capture bh01.jsonl
```

pokeldn's character appears in the room. The player raises the trade emote (Y → the communication
menu → trade Pokémon); the character walks up, and the trade runs as above. `--offer` must be a
legal PB8 whose PID the console's save does not already hold: the game refuses a duplicate. See
[Brilliant Diamond and Shining Pearl](docs/bdsp.md).

### Legends Arceus

The console's trade screen alternates scanning and hosting and registers its own protocols only
while it hosts, so pokeldn hosts and the console joins by link code.

```bash
# host, offering a record built from nothing
./.venv/bin/python bin/pla_host.py --code 00000000 --channel 6 --seconds 1800 \
  --session-update --sustain --clock --data-exchange --data-exchange-name POKELDN \
  --data-exchange-id 11223344 --game-channel --trade-box --trade-box-record offer.pa8 \
  --trade-box-collect records/

# the same host against an emulated console over the LAN, no radio and no root
./.venv/bin/python bin/pla_host.py --ip-host --our-ip 172.16.86.128 --code 00000000 ...
```

On the console: Simona at Jubilife Village → trade → someone nearby → the same eight-digit code,
then offer a Pokémon up and confirm. The host answers every showing and every offer, re-reads its
record file between offers so the offer can be changed without rejoining, and writes each distinct
record the console shows to `--trade-box-collect`.

`pokeldn.pla.pokemon` reads and writes the record, `build` composes one from 376 zero bytes, and
`pokeldn.pla.stats` gives the stats and the size the game itself would compute. See
[Legends Arceus](docs/pla.md).

### Scarlet and Violet

The console's offline Link Trade search alternates scanning and hosting, so pokeldn hosts and the
console joins on its own.

```bash
./.venv/bin/python bin/sv_host.py --seconds 240 --player-name RyuPlayer \
  --rtt-probe --net-property --clock --net-stations 4 --scarlet-response \
  --record-set records/ --announce --announce-delay 5.25 \
  --send-at 6.00:0x7c:1:b90101b902b90280800001 \
  --send-on-open 0.15:0x7c:0:<identity fragment>:z:start \
  --trade-offer offer.hex --offer-after-open 8
```

On the console: X → Poké Portal → Link Trade → offline, no code → search. It finds the host, joins,
and its trade screen draws the offer with the usual menu.

Two things the host has to get right, both of them silent when wrong. Its identity on the trade
stream is four messages, the two zlib fragments and then the same two again, and it may not send
them until the console has announced its own key 0x80. And the `lowest_pending` field of its
acknowledgements is its own next sequence id: that field sets the peer's receive window base, so a
host that declares one past the console's last sequence walks the console's base past its own next
message, which then arrives below it and is acknowledged and thrown away without reaching the game.
See [Scarlet and Violet](docs/sv.md).

### Legends Z-A

The console's Link Trade search hosts a network of its own, so pokeldn joins it.

```bash
./.venv/bin/python bin/za_join.py --channels 1,6,11 --dwell 0.35 --seconds 900 \
  --hold 450 --quiet-seat 25 --connect-timeout 6 --game --trade-offer offer.bin --offer-delay 4

# the same joiner against an emulated console over the LAN, no radio and no root
./.venv/bin/python bin/za_join.py --ip-join --host-ip 172.16.86.1 --our-ip 172.16.86.128 \
  --comm-id ffffffffffffffff --seconds 480 --hold 450 --game --trade-offer offer.bin --offer-delay 4
```

On the console: Link Trade → local communication → search with code 00000000. The console's search
alternates between scanning and hosting; the ESP32 board usually seats on the first scan, and the
joiner rescans until one seats. Once the trade box appears, offer a
Pokémon and confirm when the joiner's shows. The joiner stays seated after a trade and answers the
next offer; back out with B.

The offer file is 354 bytes: a nine-byte header, the 344-byte record and one trailing byte.
`pokeldn.sv.pokemon.build` composes the record from zero bytes, because Z-A's layout is Scarlet's.
See [Legends Z-A](docs/za.md).

### Diagnostics

- `tools/ldn/ldn_scan.py` prints discoverable LDN networks and decoded FRLG application data.
- `tools/ldn/esp32_sniff.py` makes a second ESP32 board an air sniffer for one MAC on one channel.
- `POKELDN_ESP32_TRACE=FILE` records the board's serial traffic and counters.
- `--capture FILE` on every entry point writes the protocol trace as JSONL.

See [Host implementation](docs/frlg_host.md) for the component boundaries, protocol flow, timing
ownership and shutdown sequence.

## Credits

- [kinnay](https://github.com/kinnay): the [LDN library](https://github.com/kinnay/LDN) this is built
  upon, and the [NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki)
- [pokefirered](https://github.com/pret/pokefirered): a full decompilation of FireRed/LeafGreen,
  including the Switch port

## License

AGPLv3
