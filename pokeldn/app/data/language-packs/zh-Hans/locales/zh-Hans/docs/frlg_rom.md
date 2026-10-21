<a id="running-code-on-the-console"></a>
# 在游戏机上运行代码

神秘礼物客户端通过两种执行机制运行收到的代码：`CLI_RUN_MEVENT_SCRIPT`（操作码 15）将字节交给神秘事件虚拟机，`CLI_RUN_BUFFER_SCRIPT`（操作码 21）将代码交给 CPU 执行。两者都不需要利用游戏漏洞、准备特殊存档或进行其他设置；游戏机停留在神秘礼物菜单即可。

本页地址对应法文版《火红》，卡带标识为 BPRF，软件版本为 0x0A。《叶绿》的地址见[叶绿](frlg_leafgreen.md)，相关表格见 [ROM 映射](frlg_rom_map.md)。
<a id="the-mystery-event-vm"></a>
# 神秘事件虚拟机

这是一个独立的解释器 [src/mystery_event_script.c]，拥有包含 17 条命令的命令表 [data/mystery_event_script_cmd_table.s]，与接收神奇卡片礼物的脚本所使用的场景脚本虚拟机不同。`pokeldn/frlg/rom/mystery_event.py` 负责汇编各条命令（`MysteryEventScript.blob()` 保存数据，汇编器解析指针）。每个操作码都已在零售版实机上验证。
<a id="the-command-table"></a>
## 命令表

| # | 命令 | 操作码字节之后的操作数 | 返回值 | 效果 |
|---|---|---|---|---|
| 0 | `nop` |  | FALSE | 不执行任何操作 |
| 1 | `checkcompat` | u32 base, u16, u32, u16, u32 | TRUE | 检查兼容性 |
| 2 | `end` |  | TRUE | `StopScript` |
| 3 | `setmsg` | u8 selector, ptr | FALSE | 当 selector 为 `0xFF` 或等于状态值时，执行 `StringExpandPlaceholders(gStringVar4, str)` |
| 4 | `setstatus` | u8 | FALSE | `ctx->data[2] = value` |
| 5 | `runscript` | ptr | FALSE | 通过 `RunScriptImmediately` 运行场景脚本 |
| 6 | `initramscript` | u8 group, u8 map, u8 object, ptr, ptr | FALSE | 通过 `InitRamScript` 将脚本绑定到任意地图和对象 |
| 7 | `setenigmaberry` | ptr | FALSE | 写入 `gSaveBlock1Ptr->enigmaBerry` |
| 8 | `giveribbon` | u8 index, u8 ribbonId | FALSE | 为队伍中每只非蛋的宝可梦授予礼物奖章 |
| 9 | `givenationaldex` |  | FALSE | `EnableNationalPokedex()` |
| 10 | `addrareword` | u8 | FALSE | `EnableRareWord`（Easy Chat 流行语） |
| 11 | `setrecordmixinggift` |  | TRUE | 功能已禁用：`SetIncompatible` |
| 12 | `givepokemon` | ptr | FALSE | 将完整的 `struct Pokemon` 及附带邮件加入队伍 |
| 13 | `addtrainer` | ptr | FALSE | 添加一个 188 字节的 `BattleTowerEReaderTrainer` |
| 14 | `enableresetrtc` |  | TRUE | 功能已禁用：`SetIncompatible` |
| 15 | `checksum` | u32, ptr, ptr | TRUE | 若指定范围的 `CalcByteArraySum` 校验和不匹配，将状态设为 1 |
| 16 | `crc` | u32, ptr, ptr | TRUE | 同上，使用 `CalcCRC16` 校验 |
<a id="checkcompat-is-optional"></a>
## `checkcompat` 可选

`checkcompat` 打开每个官方脚本并门控语言和版本掩码（decomp 的
`LANGUAGE_MASK` 是英文）。脚本可以跳过它：

```c
bool32 RunMysteryEventScriptCommand(struct ScriptContext *ctx)
{
    if (RunScriptCommand(ctx) && ctx->data[3])   // data[3] is set only by checkcompat
        return TRUE;
    return FALSE;
}
...
while (MEventScript_Run(&ret));
```

`RunScriptCommand` [script.c:107] 在一次调用中循环，直到命令返回 TRUE。没有
`checkcompat`、`data[3]` 保持 0：脚本运行到第一个返回 TRUE 的命令（通常
`end`) 和外部 `while` 停止。掩码并不重要，指针会重新定位为
`operand - ctx->data[1] + ctx->data[0]` 和 `data[1]` 0（仅由 `checkcompat` 设置）和 `data[0]` 游戏机的 1024 字节 `client->recvBuffer`：N 的操作数是发送内容中的 N 个字节。 `checkcompat` 是汇编器允许在其后编写代码的一条命令。
<a id="the-return-channel"></a>
## 返回通道

`MEventScript_Run`将状态写入`client->param` [mystery_event_script.c:75]；
`CLI_LOAD_TOSS_RESPONSE` 将其加载到 `MG_LINKID_RESPONSE` [mystery_gift_client.c:204] 中。这四个客户端命令返回脚本选择的 u32：

    CLI_RECV MG_LINKID_RAM_SCRIPT
    CLI_RUN_MEVENT_SCRIPT
    CLI_LOAD_TOSS_RESPONSE
    CLI_SEND_LOADED

`setstatus` 设置任意值。库存状态：

|状态 |意义|
|---|---|
| 0 |没有命令集一 |
| 1 | `setenigmaberry` 无法验证浆果，或 `checksum`/`crc` 不匹配 |
| 2 |成功;每个完成其工作的操作码都会设置此 |
| 3 | `SetIncompatible` 或 `givepokemon` 发现一条完整的队伍 |

`CLI_COPY_RECV_IF` 和 `CLI_COPY_RECV_IF_N` 可以在其上分支客户端脚本
[mystery_gift_client.c:170]（未使用）。

菜单打印 `CLI_RETURN` [`GetClientResultMessage`, mystery_gift_menu.c:884] 的结果，因此
`setmsg` 在这里是不可见的。只有成功消息到达 `MG_STATE_SAVE_LOAD_GIFT` [:1379]，否则事件的写入将在复位时丢失；因此返回 `CLIENT_SCRIPT_MEVENT_DONE`
`CLI_MSG_CARD_RECEIVED` 即使没有卡。 `CLI_MSG_BUFFER_SUCCESS`(13)，对方成功退出，打印压入的64字节`CLI_COPY_MSG`。
<a id="the-probe-script"></a>
### 探测脚本

`--gift mystery-event-probe` 是无害的：一旦 National Dex 开启，`givenationaldex` 就不会执行任何操作，而 `checksum` 只会读取。

    givenationaldex; setstatus 42; checksum 1026, 16, 31

|状态 |它证明了什么|
|---|---|
| 42 | 42链运行到末尾，指针操作数是发送缓冲区中的偏移量 |
| 1 |链运行，但重定位的指针没有落在探测字节上 |
| 2 | `givenationaldex` 运行后没有任何反应 |
| 0 |已进入虚拟机但未执行任何命令 |
|什么都没有|客户端脚本形状错误，而不是VM |

`checksum` 已终结并保持比赛之前的状态。零售火红回答42。
<a id="givepokemon"></a>
## `givepokemon`

`pokeldn/frlg/save/mevent_pokemon.py` 构建了楼梯：一个 100 字节的加密队列，然后游戏机在 `pointer + sizeof(struct Pokemon)` 处读取 34 字节的 `struct Mail`。
`--gift mystery-event-celebi` 运送一件。与字段脚本 `givemon` 不同，它：

- 附上邮件。 `ItemIsMail`对其进行门控，因此持有物必须是十二件邮件物品[mail_data.c:167]之一； `GiveMailToMon2` 将整个结构（单词、发件人姓名、家 ID、种类、物品）复制到 `gSaveBlock1Ptr->mail` [:100] 中；
- 在国家号码上设置`FLAG_SET_SEEN`和`FLAG_SET_CAUGHT`；
- 到达神秘礼物菜单：当菜单关闭时，mon 位于队伍中。

状态2是成功，状态3是一个完整的队伍，没有任何文字。切勿在其后添加 `setstatus`。

构建器强制执行的陷阱：

- mon的`mail`字节必须是`MAIL_NONE`（0xFF）； 0为邮槽0，读取为真实邮件；
- `personality == otId` 使加密密钥为 0，因此 mon 验证已洗牌或未洗牌，并且未洗牌的可以发货；
- 推导出队伍尾部；零尾读回为级别 0；
- 保留项目和邮件的 `itemId` 必须一致：`GiveMailToMon2` 设置邮件中的保留项目。
<a id="initramscript"></a>
## `initramscript`

`initramscript 3, 0, 2` 将现场脚本绑定到组 3、地图 0、对象 2、托盘镇南部的胖子。重新启动后，他说出了脚本的台词，并扩展了 `{PLAYER}`。

`CLI_SAVE_RAM_SCRIPT`使用`InitRamScript_NoObjectEvent`（MAP_UNDEFINED，对象0xFF）[script.c:578]，只有送货员的`GetSavedRamScriptIfValid` [:554]读取，并且只有有效的神奇结构。真实坐标达到`GetRamScript(gSpecialVar_LastTalked, script)`[:514,
field_control_avatar.c:458]，它代替对象自己的脚本运行脚本并忽略卡片。
`gSpecialVar_LastTalked` 是对象的本地 id，按 `map.json` 从 1 开始的顺序。

需要花费神奇配合（[一个RAM脚本槽](frlg_gift.md#the-one-ram-script-slot))；会话记录“不持有神奇反应”，直到下一张普通卡收回插槽。对象在绑定时会丢失自己的脚本：绑定到静态遭遇的对象时，脚本会替换该遭遇。
<a id="traps"></a>
## 陷阱

- `setenigmaberry` 无法设置物品效果。 `struct ReceivedEnigmaBerry` [berry.c:944] 为 1322 字节：`Berry2`（28 字节）、`u8 unk_001C[0x4FA]`，然后是 `itemEffect[18]`、`holdEffect` 和 `holdEffectParam` 0x516，超过1024字节缓冲区；尾部是堆上 `recvBuffer` 之后的任何内容（`build_enigma_berry_blob`；模拟器报告 `read_past_buffer`）。
- `struct Berry2` 中的两个 ROM 描述指针必须从卡带中读取并原封不动地发回：Berry Pouch 将永远取消对它们的引用。
- `giveribbon` 索引 7..10：`GiveGiftRibbonToParty` [pokemon_size_record.c:193] 接受 `index < 11`，但 `sGiftRibbonsMonDataIds` 将七个条目复制到 `u8[8]` 中，因此 7..10 `SetMonData`来自未初始化堆栈的字段 ID。汇编器拒绝任何高于 6 的内容。FRLG 没有功能区 UI；仅在传输后才会显示功能区。
- 没有终端命令的脚本将零填充缓冲区的其余部分解码为操作码。 `assemble()` 和服务器拒绝一个。
- `setrecordmixinggift`和`enableresetrtc`各拨打一个电话，`SetIncompatible`，并停止链条[mystery_event_script.c:227, :291]。作曲家拒绝了它们。
- `addrareword`和`setenigmaberry`在游戏中不可见；从保存中读回它们：`additionalPhrases`（SaveBlock1 + 0x2F10，又一个轻松聊天词）和`enigmaBerry`（+0x30EC）。它设置的 `VAR_ENIGMA_BERRY_AVAILABLE` 在 FRLG 中的其他地方无法读取。
<a id="how-it-is-wired"></a>
## 接线方式

- `pokeldn/frlg/rom/mystery_event.py`：操作码、汇编器、反汇编器（`describe`）和`run()`，离线客户端使用的模拟器。
- `pokeldn/frlg/gift/mg_script.py`：`CLIENT_SCRIPT_SAVE_CARD_AND_MEVENT`（没有持有卡：卡、交付脚本、事件）、`CLIENT_SCRIPT_RUN_MEVENT`（已持有卡：仅事件、没有扔任何东西）、`CLIENT_SCRIPT_MEVENT_DONE`（共享成功尾部）。
- `pokeldn/frlg/gift/mg_server.py`：`SCRIPT_SEND_MYSTERY_EVENT` 与 `SVR_LOAD_MEVENT` 和 `SVR_READ_MEVENT_STATUS`；状态出现在 `server.mevent_status` 和主机日志中。
- `pokeldn/frlg/gift/gift_composer.py`：`WonderGift.mevent` 验证组装的字节。
<a id="native-arm-code"></a>
# 原生 ARM 代码

```c
case CLI_RUN_BUFFER_SCRIPT:
    memcpy(gDecompressionBuffer, client->recvBuffer, MG_LINK_BUFFER_SIZE);
    client->funcId = FUNC_RUN_BUFFER;
    ...
static u32 Client_RunBufferScript(struct MysteryGiftClient * client)
{
    u32 (*func)(u32 *, struct SaveBlock2 *, struct SaveBlock1 *) = (void *)gDecompressionBuffer;
    if (func(&client->param, gSaveBlock2Ptr, gSaveBlock1Ptr) == 1)
```

[mystery_gift_client.c:237,276]。每一个死刑都基于五个事实：

- 1024 字节 (`MG_LINK_BUFFER_SIZE`) 会被复制，无论发送的内容如何，因此 VOC 都会在其后面运行前一个接收的尾部，并且必须是独立的。
- `r0 = &client->param`、`r1 = gSaveBlock2Ptr`、`r2 = gSaveBlock1Ptr`：均为保存块，可读可写。
- `client->param` 是 `CLI_LOAD_TOSS_RESPONSE` 作为 `MG_LINKID_RESPONSE` [:204] 返回的内容。
- 每帧调用一次，直到返回 1；一个从来不挂的神秘礼物菜单却没有出路。 `memcpy` 在 `CLI_RUN_BUFFER_SCRIPT` [:239] 处运行一次，因此 VOC 可以跨帧保持状态。
- ARM 状态：调用者使用 `bx` 到达字对齐地址。

`gDecompressionBuffer` 位于 0x0201C000（通过 `anchors` 测量）。有效负载与位置无关。
<a id="the-build"></a>
## 构建

该应用程序的神秘礼物构建器使用相同的工具链（`pokeldn/frlg/rom/custom_code.py`）组装ARM源代码，或者采用原始`.bin`，并在发送之前在模拟游戏机上运行它。 `.pokegift` 文件携带编译后的 ARM 字节、卡带目标和响应设置。 [神秘礼物档案](gifts.md#console-code)文档打包分享。

- `asm/*.s`，每个思科一个ARM源代码，由`scripts/gen_buffer_scripts.py`组装成承诺的`pokeldn/frlg/rom/buffer_payloads.py`； `tests/test_buffer_script.py`安装`arm-none-eabi-as`时重新组装并比较。
- `pokeldn/frlg/rom/buffer_script.py`：注册表、验证和 `emulate()` / `emulate_repeating`，它们使用游戏机的三个参数在 GBA 内存映射上的Unicorn下运行 VOC；发生故障或永不返回的 1 永远不会到达空中。
- `pokeldn/frlg/gift/mg_script.py`：`CLIENT_SCRIPT_RUN_BUFFER`（接收、运行、加载返回通道、发送、接收下一个脚本）和`CLIENT_SCRIPT_BUFFER_SUCCESS`。
- `pokeldn/frlg/gift/mg_server.py`：`SCRIPT_RUN_BUFFER_SCRIPT`。无卡无抛掷提示；保持保持的神奇关系。
- 两个模拟控制台均独立地从解压缩中编写，通过每帧重新输入来执行火灾：`tests/test_mystery_gift_flow.py` 中的 `pokeldn/frlg/gift/mg_client.py` 和 `ConsoleClientModel`。

每次都先离线：

    ./.venv/bin/python -m pytest tests/test_buffer_script.py -q
    ./.venv/bin/python scratchpad/mg_client_harness.py --buffer-script -v
 在硬件上，游戏机等待神秘礼物 -> 奇迹卡 -> 朋友并加入主机。在下面的运行行中，`HOST` 代表
`POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/frlg_mg_host.py --live --keys PROD_KEYS --dump-file DUMP.bin` 和 `./.venv/bin/python -u bin/frlg_mg_host.py --over-ip --dump-file DUMP.bin` 的 `IP_HOST`，它通过 LAN 提供模拟游戏机，无需无线收发设备和按键。之前从未对主机发出 SIGTERM
`DUMP.bin` 存在；它写在`Buffer script dump: N bytes`之后几秒：

    until ls DUMP.bin >/dev/null 2>&1; do sleep 2; done

<a id="where-a-payload-can-live"></a>
## 载荷可驻留的位置

缓冲区脚本每帧都会重新复制，因此它写入自己图像的任何内容都不会保留。比菜单寿命更长的代码会出现在游戏从未写入的地方：

    0x0203FC00 .. 0x02040000    1024 bytes, above every symbol the game links
 最大大小的 EWRAM 符号以 0x0203FBAC 结尾（[EWRAM 在两个版本中位于相同的地址](frlg_rom_map.md)）。根据分解命名（`gHeap` 的 114688 字节在符号表中没有携带大小），这是唯一无人认领的 EWRAM 跨度；其余的是三字节和八字节对齐孔。

    0x0203F768 .. 0x0203FBAC    1092 bytes, newlib's malloc state

`__malloc_av_` 和它之后的 malloc 计数器仅从 newlib 的 stdio 到达，这仅
`AGBPrintf`，在发布版本中未使用，调用（pokefirered_switch.elf：唯一的`bl`到`_malloc_r`，
`_calloc_r` 和 `_free_r` 位于 libc 内部）。一个 0xA5 填充物在 mGBA 的菜单、行走和法语版《火红》上的一场疯狂战斗中幸存下来。 GB-Link Team 卡将其重新定位的脚本保留在那里 ([frlg_gift.md](frlg_gift.md#gb-link-team-cards))。
`scratchpad/ewram_symbol.py ADDR LEN` 检查地址。

切勿选择地址，因为它的读数为零。 0x0202B280、0x020185C4 和 0x0203B0E9 读取数十 KB 的零，是战斗和盒子缓冲区、`gDecompressionBuffer` 的预备阶段和分配器簿记； 0x02012304 位于 `gHeap` 中。 0x0202B280位于`gPokemonStorage`内部：在那里写入可以落在盒装宝可梦的校验和上，然后保存会保留一个坏蛋。

软复位两次清除 EWRAM：`DoSoftReset` 调用 `SoftReset(RESET_ALL & ~RESET_SIO_REGS)`
[main.c:488]（`svc 0x1` 然后 `svc 0` [libagbsyscall.s:69]），然后 `AgbMain` 调用
`RegisterRamReset(RESET_ALL)` [main.c:134]; 0xFF 的位 0 是 `RESET_EWRAM` [include/gba/syscall.h:4,12]。 Switch 包装器还会重新启动模拟的游戏机，因此 `AgbMain` 运行两次：`gIntrTable` 和
`INTR_VECTOR` (0x03007FFC) 每次启动时都会被清除和重建两次，条目 1、2 和 7 取其间的无线值（以每秒 328000 采样：33.3 ms，然后是第二次清除的 133.6 ms，重建的 33.6 ms）。启动不会重建高于 0x0203B0E8 的任何内容。两个靴子之间没有任何写入
0x0203FC00..0x02040000：标题屏幕上存在一个标记，重新加载，菜单，保存，地图更改，战斗和PC盒，软重置（A + B + START + SELECT）将其清除。
<a id="the-per-frame-hook"></a>
## 每帧钩子

`gIntrTable` 位于法语版卡带上的 0x03002720；条目 4（V 型毛坯处理程序）保存 `VBlankIntr` (0x0800071D)。它是由 `InitIntrHandlers` 一次写入的十四个函数指针
`gIntrTableTemplate` [main.c:339]，由BIOS通过`IntrMain`到达，其地址为向量
0x03007FFC 成立。替换条目 4 可以让代码在每个游戏状态下的每一帧进行一次调用；
每当菜单或战斗开始时，`gMain.vblankCallback`和`gMain.callback2`都会被重写。

位于游戏机的 IWRAM 中：`IntrMain_Buffer` 是 0x03002760（英文 0x03002810）并且
`gSaveBlock1Ptr` 是 0x03004228（英语 0x030042D8），因此盒带的 IWRAM 位于这些地址的英语版 0xB0 的下方。 IWRAM 不像 EWRAM 那样在构建之间传输。

|条目 |卡带|英语 | |
|---|---|---|---|
| 0 V计数 | 0x08000805 | 0x0800081C | `VCountIntr` |
| 1 连载 | 0x03004B34 | |链接启动时的 IWRAM 处理程序 |
| 2 定时器3 | 0x08005AE1 | | `Timer3Intr`，不同的ROM段和增量|
| 3 空白 | 0x080007D5 | 0x080007EC | `HBlankIntr` |
| 4 空白 | 0x0800071D | 0x08000734 | `VBlankIntr` |
| 5、6、8-13 | 0x08000885 | 0x0800089C | `IntrDummy`，八次|
| 7 | 0x081E0D35 | | RFU 定时器处理程序，`sTimerIntrFunc = gIntrTable + 0x7` [main.c:85] |

条目 1 和 7 与模板不同，因为无线运行时 decomp 进行了预测；条目 1 和 2 在会话后保留其无线值，直至重置。游戏仅将条目 4 写入
`InitIntrHandlers`，仅在软重置时重新运行。
<a id="code-that-outlives-the-session"></a>
### 超出会话寿命的代码

安装在条目 4 中的暂存区域中的 20 字节存根在会话关闭后在每个游戏状态下运行每个帧。 `asm/resident/vblank-hook.s`：

```arm
    ldr     r0, .Lcounter
    ldr     r1, [r0]
    add     r1, #1
    str     r1, [r0]
    ldr     r0, .Loriginal
    bx      r0                      @ tail branch: lr still points at intr_return
```

`IntrMain` 在 `intr_return` 处以 `lr` 进入 SYS 模式的处理程序，并让它破坏 r0-r3 [crt0.s,
`jump_intr`]，因此被替换的处理程序通过其自己的`bx lr`返回。这两个文字在发送之前都会被修补。

`call-chain` 安装它：五个字在前，条目 4 最后，每次写入都会读回。

    read32  [0x03002730]                gIntrTable[4], 0x0800071D
    write32 [0x0203FC00] = 0x68014802   the stub
    write32 [0x0203FC04] = 0x60013101
    write32 [0x0203FC08] = 0x47004801
    write32 [0x0203FC0C] = 0x0203FC40   the counter's address
    write32 [0x0203FC10] = 0x0800071D   the handler being replaced
    write32 [0x03002730] = 0x0203FC01   the hook, THUMB bit set
    read32  [0x0203FC40]                the counter
 该钩子在每个游戏状态下每帧运行一次：在超过 19995 帧的时间里，它在菜单、标题屏幕、主世界、队伍菜单、狂野战斗和游戏内重新启动时每秒调用 59.0 到 63.3 次。软复位结束它：`InitIntrHandlers` 重写条目 4 [main.c:339]（`gIntrTable[4]` 读取零，然后 0x0800071D）。 神秘礼物只有在启动后才能访问，这会清除 EWRAM，因此在没有新会话的情况下必须存在的迷宫需要在保存中保存其安装程序。
<a id="re-arming-it-after-a-reset"></a>
### 重置后重新装备

`--gift resident-hook` 将神秘事件脚本 `initramscript` 的现场脚本发送到玩家的母亲身上。绑定存在于保存中并在电源循环后继续存在（[一个 RAM 脚本插槽](frlg_gift.md#the-one-ram-script-slot)）；在任何引导安装挂钩后与她交谈，没有链接，也没有主机。

`asm/field/install-vblank-hook.s`，68 字节，与 `setptr` 一起以每个 6 个脚本字节进行暂存，并与 `callnative` 一起运行：RAM 脚本主体保存的 995 字节中的 418 个字节。

    read  gIntrTable[4]
    if it already names the stub: return, writing nothing
    write the five words of the V-blank stub to the staging area
    write the handler just read into the stub's fifth word
    zero the counter
    write the staging area, Thumb bit set, into gIntrTable[4], last
 尾部目标来自表，因此钩子链接那里的任何处理程序。顶部的防护是必需的：安装两次会使存根尾部分支自身，它在中断处理程序内旋转并冻结整个世界。

`SaveBlock1 + 0x32E0` 处的脚本块在重新滚动的指针处进行软重置后仍然存在（在模拟器上验证）。

该脚本在每次启动时都会重建代码，因此代码受到脚本主体的限制：暂存 162 个字节，或者在最后一个命令之后附加大约 755 个字节，并通过蹦床到达。
<a id="a-payload-larger-than-a-script-body"></a>
### 大于脚本体的载荷

`asm/field/save-loader.s`，64 字节，是所有 RAM 脚本阶段，无论 VOC 的重量如何：它读取
`gSaveBlock2Ptr` 新鲜，添加 0xB20，将 N 个单词复制到暂存区域，根据魔法检查第一个单词（从未写入的保存，或稍后卡到达的区域）并分支。它仅使用 r0-r3 并且从不推送，因此 √ 直接返回到 `ScrCmd_callnative` 的调用者。

blob 大小为 936 字节，1 个 `save-write`（`MAX_SAVE_WRITE_BYTES`，1024 字节接收缓冲区减去写入器）：

    +0x000  magic 0x444C4B50
    +0x004  installer
    +0x054  the V-blank hook
    +0x068  filler
    +0x3A4  checksum over the filler
 除非填充符正确，否则安装程序不会安装任何内容（[证明尺寸](frlg_rng.md#proving-the-size-rather-than-the-jump)）。

保存副本中钩子的尾部目标必须是测量的 `VBlankIntr`，绝不为零：加载程序复制可能处于活动状态的钩子，并且在第二次访问时，安装程序会发现已安装钩子并且不修补任何内容。第二次对话后，一个零会使游戏机崩溃并黑屏。

RAM 脚本是 995 字节中的 394 个字节，不管怎样。 `filler_B20` 保存 1024 字节，保存的其他未使用区域大约 700 个。更大的 blob 在一个会话中以 936 字节为单位写入，每个分区一个分区 ([`save-write`](#save-write))。在满 1024 时，blob 到达 EWRAM 的顶部，并且计数器移至暂存区域下方的 84 字节。暂存的副本等于除了钩子的第五个字之外的保存，并且每次准备都暂存相同的字节（在模拟器上验证，其中计数器以每秒 60.0 的速度运行）。
<a id="calling-the-wrapper"></a>
### 调用包装器

GBA 代码通过 Sloop 系统调用到达 Switch 模拟器：23 之间
`swi 0x40` 和 `swi 0x62`，在 0x46、0x4E、0x52 和 0x58 到 0x60 处有间隙 [src/sloopsvc.c]。驻留的 税务 可以发出其中的任何一个：构建器将一个 thunk `swi N ; bx lr` 组装到带有修补的数字的 blob 中。标记在调用之前下降，因为不返回的系统调用不会留下任何其他内容可读取：

    +0x00  0xB0B00001   the probe was reached
    +0x04  the syscall number
    +0x08  0xB0B00002   it returned, and zero until it does
    +0x0C  r0, r1, r2, r3 as the syscall left them

`swi 0x54`、`svc_CommsAllowedByParentalControls` [sloopsvc.c:182]，在没有家长控制的游戏机上返回非零。
<a id="the-dispatcher-the-sloop-syscall-boundary"></a>
#### 调度程序：Sloop 系统调用边界

调度程序位于 `main + 0x057014`，其跳转表位于 `main + 0x17D7F6`。它承认
`N` 中的 0x40..0x62：

    cmp   w2, #0x2b ; b.lo default       below 0x2B, the BIOS syscalls
    sub   w9, w19, #0x40 ; cmp w9, #0x22 ; b.hi default
    ldrh  w12, [table, w9, lsl #1]       a u16 word-offset from 0x05706C
    br    base + offset * 4
共三十五个条目、二十三个不同的处理程序。`sloopsvc.c` 中列出的每个编号都有对应处理程序。0x46、0x4E 及 0x58 至 0x60 共用默认处理，恰好对应反编译代码中的空缺。0x48 与 0x56 共用一个处理程序（`WriteSector`、`ReplaceSector`）；0x40 与 0x41 共用另一个，按编号分支。调度器的 `x0` 是 CPU 对象，`w2` 是编号，`x3` 是供处理程序读取的寄存器上下文：客户机的 `r0` 位于 `+0x48`，`r1` 位于 `+0x4C`（`0x52` 处理程序先执行 `mov x20, x3`，再执行 `ldp w1, w22, [x20, #0x48]`）。

默认值为 `cmp w19, #0x2a ; cset w0, hi ; ret`。 `w0` 是包装器自己的“处理”布尔值，而不是访客的 r0，因此未实现的数字是惰性的（不会挂起）并且使每个访客寄存器保持不变。过零且读数为零的探头未测量到任何结果。

千万不要盲扫0x40..0x62：0x48和0x56取一个扇区号和一个指针，0x4C完成一次保存，
0x55 交出 SaveBlock2 指针，0x43、0x57、0x61 和 0x62 接受参数。 r0 中的标记成为垃圾闪存源。

探针在每次调用之前重写自己的 `swi`（无指令缓存），首先写入数字，以便挂起命名自己，并在七个标头字（35 个结果，140 字节）之后记录每个数字的 `r0`。
`p_probe_num_step` 步数； `p_probe_a0_step` 步进 `r0`，步数为零。

|数量 | r0 中 | r0 输出 |
| --- | --- | --- |
| `swi 0x52` | `0xA5A00052` | `0` |
| `swi 0x53` | `0xA5C00052` | `1` |
| `swi 0x54` | `0xA5E00052` | `1` |
| `swi 0x55` | `0xA6000052` | `0xA6000052`，不变|
| `swi 0x56` | `0xA6200052` |包装有问题|

`swi 0x56` (`ReplaceSector`) 的目标区域表拒绝（r0 中的标记），使模拟器在 `0xFF8` (`main+0x573F8`) 处发生故障，并且保存未受影响：

    Invalid memory access at virtual address 0x0000000000000FF8
    PC  = main+0x573F8     LR = main+0x573EC
    x19 = 0x56                  the syscall number
    x22 = 0xA6200052            the guest's r0
    x13 = 0x0203FFC2            the guest's PC, the halfword after the thunk's `swi`
    x03 = 0x655DB09BE8          0x2D0 above the object 0x52's index 45 resolves to
 日志标签 `0x0855D3F8` 为
`gba-app:0x573f8`，将 `main` 基数置于 0x08506000 处。
<a id="swi-0x52-and-swi-0x55-the-memory-bus"></a>
#### `swi 0x52` 和 `swi 0x55`：内存总线

0x52 有一个 decomp 缺少的处理程序，位于 `main + 0x05728C`：

    ldp   w1, w22, [x20, #0x48]     guest r0 into w1, guest r1 into w22
    lsr   x9, x1, #0x15             r0 >> 21
    ldr   x8, [x21, #0xe0]!         the region table
    and   x9, x9, #0x7f8            bits 3..10, so x9 is a BYTE OFFSET, not an index
    add   x8, x8, x9
    ldr   x0, [x8, #0x50]           the object for this selector
    ldr   x8, [x0]                  its vtable
    ldr   x8, [x8, #0x48]           slot 9
    blr   x8
    mov   x0, x20 ; mov w1, wzr ; mov w2, wzr ; b 0x0855D584
 返回值被丢弃：`main + 0x057584` 处的写回被交给 `w1 = wzr`，因此客户机始终读取 r0 = 0，而 r1 到 r3 保持不变。 `swi 0x52` 返回 r0 = 0 并保留 r1 到 r3，并且保存不变，从主世界，跨选择器 45 到 54（`r0` 按 `1 << 21` 步进）。 `swi 0x55` 在
`main + 0x057304` 索引具有相同移位的同一个表，调用槽 9 并通过退出
`main + 0x057588`，跳过回写；这就是为什么它返回 r0 不变。

要读取对象和目标，请停在 `blr x8`、`main + 0x0572AC`（虚拟 `0x0855D2AC`）：`x0` 是对象，`x8` 插槽 9 的目标，`w1` 客户 r0。一条指令后，返回值仍然在
`x0`。对于所有 256 个条目的调查，在取消引用任何内容之前，在 `ldr x8, [x0]`、`main + 0x0572A4` 处停止：空或未映射的对象在此处发生故障。

`0x7f8` 在一条指令中进行掩码和缩放：

    entry = (r0 >> 24) & 0xFF        and the byte offset is entry * 8
 将其读为 `(r0 >> 21) & 0xFF` 会使每个条目都大八倍。 `r0` 是 GBA 地址，表是内存总线：顶部字节选择区域，插槽 9 是其地址折叠。

|条目 |地区 |对象|插槽 9 |
| --- | --- | --- | --- |
| 0x00 | BIOS |自己的| `and w0, w1, #0xffffff` |
| 0x01 |未映射 |默认 | `and w0, w1, #0xffffff` |
| 0x02 | EWRAM，256 KB |自己的| `and w0, w1, #0x3ffff` |
| 0x03 | IWRAM，32 KB |自己的| `and w0, w1, #0x7fff` |
| 0x04 |输入/输出|自己的| |
| 0x05 |调色板，1 KB |自己的| `and w0, w1, #0x3ff` |
| 0x06 |显存，96 KB |自己的| `and w8, w1, #0x1ffff`，然后 `0x18000..0x1FFFF` 被 `0x8000` 向下折叠 |
| 0x07 | OAM，1 KB |自己的| `and w0, w1, #0x3ff` |
| 0x08，0x09 | ROM 等待状态 0 |一个物体覆盖两个| `ldr w8, [x0, #0x34] ; and w0, w8, w1`，卡带尺寸掩码|
| 0x0A，0x0B | ROM 等待状态 1 |一个物体覆盖两个|相同的虚表|
| 0x0C | ROM 等待状态 2 |自己的|相同的虚表|
| 0x0D |等待状态 2 的顶部，EEPROM 所在的位置 |自己的|默认虚函数表|
| 0x0E |静态随机存取存储器| 远离所有其他区域对象分配 | |
| 0x0F | SRAM 镜像 |自己的| |
| 0x10 至 0xFF |未映射 |默认 | `and w0, w1, #0xffffff` |

条目 0 到 15 给出 14 个对象和 11 个 vtable。 VRAM折叠是硬件镜像（`0x18000`读取`0x10000`，`0x1FFFF`读取`0x17FFF`）。默认对象是`0x655DB09918`，vtable
`main + 0x1C1FB0`，插槽 9 `main + 0x01F7D8`；它的插槽 10 是 `mov x0, xzr ; ret`，11 是裸 `ret`，2 是两层设置器。每个 vtable 在 `-0x08` 处都有一个空类型信息指针：没有 RTTI，没有类名。

EWRAM的vtable，`main + 0x1C21A0`（`x0`区域对象，`x1`循环计数器，`x2`地址，
`x3` 的值）：

|槽 |它是什么 |
| --- | --- |
| 2 |将两个字存储到 `+0x24` 和 `+0x2C` 的对象中 |
| 3, 4, 5 |读取 16、32 和 8 位 |
| 6、7、8 |写入 16、32 和 8 位 |
| 9 |将地址折叠到区域 |
| 10、11 |返回 null，并且无操作 |

访问器首先对周期计数器进行充电（三个用于半字或字节，六个用于一个字），然后将主机后备指针索引到 `+0x10`。大小为 `+0x20`，ROM 大小掩码为 `+0x34`。

七个系统调用到达表（0x45、0x47、0x48 和 0x56、0x4D、0x52、0x55、 0x62)，且每次仅调用槽位9；读写访问器属于仿真器的CPU 内核。 `swi 0x62` 是递增计数器的四个指令。

通过自己的控制流来绑定处理程序：有几个处理程序在最后一个表条目之后携带一个外线延续，该延续由下一个处理程序的开始错误属性来限制。
<a id="the-flash-sector-path"></a>
### 闪存扇区路径

`swi 0x48` 和 `swi 0x56` 在 `main + 0x057084` 共享一个处理程序，在 `main + 0x057364` 继续。 Guest `r0`是一个4 KB的扇区号，Guest `r1`的源码：

    source      = r1, resolved through the region table and folded
    destination = 0x0E000000 + r0 * 0x1000, resolved the same way

目标地址通过 32 位算术计算 [main + 0x05737C]：`0x0E000000 + ((r0 & 0xFFFFF) << 12)`。区域条目是该地址的最高字节 [main + 0x057384]：`0x0E + ((r0 & 0xFFFFF) >> 12)` mod 256，因此 `r0` 决定所选区域。EWRAM、IWRAM 或卡带缓冲区中的目标均通过两项边界检查（`fold < size`、`size - fold >= 0x1000`）；当 `r0 = 0xFA000 + n` 时，无论源数据来自哪个区域，目标都会折叠到 ROM 副本中 `n * 0x1000`（`n` 为 0..0xFFF）处的 4 KB 区块。

ROM 目标会实时写入卡带缓冲区。这已在修补后的 Ryubing 模拟游戏机构建上通过 IP 主机测得（未接触实机）：使用 `r0 = 0xFA3FF`（`dest` 为 0x083FF000，`n` = 0x3FF，区域条目 0x08）和 EWRAM 源数据（`r1` 为 0x0201C400，折叠偏移 0x1C400，掩码 0x3ffff）时，两项检查均通过，复制成功。卡带缓冲区 0x3FF000 处的字节与源数据的 0x1000 字节完全一致（0x3FF000..0x3FF31F 为选定模式的 200 个字，之后连同源缓冲区自身的尾部字节一起复制到 0x3FF320+；例如，两处的第 200 个字均为 0x11111000）。随后，模拟机在 0x083FF000 处的加载通过折叠后的 ROM 窗口读取到该模式。主机会话保持正常：载荷返回 1，`client->param` 携带模式的第一个字，游戏机显示成功消息并正常关闭连接。

以同样方式复制的代码可以执行。将源数据的第 0 个字设为两条指令组成的 THUMB 例程（`0x47706001`：`str r1,[r0]; bx lr`），第 1 至 199 个字仍为上述模式。复制后，载荷从折叠后的窗口回读到例程（`0x47706001`），随后将一次性测试值放入 `r1`、自身结果字的地址放入 `r0`，跳转到 `0x083FF001`。游戏机的响应携带该测试值，说明包装器的指令取值读取了系统调用写入的同一块实时底层存储，复制的字节通过正常取指路径作为代码执行。会话以成功消息结束，游戏完成保存。

写入在软复位后仍然保留。按下 A+B+START+SELECT 后，通过调试器回读折叠偏移 0x3FF000 处的同一块 4 KB 数据，逐字节完全相同（4096 字节中有 0 字节变化），而 EWRAM 中的源数据暂存区已被清空。复位后开启第二次会话，读取 0x083FF000（`0x47706001`），再携带新的测试值跳转到 0x083FF001，驻留例程返回该测试值。完全退出并重新启动应用后，模拟器会从 ROM 文件恢复字节：新进程在折叠位置保存的是文件中的原始内容。因此，写入的有效期为模拟器进程的生命周期。

如果 `+0x10` 处的区域后备指针为空，折叠偏移量等于或超过 `+0x20` 处的大小，或者剩余字节少于 `0x1000` ，则每一侧都会被拒绝（指针设置为空）。双方在复制 `0x1000` 字节之前解析。然后 `swi 0x56` 将 `0xFF` 存储在目的地 `+0xFF8` 上，不进行空检查：

    cmp   w19, #0x56
    b.ne  exit
    mov   w8, #0xff
    strb  w8, [x21, #0xff8]

`+0xFF8` 是扇区签名 [pokeldn/frlg/save/save_inject.py]：`0x08012025` 变为 `0x080120FF`，扇区无效。 `ReplaceSector` 写入并无效，`WriteSector` 写入。被拒绝的目的地使 `x21` 为空，因此 `swi 0x56` 在 `0xFF8` 处发生故障，即上面的中止。

在模拟游戏机上使用 `swi 0x48` 测量：

|致电 |结果 |
| --- | --- |
| `r0` 超过闪存大小的扇区，`r1` 未映射的区域 |未写入任何内容，闪存字节相同，无故障，无冻结 |
| `r0 = 30`、`r1 = 0x08000000`（ROM 标头）|扇区 30 成为卡带的第一个 4 KB，4096 字节中的 4096 个，邻居未受影响 |
| `r0 = 30`、`r1` EWRAM 缓冲区填充了污染物 |扇区 30 成为那些字节；缓冲区读回不变|
| `r0 = 0xFA3FF`（目标 0x083FF000），`r1` 为 EWRAM 缓冲区 | 复制写入卡带缓冲区：折叠偏移 0x3FF000 处的字节与源数据的 4 KB 逐字节一致；模拟机在 0x083FF000 处读取到该模式；会话正常结束 |
| 执行同样的复制，源数据第 0 个字为 THUMB 例程，随后携带 `r1` 中的测试值跳转到 `0x083FF001` | 复制的例程返回测试值；游戏机显示成功消息，保存并正常关闭连接 |
| 软复位后，通过调试器读取同一折叠位置 | 4 KB 数据逐字节相同（4096 字节中有 0 字节不同），而 EWRAM 的源数据暂存区已被清空 |
| 复位后，第二次会话读取例程，再跳转到 `0x083FF001` | 驻留例程返回新的测试值，在同一进程内跨复位仍可调用 |
| 完全退出并重新启动应用后，通过调试器读取同一折叠位置 | 该位置恢复 ROM 文件中的原始字节；写入的有效期为进程生命周期 |

它不会修改访客寄存器，也不会返回任何状态：只有快速读取才能区分已接受的呼叫和已拒绝的呼叫。

仅当游戏保存时，模拟器才会提交其 128 KiB 闪存映像，并携带外部扇区。系统调用写入后进行硬终止将使主机文件保持不变。一旦会话以成功消息结束，从神秘礼物会话内部进行的写入就会持久，从而节省
[mystery_gift_menu.c:1379]；在任何其他结果之后，并且来自驻留挂钩，它等待下一次保存。
<a id="the-breakpoint-hooks"></a>
### 断点挂钩

包装器的 GBA CPU 对象在 `cpu + 0x170` 处有 256 个钩子槽，每个 `bkpt` 立即数一个。 ARM 解码测试 `(insn & 0xFFF000FF) == 0xE1200070`，THUMB 解码 `(insn & 0xFF00) == 0xBE00` 位于
`main + 0x01FCE4`; `main + 0x01EFC0` 处的 THUMB 处理程序调用插槽中挂钩的 vtable 插槽 2
`imm8`（钩子，`&insn`，`bkpt`的地址，CPU）通过`main + 0x01F820`。返回 1 的钩子让核心执行它存储在 `insn` 中的指令； 0 或空槽使 `bkpt` 成为无操作。 `main + 0x022A2C` 注册一个钩子并拒绝已填充的槽。两个槽被填满：

|槽 |业主|钩子|它是做什么的 |
| --- | --- | --- | --- |
| `bkpt #0x52` | Sloop 组件，vtable `main + 0x1C3878` | `main + 0x05499C` -> `main + 0x056368` -> `main + 0x03E850` |下面的 librfu 补丁 |
| `bkpt #0xFF` |应用程序对象，vtable `main + 0x1B4078` | `main + 0x001140` |使用参数 1 发布事件 `0x82EF0054`，这将退出应用程序 |

加载时，包装器将三个补丁写入来宾的 ROM 副本中，仅超过 10 个字节
`0x08000000..0x09000000` 与卡带不同，在 v0 和 1.0.1 上类似（块校验和并通过神秘礼物客户端进行读取、零售和模拟）：

|地址 |卡带|来宾|
| --- | --- | --- |
| `0x081E1696` |拇指 `mov ip, r1` (`468c`) | `bkpt #0x52` (`be52`) |
| `0x081E187C` | ARM `ldr r3, [pc, #0x50]` (`e59f3050`) | `bkpt #0x52` (`e1200572`) |
| `0x081E1F90` | ARM `mov lr, r0, lsr #14` (`e1a0e720`) | `b 0x081E1FB8` (`ea000008`) |

第三个补丁删除了等待循环。 `0x081E1F74` 处的函数根据调用者的 `r0`（`r0` 屏蔽为 u16、`lr = r0 >> 14`）轮询 `REG_SIOCNT` (`0x04000128`) 位 2，并在字节到达时提前返回`[*(0x03000030) + 0x10]` 为 1，清除它并回答 1。在仿真中，轮询永远不会匹配，因此包装器将主体替换为 `mov r0, #0; return`：等待立即回答 0。

`bkpt #0x52`以地址为键：它的钩子保存了`+0x120`和`+0x148`的两条记录`{u32 pc, u32 original insn, ..., u32
hits at +0x0C}`，`main + 0x0546C0`匹配地址并返回原始指令。在`Sio32IDMain`补丁（`0x081E1696`）中，它解析来宾`r0`（`&gRfuSIO32Id`）并将`0x8001`存储在`+0x0A`，适配器ID `AgbRFU_checkID`等待[librfu_sio32id.c]。任何其他地址的 `bkpt #0x52` 都会在会话的剩余时间内将第二条记录（`0x081E187C` 补丁）重新加密到自身。
<a id="the-record-resolver-main--0x03e850"></a>
#### 记录解析器 (`main + 0x03E850`)

钩子`main + 0x05499C`将`bkpt`本身写入`insn`，然后调用虚函数
`[[x0 - 0x60] + 0x98]`与`x0 - 0x60`为`this`（拆解，`main + 0x549c4`-`0x549cc`）；对于解析为 `main + 0x056368` 的 Sloop 组件，它派生记录持有者 `[component +
0x40] -> [+0xA8] + 0x68` 并用它尾部调用解析器 `main + 0x03E850`，`&insn`，
`bkpt` 的地址和 CPU（`0x3e850` 在图像中只有一个调用者，`0x56378`）。客人
`r0` 的顶部字节仅稍后在下面的解析器的 Sio32ID 仿真内选择一个区域。解析器：

- 匹配记录 1（持有者 `+0x120`）到 `main + 0x0546C0`：匹配会增加 `+0x0C` 处的命中计数，并将 `+0x4` 处的原始数据复制到 `insn` 中，然后内核执行该记录；
- 在记录 1 匹配上继续进入 Sio32ID 模拟：来宾 `r0` 通过区域表折叠，折叠偏移量仅针对 `offset < region size` (`+0x20`) 进行边界检查，并且在持有者 `+0x108` 处设置标志字节，`strh` 存储`backing + offset + 0xA` 处的 `0x8001` 和 `main + 0x2209C` 将 `backing + offset + 1` 处的字节写入客户机 `r1` (`str w2, [regfile + 4 + 0x48]`)。 `+0xA` 不受边界检查覆盖，因此区域最后 `0xA` 字节中的偏移量会写入超过该区域的后备分配，最多超出其末尾 11 个字节；设置标志且偏移量超出范围后，后备指针为空，并且包装器读取地址 `0x1` 时出错。当标志清除时，解析器返回而不进行写入。支架`+0x108`是`[+0xA8] + 0x170`（支架是`[+0xA8] + 0x68`），与下面的适配器电源开关相同的字节：在游戏机自己的神秘礼物搜索过程中通过`main + 0x03E850`进行3次实时读取每次都找到它`0x1`，所以`swi 0x40` 单独武装写入路径。
- 在记录 1 不匹配时，重新键入记录 2（持有者 `+0x148`）：`record2.pc := the bkpt address`，然后匹配它，因此核心执行记录 2 的原始记录，该记录从未更新：过时的 `0x081E187C` 原始 `e59f3050` (`ldr r3, [pc, #0x50]`)，在任何地址无论访客处于何种 CPU 模式，访客都执行 `bkpt #0x52`。在游戏机自己的神秘礼物搜索中，每个调度都通过此路径重新键入：记录 2 的命中计数（持有者 `+0x154`）在三个实时读取中每 0.33 秒前进约 20，记录 1 没有移动，因此 STWI 驱动程序自己的命中计数`bkpt #0x52` 位于 `0x081E187C` 的运行时 IWRAM 副本，而不是 `Sio32IDMain` ROM 站点，是搜索屏幕每帧运行一次的内容。
- 在记录 2 与 `+0x108` 标志设置匹配时，落入 `main + 0x03E954`：它折叠存储在持有者 `+0x170` 处的地址，读取折叠地址处的字，并使用字的顶部字节作为区域选择器，使用字本身作为要再次折叠的地址，进行边界检查，递减持有者处的计数器`+0x42B8 + 0x7C`。
- 在记录 2 与 `+0x108` 标志清除匹配时，落入 `main + 0x03E960`：它折叠存储在持有者 `+0x170` 中的地址，读取那里的一个字，并针对 `0x600` 测试其位 15 到 26。在匹配时，它会通过同一区域表折叠该字的低 24 位，进行边界检查，并递减持有者 `+0x42B8 + 0x7C` 处的计数器；如果不匹配，什么也没有。

来宾控制整个触发器：使用选定的 `r0` 分支到 `0x081E1696`（修补站点，THUMB）的 VOC 使包装器在 `fold(r0) + 0xA` 处写入 `0x8001` 并将 `r1` 设置为 `fold(r0) + 1` 处的字节；在其他任何地方执行 `bkpt #0x52` 的 PBS 都会执行过时的内容
`e59f3050` 有。两者都是宾客亲属； `+0xA` 写入是离开客户机区域的唯一路径：它可以写入 `0x8001` 两个常量字节，最多可超出任何区域的后备分配（包括 16 MB ROM 副本）的 11 个字节。
<a id="what-follows-the-rom-buffer-the-sloop-component"></a>
#### ROM 缓冲区之后是：Sloop 组件

ROM 对象的掩码 (`+0x34`) 为 `0x1ffffff`，而卡带占用 `0x1000000` 字节，因此折叠 `0xFFFFF6..0xFFFFFF` 通过边界检查，并将写入紧接在 ROM 缓冲区后面的十个字节上。那里的对象是Sloop组件（[断点钩子](#the-breakpoint-hooks)）：它的第一个字是vtable指针
`main + 0x1C3878`、`+8` `0x000004bf`、`+0xC` `0x0A828400`、`+0x18` 和 `+0x20` `main + 0x16EB83`、
`+0x28` `0x655db` 堆指针，`+0x60` 和 `+0x88` 进一步的 vtable（`main + 0x1C3948`，
`main + 0x1C3978`)、`+0xE0` CPU 总线对象。

邻居在引导之间发生变化：一个引导的 ROM 邻居是一个对象，其第一个字是 vtable `main + 0x1C36D8`，其 `+0x60` 是 vtable `main + 0x1C3790`。构造函数
`main + 0x547CC` 准确地写入该对，读取 `main + 0x86D67E8` 处的静态指针（加数 `main + 0x1C36C8` [main_relocs.json]）。该类的字段由其自己的构造函数和自己的代码编写；访客会话中的任何存储都不会到达他们。

在修补站点，卡带自己的代码停放自己的 `r0`（`ldr r0, [pc, #0x10]` 加载
`0x0300744A`，它自己的`&gRfuSIO32Id`，IWRAM），所以游戏自己的调度总是折叠到游戏自己的结构：包装器的`0x8001`存储是适配器id到达
`gRfuSIO32Id.lastId`（`RFU_ID = 0x8001` [librfu.h]），值`AgbRFU_checkID`等待。分支到 `0x081E1696` 的书签会直接跳过该负载并停放自己的 `r0`，这才是移动商店的原因。

对strh本身（`main + 0x3E928`）及其延续进行检测：通过直接分支和`r0 = 0x08FFFFF6`，商店的`x8`是`backing + 0xFFFFF6`（`0x66209f9ff6`，尾部的
`ff` 填充在其后面），预/后转储将 `0x66209fa000` 读取为存储之前的 `78 98 6c 08 ...` 和存储之后的 `01 80 6c 08 ...`：两次存储相隔约 90 毫秒（视线的触发器，然后通过与停放的 `r0` 相同的站点进行第二次调度）。

对组件前两个字节的写入会植入 vtable 指针 `0x086C8001`，然后调度程序 `main + 0x1F820` 从中读取钩子槽 19（偏移量 `+0x98`）：位于的 8 个字节
`main + 0x1C2099` 是 `f7 01 00 00 00 00 00 00`，因此包装器的下一个虚拟调用在来宾 PC `0x1F7` 上执行，这是一个未映射的地址，否则来宾路径无法到达。在模拟器上，这会中止进程（`Unhandled guest exception InstructionAbortLowerEl`）；与区域内的折叠相同的触发器会在本地折叠的只写中结束会话，没有这样的调度。站点上的卡带自身代码排除了其他候选者：`mov ip, r1` 将 `ip` 存储为值 (`mov r0, ip; strh r0, [r4]`)，它永远不会分支。

仅当 `[component + 0x40] -> [+0xA8] + 0x170` 处的字节被设置时，挂钩才会起作用：虚拟适配器的电源开关。 `swi 0x40` 设置它，`swi 0x41` 清除它（处理程序 `main + 0x05706C` 存储
`number == 0x40`; [sloopsvc.c:23] 中的“未引用的标志设置器”）。神秘礼物菜单中的 `swi 0x41` 停止 RFU 帧：游戏引发链接错误并离开 LDN。适配器在软重置后保持关闭状态，因此下一个无线菜单报告“L'adaptateur sans fil GBA n'est pas connecté”。该字节在软复位后仍然存在；重新启动，或
`swi 0x40`，恢复它。每帧读取：`swi 0x41`，然后 `swi 0x40` 在一个 VOC 中是无害的。
<a id="the-chain-from-a-bkpt-to-the-resolver"></a>
#### 从 bkpt 到解析器的链

NSO 的 vtable 槽保存文件中未重定位的加数；加载程序添加映像库（`main` 位于 `0x8506000`）。应用该基础后，访客 `bkpt #0x52` 运行此链：

- 两个解码路径（THUMB `main + 0x1EFE0`、ARM `main + 0x1B7B8`）均将调度程序 `main + 0x1F820` 调用为 `(CPU, bkpt address, immediate, &insn)`；
- 调度程序接受 hook = `[CPU + (imm & 0xff) * 8 + 0x170]`；对于`bkpt #0x52`，即`component + 0x60`，组件的子对象（该组件是GBA CPU对象：`+0x84`当前pc，`+0x170`挂钩表，`+0x960`第二总线表，`+0xE0`总线对象）。它读取钩子自己的vtable（`main + 0x1C3948`）插槽`+0x10`，并将其称为`f(hook, &insn, bkpt address, CPU)`。槽位`+0x10`直接为`main + 0x5499C`；
- `main + 0x5499C` 将 `0xE1200572` 写入 `insn`，然后加载 `[component]` 并使用 `(component, &insn, bkpt address, CPU)` 尾部调用 `[that pointer + 0x98]` 处的虚拟：插槽 `+0x98` `main + 0x1C3878`是`main + 0x56368`，其导出记录保持者并到达解析器`main + 0x03E850`。

因此，在插槽 `+0x98` 处消耗了组件前 10 个字节的存储；的
`+0x10` 读取发生在钩子对象上，位于这十个字节之外。解析器的写入目标是 `buffer_data + fold + 0xA`，折叠是所选区域的插槽 9（[`swi 0x52` 和 `swi 0x55`：内存总线](#swi-0x52-and-swi-0x55-the-memory-bus)）。
<a id="what-a-plant-over-a-seam-does"></a>
#### 跨分配边界的指针植入效果

当 `fold = size - 0xB`（未越界）时，写入位置为 `(size-1, size)`：区域最后一个字节写入 `0x01`，相邻分配块的第一个字节写入 `0x80`。当 `fold = size - 0xA` 时，写入位置为 `(size, size+1)`，即将 `0x01 0x80` 写入相邻分配块的前两个字节。一次神秘礼物会话中，每次访问该位置都可使用一个选定的折叠值。

该位置背后的函数体通过五个字组成的栈帧返回：位于 `0x081E177C` 的尾声是 `movs r0,#0 ; pop {r4,r5,r6,r7} ; pop {r1} ; bx r1`。直接跳入该位置的载荷绕过了函数序言，必须自行压入这个栈帧，并让 `lr` 指向后续执行位置；函数体随后返回载荷，载荷便可继续执行代码并正常结束会话。如果载荷压入其他栈帧，就会错误地从调用者的栈中恢复；实测运行会带着同一个停留的 `r0` 再次进入该位置。

窗口 4（GBA IO 寄存器）映射到紧邻其自己的后备分配后面的 0x400 字节区域对象：后备位于总线 `+0x14C0` 处，对象位于总线 `+0x18C0` 处，按键中断子对象嵌入在对象 `+0x88` 处。因此，工厂落在总线调度每个 IO 访问所通过的对象上。该映像的 CPU 内核在访问器形状中具有 210 个调用站点（[`swi 0x52` 和 `swi 0x55`：内存总线](#swi-0x52-and-swi-0x55-the-memory-bus)）。

在模拟游戏机上：

|植物 |消耗于 |结果|
| --- | --- | --- |
|组件字节对 `01 80` (`0x086C8001`) |插槽 `+0x98` 在 `main + 0x1C2099` 处读取，未重定位，`0x1f7`（[上面](#what-follows-the-rom-buffer-the-sloop-component)）| |
|组件字节 0 `0x80` (`0x086C9880`) | `main + 0x5492C`，同样方法，无需`-0x60` |它在仍然植入的组件上重新读取 `[x0] + 0x98` 并递归到自身；线程堆栈耗尽且进程因数据中止而终止 (`InvalidMemoryRegionException`) |
| IO 对象字节 0 `0x80` (`0x086C8480`) |巴士的商店槽位 `+0x38`/`+0x40`，其植入目标是原始 `0xffffffffffffe5e0` 和 `0` |工厂在 ~30 ms 内中止进程后的第一个 IO 存储；加载目标（`main + 0x30EAC`、`main + 0x31114`、`main + 0x36D54`）从未运行|
|名称哈希块字节 0 (`0x80`) |该块是一个 SDK 绑定器/表面描述符对象（`android.gui.IGraphicBufferProducer` 和朋友是 SDK 映像中的静态字符串），而不是调度对象 |没有反应；游戏运行到自己干净的退出|

工厂 `0x086C8080`（字节 `80 80`：每个 `bkpt #0x52` 然后运行纯计数器 getter
`main + 0x1F7F0`，因此每个 bkpt 都变成无操作）需要两次写入，中间不分派；一个会话购买一次写入，并且途中的两个单写入状态都会终止该进程。相反，通过调试器植入，该指针在游戏运行且进程处于活动状态时保持在原位置五分钟。图像中没有代码站点在初始化后写入包装器对象的标头。
<a id="every-placement-a-one-write-plant-can-make"></a>
#### 单次写入可形成的全部植入位置

植入会在相邻对象上写入两种字节模式之一：首字节的 `80`（本区域最后一个字节接收 `01`），或第 `k`、`k+1` 字节的 `01 80`，其中 `k` 为 0..9。相邻对象的前八个字节是虚函数表指针，因此使用方读取该指针后，会按照文件映像及其重定位解析目标。以下四种情况会读取 main 的运行时内存：

| 对象 | 写入字节 | 植入指针 | 使用方 |
| --- | --- | --- | --- |
| 组件（虚函数表 `main + 0x1C3878`） | +0 处的 `80` | `0x086C9880` | `bkpt #0x52` 调用链中的 `[P + 0x98]` = `main + 0x1C3918` = `main + 0x5492C` |
| 组件 | +0..1 处的 `01 80` | `0x086C8001` | `[P + 0x98]` = `main + 0x1C2099` = 原始值 `0x1F7` |
| IO 对象（虚函数表 `main + 0x1C2408`） | +0 处的 `80` | `0x086C8480` | 下表中的总线访问槽位 |
| IO 对象 | +0..1 处的 `01 80` | `0x086C8001` | 总线访问槽位：`0x1F7`、零和原始加数 |

其他位置解析到映像之外。+1 处的 `01 80` 会得到 `0x08800178`（组件）和 `0x08800108`（IO 对象），位于 main 的 bss 中。全零 bss 模型预测此处会调用空指针；仅凭文件映像无法确定运行中会话的实际内容。+2 至 +7 处的 `01 80` 会改变字节 2 或字节 3，使使用方的读取本身就发生异常。+8 和 +9 处的字节对落入 `+8` 字段（组件的 `0x000004BF` 在 +8 写入后变成 `0x00008001`，在 +9 写入后变成 `0x008001BF`），虚函数表指针保持原样，因此仍分派给对象自身的方法。

如果两次访问之间没有 `0x04` 访问，两次写入的字节对可以在 IO 对象上叠加；载荷从 ROM 或 EWRAM 取指本身不会访问该对象。重复写入同一位置具有幂等性，+8 或 +9 处的写入也不会改变虚函数表指针。仅限字节 0 和 1 的不同写入仍可能得到上表中的映像内指针；改变指针高位字节的组合需要单独分析。对于组件，下一次 `bkpt #0x52` 将使用当前植入值。连接建立时 STWI 驱动每秒约产生 60 次此类调用，但仅凭频率不能断定载荷每两次访问之间必定插入一次调用。

IO 对象植入后的代码块按总线槽位列于下表。访问类型由调用者对结果使用的掩码确定（16 位读取为 `main + 0x18378` 的 `and #0xffff`，32 位读取为 `main + 0xBDB8` 的字循环移位，8 位读取为 `main + 0xD914` 的 `and #0xff`）。

| 总线槽位 | 访问 | 植入目标 | 以 IO 对象作为 `this` 时 |
| --- | --- | --- | --- |
| `+0x18` | 16 位读取 | `main + 0x30EAC` | 按键处理程序的默认分支：`w2` 为完整的 `0x04xxxxxx` 地址，大于其分支表中的所有寄存器编号，因此将 `w3 & 0xffff` 存入 `[x1]`；`main + 0x18330` 调用处传入 `x1 = CPU + 0x20` 和 `w3 = 1`，客户机读取返回处理程序遗留的 `w0` |
| `+0x20` | 32 位读取 | `main + 0x31114` | 以 `(x1 from the site, IO + 0x20)` 调用 `main + 0x3580C`，随后以 `x0 = [[IO + 8] + 0x90]` 尾调用 `main + 0x22404` |
| `+0x28` | 8 位读取 | `main + 0x36D54` | 0x76000 字节对象的清理函数族：`[x0 + 0x76C70]`、`+0x76C30`、`+0x76C00`、`[x0 + 0x4E68]` |
| `+0x30` | 写入 | `main + 0x36E40` | 执行 `x0 -= 0x1A10`，随后调用 `main + 0x3664C`，对调整后的指针执行同一清理函数族 |
| `+0x38` | 写入 | 原始值 `0xFFFFFFFFFFFFE5E0` | 调用发生异常 |
| `+0x40` | 写入 | `0` | 调用空指针 |
| `+0x48` | | `main + 0x36E4C` | 清理函数族，访问 `+0x76C60`、`+0x76C20`、`+0x76BF0`、`[x0 + 0x4E58]` |
| `+0x68` | | `main + 0x310A8` | 执行 `x0 -= 0x10`，随后调用 `main + 0x30EAC` |

上述位置都不会到达由客户机内存提供的分派目标：四种 main 内位置读取 main 自身的数据，IO 对象的代码块则以总线参数调用 main 自身的处理程序。

在零售版实机上（Switch Lite、英语版火红，载荷由 XIAO ESP32S3 无线开发板通过 LDN 发送），应通过连接断开方式区分组件植入和范围内写入。每次运行都在脚本执行约两秒后返回 HOME，并显示“由于发生错误，软件已关闭”，因此该提示无法区分情况；Pia 正常离开消息（`Session type 3`）则可以：

- 折叠值越过卡带缓冲区末端一个位置时（组件，`r0 = 0x08FFFFF6`），游戏机离开 LDN，却没有发送 `Session type 3`（标签 `pl01`、`pl04`），对应模拟器分派中出现的突然终止，现已在硬件上确认。
- 折叠值位于范围内时（`r0 = 0x08FFFFF0`，标签 `pl03`，写入缓冲区 `+0xFFFFFA`），以及 EWRAM 末端越界落入 VRAM 时（`r0 = 0x0203FFF6`，标签 `pl02`），游戏机发送 `Session type 3` 并正常离开；普通卡片会话（`scratchpad/re1_host.log`、`rt02`..`rt04`）也如此。

因此，在零售版实机上，折叠值越过 ROM 缓冲区末端时，记录解析器的写入确实到达仍在使用的封装层对象，并导致应用终止；同样的写入若留在客户机可见内存中则不会。载荷压入函数体所需栈帧后，在实机上也能从该位置返回。

植入后的分派发生在应用下一次 `bkpt #0x52`。游戏从两处产生此调用：STWI 驱动的 IWRAM 副本（连接建立时每秒约 60 次，来自实时命中计数），以及游戏在该位置对 `Sio32IDMain` 的调用（记录 1 的一次实时读取中命中 12 次）。虚函数表低字节变成 `0x80` 后，分派到达 `main + 0x5492C`，它基于植入指针重新读取 `[component] + 0x98` 并不断递归，直至线程栈越界；游戏机返回 HOME，没有发送 `Session type 3`。载荷可将 IWRAM 副本中的 `bkpt #0x52` 恢复为卡带原始指令，并通过 `swi 0x48` 还原卡带副本中包含两处位置的 4 KB 块，撤销两个加载时补丁。这样会移除两个调用来源：游戏机随后显示游戏自身的通信错误，发送 `Session type 3` 离开 LDN，提交网络报告并继续运行。这时植入只是未被使用，并未修复；没有代码恢复虚函数表。还原后的卡带副本也会保持到进程结束：无线菜单会提示适配器未连接，完整重启应用后才会重新应用封装层的加载时补丁。

<a id="where-the-boundary-stands"></a>
### 边界所在

本页检查的客户机路径包含越过区域后备存储的写入：解析器在 `fold + 0xA` 处执行的 `0x8001` strh；使用植入指针的代码从 `main` 自身的静态地址数据读取目标（[单次写入可形成的全部植入位置](#every-placement-a-one-write-plant-can-make)）。该节列出了四种读取运行时内存的情况及其他位置的结果；会话中低字节被写为 `80` 后，组件的使用方是 `bkpt #0x52` 钩子链中的 `main + 0x5492C`。单次写入分析没有发现由客户机字节提供的调用目标，但不能据此确定任意多次写入序列的结果。移除调用链的两个客户机来源可阻止已观察到的分派。系统调用写入组件的字段及其读取方见[剩余的系统调用](#the-remaining-syscalls)；`main + 0x1C36C8` 类的字段由自身构造函数及代码写入（[ROM 缓冲区之后的内容](#what-follows-the-rom-buffer-the-sloop-component)）。第三个加载时补丁替换等待循环。脏话过滤器的两个缓冲区均限制在调度器自身栈帧内（[脏话过滤器](#the-bad-word-filter)）；闪存扇区路径的边界见[闪存扇区路径](#the-flash-sector-path)。

Pia 两端的路径均已解码：客户机的 `RfuGameData` 和用户名重新打包为广播记录并进行 base85 编码（[广播记录](#the-advertisement-record)）；对端的 `NetworkInfo` 字节原样进入候选列表（[封装层自身的扫描流程](#the-wrappers-own-scan-pipeline)）；对端的会话消息在处理程序读取之前通过按类型划分的边界检查（[Pia 会话消息调度器](#the-pia-session-message-dispatcher)）。下方[线缆数据解析](#the-pia-librarys-own-wire-parsing)一节追踪静态链接的 `PiaCommon-6_42_1` 从 UDP 套接字到会话队列的路径；该追踪并未穷尽验证所有长度检查或消息处理程序。

<a id="the-remaining-syscalls"></a>
#### 剩余的系统调用

处理程序地址是 `main + 0x05706C + entry * 4`，来自 `main + 0x17D7F6` 的跳转表。最后一栏是来自神秘礼物客户端`sloop-svc`的一期内容。

|瑞士 |处理程序、被调用方 |它是做什么的 |发布一次后观察 |
| --- | --- | --- | --- |
| 0x40，0x41 | `main + 0x05706C` |适配器电源开关：将 `r0 == 0x40` 存储在 `[component + 0x40] -> [+0xA8] + 0x170` |神秘礼物菜单中的 swi 0x41 会引发链接错误并留下 LDN ([上面](#what-follows-the-rom-buffer-the-sloop-component)) |
| 0x42 |模式开关 `main + 0x0588A0` | `rfu_REQ_startSearchChild` [sloopsvc.c:49];将网络管理器设置为模式 2 |结束会话并出现链接错误；没有打开接入点|
| 0x43 | `main + 0x0570EC` -> `main + 0x058AD0` | `rfu_REQ_startConnectParent`，`r0` [sloopsvc.c:91]中的16位PID；相同模式切换|缓冲区脚本回答，然后在关闭时显示“Erreur de connexion” |
| 0x44 | `main + 0x057100` -> `main + 0x058B0C` | `rfu_REQ_stopMode`，无参数 [sloopsvc.c:102] | 0x43之后，没有明显的变化|
| 0x45 | `main + 0x057110` -> `main + 0x058900` | `rfu_REQ_startSearchParent`、`rfu_STC_readParentCandidateList` 与 `&gRfuLinkStatus` [sloopsvc.c:67-75]；将包装器的扫描结果通过区域表复制到 `struct RfuLinkStatus`、`findParentCount` [include/librfu.h] 首先在偏移量 8 处 | 220 个归零字节保持为零（礼物会话中没有父节点搜索） |
| 0x46 |跳转表条目 `0x147` |落入调度程序的出口：系统调用不执行任何操作 | |
| 0x47 | `main + 0x05715C` -> `main + 0x058680` | `rfu_REQ_configGameData`、`r0`指向`struct RfuGameData`（16字节）和用户名（8、`RFU_USER_NAME_LENGTH`）[sloopsvc.c:34-46; include/link_rfu.h:103-115,232]；如果更改，则将所有 24 复制到 `component + 0x6050D8` 和 `activity`（第二个 64 位字的位 16-22）到 `component + 0x605360` | `activity` 0x30 均逐字节落地 |
| 0x48，0x56 | `main + 0x057084` |闪存扇区副本：目标扇区是客户 `r0`，源扇区是 `fold(guest r1)`，通过相同的区域表并根据区域大小进行边界检查，最大为 4 KB | [Flash扇区路径](#the-flash-sector-path) |
| 0x49 | `main + 0x0571A8` -> `main + 0x0588D0` |在 `component + 0xD0` 对象上调用 `main + 0x0588D0` ；不接受任何客人的争论 |返回 0 |
| 0x4A | `main + 0x0571B8` -> `main + 0x058AB8` | `component + 0xD0` | 相同形状返回 0 |
| 0x4B | `main + 0x0572C4` |没有争论；位 1 使 `RfuMain1` 从 `gHostRfuGameData->compatibility.playerTrainerId` 重新播种 RNG，位 0 清除使 `SpawnGroupLeaderAndMembers` 提前退出领导者 [sloopsvc.c:132-145] | 0 |
| 0x4C | `main + 0x0571CC` |在 `[component + 0xE8] + 0xA0` 上调用 `main + 0x05D930`，当它回答 0 时，在全局指针上调用 `main + 0x049D28`；没有访客数据到达 |返回 0 |
| 0x4D | `main + 0x0571FC` |坏字过滤器：解析 `r0` 并在 `fold(r0)` 处读取最多 256 个字节，[如下](#the-bad-word-filter) | |
| 0x4E |跳转表条目 `0x147` |落入调度程序的出口：系统调用不执行任何操作 | |
| 0x4F | `main + 0x057248` -> `main + 0x058B54` |在其堆栈上构建 `{u16 tag 0x4757; u32 value = r0}`；标记属性调度程序 `main + 0x4EBD0` 和设置程序 `main + 0x058BB4` 将未验证的值存储在 `component + 0x6052A0` |写3和`0x7FFFFFFF`，每个后面跟着0x49和0x4A，没有任何可观察到的改变|
| 0x50 |吸气剂 `main + 0x058BA4` |读取相同的 4 字节计数 | |
| 0x51 | `main + 0x057270` -> `main + 0x0511BC` |将 `component + 0x3404` 读入输出参数并将其清除；输出参数始终是调度程序自己的堆栈槽 | |
| 0x52 | `main + 0x05728C` | 通过总线对象的区域表（`[component + 0xE0] + 0x50`）折叠客户机 `r0`，并调用区域的 `+0x48` 折叠方法。客户机 `r1` 非零时，还运行指针解析器 `main + 0x562CC`：以无界索引 0..255 读取 `[[bus] + 0x50 + (r1 >> 24) * 8]`，将所得值的 `+0x48` 作为虚函数调用，随后在 `offset < size` 时返回 `backing + offset`。该处理程序是解析器的唯一调用方，它丢弃解析结果并返回 `r0 = 0`，因此客户机 `r1` 读回 0。运行时读取的 256 个条目是 main 自身的方法指针、负数和零，没有包含 `+0x48` 方法的对象 | |
| 0x53 | `main + 0x0572D4` |答案 `component + 0x2770 == 0`（通过 `[component + 0xD0]`）| |
| 0x54 | `main + 0x0572EC` | `svc_CommsAllowedByParentalControls` [sloopsvc.c:182] |返回 1 |
| 0x55 | `main + 0x057304` |将 `r0` 存储在 `component + 0xE1BC`，通过区域表折叠存储的字并读回一个字节（[播放报告的构建来源](#what-the-play-reports-are-built-from)) | |
| 0x57 | `main + 0x057330` | `MonsSelect` 进入报告副本 `component + 0x140` | |
| 0x58 至 0x60 |跳转表条目 `0x147` |落入调度程序的出口：系统调用不执行任何操作 | |
| 0x61 | `main + 0x057340` -> `main + 0x058B2C` | `svc_SetActivity`;仅针对 0x41 至 0x48 写入 `r0` 至 `component + 0x605360`，联合房间活动代码 | 0x45：被调用者的`ret`（`main + 0x058B50`）上的断点读取`w1`，字段为0x45；正常关闭 |
| 0x62 | `main + 0x057354` | `component + 0xE1B0` 加 1，下一份报告为 `CommsError` | |

通过 `main + 0x2209C` 返回答案：客人 `r0` = 1 当号码大于 0x2A 时，客人
`r1` = 处理程序的应答词。没有处理程序的答案带有包装器地址。

`component + 0x6052A0` 是 16 个字节：4 个字节计数，4 个未使用，一个指向 `main` 的 8 字节指针。新推出：计数 1，指针 `main + 0x1E8D20`，一个指针数组，在一个填充槽后有两个空值。

标记属性调度程序 `main + 0x4EBD0` 遍历组件上的侦听器列表：
`0xd0`在`component + 0x10`，计数在`+0x688`，使能字节在`+0x690`；对于第一个字为 2 的每个条目，它使用 `entry - 8` 处的 8 个字节和标记条目调用组件 vtable 槽 `+0x50`。设置器 `main + 0x058BB4` 是 `0x4757` 监听器。 `main + 0x50618` 处的 `0x59` 监听器将 `[tagged entry + 4]` 处的值写入 `component + 0x3324 + index * 4`，索引从 `[x2]` 读取，并以 `main + 0x4DB0C` 为界 0..7。没有系统调用构建 `0x59` 条目或提供第三个参数，并且调度程序的十二个调用从包装器内部字段构建其条目。 `0x4757` 侦听器存储的计数
`component + 0x6052A0` 没有读取器，但有 getter `main + 0x058BA4` (`swi 0x50`)：在映像中形成偏移量 `0x6052A0` 或 `0x6052A8` 的每个其他代码位都会在 init 处写入它或它旁边的指针。 `0x4F` 调用者提供的值是惰性的。

游戏机自己的神秘礼物搜索在任何缓冲脚本之前发出 `swi 0x47`，广告
`activity` 0x15 (`ACTIVITY_WONDER_CARD` [include/constants/union_room.h:46]);发票的调用会覆盖它。 `main + 0x0586B4` 处的断点读取 `component + 0x605360` 到 `x8 + 0x280`。游戏数据对象（虚函数表 `main + 0x1C3B30`）是 CPU/总线对象 `bkpt #0x52` 的挂钩表解析的兄弟（虚函数表 `main + 0x1C3878`、区域表、系统调用 0x45、0x48、0x52、 0x55、0x62)；实时地址的不同之处在于 `0x100000000`。

每个候选布局 0x45 写入未解决：复制循环的字节计数不匹配
`sizeof(struct RfuTgtData)`;在依赖它之前先阅读它。

`component + 0x6050D8` 保存 `swi 0x47` 复制的 24 字节（[main + 0x058694]，从客户机 `r0` 缓冲区执行预索引存储）；同一处理程序会读回这些字节并重新打包为广播记录。`component + 0x605360` 的读取方是活动比较函数 `main + 0x058698`（通过 `component + 0x6050E0`）和 `svc_SetActivity` 的设置函数 `main + 0x058B40`，两者分别比较或存储活动代码。

<a id="the-advertisement-record"></a>
#### 广播记录

`swi 0x47` 处理程序使用客户机自己的 `RfuGameData`（16 字节）和 `gHostRfuUsername`（8 字节），组装广播携带的 24 字节 RFU 记录 [include/link_rfu.h:103-115, src/sloopsvc.c:34-46]：

| 记录 | 来源 |
| --- | --- |
| `[0:2]` | `RfuGameData[2:4]`，训练家 ID（`compatibility.playerTrainerId`） |
| `[2:10]` | 用户名 |
| `[10:12]` | 封装层的 RFU 会话 ID，`main + 0x3F2E0([component + 0x6050D0])` |
| `[12:16]` | `RfuGameData[4:8]`，`partnerInfo` |
| `[16:20]` | 搜索字，由 `RfuGameData[0:2]` 和 `[8:12]` 打包 |
| `[22:24]` | `RfuGameData[8:10]`，`tradeSpecies` |

搜索字的各位来自两个源字：0-6 为活动（`RfuGameData` 的位 16-22），7 为性别（位 24），8-10 为版本（`RfuGameData[0:2]` 的位 10-12），11-14 为语言（位 0-3），15 为 `startedActivity`（位 23），16 为 `canLinkNationally`（位 7），17 为 `hasNationalDex`（位 8），18-23 为 `tradeType`（位 10-15），24 为 `gameClear`（位 9），25-31 为 `tradeLevel`（位 25-31）。`hasNews` 和 `hasCard`（位 4 和 5）未被复制。`[20:22]` 的两个字节保留栈帧中的原值。

编码器 `main + 0x2A90` 每 4 字节组写入五个字符，低位数字在前；字符表从 `0x23` 开始，跳过 `0x5C`，输出将超过所给容量时拒绝编码。处理程序为这 24 字节传入 `0x20` 的容量，足以容纳 30 个字符，再将文本存入 `component + 0x6C0`，将其 `strlen` 存入 `component + 0x700`（`main + 0x15FAE0` 和 `main + 0x15FB20` 是 `strlen`/`memcpy` 的 PLT 桩）。

主机信标复制的已捕获应用数据（`pokeldn/frlg/link/host_beacon.py`）共 122 字节：`0x5C` 字节的 Pia 系统头，加上 30 个字符。解码后是训练家 ID `0x1050`、名字 `GREEN`、RFU 会话 ID `0xac65` 及搜索字 `0x1584`（活动 4、版本 5、语言 2，位 7 已设置）。

记录文本进入处理程序临时构造的广播数据生成器（类虚函数表 `main + 0x1CB8C8`，构造函数 `main + 0x87514`）：`+0x1C` 是 `0x180` 字节的 Pia 广播区域，`+0x18` 是已用大小，初值为 `0x5C` 字节的头部；应用数据指针 `main + 0xA2C70` = `+0x78`，应用数据大小 `main + 0xA2C90` = 已用大小减去 `0x5C`，上限为 `0x124`（槽位 `+0x28`，`main + 0x875AC`；头部偏移 `0x5C` 位于槽位 `+0x30`，`main + 0x875A4`）。`main + 0xA3480` 通过保存在 `+8` 的缓冲区对象，在应用数据偏移处追加 30 个字符（容量由缓冲区虚函数表槽位 `+0x28` 提供，已用大小位于缓冲区 `+0x18`，追加操作会设置缓冲区 `+8` 的位 1）；它的唯一调用方是处理程序（`main + 0x58838`）。随后，处理程序在 `main + 0x58854` 交付生成器：`x0 = [component + 0x3528]`，调用 `main + 0xB1304`。该方法调用 `[session + 0xD0]` 上的方法并将它作为参数传递，清零 `+0xD8` 的 u32，然后调用 `main + 0xD4DD0(x0 = [session + 0x70], x1 = [session + 0xD0], x2 = [session + 0x30], x3 = the
builder)`。交付代码取出 `X = [session + 0x30]`，以 `(X, [session + 0x70] + 0x90, builder)` 调用 `X` 的虚函数表槽位 `+0xA8`，前提是 `X` 的槽位 `+0xD8` 返回真、`+0xE8` 返回假。会话的 `+0x30` 由 `main + 0xAF760` 从 `[[session + 8] + 0xB8]`（会话所有者的 `+0xB8`）设置。

`X` 具有门面类的结构：`nn::pia::local::LocalFacade`（虚函数表 `main + 0x1CB548`）与 `nn::pia::net::NetFacade`（`main + 0x1CBE60`）共用实现。其槽位为：`+0xA8` = `main + 0x8D4AC`，`+0xD8` = `main + 0x8D84C`（门面的 `+0x28` 已设置且 `+0x30` 非空时返回真），`+0xE8` = `main + 0x8D920`（`[[facade + 0x30] + 0x12D8]` 非零时返回真）。门面的 `main + 0x8D4AC` 通过 `main + 0x8C6FC` 验证，锁定管理器（通过 `main + 0x94B78` 锁定 `[facade + 0x30] + 0x2B8`，因此门面在 `+0x30` 持有管理器），取出生成器 `+8` 的值（`main + 0xA3710`）并交给管理器的 `main + 0x99C3C`，随后将传输对象记入 `[facade + 0x48]`，将状态 8 记入 `[facade + 0x40]`。管理器将缓冲区交给下述任务的接收部分；任务的发布部分通过管理器的 blob 生成器到达 `nn::ldn::SetAdvertiseData`。

组件在 `[component + 0x3528]` 保存的对象是 `nn::pia::session::Session`，其方法位于 `main + 0xAF4E0` 至 `0xB23xx`（主虚函数表 `main + 0x1CE300`，另一个位于 `main + 0x1CE330`；构造函数 `main + 0xAF4E0` 初始化从 `+0x10` 开始的字段，并将 `+0xD8` 视为 u32）。其方法分别设置 `+0x30`（`main + 0xAF760`）、`+0x70`（由 `main + 0xAF9F0` 设置；运行时持有 `UpdateSessionPropertyJob` 单例，设置函数维护其 `+0x10` 的 u16）及 `+0xD0`（`main + 0xAFA94`），并在 `main + 0xAFB44` 清除它们。交付调用方读取的 `+0x150`、`+0x528`、`+0x70`、`+0x30`、`+0xD0` 和 `+0xD8` 都是 Session 字段。组件在 `main + 0x528F8` 从内嵌于 `+0x34A0` 的对象首字，或从重定位槽位 `main + 0x1D1AB0` 的全局对象（指向映像外的 `0x41FB1C8`）选择会话，再用 `main + 0xB14E0` 打开，在 `+0x88` 存入回调 `main + 0x52BB4`，在 `+0x90` 存入组件。Session 构造函数在映像中没有调用方，虚函数表指针槽位也仅由该构造函数与析构函数加载，因此实例来自此模块之外。运行时结构（模拟器中的法语版火红、神秘礼物会话，同一个 `main` 二进制）是一组 bss 单例：`Session` 位于 `main + 0x1029950`，`SessionProtocol` 位于 `main + 0x1032000`，所有者位于 `main + 0x9E1798`，`LocalFacade` 位于 `main + 0x9E15B8`，三个会话任务单例位于 `main + 0x103FBB0`、`+0x103FCE8` 和 `+0x1040180`（`LeaveMeshWithHostMigrationJob`、`ProcessHostMigrationJob`、`KickoutManageJob`）。会话运行时，`[component + 0x3528]` 正是该 `Session`，其中组件 = `[session + 0x90]`，即系统调用调度器接收的对象；其 `+0x6050D8` 的 RFU 副本保存最新记录，包括活动 `0x15` 和用户名字节。`[session + 8]`（所有者，也是各协议的 `[protocol + 8]` 及 `[reader + 0x60]`）没有虚函数表：`+0xB8` 持有门面，`+0xC8` 持有协议管理器。`[session + 0x30]` = `LocalFacade`，已由类型信息确认。会话任务的 `+0x80` = `[SessionProtocol + 0x130]`，即 `Session`；其 `+0x88` 为 SessionProtocol（构造函数 `main + 0xCB0D0`：`stp x9, x19,
[x20, #0x80]`，`x9 = [x19 + 0x130]`）。

广播机制属于另一个对象：`nn::pia::local::LdnBackgroundProcessJob`（类虚函数表 `main + 0x1CAC48`，大小 `0xA60` 字节，工厂 `main + 0x7EED8` = 管理器虚函数表槽位 `+0x278`，构造函数 `main + 0x83A88`）。它派生自 `nn::pia::net::NetBackgroundProcessJob`（虚函数表 `main + 0x1CB928`），在 `+0xD8` 内嵌 `nn::pia::common::StepSequenceJob::Step`（虚函数表 `main + 0x1C9770`），在 `+0x320` 内嵌 `nn::pia::local::LocalConnectNetworkSetting`（虚函数表 `main + 0x1CA2D0`）。基类构造函数 `main + 0x875BC` 将网络管理器存入 `+0xA8` 并构造子对象；自身构造函数在 `+0x8C0` 构造广播数据生成器（`main + 0x87514`）。任务的方法 `main + 0x84260`（虚函数表槽位 `+0x60`）是接收部分：锁定管理器（`+0x2B8`），访问持有对象（`main + 0x87374`，作用于 `[manager + 0x200] + 0xA8` 和 `[manager + 0x2D8]`），通过 `main + 0x8885C` 验证传入缓冲区（缓冲区大小 `main + 0xA2C90` 不超出管理器槽位 `+0x100` 的限制，缓冲区 `+0x8` 的位 1 已设置，`[manager + 0x12D8]` 为零，通过 `w2 = 8` 的 `main + 0x879C0` 检查，并检查 `[job + 0xA0]` 的时间戳），将缓冲区 `0x180` 字节的广播区域（`+0x1C`）复制到任务 `+0x8C0` 的生成器（`main + 0x87578`），再将下一步设置为槽位 `0x130`。此方法经任务虚函数表到达：管理器的 `main + 0x99C3C` 将缓冲区交给它保存在 `+0x250` 的对象（派生自 `StepSequenceJob::Step` 的委托，构造函数 `main + 0xA2824`，大小 `0x98` 字节，`+0x88` 有 `0x38` 字节的辅助对象，`+0x90` 是管理器），其 `main + 0xA28E4` 以 `(job, helper, buffer)` 调用任务槽位 `+0x60`。发布部分是任务的 `+0x130`（`main + 0x84360`），它在 `main + 0x8445C` 将任务生成器 `+0x8C0` 传给管理器槽位 `+0xD0`。Pia 自身会话任务步骤中的八处调用（`main + 0xCB0CC`-`0xCC738`；`nn::pia::session::LeaveMeshWithHostMigrationJob`，虚函数表 `main + 0x1CEB70`；`nn::pia::session::ProcessHostMigrationJob`，`main + 0x1CEBA0`；`nn::pia::session::KickoutManageJob`；以及构造槽位 `main + 0x1D26F8`-`0x1D2728` 对应的类），分别按任务 `+0x90` 的状态字节检查条件，读取 `+0x80` 的持有对象（即 `[SessionProtocol + 0x130]`，Session，已实时验证），调用 `[holder + 0x30]` 的虚函数表槽位 `+0x130`。`[holder + 0x30]` 是 `LocalFacade`（实时类型信息），其 `+0x130` 项为 `main + 0x8E0B4`。

调用链受封装层网络状态约束，属于网络领导者一侧的路径。`swi 0x47` 函数体仅在会话非空、`component + 0x690` 字节已设置、`component + 0x2770` 至少为 10、会话条件 `main + 0xB06BC` 返回假时交付（`main + 0x5879C`-`0x587DC`）。`+0x690` 是侦听器列表的启用标志：仅当 `[component + 0x6A0] == [component + 0x6A4]`（封装层的扫描与加入状态对）时，才在 `main + 0x53A58` 设置；标记属性调度器的遍历（`main + 0x4EBB0`，模式 `-2`）及向两字段写入 `-1` 的清理操作会将它清除。交付自身的检查会比较管理器中的两个 Pia 地址结构：`X` 的槽位 `+0xD8` 尾调用 `main + 0x95C90`，要求 `[manager + 0x1268]` 和 `[manager + 0x1288]` 均通过 `main + 0x74BE0`（有效地址），且经 `main + 0x74C18` 比较相等（先比较 `+0x18` 的 u16，再比较 `+8` 的 0x10 字节）；槽位 `+0xE8` 要求 `[manager + 0x12D8]` 为零。这两个结构分别保存封装层的本地地址（模拟器上为 `127.0.0.1`）及对端地址（主机 IP），因此调用链只在游戏机作为所在网络领导者时运行。加入网络的游戏机只在副本中保存记录；游戏数据仍通过会话到达父节点。

在模拟器的同一帧中已实时确认全部八个环节，使用的 `swi 0x47` 携带版本 5、语言 2、训练家 ID `0x1234`、活动 `0x45` 和用户名 `PKLDNTST`：处理程序副本接收 24 字节；将条件字节和地址对改为满足要求后，会话的 `main + 0xB1304` 运行，门面的 `main + 0x8D4AC` 接收栈上的生成器（应用数据携带 30 字符记录文本 ``Z8J4;Vk.+>`.uN;#####<P?>######``）；管理器的 `main + 0x99C3C` 及其 `+0x250` 委托的 `main + 0xA28E4` 继续传递；任务的 `+0x60` 验证并将 `0x180` 字节区域复制到任务 `+0x8C0` 的生成器（`main + 0x87578`）；任务的 `+0x130` 从状态机运行；管理器的 blob 生成器 `main + 0x80C3C` 接收含有相同记录文本的任务生成器。任务本身是状态机：`+0x38`/`+0x40` 保存当前步骤（带一位虚函数标志的虚函数表槽位，或直接函数），基类方法 `main + 0x6EAA0`（“ExecuteCore”，任务槽位 `+0x20`）进行分派。已观察到的步骤有虚函数表槽位 `0xB8`、`0xC8`、`0xD8`、`0xE8`、`0xF8`、`0x108`、`0x118`、`0x138`、`0x148`，以及 `main + 0x891F0` 等直接函数。

管理器类（`nn::pia::local::LdnProtocol`，虚函数表 `main + 0x1CA5B0`，指针在 `main + 0x7E244` 从重定位槽位 `main + 0x1D1E98` 生成）将自身的 `NetworkInfo` 保存在 `[manager + 0x2D8] + 0xB8`：广播大小位于 `NetworkInfo + 0x26A`（`+0x322`），blob 位于 `NetworkInfo + 0x26C`（`+0x324`），`NetworkInfo + 0x282` 位于 `+0x33A`。其方法 `main + 0x80C3C` 是生成器应用数据的唯一使用方（`main + 0xA2C70` 仅由它调用）：清零 `+0x380`（`NetworkInfo + 0x2C8`），将应用数据复制到此处，在 `+0x322` 写入应用数据大小加 `0x5C`，用持有对象自身的方法（虚函数表槽位 `+0x68`）在 `+0x324` 写入 `0x5C` 字节的 Pia 系统头，再调用 `nn::ldn::SetAdvertiseData(holder + 0x324, size)`（PLT `main + 0x160A90`，GOT `0x1d3800`）。另有两个管理器方法广播第二个对象的数据（`main + 0x7F990`、`0x81140`：`[object +
0x18]`，大小来自其虚函数表槽位 `+0x38` 加 `main + 0x8AC20`），`main + 0x80EBC` 则在广播前从 `[manager + 0x128]` 重建持有对象。

`component + 0x2770`（通过 `[component + 0xD0]`）由 `swi 0x53`（布尔值）和
`main + 0x0511CC` 和 `main + 0x0511F4`，没有系统调用到达。 `main + 0x0511F4` 将其与 10 进行比较，并且在达到或超过该值时，自动加载 `component + 0x2790` 处的标志；设置标志进入
`main + 0x057250` 的延续，测试第三个参数是否为 null。其呼叫者身份不明。

`bkpt #0x52` 组件还拥有调度程序（其 vtable 的插槽 21）和 2324 个种类名称，每个种类有六种语言，使用 djb2 进行哈希处理（`main + 0x056540`，字符串位于 `main + 0x1C4470`）。由每个处理程序共享的调度程序的帧是保存的寄存器的 `0x40` 字节加上 `0x310`。

来自 ψ 的 `bkpt #0xFF` 关闭游戏：包装器归档会话的播放报告，完成 LDN，停止音频，归档从保存构建的报告，提交保存并退出。主机没有应答。 Ryujinx 的 `prepo` 打印的报告：

|房间|领域 |
| --- | --- |
| `network`，每个链接会话一个 | `Flavor` 66、`Trainer`（32位训练家ID）、`Zone`（链接活动，21 `ACTIVITY_WONDER_CARD`代表神秘礼物）、`Duration`、`Players`、 `Slot`、`Rtt` |
| `game`，在出口处| `Flavor`、`TimeStamp`、`Trainer`、`Gender`、`Duration`、`Badges`（位掩码）、`TotalBadges`、`HallOfFame`、 `TotalHallOfFame`、`CompleteRegionalPokedex`、`RegionalPokedexCnt`、`RegionalPokedexCap`、`CompleteNationalPokedex`、`NationalPokedexCnt`、`NationalPokedexCap`、`Distributed`、 `LinkExchange`、`LinkBattle`、`MonsNo1..5` 和 `MonsNoNLevel`、`Money`、`CommsError` |
<a id="what-the-play-reports-are-built-from"></a>
### 比赛报告的依据是什么

游戏报告从闪存映像解析。`main + 0x05A280` 根据扇区尾部（签名 `0x08012025`）找到最新存档槽，将其 14 个扇区（0xE000 字节）复制到 `component + 0x140 + 0x70`；`main + 0x05A370` 按各游戏的描述表遍历，包括徽章标志位、名人堂和图鉴标志，以及用存档密钥异或的钱数。每个偏移量和位索引均来自静态表；复制的存档只提供一个计数，即一个字节的 `playerPartyCount`，用于限制 `main + 0x05AAE0` 的同行宝可梦遍历。即使按 255 个、每个 0x64 字节计算，也仍位于 0xE000 字节副本内。`swi 0x57` 填入 `MonsSelect`（初始伙伴，通过 `main + 0x17DA8C` 的内部编号到全国图鉴编号表）；输出的 JSON 只包含表中固定子集，不含 `MonsSelect`。`swi 0x62` 递增 `component + 0xE1B0`，成为 `CommsError`：每次调用都会使 Ryujinx 的 `ServicePrepo ProcessPlayReport` 在主机日志输出的下一份报告中，`CommsError` 增加 1。`swi 0x55` 将 SaveBlock2 指针保存到 `component + 0xE1BC`，其唯一读取方是 `main + 0x0577D8`，检查 `optionsButtonMode == 2`（L=A）。存储位置就是处理程序自身 `main + 0x057308`：调度器在 `main + 0x057058` 设置 `x8 = component + 0xE1B0`，处理程序把客户机原始 `r0` 存入 `[x8 + 0xC]`。读取方通过区域表折叠所存的字，检查边界后读取折叠区域内 `+0x13` 的一个字节：两者都使用客户机相对地址，并有边界检查。

`main + 0x059CE4` 从游戏代码中挑选桌子；该应用程序包含所有五个：

|游戏代码|表| `Flavor` 底座 |
| --- | --- | --- |
| `AXV?` |红宝石 | 0x10 |
| `AXP?` |蓝宝石| 0x20 |
| `BPE?` |祖母绿| 0x30 |
| `BPR?` | 火红 | 0x40 |
| `BPG?` | 叶绿| 0x50 |

`Flavor` 在 `JEFIDS` 中添加该语言的索引，因此法语火红报告 `0x42` (66)。

该表按id顺序寻址14个扇区，0x1000每个：字节偏移`o`是SaveBlock1偏移
`((o >> 12) - 1) * 0xF80 + (o & 0xFFF)`。标志是 `(bit, byte)` 对；略高于 7 表示不存在。针对三个分解进行解码：

|领域 |红宝石/蓝宝石 |祖母绿| 火红 / 叶绿 |
| --- | --- | --- | --- |
|徽章、 8 面旗帜 |字节 `0x23A0` 位 7，`FLAG_BADGE01_GET` 0x807 | `0x23FC` 位 7，0x867 | `0x2064` 位 0，0x820 |
| `HallOfFame` | `0x23A0` 位 4，`FLAG_SYS_GAME_CLEAR` 0x804 | `0x23FC` 位 4，0x864 | `0x2065` 位 4，0x82C |
| `Money` | `0x1490`（SaveBlock1 + 0x490），无密钥 | `0x1490`，异或 `0x00AC`（保存块2 `encryptionKey`）| `0x1290` (+0x290)，异或 `0x0F20` |
| 臂数、臂数 | `0x1234`，`0x1238` | `0x1234`，`0x1238` | `0x1034`，`0x1038` |
| `TotalHallOfFame` | `0x25E8`，`GAME_STAT_ENTERED_HOF` | `0x2644` | `0x22A8` |
| `LinkExchange` | `0x2614`，`GAME_STAT_POKEMON_TRADES` | `0x2670` | `0x22D4` |
| `LinkBattle`，| 的总和`0x261C..0x2624`，链接胜、负、平| `0x2678..0x2680` | `0x22DC..0x22E4` |
| 地区图鉴大小 | 202 | 202 | 151 |

游戏统计数据与游戏中的金钱键进行异或运算。

`Distributed` 是四位，每一位都是开启前往仅售票岛屿的渡轮的标志：

|比特|旗帜|红宝石/蓝宝石 |祖母绿| 火红 / 叶绿 |
| --- | --- | --- | --- | --- |
| 0 |肚脐岩（神秘门票）|缺席| `0x240C` 位 0，`FLAG_ENABLE_SHIP_NAVEL_ROCK` 0x8E0 | `0x2069` 位 2，0x84A |
| 1 |诞生岛（极光门票）|缺席|缺席| `0x2069` 位 3，0x84B |
| 2 |南岛（Eon 门票）| `0x23AA` 位 3，`FLAG_SYS_HAS_EON_TICKET` 0x853 | `0x2406` 位 3，`FLAG_ENABLE_SHIP_SOUTHERN_ISLAND` 0x8B3 |缺席|
| 3 |遥远的岛屿（旧海地图）|缺席| `0x240A` 位 6，`FLAG_ENABLE_SHIP_FARAWAY_ISLAND` 0x8D6 |缺席|

在火红和叶绿中，两个标志均由门票的神秘事件脚本 [mystery_event_msg.s:222,281] 和 Switch 版本的名人堂授予设置
[post_battle_event_funcs.c:58];名人堂保存的保存已进入报告 0。
<a id="the-bad-word-filter"></a>
### 坏词过滤器

`swi 0x4D`，处理程序`main + 0x0571FC`，将`r0`解析为GBA地址，后面需要256个字节，将ASCII字符串转换为UTF-16并运行平台的亵渎检查，重写该字符串。 `r1` 非零选择游戏从不使用的第二种模式（`r1` = 1 以相同方式屏蔽）。游戏通过 `svc_BadWordCheck` 调用它，将名称转换为 ASCII 并返回 [sloopsvc.c:211]。仅当命名屏幕回答 0 [naming_screen.c:686] 时，才会保存键入的名称。

| 发送的字符串 | `r0` | 处理后的字符串 |
| --- | --- | --- |
| `hello world` | 0 | `hello world` |
| `hello fuck` | 1 | `hello ` 然后四个 `0xA1` 字节 |
| `POKELDN` | 0 |不变|
| `ASSASSIN` | 0 |不变|
| `NINTENDO` | 0 |不变|

路径 [main + 0x0571FC -> main + 0x057458]：处理程序折叠 `r0`，需要折叠后面的 `0x100` 字节，并将字符串复制到帧 `-0x100` 处的 `0x100` 字节堆栈缓冲区中（复制在`main + 0x85645F0` 受其 `w1 = 0x100` 参数限制）。到 UTF-16 的转换从该缓冲区运行到 `sp + 0x10` 处的 `0x200` 字节缓冲区（[main + 0x855F100]，`w2 =
0x200`），亵渎检查通过全局指针 [main + 0x574AC，被调用者`main +
0x86664C0`]，并且屏蔽字符串被复制回来宾折叠。两个缓冲区都在调度程序自己的 `0x310` 字节帧（`sp + 0x210` 和 `sp + 0x310`）内结束；副本既不会到达已保存的寄存器，也不会越过帧。替换字节是常量 `0xA1`。
<a id="the-wrappers-own-scan-pipeline"></a>
### 包装器自己的扫描管道

包装器扫描网络`nn::ldn::Scan`通过自己的 PLT (`main + 0x160B70`;
`ScanPrivate`在`main + 0x160B60`), 来自管理器对象`x23`在呼叫站点`main + 0x80944`/`0x8095C`和`w2 = 0x18`网络，进入内联数组`manager + 0x14C0`, 24 个条目 x`0x480`（初始化时填零一次，`main + 0x7E290`）。模拟器自带的ldn服务投线`ScanResponse`身体进入`NetworkInfo`没有长度检查，因此另一个席位的字段值逐字到达包装器。

使用循环 (`main + 0x80A20..0x80B9C`) 遍历数组：它将 `0x480` 字节记录清零
`sp + 0x128`（`main + 0x874A0`），将条目转换为它（`main + 0x87374`：整个`0x480`的一个memcpy到`record + 0xB8`，然后位精确字段读取：源`+0xA`， `+0x11`（15字节整数解析，`main + 0xA9830`，十六进制/八进制/十进制/二进制，带有`b`/`x`前缀，每次提前进行边界检查），`+0x26A`（广告数据大小）， `+0x281`/`+0x282`,
`+0x11A..0x11F`；存储记录 `+0x90`、`+0xA0`、`+0xA2`、`+0xA4`、`+0xA6`、`+0xB0`），然后将记录通过过滤器虚拟和接受虚拟（`main + 0x80A88..0x80A94`）。

接受的网络进入父节点候选列表： 16 个槽位 x `0x1A` 字节
`owner + 0x6050F2`，`owner + 0x605294`处的写入索引上限为15（`cmp w8, #0xf; b.le` [main + 0x58C3C]）；数组以 `+0x605292` 结束，紧靠索引。填充是所有者类的（vtable `main + 0x1C3B30`）插槽`+0xA0`，`main + 0x58BF8`，由`main + 0x536A4`根据扫描结果站调用；站名长度来自于站自己的虚拟[槽位`+0x50`]，`sub w8, w0, #1; cmp w8, #0x3f; b.hi`[主+0x5364C]下降
`x6 > 0x40` 之前调用。在填充内部，`sp + 7` 处的 `0x41` 字节堆栈缓冲区接收
`memcpy(sp + 7, x5, x6)`，当 `x6 > 0x40` [main +
0x58C68]：对于 `x6 > 0x40`，副本到达帧的已保存 `x29`/`x30`（缓冲区偏移量）
`0x59`/`0x61`）。第一个调用者解码了钳位，因此通过它的长度最多为
`0x40`；在加载班级插槽 `+0xA0` 的图像的 8 个站点中，`main + 0x536A4` 是已确认在该班级上发送的站点。

在模拟游戏机上测得，一个主机广告：计数1，槽位0=主机的广告字节：16字节游戏数据（活动`0x15`），8字节显示名称，父节点id u16（`0x59f1`）。

在 `main` 中，列表仅由填充函数族（`main + 0x58BB4`、`0x58BE4`、`0x58BF8`）写入，均为虚函数；映像中其他基于组件的访问均为读取。所有者类的虚函数表指针 `main + 0x1C3B30` 在 `main` 中通过加载重定位槽位 `main + 0x1D1B38`（值 `main + 0x1C3B20`）再加 `0x10` 得到：`main + 0x58558` 在清零 `component + 0x6050F0` 的候选列表时存入该指针；两个组件初始化函数中的 `main + 0x58FD8`/`0x59054` 也会存入。同样的方式还用于生成管理器类指针（槽位 `main + 0x1D1E98`；`main + 0x7E244`、`0x7E4D0`）及会话类指针（槽位 `main + 0x1D2770`；`main + 0xB7D24`、`0xB7E78`）。

<a id="the-pia-session-message-dispatcher"></a>
### Pia 会话消息调度器

封装层原生 Pia 会话接收代码在 `main + 0xB9FC0` 按类型分支。它遍历节点链：`[node + 0x10]` 是消息体，首字节为类型；节点自身的前三个字节是用作队列键值的协议地址。当管理器对象的 `[x0 + 0xA0]` 非零且类型不大于 `0x11` 时分派节点。分支指令为 `adr x8, main + 0xB9FD0`（`main + 0xB9FCC`）、`ldrb w9, [main + 0x180FC9 + type]`（`main +
0xB9FC4`；在 `main + 0xB9EFC` 执行 `adr x27, main + 0x180FC9`）、`add x8, x8, w9, lsl #2`、`br x8`。`main + 0x180FC9` 的字节表每种类型有一项；十八个分支块位于 `main + 0xB9FD0 + index * 4`，分别调用处理程序（`main + 0xBCB60`、`main + 0xBE438`、`main + 0xBE8BC` 等），并以无条件 `b main + 0xB9F80` 结束。

各处理程序读取前都会检查消息边界：类型 1 的处理程序 `main + 0xBE438` 开头为 `cmp w2, #0x15; b.ne`，只有 `0x15` 字节的消息能到达复制操作。此次审计解码的类型检查包括：类型 2 为 `>= 4`，类型 3 为 `== 0x16 or 0x22`，类型 4 为 `== 0xf`，类型 6 为 `>= 0xf`，类型 9 为 `== 0x1e or 0x2a`，类型 10 和 12 为 `== 0x15`，类型 11 为 `>= 0xe`，类型 13 为 `== 0xa`，类型 14 为 `>= 0x4d`，类型 17 为 `>= 0xd`。变长读取函数 `main + 0xC0D90` 从位数计算字节数，与声明长度比较，长度不足时拒绝。在这一组处理程序中，未发现将消息控制的长度复制进固定缓冲区的情况。

这些类型是 Pia 会话协议自身的消息类型；主机的会话层（`pokeldn/ldn/pia_connect.py`）编号为：0 加入请求、1 加入确认、2 加入响应、3 离开请求、4 离开响应、5 更新、6 更新确认、7 开始主机迁移、8 迁移确认。类型 1 的处理程序 `main + 0xBE438` 将 21 字节消息读取为：`[0]` 类型，`[1:9]` 和 `[9:0xB]` 为来源站点的固定 ID、可变 ID，`[0xB:0x13]` 和 `[0x13:0x15]` 为目标站点的对应 ID。目标 ID 对必须与传输对象自身的值（[transport + 0x1B8]、`+0x1C0`）匹配，否则拒绝；随后查找来源站点并对它调用 `main + 0xC9B4C`。类型 2 的处理程序 `main + 0xBE8BC` 接受至少 4 字节的消息，检查管理器状态字节（`+0x30 == 0xFD`），再按消息字节 3 在 3 至 0x10 范围内分支。

接收路径的所有者是会话类（`nn::pia::session::SessionProtocol`；虚函数表基址 `main + 0x1CE8E0`；指针在 `main + 0xB7D24`/`0xB7E78` 从重定位槽位 `main + 0x1D2770` 生成，构造函数是 `main + 0xB7E70`）。驱动函数是该类的虚函数表槽位 `+0x50`，即 `main + 0xB9CA0`，调用遍历函数 `main + 0xB9DB0`；链挂在 `[protocol + 0xF8]` 对象（由协议管理器附加的会话数据包读取器）的 `+0x70` 表上（`main + 0xD6D68` 返回该地址）。消息对象由 `main + 0xD4430` 构造，其虚函数表指针来自重定位槽位 `main + 0x1D27B0`。Pia 库自身静态链接于 `main` 中，映像含有 `SDK MW+Nintendo+PiaCommon-6_42_1-Release` 及会话任务名称。

<a id="the-pia-librarys-own-wire-parsing"></a>
### Pia 库自身的线缆数据解析

`main` 链接完整的 Pia 6.42.1 协议栈，映像含有 `PiaCommon`、`PiaLocal`、`PiaNet`、`PiaSession`、`PiaTransport` 和 `Pia_ZStandard` 的 `SDK MW+Nintendo+...` 发布字符串及修饰后的类名。前文仅按虚函数表描述的类如下：

| 前文称呼 | 类（虚函数表类型信息中的修饰名称） | 虚函数表 |
| --- | --- | --- |
| 网络管理器 | `nn::pia::local::LdnProtocol` | `main + 0x1CA5B0` |
| 会话对象（生成器位于 `+0x8C0`） | `nn::pia::local::LdnBackgroundProcessJob` | `main + 0x1CAC48` |
| 会话类（接收路径） | `nn::pia::session::SessionProtocol` | `main + 0x1CE8E0` |
| 数据包对象 | `nn::pia::common::Packet::Header` | `main + 0x1CA100` |
| 本地接收流 | `nn::pia::local::LocalInputStream` | `main + 0x1CA540` |
| 网络接收流 | `nn::pia::net::NetInputStream` | `main + 0x1CC1D0` |

传输类的虚函数表分别为：`PacketReader` `main + 0x1CF1A8`（另一个位于 `main + 0x1CE7E8`），`PacketWriter` `main + 0x1CF258`，`ProtocolManager` `main + 0x1CF3A0`，`ProtocolMessageReader` `main + 0x1CF458`，`ProtocolMessageWriter` `main + 0x1CF490`，`ReliableProtocol` `main + 0x1CF4C8`，`Station` `main + 0x1CF8C8`，`StationManager` `main + 0x1CF938`，`ReceiveThreadStream` `main + 0x1CFB20`，`SendThreadStream` `main + 0x1CFB68`。会话类分别为：`Session` `main + 0x1CE300`，`SessionPacketReader` `main + 0x1CE748`，`SessionPacketWriter` `main + 0x1CE7F8`，`SessionStation` `main + 0x1CED20`。本地类分别为：`LocalProtocol` `main + 0x1CA9B0`，`LocalService` `main + 0x1CB460`，`LocalFacade` `main + 0x1CB548`。

**数据包。** 数据包对象大小为 `0x1D18` 字节：解析后的头部位于 `+8` 至 `+0x24`；数据报缓冲区位于 `+0x30`（容量 `0x1C5C`，即追加辅助函数 `main + 0x75664` 和 `main + 0x75694` 的边界，后者还在 `+0x14` 记录尾部大小）；已接收大小位于 `+0x1C90`（本地接收路径在 `main + 0x7DE40` 写入，接收上限 `0x5AC` 字节并检查该限制）。解析函数（`main + 0x752D4`，虚函数表槽位 `+0x18`；入口 `main + 0x752C8` 传入对象自身缓冲区及常量 `0x1C5C`）要求数据多于 `0x1C` 字节，并读取 `0x1D` 字节头部：

| 位置 | 大小 | 含义 | 写入位置 |
| --- | --- | --- | --- |
| 0x00 | 4 | 魔数 `0x32AB9864`，大端序 | `+0x08` |
| 0x04 | 1 | 位 0-6 为版本，加密标志为 `0x80` | `+0x0C` |
| 0x05 | 1 | 一个字节，按发送值保留 | `+0x0D` |
| 0x06 | 2 | 目标可变 ID，大端序 | `+0x0E` |
| 0x08 | 2 | 来源可变 ID，大端序 | `+0x10` |
| 0x0A | 2 | 数据包 ID，大端序 | `+0x12` |
| 0x0C | 1 | 尾部大小 | `+0x14` |
| 0x0D | 8 | nonce，按发送值保留 | `+0x15` |
| 0x15 | 8 | GCM 标签，按发送值保留 | `+0x1D` |

此应用使用的版本为 `0x10`（16）。有效性检查 `main + 0x75610` 要求魔数匹配、`([+0xC] & 0x7F) == 0x10`，并满足 `size - 0x1D < 0x1C40`。载荷指针为 `+0x4D`（缓冲区跳过头部，`main + 0x75474`）；`main + 0x75458` 返回 `buffer + t`，其中 `t = (n + 0x1D)` 使用 32 位算术，`(t >> 2) > 0x716` 时返回空。该容量检查允许 `t` 最大为 `0x1C5B`；消息遍历器另行检查接收大小减去头部和尾部后的范围（`main + 0xDE278`）。

**套接字与接收流。** 套接字由一个小对象持有（构造函数 `main + 0x6D93C`：`+0` 为值为 `-1` 的 fd，`+4` 为计数，`+8` 为地址族，`+0xC` 为协议）。`main + 0x6D95C` 打开它（`nn::socket::Socket`，PLT `main + 0x160940`），`main + 0x6DBF4` 关闭它（`main + 0x160950`），`main + 0x6DCD0` 绑定它（`main + 0x160960`），`main + 0x6DE6C`、`0x6DF44`、`0x6E00C`、`0x6E0F0` 设置选项（`main + 0x160970`）。数据报调用为 `main + 0x6E1D0`（`nn::socket::RecvFrom`，PLT `main + 0x160980`，标志 `0x80`，来源地址由 `main + 0x6E9D0` 转换）及 `main + 0x6E538`（`nn::socket::SendTo`，`main + 0x160990`）。本地接收流（可变 ID 位于 `+0x88`，锁位于 `+0x68`，套接字持有对象指针位于 `+0x18`）运行驱动函数 `main + 0x7DD10`（虚函数表槽位 `+0x10`）：将数据接收进数据包缓冲区并解析头部（`main + 0x7DDEC`；`main + 0x6E1C8` 为跳板）。数据包过滤器 `main + 0x91280`（槽位 `+0x20`）首先要求数据包有效。版本至少为 7、尾部非空且目标可变 ID 不大于 1 时，尾部必须至少有两个字节，接收流自身 ID（`+0x88`）必须非零，并出现在尾部的大端序 u16 接收者 ID 中（`footer_size >> 1` 个条目）。另有检查：当 `([+0xC] & 0x7E) >= 6` 且目标至少为 2 时，目标必须等于接收流自身的 `+0x88`。

过滤器在 `main + 0x912EC` 的 `sub w8, w8, w9` 后，将接收者指针计算为 `packet + (size - footer) + 0x30`；消息遍历器 `main + 0xD6460` 和解析器 `main + 0xDE278` 将遍历上界计算为 `size - footer - 0x1d`（`main + 0xD651C`、`main + 0xDE298`）。这两次减法都不检查尾部大小是否在数据报范围内。尾部大小字节位于数据报偏移 12 的明文头部，对端可任意设置。尾部大小超过数据报大小不会令过滤器报错：六个 31 字节、尾部为 `0x40` 的数据报到达了套接字，会话仍继续运行（在模拟器中测得）。

**线程。** 传输层的接收和发送循环是 `nn::os` 线程，名称分别为“Pia ReceiveThreadStream”（在 `main + 0xE9020` 启动，名称由 `main + 0xE9034` 的 `adr` 提供）及“Pia SendThreadStream”（`main + 0xEA758`），通过 `main + 0xF6010` 创建（`nn::os::CreateThread`，PLT `main + 0x15FDF0`；以及 `StartThread`，`main + 0x15FE00`）。

**从线缆到会话处理程序。** 接收到的会话消息由会话数据包读取器解析，保存在按地址索引的表中；会话协议每次更新都会遍历该表。

`nn::pia::session::SessionPacketReader`（虚函数表 `main + 0x1CE748`）继承 `nn::pia::transport::PacketReader`（虚函数表 `main + 0x1CF1A8`）。读取器的 `+0x30` 方法（`main + 0xD5DE0`）处理接收到的数据包，调用 `main + 0xD6460(reader, packet)` 遍历消息。遍历器从数据报偏移 `0x1D` 开始，在 `packet_size - footer_size` 之前停止（`main + 0xDE278`、`0xD6510`-`0xD6538`）；尾部紧跟载荷。它用 `main + 0x74EA8` 解析各消息，通过读取器的 `+0x78` 虚函数取出用作队列键值的协议地址（`main + 0xD6D0C`：消息 `+0x2C` 的 u16，以 `+0x2E` 的字节作为高位），并调用 `main + 0xD6944(table, address, message)`。

表内嵌于 `reader + 0x70`：`+0` 是 u32 桶数，`+8` 是桶数组指针（每桶 0x18 字节，`+0` 为链首，`+8` 为链尾），`+0x40` 是可选散列回调。`main + 0xD6944` 先加载数组指针，再加 `index * 0x18`；桶并不内嵌于表中。桶索引为 `callback(address) % count`，未设置回调时为 `(address[0] + address[1] + address[2]) % count`。`main + 0xD71F0(bucket, address, message)` 取出一个节点，将消息复制进去（`+0` 为三个地址字节，`+0x10` 为消息体指针，`+0x18` 为 ID，其他字段位于 `+0x20` 至 `+0x30`，其余由 `main + 0x74C54` 复制），再追加到桶的双向链表（后继在 `+0x78`，前驱在 `+0x80`）。

协议侧：`nn::pia::session::SessionProtocol` 的 `+0x50` 虚函数（`main + 0xB9CA0`）每次更新运行 `main + 0xB9DB0`。它读取 `[protocol + 0xF8]`（按下文方式附加的读取器），取得读取器 `+0x70` 的表，根据协议自身三字节地址计算桶（`+0x120` 的 u16 和 `+0x122` 的字节，由 `+0x18` 虚函数 `main + 0x828E4` 读取；该字段对属于 `nn::pia::transport::Protocol`，由 `main + 0xDA614` 设置），遍历链表，并按 `[node + 0x10]` 消息体的首字节，经跳转表分派给处理程序（`main + 0xBCB60`、`main + 0xBE438`、`main + 0xBE8BC`、`main + 0xBF2D4` 等），传入 `(protocol, node, id)`。

附加过程：协议管理器（内嵌于所有者的 `+0xC8`，协议表位于自身 `+0x18`）遍历表，将所有者的 `+0xF8` 和 `+0x100` 设置到每个协议的 `+0xF0` 和 `+0xF8`（设置函数 `main + 0xDA8C8` 和 `main + 0xDA8D0`，广播函数 `main + 0xDB740` 在 `main + 0xEC0E4` 接收该字段对；任意参数为零时拒绝）。`+0xF8` 的对象即读取器，因此遍历器使用的是读取器 `+0x70` 的表。

运行时，管理器位于 `[session + 8] + 0xC8`（前述所有者），其表位于 `[manager + 0x18]`，`+0` 为 u32 桶数，`+8` 为桶数组指针。每个桶大小 `0x18` 字节，`+0` 是节点，节点的 `+8` 是协议，`+0x30` 指向下一个节点。模拟器会话中的桶数为 `19`，恰有六个协议，每种一个，以协议地址为键值（u16；`+0x122` 字节为零，每个协议的 `+0x108` 保存网络的 Pia 可变 ID，`0x8fa2`/`0x0766`）：`0xfd01` `nn::pia::local::LdnProtocol`，`0xfd03` `nn::pia::transport::RttProtocol`，`0xfd05` `nn::pia::transport::UnreliableProtocol`，`0xfd0a` `nn::pia::transport::ReliableProtocol`，`0xfd0d` `nn::pia::session::SessionProtocol`，`0xfd0f` `nn::pia::transport::MonitoringDataProtocol`。协议按种类实例化，而非按站点：对 `SessionProtocol` 驱动函数的八次追踪都命中同一个实例，读取器表中的节点也按协议地址归档（`0xfd0a`，消息 ID `0x60`）。`main + 0xB1F60` 创建并注册实例（通过 `main + 0xDB114` 分配 `0xD8E8` 字节，调用构造函数 `main + 0xB7D0C`，以地址对为键插入管理器映射）；Session 构造函数调用它一次，将返回地址保存在 `+0x12`/`+0x14`。

`nn::pia::transport::Protocol` 基类（虚函数表 `main + 0x1CF308`，构造函数 `main + 0xDA548`，虚函数表指针来自重定位槽位 `main + 0x1D2808`）在 `+0x120`/`+0x122` 保存三字节地址，`+0xC8` 保存锁，`+0xF0`/`+0xF8` 保存附加的字段对，`+0x100`/`+0x108` 和 `+0x110`/`+0x118` 保存两个已配置的“8 字节值加 u16”组合，`+0x123` 保存状态字节，`+0xD8` 保存标志。

<a id="repointing-the-consoles-outgoing-message"></a>
## 重新指向游戏机的传出消息

`r0` 是 `&client->param`，因此 `struct MysteryGiftClient` [include/mystery_gift_client.h:71] 位于与其固定的偏移处：

|领域 |来自 `r0` |
| --- | --- |
| `client->sendBuffer` | 0x10 |
| `client->link.sendSize` | 0x34 |
| `client->link.sendBuffer` | 0x3C |

`MysteryGiftLink_InitSend` 存储给它的指针 [mystery_gift_link.c:59]； CRC 是在通过 `link->sendBuffer` 发送 `link->sendSize` 字节 [:166] 时获取的。在 InitSend 和发送端之间运行的 PBS 将游戏机的传出消息指向任意地址：

    CLI_RECV -> CLI_LOAD_TOSS_RESPONSE -> CLI_RUN_BUFFER_SCRIPT -> CLI_SEND_LOADED
 在另一个顺序中，InitSend 会覆盖 VOC 的补丁。

切勿转储在 CRC 帧和发送帧之间移动的区域：

```c
case 0:  header.crc = CalcCRC16WithTable(link->sendBuffer, link->sendSize);   // one frame
case 1:  SendBlock(0, link->sendBuffer + blocksize, ...);                     // the next
case 2:  if (CalcCRC16WithTable(...) != link->sendCRC) LinkRfu_FatalError();  // the one after
```

[mystery_gift_link.c:155]。 `gRngValue`（0x03004220）每帧前进两步；对它的转储使身体 CRC 失败，游戏机报告“erreur de connexion”。 `buffer_script.build_memory_dump` 拒绝任何与其重叠的范围； dump 周围的数据，或者使用 `rng-trace`，它通过 4 字节通道返回它。任何其他不稳定区域都必须以同样的方式找到。
<a id="the-payloads"></a>
## 有效负载
<a id="trainer-id-probe"></a>
### `trainer-id-probe`

24 字节，只读。游戏机已将其 `playerTrainerId` 发送到
`MysteryGiftLinkGameData` 比 [mystery_gift.c:337] 早几秒，所以答案是已知的。

```arm
    ldrh    r3, [r1, #0x0A]         @ SaveBlock2.playerTrainerId[0..1]
    ldrh    ip, [r1, #0x0C]         @ SaveBlock2.playerTrainerId[2..3]
    orr     r3, r3, ip, lsl #16
    str     r3, [r0]                @ *param
    mov     r0, #1
    bx      lr
```
 匹配意味着它在 ARM 状态下运行，并且 decomp 的参数与真实的 `gSaveBlock2Ptr` 相对应并返回 1；不同的值意味着参数或偏移量是错误的；没有 `Buffer script status:` 行意味着客户端脚本形状错误或从未到达调用。 7个字符的玩家名字的终结符覆盖游戏数据[mystery_gift.c:364]中的`playerTrainerId[0]`；然后主机比较前三个字节。
<a id="save-dump-and-memory-dump"></a>
### `save-dump` 和 `memory-dump`

`memory-dump` 采用绝对地址。 `save-dump` 在任何构建上通过 r1 和 r2 在任何偏移处读取任一保存块。每次运行最多 1024 字节； `MGL_Receive` 拒绝更多 [mystery_gift_link.c:102]。

    HOST --buffer-script save-dump --dump-block sav2 --dump-size 256 --version firered
    HOST --buffer-script memory-dump --dump-address 0x0201C000 --version firered
 它们在 0x0038 处到达 `SaveBlock1.playerParty`，在 0x0290 处到达 `money` 与
`SaveBlock2.encryptionKey` at 0xF20、包、标志和变量以及 IWRAM (`gRngValue`)。
<a id="memory-dump-multi-and-memory-dump-scatter"></a>
### `memory-dump-multi` 和 `memory-dump-scatter`

`MG_LINK_BUFFER_SIZE` 限制消息而不是会话。客户端从其 1024 字节接收缓冲区 [mystery_gift_client.c:140] 运行命令脚本，并转储三元组

    CLI_LOAD_TOSS_RESPONSE -> CLI_RUN_BUFFER_SCRIPT -> CLI_SEND_LOADED
 尽可能频繁地重复：41 以 8 个字节传递一条命令，并在循环中包含三个固定命令。
`mg_script.MAX_DUMP_BLOCKS` 将其保持在 32，因为终止的会话会丢失所有块。在 ESP32 无线收发设备上，16 KB 转储大约需要 57 秒，块间隔大约 2.5 秒。

`CLI_RUN_BUFFER_SCRIPT` 每次都会重新复制图像 [:238]，因此光标位于 `client->param` 中：每次都会发送 `base + index * 1024` 并传递下一个索引。高半部分没有 `0x5A5A0000` 的 `param` 是通过零。

`memory-dump-scatter` 索引碱基表：

    adr     r3, .Ltable
    ldr     r3, [r3, r1, lsl #2]    @ this block's own base
    str     r3, [r0, #0x3C]         @ client->link.sendBuffer

`adr` 是与 PC 相关的。所有 32 个槽都已填满，未使用的槽具有最后一个地址，因此额外的传递会重新发送保留的块，而不是将消息指向 0。分散的块每次连接捕获的短函数体数量大约是连续块的四倍；对于一组超过 1 MB 的 166 个未读函数体：

|一次连接，离线 16 KB |它捕获的尸体|
|---|---|
| `memory-dump-multi`，最佳基址处连续的 16 个区块 | 22 |
| `memory-dump-scatter`，数据最密集的 16 个千字节区块 | 83 |
| `memory-dump-scatter`，32块| 119 共 166 |

可读性防护检查每个分散块。这些块在一个文件中首尾相连；
`--dump-scatter A,B,C` 让 `script_read.dumps` 将每个元素放置在其基部，标记为 `<run>[0]`、`<run>[1]`、... `--dump-blocks 1` 逐字节返回 `CLIENT_SCRIPT_DUMP_MEMORY`。
<a id="anchors"></a>
### `anchors`

将11个字写入`client->sendBuffer`，并将`link->sendSize`加宽至44；不需要重新指向，因为 `CLI_LOAD_TOSS_RESPONSE` 已经瞄准了 `link->sendBuffer` 那里
[`MysteryGiftClient_InitSendWord`, mystery_gift_client.c:91]。

|词|什么|一只靴子|
| --- | --- | --- |
| 0 | `sub ip, pc, #8`：游戏机放置代码的位置 | 0x0201C000 |
| 1 | `lr`：调用[mystery_gift_client.c:276]后的ROM地址，位0设置，因为调用者是THUMB | 0x08148C75 |
| 2 | `sp` | 0x03007DB8 |
| 3 | `r0` = `&client->param`，所以`AllocZeroed`将客户端放在`gHeap`|中的位置0x020020D4 |
| 4-5 | gSaveBlock2Ptr、gSaveBlock1Ptr | 0x02024598、0x0202553C |
| 6-9 |四个 AllocZeroed 缓冲区：send、recv、script、msg | 0x02006510 .. 0x02007140 |
| 10 | 10 `link->sendBuffer` 为 InitSend 留下的；必须等于单词 6 | 0x02006510 |

每场战斗和负载 [load_save.c:75] 中的单词 4-5 都会发生变化；字 3 和 6-9 取决于堆状态。 Word 1 锚定一个 decomp 调用站点；字 10 等于字 6 确认结构偏移量。缓冲区按 0x410 分开（1024 字节加 16 字节块头），如 `malloc.c` 所描述。 `buffer_script.describe_anchors` 打印所有十一个及其一致性检查。
<a id="save-write"></a>
### `save-write`

将其尾巴复制到块中，然后将 `link->sendBuffer` 指向目的地，因此答案就是保存现在保存的内容。会话以 `CLI_MSG_BUFFER_SUCCESS` 结束，达到
`MG_STATE_SAVE_LOAD_GIFT` 并将写入提交至闪存；它在从标题屏幕重新加载后仍然存在。

    HOST --buffer-script save-write --dump-block sav2 --dump-offset 0xB20 \
        --write-text "some text" --version firered
 1个VOC携带936字节。较长的数据以 936 块的形式写入，每块都有自己的描述符，全部在会话中依次运行；客户端按照命令列表所示接收并运行它们
[mystery_gift_client.c:145, 236]。答案是保存在最后一块下的内容。

`build_save_write` 拒绝 0x090 处的 `filler_90[8]` 和 0xB20 处的 `filler_B20[0x400]` 之外的任何跨度
`struct SaveBlock2` [global.h:345,357]，`src/` 中没有任何内容引用。过去四个字节
`filler_B20` 是 `encryptionKey`，与货币进行异或运算。 `--write-unsafe` 覆盖。块在闪存中着陆的位置会旋转（[id 所在的位置](#where-an-id-lives-and-which-sector-carries-the-slots-counter)）。

`save-write` 仅更改其命名的范围：256 字节写入更改了 SaveBlock2 的 196 字节，全部位于范围内，而 SaveBlock1 没有更改。游戏中没有任何内容写入 `filler_B20`：那里的写入在保存（测量了十代）、神秘事件、奇迹卡、软重置和游戏中持续存在（在一分钟的游戏中，256 字节没有变化，其中 1456 字节的 SaveBlock1 移动了）。
<a id="memory-scan"></a>
### `memory-scan`

需要一个 32 位针和一个范围。每次调用都会扫描其 32 字节块的预算，将光标写回到其映像中并返回 0；到达末尾的调用将 `link->sendBuffer` 重新指向结果并返回 1。图像打开时会在其参数上显示一个分支：

|偏移| |
|---|---|
| 0x000 | `b .Lcode` |
| 0x004 | 游标：起始地址，由载荷向前推进 |
| 0x008 |结束 |
| 0x00C |针|
| 0x010 |每次调用的块数 |
| 0x014 | max_calls，看门狗|
| 0x018 |结果：找到的匹配项、最终光标、使用的调用、存储的匹配项 |
| 0x028 |结果：64×（地址，值）|
| 0x228 |代码 |

预算保护需要其帧的 RFU 链路。内循环是一个 8 个字的 `ldmia` 和 8 个链式 `cmpne`，每 8 个字大约有 14 条指令；默认的 512 个块是 unicorn 下的一次调用 7703 条指令，大约是来自 EWRAM 的一帧 280896 个周期中的 60000 个周期（16 位总线，ARM 读取约 6 个周期）。 16 MB 卡带可调用 1024 次，大约 17 秒。 `--scan-blocks` 设置；整个主机每秒读取约 60 个子节点帧。

`max_calls` 默认为范围需要的加二；看门狗停止会用一个短光标来回答，说明从哪里恢复。答案始终是 528 字节，因此 `len(dump) == buffer_dump_size` 证明了重新指向。 `found` 计算每个匹配项，`hits` 保留前 64 个。`ldmia` 只看到字对齐的匹配项：从未与实际步幅字对齐的针返回零。
<a id="table-scan"></a>
### `table-scan`

按形状查找表格：`runlen` 单词的每个最大运行都恰好高于其前一个单词 `delta`，并以运行的开始值和第一个值作为答案。 `gSpecialVars` [data/event_scripts.s:51] 列出 `gSpecialVar_0x8000` 到 `0x800B`，十二个连续的 `u16`
[event_data.c:16]，所以它的前十二个字步长为2，第一个值为`&gSpecialVar_0x8000`。

    HOST --buffer-script table-scan --table-delta 2 --table-runlen 12 \
        --table-start 0x08140000 --table-end 0x08400000 --version firered
 条目 12 是 `gSpecialVar_Facing`，在 `Result` 和 `LastTalked` 之后声明，从条目 11 开始+6，因此运行正好是 12，而 13 没有发现任何结果。

形状测试是〜7个指令一个字相对于〜1.75个值，因此`TABLE_SCAN_DEFAULT_BLOCKS`是192个16字节的块，与`memory-scan`的512个32个相同的负载。`run`，`runstart`和`expect`住在
0x22C..0x234 位于光标旁边，并在每次产量时保存，因为运行跨越 `ldmia` 和帧边界。 `expect` 从 0 开始，因此第一个字为零记入未写入的运行
`runstart`； `read_table_scan` 丢弃范围外的命中。

相同的形状找到一个实时的`struct ScriptContext`：`InitScriptContext`存储一个命令表及其结尾在+0x5C和+0x60 [include/script.h]，17个条目的表相隔68，因此EWRAM上的`--table-delta 0x44
--table-runlen 2`用上下文的地址回答和桌子的。在脚本运行之前，上下文为零，因此扫描必须在同一启动中遵循神秘事件礼物。
`--table-delta 0x358`（214个条目）查找字段脚本上下文，其`cmdTable`是已知的
`gScriptCmdTable`。
<a id="rom-checksum"></a>
### `rom-checksum`

对最多 128 个块的范围进行求和，每个块求和，因此主机命名的盒带块与其 ROM 映像不同；第二次在一个街区上运行较小的街区会缩小它的范围。帧循环、预算、看门狗和重新指向发送是 `memory-scan` 的。每个块从 0 开始按升序对其单词进行求和：

    acc = w + ror(acc, 31)          one `add r0, rN, r0, ror #31` per word, mod 2^32

`rom_checksum_reference` 从 ROM 文件计算出相同的结果。 XOR 将取消（重复的单词总和为 0；相等更改相隔 32 个单词取消）。超过引用末尾的块由其总和命名：零填充、0xFF 填充、开放总线（每个半字其自身地址减半）、镜像或内容。

|偏移| |
|---|---|
| 0x000 | `b .Lcode` |
| 0x004 | 游标：起始地址，由载荷向前推进 |
| 0x008 |结束 |
| 0x00C |开始 |
| 0x010 |每次调用 32 字节块 |
| 0x014 | max_calls，看门狗|
| 0x018 | shift：块大小的log2，5到25 |
| 0x01C |正在进行的块的运行总和，跨调用进行 |
| 0x020 |结果：最终光标、使用的调用、存储的总和、回显的移位 |
| 0x030 |结果：128 × u32 块和 |
| 0x230 |代码 |

答案是 0x020 中的 528 字节。构建器拒绝未与块对齐的开始、不是整数块的范围、超过 128 个块以及不是 32 字节的 2 的幂的块。每 8 个字 13 条指令； 512 个块相当于一次调用 6688 条指令。默认
0x08000000..0x09000000 在 128 KiB 块中是 1024 次调用，大约 17 秒。

    HOST --buffer-script rom-checksum --version firered
    HOST --buffer-script rom-checksum --sum-start 0x08120000 --sum-end 0x08140000 \
        --sum-block 0x400 --version firered
 主机记录每个块的范围，总和以及 `SAME` 或 `DIFF`，然后
`rom-checksum: N of M blocks differ from <image>`。图像为 `config.REFERENCE_ROMS[game code]`，或
`--sum-reference` 适用于每个版本。超出图像的块会被列出，但不会被计算在内。
<a id="rng-trace"></a>
### `rng-trace`

每帧采样一次单词，并在每个样本的两次读取之间调用 ROM 函数（`--trace-call 0` 使其成为普通采样器）。

    HOST --buffer-script rng-trace --trace-address 0x03004220 --trace-call 0x080486B1 \
        --trace-samples 96 --version firered
 调用是`mov lr, pc; bx r2`：pc读取`bx`之后的指令，位0清零，因此被调用者返回ARM状态。在零售火红中，`Random` 轨迹的每个样本都遵循 LCG（测量的轨迹中的 96 个中的 96 个）。结果在[RNG](frlg_rng.md)上。
<a id="string-gather"></a>
### `string-gather`

给定第一个指针的地址、步长和计数，将指向的每个字符串（直到并包括 0xFF 终止符）复制到一个答案中，并报告下一次运行的恢复位置。

    HOST --buffer-script string-gather --gather-address 0x083E0D54 --gather-count 69 \
        --gather-stride 12 --version firered

`--gather-stride` 对于 `struct EasyChatWordInfo` 来说是 12（`text` 为 0），对于 `const u8 *` 数组来说是 4。答案是 776 字节：四个标头字，最多 760 字节的字符串。它永远不会截断：不适合的字符串会结束运行并为其命名 `next`。 `--gather-maxlen`（默认64）限制一个不是字符串的指针。
<a id="create-mon"></a>
### `create-mon`

```c
void CreateMon(struct Pokemon *mon, u16 species, u8 level, u8 fixedIV,
               u8 hasFixedPersonality, u32 fixedPersonality, u8 otIdType, u32 fixedOtId)
```
 `r0..r3` 中有四个参数，四个在堆栈上。 `asm/create-mon.s` 遵循游戏机自己的序言：

    08041150  push {r4,r5,r6,r7,lr}    ; sp -= 20
    08041152  mov  r7, r8
    08041154  push {r7}                ; sp -= 4
    08041156  sub  sp, #28             ; sp -= 28, so entry sp is now sp + 52
    0804115c  ldr  r4, [sp, #52]       -> entry sp +  0   hasFixedPersonality  (masked to u8)
    0804115e  ldr  r7, [sp, #56]       -> entry sp +  4   fixedPersonality     (NOT masked: u32)
    08041160  ldr  r5, [sp, #60]       -> entry sp +  8   otIdType             (masked to u8)
    08041184  ldr  r0, [sp, #64]       -> entry sp + 12   fixedOtId            (u32)
 这四个单词作为整个单词指向 `sp+0..sp+12`，而 VOC 会自行弹出它们。 mon 内置于 PBS 镜像内，代码前有 32 字节的防护； `--create-mon-destination ADDR` 继续复制它并需要 `--write-unsafe`。

    HOST --buffer-script create-mon \
        --create-mon-species 151 --create-mon-level 30 --create-mon-iv 31 \
        --create-mon-personality 0x3ADE0000 --version firered

`--create-mon-call` 从 `rom_map.py` 默认为 `CreateMon | 1`； `0` 不调用任何内容并应答归零的缓冲区。答案是 116 字节（四个标头字，100 字节 `struct Pokemon`），并且
`*param`是个性。

子结构使用 `personality ^ otId` 进行加密并进行校验和，因此有效的校验和可以证明这两个字。 `check_create_mon` 检查种类、级别和 IV； `scratchpad/verify_create_mon.py` 预测十三个派生字段：来自 `gExperienceTables[growthRate][level]` 的 exp，来自 `gSpeciesInfo` 的亲密度和特性槽，来自学习集的移动和 PP，来自 `CalculateMonStats` 的六个统计数据。该昵称来自`gSpeciesNames` [pokemon.c:1810]，即卡带的法语表，并且是读取的，从未预测过。三个字段衡量游戏机：

|领域 |价值|它说了什么|
| --- | --- | --- |
| `language` | 3 | `gGameLanguage` 是 LANGUAGE_FRENCH [global.h:22] |
| `metGame` | 4 | `gGameVersion` 是 VERSION_FIRE_RED [global.h:11] |
| `metLocation` | 91 | 91 `GetCurrentRegionMapSectionId()` [overworld.c:1265]，玩家站立的地方|

`buffer_script.shiny_personality(tid, sid)` 给出异色 `fixedPersonality`。离线存根
`CreateMon`：`CREATE_MON_ARG_MODEL` 将八个参数写入目标，
`create_mon_copy_model(source)` 复制 100 个准备好的字节。
<a id="create-mon-append"></a>
#### `--create-mon-append`

它写的是`gPlayerParty`，而不是保存块的队伍：

```c
void SavePlayerParty(void)
{
    gSaveBlock1Ptr->playerPartyCount = gPlayerPartyCount;
    for (i = 0; i < PARTY_SIZE; i++)
        gSaveBlock1Ptr->playerParty[i] = gPlayerParty[i];
}
```
 向保存块的追加报告成功，但在下一次保存 [load_save.c:160,196] 时丢失。它写入 `slot == playerPartyCount` 并增加计数，就像 catch 一样；被占用的槽永远不会被触及，满行则不写入任何内容。第五个答案词报告
`countBefore | slot << 8 | status << 16`（0未问，1追加，2队伍满，3空跑）。带有绝对值 `--create-mon-destination` 或 `--create-mon-call 0` 的附加将被拒绝。

    # dry run first: the same code with the two stores left out
    HOST --buffer-script create-mon --create-mon-append-dry-run \
        --create-mon-species 59 --create-mon-level 30 --version firered
    HOST --buffer-script create-mon --create-mon-append \
        --write-unsafe --create-mon-species 59 --create-mon-level 30 --version firered
 试运行报告计数、目标地址和该槽的当前 100 字节，捕获
`playerPartyCount` 表示不同意队伍的观点。空槽不全为零：`ZeroMonData` 以 `SetMonData(mon, MON_DATA_MAIL, &MAIL_NONE)` [pokemon.c:1737] 结尾，因此偏移 0x55 为 `0xFF`（`buffer_script.EMPTY_PARTY_SLOT`、`is_empty_party_slot`）。

| |动作？ |那么|
| --- | --- | --- |
| `gSaveBlock1Ptr` |是的，每次战斗和负载时都会重新滚动随机 4 对齐偏移 [`SetSaveBlocksPointers`, load_save.c:75] |每次通话都从 `r1`/`r2` 获取 |
| `gPlayerParty` |不，链接时 EWRAM 全局 |地址是合法的 |

`gPlayerParty` 是 0x02024280 和 `gPlayerPartyCount` 0x02024025：EWRAM 转储的一个 4 对齐窗口，解码为校验和 `struct Pokemon`。
<a id="call"></a>
### `call`

一个地址、最多八个参数字、返回的 `r0` 以及读取调用两侧的一个地址。

    HOST --buffer-script call \
        --call-address 0x080486D1 --call-arg 0xC0DE --call-watch 0x03004220 --version firered

    0x000  b .Lcode
    0x004  function    THUMB pointer (bit 0 set), or 0 to call nothing
    0x008  argc        how many of the eight words below are meant
    0x00C  args[0..7]  r0, r1, r2, r3, then [sp+0], [sp+4], [sp+8], [sp+12]
    0x02C  watch       a word to read before and after the call, or 0
    0x030  result      calls used, function, argc, r0, *watch before, *watch after

`asm/call.s` 总是压入十六个堆栈字节；被调用者永远不会弹出它们。 `SeedRng`什么也没返回（`gRngValue = seed` [random.c:15]），所以监视字就是证据。仅调用已读取为代码的地址。 `tests/test_buffer_script.py`通过unicorn下的VOC运行游戏机自己的`SeedRng`字节，以及具有2的幂的八参数路径。
<a id="flash-write"></a>
### `flash-write`

在 EWRAM 中组成一个 4 KB 扇区，并通过 [`swi 0x48`](#the-flash-sector-path) 将其写入闪存，绕过游戏的保存代码。划痕是`gDecompressionBuffer + 0x400`、0x400，位于VOC自身图像上方。

    --flash-sector N            the sector, 0..31; 0..27 are the save bands and need --write-unsafe
    --flash-fill-base WORD      word[i] = base + i * step, the data pattern
    --flash-footer              compose a well-formed sector instead of a raw pattern
    --flash-id N                the sector id at +0xFF4
    --flash-derive              read the save globals and place it where that id actually lives
    --flash-position N          aim at band position N and derive the id from it instead
    --flash-counter-bias N      added to gSaveCounter for the footer

`--flash-footer` 与游戏一样从模式末尾到 `+0xFF4` 归零，计算游戏的校验和并设置 id、校验和、签名和计数器。状态字是物理扇区（高半部分）和校验和（低半部分）。 `--flash-derive` 读取 `gLastWrittenSector` 和
写入时的 `gSaveCounter`：每次保存都会前进，并且以成功消息结束的礼物会话会保存 [mystery_gift_menu.c:1379]。
<a id="sloop-svc"></a>
### `sloop-svc`

一个会话中最多有 8 个 Sloop 系统调用，使用主机选择的操作数，并通过结果块进行应答。

    IP_HOST --buffer-script sloop-svc --svc-number 0x4d --svc-text "hello fuck" \
        --svc-data-in r0 --version firered

    0x000  b .Lcode
    0x004  flags       bit 0: r0 = &copy, bit 1: r1 = &copy
    0x008  r0..r3
    0x018  scratch     gDecompressionBuffer + 0x400
    0x01C  length      of the data, at most 256
    0x020  thunk       swi N ; bx lr (THUMB), or bkpt N ; bx lr with --svc-bkpt
    0x024  count       1..8
    0x028  numbers     eight bytes, one per call
    0x030  data
 在每次调用之前，纳税重新复制数据并将数字写入 thunk 的低字节。结果块：标记`0x53565331`，计数，标记`0x53565332`，长度，8个20字节记录（thunk字，`r0..r3`之后），以及最后一次调用留下的数据。仅值号码（0x46，
0x49..0x4B、0x4D、0x4E、0x50..0x54、0x58..0x60）作为他们是； 0x48、0x56、0x4C 和 0x55 被拒绝；其余的，还有`--svc-bkpt`，需要`--write-unsafe`； `--svc-bkpt` 拒绝`#0x52`。
<a id="install-resident"></a>
### `install-resident`

将常驻 THUMB 挂钩复制到 `0x0203FC00` 并在一个会话中将其安装到 `gIntrTable[4]` 中。它运行每一帧，通过 CONTINUER 和主世界，直到软重置。

    IP_HOST --buffer-script install-resident --resident turbo \
        --resident-param extra=4 --resident-param field=1 --resident-param battle=1 \
        --resident-param overlay=0x03004220 --resident-param hold=0x100 \
        --resident-param budget=228 --write-unsafe --version firered

    0x000  b .Lcode
    0x004  dest          0x0203FC00
    0x008  length        of the hook, whole words
    0x00C  table         &gIntrTable[4], 0x03002730
    0x010  entry_off     the hook's entry inside it
    0x014  original_off  its p_original word
    0x018  blob_off      where the hook starts in this image, after the installer's code
 THUMB 安装程序为 148 个字节，为挂钩留下 876 个字节，其数据（`p_frames`、`p_ring`、`p_state`）不得与其代码重叠或传递 `0x02040000`。 REG_IME 在复制和表写入周围被清除。第一次安装将替换的处理程序保留在 `0x0203FBFC` 处；稍后将链安装到该字，并在其为空时以 `0xBAD0BAD0` 拒绝。答案是处理程序找到的：
`0x0800071D` 全新安装。一次只有一个钩子驻留；全部共享 `0x0203FC00` 的 1 KB。
<a id="turbo"></a>
#### `turbo`

`asm/resident/turbo.s`运行`VBlankIntr`，然后在空闲帧中主世界的回调`field`更多次，战斗的`battle`更多次，以及`RunTextPrinters`（`0x08002D51`） `extra` 更多次。仅当 `callback1`/`callback2` 恰好是 `CB1_Overworld` (`0x08059E49`) / 时才会运行通行证
`CB2_Overworld`（`0x08059EC9`）或`BattleMainCB1`（`0x08015B6D`，由战斗初始化存储在
`0x08013FDE`) / `BattleMainCB2` (`0x08014889`)，在两次调用之间重新检查。 `newKeys` 和
`newAndRepeatedKeys` 首先被清除，因此按下一次即可处理。

设置 `gPaletteFade.active` (`0x02037AB4`) 时不运行任何 pass：硬件淡入淡出结束时
`UpdatePaletteFade` 设置一位 `hardwareFadeFinishing` 并且下一个 V-blank 看到它
[palette.c:701, 743];一帧中的第二次更新将该位包装为 0，然后 `CompleteWhenChoseItem` 在战斗中袋子关闭后永远等待。还有两个门：

- `gMain.intrCheck` (`0x030022EC`) 位 0 清零，在 `VBlankIntr` 之前读取：主循环停在 `WaitForVBlank` [main.c:462] 中。集合是一个滞后框架，单独留下。
- 在 `sTextPrinters`（`0x02020034`，0x24 的 32 个字节）中，其原点（`currentX ==
  x`，`currentY == y`）中没有活动打印机：字段消息在绘制其框 [field_message_box.c:44] 之前添加其打印机，并且在框绘制之前通过绘制的打印到一个窗口中，然后该框被清除。

在模拟器上测量：每秒 60 帧，97% 空闲，每帧有 5 个字形的文本； `field=1` 是主世界的两倍，`battle=1` 是一场战斗及其菜单。

`hold=MASK` 仅在 `gMain.heldKeys` (`gMain + 0x2C`) 保留掩码中的每个按钮时运行回调传递；不管怎样，文本附加功能都会运行。使用 `hold=0x100` (R)，挂钩将每帧存储 1 个
`gHelpSystemToggleWithRButtonDisabled`（`0x0203F171`，`0x0813F6FC` 处的文字
`RunHelpSystemCallback`、`0x0813F65C`），因此R不打开帮助系统[help_system_util.c:50]； L仍然如此。

`budget=LINES` 随时间流逝。当帧代码运行时，Switch 模拟器会前进 `REG_VCOUNT`（0 到 227，V-blank 从 160）；仅当自 V-blank 起的行加上最后一次传递成本的两倍适合 `LINES` 时，传递才会开始。最后一次费用在柜台`+0x0C`，保留的通行证计在`+0x10`；每一次保留的传递都会将保留的成本减少八分之一。

在模拟器上测得：

|设置，R 持有 |额外传递一帧|注意|
|---|---|---|
| `field=2 battle=2` | 1.70 至 1.90 的 2 |约 2.9 倍，无明显延迟 |
| `field=3 battle=3` |最多 2.38 / 3 |大约四分之一的帧滞后；可见的口吃 |
| `field=3 battle=3 budget=228` |高达 2.48 |光滑的;通行证的步行成本为 36 至 42 条线，战斗中则为 100 至 108 条线 |

`overlay=ADDRESS` 在主世界的右上角将 `ADDRESS` 处的单词绘制为八个十六进制数字（`0x03004220` 是 `gRngValue`）。条目进入`gMain.oamBuffer[120..127]`（`0x030026C8`），两种颜色进入`gPlttBufferFaded`（`0x020375F4`）和`gPlttBufferUnfaded`（`0x020371F4`）的OBJ调色板15，之前`VBlankIntr` 的 `LoadOam` 和 `TransferPlttBuffer`（在其之后，顶行落后一帧）。当两个标记字不同时，128 字节 1bpp 字体（十六个 3x5 位，第 1 至 5 行的像素 2 至 4，`asm/resident/overlay.inc`）将扩展为 OBJ 图块 1008 至 1023。覆盖层会覆盖游戏在调色板 15 和这些图块中保留的所有内容。

`ring=ADDRESS`（140字节；`0x0203FF74`在EWRAM的顶部结束）将`VBlankIntr`找到它时保留`gRngValue`，一个字一帧为32帧，并在`watch`时冻结（`gEnemyParty[0]`的个性，
`0x02024028`）更改。草的遭遇的个性源自每一粒保存下来的种子。在模拟器上的草地上行走时测量：两个 `Random` 调用一个帧，并且从前一帧的种子开始，性格滚动是第五次调用（`VBlankIntr` 的 [main.c:412]，帧自己的、插槽、级别、性格）。
<a id="shiny-ivs-noencounter"></a>
#### `shiny`, `ivs`, `noencounter`

`shiny` (`asm/resident/shiny.s`) 倒计时到下一个异色百搭卷。 `VBlankIntr` 每帧调用一次 `Random` [main.c:412]；野生宝可梦以其本性投掷 `Random() % 25`，然后抽牌
`Random() | Random() << 16`直至性格匹配[wild_encounter.c:233, pokemon.c:1864]；
`method=1` 采用第一对（脚本化的 `CreateMon`）。 异色为`TID ^ SID ^ high ^ low < 8`，TID和SID来自`gSaveBlock2Ptr`（`0x0300422C`）`+0x0A`。该钩子逐帧跟踪`gRngValue`（最多64步，否则重新启动），在每个空闲帧搜索`search`候选者，并以十进制显示目标的性格和`target - current - offset`（`offset=4`，草情况），或`FF`和搜索距离。当 `slow` (R) 被持有时，它会等待 `slow_frames` 更多的 V 空白帧：`IntrMain` 在处理程序 [crt0.s] 中启用 VCount，因此 `m4aSoundVSync` 运行，并且钩子调用 `m4aSoundMain` （`0x081DF53D`、`gPcmDmaCounter` `0x03002F68` 来自 `gSoundInfo` `0x03005F80`）每个等待的 V 空白并将其清除在 `REG_IF` 中。状态为 36 个字节，位于 `0x0203FF80`。

`ivs` (`asm/resident/ivs.s`) 在两行上显示先导的 IV（`OVERLAY_TWO_ROWS`，第二行）
`gMain.oamBuffer[112..117]` at y 10)：生命值、攻击力、防御力、速度，然后是 Sp。阿特克，Sp。定义和
`personality % 25`。 `GetMonData(mon, MON_DATA_IVS)`（66，`0x080432E5`）返回6个五位IV，HP最低[pokemon.c:3250]； `GetBoxMonData` 就地解密并重新加密 [pokemon.c:2992, 3327]，因此仅在空闲的主世界帧中进行调用。

`noencounter`（`asm/resident/noencounter.s`）每帧将1存储到`sWildEncountersDisabled`（`0x020386D8`）中，其中`StandardWildEncounter`（`0x08086528`）首先测试[wild_encounter.c:360]；
`DisableWildEncounters` (`0x08085FAC`) 是其唯一的其他编写者。草、水、漫游者的遭遇停止；钓鱼和香香各走各的路。
<a id="noclip"></a>
#### `noclip`

`noclip`（`asm/resident/noclip.s`，304字节）允许玩家在按住`hold`（默认`0x100`，R）中的每个按钮的情况下穿过墙壁。在每个空闲的主世界帧上（`gMain.intrCheck` 位 0 清零，
`callback2` `CB2_Overworld`）它将地图网格中玩家`currentCoords`周围的四个块`VMap.map`（`gBackupMapData`，`0x02031DF8`）重写为碰撞0和高度15，保留元图块id。 `VMap` 是 `0x03004260`（法语）或 `0x03004310`（英语）中的 `{s32 Xsize, s32 Ysize, u16 *map}`，即 `MapGridGetCollisionAt` 中的文字。一个块是`metatile | collision << 10 |
elevation << 12` [global.fieldmap.h:7]； `GetCollisionAtCoords` 在冲突位上阻塞，然后在
`IsElevationMismatchAt`，通过海拔 15，而 `ObjectEventUpdateElevation` 在 15 块 [event_object_movement.c:4830, 8346, 8400] 上使玩家自己的海拔保持不变。

下一个空闲帧将每个块放回原处，仅当 `gMapHeader.mapLayout` (`0x02036DF8`) 是它更改的布局并且该块仍然具有其元图 id（标高 15 和碰撞 0）：游戏重写的扭曲或元图保留新块时。等于 `MAPGRID_UNDEFINED` (`0x3FF`) 的方块会保留，否则玩家将离开地图。物体事件仍然会阻塞（`DoesObjectCollideWithObjectAt`），壁架仍然会跳跃，并且玩家旁边的徘徊物体事件可以踩到打开的块上。按住 R 将打开帮助系统，因此挂钩将每帧 1 存储到 `0x0203F171` 中（请参阅 `turbo`）。 `0x0203FF80` 处的状态为 24 个字节：布局、计数和四个 `{u16 index, u16 block}`。

`tests/test_noclip.py`通过每个卡带自己的客户端安装它，并用卡带自己的`MapGridGetCollisionAt`和`MapGridGetElevationAt`读取结果。在 Pallet Town 中使用法语版卡带在 mGBA 上进行测量：向南走，玩家在没有 R 的情况下停在栅栏处，并在持有 R 的情况下穿过六块瓷砖；对象事件仍然会阻止它。
<a id="follower"></a>
#### `follower`

`asm/resident/follower.s` 作为一个真实的物体事件，带领宝可梦在玩家身后走一格，由游戏自己的移动动作移动，因此游戏绘制其脚步、奔跑、壁架跳跃（弧线、阴影、落地灰尘）、门淡入淡出和精灵优先。该设计遵循 GB-Link 的 `cards/follow.s` (GPL-3.0)。它是 984 字节，经过一个 `install-resident` 会话，因此它是从保存中安装的（[保存在保存中的常驻挂钩](#a-resident-hook-kept-in-the-save)）。

在每个空闲的主帧（`gMain.intrCheck` 位 0 清除，`callback2` `CB2_Overworld`）上，之后
`VBlankIntr`：

|步骤|钩子的作用是什么？
| --- | --- |
|找到它 |本地 ID `0xF0` 的活动对象事件，没有地图使用的本地 ID；地图加载后无 |
|产卵| `SpawnSpecialObjectEventParameterized(gfx, MOVEMENT_TYPE_NONE, 0xF0, x, y, elevation)` 在玩家的图块上，隐藏直到玩家迈出第一步 |
|每一帧 |它当前的高度设置为 14，没有任何图块具有该高度：玩家通过它往回走，没有任何东西与它对话 [event_object_movement.c:4899]； `fixedPriority` 在字段锁定时设置，因此负载保持该高度 |
|玩家一步|玩家留下的方块成为其目标；一个格子之外，它会获得玩家自己的动作系列（运行变成`WALK_FAST`），离线时它会被直接移动到那里，`MoveObjectEventToMapCoords` |
|壁架|玩家的 `JUMP_2` 移动其坐标两次：第一次将跟随者带到边缘，第二次将其留在那里；在玩家的下一步中，它会执行 `JUMP_2` 本身，两个图块；两块瓷砖排成一行，没有壁架挂起，它以 `WALK_FASTER` (0x35) 关闭，一次一块瓷砖 |
| 菜单 | `sLockFieldControls`（`0x0300109C`）与 `sGlobalScriptContextStatus`（`0x03000FA8`）在 `CONTEXT_SHUTDOWN` 时设置：执行 `RemoveObjectEvent`，因此存档中不会保留该对象；之后会再次生成 |
|自行车、冲浪、潜水 |隐藏在玩家的图块上 |
|新的线索|删除并再次生成|
|一个肿块|玩家在海拔 0 的图块上撞到它会将其放在玩家的图块上 |

|铅 |对象|
| --- | --- |
|拥有主世界精灵的 42 个种类之一（`OBJ_EVENT_GFX_SNORLAX` 109 至 `DEOXYS_N`；代欧奇希斯的版本形式为建造者的 `deoxys=`） |它自己的图形ID |
|任何其他种类，一个蛋，字母未知图腾 | 卡比兽的32x32帧(109, `sAnimTable_Standard`);其精灵的 `images` 指向 OBJ 调色板 15 上 `0x0203FBB4` 处的 9 个 `SpriteFrameImage`（站立 0..2：图标帧 0，行走 3..8：帧 1，每个 0x200 字节，来自 `GetMonIconPtr`）|

图标的调色板转到 `gPlttBufferUnfaded` OBJ 调色板 15 (`0x020375D4`) 每个空闲帧，并转到
`gPlttBufferFaded` (`0x020379D4`) 仅当混合 `y`（`gPaletteFade + 4`，位 6..10）为 0 时。门淡出运行 `BeginNormalPaletteFade` 到 `y` 16，然后清除`active` 屏幕仍然黑屏
[field_weather.c:740, palette.c];在 mGBA 上测量，走进一扇门，`active` 保持设定 21 帧，然后 `y` 16，`active` 清除 4 帧，然后 `callback2` 离开主世界。

场中的 A，而玩家前面的图块是跟随者的且场未锁定（游戏自己的 A、脚本或菜单首先获取帧）：`gSelectedObjectEvent` 设置为它并且
`ScriptContext_SetupScript` 运行，种类写成（`SPECIES_EGG` 没有，412，没有哭声）：

    6A                lock
    A1 SPEC 0000      playmoncry SPECIES, CRY_MODE_NORMAL
    5A                faceplayer
    4F F000 PTR       applymovement 0xF0: 66 FE (MOVEMENT_ACTION_EMOTE_SMILE, step_end)
    51 0000           waitmovement 0
    C5                waitmoncry
    7F 00 0000        bufferpartymonnick STR_VAR_1, 0
    67 PTR            message: "{STR_VAR_1} saute\nde joie !" (French), "{STR_VAR_1} jumps\nfor joy!" (English)
    66 6D 6C 02       waitmessage, waitbuttonpress, release, end
 状态，`0x0203FFDC` (`state=`) 处的 17 个字节：`+0` 其对象事件或 `0xFF`、`+1` 待处理步骤，`+2` 显示图标， `+3` 运动系列，`+4` 玩家上次看到的坐标，`+8` 目标，
`+12` 是领头的种类，`+14` 是它生成的种类，`+16` 是一个待定的壁架。图标的帧表为 72 字节，位于 `0x0203FBB4` (`images=`)，位于安装程序保存的处理程序 `0x0203FBFC` 下方。

|卡带| `SpawnSpecialObjectEventParameterized` | `ObjectEventSetHeldMovement` | `ObjectEventClearHeldMovement` | `MoveObjectEventToMapCoords` | `RemoveObjectEvent` | `ScriptContext_SetupScript` | `gSelectedObjectEvent` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BPRF、BPGF | `0x08062130` | `0x080675A4` | `0x08067634` | `0x08063024` | `0x08061DB4` | `0x0806D3D4` | `0x03004294` |
| BPRE、BPGE | `0x08061FD4` | `0x08067448` | `0x080674D8` | `0x08062EC8` | `0x08061C58` | `0x0806D270` | `0x03004344` |

|卡带| `gMonIconPaletteIndices` | `gMonIconPalettes` | `GetMonIconPtr` |
| --- | --- | --- | --- |
| BPRF | `0x083CBEE8` | `0x083CB7A8` | `0x0809AA74` |
| BPGF | `0x083CBD24` | `0x083CB5E4` | `0x0809AA48` |
| BPRE | `0x083D197C` | `0x083D123C` | `0x0809A7B8` |
| BPGE | `0x083D17B8` | `0x083D1078` | `0x0809A78C` |

英文值为`pokefirered_switch.elf`的；法语的字节与每个图像中找到的字节相同。
`tests/test_follower.py` 在 `install-kept` 将钩子安装在每个图像上时运行钩子，对象函数代表：生成、行走、图标框架和调色板、壁架等待和单跳、对话脚本、菜单下的删除。

`AddSpritesToOamBuffer` 仅用 `gDummyOamData` 填充未使用的 OAM 条目，最多为 `gOamLimit`
[sprite.c:487]，`ResetSpriteData` 将其设置为 64 [sprite.c:297]，并在主世界中读取 64 (`0x02021B44`)：由钩子写入的高于 64 的条目将保留在屏幕上，直到屏幕重置其精灵。
<a id="verified"></a>
#### 已验证

|钩子|零售法语版《火红》，ESP32 收音机（每个安装答案 `0x0800071D`）|模拟器|
| --- | --- | --- |
| `turbo` `extra=4 field=3 battle=3 hold=0x100 budget=228` |按住 R 快进 | |
| `overlay` | 显示八位数字，每帧变化 | 在 CONTINUER 之后的回顾中显示 |
| `shiny` |在草地上倒计时； R 减慢速度 |以下种子匹配 `gRngValue`； Python 模型同意异色 |
| `ivs` |线索的 IV 字和 `personality % 25` 匹配 `SaveBlock1 + 0x34` 的 `save-dump` |匹配 `gPlayerParty` (`0x02024280`) |
| `noencounter` |草丛中行走，不遇狂野|没有任何;遇到软重置后返回|
| `turbo-lite+noclip+noencounter`、`turbo-lite.field=2 battle=2 hold=0x2`、`noclip.hold=0x100` |一次会话回答 `0x0800071D`； B按住快进，R按住穿墙，没有草丛遭遇，两个按钮同时快速穿墙| |
| `follower` |走在后面的一块瓷砖上，在壁架边缘等待，并在玩家走下着陆瓷砖后跳过它，带着游戏的阴影和灰尘；在壁架上跑来跑去，没有闪烁； A面对它：哭、笑、行；开始菜单和门；一个会话将其写入保存并安装它 | mGBA上同样有吉利蛋的精灵和水箭龟的图标|

未解决：在模拟器上，在 CONTINUER 之后的回顾期间绘制了覆盖层，但不在交互式游戏中绘制，而 `field` 仍然加快了游戏速度。

每个钩子都运行在叶绿上，并更改了一个地址：`m4aSoundMain` 是 `0x081DF518`（其 `bl`
`VBlankIntr` 在 `0x08000772`）；所有其他常数都通过火红自己的引用进行相同的映射。
`follower` 还读取其部分中列出的移动的 ROM 表和函数。建造者采用`version=`，主机`--version leafgreen`。在模拟的叶绿：turbo 和 `shiny` 上进行验证，音乐完好无损。
<a id="several-hooks-at-once"></a>
### 一次多个钩子

每个钩子都将其替换为函数（`bl` 到 `p_original` 上的 `bx r3`）的处理程序调用，并通过其自己推送的 `lr` 返回，因此钩子的 `p_original` 可能会命名另一个钩子。 `--resident
turbo-lite+noclip+noencounter` 将钩子从 `0x0203FC00` 背靠背放置，写下每个钩子的
`p_original` 作为下一个条目（Thumb 位设置），并将一个 blob 交给安装人员，该 blob 的条目是第一个钩子的，其 `p_original` 是最后一个的。 `install-resident`、`install-kept`和MOM的加载器不变。设置将其挂钩命名为：`--resident-param turbo-lite.hold=2`。

|规则|为什么|
|---|---|
|订购turbo、noclip、异色、ivs、noencounter | Turbo 的回调传递在其他钩子完成帧后运行 |
|每个hook的数据都放在`0x0203FBB4..0x0203FBFC`中，然后上面的代码|默认重叠：`shiny`、`ivs` 和 `noclip` 都将状态保持在 `0x0203FF80` |
|至多 `shiny`、`ivs` 和 Turbo 的 `overlay` 之一 |每个都在 `gMain.oamBuffer[120..127]` 和 OBJ 调色板 15 中绘制 |
| `follower` 单独运行 | 984 字节：对于任何其他钩子，它都会传递保存保存的 1004 |
|代码适合 `0x0203FC00..0x02040000` | 1024字节；过去 876 集经过保存，过去 1004 无处可去 |

`turbo-lite` (`asm/resident/turbo-lite.s`) 是 `turbo.s` 与 `TURBO_LITE` 集组装而成：相同的通过、门、保持和预算，没有覆盖，没有 RNG 历史，356 字节对 696。每个 Turbo 帧测试都在其上运行 (`tests/test_turbo_lite.py`)；框架通过链条运行每个钩子，
`VBlankIntr` 一次（`tests/test_resident_chain.py`）。
<a id="install-kept"></a>
### `install-kept`

`asm/install-kept.s`，192字节，安装`filler_B20`中保留的钩子，就像`install-resident`安装自己的钩子一样：它读取`gSaveBlock2Ptr`（块在每次加载时移动），检查魔术，将校验和留在`filler_B20`内的长度以及总和，然后清除REG_IME，将游戏处理程序保留在 `0x0203FBFC`，复制钩子，写入 `p_original` 并将 `gIntrTable[4]` 指向它。答案是表中找到的处理程序，或者在未安装任何内容时为 `0xBAD0BAD0`。 +0 处的 ARM 条目是缓冲区脚本的； MOM 的 RAM 脚本在 +8 处运行 THUMB 条目，该条目将答案指向图像中的某个单词。每个卡带的最后两个字已修补：`&gSaveBlock2Ptr` 和
`&gIntrTable[4]`。

    IP_HOST --buffer-script install-kept --version firered

<a id="a-resident-hook-kept-in-the-save"></a>
### 保存在保存中的常驻钩子

任何常驻挂钩都可以驻留在 `filler_B20` 中，并在启动后通过与 MOM 对话来重新安装，无需链接，也无需主机。两场礼物会议设置了它：

    IP_HOST --buffer-script save-write --resident follower --version firered
    IP_HOST --gift resident-save --version firered
 第一个将此 blob 写入 `SaveBlock2 + 0xB20` 并在同一会话中安装其中的挂钩：

    +0x00  magic     0x32524B50, "PKR2"
    +0x04  length    the hook's bytes, whole words
    +0x08  dest      0x0203FC00
    +0x0C  entry     u16 offset of the hook's entry
    +0x0E  original  u16 offset of its p_original word
    +0x10  the hook
    +len   checksum  the sum of every word before it
 超过 1 个 `save-write`（936 字节）的 blob 由两个写入。会话运行每次写入，然后运行 [`install-kept`](#install-kept)，每个都有其自己的危险：客户端按照其命令列表中的 [mystery_gift_client.c:145, 236] 依次接收并运行缓冲区脚本，并且只有最后一个答案返回。

    client  RECV RUN  RECV RUN  RECV RUN LOAD_TOSS_RESPONSE SEND_LOADED  RECV COPY_RECV
    host    script    write 1   write 2  install-kept   <- the handler found
 会话以 `CLI_MSG_BUFFER_SUCCESS` 结束，保存，因此 `filler_B20` 到达闪存。

第二个将 RAM 脚本绑定到 MOM，该 MOM 暂存 36 字节 [ram-jump Trampoline](#a-payload-larger-than-a-script-body) 并分支到 `install-kept` 的 THUMB 条目，该条目在脚本主体中以每个字节 (428 字节 995) 的形式承载。与 MOM 对话安装钩子；第二次访问链接到保留的处理程序，软重置会删除挂钩，直到再次与 MOM 对话。

|钩子|斑点| `save-write` 有效负载 |
| --- | --- | --- |
| `noencounter` | 48 | 1 |
| `ivs` | 520 | 1 |
| `turbo-lite` | 376 | 1 |
| `turbo` | 716 | 1 |
| `shiny` | 888 | 1 |
| `follower` | 1004 | 2 |

`tests/test_resident_save.py` 在主机和模拟客户端之间运行整个会话，以及启动游戏机上 MOM 的正文脚本：翻转字节、丢失第二次写入、过去的长度
`filler_B20` 什么也不安装。零售火红从其 `PKR2` blob 安装追随者。

一个新的神奇关联解除了绑定：`SaveWonderCard`来电`ClearSavedWonderCardAndRelated`，这称为`ClearRamScript` [mystery_gift.c:172, 160]. `filler_B20`保持原样。
<a id="call-chain"></a>
### `call-chain`

一帧中最多按顺序排列十六个步骤，每个步骤一个答案词。

    HOST --buffer-script call-chain \
        --chain-step call:FlagGet,0x828 \
        --chain-step call:FlagSet,0x828 \
        --chain-step call:FlagGet,0x828 --version firered
 一个步长为 24 个字节（操作、目标、四个参数），写为 `OP:TARGET[,ARG]...`，操作为 `call`，
`read32/16/8`，`write32/16/8`。调用目标可以是 `rom_map.CALLABLE` 名称（绝不是解压缩地址）。

步骤可以从前一个结果 `prev` 中获取其目标或第一个参数：

    --chain-step call:GetVarPointer,0x4024      prev = the address the GAME computed
    --chain-step read16+keep:prev               the value before, prev untouched
    --chain-step write16:prev,7                 the store, read back by the payload itself
    --chain-step read16:prev                    the value after

`ScrCmd_setvar`通过`GetVarPointer`的返回[scrcmd.c:472]写入；没有 ScrCmd 工作人员是 `VarSet`（[ROM 映射](frlg_rom_map.md)）。写入永远不会变成`prev`；除非携带 `+keep`，否则读取会执行此操作。每次写入都会将自身读回到答案中。

    0x000  b .Lcode
    0x004  count       how many steps are meant, 0..16
    0x010  steps[16]   {op, target, a0, a1, a2, a3}, 24 bytes each
    0x190  result      calls, count, steps executed, the op word that stopped it
    0x1A0  values[16]  one word per step, in order
 未知操作码停止运行并在答案中指定； ARM 也限制了步数。构建器拒绝空链、超过十六步、对 ARM 指针或卡带外部的调用、来自 `prev` 的调用目标（错误的目标会挂起菜单）、未对齐或无法访问的读取、超过四个参数以及任何没有 `--write-unsafe` 的写入（游戏机随后提交其保存）。

    call GetVarPointer(0x4024)   -> 0x020265B4
    read16 [prev] keep           -> 0
    write16 [prev] = 3           -> 3        the store, read back by the payload
    read16 [prev]                -> 3
    call VarGet(0x4024)          -> 3        the game's own reader, same frame
 `gSaveBlock1Ptr` 更改基数后变量仍然读取 3。钱是 `*moneyPtr ^
gSaveBlock2Ptr->encryptionKey` [money.c:14]：

    read32 [0x03004228]              -> 0x02025554     gSaveBlock1Ptr
    read32 [prev + 0x290] keep       -> 0x5A5A198C     the ciphertext, before
    call GetMoney(prev + 0x290) keep -> 0x00000BB8     3000, the plaintext
    call AddMoney(prev + 0x290, 1234) keep
    call GetMoney(prev + 0x290) keep -> 0x0000108A     4234, exactly +1234
    read32 [prev + 0x290]            -> 0x5A5A02BE     the ciphertext, after
（说明性值。）两个 XOR 对都给出密钥，此处为 0x5A5A1234，即 SaveBlock2 + 0xF20 处的字（`rom_map.SAV1_MONEY`、`SAV2_ENCRYPTION_KEY`）。特殊从特殊变量中读取其操作数：将`gSpecialVar_Result`设置为`GET_CARD_BATTLES_WON`，特殊390回答卡的`battlesWon`，值`SaveBlock1 + 0x3434`保存在同一帧中。

永远不要从缓冲脚本中调用扭曲或消息工作者：神秘礼物菜单没有主世界。它们属于[字段存根](frlg_rng.md#the-payload-in-the-script-body)。
<a id="writing-a-sector-the-game-will-load"></a>
## 写入游戏将加载的扇区

下面的所有内容都是在模拟器上测量的。
<a id="the-checksum-covers-the-ids-chunk"></a>
### 校验和覆盖了 id 的块

`CalculateChecksum(data, size)` 将 `size` 字节求和为小端 u32 字并折叠
`(sum >> 16) + sum` 到 u16 [decomp:src/save.c]。 `size` 是来自 `sSaveSlotLayout` 的 id 自己的块，法语版卡带上的 `0x083F58C4` 处有 14 个 {u16 偏移量，u16 大小}条目：

|编号 |尺寸|编号 |尺寸|
| --- | --- | --- | --- |
| 0 | 3876 | 4 | 3816 |
| 1-3 | 3968 | 5-12 | 3968 |
| 13 | 2000 |  |  |

`HandleWriteSector` 在复制块 [save.c:181-183] 之前将整个扇区缓冲区清零，因此游戏写入的扇区在其块之后为零，并且将所有 3968 字节相加得到相同的校验和；数据超过其块的组合扇区将被拒绝。仅填充该块。当游戏机决定id时，最多填充2000字节，最小的块：一个校验和对任何id都有效。
<a id="where-an-id-lives-and-which-sector-carries-the-slots-counter"></a>
### id 所在的位置以及槽计数器所在的扇区

一个槽位有14个扇区；游戏在两个插槽之间交替并轮换 ID [decomp:src/save.c:174]：

    physical = ((gLastWrittenSector + id) % 14) + 14 * (gSaveCounter % 2)

`gLastWrittenSector` 每次完整保存都会前进 1，在 14 处结束 [:147]。它与普通游戏中的计数器一致，但当写入被标记为损坏时会分离：游戏将其恢复
`gLastKnownGoodSector` [save.c:159] 和 `Save_ResetSaveCounters` [:104] 独立重置它。
`gLastKnownGoodSector` 和 `gLastSaveCounter` 在前进之前采用了现场对，因此它们准确地描述了上一代。通过解析页脚来查找扇区，而不是通过固定的文件偏移量。

`GetSaveValidStatus` 当扇区签名为 `0x08012025` 并且其校验和超过时，对扇区进行计数
`locations[id].size` 匹配，id 取自其自己的页脚：

- 仅当所有 14 个 id 都存在且有效时，一个槽才可以；一个时隙内的计数器不需要一致；
- `slotNsaveCounter` 按物理顺序分配在每个有效扇区上，因此它保存最后一个有效扇区的计数器。

因此，最后一个扇区带有较高计数器的完整乐队将胜过所有扇区都带有较低计数器的乐队（13 个在 129 处，一个在 131 处击败了 14 个在 130 处）。

|地址 |符号|宽度|
| --- | --- | --- |
| `0x030045A0` | `gLastWrittenSector` | u16 |
| `0x030045A4` | `gLastSaveCounter` | u32 |
| `0x030045A8` | `gLastKnownGoodSector` | u16 |
| `0x030045AC` | `gDamagedSaveSectors` | u32 |
| `0x030045B0` | `gSaveCounter` | u32 |

IWRAM，法语版构建。加载后`gLastWrittenSector`描述了所采用的槽位。
<a id="the-band-the-sessions-own-save-will-not-write"></a>
### 会话自己保存的乐队不会写入

完整保存会分配前一对，前进 `gLastWrittenSector` 和 `gSaveCounter`，然后将递增计数器选择的带写入 [save.c:144-153]。以成功消息结束的礼物会话可保存 [mystery_gift_menu.c:1379]；以任何其他结果结尾的结果将返回到菜单而不保存。当会话成功结束时，写入 `gSaveCounter % 2` 现在选择的频段：会话的保存写入另一个频段。待采纳的板块位于波段位置 13，柜台为 `gSaveCounter + 2`，比交易日的
`gSaveCounter + 1`。第 13 位的 ID 是 `(13 - gLastWrittenSector) % 14`，源自游戏机。
<a id="composing-a-sector-from-a-ram-snapshot"></a>
### 从 RAM 快照组成一个扇区

保存例程在保存时进行序列化，因此 SaveBlock2 的实时内容与其写入的内容不同。每个校验和都通过，并且 `gDamagedSaveSectors` 在以下两种情况下都保持 0：

- 加载时重新滚动加密密钥。 `LoadGameSave` 恢复块，创建新密钥，将其应用于 RAM 中的每个加密字段，并将其存储在 SaveBlock2 [decomp:src/load_save.c:126-128] 中。由 RAM 和未受影响的 SaveBlock1 组成的 SaveBlock2 读取的金额为 `raw ^ flash_key ^ ram_key`。加密集[ApplyNewEncryptionKeyToAllEncryptedData]：训练塔时间、游戏统计数据、SaveBlock2 中的袋子数量和浆果粉、金钱和硬币。
- 保存的地图视图，在 SaveBlock2 `+0x898` 处为 420 字节（210 u16 元图 id，`0x03FF` 空白），仅在保存时填充，并且在 RAM 中为零；一个组合的扇区将整个世界绘制成一个空白网格。

正常的保存会同时写入所有 14 个扇区，因此密钥和密文会一起移动；部分写入必须保留这一点。
<a id="reading-flash-a-64-kib-window-over-a-128-kib-chip"></a>
### 读取闪存：128 KiB 芯片上的 64 KiB 窗口

`swi 0x48`对芯片进行线性寻址。来宾负载在 `0x0E000000` 处看到 64 KiB 孔径，1 Mbit 部分作为两个组到达它：

    sector N is bank N / 16 at 0x0E000000 + (N % 16) * 0x1000
 孔径别名上方的地址：`0x0E01E000`（扇区 30）读取 `0x0E00E000`，所选存储体的扇区 14，通常为零。从扇区计算银行和窗口。选择银行是游戏自己的四个商店[decomp：src / agb_flash.c SwitchFlashBank，`0x081E0C74`，七个指令，无循环，无`REG_WAITCNT`]，内联所以一个防火墙不进行ROM调用：

    strb 0xAA -> 0x0E005555 ; strb 0x55 -> 0x0E002AAA ; strb 0xB0 -> 0x0E005555 ; strb bank -> 0x0E000000
 读取为字节宽度；闪存总线是8位的。

`ReadFlash` 的一个持久影响，`REG_WAITCNT` 的 SRAM 字段设置为 3 (`WAITCNT_SRAM_8` [decomp:src/agb_flash.c:149])，在启动后已经就位：`AgbMain` 清除它
[main.c:143]，引导保存加载调用`ReadFlash` [intro.c:1006]，每个闪存例程写入3（`gFlash->wait[0]` [agb_flash_mx.c:28, agb_flash_le.c:28]）。

切勿将传出消息指向闪光灯。 header 和 body 以不同的宽度读取窗口：

|步骤|代码|负载|它读了什么|
|---|---|---|---|
|头 CRC | `CalcCRC16WithTable` [mystery_gift_link.c:166] | `ldrb` | flash：`0xDEC2`是物理`0x1BC00..0x1BFFF`的CRC，`0x1E000..0x1E0FB`的`0x5907`（选择了bank 1）|
|身体| `Rfu_InitBlockSend` 将每个 252 字节或更少的块复制到 `gBlockSendBuffer` [link_rfu_2.c:1357] 和 `memcpy` `0x081E44F4` | `ldm`，一个字，当源和目标字对齐且剩余 16 字节或更多时 |其他字节：字节对 `01 cb`、`10 3a` 和 `04 3a` 的运行，对于 `0x0E01BC00` 和 `0x0E01E000` 相同 |

正文 CRC 失败，主机将其丢弃，礼品菜单挂起，且 RFU 链路接通。主体字节从何而来尚不清楚。 `build_memory_dump` 及其两个兄弟姐妹拒绝任何接触 `0x0E000000..0x0FFFFFFF` 的跨度。 `flash-read` 将扇区复制到 EWRAM 中
`ldrb` 并发送副本，准确返回扇区。
<a id="changing-one-field-of-a-real-save"></a>
### 更改真实保存的一个字段

`flash-patch` 读取真实保存写入的扇区，更改一个字段并将其写回，因此密钥和映射视图保持一致。一次编辑是两个部分：

    A   the target id's sector: patch the field, recompute the checksum over the id's own chunk,
        set the counter to gSaveCounter + 2
    B   the sector at band position 13: set its counter to gSaveCounter + 2 and nothing else, not
        even the checksum, because +0xFFC is outside the summed data area
 加载程序占用该带（旧计数器处有 12 个扇区，新计数器处有 2 个扇区），因为所有 14 个 id 均有效，并且最后一个有效扇区携带较高的计数器。玩家名`flash-patch`仅改变扇区A的字段和校验和以及扇区B的计数器；负载采用没有坏校验的乐队，金钱和主世界不变，钥匙副本和地图视图是游戏编写的。
<a id="the-chain-end-to-end"></a>
### 链，端到端

在模拟游戏机上测量：缓冲区脚本从实时全局变量中组成一个扇区，`swi 0x48` 写入它，游戏的下一次保存提交图像，下一次加载采用带
`gDamagedSaveSectors` 干净。交付的模式（与加载程序的预测试模式不同，后者在任何地方都没有出现）在 EWRAM 中读回，在两个站点中的每一个站点上读回 500 个连续字。
<a id="reading-the-save"></a>
# 读取保存的内容

神秘礼物会话读取实时保存：里 ID，以及每个队伍宝可梦的 PID、IV 和性格。没有写任何东西，也没有卡易手。主机日志解码`save-dump`SaveBlock2 从偏移量 0 开始（名称、性别、TID、SID、播放时间）或 SaveBlock1 覆盖0x38（每支队伍宝可梦的性格，IVs和EVs）通过`pokeldn.frlg.save.readout`，和一个`trainer-id-probe`回答为 TID 和 SID。
<a id="trainer-id-and-secret-id"></a>
## 训练家ID和里ID

SaveBlock2 偏移量 0 保存玩家姓名、性别、32 位训练家 ID 和游戏时间 [global.h:327]。下半部分是训练家卡上的TID；高半部分是里 ID，没有显示并且没有链接消息发送。

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/frlg_mg_host.py --live --keys PROD_KEYS \
        --buffer-script save-dump --dump-block sav2 --dump-size 64 --dump-file dump.bin

    ./.venv/bin/python tools/frlg/dump_read.py dump.bin --block sav2

    dump.bin: 64 bytes from sav2 + 0x0
      playerName    'PLAYER'
      gender        boy
      trainerId     0x12345678  TID 22136  SID 4660
      playTime      12h 34m 56s
 与训练家卡不一致的 TID 意味着读取错误。
<a id="the-party"></a>
## 队伍

SaveBlock1 0x34 是 `playerPartyCount`，然后 `playerParty[6]` 位于 0x38，每个 100 字节 [global.h:772]：6 个 604 字节。

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/frlg_mg_host.py --live --keys PROD_KEYS \
        --buffer-script save-dump --dump-block sav1 --dump-offset 0x34 \
        --dump-size 608 --dump-file party.bin

    ./.venv/bin/python tools/frlg/dump_read.py party.bin --block sav1 --offset 0x34

    party.bin: 608 bytes from sav1 + 0x34
      playerPartyCount 5
      slot 1: PIKACHU   Lv25 nick='PIKACHU' OT='PLAYER' PID=0x00000019 Hardy   IVs=[10,20,30,15,5,25] checksum ok
      slot 2: ...
（示例值。）

IV 读取 HP、ATK、DEF、SPE、SPA、SPD。异色列将每个mon的PID与其自己的OTID进行比较。每个槽位上的`checksum ok`表示真正的队伍。 Party mon 存储为 `.pk3`/`.ek3` 存储它们 (`pokeldn.frlg.save.mon`)：0x20 处的 48 个字节与 `PID ^ OTID` 进行异或，这四个子结构按 `PID % 24` 排序。

SaveBlock1 保留上次保存时的队伍（`SavePlayerParty` [load_save.c:160]，参见
`--create-mon-append`）。对于两个测量盒上的实时队列转储 `gPlayerParty`、0x02024280：

    --buffer-script memory-dump --dump-address 0x02024280 --dump-size 600
 切勿在运行之间携带绝对保存块地址； `save-dump` 使指针焕然一新。 IWRAM和`gRngValue`位于[随机数生成器](frlg_rng.md)上。
