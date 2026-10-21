
<a id="command-line-usage"></a>
# 命令行用法

在仓库根目录执行命令。源码工具需要 Python 3.11+、Switch 的 `prod.keys`（默认 `~/.switch/prod.keys`，或通过 `--keys PATH` 指定）及已刷写固件的 ESP32 开发板。参见[支持的开发板](hardware_esp32.md#supported-boards)与[构建和刷写](hardware_esp32.md#building-and-flashing)。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
dotnet build -c Release services/pkhex
export POKELDN_RADIO=esp32:auto
python -m pokeldn --list
python -m pokeldn --radio esp32:auto swsh-host --offer-file offer.pk8
```

交换工具还需要 .NET 10 SDK 来构建 PKHeX 辅助程序。通过 `requirements.txt` 安装仓库附带的 LDN 库，不要用 PyPI 的 `ldn` 包替代。Windows 用户在 PowerShell 中通过 `.venv\Scripts\Activate.ps1` 激活虚拟环境，并用 `$env:POKELDN_RADIO = "esp32:auto"` 设置无线后端。

`esp32:auto` 选择唯一的 USB 串口；也可用 `esp32:PORT` 明确指定。参见[无线设置和诊断](hardware_esp32.md#running)。配置文件和默认输出路径相对于工作目录解析。每个入口都支持 `--help`。

<a id="firered-and-leafgreen"></a>
## 火红／叶绿

在游戏机上解锁直接大厅，并准备至少两只 `.pk3` 同行宝可梦。

```bash
./.venv/bin/python bin/frlg_trade_join.py --live -o output.pk3 PARTY1.pk3 PARTY2.pk3   # join the Switch's trade
./.venv/bin/python bin/frlg_trade_host.py -o output.pk3 PARTY1.pk3 PARTY2.pk3          # host a Direct Corner trade
```

主持方广播队伍并引导交换，默认提供 `PARTY2.pk3`，将接收的宝可梦写入 `output.pk3`。默认配置先读取 `config/host.toml`，再读取 Git 忽略的 `config/host.local.toml`；命令行参数覆盖两者，`--print-effective-config` 显示最终配置。

1. 启动主持方，等待 `Hosting Direct Corner`。
2. 在 Switch 上进入直接大厅，加入队伍并选择 pokeldn 的训练家；等待主持方报告交换选择已激活。
3. 选择要交出的宝可梦并确认。
4. 每次交换后游戏机返回交换菜单。`--trades N`（1 到 6）在同一连接上依次提供队伍位置 0 到 N-1 的宝可梦。最后一次交换后等待主持方提示，再选择 **CANCEL**（取消）、**YES**（是），随后自动离开房间并断开连接。

| 参数 | 用途 |
|---|---|
| `--keys PATH` | `prod.keys` 的位置 |
| `--slot N` | 要提供的同行宝可梦位置，从零计数 |
| `--capture FILE` | JSONL 诊断录制 |
| `--config` / `--local-config` / `--no-local-config` | 替换或禁用某层配置 |
| `--ot NAME`、`--version firered\|leafgreen`、`--id TID[:SID]` | 单次运行的训练家覆盖值（各为 0..65535；LinkPlayer ID 为 `(SID << 16) \| TID`） |
| `--verbose` | 逐包输出，在按帧计时的循环内同步记录；只应配合 `--replay` 使用 |

[`pokeldn/config.py`](../pokeldn/config.py) 的 `DEFAULT_TRAINER` 保存没有命令行参数时使用的默认值（性别、语言、全国图鉴）。连接协议见[连接协议](frlg_link.md)。

**交流室。** `--union-room` 在中间 NPC 的通信路径上广播；保活等待约 10 秒后，游戏机显示连接成功（[连接协议](frlg_link.md)）。交流室连接只进行一次交换，随后游戏机返回场景（`union_room.c:1744`）。`--board-type normal` 将提供的宝可梦登记到交换公告板；`--union-room-chat` 配合 `--chat-message` / `--chat-file` 聊天；`--union-room-battle --battle-fight` 进行对战（游戏机需有两只等级不超过 30 的非蛋宝可梦）。

```bash
./.venv/bin/python bin/frlg_trade_host.py --union-room --union-room-keepalive 120 PARTY1.pk3 PARTY2.pk3
```

**神秘礼物。** `bin/frlg_mg_host.py` 在朋友路径广播，发送神奇卡片及分发脚本。在 Switch 上进入 **神秘礼物 → 神奇卡片 → 朋友**，再选择 pokeldn 主持方；存档必须已解锁神秘礼物。`--make-artifact` 将发送的字节写入 `.ram.lst` 清单。礼物目录、制作系统和朋友路径要求见[神秘礼物](frlg_gift.md)。

```bash
./.venv/bin/python -u bin/frlg_mg_host.py --gift beast-cutscene --flag-id 1005 --capture mystery-gift.jsonl
```

三圣兽由存档的初始宝可梦决定：妙蛙种子对应水君，杰尼龟对应炎帝，小火龙对应雷公。共享的盖章拉力赛卡片通过 `--gift solrock-stamp` 和 `--gift lunatone-stamp` 发送，顺序不限。

**神奇新闻。** `--news` 提供游戏机神秘礼物的第二栏内容（**神秘礼物 → 神奇新闻 → 朋友**）：444 字节的标题和正文，在华蓝市奖励树果。只有与已有新闻不同才会保存；`--news-id N` 可强制视为新新闻。

```bash
./.venv/bin/python -u bin/frlg_mg_host.py --news berry --news-id 7
```

**存档备份与恢复。** 同一朋友路径可以将整个 128 KB 存档复制到 `.sav` 文件，或写回 `.sav`：先写到游戏机原存档旁，再读回每个扇区，最后游戏加载并保存；任何环节未完成都保留原存档。应用神秘礼物工具的“你的存档”页可保存及命名备份、导入和导出 `.sav`，并通过 PKHeX 编辑训练家和同行宝可梦。在实体法语版火红上备份约需四分钟；实体英语版火红恢复后可通过 CONTINUE 载入，也支持法语存档。[存档备份与恢复](frlg_gift.md#save-backup-and-restore)。

```bash
./.venv/bin/python -u bin/frlg_mg_host.py --live --save-backup backup.sav --save-resume-dir partial
./.venv/bin/python -u bin/frlg_mg_host.py --live --save-restore backup.sav
```

**游戏机存档。** 神秘礼物会话在游戏机上执行原生 ARM 代码。`save-dump` 读取当前存档（秘密 ID、每只同行宝可梦的 PID、个体值和性格），不写入数据。`flash-patch` 修改单个字段：读取扇区、仅修改指定字节、重算校验和、写回并增加计数器，使游戏加载它。此操作会修改真实存档，应先阅读[从 RAM 快照组成扇区](frlg_rom.md#composing-a-sector-from-a-ram-snapshot)。载荷见[游戏机上的代码](frlg_rom.md)。

```bash
./.venv/bin/python -u bin/frlg_mg_host.py --buffer-script save-dump --dump-block sav2 --dump-size 64 --dump-file dump.bin
./.venv/bin/python tools/frlg/dump_read.py dump.bin --block sav2
./.venv/bin/python -u bin/frlg_mg_host.py --buffer-script flash-patch --flash-id 0 \
  --flash-patch-offset 0x00 --flash-patch-hex cac9c5bfc6bec8ff --write-unsafe
```

<a id="lets-go-pikachu-and-eevee"></a>
## Let's Go！皮卡丘／伊布

交换画面交替主持和扫描，因此 pokeldn 可以主持或加入。两者都发送类型 1 的身份消息：加入方使用 `pokeldn.lgpe.reference` 附带的消息；主持方回传游戏机自身消息（`--first echo`），或读取文件。两者均提供 232 字节的 PB7（`pokeldn.lgpe.pb7`；`--offer echo` 回传游戏机自己的宝可梦）。主持方的 `--next-offer` 和加入方重复的 `--offer` 为同一席位的后续交换逐次排队。加入方的 `--leave-after S` 在响应首个交换步骤 S 秒后退出，与玩家离开交换画面的方式相同；不指定则维持席位以继续交换。

```bash
./.venv/bin/python bin/lgpe_host.py --seconds 600 --player-name POKELDN \
  --first echo --our-trainer 41234:12345 --offer offer.pb7
./.venv/bin/python bin/lgpe_join.py --connect --connect-seconds 300 \
  --ack-peer-clock --ack-re-announce \
  --our-trainer 41234:12345 --offer offer.pb7
```

游戏机操作：Communiquer（通信）→ Communication locale（本地通信）→ Échange（交换），连接密码选择三个皮卡丘，在搜索画面等待。局域网内的模拟游戏机使用 `lgpe_host.py --ip-host --our-ip IP`。参见[Let's Go](lgpe.md)。

<a id="sword-and-shield"></a>
## 剑／盾

游戏机操作：YY 通信 → 连接交换 → 本地通信，在两个提示上按 A，等待在搜索画面。

```bash
# join the console's session and trade: the console's own party snapshot is sent back, rewritten
POKELDN_RADIO=esp32:auto ./.venv/bin/python bin/swsh_connect.py --keys PROD_KEYS \
  --preset trade --offer-slot 1 [--offer-file your.pk8 --offer-file next.pk8 --fresh-pid] \
  --save-offered received.pk8

# or host, and let the console join: its snapshot is taken from this trade
POKELDN_RADIO=esp32:auto ./.venv/bin/python bin/swsh_host.py --keys PROD_KEYS \
  --offer-file your.pk8 --fresh-pid --received received.pk8 --channel 6 --seconds 900
```

主持方生成自身站点广播，并重写加入游戏机的实时快照。主持时，游戏机从 YY 通信 → 连接交换 → 交换加入，并在随后两个提示上按 A；`--received FILE` 保存其发送的宝可梦，`--code 12345678` 使用连接密码主持。`--advert` 和 `--snapshot` 仍可读取保存的记录用于比较。主持方和加入方均支持重复 `--offer-file`，在同一会话中每次提供一只，玩家每次重新从盒子选择；第 N 次交换的接收文件添加 `-N`。详见[交换](swsh_trade.md)。

神秘礼物无需建立会话；礼物画面扫描时，分发方广播卡片。游戏机操作：神秘礼物 → 接收礼物 → 通过本地无线通信。

```bash
./.venv/bin/python bin/swsh_gift_host.py --species 25 --level 25 \
  --move1 84 --move2 45 --move3 86 --move4 98 --nickname POKELDN --ot POKELDN --seconds 300
./.venv/bin/python bin/swsh_gift_host.py --record card.wc8 --seconds 300
```

`--set FIELD=VALUE` 设置任意记录字段（`shiny_type=3`、`ball=1`、`held_item=236`、`iv_hp=31`、`gigantamax=1`），`--ribbon N` 添加奖章，`--dump FILE` 在不使用无线后端的情况下写出记录。道具 ID 会与道具表核对；没有对应行的 ID 可能被接受，但显示其背包条目时会使游戏中止。参见[神秘礼物](swsh_gift.md)。

<a id="brilliant-diamond-and-shining-pearl"></a>
## 晶灿钻石／明亮珍珠

pokeldn 以角色加入游戏机的交流室。游戏机操作：任意宝可梦中心 → 二楼 → 左侧接待员 → 普通“是”（不要选密码或群组选项），随后在交流室中远离墙壁等待。

```bash
./.venv/bin/python tools/ldn/ldn_scan.py --channels 1,6,11 --dwell 0.8      # see the session
./.venv/bin/python bin/bdsp_connect.py --channels 1,6,11 --count 9 --connect 5 --join 6 \
  --hold 420 --reliable-ack --reliable-sweep 3 --room-walk 15 --room-pattern fixed \
  --room-walk-steps 0 --join-avatar 0 --answer-requests --state 0 --recruiting 0 \
  --answer-talk --can-talk 0 --initiate-talk --initiate-delay 3 \
  --after-approach 0x06:0001000000 --trade-reply --complete-trade \
  --trade-template offer.pb8 --trade-nickname POKELDN --src-var 0x2B7F4C12
```

关联可能失败（`Connect failed with status code 1`）；诊断前先重试（[会话](bdsp_session.md)）。`--room-pattern fixed` 持续发送加入消息，直到游戏机询问角色状态，最多行走 `--room-walk`（上方示例为 15）。重复 `--trade-template` 在会话中每次交换提供一只，最后一只会再次提供。每次运行须用新的 `--src-var`（游戏机会记住已见过的 ID）；手动停止后，玩家需离开并重新进入房间。`--complete-trade` 允许游戏机写入存档，否则在最后一次确认前停止。角色出现并完成行走后：Y → 通信菜单 → 交换宝可梦。

若要主持，先启动主持方，再让玩家以相同方式进房间并举起交换表情（Y → 通信菜单 → 交换宝可梦）：

```bash
./.venv/bin/python bin/bdsp_host.py --offer offer.pb8 --complete-trade --capture host.jsonl
```

`--offer` 必须是合法 PB8，且 PID 不存在于存档中；重复该参数可为每次交换排队，最后一只重复提供。`--password 00000000` 主持使用此密码进入的房间。参见[晶灿钻石／明亮珍珠](bdsp.md)。

<a id="legends-arceus"></a>
## 传说 阿尔宙斯

游戏机主持交换时，会与加入的站点进行交换；站点加入较晚时，也会将主持角色交给它（[传说 阿尔宙斯](pla.md)）。`bin/pla_host.py` 主持，由游戏机通过连接密码加入；`bin/pla_join.py` 加入游戏机搜索，在同一席位上每次交换依次使用重复的 `--offer`，并在主持权交接时接管。

```bash
./.venv/bin/python bin/pla_host.py --code 00000000 --channel 6 --seconds 1800 \
  --session-update --sustain --clock --data-exchange --data-exchange-name POKELDN \
  --data-exchange-id 11223344 --game-channel --trade-box --trade-box-record offer.pa8 \
  --offer-out received.pa8
./.venv/bin/python bin/pla_host.py --ip-host --our-ip 172.16.86.128 --code 00000000 ...   # emulated console, no radio
```

游戏机操作：祝庆村的佐雯 → 交换 → 附近的人 → 相同的八位密码，选择宝可梦并确认。主持方在每次提供之间重读记录文件，并将游戏机交出的宝可梦写入 `--offer-out`（后续交换加 `-2` 等后缀）；`--trade-box-collect DIR` 保留游戏机显示或提供的所有记录，包括光标。重复 `--trade-box-record` 为每次交换排队，最后一只重复提供。`pokeldn.pla.pokemon` 可读取、写入并从 376 个零字节 `build` 记录；`pokeldn.pla.stats` 计算能力值和体型。参见[传说 阿尔宙斯](pla.md)。

<a id="scarlet-and-violet"></a>
## 朱／紫

离线连接交换搜索交替扫描和主持，因此 pokeldn 可主持（`bin/sv_host.py`）或加入（`bin/sv_join.py`）。

```bash
./.venv/bin/python bin/sv_host.py --seconds 240 --player-name POKELDN \
  --rtt-probe --net-property --clock --net-stations 4 --scarlet-response \
  --record-delay 0.17 --announce --announce-delay 5.25 \
  --send-at 6.00:0x7c:1:b90101b902b90280800001 \
  --trade-offer offer.hex --offer-after-open 8
```

游戏机操作：X → 宝可入口站 → 连接交换 → 离线、无密码 → 搜索。重复 `--trade-offer` 在同一席位每次交换提供一只。线路层要求（身份消息顺序、确认值 `lowest_pending`）见[朱／紫](sv.md)。

两者也支持本地太晶团体战。`--raid-seed` 主持供游戏机加入的团体战（宝可入口站 → 太晶团体战，连接密码 4970）：种子与四个上下文参数决定首领；`--raid-reward
ITEM:QUANTITY` 替换奖励；`--raid-pokemon` 指定 pokeldn 玩家携带的宝可梦。`--raid-event FOLDER` 改为从宝可入口站新闻分发生成首领和奖励，活动来自 Project Pokemon 的 [EventsGallery](https://github.com/projectpokemon/EventsGallery)，可按需由应用下载和更新。`--raid-players N` 允许最多三台游戏机加入；指定数量全部进大厅并准备完毕，或大厅倒计时结束时开始。`--raid-partner TRAINER` 选择填补空位的 NPC 搭档，每个空位最多指定一次（一台游戏机时有两个空位）；未指定时由游戏机按主持方剧情进度随机安排。`bin/sv_join.py --raid-pokemon FILE` 加入游戏机主持的团体战。两种角色下，pokeldn 玩家在对战开始时离开，宝可梦仍与游戏机的宝可梦并肩战斗。应用的两个太晶团体战工具均提供相应参数，参见[太晶团体战](sv_raid.md)。

<a id="legends-z-a"></a>
## 传说 Z-A

连接交换搜索交替主持和扫描，pokeldn 可加入或主持。游戏机操作：连接交换 → 本地通信 → 用密码 00000000 搜索。加入方持续扫描，直到取得席位。

```bash
# host: start it first, then search on the console
POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/za_host.py --keys prod.keys --trade-offer offer.bin --capture zh.jsonl
# join
./.venv/bin/python bin/za_join.py --channels 1,6,11 --dwell 0.35 --seconds 900 \
  --hold 450 --quiet-seat 25 --connect-timeout 6 --game --trade-offer offer.bin --offer-delay 4
```

在交换盒子选择宝可梦，看到对方的宝可梦后确认。两种角色都可在同一会话响应下一次提供；重复 `--trade-offer` 为每次交换排队。完成后按 B 退出；游戏机离开时主持方关闭。`--offer-out FILE` 保存游戏机提供的宝可梦。局域网的模拟游戏机使用 `za_host.py --ip-host --our-ip IP --comm-id ffffffffffffffff` 和 `za_join.py --ip-join --host-ip IP --our-ip IP --comm-id ffffffffffffffff`。提供文件为 354 字节（九字节头部、344 字节记录、一个尾字节）；Z-A 的布局与朱相同，因此用 `pokeldn.gen9.build` 组成记录。参见[传说 Z-A](za.md)。

<a id="diagnostics"></a>
## 诊断

- `tools/ldn/ldn_scan.py` 列出可发现的 LDN 网络；`esp32_sniff.py` 可将第二块开发板作为单一信道、单一 MAC 的无线监听器。
- `POKELDN_ESP32_TRACE=FILE` 记录开发板串口流量和计数器；每个入口的 `--capture FILE` 都将协议录制写为 JSONL。
- [主持方实现](frlg_host.md)：组件边界、协议流程、时序与关闭。
