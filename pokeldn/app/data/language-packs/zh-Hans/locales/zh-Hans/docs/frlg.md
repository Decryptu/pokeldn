
<a id="firered-and-leafgreen"></a>
# 火红和叶绿

Switch 版《火红／叶绿》是在模拟器中运行原版 GBA ROM，因此叠加了两层连接协议：

| 层次 | 所属组件 | 对应文档 |
|---|---|---|
| LDN 与 Pia | 属于模拟器，与其他 Switch 游戏共用 | [无线通信层](ldn.md) |
| GBA 连接层：RFU 帧、席位和区块发送 | 属于 ROM | 本组文档 |

[pret/pokefirered](https://github.com/pret/pokefirered) 是 `REVISION >= 0xA` 下整个游戏层协议的权威参考。从两台主机读取的卡带头信息为：软件版本 `0x0A`，游戏代码 `BPRF`（法语版《火红》）和 `BPGF`（法语版《叶绿》）。主持端还会为英语、德语、意大利语、西班牙语和日语版本选择经过测量的 ROM 与 RAM 地址，共支持十二种卡带。玩家在“朋友”列表中选择 pokeldn 后，神秘礼物功能根据卡带代码检测语言；基础页面在版本旁显示结果。新增语言版本已通过离线 ROM 和 mGBA 检查，实机覆盖范围见[实机验证](frlg_rom_map.md#retail-verification)。参见[卡带地址映射](frlg_rom_map.md#the-international-revision-0x0a-cartridges)。

如果主机在关联并完成 Pia 会话建立后约三秒离开，原因可能是关联响应未包含 6、9、12 Mbit/s（[frlg_link.md](frlg_link.md) 中的广播速率集合）；缺少 Pia 类型 2 的 Join Response 也会出现相同现象。

<a id="what-works"></a>
## 已验证的功能

两种卡带均已在实机验证游戏提供的全部活动：双向神秘礼物、主机端和加入方交换、完整联合房间功能（含连接对战）、神奇新闻、连接俱乐部斗兽场，以及来访的对战塔训练家。

通过礼物链接的两个解释器，游戏机还运行发送给它的代码：它的内存读取和写入，它的ROM映射到它运行的构建的命名函数，它自己的函数用八个参数调用，以及由它自己的`CreateMon`构建的主机选择的宝可梦，并留在玩家的队伍中。 RNG是端到端封闭的；每次有针对性的异色遭遇需要按 A 键。

来宾到包装器的边界被解码（[游戏机上的代码](frlg_rom.md#where-the-boundary-stands)）：来宾的一个存储通过区域的支持是字节精确和常量值的，植入的指针的消费者从中读取他们的目标
`main` 在静态地址处的自身数据以及系统调用存储到组件中的数据将作为计数和 GBA 地址读回，每个地址都会进行边界检查。包装器自己的扫描管道被解码到其第一阶段（[包装器自己的扫描管道](frlg_rom.md#the-wrappers-own-scan-pipeline)）：扫描结果、消耗循环和父节点候选列表都是固定形状和有界的，并且单个长度路径（站名，最多 `0x40`）被夹在其调用者处。
<a id="pages"></a>
## 相关页面

|页 |内容 |
|---|---|
| [链接协议](frlg_link.md) | RFU链路层、座位屏障、联合房间、聊天、链路战斗和连接俱乐部斗兽场|
| [神秘礼物](frlg_gift.md) | 礼物会话、礼物制作、神奇新闻、来访训练家及受阻的无线通信路径 |
| [游戏机上的代码](frlg_rom.md) | 神秘事件虚拟机、原生 ARM 载荷，以及读取和写入当前存档 |
| [ROM 地址映射](frlg_rom_map.md) | 地址测量、四张函数表、种类表和法语 Easy Chat 词汇 |
| [随机数生成器](frlg_rng.md) | 读取和预测 `gRngValue`，以及定向遭遇的场景代码存根 |
| [叶绿](frlg_leafgreen.md) | 两种卡带的共享内容、实测偏移映射，以及用英语版构建辅助分析 |
| [主机实现](frlg_host.md) |交换和神秘礼物主机的组件边界|
<a id="the-two-cartridges"></a>
## 两种卡带

叶绿以分段恒定偏移量运行相同的代码；测量的对和边界位于[叶绿](frlg_leafgreen.md)上。切勿预测跨越无括号边界的地址。
<a id="rules-that-hold-across-all-of-it"></a>
## 贯穿所有内容的规则

- 分解的链接顺序是证据；其地址需要在卡带上测量。   `pokeldn/frlg/rom/rom_map.py`记录了每个地址是如何获得的。
- 发送前，载荷必须在 Unicorn 中离线运行（`buffer_script.emulate`、`emulate_repeating`，两台模拟主机）。出错或永不返回 1 的载荷会使神秘礼物菜单卡住；无限循环的场景代码存根会让整个游戏场景无响应。
