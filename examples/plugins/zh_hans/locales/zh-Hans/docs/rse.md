
<a id="ruby-sapphire-and-emerald"></a>
# 红宝石、蓝宝石与绿宝石

红宝石、蓝宝石和绿宝石尚未推出 Switch 版本。pokeldn 根据 [pret/pokeemerald](https://github.com/pret/pokeemerald) 和 [pret/pokeruby](https://github.com/pret/pokeruby) 预先准备了支持代码，以应对任天堂将它们加入火红、叶绿所用 GBA 应用的情况。本页内容均未经实机测量。所有地址和数值来自 GBA 英文版；Switch 火红是代码位置发生变化的新修订版（`0x0A`），因此 Switch 绿宝石也可能有相同差异。

仅从源码目录运行时，应用才显示这些游戏（[尚未发布的游戏](gui.md#unreleased-titles)）；本页不出现在网站导航中。

<a id="why-the-gba-application-is-expected-to-run-them"></a>
## 为什么预计 GBA 应用能够运行它们

火红、叶绿应用已包含第三世代五种游戏代码对应的游玩报告表，其中包括红宝石的 `AXV?`、蓝宝石的 `AXP?` 和绿宝石的 `BPE?`（[游戏机代码](frlg_rom.md)）。全部十二个火红、叶绿版本列出的首个本地通信 ID 均为 `0x01006fa0233f8000`（[ROM 映射](frlg_rom_map.md)）；未指定 ID 时，启动器扫描并加入唯一存在的网络。

<a id="what-each-game-can-do-over-the-link"></a>
## 各游戏的连接功能

| | 红宝石／蓝宝石 | 绿宝石 |
|---|---|---|
| 无线适配器（RFU）代码 | 无：`pokeruby` 仅有 SIO 多人通信线代码 | 与火红相同的 `link_rfu_2.c` |
| 连接交换 | 通信线 | 与火红相同的直接大厅和联合房间 |
| 神秘礼物（神奇卡片、神奇新闻） | 无 | 与火红相同的协议和结构 |
| 神秘事件 | 通过通信线连接 e-Reader，用“神秘事件令人兴奋”启用 | 标题菜单中没有此项 |

pokeldn 的启动器使用无线适配器协议，因此能连接的是绿宝石。Switch 版会如何承载红宝石、蓝宝石的通信线连接，目前尚不清楚。

RS 通信线协议在连接层以上，与火红、绿宝石共用 pokeldn 交换引擎所需的内容：含 GameFreak 魔数的 `LinkPlayer` 记录，大小为 200、200、100、220、40 的数据块，连接命令字，以及一次交换中的三个 200 字节队伍块、220 字节邮件块和 40 字节奖章块 [pokeruby link.c, trade.c]。RS 在 `LinkPlayer` 中写入 11 字节姓名，占用了火红、绿宝石读取进度标志的字节，因此两者遇到 RS 伙伴时均会清零这些标志。

<a id="identifiers"></a>
## 标识符

| 字段 | 红宝石 | 蓝宝石 | 绿宝石 |
|---|---|---|---|
| 游戏代码 | `AXV` + 语言 | `AXP` + 语言 | `BPE` + 语言 |
| 头部标题 | `POKEMON RUBY` | `POKEMON SAPP` | `POKEMON EMER` |
| `gGameVersion` | 2 | 1 | 3 |
| `LinkPlayer.version` | `0x4002` | `0x4001` | `0x4003` |

语言字母与火红卡带相同，为 `E`、`F`、`D`、`I`、`S` 或 `J`。三个反编译项目的版本号和语言编号均相同 [include/constants/global.h:8-12]。

<a id="joining-a-host"></a>
## 加入主机

广播记录与 `RfuGameData` 布局和火红相同 [include/link_rfu.h:80-113]。搜索交换时，如果主机广播的版本不是 3，绿宝石会将其列为“尚未准备好”；只有玩家已成为冠军，且主机广播 `canLinkNationally` 时才允许连接 [union_room.c:1266-1283]。交换公告板使用相同规则 [trade.c:2514-2521]。

使用 `--version emerald`（或 `ruby`、`sapphire`）运行时，启动器会广播对应版本，并按配置设置 `canLinkNationally`、`hasNationalDex` 和 `gameClear`；它们位于广播记录（`[16:20]` 字段的第 16、17、24 位）及 NI 游戏数据（`RfuGameData` 的第 7、8、9 位）。火红、叶绿保留实机已接受的字节，这些位均清零。

<a id="trade"></a>
## 交换

线上格式与火红相同，包括连接命令、块交换顺序和大小、训练家卡片（`0x60` 处为神奇卡片 ID）。有两项规则不同。

- 没有全国图鉴时，绿宝石拒绝伙伴提供的蛋或丰缘图鉴之外的宝可梦，然后等待玩家按 A，再发送 `READY_CANCEL_TRADE` [trade.c:1585-1589]。游戏机在 `LinkPlayer.progressFlags & 0xF` 中报告全国图鉴状态。`pokeldn.rse.constants` 包含 202 项丰缘图鉴；主机会在日志中说明该游戏机拒绝哪些交换提议。
- GBA 绿宝石在交换后运行五轮待机（`trade.c` 的状态 1、41、5、8，以及交换菜单初始化）；Switch 火红运行六轮，状态 43 的一轮后调用 `svc_FinishSave`。`--save-rounds N` 设置主机等待的轮数，默认 6。如果 Switch 绿宝石通过相同系统调用保存，也会有第六轮；在实机测量前尚无法确定。

版本为 3 时，绿宝石游戏机在我方训练家卡片的 `0x3A` 处显示对战开拓区象征，在 `0x3C` 处显示对战点数；版本为 4 或 5 时显示火红卡片。绿宝石接收队列有 32 个位置，火红为 20；它除 `0x0002` 和 `0x7F7D` 外，也接受序列号 `0x0000`。

<a id="mystery-gift"></a>
## 神秘礼物

连接传输、服务器和客户端脚本、332 字节的 `WonderCard`、444 字节的 `WonderNews` 以及 `MysteryGiftSave`（`0x36C`）的字段都与火红相同。有三点差异。

绿宝石在游戏数据 `+0x0C` 和 `+0x10` 处携带礼物类型位：卡片为 4 和 `0x200`，新闻为 5 和 `0x201`；火红在此发送 1 和版本代码 [mystery_gift.c:346-363]。绿宝石检查卡片时要求第 2 位和 `0x380`，新闻则不检查 [mystery_gift.c:390]。主机根据游戏机的游戏代码选择规则，也从该代码读取版本。

礼物脚本使用的标志、变量和特殊函数编号不同。pokeldn 生成的场景脚本操作码相同，只有 `0xC7..0xCC`、`0xD0` 和 `0xD3..0xD5` 不同，绿宝石的操作码范围达到 `0xE3`。

| | 火红／叶绿 | 绿宝石 |
|---|---|---|
| 卡片 flagId 1000（`sReceivedGiftFlags[0]`） | `0x2A7` | `0x13A` |
| `FLAG_MYSTERY_GIFT_DONE` | `0x3D8` | `0x1E4` |
| 礼物游标变量 | `0x40B6..0x40BC` | `0x40DE..0x40E4` |
| 最后一个道具 | 374 | 376（`ITEM_OLD_SEA_MAP`） |
| `StartLegendaryBattle` / `GetMysteryGiftCardStat` | 312 / 390 | 314 / 392 |
| `special` 索引检查 | 由 `gSpecialsEnd` 限制 [scrcmd.c:101] | 无：527 个特殊函数 [scrcmd.c:119] |
| SaveBlock1 中的 RamScript | `0x361C` | `0x3728` |

`pokeldn.frlg.gift.gift_composer` 接受 `GameRules` 表；`pokeldn.rse.constants.EMERALD_RULES` 使用绿宝石的编号编译礼物。载荷携带目标游戏信息，主机会在发送前拒绝其他游戏的游戏机。

绿宝石的神奇新闻没有奖励：没有代码增加步数计数器，也没有脚本读取其树果。

<a id="gifts"></a>
### 礼物

pokeemerald 附带的四份官方礼物脚本（`data/scripts/gift_aurora_ticket.inc`、`gift_mystic_ticket.inc`、`gift_old_sea_map.inc`、`gift_altering_cave.inc`）在 `pokeldn.rse.gifts` 中逐条重建，使用 pokeldn 自己的文字；`tests/test_rse.py` 汇编反编译项目源码并比较字节码。宝可梦中心二楼的神秘礼物配送员运行保存的脚本（`trywondercardscript`、`CableClub_EventScript_MysteryGiftMan`）。

| 预设 | 卡片 flagId | 效果 |
|---|---|---|
| 极光船票 | 1000 | 船票与 `FLAG_ENABLE_SHIP_BIRTH_ISLAND` |
| 神秘船票 | 1001 | 船票与 `FLAG_ENABLE_SHIP_NAVEL_ROCK` |
| 古航海图 | 1002 | 航海图与 `FLAG_ENABLE_SHIP_FARAWAY_ISLAND` |
| 变化洞窟传闻 | 1003 | 切换到洞窟九套野生宝可梦表中的下一套 |
| 无限船票 | 1007 | 游戏自身的发放流程 [cable_club.inc:33]：船票与 `FLAG_ENABLE_SHIP_SOUTHERN_ISLAND` |
| 大师球、神奇糖果 x5、会冲浪的皮丘的蛋 | 1004..1006 | 使用 `EMERALD_RULES` 制作 |

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/frlg_mg_host.py --live --version emerald \
        --gift-file old-sea-map.pokegift --keys "$HOME/Documents/Switch/23.0.0 keys/prod.keys"

绿宝石礼物文件只有一个版本变体 `emerald`（[神秘礼物文件](gifts.md)）。原生代码、存档备份和火红预设使用火红地址，因此绿宝石不允许使用它们。

<a id="the-save"></a>
## 存档

闪存布局、扇区签名 `0x08012025` 和校验和与火红相同 [save.c]。SaveBlock1 大小为 `0x3D88` 字节，SaveBlock2 为 `0xF2C`。队伍数量位于 `0x234`，队伍位于 `0x238`，金钱位于 `0x490`（与 SaveBlock2 `+0xAC` 异或），标志位于 `0x1270`，变量位于 `0x139C`，游戏统计位于 `0x159C`，神秘礼物位于 `0x322C`。SaveBlock2 没有 `filler_B20`；持久保存的原生载荷需要另找位置。

<a id="emerald-link-features-pokeldn-lacks"></a>
## pokeldn 尚未支持的绿宝石连接功能

混合记录（记录角）、树果混合器、华丽大赛、对战塔联机多人对战、树果碾粉、宝可梦跳绳和嘟嘟利摘树果均通过绿宝石的无线适配器运行，连接组为 12 至 21，活动为 14 及 23 至 29。火红也包含最后三项。

<a id="unresolved"></a>
## 尚未解决

- 是否会推出 Switch 版本，以及其应用 ID、游戏代码和软件版本。
- 是否保留火红应用的通信 ID、场景 ID 和广播打包方式。
- Switch 版本如何承载红宝石、蓝宝石的通信线连接。
- Switch 绿宝石在交换后的待机轮数。
- Switch 绿宝石的全部 ROM、RAM 地址；原生代码载荷需要这些地址。
- 日版绿宝石的神秘礼物活动和卡片大小。
- Switch 是否保留绿宝石对神秘礼物菜单的游戏内解锁条件（`FLAG_SYS_MYSTERY_GIFT_ENABLE`，通过“LINK TOGETHER WITH ALL”设置 [easy_chat.c:693]）。
