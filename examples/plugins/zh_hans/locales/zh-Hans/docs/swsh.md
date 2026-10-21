
<a id="sword-and-shield"></a>
# 剑和盾

宝可梦剑和盾通过通用的发布/订阅框架，直接在 Pia 上运行带有协议缓冲区消息的 C++ 游戏代码。

静态读数来自 盾 1.3.2 EUR 映像（`01008db008c2c000`，更新 NCA，SDK 7.7.0.0）；测量值是针对法语版《剑》 1.3.2 的。两者共享他们的网络代码；存在差异的地方会被标记出来。

零售 剑 已与 pokeldn 进行过两种角色的交易（[主持交换](swsh_trade.md#hosting-a-trade)）。

|页 |内容 |
|---|---|
| [卡带和会话](swsh_session.md) |键、图像、Pia 4、与第一个应用程序数据的关联 |
| [同步框架](swsh_protocol.md) |消息 ID、内容、持有者、路由、队列 |
| [交易](swsh_trade.md) |交换屏幕、盒子状态机、确认梯 |
| [神秘礼物](swsh_gift.md) |神秘礼物菜单的本地无线分支|

<a id="sources"></a>
## 来源

ID、偏移量和地址来自 盾 的 `main` 或空气，除非某个部分指定了客户端。
`pokeldn/swsh/trade.py` 中的 `SYNC_ANSWERS` 是 `andyjusa/nxldn-lab` 对游戏机到游戏机捕获的读取（消息 97 和 60000 与 pokeldn 的字节逐字节匹配）。四个客户端讲LAN模式，
`kwsch/PokePiaSWSH`、`lincoln-lm/swsh-lan-client`、`andyjusa/nxldn-lab`、`Slashcash/PSD`，从Pia站握手上去；没有一个涵盖 LDN 或主机迁移。

<a id="the-field-scripts"></a>
## 字段脚本

`bin/script/amx/*.amx`（1.3.2 中的 953）是具有 64 位单元的 Pawn 3.x：魔术 `0xF1E1`，版本 10，标志 `0x1C`（紧凑代码，睡眠，无检查）。紧凑编码：每字节 7 位，高位组在前，符号位于第一个字节的第 6 位。非分支单参数操作码也打包为
`(param << 32) | op`，按 3.x 顺序从 162 开始编号（`LOAD.pri` 162、`LOAD.S.pri` 164、`PUSH.C` 188、`PUSH.S` 190、`STACK` 191、`ADD.C` 197、`ZERO.S` 200、`EQ.C.pri` 201、`INC.S` 204、`HALT` 210、
`PUSH.ADR` 212); `halt 0` 在偏移 0 处将其引脚。

本机是十二个字节，`u64 0` 和 `u32` 名称哈希，由 `amx_Register` (`0x0066d970`) 解析：

    h = 0; for each byte c: h = (h * 0x83) ^ c        (32-bit)
 绑定表是 `.data` 中的 `(name, function)` 对，每个模块一个（吸气剂，例如
`0x014aea00`)：777 个名称，使用了 513 个哈希值中的 512 个。商品：`ItemAdd` (`0x014acea0`)、`ItemSub` (`0x014acf40`)、`ItemGetNum`、`ItemAddCheck`、`ItemGetCategory`、`GetPocketNumberFromItemNumber_`。变量：`WorkGet`/`WorkSet`（散列的 64 位密钥）、`TempWorkGet`/`TempWorkSet`（指示在脚本恢复之前 UI 填充）。每个参数的调用是 `PUSH`，从右到左，然后
`SYSREQ.N native, bytes`。

<a id="unresolved"></a>
## 未解决

- [玩家档案](swsh_protocol.md#the-player-profile)：宝可梦露营会话中，角色采样状态 3 和 4 各代表哪种角色（`StateCreateSession`、`StateConnect`）。`a_wr0301` 表示王冠雪原野外区域是根据编号推断的；在该区域采集一个信标可确认。
- [对战竞技场](swsh_protocol.md#the-battle-stadium-block)：`0x01430670` 为已存储队伍记录读取哪个存档块，以及 `v1/validate` 签名覆盖 `+0x36` 前，存档队伍描述符的 `+0x30..+0x135` 保存什么（`0x015039f0` 后 `[sp+0x28]` 中的条目）。
- 《剑》和《盾》的差异：二进制分析来自《盾》，实机为《剑》；[会话常数](swsh_session.md#taking-a-seat)适用于两者。《剑》检查卡片版本掩码位 0 的结论来自《盾》代码：条件为 `1 << (v == 0x2D)`，`0x007d4270` 的 31 处调用中有 11 处同时比较 `0x2C` 和 `0x2D`；PKHeX 的 `RestrictVersion`（1 为剑、2 为盾、3 为两者）也支持此结论。两份实机《剑》快照在 MyStatus `+0xA4` 处包含 `0x2C`。《剑》自身的 `0x007d4270` 和通信 ID 常量尚未读取。
- [神秘礼物](swsh_gift.md#what-the-menu-refuses)：实机是否像模拟运行的《盾》一样，将种类不在游戏中的类型 1 礼物接收为名为“Egg”的坏蛋，以及该蛋孵化或交换时的行为。
