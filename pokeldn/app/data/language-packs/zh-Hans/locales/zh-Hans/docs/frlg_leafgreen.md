<a id="leafgreen-and-the-two-cartridges-offset-map"></a>
# 叶绿与两种卡带的偏移映射

本组文档其余内容基于法语版《火红》（BPRF，修订号 0x0A）的读取结果。法语版《叶绿》为 BPGF，修订号同为 0x0A（卡带标题为 `POKEMON LEAF`）。所有通信层均可直接使用，但 ROM 地址不同。测量在神秘礼物菜单内进行，因此主机始终停留在保存点。
<a id="the-measured-addresses"></a>
## 测量的地址

|符号| 叶绿| 火红 |
|---|---|---|
| `gDecompressionBuffer` | 0x0201C000 |相同|
| 神秘礼物调用点 | 0x08148C50 | 0x08148C74 |
| `Random` | 0x080486B0 |相同|
| `SeedRng` | 0x080486D0 |相同|
| `gRngValue` | 0x03004220 |相同|
| `gPlayerParty` | 0x02024280 |相同|
| `gPlayerPartyCount` | 0x02024025 |相同|
| `gEnemyParty` | 0x02024028 |相同|
| `gSpeciesInfo` | 0x0824CDD8 | 0x0824CDFC |
| `CreateMon` | 0x08041150 |相同|
| `sEasyChatGroups` | 0x083E353C | 0x083E3700 |
| `gSpecialVar_0x8000` | 0x020370B4 |相同|
| `gSpecialVars` | 0x08163984 | 0x081639A8 |
| `gSaveBlock1Ptr` | 0x03004228 |相同|
| `gSaveBlock2Ptr` | 0x0300422C |相同|

`rom_map.LEAFGREEN` 持有这些证据； `rom_map.leafgreen(symbol)` 对不在表中的符号加注，而不是回落到火红。

测量的每个 IWRAM 和 EWRAM 地址都是相同的（相同代码的链接时全局变量）； 0x080486C8 以上的每个 ROM 地址都不同。十五个符号证实了这一点；新的 ROM 符号是测量的，而不是预测的。
<a id="the-delta-by-region"></a>
## 各地址区段的偏移量

从火红地址到其叶绿孪生地址的偏移量在至少八个段上是分段常数，并且不是单调的（四个低段各自比下面的少四个字节）：

    +0x0   -0x2C   -0x28   -0x24   -0x20   -0x1C4   -0x124C   -0x1240   -0x12D8

`rom_map.leafgreen_guess(firered_address)` 仅对已测量区段返回地址，拒绝区段之间的空隙。它适合定位转储目标，不能证明目标处的内容。`pokeldn/frlg/rom/leafgreen_twins.py` 包含从两种卡带分别读取的 738 对地址（约 200 个已命名函数）；`leafgreen_twins.leafgreen(address)` 优先返回已配对的精确地址，否则回退到 `leafgreen_guess`。
<a id="the-boundaries"></a>
### 边界

    step             span                          what is in it
    0     -> -0x2c   644 B, 0x0807CF68..0x0807D1EC  title_screen.o
    -0x2c -> -0x28    62 B, 0x080DE2E4..0x080DE322  mystery_event_script.o
    -0x28 -> -0x24    90 B, 0x081480CE..0x08148128  mystery_gift.o
    -0x24 -> -0x20    31 B, 0x08251D8E..0x08251DAD  pokemon.o rodata
    -0x20 -> -0x1c4 1209 B, 0x083B7B47..0x083B8000  title_screen.o rodata
    -0x1c4 -> -0x124c  30 KB, 0x0843AFFF..0x08442800  graphics
    -0x124c -> -0x1240 17 KB, 0x08442BFF..0x08447000  graphics
    -0x1240 -> -0x12d8 63 KB, 0x0844F3FF..0x0845F000  graphics
 边界是版本分歧区域本身，其中不适用增量。跨度是与旧增量匹配的最后一个窗口与与新增量匹配的第一个窗口。 `rom_map.LEAFGREEN_DELTA_BOUNDARIES` 持有它们；测试断言边界表和段表一致。在 0x0843C800 之上，卡带保存不同的字节（特定于版本的图形），因此内容未定义增量。
<a id="measurement-methods"></a>
## 测量方法
<a id="paired-constants"></a>
### 成对常量

`RAND_MULT` 对两个卡带进行扫描，每个卡带均获得 11 次命中，在 1.3 MB 范围内按顺序配对。
<a id="a-pointer-as-the-needle"></a>
### 用指针作为扫描特征

在两个控制台上测量的每个地址的引用都是一个配对点。扫描每个卡带中的 `gSpeciesInfo` 会得到 56 个文字池引用，按升序排列，一对一配对：

| 偏移量 | 火红地址范围 | 配对命中数 |
|---|---|---|
| 0 | 0x080001BC .. 0x0805359C | 42 |
| -0x2C | 0x080CBFB0 .. 0x080CE36C | 2 |
| −0x28 | 0x080EBA14 .. 0x0813E8CC | 9 |
| −0x24 | 0x0815A3F4 .. 0x0815A630 | 3 |

0x0815A630 以上没有命中。
<a id="making-a-needle-where-there-is-no-symbol"></a>
### 在没有符号的地方做一根针

上面的 0x083E3700 没有任何东西有名字。从一台游戏机上转储 1 KB；一个单词在其中出现一次，用四个不同的字节指纹表示一个地方，扫描另一个游戏机就可以得到该地方的地址。 ROM 中任意位置的一个点运行两次：

| 火红 | 叶绿|针|偏移量 |
|---|---|---|---|
| 0x086003E0 | 0x085FF108 | 0xE1926F4D | −0x12D8 |
| 0x086803FC | 0x0867F124 | 0xC35D61AE | −0x12D8 |

每次扫描都会在 2 MB 窗口中返回一个匹配项。两个一致的点使它们之间的范围不受限制，因此需要一个控制点。脚本层扫描：

|针|取自 |发现于叶绿 |偏移量 |
|---|---|---|---|
| 0x49050B80 |里面 `ScrCmd_special` | 0x0806D7F4 | 0 |
| 0x4831D940 |处理程序块的顶部 | 0x080701C0 | 0 |
| 0x49040A00 |在 flag/var 工人内部 | 0x08071E1C | 0 |
| 0x47708008 |以上 `FlagGet` | 0x08071FC4 | 0 |
| 0x18210094 |里面 `AddBagItem` | 0x0809DA80, 火红 0x0809DAAC | −0x2C |

Delta 0 也是错误游戏机扫描的答案，因此边界上方的最后一行必须返回移位。
<a id="literal-pools-which-are-free-pointer-tables"></a>
### 文字池，即空闲指针表

函数将其接触的地址保存在其主体之后的池中，因此 1 KB 的代码窗口相当于几十个指针。如果代码的段增量已知，则可以自由地将窗口放置在两个卡带上。 m4a 代码位于 `lib_text`（-0x24 段），其池指向 ROM 顶部的声音数据。两个 1 KB 转储各提供 24 个池字，其中 13 个相同（RAM 地址和常量），并且所有五个卡带指针的移动方式相似：

| 火红 | 叶绿|偏移量 |
|---|---|---|
| 0x0847DCF8 | 0x0847CA20 | −0x12D8 |
| 0x0847DDAC | 0x0847CAD4 | −0x12D8 |
| 0x0847DF10 | 0x0847CC38 | −0x12D8 |
| 0x0849758C (`gMPlayTable`) | 0x084962B4 | −0x12D8 |
| 0x084975BC (`gSongTable`) | 0x084962E4 | −0x12D8 |

`gMPlayTable` 和 `gSongTable` 在两者上都是 0x30：四个 12 字节 `struct MusicPlayer`，如
`sound/music_player_table.inc` 成立。

两个 16 块池对给出了 550 和 288 个配对站点，并发现了 −0x20 段，该段在 −0x24 和 −0x1C4 之间跨越了超过一兆字节。按代码偏移量配对，而不是按索引配对：552 和 550 个单词的池按顺序配对，在第一次不匹配后发明增量 (−0x53BADA0)。

`bl` 是相对的，因此两个卡带上的相同指令解析为目标上的增量不同的目标； 16 KB 处理程序窗口包含 834。`tools/frlg/cartridge_pair.py` 读取池并
`bl` 位于两个卡带上的每个窗口之外：1592 个点，每个位点配对（734 个中的 734 个，834 个中的 834 个），每个窗口有四个不同的增量，没有异常值。
<a id="dumping-both-cartridges-at-the-same-address"></a>
### 将两个卡带转储到同一地址

在具有 delta d 的公共地址处，叶绿区块保存着移动了 d 的火红区块；对于|d|千字节以下，互相关直接读取d。
`memory-dump-scatter` 向两个控制台发送相同的 27 个地址。在一个块内，测试哪个增量仍然与窗口逐个窗口匹配，会向字节放置一个步骤：五个代码步骤的边界总共 2036 个字节，所有 272 个特殊字符都有一个叶绿地址。

较大的间隙可能隐藏了几个步骤：从 -0x1C4 到 -0x12D8 的 421 KB 包含三个步骤。图形与其自身相似，因此每个读数都根据替代方案进行评分：0x08442800 −0x124C 得分 436/436，−0x1240 6.9%，−0x12D8 2.7%； 0x08457000 74.7% 对 57.3% 记录为无判决。
<a id="reading-a-leafgreen-dump-against-firereds-tables"></a>
## 阅读火红桌子上的叶绿转储

这里的每张桌子都被念成火红。 `tools/frlg/rom_functions.py --console leafgreen` 通过测量的双胞胎移动条目、实体和名称，并删除落在边界内的条目：213 个现场实体中的 184 个和 252 个可放置的特殊符号中的 33 个返回，与火红相同的三个未命名呼叫目标。

0x0807AF04 (`rom_map.SHARED_WITH_LEAFGREEN_THROUGH`) 以下的两个盒上的脚本层相同：`gScriptCmdTable` 处理程序块 (0x0806D7C0..0x080700B8)、脚本引擎 (`ScriptContext_Stop`、 `ScriptJump`、`ScriptCall`、`ScriptReturn`（本机指针设置器 `callnative` 使用）、`GetVarPointer`、`VarGet`、`FlagSet`、 `FlagClear`、`FlagGet` 和
`_call_via_r0`单板。
<a id="the-overworld-and-a-shiny-mewtwo"></a>
## 主世界，还有异色超梦

[搜索存根](frlg_rng.md) 中的每个文字都是与火红共享的链接时 IWRAM 字（`gRngValue`、`gSaveBlock1Ptr`、`gSaveBlock2Ptr`），因此存根运行时未移植。 RAM 脚本需要绑定到地图对象：`initramscript` 接受地图组、地图编号和对象 ID，`GetRamScript` 运行脚本而不是对象自己的 [field_control_avatar.c:458]。华蓝洞 B1F 是第 1 组地图 74 [data/maps/map_groups.json]； 超梦是对象3 [data/maps/CeruleanCave_B1F/map.json]。
`rng-mon-hunt-both`与`setwildbattle`种类150，等级70绑定，替换超梦的脚本并立即开始定向超梦战斗（已在零售叶绿上验证异色）。

- 杂散绘制搜索适用于叶绿；存根在运行时从 `gSaveBlock2Ptr` 读取 `TID ^ SID` [asm/field/mon-seek-both.s:73]。
- 尽管 `gSaveBlock1Ptr` 在每次加载时都会重新滚动，但绑定在电源循环后仍然存在。
- 缓冲脚本不发送任何卡，并单独保留 RAM 脚本槽。神奇卡片会话将其收回：普通卡通过`InitRamScript_NoObjectEvent`重新绑定插槽，超梦自己的脚本返回。

绑定时，游戏机报告未持有神奇卡片；卡保持完整（[一个 RAM 脚本插槽](frlg_gift.md#the-one-ram-script-slot)）。
<a id="a-dumped-region-must-not-move"></a>
## 转储区域不得移动

0x03004220（`gRngValue`，每帧两转）的 `memory-dump` 在传输过程中因 *erreur de connexion* 而死亡：CRC 和发送发生在不同的帧上。帧间变化的区域转储未通过 CRC；相同大小的 ROM 区域则不然。机制和守卫：[游戏机上的代码](frlg_rom.md#repointing-the-consoles-outgoing-message)。

从高 4 个字节开始读取保存块指针。两者一起移动，通过 0..124 范围 `SetSaveBlocksPointers` 滚动 [load_save.c:75] 内的一个共享 4 对齐偏移。
<a id="the-english-build"></a>
## 英文构建

`pret/pokefirered` 在 REVISION 10（Switch 版本的修订版）上构建了这两个卡带：

    make firered_switch     -> pokefirered_switch.gba    baa452d0b24629dd7782cfc07a8984085dde1311
    make leafgreen_switch   -> pokeleafgreen_switch.gba  62b9fc77549dbc67032eb6cbd0ea6ad3b825690f
 当使用 binutils 和 `pret/agbcc` 构建时，两者都匹配 decomp 的 sha1；不匹配的版本无法使用。 ROM 从未被提交。

这是英语版：在同一地址，法语游戏机和英语版在 3.7% 的字节数上一致，因为法语字符串的长度不同。它作为来自相同来源和链接顺序的第二个卡带对，每个符号都已知。
<a id="the-offset-french-address-to-english-address"></a>
### 偏移量：法语地址到英语地址

分段常量，仅在对象在语言之间改变大小的情况下步进；代码运行长度为数十 KB，其中一次为 1.3 MB。两个独立的解读在任何地方都适用：

- 表：`gSpecials[i]`、`gScriptCmdTable[i]` 和 `gMysteryEventScriptCmdTable[i]` 在两个版本上具有相同的功能，从现有转储中获得 675 分。
- 转储：在英语 ROM 中仅出现一次的 16 字节窗口放置了相同的法语字节；一千字节的代码投票数百次，块内的一个步骤显示为两次运行。

      ./.venv/bin/python tools/frlg/english_build.py --offsets

<a id="the-control"></a>
### 控制

英语 ELF（与链接映射不同，它带有静态函数）通过偏移量命名法语地址。针对`worker_names`，每个名字都是根据游戏机自己的身体测量的：232个同意，0个不同意。 `GetBoxMonData2` 为 `__attribute__((alias("GetBoxMonData3")))` [pokemon.c:3332]；读者保留地址中的每个名字。

    ./.venv/bin/python tools/frlg/english_build.py --check
 从英文版本推断出一个名称。 `rom_map.CALLABLE` 表示调用硬件并产生效果；
`worker_names` 表示游戏机本身按源顺序调用它。 `pokeldn/frlg/rom/english_names.py` 保存了 7573 个以此方式命名的法语版函数地址 (`scripts/gen_english_names.py`)，并带有偏移量。 `rom_functions` 最后读取它们，标记为 `[english]`，因此演绎永远不会推翻游戏机命名的实体； `gen_worker_names` 通过 `with_english=False`。

177 个未命名调用目标中，158 个落在已测量的偏移区段内，因此可以命名。其余目标位于区段之间，记录在 `english_names.BRACKETED`：只有两侧偏移量之一恰好对应函数入口、另一侧不对应时，才采用该偏移命名（`[english?]`）。仍有两个目标未能命名。十多个函数体调用的另外三个目标是 `__divsi3`、`__modsi3`、`__umodsi3`，即 agbcc 的除法辅助函数。
<a id="the-english-pairs-own-delta-map"></a>
### 英语版两种卡带的偏移映射

比较的两种英语 ROM 给出了与法语版卡带测量的相同的 6 个增量，顺序为：

    +0x0   -0x2c   -0x28   -0x24   -0x20   -0x1c4
 每个步骤都位于版本不同的对象内（`title_screen.o`、`mystery_event_script.o`、
`mystery_gift.o`、`pokemon.o`），其中两个版本没有共同的符号；字节比较括号每个为 79..1606 字节。通过偏移地图，所有五个预测的法语版边界都落在硬件测量的括号内。

    ./.venv/bin/python tools/frlg/english_build.py --boundaries

<a id="traps"></a>
### 陷阱

- `.gcc2_compiled.` 符号隐藏其文件的第一个函数；跳过以 `.` 或 `$` 开头的名称。
- 填充匹配每个增量。在匹配计数之前，窗口中需要 16 个不同的字节值，或者 0xFF 填充符读取为一致。
- 偏移量（法语到英语，一盒）不是 delta（火红到叶绿）：`french delta = offsetFR - offsetLG + english delta`。
- 在任何新转储后，使用 `scripts/gen_english_names.py` 重新生成 `english_names.py`。
<a id="unusable-references"></a>
## 不可用的引用

`gSongTable`（347个`{header, ms, me}`条目）在9 KB内打包了122个歌曲头，因此它只修复了一个位置。

火红的ROM数据在0x086ABE68（最后一首歌曲头）和0x08800000之间结束：0x08800000读取所有`0xFF`，0x08E00000所有`0x00`，0x08680000是高熵数据。
