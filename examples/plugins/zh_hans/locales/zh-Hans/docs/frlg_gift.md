
<a id="mystery-gift"></a>
# 神秘礼物

神秘礼物菜单不需要宝可梦中心。 Wonder Cards屏幕上的游戏机接受神奇卡片、传送脚本、神奇新闻、来访的战斗塔训练家和直接进入队伍的宝可梦。神秘事件VM和原生ARM代码位于[游戏机上的代码](frlg_rom.md)。
<a id="the-session"></a>
## 会议

游戏机的客户端启动时显示 `{CLI_RECV, MG_LINKID_CLIENT_SCRIPT}, {CLI_COPY_RECV}`
[mystery_gift_scripts.c:15] 并执行它收到的任何 `MysteryGiftClientCmd` 数组
[mystery_gift_client.c:87]。它理解整个操作码集，因此主机可以驱动超出火红的两个 ROM 服务器脚本的流量。

    console joins  ->  SEND_PLAYER_IDS  ->  LinkPlayer block exchange  ->  one standby barrier
                                                                              |
      server -> CLIENT_SCRIPT (sClientScript_SendGameData, 32 B)
      client -> GAME_DATA     (MysteryGiftLinkGameData, 96 B)   -- validated, card flag compared
      server -> CLIENT_SCRIPT (sClientScript_SaveCard, 48 B)
      server -> CARD          (struct WonderCard, 332 B)
      server -> RAM_SCRIPT    (1024 B: the delivery bytecode, zero-padded)
      client -> READY_END     (1024 B)
                                                                              |
                                              close-link handshake  ->  disconnect
 主机发出一个 LinkPlayer 块请求，等待游戏机的有效块，发送自己的有效块，然后等待备用屏障。
<a id="framing-rules"></a>
### 框架规则

大小 0 表示 1024：`MysteryGiftLink_InitSend` [mystery_gift_link.c:55] 将其扩展为
`MG_LINK_BUFFER_SIZE` 和 `SVR_COPY_SAVED_RAM_SCRIPT` 从不设置 `ramScriptSize`
[mystery_gift_server.c:275]，因此RAM脚本和`CLI_SEND_READY_END`是完整的1024字节消息。 CRC 覆盖填充的缓冲区。

块调步没有确认。 `SEND_BLOCK_INIT` 被忽略，除非接收器的插槽是
`RECV_STATE_READY` [link_rfu_2.c:1146]，仅由游戏机的`MGL_ResetReceived`恢复。父节点自己的`MGL_HasReceived`标志立即被设置为[link_rfu_2.c:1044]；四VBlank倒计时
[link_rfu_2.c:1220] 仅适用于子节点区块。 `MysteryGiftTiming.inter_block_gap_frames` 为 36：游戏机模型每块最多占用 13 帧，没有任何内容丢失，在传输死亡之前为 16 帧。掉落的方块会让游戏机永远等待。游戏机发送遵循[镜像规则](frlg_link.md#row-one-of-the-parents-table-is-the-consoles-own-command-mirrored-back)时停顿。
<a id="modules"></a>
### 模块

根据 `pokeldn/frlg/gift/` 除非另有说明：

|文件|角色 |
|---|---|
| `mg_link.py` |成帧：6字节`{ident, crc, size}`头块+≤252字节块|
| `mg_script.py` |客户端脚本汇编器、decomp 的预设脚本、`MysteryGiftLinkGameData` 阅读器 |
| `mg_server.py` |服务器脚本解释器 (`SVR_*`) |
| `host_mystery_gift.py` |领导引擎: `tick()` → 父节点 gSendCmd, `feed_child_slot()` ← 子节点 row |
| `host_mg_app.py` |应用程序挂接在主机运行时|
| `wonder_card.py` |字节精确时拉比和传奇野兽卡/RAM 脚本构建器 |
| `stamp_rally.py` |集邮卡、邮票、激活包装纸、交付脚本 |
| `gift_composer.py` |操作定义、光标状态验证、RAM 脚本编译器 |
| `gift_registry.py` |目录 |
| `gift_to_bin.py` | `.bin` 外部 Gen-3 神秘礼物工具的导出器 |
| `pokeldn/frlg/save/save_inject.py` |使用卡、RAM 脚本和扇区校验和保存注入 |
| `bin/frlg_mg_host.py` | CLI |
<a id="running-it"></a>
## 运行它

    (them) Mystery Gift -> Wonder Cards (Recevoir) -> Friend (Ami), wait on the search screen
    (you)  POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/frlg_mg_host.py --live --phy auto \
               --keys PROD_KEYS --gift beast-cutscene --flag-id 1005
    (them) join the host when it appears; YES on the replace-card prompt if one shows
 无线收发设备设置：[ESP32 无线收发设备](hardware_esp32.md)。 `bin/frlg_mg_host.py` 每次运行服务一台游戏机，并在其离开 LDN 后停止（[主机实现](frlg_host.md)，关闭和清理）；第二台游戏机需要重新运行。 `tests/test_mystery_gift_flow.py` 对块接收门、`MGL_Receive` 和每帧一个客户端命令进行建模； `tests/test_mystery_gift_end_to_end.py` 添加受损的可靠/RFU 路径。
<a id="what-the-link-can-carry"></a>
## 链接可以携带什么

22 个客户端指令中的 3 个 [include/mystery_gift_client.h:18] 执行某些操作：

|指导 |游戏机的作用是什么？
|---|---|
| `CLI_SAVE_RAM_SCRIPT` (17) |存储字段脚本；它在下一次 NPC 交互时运行 |
| `CLI_RUN_MEVENT_SCRIPT` (15) |运行神秘事件字节码脚本，第二个虚拟机拥有自己的 17 操作码表 |
| `CLI_RUN_BUFFER_SCRIPT` (21) | `func = (void *)gDecompressionBuffer; func(&param, gSaveBlock2Ptr, gSaveBlock1Ptr)`;使用两个保存块指针执行最多 1024 字节的 ARM |
<a id="the-one-ram-script-slot"></a>
## 一个 RAM 脚本槽

游戏机拥有神奇响应或绑定的 RAM 脚本，但绝不会两者兼而有之。 `ValidateSavedWonderCard`检查卡CRC，`ValidateWonderCard`，然后`ValidateRamScript` [mystery_gift.c:186]，这就需要
`magic == RAM_SCRIPT_MAGIC`，地图组和编号 `MAP_UNDEFINED` 和 `objectId == 0xFF`
[script.c:538]。现场通过`GetRamScript(gSpecialVar_LastTalked, script)`运行RAM脚本
[field_control_avatar.c:458]，需要对话对象的坐标。
`CLI_SAVE_RAM_SCRIPT` 调用 `InitRamScript_NoObjectEvent`（MAP_UNDEFINED、0xFF [script.c:578]）；神秘事件VM的`initramscript`写入真实坐标。使用绑定脚本，卡会保留在保存中并具有良好的 CRC，但菜单将其隐藏，并且 `MysteryGift_LoadLinkGameData` 报告 `flagId` 0
[mystery_gift.c:349] (`HAS_NO_CARD`)。

下一个神奇关联重新绑定插槽（`magic` 保持 51，坐标 0xFF），卡片回来；缓冲区脚本不发送任何卡，并保留插槽。通过绑定脚本交付的普通卡会重写+0x32E0处的卡和+0x361C处的RAM脚本，两者都在一个保存扇区中，并且SaveBlock2中没有任何内容；经过测量，SaveBlock1 的 15872 个字节中有 564 个不同。

该插槽的校验和（`ramScript.checksum`，SaveBlock1 + 0x361C）是`CalcCRC16WithTable`
`sizeof(RamScriptData)`，即 1000 字节：999 个声明字节和 1 个填充字节
`InitRamScript` 首先将 [script.c:500] 归零。 `CalculateRamScriptChecksum` 通过 `250 << 2`（`0x0806D43C` BPRE、`0x0806D5A0` BPRF）。每个游戏写入的槽读回都携带 1000 字节的 CRC。 CRC 仅覆盖 999 字节的槽在第一次与其对象对话时被 `GetRamScript` 擦除
[script.c:526]。
<a id="the-gift-catalogue"></a>
## 礼品目录

`--gift NAME`; `--help` 列出标志 ID (1000..1019)。只有持有的卡才重要：相同的 ID 意味着“已经拥有此卡”(`MysteryGift_CompareCardFlags`)。

|礼物|它是做什么的 |
|---|---|
| `beast-cutscene-share` |可重复的传奇野兽过场动画；默认演示卡 |
| `celebi` |组成的50级时拉比卡|
| `porygon-tm-gift` |多边兽卡、皮皮场景、TM29 精神强念然后 TM46 小偷 |
| `solrock-stamp` / `lunatone-stamp` |一张集邮卡的两半|
| `altering-cave` |官方改变洞穴活动，移植 |
| `wish-egg`、`pokepark-egg`、`pc-japan-egg` |官方分发蛋；查看分发蛋 |
| `event-pokemon` | 3代分布宝可梦，直入队伍；查看活动宝可梦 |
| `starter-egg` |九个第一伙伴之一的蛋，由 `random` 绘制 |
| `rare-berries` |一个 谜芝果、一个 兰萨果 和一个 星桃果，各一个阶段 |
| `national-dex` | `EnableNationalPokedex`（特殊367）除非`IsNationalPokedexEnabled`（403）回答1|
| `nature-mint`、`pc-anywhere` 及其他 42 个 | GB-Link 团队卡；查看 GB-Link 团队卡 |
| `battle-count-card` |官方战斗计数卡|
| `visiting-trainer` |身份 26 的战斗塔训练家（仅限火红）|
| `mystery-event-probe` | `givenationaldex; setstatus 42; checksum`，VM自身自检|
| `mystery-event-celebi` | `givepokemon`：Lv30时拉比拿着邮件，直入大腿|
| `mystery-event-npc` | `initramscript`：将现场脚本绑定到托盘镇胖子|
| `rng-seed-reader`、`rng-rate-probe`、`rng-shiny-hunt`、`rng-mon-hunt`、`rng-mon-hunt-both`、`rng-mon-hunt-log` |参见[RNG](frlg_rng.md) |

已经持有该卡的游戏机会在没有提示的情况下单独获取神秘事件礼物。
<a id="the-legendary-beast"></a>
### 传说中的神兽

送货员的过场动画给了 兰萨果 和 枝荔果 Berries，然后是一个大师球，然后开始了由保存的启动者选择的狂野的 65 级传奇野兽战斗：

|启动器|野兽|
|---|---|
| 妙蛙种子 | 水君 |
| 杰尼龟 | 炎帝 |
| 小火龙 | 雷公 |

保存的脚本会保留，因此事件会重复。
<a id="porygon-tm-gift"></a>
### 多边兽TM礼物

一张多边兽图标卡，一个皮皮精灵，位于玩家右侧朝西三格处，TM29 精神强念，然后是 TM46 小偷，有单独的交付检查点，因此重试小偷无法复制精神强念。默认标志 ID 1007；查看器在右上角显示 `7` (`flag_id % 100`)。
<a id="the-stamp-rally"></a>
### 集邮活动

两个活动共享一张 `SUN AND MOON RALLY` 卡（念力土偶图标，两个邮票槽，显示号码 `6`，旗帜 ID 1006），按任一顺序接收。

|状态|意义|
|---|---|
| `VAR_MYSTERY_GIFT_1` | 时拉比完成光标|
| `VAR_MYSTERY_GIFT_2 = 0/1/2` | 太阳岩 缺席/活跃/收到 |
| `VAR_MYSTERY_GIFT_3 = 0/1/2` | 月石 缺席 / 活跃 / 收到 |
| `FLAG_MYSTERY_GIFT_DONE` |集会完成|
|卡收据标志|时拉比成功时同步|

每张邮票可获得 30 级太阳岩或月石；两人都获得了 50 级的时拉比，全部通过简单的 `givemon` 获得。聚会或电脑计数；如果两者都满了，则不会有任何进步。两张待处理的邮票同时交付所有三张邮票。

```text
matching =
    saved flag ID == distribution flag ID
    and max stamps == 2
    and metadata icon species == CLAYDOL

if no card:                install shared card + delivery script + selected stamp, run activation
else if not matching:      offer the toss prompt; on accept, install as above
else if stamp species or ID already exists:   HAS_STAMP, no activation
else if neither slot empty:                   NO_ROOM_STAMPS, no activation
else:                      save the stamp, run activation, STAMP_RECEIVED
```
 激活是一个神秘事件包装器（`runscript` 加上嵌入的字段脚本）。邮票仅限实时主机。 `IsStampInMetadata` [mystery_gift.c:272] 拒绝 id 或种类冲突的图章（最多 7 个）。 `CLI_SAVE_STAMP` 只写入 `cardMetadata.stampData` [mystery_gift.c:307]，避免 `CLI_SAVE_CARD` 的卡擦除。
<a id="altering-cave"></a>
### 改变洞穴

官方脚本[data/mystery_event_msg.s:325]：`addvar VAR_ALTERING_CAVE_WILD_SET, 1`，10处换行[:328]，一条消息；它以 `end` 结尾，因此每个谈话前进一组。阅读器将 9 及以上固定到表 0 [wild_encounter.c:192]。 var (0x4024) 位于 SaveBlock1 + 0x1048：

    --buffer-script save-dump --dump-block sav1 --dump-offset 0x1048 --dump-size 2
 3次会谈将其设置为3，然后GROTTE METAMO（六岛）从表3中抽取
`sSixIslandAlteringCave_4_FireRed` [src/data/wild_encounters.json]（零售火红上的 16 级戴鲁比）。

|变量 |种类 | |变量 |种类 |
|---|---|---|---|---|
| 0 | 超音蝠| | 5 | 长尾怪手|
| 1 | 咩利羊 |  | 6 | 壶壶 |
| 2 | 榛果球 | | 7 | 惊角鹿 |
| 3 | 戴鲁比 | | 8 | 图图犬|
| 4 | 熊宝宝 | | | |
<a id="distribution-eggs"></a>
### 分发蛋

三个日本发行版，从 GB-Link-Switch-LDN 携带的字节 (`web/js/gift/official.js`) 移植。每张卡都包含其分配的所有蛋，游戏机以 `random` [scrcmd.c:455] 挑选一个；蛋得到了分布的四个动作，命运般的相遇位和相遇位置 0xFF，正如原始脚本所设置的那样。抽牌前全队拒绝，牌保持开放状态。

|卡 |蛋 |
|---|---|
| `wish-egg`（纽约宝可梦中心） | 吉利蛋、催眠貘、蛋蛋、大葱鸭、袋兽、大舌头；均掌握祈愿 |
| `pokepark-egg`（PokePark 市场幻想曲）| 刺球仙人掌、龙虾小兵、太阳珊瑚、宝宝丁、负电拍拍、皮丘、正电拍拍、可达鸭、向尾喵、晃晃斑、跳跳猪、溜溜糖球、傲骨燕、咕妞妞、小果然 |
| `pc-japan-egg` (宝可梦中心日本) | 喇叭芽 (摇晃舞)、喵喵 (花瓣舞)、走路草 (寄生种子)、蚊香蝌蚪 (天使之吻) |

相遇地点为 0xFF 或设置了命运般的相遇标志时，概要界面显示“Drôle d'ŒUF de POKéMON obtenu dans un bel endroit”（在美好地点获得的特别宝可梦蛋）[pokemon_summary_screen.c:2799]。
<a id="event-pokemon"></a>
### 活动宝可梦

`--gift event-pokemon --event-pokemon NAME` 发送 Gen 3 发行版的新副本：PKHeX.Core 通过该事件的 PID/IV 方法从其自己的事件表（`EncounterGift3`，非蛋、非日本条目）中制作它，包含其训练家姓名、训练家 ID、级别、动作、持有物、奖章和命运般的相遇位，并且其合法性检查必须通过。记录在卡被保存的那一刻就通过神秘事件 `givepokemon` 进入队伍，就像 `mystery-event-celebi` 一样；满队回答状态3并且什么也得不到，并且可以再次收到卡。如果没有 `--event-pokemon`，卡会发送存储的 WISHMKR 基拉祈。

`NAME` 是训练家名称、空格和种类：`WISHMKR Jirachi`、`CHANNEL Jirachi`、
`Aura Mew`、`MYSTRY Mew`、`DOEL Deoxys`、`SPACE C Deoxys`、`ROCKS Metang`、`10 ANIV Pikachu`及其他所有`10 ANIV`品种、欧洲`10ANNIV`、 `10JAHRE`、`10ANNI` 和 `10ANIV` 发布。如果事件以多种语言发布，则发送匹配 `--language` 的事件。

这种卡片不依赖特定卡带构建：神秘事件虚拟机的 17 项命令表、其中的 `givepokemon`，以及礼物客户端 `Client_Run` 的 23 个选择分支，在全部十二种卡带上都具有相同布局。`tests/test_frlg_english_cartridges.py` 通过各卡带自身的 `RunMysteryEventScript` 执行卡片脚本（成功时返回状态 2，宝可梦记录进入队伍；队伍已满时返回状态 3，不添加记录）。

<a id="gb-link-team-cards"></a>
### GB-Link 团队卡

GB-Link Team 的自定义神奇卡片（GB-Link-Switch-LDN `cards/`，GPL-3.0）由神奇卡片和派送员 RAM 脚本组成，脚本携带通过 `callnative` 调用的 THUMB 代码。ARM 源码位于 `vendor/gblink-cards/`；`scripts/gen_team_cards.py` 为五种卡带汇编到 `pokeldn/frlg/data/team_cards.json`，`pokeldn/frlg/gift/team_cards.py` 则按卡片 ID 注册，不添加 `custom-`（`--gift nature-mint`）。使用其未修改的源码和 RAM 地址，生成器可逐字节复现全部 44 个 `BPRE 1.10` 载荷。

`starter-egg`、`rare-berries`、`national-dex` 是三张不需要原生代码的卡片，使用组合器重新构建：树果对应道具 173、174、175，全国图鉴卡片设置 `FLAG_SYS_NATIONAL_DEX`（0x840）。活动宝可梦由 PKHeX 生成（见“活动宝可梦”），但 PKHeX 表中缺失的四种除外；其跟随、大师球、加速及遭遇钩子由本项目自己的实现覆盖。

| 分组 | 卡片 |
|---|---|
| 修改宝可梦 | `nature-mint`, `ability-capsule`, `poke-ball-changer`, `pokemon-gender`, `nickname`, `stat-judge`, `hidden-power`, `hidden-power-type`, `ev-training`, `friendship`, `pp-max`, `max-conditions`, `pokerus`, `unown-letters`, `trade-evolution`, `espeon-umbreon`, `move-tutor` |
| 逐帧钩子 | `speed-2`, `speed-3`, `speed-4`, `speed-0-75`, `speed-0-5`, `fast-text`, `travel-anywhere`, `pc-anywhere`, `hm-moves`, `reusable-tms`, `physical-special-split`, `exp-share`, `shiny-hunting`, `roamer` |
| 其他 | `no-encounters`, `legendary-respawn`, `instant-eggs`, `gift-box`, `pocket-casino`, `gift-ribbons`, `trainer-ids`, `gender-swap`, `rival-name` |
| 活动宝可梦 | `box-eggs`, `colosseum-pikachu`, `ageto-celebi`, `mattle-ho-oh` |

与原构建的区别：

- 支持全部十二种修订版 `0x0A` 卡带。源码使用的 167 个地址均在英语、法语、德语、意大利语、西班牙语和日语版《火红／叶绿》ROM 上测量：函数依据唯一的指令窗口，RAM 和含指针的数据依据字面量池，场景脚本标签依据屏蔽指针后的命令序列。`vendor/gblink-cards/symbols.json` 保存全部十二张地址表；`tests/test_team_cards.py` 在每种卡带上对照 `builds.py` 检查 25 项。每个脚本都会检查卡带头中的游戏字母、语言字母和修订号。参见[卡带地址映射](frlg_rom_map.md#the-international-revision-0x0a-cartridges)。
- 重定位后的脚本（996 字节）和菜单列表（80 字节）放在 `0x0203F768` 和 `0x0203FB50`，即 newlib 的 malloc 状态区，而不放在本项目常驻钩子运行的 `0x0203FC00`；参见[载荷的可用位置](frlg_rom.md#where-a-payload-can-live)。
- 钩子卡片的安装器在复制前将 `gIntrTable[4]` 指向 `VBlankIntr`，链接到该处理器而非当前位置读到的处理器，并把它保存到本项目常驻安装器查找的 `0x0203FBFC`。钩子卡片会替换正在运行的游戏增强功能，反之亦然；两者都不会链接到过期副本。其状态位于 `0x0203FF60`，复制内容结束于该地址之前。
- 大于 1019 的卡片 ID 没有对应的 `sReceivedGiftFlags` 位；注册器为它们发送 1000 + 卡片 ID 对 20 取余后的值。
- 为使修改安装器后的内容不超过 995 字节，两段文本分别缩短四个和六个字符（`hm-moves`、`physical-special-split`）。

所有卡片均已在 mGBA 中绑定到妈妈，并在全部十二种卡带上运行检查；检查覆盖入口、消息和菜单，而非每张卡片内的所有选项。`nature-mint`、`pc-anywhere`、`rival-name` 还在法语版《火红》实机上运行过。向另一游戏版本的卡带发送载荷会回复“This gift doesn't work with this version of the game.”（此礼物不适用于这个游戏版本；日语版显示“Wrong game.”）。常驻钩子运行时，`nature-mint` 不改动 `0x0203FC00..0x02040000`，`pc-anywhere` 接管 `gIntrTable[4]`，同时在 `0x0203FBFC` 保留 `0x0800071D`。

`colosseum-pikachu` 和 `ageto-celebi` 保留日语初训家名称，在欧洲语言版卡带上显示为圆点；PKHeX 判定四只活动宝可梦均合法。

<a id="the-battle-count-card"></a>
### 战斗计数卡

`MysteryEventScript_BattleCard` [data/mystery_event_msg.s:162] 通过读取 `GET_CARD_BATTLES_WON`
`GetMysteryGiftCardStat`（特殊390）并在正好三点处给出药剂。该端口用自己的奖品变量替换了官方的 `FLAG_MYSTERY_GIFT_DONE` 门，因此它保持可重复性。

伙伴布防计数器：仅当 `BLOCK_REQ_SIZE_100` 缓冲区中 96 字节训练家卡后面的 u16 等于所持卡的标志 ID [union_room.c:1777] 时，在进入交换中心或斗兽场时，`Task_ExchangeCards` 布防 `MysteryGift_TryEnableStatsByFlagId` （`frlg_trade_host.py
--card-flag-id N`）。

|什么增量|哪里 |规则|
|---|---|---|
| `numTrades` |已完成的交换 [trade_scene.c:2609] |训练家ID卡未计算|
| `battlesWon` / `battlesLost` |电缆俱乐部之战的结束 [cable_club.c:792] |同样，每个统计记录 5 个 ID |

`IncrementCardStatForNewTrainer` [mystery_gift.c:630] 每个训练家 ID 计数一次。联合房间之战通过`CB2_ReturnToField`返回并不算什么；只有[罗马斗兽场](frlg_link.md#the-cable-club-colosseum) 可以。计数器位于 SaveBlock1 + 0x3434 (`buffer_script.SAV1_CARD_METADATA`)，读取时不进行 CRC 检查 [mystery_gift.c:490]：

    0x3434: 0000 0000 0000 2300     battlesWon 0, lost 0, trades 0, icon 35 (CARD_TYPE_GIFT)
    0x3434: 0000 0000 0100 2300     trades 1                       (CARD_TYPE_LINK_STAT)
 `CARD_TYPE_GIFT` 卡即使在武装时也保持为零。无线俱乐部的交换中心经过
`union_room.c` 的 `Task_StartActivity`，唯一在偏移 96 处写入标志 id 的构建器。
<a id="the-visiting-trainer"></a>
### 客座训练家

`CLI_RECV_EREADER_TRAINER` (18, ident `MG_LINKID_EREADER_TRAINER` = 26) 将缓冲区复制到
`gSaveBlock2Ptr->battleTower.ereaderTrainer` 并致电 `ValidateEReaderTrainer`
[mystery_gift_client.c:233]。该结构体为 188 字节 [global.h:286]：

    0x00 u8  unk0                  0x10 u16 greeting[6]            0x34 BattleTowerPokemon party[3]
    0x01 u8  trainerClass          0x1C u16 farewellPlayerLost[6]  0xB8 u32 checksum
    0x02 u16 winStreak             0x28 u16 farewellPlayerWon[6]
    0x04 u8  name[8]
    0x0C u8  trainerId[4]
 验证：前 46 个字不全为零，尾随 u32 它们的和 [battle_tower.c:1354, :1384]；故障会被默默地清除。 `SevenIsland_House_Room1` 门仅在其上：老妇人在 Room2 中提供 3v3，由 `CreateBattleTowerMon` 从结构 [battle_tower.c:928] 构建，之后愈合，可重复。此处从未调用级别规则和禁止列表 (`ShouldBattleEReaderTrainer` [:232])。

`CreateBattleTowerMon` 设置种类、项目、四个动作（来自动作表的 PP）、等级、ppBonuses、EV、IV、特性编号、otId、个性、昵称、亲密度。这些短语是六个 Easy Chat 单词；
当玩家获胜时会说 `farewellPlayerWon`。 FRLG 显示八个名称字节中的五个
[`CopyEReaderTrainerName5`, battle_tower.c:1343]。 `CLI_MSG_TRAINER_RECEIVED` (12) [strings.c:1296] 算作成功，因此游戏机保存。

`--gift visiting-trainer` 在一次会话中发送卡、RAM 脚本和训练家：无卡 → 所有三项；同一张牌→训练家单独，无抛掷提示；另一张牌 → 抛掷提示，然后全部三张。
<a id="wonder-news"></a>
## 神奇新闻

神秘礼物菜单是{神奇卡片、神奇新闻} x {无线通讯、朋友}。
`struct WonderNews` [global.h:646] 是 444 字节并且不携带标识：

|偏移|尺寸|领域 |笔记|
|---|---|---|---|
| 0x000 | 2 | `id` | `ValidateWonderNews` 唯一检查的是：它不能是 0 [mystery_gift.c:113] |
| 0x002 | 1 | `sendType` | `SEND_TYPE_DISALLOWED` 隐藏游戏机自己的“发送”选项 [mystery_gift.c:120] |
| 0x003 | 1 | `bgType` |未经验证； `WonderNews_Init` 将 `>= NUM_WONDER_BGS` 钳位至 0 [mystery_gift_show_news.c:110] |
| 0x004 | 40 | `titleText` | 居中于 224 px 窗口 |
| 0x02C | 400 | `bodyText[10][40]` |屏幕上有八行；索引 7 之后的非空行将滚动指示器 [:346] |

新闻没有 `flagId`、元数据、RAM 脚本或收据标志，并且从不查阅
`sReceivedGiftFlags`。 `IsWonderNewsSameAsSaved` [mystery_gift.c:140] 比较所有 444 个字节，因此更改一个字节即可使旧消息成为新消息 (`--news-id N`)。对抗神奇配合主机：

- 新闻接受列表包含一项活动 [`sAcceptedActivityIds_WonderNews`，src/data/union_room.h:406]：`build_wonder_news_app_data` 通告 22，而不是 21。`hasNews` 位仅在无线路径 [union_room.c:3777] 上起作用。
- 游戏机回答 `MG_LINKID_RESPONSE`（识别号 19）[mystery_gift_client.c:210]：`FALSE` = 已保存，`TRUE` = 已持有。 `sServerScript_SendNews` [mystery_gift_scripts.c:126] 在 `TRUE` 上以 `SVR_MSG_HAS_NEWS` 结尾，否则运行 `sClientScript_NewsReceived`，保存并设置奖励。 `SCRIPT_SEND_WONDER_NEWS` 放弃了领先的 `SVR_COPY_SAVED_NEWS`。
- 没有卡牌检查、投掷提示或 RAM 脚本：新闻和卡牌永远不会相互取代。

来自朋友的消息在 `ITEM_RAZZ_BERRY` 和 `ITEM_NOMEL_BERRY` 之间滚动浆果
[mystery_gift_menu.c:1367, wonder_news.c:21]，由 `CeruleanCity_House4` 中的人给出：最多 5 步，然后 500 步 [`MAX_REWARD`]。四浆果奖励需要`WONDER_NEWS_RECV_WIRELESS`，一条封闭路径。

`--news`（`--news berry`、`--news-id N`）；玩家选择神奇新闻，“输入一个？”，朋友（持有新闻的游戏机显示：A，然后接收）。一次会话的消息顺序（约18秒）：

    ident 16  sClientScript_SendGameData
    ident 17  MysteryGiftLinkGameData
    ident 16  sClientScript_SaveNews
    ident 23  MG_LINKID_NEWS - 444 bytes in three blocks
    ident 19  MG_LINKID_RESPONSE - FALSE: the console saved it
    ident 16  sClientScript_NewsReceived
    ident 20  READY_END                              -> SVR_MSG_NEWS_SENT

<a id="the-questionnaire-as-a-password-gate"></a>
## 问卷作为密码门

`SVR_CHECK_QUESTIONNAIRE` 按顺序比较四个 Poke Mart 问卷单词
[`MysteryGift_DoesQuestionnaireMatch`, mystery_gift.c:422] 转换为 `param` 为 `SVR_GOTO_IF_EQ`；没有 ROM 服务器脚本使用它。 `mg_server.gate_on_questionnaire(script)`拼接在game-data前缀之后：

    MysteryGiftServer(card, ram_script, questionnaire=phrase, denied_message="Say the words.")
    bin/frlg_mg_host.py --gift ... --questionnaire species:55,FEELINGS/60,move:177,why
 一个单词可以是英文名称、`species:N`、`move:N`、`GROUP/INDEX` 或原始 id。错误的短语通过`CLIENT_SCRIPT_DYNAMIC_ERROR`和`SVR_MSG_NOTHING_SENT`获取主机的64字节消息；没有发送或丢弃任何内容。首先测试拒绝能力：通行门看起来就像是无线门。

法语单词 id 从游戏机中读取：每个会话都会发送四个单词
`MysteryGiftLinkGameData` [mystery_gift.c:361] 和主机记录它们。

    questionnaire: POKEMON/55  done [FEELINGS/60]  MOVE_1/177  why [MISC/37]
 AKWAKWAK FURAX AEROBLAST POURQUOI：`EC_GROUP_POKEMON` 按种类索引（哥达鸭，55），
`EC_GROUP_MOVE_1` 按招式 ID (气旋攻击, 177)，英文表关于 MISC/37 是正确的，关于 FEELINGS/60 是错误的。请参阅[法语轻松聊天词汇](frlg_rom_map.md#the-french-easy-chat-vocabulary)。
<a id="what-the-console-volunteers-about-itself"></a>
## 游戏机自愿介绍自己的内容

每个会话的 `MysteryGiftLinkGameData` 都包含轻松聊天配置文件和卡片统计信息 (`CARD_STAT_BATTLES_WON` / `_LOST` / `_NUM_TRADES` / `_NUM_STAMPS`) [mystery_gift.c:361]。
`--game-data-log PATH` (`pokeldn/frlg/gift/game_data_log.py`) 将每个会话附加到 JSONL 分类帐并打印自该游戏机上一个会话以来移动的内容； `tools/frlg/game_data_read.py PATH` 读取它。计数器仅作为同一卡标志 ID 上的差异的证据。账本列出了 法语 Easy Chat 表所缺少的每个单词的名称。
<a id="save-backup-and-restore"></a>
## 存档备份与还原

“神奇卡片 → 朋友”会话可将主机的整个 128 KiB 存档芯片复制到主持端，或将 `.sav` 写入芯片并让游戏加载、保存。不会发送或替换任何卡片。两种载荷 `asm/save-backup.s`、`asm/save-restore.s` 移植自 GB-Link Team 的 `cards/savebackup.s`、`cards/saverestore.s`（`GB-Link/GB-Link-Switch-LDN`，GPL-3.0）；主持端为 `pokeldn.frlg.gift.save_transfer` 和 `bin/frlg_mg_host.py --save-backup FILE` / `--save-restore FILE`。应用在神秘礼物工具的“存档”选项卡中运行两者（[存档管理](gui.md#your-saves)）。

两者均支持全部十二种卡带。载荷中修补两个与版本相关的地址，其余存档布局共用（[存档备份与还原](frlg_rom_map.md#save-backup-and-restore)）。

<a id="the-token-coding"></a>
### 标记编码

两个方向都以标记编码传输芯片字节：字节 `n < 0x80` 后跟 `n + 1` 个原样字节；字节 `n >= 0x80` 后跟一个重复 `n - 0x80 + 3` 次的字节。连续三个或更多相同字节作为一个完整重复段处理，最多 130 个；原样字节段最多 128 个。存档大部分是 `0x00` 和 `0xFF` 重复段。

<a id="backup"></a>
### 备份

客户端脚本每轮最多重复 `CLI_LOAD_TOSS_RESPONSE, CLI_RUN_BUFFER_SCRIPT, CLI_SEND_LOADED` 32 次，然后请求下一轮脚本；主持端依据当前进度和速度，发送预计处理剩余数据所需的轮数再加一。每轮发送最多 1 KiB 标记，覆盖最多 8 KiB 芯片数据，不跨越 64 KiB 存储分区边界。芯片偏移量以 `0x5A << 24 | offset` 保存在 `client->param` 中 [mystery_gift_client.c:276]；没有 `0x5A` 的 `param` 表示会话第一轮，起点为头部字 `first`。

| 载荷中的字 | 偏移 | 值 |
|---|---|---|
| `first` | `0x004` | 第一轮开始读取的芯片偏移量 |
| `send_queue` | `0x008` | `&gRfu.sendQueue.count` |

每轮先把数据段暂存到 `gDecompressionBuffer + 0x800`，每帧处理 `0x800` 字节并返回 0，然后压缩到 `gDecompressionBuffer + 0x400`，将 `link.sendBuffer`（`param + 0x3C`）和 `link.sendSize`（`param + 0x34`）指向消息。只要 `gRfu.sendQueue.count` 不为零，该轮就返回 0：丢失的分片会在每帧发送之外重新入队，而 40 条命令的队列只在没有新数据发送时排空。

会话在一条 64 字节消息之后以 `CLI_MSG_BUFFER_FAILURE` 结束，因此主机显示消息而不保存 [mystery_gift_menu.c:1379]。中断的备份按游戏代码和训练家 ID 保留在主持端；下一次备份同一主机时，将 `first` 设置为上次停止位置。

<a id="restore"></a>
### 还原

1. 第一条消息是完整的 620 字节镜像。`install` 将其复制到 `gDecompressionBuffer + 0x400`，避开每条消息覆盖的 1 KiB 区域，并返回两个存档槽共 28 个扇区的 12 字节尾部（`+0xFF4` 处的 ID、校验和、签名、计数器）。
2. 主持端像 `GetSaveValidStatus` 一样，根据尾部找到芯片中最新的完整存档槽并制定写入计划：将文件中已加载的副本写入另一槽，计数器设为 `newest + 1`；随后按文件内容写入扇区 28 至 31（名人堂、训练家之塔）。
3. 只要待替换槽的 14 个 ID 全部通过检查，不论计数器如何，它仍可加载，因此可能选中只写了一半的槽。写入计划先擦除该槽的 ID 0 扇区，最后才写入新的 ID 0；副本完整之前，该槽始终缺少一个 ID，游戏便加载芯片中原有的副本。
4. 后续每条消息以 `b RESIDENT + 4`（`0xEA0000FF`）开头，随后是操作码。`OP_DATA`（1）携带扇区号、写入标志、u16 偏移、u16 标记长度，以及用于填充 4 KiB 暂存缓冲区的标记；扇区最后一条消息通过 `swi 0x48` 写入，并从窗口读回。读回不一致或标记导致缓冲区溢出时，会设置失败掩码中的相应位；主持端收到报告后才开始下一个扇区。
5. `OP_FINISH`（2）在没有扇区失败时调用 `LoadGameSave(SAVE_NORMAL)` [save.c:803]，并报告失败掩码和加载结果。若结果为 `SAVE_STATUS_OK`，会话以 `CLI_MSG_BUFFER_SUCCESS` 结束，主机将已加载的游戏保存到原副本所在槽；其他结果以 `CLI_MSG_BUFFER_FAILURE` 结束，主机保留原存档。

| 载荷中的字 | 偏移 | 值 |
|---|---|---|
| `b install` | `0x000` | 第一条消息的入口 |
| `b entry` | `0x004` | 后续各条消息的入口，位于 `gDecompressionBuffer + 0x404` |
| `load_game_save` | `0x008` | `LoadGameSave \| 1` |

主持端拒绝已加载副本不完整的存档，也拒绝布局不匹配的存档：日语版 SaveBlock1 短 40 字节，填零扇区的校验和无法体现这一差别，因此通过玩家自己的宝可梦（初训家 ID 与训练家一致）的语言字节（`+0x12`）判断布局。拒绝时不会写入任何数据。

<a id="what-is-measured"></a>
### 已验证的内容

离线对脚本化主机（`tests/test_save_transfer.py`）进行检查：在法语版《火红》、英语版《叶绿》和日语版《火红》上，备份逐字节还原芯片内容；备份在 40 KB 处中断后可以继续并完成；还原后，文件中的已加载副本成为芯片上最新的副本，额外扇区与文件一致，主机原副本保持完整；还原在八个扇区后中断，主机仍能加载原副本。

通过 ESP32 开发板，在法语版《火红》实机上备份用了 64 轮，从第一轮至最后一区块耗时 219 秒；文件的两个槽都完整，训练家信息与主机一致。主机显示了消息并保留原存档。

通过 ESP32 开发板，在英语版《火红》（BPRE）实机上，`--console-build auto` 根据游戏机报告的版本代码选择 BPRE，备份读取到两个完整槽位（计数器为 2 和 1）。恢复该文件写入了全部 19 个扇区，并显示成功消息。紧接着再次备份，槽位 1 中计数器为 3 的已加载副本与文件逐字节相同；槽位 0 为游戏机对已加载游戏的自行保存，计数器为 4。该副本的扇区 1 至 7 与文件不同，这些区块包含 `LoadGameSave` 重新生成的加密密钥。

第二次恢复将法语版《火红》存档写入同一英语版游戏。操作显示成功，选择 CONTINUE 后成功进入法语存档的地图。

<a id="authoring-gifts"></a>
## 创作礼物

`pokeldn.frlg.gift.gift_composer` 从不可变的 `WonderGift` 定义构建卡片和送货员脚本：

```python
MEWTWO_GIFT = WonderGift(
    slug="mewtwo-encounter",
    card=WonderCardSpec(icon_species=150, title="MYSTERIOUS ENCOUNTER",
                        body=("Visit the deliveryman.",), default_flag_id=1008),
    intro_message="A powerful presence is waiting!",
    event=GiftSpec(shareable="once"),          # or StampRallySpec(...)
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(Message("Take this."), GiveItem(1)),  # Master Ball
        DeliveryStage(ShowSprite(0, RelativeToPlayer(dx=1)), BattleLegendary(150, level=70)),
    )),
    completed_message="That mysterious encounter is over.",
)
```

`GiftSpec` 持有可重复、可共享； `StampRallySpec` 拉力槽和完成钩。一个
`DeliveryPlan`有3个序列：`WonderGift.delivery`使用`delivery`； `StampSlot.delivery` 和
`StampRallySpec.completion` 使用 `pre_stages` 和 `post_stages`；其他任何内容都会被拒绝。

编译器显示 `intro_message`，从 `VAR_MYSTERY_GIFT_1` 恢复各个阶段，并在成功集上
`FLAG_MYSTERY_GIFT_DONE` 和卡收据标志。后来访问显示`completed_message`；
`GiftSpec(repeatable=True)` 而是重置光标。
<a id="stages-and-conditions"></a>
### 阶段和条件

每个 `DeliveryStage` 都是一个检查点：失败的奖励会重新提供该阶段，并跳过之前的成功奖励。切勿将两个可能出错的奖励（`GiveItem`、`GivePokemon`、`GiveEgg`）放在一个阶段中。
`GiveEgg`取与`GivePokemon`相同的`moves=(...)`；一个可移动的蛋需要一个队伍槽，所以稍后会重试完整的队伍，而不是将其发送到电脑。第一个空位后移动 0。 `GiveRandomEgg(eggs)` 采用 `(species, moves)` 对并给出 `random` 选择的一个：一个跳转表，因此 15 个蛋，每个蛋有 4 个动作，适合一个 RAM 脚本（944 字节）。

`condition=`（`VarEquals`、`FlagSet`、`Not`、`AllOf`、`AnyOf`）在为 false 时跳过阶段的操作，但对于互斥分支，仍使光标前进。 `RequireSpecialResult(...)` 将特殊字段调用到 `VAR_RESULT` 中，进行比较，失败时显示其消息而不前进。

```python
DeliveryStage(ShowSprite(142, RelativeToPlayer(dx=1)),
              condition=VarEquals(0x4031, 0))  # VAR_STARTER_MON == Bulbasaur
DeliveryStage(BattleLegendary(243, level=65),
              condition=Not(AnyOf((VarEquals(0x4031, 0), VarEquals(0x4031, 1)))))
DeliveryStage(RequireSpecialResult(SPECIAL_HAS_ALL_KANTO_MONS, 1, "Finish the KANTO POKEDEX first."),
              GivePokemon(251, level=50))
```

<a id="writing-the-players-save"></a>
### 写入玩家的保存

`SetVar(variable, value)` 发出 `setvar` (0x16) 和 `AddVar(variable, value)` 发出 `addvar` (0x17)，两者都仅限于保存的变量（0x4000..0x40FF）或特殊变量（0x8000..0x8011）。
<a id="battles"></a>
### 战斗

`BattleLegendary` 发出 `setwildbattle`、`special StartLegendaryBattle`，然后 `end` 不发出
`waitstate`，因此在战斗移动 SaveBlock 内存后，RAM 脚本指针不会恢复（[RAM 脚本可能不会从战斗中返回](frlg_rng.md#a-ram-script-may-not-come-back-from-a-battle)）。
`BattlePokemon` 发出普通的 `dowildbattle` 信号。两者都必须是该阶段的最后一个动作。禁止在邮票槽路径中进行战斗，包括集会的共用中间；允许有条件的战斗阶段作为最终选择。
<a id="sharing"></a>
### 分享

`GiftSpec.shareable` 映射到神奇配合 `sendType` 位：

|价值|行为 |
|---|---|
| `"never"` |无法继续共享 |
| `"once"` |可以分享一次；接收游戏将卡翻转为不可共享|
| `"always"` |收到后可以继续分享|
<a id="fateful-encounter-marking"></a>
### 命中注定的相遇标记

`GivePokemon(..., fateful_encounter=True)`（和 `GiveEgg`）发出官方 Surf 皮丘对：
`setmonmodernfatefulencounter` (`0xCD`) 和 `setmonmetlocation` (`0xD2`, `METLOC_FATEFUL_ENCOUNTER` =
0xFF）[数据/mystery_event_msg.s:71]。它是选择性加入的，因此旧卡的字节是相同的。

`ScrCmd_setmonmodernfatefulencounter` 不会对其索引 [scrcmd.c:2239] 进行边界检查（`setmonmove` 钳制 [script_pokemon_util.c:144]），因此作曲家的 `LAST_PARTY_MON_INDEX` 7 一定达不到它。该索引是给定之前的队列数（`specialvar ... CalculatePlayerPartyCount`）；完整的队列会跳转到故障标签，因此发送到 PC 的 mon 永远不会被标记。

摘要屏幕的命运相遇线仅来自相遇地点
[pokemon_summary_screen.c:2665, ORed at :2799]。 `modernFatefulEncounter` 是 Misc+0x08 [include/pokemon.h:40-82] 中功能区字的第 31 位； `mon.decode_mon` 从队伍转储中读取它。
<a id="initramscript-in-the-composer"></a>
### `initramscript` 在作曲家中

`gift_composer.build_bound_script(actions)` 将composer动作编译到现场脚本中
`initramscript` 结合； `build_mevent_npc_script(actions=...)` 直接拿走它们。相同的字节码、解释器和 `ramScript` 插槽，因此物品、怪物、精灵和战斗都可以工作。没有舞台光标或收据标志：脚本以 `end` 结尾并重新运行整个脚本，因此一次性效果需要自己的效果
`SetVar` 或条件。
<a id="registration-and-validation"></a>
### 注册和验证

```python
from pokeldn.frlg.gift.gift_registry import GIFT_REGISTRY
GIFT_REGISTRY.register_definition(MEWTWO_GIFT)
```
 注册验证并编译默认flag id；运行时 `--flag-id` 再次编译。验证涵盖卡牌文本和标志、计划结构、行动范围、光标边界、独特印记、战斗布局、虚拟指针和 995 字节 RAM 脚本限制，命名该部分：

```text
example-rally.event.slots[1].delivery.post_stages[0].actions[1]: battles are not allowed in stamp-slot delivery plans
```

<a id="static-tools"></a>
## 静态工具

```bash
./.venv/bin/python -m pokeldn.frlg.gift.gift_to_bin --gift beast-cutscene --flag-id 1005 --out-dir exported-gift
./.venv/bin/python -m pokeldn.frlg.save.save_inject game.sav --gift beast-cutscene --flag-id 1005
```

`gift_to_bin` 写入 336 字节的神奇配合和 1004 字节的 RAM 脚本为
`pokemon-gen3-mysterygift-tool` 预计。 `save_inject` 将两者写入活动保存槽，重建卡 CRC、RAM 脚本 CRC 和扇区校验和，并保存 `<save>.gift.sav`（`--in-place` 覆盖）。 `--make-artifact` 在 `artifacts/` 下写入确定性 `.ram.lst`（字节、解码指令、校验和、目标、阶段摘要）。
<a id="closed-paths"></a>
## 封闭路径
<a id="wireless-communication-joyspot"></a>
### 无线通信（JoySpot）

在 RFU 序列号门处被封锁。两条路径都达到相同的礼物对话：

| |朋友|无线通讯|
|---|---|---|
|听众 | `Task_ListenForCompatiblePartners` [union_room.c:3757] | `Task_ListenForWonderDistributor` [union_room.c:3799] |
|接受 RFU 序列号 | `IsRfuSerialNumberValid` → `{0x0002, 0x7F7D}` |仅 `== 0x7F7D` [link_rfu_3.c:920] |
|选择|玩家从列表中选择 |自动连接，无需按下按钮 |
|可通过 Switch | 访问是的 |没有|

`Task_CardOrNewsOverWireless` [union_room.c:2415] 扫描，等待 120 帧，然后门候选 0：

1. `Rfu_GetWonderDistributorPlayerData` [link_rfu_3.c:917] 仅当 `partner[idx].serialNo == RFU_SERIAL_WONDER_DISTRIBUTOR (0x7F7D)` 时才保留候选，否则将其归零。
2.`groupScheduledAnim == UNION_ROOM_SPAWN_IN && !startedActivity`。
3. `HasWonderCardOrNewsByLinkGroup`：通告的`hasCard`位；如果失败，则播放 SE_BOO。
4.`CreateTask_RfuReconnectWithParent(...)`。

错误的序列会默默地使门 1 失败（无 SE_BOO）。 Switch 网桥报告 `0x0002` (`RFU_SERIAL_GAME`): Friend (`sAcceptedSerialNos` [link_rfu_2.c:240]) 列出每个候选者，而 Wireless 会忽略每个候选者。广告没有序列字段；本地 1 在四个字段之外为零：

```
50 10 | c1 cc bf bf c8 ff 00 00 | 65 ac | 00 00 00 00 | 84 15 | 00 00 00 00 00 00
TID   | uname                   | parent| unexplained | search| unexplained
```

`svc_47` [sloopsvc.c:34] 占用 `{u8 HostRfuGameData[0x10]; u8 HostRfuUsername[8]}`，24 个字节，无串行，而桥接器通过 `svc_45_rfu_link_status()` 写入候选列表。

没有从无线路径中提取 802.11 身份验证的广告（尝试了 21 次）：场景 id (0, 21, 0x7F7D)、LDN 和 Pia 应用程序版本、`0x7F7D` 的两个字节顺序，偏移量为 12、13、14、18、19、20、22，活动 (0, 4, 21)，`hasCard`，以及搜索字的位 7。保持不变：`local_communication_id =
0x01006fa0233f8000`，LDN 版本 4，通道 1，`max_participants = 2`，Pia `sysCommVer = 22`，场景 22287。

本机捕获中的 `0x1584 & 0x7F = 4 = ACTIVITY_TRADE`，并且该偏移处的活动 21 给出了好友列表和连接，因此 `record[16:18]` 处的搜索词是
`activity:7 | bit7 | version:3 | language:3 | hasCard?:1 | startedActivity:1`（版本 5 = 叶绿，语言 2 = 该捕获中的英语）。

未经测试：`local_communication_id`（更改隐藏了主机，与门无法区分），场景暴力，多变量组合。它在桥梁证据分配时重新打开
`partner[].serialNo` 来自任何可广告的内容，或者捕获 Switch 视为奇迹分发者的广告。该区块花费了零按钮路径和四浆果神奇新闻奖励。
<a id="the-e-reader-itself"></a>
### 电子阅读器本身

训练塔套装和 `CEReaderTool_SaveTrainerTower`：`ereader_screen.c` 打开
`gLinkType = LINKTYPE_EREADER_FRLG` 通过 GBA 串行链路，而不是无线适配器。
<a id="the-aurora-and-mystic-tickets"></a>
### 极光和神秘门票

票卡在 Switch 版本上没有任何作用。分发脚本位于 `data/mystery_event_msg.s:200` 中，但 Switch 版本在第一个名人堂条目上授予两张门票和两个 `FLAG_RECEIVED_*` 标志
[post_battle_event_funcs.c:52, `#if REVISION >= 0xA`]，因此完成保存脚本后是无操作的。画廊的`FL - Item AuroraTicket`脚本先测试`FLAG_RECEIVED_AURORA_TICKET`；经过名人堂后，送货员只说了一句“Merci d'utiliser le système CADEAU MYST”。并没有给出任何东西。该卡的 `iconSpecies` 是 `0xFFFF`：除 `SPECIES_NONE` 之外的任何值都会绘制一个图标，并且 `SPECIES_UNOWN_B - 1` 之后的种类会绘制 `SPECIES_NONE` 的问号
[mystery_gift_show_card.c:466, pokemon_icon.c:1102]。旧海地图是翡翠专用的 [mystery_gift.c:30]。
<a id="traps"></a>
## 陷阱

- `charmap.encode` 删除未知字符，包括换行符。断行符为0xFE； `mg_server` 的编码器在 `\n` 上拆分，在 0xFE 上合并，并拒绝第三行或比该窗口中 ROM 最长字符串更宽的行（“A WONDER CARD 已收到”，31 个字符 [strings.c:1291]）。   窗口 1 为 28 格，乘以 4 [mystery_gift_menu.c:97,524]。
- 新的税务进入 `buffer_script.py` 中的 `DUMP_SCRIPTS` 和 `DECODED_SCRIPTS` 以及启动器的 `--dump-file` 线路，或者在硬件路径未经测试时离线线束通过。
