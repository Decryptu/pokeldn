<a id="mystery-gift-files"></a>
# 神秘礼物文件

`.pokegift` 文件存储火红／叶绿或剑／盾或 FRLG ARM 游戏机的完整神秘礼物分布及其目标游戏和本地记录。
<a id="desktop-app"></a>
## 桌面应用程序

“游戏 → 神秘礼物”为每个游戏提供一个工具，包含三种礼物选择方式，《剑／盾》为四种。两个游戏共用一个构建器，各游戏模块提供预设和表单（`pokeldn/frlg/gift/builder.py`、`pokeldn/swsh/gift_builder.py`，在 `pokeldn/app/gift_builder.py` 绑定）。

| 模式 | 发送内容 |
|---|---|
| 使用预设 | 内置礼物；FRLG 的神奇卡片、神奇新闻和主机代码以参数形式传给启动器 |
| 官方活动 | 真实的《剑／盾》活动卡片（[官方活动卡片](swsh_gift.md#official-event-cards)），按自建礼物的方式编译 |
| 自行构建 | 表单在开始时编译成 `session/gifts/<tool>.pokegift`，以 `--gift-file` 传入 |
| 打开文件 | 共享的 `.pokegift`，或《剑／盾》的 `.wc8` |

FRLG 的游戏增强功能由常驻钩子实现（[`install-resident`](frlg_rom.md#install-resident)）。可以同时勾选多个，它们作为一条链运行（[同时运行多个钩子](frlg_rom.md#several-hooks-at-once)）。各项设置转换为启动器的 `--resident-param` 参数；面板显示已勾选组合占用主机 1024 字节空间中的多少字节。

| 增强功能 | 设置 | 参数 |
|---|---|---|
| 游戏加速（`turbo-lite`） | 1 至 4 倍速；地图场景、对战或两者；始终启用或按住 R、B、Select 时启用；加快文字显示 | `field` 和 `battle` = 倍速 - 1，3 倍速起使用 `budget=228`，以及 `hold`、`extra=4` |
| 穿墙 | R、B 或 Select | `hold` |
| 异色倒计时 | 减速按钮；减速至 1/2、1/4 或 1/8 | `slow`，`slow_frames` 为 1、3 或 7 |
| 不遇野生宝可梦、显示领队个体值、宝可梦跟随 | 无 | |

不提供 L：只有 R 的帮助系统开关有可由钩子抑制的标志。“保存增强功能供以后使用”发送 `save-write --resident` 而非 `install-resident`，将组合写入 `filler_B20` 并在同一会话安装。超过一轮 `install-resident` 会话容量（876 字节）的组合，以及跟随功能，始终经由存档安装。“由妈妈恢复增强功能”绑定妈妈的加载器，重启后与妈妈对话即可安装存档中保存的组合。再次发送增强功能会替换运行中的组合。应用在保存选项旁和“发送前”区域显示恢复步骤，包括必须保存的组合。预设名称与说明会自动换行，以完整显示操作指引。`tests/test_gift_builder.py` 对全部十二种卡带，逐一通过启动器发送每种增强组合及各项设置进行检查。

“读取存档”可读取训练家 ID（TID）、秘密 ID（SID）、训练家信息、游戏时间，以及上次保存队伍的性格、个体值和努力值。结果显示在会话日志中；两个转储预设还会把读取的数据写入“已接收”。该分组说明通常隐藏的 SID、六项各为 0 至 31 的个体值，以及训练获得的努力值。这些读取不改动存档和神奇卡片（[读取存档](frlg_rom.md#reading-the-save)）。

原生 `.wc3` 和 `.wc8` 扩展名优先选择对应游戏的二进制读取器，再检测 JSON。WC8 的二进制标记可能以 `{` 开头，但仍属于原生记录。`.pokegift` 文件使用 JSON 读取器；未知扩展名若以 JSON 左花括号开头，也可包含共享礼物。

“自定义”把预设复制到表单。FRLG 卡片预设仅在表单能表达所有步骤时提供该选项：不带条件的宝可梦、道具、蛋、野生对战和消息阶段，不含事件脚本或来访训练家。《剑／盾》的每个预设都可表示为表单状态。

FRLG 表单可构建神奇卡片、神奇新闻或主机代码。

| 组成部分 | 内容 |
|---|---|
| 卡片 | 标题、副标题、四行文字、图标种类、1000 至 1019 的卡片 ID、是否可重复接收及分享 |
| 派送者 | 任意宝可梦中心的派送员、玩家家中的妈妈，或真新镇南部的男子 |
| 步骤 | 宝可梦（种类、等级、持有物、四个招式）、道具及数量、蛋、野生对战、消息 |
| 新闻 | 标题、最多十行文字、新闻 ID |
| 主机代码 | ARM 源码或预构建的 `.bin`、目标卡带版本、预期返回值、返回字节数 |

每个步骤都是独立的派送阶段，因此队伍或背包满时只停在当前步骤，玩家重试时只领取剩余部分。派送员以外的角色通过 `initramscript` 绑定保留这些步骤；绑定期间不会显示卡片。绑定脚本没有领取标志，该角色每次都会执行这些步骤，直到其他礼物替换绑定。种类使用卡带内部编号（`pokeldn/frlg/save/species_names.py`）。卡片和新闻为全部四种卡带编译；主机代码可以为全部四种或选定的一种编译。

PATH、Homebrew 目录或 Arm 的 Windows 安装目录中存在 `arm-none-eabi-as` 时，使用它汇编主机代码；否则表单接受预构建的 `.bin`，并显示适用于当前系统的汇编器安装命令：

| 系统 | 命令 |
|---|---|
| macOS | `brew install arm-none-eabi-binutils` |
| Fedora | `sudo dnf install arm-none-eabi-binutils-cs` |
| Debian、Ubuntu 及其衍生发行版 | `sudo apt install binutils-arm-none-eabi` |
| Windows | `winget install Arm.ArmGnuToolchain` |

其他 Linux 发行版会显示 Arm 下载页面。Fedora 44 和 Ubuntu 24.04 的软件包可把默认模板汇编为 `01 00 a0 e3 1e ff 2f e1`。“离线检查”在模拟主机上执行一次代码（`pokeldn/frlg/rom/custom_code.py`），显示返回值和字节。开始运行及保存文件前也会执行同样检查：发生异常或始终不返回 1 的代码会被拒绝。

剑／盾表单可生成宝可梦（可指定或随机性格、选择超极巨化）、蛋、最多六种背包道具、官方服装、对战点数或金钱，并设置卡片 ID。宝可梦、蛋、道具、服装和对战点数写入实机剑已列出并领取过的记录字节（[剑／盾神秘礼物](swsh_gift.md#a-card-delivered-to-a-retail-console)）；皮卡丘预设逐字节等同启动器默认记录。服装取自官方服装卡片的配对（[服装](swsh_gift.md#clothing)），每种玩家性别最多六件。PKHeX 拒绝不支持超极巨化的种类设置该标志。

“发送前”列出主机会收到什么、何时执行，以及礼物适用的卡带。“保存礼物文件”把所选礼物写成 `.pokegift`，无需开发板或 Switch 密钥。FRLG 预设使用启动器自己的构建器，因此文件保留它构建的所有卡带变体。礼物握手时按主机游戏代码选择变体；文件中没有相应卡带时，在发送礼物数据前拒绝。预设的卡片 ID 位于“高级”选项卡（`--flag-id`，1000 至 1019）。

应用导入时不修改礼物文件，文件仍保留在所选路径。

已在实机上从打开的文件传送：法语版《火红》的时拉比卡片和主机代码文件，以及《剑》的皮卡丘卡片。由表单构建的主机代码返回了存档中的训练家 ID。

<a id="command-line"></a>
## 命令行

两个礼品发射器均接受 `--gift-file FILE`。 剑／盾保留`--record`作为别名。
`--export-gift FILE` 在使用收音机之前保存所选的礼物并退出。

```bash
./.venv/bin/python bin/frlg_mg_host.py --gift celebi --export-gift celebi.pokegift
./.venv/bin/python bin/frlg_mg_host.py --news berry --export-gift news.pokegift
./.venv/bin/python bin/swsh_gift_host.py --species 25 --level 25 --export-gift pikachu.pokegift
./.venv/bin/python -m pokeldn.gifts inspect celebi.pokegift
```
 FRLG 礼品文件一起定义了卡旗 ID、脚本、问卷和拒绝消息。诸如 `--flag-id`、`--questionnaire` 和 `--hunt-*` 之类的有效负载覆盖将被拒绝。无线收发设备、训练家身份和卡带选择选项仍然是会话设置。
<a id="console-code"></a>
### 控制台代码

导出内置的发票及其配置的字节和响应设置：

```bash
./.venv/bin/python bin/frlg_mg_host.py --buffer-script save-dump --dump-size 64 \
  --export-gift save-dump.pokegift
```
 作者可以使用显式的卡带目标打包自己的原始 ARM 代码：

```bash
arm-none-eabi-as -march=armv4t -mcpu=arm7tdmi -o payload.o payload.s
arm-none-eabi-objcopy -O binary -j .text payload.o payload.bin
./.venv/bin/python -m pokeldn.gifts import --game frlg --code payload.bin \
  --build BPRF --name "Custom payload" --expect 66 -o custom.pokegift
```
 最小的 `payload.s` 将 66 写入响应参数并在一次调用中完成：

```asm
.syntax unified
.arm
.text
.global _start
_start:
    mov r3, #66
    str r3, [r0]
    mov r0, #1
    bx lr
```
 代码必须是位置独立的 ARMv4T、字对齐且最多 1024 字节。游戏机通过`r0 = &param`、`r1 = gSaveBlock2Ptr`和`r2 = gSaveBlock1Ptr`；它每帧调用一次 SAT，直到返回 1。执行合约请参见[控制台代码](frlg_rom.md)。没有
`--expect`，接受任何返回的参数。重新指向字节缓冲区的响应的栏在打包时使用 `--dump-size N`。

共享 `.pokegift` 文件。收件人在 FRLG、神秘礼物上打开它，或者用
`--gift-file custom.pokegift`。 `--dump-file PATH` 选择主机写入返回转储的位置。在发送代码之前强制执行卡带变体。包装验证结构和尺寸；作者必须在实时运行之前使用 `buffer_script.emulate_repeating` 离线执行新的有效负载。文件哈希并不能证明本机代码返回或保持保存完好无损。
<a id="native-formats"></a>
### 原生格式

转换器支持《剑／盾》WC8 记录、FRLG 的 `.wc3` 文件，以及 `pokemon-gen3-mysterygift-tool` 使用的 FRLG 配对文件。`.wc3` 或 `.wc8` 也可直接在应用的“打开文件”和 `--gift-file` 中打开。

若 FRLG 脚本的可达代码不含绝对地址，便可使用同一卡片布局适配各卡带：跳转和文字由相对其自身 `setvaddress` 的 `vgoto`/`vmessage` 操作数指定 [scrcmd.c:171]，道具经由 `callstd` 发放。包含 `goto`、`call`、`message`、`callnative` 或其他绝对指针的脚本只适用于一种卡带，需要 `--build`；此类 `.wc3` 不允许直接打开。

```bash
./.venv/bin/python -m pokeldn.gifts import --game swsh --record event.wc8 -o event.pokegift
./.venv/bin/python -m pokeldn.gifts import --game frlg --wc3 "FL - Item AuroraTicket (FRE).wc3" -o aurora.pokegift
./.venv/bin/python -m pokeldn.gifts import --game frlg --card WonderCard.bin \
  --script Script.bin --name "Event gift" -o event.pokegift
./.venv/bin/python -m pokeldn.gifts export celebi.pokegift --build BPRF --out-dir native-gift
./.venv/bin/python -m pokeldn.gifts export celebi.pokegift --wc3 --build BPRJ --out-dir native-gift
./.venv/bin/python bin/frlg_mg_host.py --gift celebi --console-build BPRJ --export-gift celebi.wc3
```

保存路径以 `.wc3` 或 `.wc8` 结尾时，会在 `--export-gift`、“保存礼物文件”及 `pokeldn.gifts.save` 中写入对应原生文件，而不是 `.pokegift`。`.wc3` 保存一种卡带的卡片与脚本；未指定 `--build` 时，礼物的每种变体必须具有相同字节。变体不同时，GUI 会询问要导出的卡带。`.pokegift` 保留所有语言变体。`.wc3` 元数据块除重复卡片图标外全部写零。游戏可接受的每个国际版图库文件，经导入再导出后，卡片、脚本和图标字节均保持不变。

国际版 `.wc3` 长度为 1420 字节（`0x58C`）：

| 偏移 | 大小 | 内容 |
| --- | --- | --- |
| `0x000` | 336 | 卡片 CRC16、2 字节填充、332 字节的 `struct WonderCard` |
| `0x150` | 80 | 存档侧的卡片元数据；不读取 |
| `0x1A0` | 1004 | CRC16、2 字节填充、`struct RamScriptData`（魔数 51、地图组、地图编号、对象 ID、995 字节脚本）、1 字节填充 |

Project 宝可梦 的 EventsGallery 中全部 54 个国际版文件，脚本 CRC 覆盖含填充字节在内的 1000 字节；游戏自身覆盖 999 字节 [script.c:488]。导入接受两种 CRC。导入时的 `--icon N` 或应用“打开文件”中的“卡片图标”，会把卡片的 `iconSpecies`（卡片偏移 2）设置为 0 至 411 的内部种类 ID；0 表示不显示图标 [mystery_gift_show_card.c:466]。

日语版 `.wc3` 文件为 1252 字节（`0x4E4`）：卡片结构 164 字节，CRC 包装 168 字节，元数据始于 `0x0A8`，1004 字节的 RAM 脚本结构始于 `0x0F8`。直接导入时，日语文件适用于 `BPRJ` 和 `BPGJ`；国际版文件适用于十种拉丁字母语言卡带。显式指定的 `--build` 必须与卡片布局一致。图库中标志 ID 为 4 至 8 的调试卡片被拒绝：派送员只发放标志 ID 为 1000 至 1019 的礼物 [mystery_gift.c:241]。首次进入名人堂之后，极光船票和神秘船票不再生效（[极光船票与神秘船票](frlg_gift.md#the-aurora-and-mystic-tickets)）。

FRLG 配对文件包含一张 336 字节的国际版卡片或 168 字节的日语版卡片，以及 1004 字节的 RAM 脚本结构。导入检查两处 CRC 和脚本未绑定的神秘礼物头部。原生配对格式无法携带印章、来访训练家、神秘事件脚本、问卷条件或神奇新闻；分发含有这些额外内容时，拒绝导出为配对格式。`.pokegift` 可将它们一并保留。

<a id="version-2"></a>
## 版本 2

该文件是 UTF-8 JSON，具有五个必填字段：

|领域 |价值|
| --- | --- |
| `format` | `pokeldn.gift` |
| `version` |整数 `2` |
| `game` | `frlg` 或 `swsh` |
| `name` |非空显示名称，最多 180 个字符 |
| `variants` |对象将目标代码映射到本机数据和选项|

每个变体都有 `data` 和 `options` 对象。 `data` 中的组件具有 `hex`（编码为十六进制的本机字节）和 `sha256`（其小写 SHA-256 摘要）。 JSON 字段顺序没有意义。导出对确定性文件的字段进行排序。

|游戏|变体键 |数据组件|选项|
| --- | --- | --- | --- |
| FRLG 礼品 |支持的卡带代码 | `card`、`ram_script`、`stamp`、`activation_script`、`install_activation_script`、`trainer`、`news`、`mevent` | `questionnaire`，`denied_message` |
| FRLG 游戏机代码 |支持的卡带代码 | `buffer_code`, `buffer_lead_1`.. |下面的响应设置 |
| 剑／盾 | `swsh` | `wc8` |无 |

FRLG 卡变体具有相同的旗帜 ID 和礼品类型。 神奇新闻和游戏机编码每次独自旅行。捕获、密钥、文件系统路径和会话计时不属于此格式。

FRLG 游戏机代码变体只有一个 `buffer_code` 组件，并且在与 `buffer_lead_1`、`buffer_lead_2` 等相同的会话中，在其之前运行最多 8 个有效负载，编号无间隙（保存中保存的驻留钩子将 `filler_B20` 与它们一起写入，然后安装它）。其可选响应设置为 `buffer_expect`（32 位无符号整数或 `trainer-id`）、`buffer_dump_size`、
`buffer_dump_blocks`、`buffer_dump_address`、`buffer_dump_addresses` 和 `buffer_decode`。转储大小为每个块 1 到 1024 字节，最多 32 个块；分散转储为每个块命名一个地址。解码器名称来自现有的响应解码器。转储输出路径和本地 ROM 比较路径保留在主机上，并且从共享文件中排除。

读者还接受包含卡片、新闻或 WC8 的版本 1 文件。导出使用版本 2，添加了游戏机代码和整数响应设置。版本 1 读者拒绝版本 2 文件。

读者拒绝未知的版本、字段和目标代码、重复的 JSON 字段、无效的哈希值、大于 256 KiB 的文件、无效的本机大小和无效的组件组合。 FRLG 验证还检查卡字段、训练家校验和和神秘事件终止。 剑／盾传送在打开收音机之前仍然需要共享PKHeX礼物验证。

哈希检测损坏的字节。它们不会验证分发者或证明导入的 FRLG 脚本可以安全执行。本机脚本导入保留指令并需要明确的卡带目标。
<a id="implementation"></a>
## 执行

`pokeldn.gifts` 拥有信封、验证发送、读取器、写入器和转换器。游戏特定的编解码器位于 `pokeldn.frlg.gift.file` 和 `pokeldn.swsh.gift_file` 中。共享应用程序适配器调用启动器自己的构建器； GUI 对这两款游戏都使用一个选择器和导出控制。

FRLG 文件适配器构建现有的 `MysteryGiftDistribution`，包括其卡带选择和拒绝路径。剑／盾适配器提供现有的WC8广告生成器。无线协议和书签布局保持不变。
