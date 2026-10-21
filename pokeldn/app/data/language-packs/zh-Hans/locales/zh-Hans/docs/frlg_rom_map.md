
<a id="the-rom-map"></a>
# ROM 映射

这里的每个地址都是通过神秘礼物链接（`memory-dump`、`memory-scan`、`table-scan`、`call-chain`，在[游戏机上的代码](frlg_rom.md)上）从游戏机自己的盒带上读出的。
`pokeldn/frlg/rom/rom_map.py`记录了每个是如何获得的； `tests/test_rom_map.py` 根据转储检查它。卡带图像与每一个都一致。

地址为法语版《火红》，卡带BPRF，软件版本0x0A。 叶绿位于[叶绿](frlg_leafgreen.md)。
<a id="the-cartridge-image"></a>
## 卡带图像

Switch 版本将 GBA ROM 作为其 RomFS 中的唯一文件。

|标题 ID | RomFS 文件 |尺寸| sha1 |
|---|---|---|---|
| 01004B3023412000 | `/FireRed_f.gba` | 16777216 | `07566b82dbd2a91321698f730f6400ae4c56ddf1` |
| 010087C02342E000 | `/LeafGreen_f.gba` | 16777216 | `9f774956dfbad7f69ddb91fb91d2c26e54408f75` |
| 0100554023408000 | `/FireRed_e.gba` | 16777216 | `baa452d0b24629dd7782cfc07a8984085dde1311` |
| 010034D02340E000 | `/LeafGreen_e.gba` | 16777216 | `62b9fc77549dbc67032eb6cbd0ea6ad3b825690f` |

0xA0 处的标头读取为 `POKEMON FIRE` `BPRF` 和 `POKEMON LEAF` `BPGF`，版本 0x0A。

法语版《火红》 1.0.1 更新使卡带保持不变：其客户 ROM（通过 `rom-checksum` 在实机上读取）和一个不同延伸的字节读取，等于 `FireRed_f.gba` 到 `0x08000000..0x09000000`，除了包装器的三个加载时补丁之外([frlg_rom.md](frlg_rom.md),断点钩子); `0x09000000..0x0A000000` 读取两者上的开放总线（每个半字其自身地址减半）。

英文对（`BPRE`、`BPGE`、版本 0x0A、基本 v0 包）的字节相同
`pokefirered_switch.gba` 和 `pokeleafgreen_switch.gba` 作为 `pret/pokefirered` 固定它们：分解是英文版本的精确地图。

程序NCA有一个CTR RomFS部分并且没有更新，因此`bktr_read.py`拒绝它；
`scratchpad/base_romfs.py` 读到：

    ./.venv/bin/python scratchpad/base_romfs.py "$NSP" --list
    ./.venv/bin/python scratchpad/base_romfs.py "$NSP" --extract /FireRed_f.gba --out scratchpad/FireRed_f.gba

`rom_map.CREATE_MON` 是 0x08041150，图像上写着 `f0b5 4746 80b4 87b0`，序言
`asm/create-mon.s` 依靠。任何函数体都可以从图像中离线读取。
<a id="ewram-is-at-the-same-addresses-in-both-builds"></a>
## EWRAM 在两个版本中位于相同的地址

英语版的 EWRAM 符号是法语卡带的 EWRAM 地址。三个独立测量符合`pokefirered_switch.elf`：

    gDecompressionBuffer  0x0201C000
    gPlayerParty          0x02024280
    gPlayerPartyCount     0x02024025
 IWRAM 不传输：`gSaveBlock1Ptr` 在英文版中是 0x030042D8，在卡带上是 0x03004228。

从该区域中减去 ELF 中每个大小的 EWRAM 符号，留下一个跨度无符号声明（`nm -S pokefirered_switch.elf`、`scratchpad/ram_survey.py`）：

    highest symbol end   0x0203FBAC
    EWRAM end            0x02040000

<a id="the-english-cartridges"></a>
## 英文卡带

神秘礼物主持端为英语版《火红》（`BPRE`）和《叶绿》（`BPGE`）分别使用各自的地址构建代码。`pokeldn/frlg/rom/builds.py` 为每种卡带保存一张表（`BPRF`、`BPGF`、`BPRE`、`BPGE`、`BPRS`、`BPGS`、`BPRD`、`BPGD`、`BPRI`、`BPGI`、`BPRJ`、`BPGJ`），包含 IWRAM 全局变量、载荷或钩子或场景桩代码调用的 ROM 函数、`call-chain` 中命名的函数，以及礼物携带的 ROM 数据指针。

主持端根据主机 `MysteryGiftLinkGameData` 中的游戏代码选择地址表 [mystery_gift.c:369]；该数据会在发送任何依赖地址的内容之前到达。不同版本字节不同的载荷会分别构建；没有地址表，或被当前运行排除的主机（`--console-build CODE`，或 `--version` 指定了另一版本），会在不发送任何内容的情况下被拒绝。与版本无关的载荷可发送到任意主机。

英语版地址来自 `pokefirered_switch.elf` 和 `pokeleafgreen_switch.elf`，逐一对照零售版镜像检查：函数依据字节内容，IWRAM 全局变量依据使用它的字面量池，并与法语版卡带中对应的字面量池配对。

| 区域 | 法语版到英语版的偏移 |
|---|---|
| EWRAM | 不变 |
| IWRAM 0x03000000..0x03001B6F | 不变 |
| 英语版 IWRAM 0x03002370..0x0300602F，从 `gMain` 开始（法语版为 0x030022D0，英语版为 0x03002380） | +0xB0 |
| 英语版 IWRAM 0x03006090..0x03007583，从 `gSoundInfo`（法语版为 0x03005F80）到 `gFlash` | +0x110 |
| IWRAM 0x03007590 及以上：栈和中断向量 | 不变 |
| ROM | 不存在统一偏移；逐个查找函数 |

英语版数值：`gRngValue` 0x030042D0、`gSaveBlock1Ptr` 0x030042D8、`gSaveBlock2Ptr` 0x030042DC、`gIntrTable[4]` 0x030027E0、`gLastWrittenSector` 0x03004650、`gSaveCounter` 0x03004660。英语版《叶绿》的 RAM 与英语版《火红》相同；常驻钩子使用的地址中只有 `m4aSoundMain` 改变（0x081E07C4 对应 0x081E07E8）。

`tests/test_frlg_english_cartridges.py` 通过各卡带自身的 `Client_RunBufferScript`，在两个零售版镜像上执行英语版载荷；`scratchpad/frlg_en/` 中没有镜像时跳过。

英语版《火红》（USA v0，`0100554023408000`）在游戏数据中报告 `BPRE`，能接收并显示神奇卡片，也能运行英语版 `call-chain`：`0x08046A41` 处的 `SpeciesToNationalPokedexNum` 对种类 277 返回 252，`0x08071CD5` 处的 `VarGet` 正常返回。已在模拟主机上验证；两种会话均以成功消息结束并触发保存 [mystery_gift_menu.c:1379]。

<a id="the-bios-wrappers"></a>
## BIOS 包装器

`libagbsyscall.s` 按照分解顺序 [src/libagbsyscall.s] 作为 THUMB `svc N ; bx lr` 对的一个块进行链接，在两个卡带上相同，0x24 在叶绿上较低：

|包装|服务中心 | 火红 | 叶绿|
|---|---|---|---|
| `ArcTan2` | 0x0A | 0x081E21D4 | 0x081E21B0 |
| `BgAffineSet` | 0x0E | 0x081E21D8 | 0x081E21B4 |
| `CpuFastSet` | 0x0C | 0x081E21DC | 0x081E21B8 |
| `CpuSet` | 0x0B | 0x081E21E0 | 0x081E21BC |
| `Div` | 0x06 | 0x081E21E4 | 0x081E21C0 |
| `LZ77UnCompVram` | 0x12 | 0x081E21E8 | 0x081E21C4 |
| `LZ77UnCompWram` | 0x11 | 0x081E21EC | 0x081E21C8 |

游戏的 LZ77 流是 VRAM 安全的（复制距离为 1）：火红上 0x08D2FBD4（676 字节）处的妙蛙种子正面精灵和 0x08D2FE78（40 字节）处的调色板是 `gbagfx` 从解压缩源中逐字节写入的内容。 LZ77 不收缩 PBS 代码（常驻挂钩变大或更大）；它仅支持超过 1024 字节的数据。
<a id="the-first-anchor"></a>
## 第一个锚点

`anchors`返回`Client_RunBufferScript`调用后的地址，`0x08148C75`。从它到达每个其他地址：调用者的文字池和 `bl` 目标命名下一个函数，它命名的指针表提供更多，并且每个条目必须落在已知的序言（`scratchpad/rom_read.py`）上。

0x08148A00 处的转储在 0x08148C74 处反汇编为 `Client_RunBufferScript` [mystery_gift_client.c:274]、`cmp r0,#1`。它的文字池：

    0x08148C88 -> 0x0201C000   gDecompressionBuffer
    0x08148C8C -> 0x0300422C   &gSaveBlock2Ptr
    0x08148C90 -> 0x03004228   &gSaveBlock1Ptr

`MysteryGiftClient_CallFunc` 在 0x08148C94 后面，并从 0x0845DBD0 (sClientFuncs) 复制由 `client->funcId` 在 `[r0,#8]` 索引的八个字。所有八架飞机均降落在 `push {r4, lr}` 上；条目7是0x08148C61，测量的函数是`anchors`。

转储到 0x08000000 的卡带标头确认 `REVISION >= 0xA` 分支运行：

    entry      b 0x08000204
    title      POKEMON FIRE          [0xA0]
    game code  BPRF                  [0xAC]  BPR = FireRed, F = French
    version    0x0a                  [0xBC]
    header checksum 0x5d, recomputed 0x5d -> VALID

<a id="the-four-function-tables"></a>
## 四个函数表

    gScriptCmdTable              0x08163650   214 entries   the field script commands
    gSpecialVars                 0x081639A8    21 entries
    gSpecials                    0x081639FC   444 entries   gSpecialsEnd 0x081640EC
    gStdScripts                  0x081640EC    10 entries
    gMysteryEventScriptCmdTable  0x081DE144    17 entries

`script_data` 从 0x08163650 运行到 0x081DE188，其中 `lib_text` 开始。
<a id="gspecialvars-found-by-shape"></a>
### `gSpecialVars`，通过形状找到

它的前十二个字每个都比之前的字高出 2 个：`gSpecialVar_0x8000` 到 `0x800B` 是十二个连续的 `u16` [event_data.c:16]。 `table-scan` 返回运行的起始值和一次运行中的第一个值：`gSpecialVars` = 0x081639A8、`gSpecialVar_0x8000` = 0x020370B4，这是唯一一次以 2.75 MB 大小运行的运行。该范围来自链接顺序：`script_data` 遵循每个 `.text` 对象 [ld_script_rev10.ld:318]，并且 `.rodata` 从 `gSpeciesInfo` 下面开始。 `gSpecialVar_0x8000` 是
`EWRAM_DATA`，链接时全局安全命名为常量。
<a id="gscriptcmdtable"></a>
### `gScriptCmdTable`

`script_data` 以 `gScriptCmdTable`（214 个四字节条目）打开，并将 `gSpecialVars` 放在其后面 [ld_script_rev10.ld:318]，因此它从 0x08163650 开始，并且一个 856 字节转储读取它。所有 214 个字都是指向 10488 字节范围的 THUMB 指针；唯一两个共享地址的是 0 和 213，这两个
`ScrCmd_nop`，其中 `ScrCmd_nop1` 为 1。读取一个条目关闭无法产生该结果。

    0x23 callnative   0x0806D854      0x44 additem      0x0806DED0
    0x25 special      0x0806D7EC      0x79 givemon      0x0806F834
    0x29 setflag      0x0806E0EC      0x90 addmoney     0x0806F998

`pokeldn/frlg/rom/scrcmd_names.py` 通过操作码命名每个条目； `scrcmd_names.handler("additem")` 离线回答。
<a id="gspecials-and-gstdscripts"></a>
### `gSpecials` 和 `gStdScripts`

`ScrCmd_special` 使用 u16 对 `gSpecials` 进行索引，针对 `gSpecialsEnd` 进行边界检查，并通过胶合板 [scrcmd.c:101] 进行调用。它的文字池给出 `gSpecials` = 0x081639FC 和 `gSpecialsEnd` =
0x081640EC：0x6F0 = 444 × 4，`data/specials.inc` 的 444 个条目，从 `gSpecialVars + 21 * 4` 开始。该调用通过 0x081E2224，即 `_call_via_r1` 下面的四个字节。转储提供了 444 个 THUMB 指针，其中 171 个 `NullFieldSpecial` 索引了两个转储中的一个地址。 `rom_map.SPECIAL_ADDRESSES` 持有它们；
`rom_map.special_function("HealPlayerParty")` 按名称解析一个。

`gStdScripts` 遵循 `data/event_scripts.s` 中的 `gSpecials` 已满足的 `.align 2` ，位于
0x081640EC：0x081A76xx..0x081AB5xx 中的十个字，五个 msgbox 脚本彼此相差四十个字节。
<a id="gmysteryeventscriptcmdtable-via-a-live-struct"></a>
### `gMysteryEventScriptCmdTable`，通过实时结构

该表的 17 个条目是不相关的地址，但其地址保存在一个结构体中：

```c
static void InitMysteryEventScript(struct ScriptContext *ctx, u8 *script)
{
    InitScriptContext(ctx, gMysteryEventScriptCmdTable, gMysteryEventScriptCmdTableEnd);
```

[mystery_event_script.c:52]。 `struct ScriptContext` 将这对保留在 +0x5C 和 +0x60 [include/script.h] 处，间隔 68，上下文为 `EWRAM_DATA static struct ScriptContext
sMysteryEventScriptContext` [mystery_event_script.c:27]。 `table-scan --table-delta 0x44 --table-runlen 2` 通过 EWRAM 找到它；扫描必须在同一启动中跟随神秘事件礼物，因为在脚本运行之前上下文为零。

86 个调用中的所有 256 KB EWRAM 均命中一次，在 0x0203AA94 处持有 0x081DE144：
`sMysteryEventScriptContext` = 0x0203AA38，表 = 0x081DE144。这 17 个条目是奇数、不同的，位于 `.text` 内部，跨度 1084 字节，并且遵循 `mystery_event.OPCODE_NAMES` 的顺序：

| ＃|命令 |处理程序 | | ＃|命令 |处理程序 |
|---|---|---|---|---|---|---|
| 0 | `nop` | 0x080DE451 | | 9 | `givenationaldex` | 0x080DE61D |
| 1 | `checkcompat` | 0x080DE401 |  | 10 | `addrareword` | 0x080DE641 |
| 2 | `end` | 0x080DE3F5 |  | 11 | `setrecordmixinggift` | 0x080DE66D |
| 3 | `setmsg` | 0x080DE465 |  | 12 | `givepokemon` | 0x080DE681 |
| 4 | `setstatus` | 0x080DE455 | | 13 | `addtrainer` | 0x080DE78D |
| 5 | `runscript` | 0x080DE49D |  | 14 | `enableresetrtc` | 0x080DE7D5 |
| 6 | `initramscript` | 0x080DE5B5 |  | 15 | `checksum` | 0x080DE7E9 |
| 7 | `setenigmaberry` | 0x080DE4B9 |  | 16 | `crc` | 0x080DE831 |
| 8 | `giveribbon` | 0x080DE581 | | | | |

`data/mystery_event_script_cmd_table.o(script_data)` 是 `script_data` [ld_script_rev10.ld:318-330] 的最后一个成员； 0x081DE188 读为 `0x4C41B510`，`push {r4, lr}`，序言
`libgcnmultiboot`，第一个在`lib_text`。
<a id="from-a-table-entry-to-the-function-behind-it"></a>
## 从表项到其背后的函数

处理程序采用 `struct ScriptContext *` 并从脚本中读取其参数。按地址顺序排列的 `bl` 目标是按源顺序排列的 decomp 调用（每个参数 `VarGet(ScriptReadHalfword(ctx))`，然后调用 [scrcmd.c:463-590]），因此一个转储按位置命名工作人员：

    ScriptReadHalfword   0x0806D1E8      AddBagItem           0x0809DA70
    VarGet               0x08071DDC      RemoveBagItem        0x0809DBC4
    GetVarPointer        0x08071CC8      CheckBagHasSpace     0x0809D9EC
    FlagSet              0x08071EF4      CheckBagHasItem      0x0809D92C
    FlagClear            0x08071F1C      AddPCItem            0x0809DDB4
    FlagGet              0x08071F44      IncrementGameStat    0x080587A4

`ScrCmd_additem` 与指令的反编译指令匹配（`(u8)quantity` 转换为
`lsls r1, #24; lsrs r1, #24`）并通过0x020370CC、`gSpecialVar_Result`存储。 `ScrCmd_random`的第三个调用是0x080486B0，`Random`，独立于它自己的文字池找到。

`scratchpad/handler_workers.py` 按顺序打印每个处理程序的 `bl` 目标，并命名已知的目标。
`tools/frlg/rom_functions.py --table specials|field|mystery-event|callable` 在表格中执行此操作，通过下一个条目及其自己的尾声将每个正文界定，并打印下一次运行的计划：未保留的条目聚集到排名的 `--dump-address` 窗口中。

ROM 是 agbcc 构建的，并结束 THUMB 函数 `pop {r4,r5,r6}; pop {r1}; bx r1` (BC70 BC02 4708)，而不是 `pop {..., pc}`。只寻找 0xBDxx 的读者会进入下一个函数。
`pokeldn/frlg/rom/thumb.py` 也与 `bx Rn` 匹配，并且仅当序言跟随时才将返回视为边界。
<a id="naming-300-workers-offline"></a>
### 命名 300 名离线工人

`scripts/gen_worker_names.py` 压缩每个转储的正文以进行解压缩，同时压缩所有四个表，并写入 `pokeldn/frlg/rom/worker_names.py`。四项检查：

|检查 |它排除了什么|
|---|---|
|长度|内联，`__umodsi3`，宏读取为调用 |
|锚|未对齐的主体：每个测量的地址都必须返回到它自己的名称 |
|协议|两个调用者以不同方式命名的目标 |
|链接订单| ROM 中的名称位于错误位置 |

在 164 个对齐的实体中，锚点检查落在 68 个不同的测量名称上，共 557 次，每个名称都有自己的地址。 agbcc 按定义顺序发出翻译单元，`ld_script_rev10.ld:53` 按布局顺序列出对象，因此名称和锚点形成一个升序序列；检查保留最长的上升链，而不是第一个中断。

两个锚点之间的间隙恰好包含一个未命名的目标和一个源调用，这是强制的，并放宽了长度规则。一个开放的间隙（在第一个锚点之前，在最后一个锚点之后）没有任何名称。

阅读源码：

- `firered_switch` 是 `GAME_VERSION=FIRERED GAME_REVISION=10 MODERN=0` [Makefile:227]：203 `#if REVISION >= 0xA` 块是活动的，它们的 `#else` 不是活动的。
- 评估是后序的：`VarGet(ScriptReadHalfword(ctx))` 是 `bl ScriptReadHalfword`，然后是 `bl VarGet`。
- 宏不是调用：`#define ScriptReadByte(ctx) (*(ctx->scriptPtr++))` [include/script.h:24] 不发出 `bl`，它出现在 151 个主体中。
- `NDEBUG` 成立：`ScrCmd_special` 对卡带进行两次调用，并且断言将添加第三次调用。

分解也有 `rom_map` 名称，由到达该地址的每个主体确认（`rom_map.DECOMP_NAMES` 是连接）：

| `rom_map` 名称 |分解|机构同意|
|---|---|---|
| `GET_MON_DATA` | `GetMonData3` | 15 |
| `SCRIPT_CONTEXT_SET_NATIVE` | `SetupNativeScript` | 11 |
| `SET_RESPAWN` | `SetLastHealLocationWarp` | 1 |
| `SCRIPT_MOVEMENT_START` | `ScriptMovement_StartObjectMovementScript` | 2 |
| `CHANGE_AMOUNT_MONEY_BOX` | `ChangeAmountInMoneyBox` | 2 |
| `ME_CHECK_COMPATIBILITY` / `ME_SET_INCOMPATIBLE` | `CheckCompatibility` / `SetIncompatible` | 1 / 3 |

`GetMonData` 是一个根据参数计数进行调度的宏 [include/pokemon.h:343]； `GetMonData2` 是
`__attribute__((alias("GetMonData3")))` [pokemon.c:2970]：一个地址，三个名称。

一个工作人员通过与 decomp 所说的调用完全相同的命令到达，已得到确认：`Compare` 由八个 `compare_*` 命令到达，`StringCopy` 由七个 `buffer*` 加上两个从 `gText_BigGuy` 构建名称的特殊命令到达。 `0x0806D0EC`是`StopScript(ctx)` [script.c:76]、`ScrCmd_end`的调用； `ScriptContext_Stop(void)` [:360] 是 0x0806D418，由十二个处理程序和整个
除 `return TRUE` 外，还有 `ScrCmd_waitstate`。
<a id="two-mixed-image-hazards"></a>
### 两种混合图像危险

- 切勿将两个卡带的转储读取为一张图像。 叶绿保留此代码−0x2C，因此放置在其火红`--dump-address`处的叶绿转储会错误地回答：混合图像将`gSpecials[54]`的（`Script_HasTrainerBeenFought`，`FlagGet(GetTrainerAFlag())`）调用读取为`FlagSet`，这是`SetBattledTrainerFlag2` 位于 +0x2C。 `script_read.every_dump` 从运行的 `--expect-console` 中取出一个卡带（默认为火红），落回标签。
- 立即阅读每个转储。 `scrcmd.Memory` 合并重叠和相邻的转储，因此跨越两条跑道的块仍然可以行走（`tools/frlg/script_read.py --with-every-dump`）；一次转储建议运行已保存的字节。
<a id="what-is-measured"></a>
### 测量什么

每个表后面的每个主体都在卡带之外：213 个字段命令、17 个神秘事件操作码、27 个可调用函数、272 个特殊函数。

- `NullFieldSpecial` 是 `bx lr`，两个字节，位于 0x080CE8DC。
- 特殊变量按 id 顺序排列，每个字节两个字节：`ShakeScreen` [310] 加载 0x020370BC、BE、C0、C2，并且解压缩的读取为 `gSpecialVar_0x8004..0x8007`； `GetPlayerXY` [143]写入前两个，`GetPartyMonSpecies` [327]读取第一个。
- `GetLeadMonIndex` at 0x080CE818 不在表中；四个主角特价称之为它。
- 全局的一载专用名称：`GetBattleOutcome` [180] 为 `ldr; ldrb; bx lr`，其池字为 `gBattleOutcome`。同样给出了 `gStringVar1`、`gStringVar4` (`ShowFieldMessageStringVar4` [141])。
- 表格交叉核对：特价商品名称为 0x08081CC8 `DoDiveWarp` 和 0x08081DA0 `DoFallWarp`，与经纱工人一样； `CalculatePlayerPartyCount`是特殊131和`ScrCmd_getpartysize`的一通电话；   `GetPlayerFacingDirection`是特殊287和`ScrCmd_faceplayer`的第一个。

神秘事件虚拟机的工作人员：

|工人|地址 |呼叫者 |
|---|---|---|
| `StringExpandPlaceholders` | 0x0800CADC |每个留下消息的处理程序的最后一次调用 |
| `RunScriptImmediately` | 0x0806D438 | `runscript`，在`ScriptReadWord`之后，没有别的了|
| `InitRamScript` | 0x0806D5F0 | `initramscript` |
| `GiveGiftRibbonToParty` | 0x080A43B0 | `giveribbon`，两个中的第一个 |
| `EnableRareWord` | 0x080C1658 | `addrareword`，两个中的第一个 |
| `CheckCompatibility` | 0x080DE300 | `checkcompat`，分支前|
| `SetIncompatible` | 0x080DE330 | `checkcompat`的其他；死操作码所做的唯一调用
| `memcpy` | 0x081E44F4 | `addtrainer`，第二次通话 |
| `CalcCRC16` | 0x080489A0 | `crc`，其唯一的工人 |
| `StringCopyN` | 0x0800C8CC | `setenigmaberry` 和 `givepokemon`，各两次 |
| `StringCompare`、`SetEnigmaBerry` | 0x0800C938, 0x080A01B0 | `setenigmaberry` |
| `VarSet` | 0x08071DF8 | `setenigmaberry`，最后一次通话 |
| `SpeciesToNationalPokedexNum` | 0x08046994 | `givepokemon` |
| `GetSetPokedexFlag` | 0x0808C860 | `givepokemon`，两次：看到然后捕获 |
| `ItemIsMail`、`GiveMailToMon2`、`CompactPartySlots` | 0x0809BB18、0x0809B964、0x080971FC | `givepokemon` |

0x081E44F4 处的 `memcpy`（libgcc，在 `lib_text` 中）位于 0x081DE188 之上，与边界一致。

`VarSet` 只能从这里访问：没有 ScrCmd 主体调用它（`setvar` 通过存储
`GetVarPointer` 的结果，因此 `call-chain` 的 `prev`）。 `event_data.c` 声明 `GetVarPointer`，
按 `VarGet`、`VarSet` 的顺序，0x08071CC8 < 0x08071DDC < 0x08071DF8；最后两者之间的0x1C是`VarGet`的本体。

调用胶合板为 `bx rN` 加对齐，每个四个字节：r0 0x081E2224、r1 0x081E2228 和 r3
0x081E2230 测量，因此 0x081E2234 是 `_call_via_r4` 和 0x081E223C `_call_via_r6`。
<a id="save-backup-and-restore"></a>
## 存档备份与还原

各卡带的 `LoadGameSave` [decomp:src/save.c:803] 和 `gRfu.sendQueue.count` [link_rfu_2.c:3131]，在屏蔽 `bl` 目标和字面量池中的字后，与英语版修订号 0x0A 的 ELF 匹配。全部十二种卡带中，`LoadGameSave` 都打开 `push {r4-r6, lr}; lsls r0, r0, #24`（`70 b5 00 06`），并在字面量池中引用 `gDecompressionBuffer`、`0x0201C000`。队列计数由 12 字节叶函数 `ldr r0, =gRfu; ldr r1, =0x8D2; adds r0, r0, r1; ldrb r0, [r0]; bx lr` 读取，每种卡带各有一份。

| 卡带 | `LoadGameSave` | `gRfu` | `gRfu.sendQueue.count` |
|---|---|---|---|
| `BPRE` | `0x080DDBF4` | `0x03005590` | `0x03005E62` |
| `BPGE` | `0x080DDBC8` | `0x03005590` | `0x03005E62` |
| `BPRF` | `0x080DDFD4` | `0x030054E0` | `0x03005DB2` |
| `BPGF` | `0x080DDFA8` | `0x030054E0` | `0x03005DB2` |
| `BPRD`, `BPRI` | `0x080DDF14` | `0x030054E0` | `0x03005DB2` |
| `BPGD`, `BPGI` | `0x080DDEE8` | `0x030054E0` | `0x03005DB2` |
| `BPRS` | `0x080DDFFC` | `0x030054E0` | `0x03005DB2` |
| `BPGS` | `0x080DDFD0` | `0x030054E0` | `0x03005DB2` |
| `BPRJ` | `0x080DED68` | `0x03005520` | `0x03005DF2` |
| `BPGJ` | `0x080DED3C` | `0x03005520` | `0x03005DF2` |

全部十二种卡带的 `sSaveSlotLayout` 一致，只有扇区 ID 4 不同：拉丁字母语言版为 3816 字节，日语版为 3776 字节。

<a id="reading-the-consoles-scripts"></a>
# 阅读游戏机的脚本

使用 `gScriptCmdTable` 测量的和从反压缩宏生成的操作数宽度（`scripts/gen_scrcmd_args.py` → `pokeldn/frlg/rom/scrcmd_args.py`：每个 `.macro` 将其操作码作为
`.byte`，然后每个参数一个 `.byte`/`.2byte`/`.4byte`），`memory-dump` 加上 `scrcmd.disassemble` 读取盒中的任何脚本：

    0x081A7624  6A  lock
    0x081A7625  5A  faceplayer
    0x081A7626  67  message 0x00000000
    0x081A762B  66  waitmessage
    0x081A762C  6D  waitbuttonpress
    0x081A762D  6C  release
    0x081A762E  03  return
 这是 `Std_MsgboxNPC` [data/scripts/std_msgbox.inc]。证明是每个脚本停止的地方：从每个 `gStdScripts` 条目开始的遍历必须在下一个条目之前的字节处以终止符结束；任何地方的宽度错误都会使其失去同步。
<a id="the-conditional-macros"></a>
## 条件宏

十一个宏有条件体。生成器遍历每个分支并在未知的子宏上引发。

|命令 |宽度|结构|
|---|---|---|
| `applymovement` | 7 字节 | `.ifb \map` 分公司 |
| `waitmovement`、`removeobject`、`addobject` | 3字节| `.ifb \map` 分公司 |
| `applymovementat`、`waitmovementat`、`removeobjectat`、`addobjectat` | 9、5、5、5 字节 |备用分支|
| `warp` 和其他八个经线 | 8 字节 | `formatwarp` 子宏 |
|十个 `buffer*` 命令 | 4 字节 | `stringvar` 子宏 |
| `showobjectat`、`hideobjectat`、`resetobjectsubpriority` | 5 字节 | `map` 子宏 |
| `trainerbattle` | 6 + 4..16 字节 |类型相关的分支 |

`warp` 是 `.byte 0x39` 那么 `formatwarp`：一条指令，被调用者内联。那么 `giveitem` 就是 `loadword`
`callstd`：两条指令，从未内联。仅当通过宏的每条路径都以其自己的文字操作码字节开始并且没有到达其他命令宏时，宏才是命令宏。

`trainerbattle`有一个类型头、trainer和localId，然后是类型选择的一到四个指针。是`scrcmd_args.VARIABLE`；分解十之外的类型使 `scrcmd.shape` 答案为 `None`。

0x081A7699..0x081A77A3 是 `data/scripts/trainer_battle.inc`。宏使 `applymovement` 为 7 个字节，`waitmovement` 为 3 个字节；将它们读取为固定宽度命令会使区域不同步。正确阅读：

    0x081A76A8  4F  applymovement 0x800F, 0x081A77B0     @ VAR_LAST_TALKED, Movement_RevealTrainer
    0x081A76AF  51  waitmovement 0x0000
    0x081A76B2  26  specialvar 0x800D, 0x0036            @ VAR_RESULT, Script_HasTrainerBeenFought
 即 `EventScript_TryDoNormalTrainerBattle` [data/scripts/trainer_battle.inc:8]。该区域是首尾相连的标签，并给出了七个边界测试； `goto` 与 `end` 和 `return` 一起是终止符，因为 `EventScript_NoTrainerBattle` 位于 [:17] 后面的字节上。五个标准脚本只使用了七个固定宽度的命令，太少了，不足以证明表格；训练家战斗区域的所有 266 字节都是 `tests/test_script_cmd_table.py` 中的固定装置。
<a id="naming-the-operands"></a>
## 命名操作数

`tools/frlg/script_read.py DUMP.bin --base ADDR`:

    0x081A76A8  4F  applymovement 0x800F (VAR_LAST_TALKED), 0x081A77B0
    0x081A76B2  26  specialvar 0x800D (VAR_RESULT), 0x0036 (Script_HasTrainerBeenFought)
    0x081A76BC  06  goto_if 0x05 (!=), 0x081A76CD
    0x081A76C2  25  special 0x0038 (PlayTrainerEncounterMusic)

- 0x4000 或更大的操作数在任何命令中都是变量引用：`VarGet` 返回 `VARS_START` 以下的数字不变，并读取其以上的变量 [event_data.c:235、`GetVarPointer`:214]。 `additem 0x8004` 给出 `VAR_0x8004` 中保存的项目 ID。   `pokeldn/frlg/rom/symbol_names.py` 具有 274 个 var 和 1470 个标志名称，根据 `include/constants/vars.h` 和 `flags.h` 进行评估。
- 索引到达的表来自宏参数名称：`scrcmd_args.PARAMS` 命名每个操作数（`special` 的为 `function`，`setflag` 的为 `flag`）。 `function` 被共享：`ScrCmd_special` 将 u16 读入 `gSpecials`，`ScrCmd_callstd` 将 u8 读入 `gStdScripts`。
- `goto_if 0x05` 是 `!=`：`sScriptConditionTable` 的行是 <、=、>、<=、>=、!= [scrcmd.c:65]。

改变洞穴计数器在SaveBlock1 + 0x1048处移动； `GetVarPointer` 是 `vars[idx - VARS_START]`，因此是 var 0x4024、`VAR_ALTERING_CAVE_WILD_SET`。 `tests/test_script_symbols.py` 保存着它的名称。
<a id="following-a-script-to-what-it-reaches"></a>
## 遵循脚本达到的目的

`scrcmd.follow` 从一组入口点追踪每个 `goto`、`call`、`goto_if` 和 `call_if`，并收集转储未保存的每个到达的地址。报告数据指针（`text`、`movements`、多选列表），但从未跟踪。 `scrcmd.dump_plan` 将失误变成
`--dump-address` 线，最大的捕获第一。

`charmap.decode` 用于名称（固定宽度，无控制代码，未知字节如 `.`）；对话需求
`charmap.decode_message`。 `scrcmd.data_pointers` 和 `scrcmd.read_string` 解码转储所保存的内容。所有十个标准脚本都是从游戏机、代码和文本中读出的。

一个已知命令的操作数超过转储的末尾意味着转储很短，读者也是这么说的。
<a id="the-species-table"></a>
# 种类表

`gSpeciesInfo` = 0x0824CDFC，步幅 28。

解压缩 26 字节步长处的 `friendship`、`growthRate` 和 `eggGroups` 的针与 16 MB 中的任何内容都不匹配；卡带的步幅为 28。数据与英文分解相符：`CalculateMonStats`
[pokemon.c:2095] 根据五个队伍的种族值、等级、IV、EV 和性格重新计算，再现了 30 个存储统计数据中的 30 个。

梦幻、时拉比和基拉祈的所有六个种族值均为 100，因此 `0x64646464` 位于入口偏移量 0 和 2 处，其中一个无论步幅如何都是字对齐的：

    scan: 3 match(es) for 0x64646464 in 0x08000000..0x08400000
       0x0824DE80   0x0824E970   0x0824FAB8
 间隙 2800 和 4424 分别是 28 字节的 100 和 158 个条目。基址前 60 字节的转储读取 34 个条目中的 34 个条目（884 字节），与分解相同；两个额外字节是每个条目上的 `00 00` 填充。

分解建模中的陷阱：`[SPECIES_NONE] = {0},` 是一个单行块，被多行正则表达式吞没，
`genderRatio` 是宏 `PERCENT_FEMALE(x)`，`noFlip` 是不总是设置的位域，十六进制
`#define`s 转义仅包含小数的正则表达式。
<a id="finding-createmon-from-it"></a>
## 从中找到`CreateMon`

扫描 `0x0824CDFC` 发现每个文字池包含 `&gSpeciesInfo`: 31 个命中
`0x08028000..0x08048800`，低于 `Random`，位于 0x080486B0。五个正好相距`0x14`，一个函数有几个池子，所以计数没有证据；对象边界是。最大的间隙 (37 KB) 位于下面
`battle_ai_switch_items.c:88`，不在 `pokemon.o`。下一个间隙 15.6 KB 是
`src/battle_controller_link_opponent.o`，从未引用 `gSpeciesInfo`。

`pokemon.o`的块的第一个命中是`CreateMon` [pokemon.c:1755]，指令指令：

|符号|地址 |如何|
|---|---|---|
| `CreateMon` | `0x08041150` |拆解|
| `ZeroMonData` | `0x08041090` |它的第一个电话|
| `CreateBoxMon` | `0x080411C0` | ZeroMonData 和 SetMonData 之间的调用 |
| `SetMonData` | `0x08043A78` |使用 56 (`MON_DATA_LEVEL`) 调用，然后使用 255 (`MAIL_NONE`) 调用 64 (`MON_DATA_MAIL`) |
| `CalculateMonStats` | `0x08041B78` |最后一次通话|
<a id="the-spanish-firered-cartridge"></a>
## 西班牙语版《火红》卡带

西班牙语版《火红》基础版 v0（`0100EB702342C000`，显示版本 1.0.0）包含 `FireRed_s.gba`，游戏代码为 `BPRS`，修订号为 0x0A。16 MiB ROM 的 SHA-256 为 `d4dee5aeb5313e073d6067bee37278b0204886958467633978bb746bbe3d5b76`。其软件包的四个 NCA 签名、节头哈希、PFS0 和 IVFC 区块哈希及 CNMT 内容哈希均通过验证。控制信息中的标题为“Pokémon FireRed Version (Spanish Ver.)”和“Pokémon Edición Rojo Fuego”。

`builds.BPRS` 提供原生礼物、活动宝可梦和常驻钩子的西班牙语版地址。`vendor/gblink-cards/symbols.json` 提供 167 个卡片符号；生成器的语言 ID 为 7。主持端发送载荷前，根据主机游戏数据选择 `BPRS`。西班牙语版《叶绿》（`BPGS`）也有独立测量的地址表，见[修订号 0x0A 的国际版卡带](#the-international-revision-0x0a-cartridges)。

函数先通过唯一的函数体窗口，与字节一致的英语版反编译结果匹配，再通过屏蔽指针字和 THUMB BL 操作数后的指令序列匹配。RAM 或数据指针从对应已映射函数的字面量池中读取。多个短函数可能具有相同指令序列，需要额外引用来区分：`IsEnoughMoney` 在 0x080A376C 调用 `GetMoney`；0x080469A8 处的 `SpeciesToNationalPokedexNum` 读取 0x0824B9DE 处的表，种类 277 对应项返回 252。各地址分别查找，单一版本内部的 ROM 偏移也并不统一。

| 符号 | 西班牙语版《火红》 |
|---|---|
| `gRngValue`, `gSaveBlock1Ptr`, `gSaveBlock2Ptr` | 0x03004220, 0x03004228, 0x0300422C |
| `gMain`, `gIntrTable[4]`, `gSoundInfo` | 0x030022D0, 0x03002730, 0x03005F80 |
| `VBlankIntr`, `Client_RunBufferScript` | 0x0800071C, 0x08148CD0 |
| `CreateMon`, `GetMonData3`, `Random` | 0x08041164, 0x080432F8, 0x080486C4 |
| `CB1_Overworld`, `CB2_Overworld`, `RunTextPrinters` | 0x08059E5C, 0x08059EDC, 0x08002D50 |
| `m4aSoundMain`, `ReadFlash` | 0x081E089C, 0x081E224C |
| `MapGridGetElevationAt`, `MapGridGetCollisionAt` | 0x0805C658, 0x0805C6D8 |
| 居合斩、碎岩、怪力的消息返回指针 | 0x081C1909, 0x081C19FD, 0x081C1AE6 |

场景招式返回指针位于脚本的八字节 `loadword` 和消息调用序列之后。徽章检查指向 0x081C1901、0x081C19F5、0x081C1ADE 处的消息脚本。翻译后文字长度不同，会改变消息与恢复执行脚本之间的距离。

全部 44 张卡片均在该 ROM 上，通过模拟的主持端与客户端对话接收，并在 mGBA 中绑定到妈妈执行。随附的四倍速卡片跳板将 0x0203FC01 安装到 `gIntrTable[4]`，并在 0x0203FBFC 保存 0x0800071D。按下 R、释放、再次按下时，分别分发三、三、零组额外地图回调，以及四、四、零次文字处理；每帧仍调用一次原始 VBlank 处理器（`tests/test_team_cards.py`）。

`tests/test_frlg_english_cartridges.py`、`tests/test_noclip.py` 和 `tests/test_follower.py` 包含 `scratchpad/frlg_es/FireRed_s.gba` 处的西班牙语版镜像；镜像不存在时跳过依赖 ROM 的检查。卡带自身的神秘礼物客户端能从训练家探测代码返回，生成语言为 7 且校验和有效的皮卡丘，调用 `GetVarPointer`，安装常驻钩子，并加载存档中的钩子。碰撞和跟随检查也使用西班牙语版地址表执行。

<a id="the-french-easy-chat-vocabulary"></a>
# 法语 Easy Chat 词汇

所有 1006 个与语言相关的 Easy Chat 单词均从游戏机的 ROM 中读出。
`pokeldn/frlg/text/easychat_french_words.py`是表； `easychat_french.french(id)`从中得到答案。
<a id="the-slot-problem"></a>
## 插槽问题

Easy Chat id 是 `(group << 9) | index`，一个槽位。 `pokeldn/frlg/text/easychat_words.py` 来自英文 decomp，命名英文 ROM 中保存的内容；每个本地化 ROM 都有自己的
`gEasyChatGroup_*` 表。邮件、训练家卡提议、客座训练家台词、
`--denied-message`和问卷门都依赖于法语版的。在游戏机上渲染，
`EC_WORD_ENJOY` 渲染为 STRESSE，`EC_WORD_DONE` 渲染为 FURAX，`SPEECH/12` 渲染为 LES。
<a id="finding-the-table"></a>
## 查找表

`sEasyChatGroups[]` 是 22 个条目
`struct EasyChatGroup { const void *wordData; u16 numWords; u16 numEnabledWords; }` [src/data/easy_chat/easy_chat_groups.h:26]，每个 8 个字节。第 8、9 和 10 组（结局、感受、条件）包含 69 个字，其中 69 个启用，因此 `0x00450045` 出现 3 次，间隔 8 个字节。
`--buffer-script memory-scan --scan-word 0x00450045` 超过 0x08000000..0x08480000 准确地返回了这三个命中。范围：`src/easy_chat.o(.rodata)` 是 `ld_script.ld` 中的对象#99，如下
`src/mystery_gift_client.o(.rodata)`（#182，`sClientFuncs` 已知）。该表位于 0x083E3700。

所有 22 个条目的计数与英语版的计数相同，因此两种语言中的 id 是相同的槽。字数组及其文本跨越 0x083DE2C8..0x083E3700，21560 字节，每个组的字符串位于其数组和下一个数组之间。 `string-gather` 每次运行读取一组；条目 42 和 60 是渲染时的 STRESSE 和 FURAX。 `tests/test_easychat_french.py` 需要渲染和 ROM 证据才能同意。

`TRAINER/11` 是 DRESSEUR，单数； DRESSEURS 不在表中。
<a id="what-the-table-says"></a>
## 表中内容

与英文表的差异取决于组别：

- `EC_GROUP_STATUS`（109 个特性名称）几乎准确：`stench`→PUANTEUR，`thick_fat`→ISOGRAISSE，`rain_dish`→CUVETTE，`drizzle`→CRACHIN， `arena_trap`→PIEGE，`rock_head`→TETE DE ROC，`air_lock`→AIR LOCK。
- `EC_GROUP_FEELINGS` 几乎完全重新分类：英语混合了动词（meet、play、eat、drink、see、hear、got、gos、go home），法语仅保留情感状态。插槽 13 (`disappoints`) 是 RAVI，44 (`eat`) HUMILIE，51 (`drink`) HONTEUX。
- `EC_GROUP_SPEECH`：`but`→MAIS，`however`→CEPENDANT，`how`→COMMENT，`the`→LE排队，LES和L'在`case`上获得英语支出， `miss`。

专有名词组几乎没有区别；普通词汇差异很大。

807 插槽无需读取：`EC_GROUP_POKEMON`、`POKEMON_2`、`MOVE_1` 和 `MOVE_2` 打印自
`gSpeciesNames` / `gMoveNames` [easy_chat.c:155]，由游戏机本地化。 `easychat.species_word(55)` 和 `easychat.move_word(177)` 构建它们； `easychat.is_language_safe` 识别它们。
<a id="using-it"></a>
## 使用它

```python
from pokeldn.frlg.text import easychat, easychat_french
easychat_french.french(easychat.WORDS["enjoy"])     # 'STRESSE', not 'enjoy'
easychat_french.render(ids)                          # the line as the console will print it
easychat_french.check(ids, strict=True)              # raises on anything unread
```

`check` 捕获不是单词的 id，例如超出其组末尾的索引。

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/frlg_mg_host.py --live --keys PROD_KEYS \
        --buffer-script string-gather --gather-address 0x083DF5C0 --gather-count 42 \
        --gather-stride 12 --dump-file DUMP.bin --version firered    # one group per run
    ./.venv/bin/python scratchpad/ec_words.py --group 4 DUMP.bin
    ./.venv/bin/python scratchpad/ec_words.py --report

`scratchpad/ec_locate.py` 在扫描答案中找到该表，并根据 decomp 的计数检查转储；
`scratchpad/ec_words.py` 保存 22 个字数组地址。

叶绿的整个 Easy Chat 区域比火红移动了 −0x1C4，具有相同的词汇：22 个条目，每个计数相等，并且一组的 `string-gather` 在相同的槽中读取相同的单词。
`easychat_french` 两个控制台的答案。
<a id="the-international-revision-0x0a-cartridges"></a>
## 修订号 0x0A 的国际版卡带

六种语言版本各包含一个 16 MiB GBA ROM，卡带头修订号为 `0x0A`。主持端为英语、法语、德语、意大利语、西班牙语和日语的两个游戏版本均提供地址表。

函数依据唯一指令窗口与英语版修订号 0x0A 的 ELF 配对，必要时屏蔽相对调用和指针字面量。RAM 全局变量和指针表从对应字面量池读取。场景招式脚本按命令序列配对，屏蔽其中 ROM 指针；本地化文字位于这些序列之后。`SpeciesToNationalPokedexNum` 与两侧相邻的转换函数一起配对，因为三个叶函数具有相同的指令序列。

| 卡带 | ROM 文件 | SHA-256 |
|---|---|---|
| `BPRD` | `FireRed_d.gba` | `04f43a43f7cf9109561cd1744d108f50202c931ce31b30abaa6f18950824d20d` |
| `BPRE` | `FireRed_e.gba` | `d32c8df8702293716ad8de68755fe5903161f4829a0a2e486bfa7e74a0b62e94` |
| `BPRF` | `FireRed_f.gba` | `9edf7a3137536b0ccf024a732025da9a0ea1330eb9fd13b2ffed19f5e008c147` |
| `BPRI` | `FireRed_i.gba` | `cf7fa25cf57fbf12f24709efdd1d1aa8056efb4e9b6520ac7d068d3de13ff135` |
| `BPRJ` | `FireRed_j.gba` | `e2cdfb0415ef09e887e9d27b925ff02a713a92f004843490cf6b88b68db6cd01` |
| `BPRS` | `FireRed_s.gba` | `d4dee5aeb5313e073d6067bee37278b0204886958467633978bb746bbe3d5b76` |
| `BPGD` | `LeafGreen_d.gba` | `eb0e340b5efb3ccb7bab104183d2050fa834261dd816c5ad8221e4e98c04342b` |
| `BPGE` | `LeafGreen_e.gba` | `993a8a5695a4f7e4dfe8ceec55beb43e020e82b492854d457d4aa3f864d20f08` |
| `BPGF` | `LeafGreen_f.gba` | `751346c16c0cf3a3ec601d6c2d3c482b54609c5d00ca74f2f668d75b31b8efde` |
| `BPGI` | `LeafGreen_i.gba` | `b99b9c58c83a61b5bd8a1a69b6f21ce0cfab8d1f6065b53b81a323801c9b2895` |
| `BPGJ` | `LeafGreen_j.gba` | `a2aa939a23a36610902be51169042efac78f2f6db6a433e06443a2ee09d4f19e` |
| `BPGS` | `LeafGreen_s.gba` | `a943ecfd6560115b184dc244daed71ba328a67334f343eb35b39932c3ce7c731` |

| 符号 | 德语版《火红》 | 德语版《叶绿》 | 意大利语版《火红》 | 意大利语版《叶绿》 | 西班牙语版《叶绿》 |
|---|---|---|---|---|---|
| `gmain` | `0x030022D0` | `0x030022D0` | `0x030022D0` | `0x030022D0` | `0x030022D0` |
| `sb1ptr` | `0x03004228` | `0x03004228` | `0x03004228` | `0x03004228` | `0x03004228` |
| `sb2ptr` | `0x0300422C` | `0x0300422C` | `0x0300422C` | `0x0300422C` | `0x0300422C` |
| `rng` | `0x03004220` | `0x03004220` | `0x03004220` | `0x03004220` | `0x03004220` |
| `vblank_intr` | `0x08000730` | `0x08000730` | `0x08000730` | `0x08000730` | `0x0800071C` |
| `create_mon` | `0x08041178` | `0x08041178` | `0x08041164` | `0x08041164` | `0x08041164` |
| `client_run_buffer_script` | `0x08148BA4` | `0x08148B80` | `0x08148BE4` | `0x08148BC0` | `0x08148CAC` |
| `save_slot_layout` | `0x083FCEC0` | `0x083FCCFC` | `0x083F464C` | `0x083F4488` | `0x083F7674` |

依赖 ROM 的测试运行每种受支持卡带的 `Client_RunBufferScript`、`CreateMon`、`GetVarPointer`、`VBlankIntr` 和已保存钩子的加载器。碰撞测试在安装钩子后调用卡带的 `MapGridGetCollisionAt` 和 `MapGridGetElevationAt`。

西班牙语版《火红》的 `EventScript_CurrentTooFast` 起点为 `0x081AA346`，含有 `lockall`（`0x69`）。旧卡片表指向其后的 `0x081AA347`，即 `loadword`（`0x0F`）。现在生成的秘传招式卡片使用脚本真正的入口。

<a id="japanese-layout"></a>
### 日语版布局

日语版《火红／叶绿》采用不同的 EWRAM 布局：队伍起点为 `0x020241E0`，玩家角色为 `0x02036FA8`，对象事件为 `0x02036D68`，调色板渐变为 `0x020379E8`，禁用野生遭遇的字节为 `0x02038624`。`0x08002D38` 处的 `RunTextPrinters` 从 `0x08002D60` 处的字面量读取数组指针 `0x02020030`，并在 `0x08002D94` 按 `0x20` 步长前进。国际版数组的步长为 `0x24`。

两种日语版卡带均使用 `0x030022E0` 处的 `gMain`、`0x03004238` 处的 `gSaveBlock1Ptr`、`0x0300423C` 处的 `gSaveBlock2Ptr`、`0x03004230` 处的 `gRngValue` 和 `0x03002740` 处的 `gIntrTable[4]`。`gSpecialVar_0x8000` 为 `0x02036FE8`，队伍数量位于 `0x02023F85`。

日语版 SaveBlock1 为 `0x3D40` 字节，国际版为 `0x3D68`。最后一区块，即扇区 ID 4，在日语版覆盖 `0xEC0` 字节，国际版覆盖 `0xEE8` 字节。存档注入和原生闪存修补使用所选卡带的长度。`RamScript` 保留其偏移：校验和 `0x361C`、魔数 `0x3620`、脚本主体 `0x3624`。依赖 ROM 的校验和测试从各 ROM 的 `sSaveSlotLayout` 读取区块长度。

日语版神奇卡片占 164 字节，神奇新闻占 224 字节。`BPRJ` 的 `0x081481F4` 处 `SaveWonderCard` 复制 164 字节并计算校验和；`BPGJ` 使用 `0x081481CC`。对应验证例程为 `0x08148250` 和 `0x08148228`。依赖 ROM 的测试通过两个例程保存并验证应用生成的卡片。卡片 CRC 位于 SaveBlock1 `+0x3204`，数据位于 `+0x3208`；新闻数据始于 `+0x3124`。`0x08149934` 处的 `BufferCardText` 读取字节 10..27 的标题、28..40 的副标题、41..120 的四行各 20 字节正文，以及 121..160 的两行各 20 字节页脚。内置分发为日语版卡带使用此紧凑布局。原生 `.wc3` 布局见[礼物文件](gifts.md#native-formats)。

日语版卡带使用不同的活动编号来显示神秘礼物的“朋友”列表。其 `sAcceptedActivityIds` 中，神奇卡片和神奇新闻的条目分别为 6 和 7（`BPRJ` 中位于 `0x08410EC4` 和 `0x08410EC8`，`BPGJ` 中位于 `0x08410E4C` 和 `0x08410E50`）；其他语言版本的卡带则使用 21 和 22 [src/data/union_room.h:405-406]。`LINK_GROUP_UNK_11` 列表的相同位置也使用 6 和 7。广播活动编号 21 的主机不会出现在日语版的“朋友”列表中。日语版接受的 RFU 序列号为 `{0x0002, 0x7F7F}`（`BPRJ` 中位于 `0x083FC378`），国际版则为 `{0x0002, 0x7F7D}`。日语版和法语版《火红》的 Switch 可执行文件代码相同，仅字符串和 ROM 路径不同；全部十二个游戏版本的首个本地通信 ID 均为 `0x01006fa0233f8000`。

两种日语版卡带均在 Unicorn 中执行原生客户端、`CreateMon`、变量查找、VBlank 处理器和已保存钩子的加载器。`CreateMon` 为种类 25 生成日语昵称“ピカチュウ”。日语名称采用假名表，训练家名称限五个字符；拉丁字母的重音字符与假名共用字节值。内置礼物说明仍用拉丁字母文本，日语版会移除重音。由于日语对话字体较宽，说明每 26 个字符换行，两行后换页。日语版 Team 卡片采用其源码中的日语结构大小和动态菜单宽度；两条提示缩短后可满足 RAM 脚本上限。

新增的德语版和意大利语版两组、西班牙语版《叶绿》及日语版两组均通过 mGBA 卡片检查。这些是对提取卡带 ROM 的离线检查。

<a id="retail-verification"></a>
### 实机验证

| 卡带 | 实机验证内容 | 来源 |
|---|---|---|
| 意大利语版《叶绿》（`BPGI`，修订版本 `0x0A`） | 全部 41 个 `Build` 字段与游戏机内存一致；跟随宝可梦安装；大师球卡片和道具分发 | [贡献者验证](https://github.com/Decryptu/pokeldn/issues/13) |
