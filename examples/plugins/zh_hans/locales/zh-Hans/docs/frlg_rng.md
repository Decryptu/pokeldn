<a id="grngvalue-reading-it-predicting-it-and-aiming-it"></a>
# gRngValue：读取它、预测它并瞄准它

这里的一切都是在法语版《火红》上测量的，BPRF软件版本0x0A。
<a id="the-generator"></a>
## 生成器

```c
u16 Random(void) { gRngValue = 1103515245 * gRngValue + 24691; return gRngValue >> 16; }
void SeedRng(u16 seed) { gRngValue = seed; }
```
 [src/random.c，include/random.h:18]

|符号|地址 |如何获得 |
|---|---|---|
| `gRngValue` | `0x03004220` | `Random` 的文字池 |
| `Random` | `0x080486B0` |扫描 4 MB 为 `RAND_MULT` = 0x41C64E6D |
| `SeedRng` | `0x080486D0` |其矿池再次命名为`gRngValue` |
| `gSpecialVars` | `0x081639A8` |唯一一个在 2.75 MB 中增加 2 的 12 个字的运行 |
| `gSpecialVar_0x8000` | `0x020370B4` |运行的第一个条目 |

没有 ARM 或 THUMB 指令对 `RAND_MULT` 进行编码，因此它位于 `Random` 池中 `&gRngValue` 旁边。扫描返回了 11 个结果； `ld_script.ld` 将 `src/random.o` 置于#86，并将常量的下一个用户 `src/title_screen.o` 置于#123，因此最低命中是 random.o 的。转储将 `Random` 指令与 [random.c:9-13] 指令相匹配，并且 `SeedRng` 后面带有相同的池字。

`Random` 返回状态的上半部分：一个PID（两次抽奖）留下 2<sup>16</sup> 个候选状态。 `pokeldn/frlg/rom/lcg.py` 是算术； `distance(a, b)` 在任何范围内通过小步/巨步（2<sup>17</sup> 操作）都是精确的。该地图排列了所有 2<sup>32</sup> 状态，因此距离始终存在，并且仅在很小时（赔率 N / 2<sup>32</sup>）才是证据。

`gRngValue` 和 `gSpecialVar_0x8000` 是链接时全局变量，从不移动。保存块地址移动：`SetSaveBlocksPointers` 在每次战斗中重新滚动 4 对齐偏移并加载 [load_save.c:75]。
<a id="the-rate-exactly-2-turns-per-frame"></a>
## 速率：每帧正好 2 圈

`ScrCmd_delay` 在恰好 N 帧 [scrcmd.c:651] 后恢复。 `--gift rng-rate-probe` 读取
`gRngValue`，延迟N帧重新读取； `rng_script.measure_rate` 将 `lcg.distance` 除以 N。

|框架（精确）|圈数（精确）| 2N + 2 |
|---|---|---|
| 600 | 1,202 | 1202 |
| 3000 | 6,002 | 6002 |

+2是`delay`周围额外一帧；每帧 2.003333 的模型适合 N=600，但在 N=3000 时预测为 6010。 `rng-trace` 在神秘礼物链接菜单中每帧采样 `gRngValue` 一次，给出的间隙正好是 2、95 of 95。读取后 n 帧的状态是 `advance(S, 2n)`。

探针在 `delay` 期间测量锁定的玩家（`lock=False` 测量解锁）；普通世界游戏中的回合数是偶数。计数来自两个读数（`distance`）或所得的宝可梦（`recover_wild_state`）；一圈大约为 8 毫秒，因此手动计时秒数无法确定。
<a id="where-the-seed-comes-from-and-why-it-cannot-be-carried"></a>
## 种子从哪里来，为什么不能携带

```c
void SeedRngAndSetTrainerId(void) { u16 val = REG_TM1CNT_L; SeedRng(val); gTrainerId = val; }
```

[main.c:264]，在淡入淡出之后、之前从 `Task_TitleScreenMain` 调用
`SetMainCallback2(CB2_InitMainMenu)` [title_screen.c:735]。 `StartTimer1` 在 `CB2_InitTitleScreen` [:351] 处运行：种子是在 START 按下时采样的自由运行计时器，有 65536 个可能的值。

链接期间设置的种子无法生存：退出神秘礼物运行
`MainCB_FreeAllBuffersAndReturnToInitTitleScreen` → `CB2_InitTitleScreen` [mystery_gift_menu.c:463]，并开始重新播种。从神秘礼物菜单到主世界的任何路线都无法避免它。 `0xC0DE` 的种子设置没有下一次遭遇状态的祖先（测量相隔 1,898,278,119 圈）。

| `SeedRng` 致电网站 |当 |
|---|---|
| `SeedRngAndSetTrainerId` [title_screen.c:735] |标题画面|
| `LinkTestScreen` [link.c:318] |未使用的调试屏幕|
| `Debug_RfuIdle` [link_rfu_2.c:2670] |未使用的调试屏幕|
| `RfuMain1` [link_rfu_2.c:2116] |仅限开关，在 Sloop 系统调用上门控 |

```c
if ((svc_4b() & SVC4B_RESEED_RNG) != 0)
    SeedRng(ReadU16(&GetHostRfuGameData()->compatibility.playerTrainerId));
```

[link_rfu_2.c:2114, `#if REVISION >= 0xA`]。 `RfuMain1` 在 RFU 启动时运行每一帧，因此设置位会将状态固定在广告的 `playerTrainerId` 附近。没有测量状态从中得出：神秘礼物菜单中采样的状态是游戏机的 13.7 亿次旋转
`playerTrainerId`，以及在联合房间玩21亿回合后的一次遭遇中采样的样本。该位何时设置未知。

计时开始不能选择种子。定时器 1 以 F/1 运行，一帧为 280,896 个周期，因此帧对齐读取全部为 `gcd(280896 mod 65536, 65536) = 64` 的倍数。回收的种子`0xB8C0`，
`0x3742`、`0x8E94`、`0x1376` 为 0、2、20、54 mod 64：读取有子帧抖动。
<a id="reading-a-pokemon-back-into-the-state-that-made-it"></a>
## 将宝可梦读回到创建它时的状态

`GenerateWildMon` 致电 `CreateMonWithNature(..., USE_RANDOM_IVS, Random() % NUM_NATURES)`
[wild_encounter.c:233]，滚动PID直到它与性格相匹配，然后是IV。野生宝可梦有四种抽法：PID 低半字、PID 高半字、HP/ATK/DEF、SPEED/SPATK/SPDEF。两次 IV 抽签添加了 30 位检查，并且只有一个状态幸存下来 (`lcg.recover_wild_state`)。 `Random32()`，
`(Random() | (Random() << 16))`，首先在两个调用站点绘制下半部分。

必须搜索这两个间隙；不同月份的布局有所不同。零售观察：

|方法| IV 之前的间隙 | IV 之间的差距 |观察于|
|---|---|---|---|
| 1 | 0 | 0 |剧本百变怪、剧本鲤鱼王(2) |
| 2 | 1 | 0 |野生独角虫，脚本鲤鱼王|
| 4 | 0 | 1 | 野生绿毛虫、独角虫、猴怪；脚本生成的鲤鱼王 |

对一个缺口的搜索报告称，“周一没有任何州为其他缺口建造”。杂散抽出不符合`CreateBoxMon`；其来源不明。在有脚本的遭遇中，它是断断续续的。要求异色 + 爽朗 + SPEED >= 20 的存根生成了 SPEED 10 的异色 爽朗 鲤鱼王； 2<sup>32</sup> 中恰好有一个状态在接下来的两次抽奖中具有该 PID：

    state 0x429D2189
      draws 3,4 -> 15/0/12/25/7/14      what the stub tested: SPEED 25, passes
      draws 4,5 -> 25/7/14/10/10/30     the mon that appeared
 在任何 RNG 声明之前，都会根据其摘要屏幕上的六个统计数据检查 mon 的 PID 和 IV。
<a id="the-scripted-battle"></a>
## 脚本化的战斗

```
setptr b0..b3 -> 0x03004220      gRngValue = seed          (opcode 0x11)
setwildbattle <species> <level>  CreateMon rolls PID, PID, IV, IV   (0xB6)
dowildbattle                     the battle starts          (0xB7)
```

`ScrCmd_setptr` 将立即字节写入绝对地址 [scrcmd.c:300]。 `setwildbattle` 来电
`CreateScriptedWildMon` → `CreateMon(&gEnemyParty[0], species, level, 32, 0, 0, OT_ID_PLAYER_ID, 0)`
[script_pokemon_util.c:128]：随机 IV，无固定PID，无性格循环，简单的四次绘制方法 1。两个命令都返回 FALSE，并且字段引擎运行命令，直到一个返回 TRUE，因此四个命令
`setptr`s 和一代在一个框架中运行。它们之间不能有任何屈服（`playse` 会破坏它）；测试断言没有。

作为由 `initramscript` 绑定到地图对象的 RAM 脚本交付，以 `end` (0x02) 结尾，而不是
`endram` (0x0d) 因此绑定保留并重新触发。 `setwildbattle` 不需要草，也不需要遭遇翻滚。在游戏机看到种子之前离线预测，托盘镇的一个异色Lv50百变怪：

```
PREDICTED   PID 0x026F38B2   nature 17   IVs 31/23/27/18/30/30   shiny
ACTUAL      PID 0x026F38B2   nature 17   IVs 31/23/27/18/30/30   shiny
```

<a id="a-mon-predicted-from-a-seed-nobody-set"></a>
### 一个由无人设置的种子预测的 mon

不写入任何内容的脚本会读取实时状态，打印它，生成一个 mon，然后再次打印它：

```
BEFORE  0x9A4F5DAA        (read off the console)
AFTER   0x8EEB8648
```
 单独从 `BEFORE` 预测，从 `gPlayerParty` 转储的 mon 在所有七个字段上都匹配：PID
0x0BF87DD1，性格13 爽朗，不异色，IV 25/10/28/9/19/3。四次绘制从读取的状态开始，偏移量为零。

`distance(BEFORE, AFTER)` 是 6，其中 `CreateBoxMon` 为 `Random32()` 花费 4:2，加时则没有，因为玩家是加时 [pokemon.c:1796]，IV 为 2 [:1836,1845]。额外的 2（世界消耗一帧）在生成后落地。
<a id="the-seed-reading-npc"></a>
## 读种子的 NPC

`--gift rng-seed-reader`，标志 id 1015。六个命令，由 `initramscript` 作为 RAM 脚本安装一次，并以 `end` 结尾，因此绑定仍然存在：

```
copybyte gSpecialVar_0x8000+0, 0x03004220      (opcode 0x15, byte at any address to any address)
copybyte gSpecialVar_0x8000+1, 0x03004221
copybyte gSpecialVar_0x8001+0, 0x03004222
copybyte gSpecialVar_0x8001+1, 0x03004223
buffernumberstring 0, VAR_0x8000               (0x83)
msgbox                                          the NPC prints the value
```
 它没有改变任何东西； `rng_script.seed_from_printed(low, high)` 重新组合该字。

- 读取是原子的。 RNG 永远不会闲置，因此分布在帧上的字节副本将分解为游戏机从未保存的值。 `copybyte` 和 `buffernumberstring` 返回 FALSE，因此所有六个都在一帧中运行；测试断言它们之间没有任何结果。
- 文本指针是相对的。 RAM 脚本位于 `gSaveBlock1Ptr->ramScript` 中，其基础在每次战斗和负载时都会重新滚动。 `setvaddress` (0xB8) 设置 `sAddressOffset = addr2 - (ctx->scriptPtr - 1)` [scrcmd.c:171] 并 `vmessage` (0xBD) 减去它，因此操作数是脚本自身主体的偏移量。
- `buffernumberstring` 打印 `u16` [scrcmd.c:1678]，因此种子需要两个变量和两行。

相隔约二十秒的两个读数给出：

```
reading 1   RNG HI 4685   RNG LO 26687   -> 0x124D683F
reading 2   RNG HI 54871  RNG LO 55616   -> 0xD657D940
distance    2,595 turns
```
 不相关的单词相距约 2<sup>31</sup>； 2,595 是 1,655,093 赔率 1 (`rng_script.check_two_readings`)。

绑定到玩家的母亲（组 4，地图 0，对象 1）：`MOVEMENT_TYPE_FACE_LEFT`，标志 0，因此永远不会隐藏，距玩家一步。两个 Pallet Town 对象事件均为 `MOVEMENT_TYPE_WANDER_AROUND` [data/maps/PalletTown/map.json]，并在倒计时中结束。
<a id="how-precisely-a-human-can-press-a"></a>
## 人类按 A 的精确度如何

一名玩家对提前 30.00 秒的目标进行四次按压，读出打印种子的 NPC：

|试用|已过帧数 |错误 vs 1791.8 |
|---|---|---|
| 1 | 1801 | +9.2 |
| 2 | 1807 | +15.2 |
| 3 | 1800 | +8.2 |
| 4 | 1796 | +4.2 |

平均值 +9.2 帧（取消的固定偏移），标准偏差 4.5，范围 11。所有四个转动计数都是偶数。

每约 8192 帧（约 137 秒）到达一个异色帧；在 4.5 帧展开的情况下，压力机大约有 9% 的时间击中选定的帧，因此手动瞄准异色需要大约 25 分钟，而随机遭遇大约需要 23 小时。准确测量未命中。 `pokeldn/frlg/rom/rng_countdown.py`为倒计时； `--aimed-at STATE` 将未命中转换为带符号的帧计数。当RAM脚本槽持有神奇反馈时，这仍然是路线。
<a id="the-stub-that-does-the-search"></a>
## 执行搜索的存根

`--gift rng-shiny-hunt`、`pokeldn/frlg/rom/native_script.py`、`asm/field/shiny-seek.s`。此页面上的每个存根都在实机硬件上进行验证：

|存根|礼物|零售验证|
|---|---|---|
| `shiny-seek.s` | `rng-shiny-hunt` |来自母亲的异色百变怪，来自两个不同的州|
| `mon-seek.s` | `rng-mon-hunt` | 异色、爽朗、速度个体值 >= 20、等级 5 的 鲤鱼王 |
| `mon-seek-far.s` | `rng-mon-hunt-far` | 异色、爽朗的鲤鱼王，证明 559 个填充字节已送达 |
| `mon-seek-both.s` | `rng-mon-hunt-both` | 异色、爽朗、SPEED 22；叶绿上的异色超梦|

```c
bool8 ScrCmd_setptr(struct ScriptContext * ctx)          // 0x11
{ u8 value = ScriptReadByte(ctx); *(u8 *)ScriptReadWord(ctx) = value; }
bool8 ScrCmd_callnative(struct ScriptContext * ctx)      // 0x23
{ void (*func)(void) = ((void (*)(void))ScriptReadWord(ctx)); func(); return FALSE; }
```

[scrcmd.c:300, :120]

`setptr` 在任何地方写入一个字节，`callnative` 运行它，因此 RAM 脚本将代码暂存在 EWRAM 中，并在 `CLI_RUN_BUFFER_SCRIPT` 无法到达的主世界中运行它。 `notblisy/RUBYSAPPHIREDLC` 在红宝石/蓝宝石上执行相同的操作（`writebytetoaddr` + `callasm`，LCG 循环，直到 PID 为异色）。

`hasFixedPersonality` 在 `CreateScriptedWildMon` 中为 0，因此PID为 `Random32()` 且
`OT_ID_PLAYER_ID`什么也不绘制：异色状态是状态后的前两次绘制。 `setptr`，
`callnative` 和 `setwildbattle` 返回 FALSE，因此存根在 `gRngValue` 中留下的状态是第一个
`CreateScriptedWildMon`消耗。

存根在 `gSaveBlock2Ptr + 0x0A`（位于固定 IWRAM 地址的指针）处读取 `playerTrainerId`，因此相同的字节用于火红和叶绿。它写入一个字，`gRngValue`。搜索是有界的；疲惫中`gRngValue`未受影响，遭遇很平常。每个存根在登台前都在 unicorn 下运行 (`tests/test_native_script.py`)，并根据 `rng_countdown` 检查其答案。
<a id="a-ram-script-may-not-come-back-from-a-battle"></a>
### RAM 脚本可能无法从战斗中返回

`CB2_InitBattle` 和 `InitOverworldBgs` 调用 `MoveSaveBlocks_ResetHeap` [battle_main.c:614, overworld.c:1337]，将 `gSaveBlock1` 重新滚动 0..124 中 4 的倍数[`SAVEBLOCK_MOVE_RANGE` 128,
load_save.c:75]。引擎将其指针保持在 `gSaveBlock1Ptr->ramScript.data.script`
[`GetRamScript`, script.c:514] 穿过战斗，因此它会从脚本不再存在的位置恢复，并且 `dowildbattle` 之后无法访问任何内容。

症状：流浪二战（登陆0xB6/0xB7）；干净的出口（零填充着陆，`nop`）；没有 A、B 或 START 的冻结世界（995 的字节 972 处的恢复点登陆在六字节内）
`setptr` 记录并解码一个永远等待的命令）。 `releaseall` + `end` 无法修复它。

该修复从保存块外部开始战斗，以十个字节为单位[`rng_script.battle_and_exit`]：

    setvar 0x8000, 0x02B7      ->  0x020370B4: B7 02  =  dowildbattle ; end
    goto   0x020370B4

`gSpecialVar_0x8000` 不动，战斗或世界代码中没有任何内容写入它。
当脚本停止 [script.c:335] 时，`ScriptContext_RunScript` 调用 `UnlockPlayerFieldControls()`，因此 `end` 返回控制权。没有 RAM 脚本可以依赖于战斗或地图加载中的保存块地址。
<a id="choosing-the-nature-and-the-ivs"></a>
## 选择性格和 IV

`--gift rng-mon-hunt`、`asm/field/mon-seek.s`，旗帜 ID 1019。所有四张抽奖均经过测试：PID赋予异色状态和性格（`personality % 25` [pokemon.c:5020]）；抽签3和4是IV [pokemon.c:1836, HP/攻击/防御，然后是速度/特攻/特防]。

    --hunt-nature adamant,jolly   --hunt-iv speed=31 --hunt-iv attack=20   --hunt-cap N
 捕获的鲤鱼王回读PID 0x01503B8A，异色值4，爽朗，IVs 6/2/25/28/12/7；
`lcg.recover_wild_state` 给出状态 0x7041F74F 和 `rng_countdown` 再现每个字段。

在十五条指令热循环中测试异色状态；除以 25 和 IV 比较在 8192 中针对 1 个状态运行，因此标准会在不减慢迭代速度的情况下乘以所需的迭代次数：

|要求| | 1 个州典型的冻结|最差的上限|
|---|---|---|---|
| 异色| 8,192 | 8,192 0.02 秒 | 0.10 秒 |
| 异色 + 性格| 204,800 | 0.55 秒 | 2.5 秒 |
| 异色+性格+1 IV >= 20 | 546,133 | 1.5 秒 | 6.7 秒 |
| 异色 + 两个 IV = 31 | 8,388,608 | 22 秒 |拒绝 |

`native_script.search_cost` 计算此；主机拒绝任何最坏情况超过
`--hunt-freeze-frames`（默认900，约15秒）。玩家在搜索时会看到带有音乐的静止画面。

`mon-seek.s` 是 163 字节分段预算的 160 字节：异色值是其自身的倒数，因此 `pidLo` 在两个指令中返回，除数是其自己的循环计数器，IV 楼层在 30 处携带终止符位，并且两个字段都移至位 27..31，因此五位比较是无符号的。
<a id="the-payload-in-the-script-body"></a>
## 脚本主体中的书签

`setptr` 每个代码字节花费 6 个脚本字节（操作码、立即数、4 字节地址）：995 字节 RAM 脚本主体中大约有 162 字节代码。引擎将主体运行到位并且永远不会读取最后一个命令：

```c
const u8 *GetRamScript(u8 objectId, const u8 *script)
{ ... return scriptData->script; }
```

[script.c:514]，超出 `gSaveBlock1Ptr->ramScript.data.script`，因此最后一个命令后附加的字节将按每个脚本字节进行存储。保存块偏移量对于脚本运行所在的帧是固定的，并且 `&gSaveBlock1Ptr` (0x03004228) 保存它，因此运行时读取的目标是准确的。
`asm/field/ram-jump.s`（36字节）是唯一上演的部分：

| |上演|身体|
|---|---|---|
|每字节成本| 6 个脚本字节 | 1 个脚本字节 |
| 995 字节主体中的房间 | 162 字节代码 | 755 字节 |

    setptr x36    the trampoline, into gDecompressionBuffer        216 bytes
    callnative    -> trampoline -> payload -> back                   5
    setwildbattle / setvar / goto                                   16
    pad to a multiple of four                                        3
    payload                                                        755
 蹦床尾部分支（`bx r0`、`lr` 未受影响），因此，轮椅的 `pop {r4-r7, pc}` 返回到
`ScrCmd_callnative` 的来电者。它首先检查 `ramScript.data.magic` 是否为 `RAM_SCRIPT_MAGIC` = 51
[script.c:12]；如果偏移量错误，它会返回并且遭遇很普通。
<a id="alignment-to-four-bytes"></a>
### 与四个字节对齐

THUMB `ldr rN, [pc, #imm]` 和 `adr` 使用 `Align(PC, 4)`。两个字节关闭，分支着陆并且代码运行，但每个池字都晚了两个字节读取。四字节对齐保持：`offset = Random() & ((SAVEBLOCK_MOVE_RANGE - 1) & ~3)`
[load_save.c:75] 是 `& 0x7C`，`gSaveBlock1` 是字对齐的，`RAMSCRIPT_BODY_OFFSET` (0x3624) 保持如此。 `native_script.emulate_body_script` 通过遍历真实脚本字节（36 个 `setptr`、`callnative`、蹦床的 `gSaveBlock1Ptr` 读取、分支到正文中）来捕获未对齐情况。
<a id="proving-the-size-rather-than-the-jump"></a>
### 证明大小而不是跳跃

异色结果确认了跳跃，但不确认交付的尺寸。 `asm/field/mon-seek-far.s` 后面是非零填充符到字节 995；存根对其进行求和并仅在匹配项上进行搜索。 `InitRamScript` 将其余部分补零
[`ClearRamScript`, script.c:495]，因此交货期短，只剩下 `gRngValue`。 `--gift
rng-mon-hunt-far`携带196字节的存根和559字节的填充符。
<a id="searching-so-the-stray-draw-cannot-move-the-answer"></a>
## 进行搜索，以便杂散绘制无法移动答案

`asm/field/mon-seek-both.s`（232 字节，`--gift rng-mon-hunt-both`，标志 id 1001）测试覆盖所有三种方法的两个位置的楼层。 d3、d4、d5 PID后的抽签：

|方法|第一个三重（HP/ATK/DEF）|第二个三元组（SPE/SPATK/SPDEF）|
|---|---|---|
| 1（干净）| d3 | d4 |
| 2 | d4 | d5 |
| 4 | d3 | d5 |

字A是`d3 | d4<<15`，字B是`d4 | d5<<15`。要求两者都将第一个三元组的楼层放在 d3 和 d4 上，将第二个三元组的楼层放在 d4 和 d5 上，因此方法 4 在没有自己的单词的情况下通过。

仅 IV 项进行平方：异色 + 爽朗 + SPEED >= 20 从 546,000 分之一变为 1,456,000 分之一，通常约为 4 秒。上限为 95%，因为一次失误会花费 1 个 A 压力，而 99% 的运气不好则需要 18 秒。

状态0xFCB5674F在零售上按方法1给出了异色、爽朗、SPEED 22，每种方法都通过：

|方法|静脉注射 |地板 |
|---|---|---|
| 1（干净）| 4/1/10/22/14/21 |好吧，游戏机做了什么|
| 2 | 22/14/21/25/1/18 |好的 |
| 4 | 4/1/10/25/1/18 |好的 |

状态 0x4FB97B07 使用方法 4 中的 IV（SPEED 21，floor 20）准确预测 PID：

      Method 1 (clean)  25/10/30/20/ 9/25
      Method 2 (stray)  20/ 9/25/21/ 3/ 1
      Method 4          25/10/30/21/ 3/ 1   <- the mon that appeared

<a id="where-a-hunt-writes-its-report"></a>
## 狩猎记录报告的地方

`asm/field/mon-seek-log.s`（288字节，`--gift rng-mon-hunt-log`，标志id 1002）写入
`{marker, start, found, iterations, cap}` 至 `gSaveBlock1Ptr + 0x348C`、`u8 unused_348C[400]` [include/global.h]。没有代码写入 `unused_348C`，并且在零售保存时读取为零。该块位于 `ramScript` 之外，因此
`CalculateRamScriptChecksum` 未受影响且绑定仍然存在；每次谈话都会覆盖日志。它在战斗中幸存下来（`MoveSaveBlocks_ResetHeap`复制块）并在保存时到达闪存。

    --buffer-script save-dump --dump-block sav1 --dump-offset 0x348C --dump-size 32

`native_script.decode_hunt_log` 读取它。耗尽搜索会用标记写入 `found` 0。

| | |
|---|---|
| 迭代次数 | 603,745 |
| `lcg.distance(start, found)` | 603,745, 差值 0 |
| 指令数（每次 15 条） | 9,056,175 |
| 3 个周期/指令的模型 | 1.62 秒 |
|被玩家观察到| 2-3 秒 |
|暗示| 3.7-5.6 周期/指令 |

`CYCLES_PER_INSTRUCTION_FROM_EWRAM`为3。观察时间是秒表读数，搜索时间呈指数分布；低估只会让冻结上限更快地被拒绝。
<a id="leafgreen"></a>
## 叶绿

存根运行未移植：每个文字都是链接时 IWRAM 字或叶绿上相同的常量，并且 `TID ^ SID` 在运行时读取。对超梦的绑定，是为了超梦的遭遇；参见[叶绿](frlg_leafgreen.md)。
