
<a id="messages-contents-and-routing"></a>
# 消息、内容和路由

Pia 之上的发布/订阅框架。消息由 u16 LE id、鉴别器字节、零字节和 protobuf 主体组成。

<a id="where-a-message-id-comes-from"></a>
## 消息 id 来自哪里

Low ids 来自 `0x01BBFFA0`、`{u64 handler slot, u32 0x402,
u32 id, u64 0}` 的 838 24 字节记录表，ids 1..880（97，ping 持有者，其中 110、120、130）。高id是基数加上偏移量； 20030 或 40040 永远不会作为常量出现，60000 是基数 + 0（41 个位点的 MOVZ）。

<a id="contents-and-holders"></a>
## 内容和持有人

每个内容注册三个持有者（注册商 `0x010ccd90` 内容 30、`0x010da7d0` 40、
`0x010d5150` 50)，将基数添加到其偏移量 `ldrh [content+0x372]` 并将每个传递给
`0x006daeb0(manager, &holder, flag)`：

    mov w9, #0x2710    id = 10000 + offset   holder 0x010dd910   flag 1
    mov w9, #0x4e20    id = 20000 + offset   holder 0x010d85f0   flag 0
    mov w9, #0x7530    id = 30000 + offset   holder 0x010d0980   flag 0
 40000 系列铸造得更低一层，40000 作为 MOVN：

    ldrb w20, [x0, #0x28]          the content offset, 30 / 40 / 50
    mov  w9, #-0x63c0              w9 = 0xffff9c40
    add  w24, w20, w9
    strh w24, [x20, #0x160]        40030 / 40040 / 40050
 没有监听器的支架会无声掉落（`0x010d81d0`：`ldr x8,[x0,#0x168]; cbz x8, out`）。安装：内容 30 `0x010ccc94`、`0x010ccca4`、`0x010ccf7c`；内容40 `0x010da6d0`，
`0x010da9bc`（清除`0x010dab10`）；内容 50 `0x010d50ac`、`0x010d533c`（清除 `0x010d5660`）。没有一个达到 40 或 50 的 20000 碱基持有者：20040 和 20050 是惰性的。

<a id="the-30000-holder"></a>
### 30000持有者

30000+偏移量持有者（`0x010d0980`，vtable GOT `0x02618620` = `0x02528100`，无RTTI）携带
`gflnet.p2p.framework.pb.SequenceDataHolder`：

    SequenceDataHolder    oneof message {
                            1 CancelAccepted        cancelAccepted
                            2 RequestCancel         requestCancel
                            3 RequestCancelAll      requestCancelAll
                            4 RequestForcedProceed  requestForcedProceed }
    CancelAccepted        { 1 int32 currentSeqNo; 2 bool  isForced    }
    RequestCancel         { 1 int32 currentSeqNo }
    RequestCancelAll      { 1 int32 currentSeqNo }
    RequestForcedProceed  { 1 int32 currentSeqNo; 2 int32 targetSeqNo }
 解析器 `0x006a7580`（标签 `0x0a`..`0x22`）； RequestForcedProceed 的 `0x006a65c0` 将其字段存储在 `+0x14`、`+0x18` 处。接收，插槽 8 `0x008b9590`，调用侦听器插槽（案例 - 1）
`[holder+0x168]` 通过 `0x0204c430`。

盾 1.3.2 仅构建 CancelAccepted：在 protobuf 代码 (`0x006a3000..0x006a8400`) 之外，没有任何内容调用其他构造函数 (`0x006a4b50`、`0x006a5730`、`0x006a6330`) 或其访问器。
`0x006a3db0` 有 21 个外部调用者：发送包装器 `0x008b7420` 和十个同步内容（`0x008b71a0`、`0x008b7700`、`0x008cfb10`、`0x008cfbe0`、
`0x00c06420`、`0x00c064f0`、`0x010763a0`、`0x01076470`、`0x010a2090`、`0x010a2160`、`0x010cf460`、
`0x010cf530`、`0x010d7760`、`0x010d7830`、`0x010dd0c0`、`0x010dd190`、`0x012a8390`、`0x012a8460`、
`0x012bec80`、`0x012bed50`）。零售行业从不携带案例 2 至 4；游戏机仍然对他们起作用（[内容40](swsh_trade.md#the-cancel-and-proceed-messages)）。内容40的实例，30040，端口0：

    RequestForcedProceed{c, c+1}   58750000 2204 08<c> 10<c+1>     c=0: 58750000 2204 0800 1001

<a id="the-three-trade-contents"></a>
### 三个交换内容

`0x010c9280` 构建会话：

    +0x120   content 30, the box exchange       ctor 0x010cca10, registers offset 30 at 0x010ce4f0
    +0x148   content 40, SyncSaveDataHolder     ctor 0x010da3f0
    +0x2b0   content 50, PokemonTradeDataHolder ctor 0x010d4d40
    +0x60    an event source, listeners in a vector at its own +0x60
    +0x68    own Pokemon        +0x70  theirs
    +0x90    a delegate to +0xb0: thunk 0x010cc250 -> box callback 0x010ca800(session, code, payload)
    +0x140   the trade state, 1..10            +0x144  the error code
    +0x418   send command 3 on the first frame  +0x419  the role bit that suppresses it
 内容的 init 注册其持有者并铸造其 40000 个 id：在交换（状态 3）和状态 4 决策 `0x01109320` 之后，内容 50 处于交换状态 1（`0x010d4d90`），内容 40 处于状态 6（`0x010da470`）。

<a id="the-routing-path"></a>
## 路由路径

    0x006a9a20   the sync pump, from the trade session update
    0x006db3b0   the poll: per registered entry, drain both streams of its kind (byte +8)
    0x006a8490   stream A: mesh port [pia+0xd0+kind*4], Pia protocol 0x7C
    0x006a84f0   stream B: mesh port [pia+0xd8+kind*4], Pia protocol 0x80
    0x006db9c0   drain: slot 0x78 fills (sender*, length) and the buffer at manager+0xf0
    0x006db620   dispatch: match the entry, call the holder's slot 8
    0x010d81d0   content 50's 10000-base holder: parse, call the listener's slot 0
    0x010d5e40   the listener: sender to station index, memcpy 0x158, invoke

<a id="the-application-header"></a>
### 应用程序标头

楼梯是 `struct.pack("<HBB", id, discriminator, 0)`，然后是主体，由 `0x006db840` 在 `manager+0x240f0` 构建（`strh w3`，来自 `manager+0x480f0`、`strb wzr` 的鉴别器）并解析为
`0x006db620`。鉴别器是一个生成计数器，`[content+0x370] = (+1) mod 255`（`0x008b6670`），推入`[manager+0x480f0]`；强制 CancelAccepted 将其置于内容 40 上（`0x006db470`、`0x010dcea4..0x010dcec8`）；注册商将其归零 (`0x010d53a0`)。没有强制CancelAccepted的一次交换的107个有效负载全部为零。

<a id="reading-the-registrations-live"></a>
### 现场阅读报名信息

    manager = read_u64(read_u64(main + 0x02616750))     0x006a9a70, the poll's caller
    count   = read_u64(manager + 0xD8)                  0x006db3dc
    array   = read_u64(manager + 0xD0)                  0x006db3e0
    entry i = array + i * 0x10                          0x006db3e4
    id      = holder's vtable slot 7, called at 0x006db740 (`ldr x8, [x8, #0x38]`)
 插槽 7 在此处返回 `[holder+0x160]`；其他地方解码其 `ldrh`。空闲屏幕上为空；就座链接交换增加了两个条目（在座位两秒内可见）； 神秘礼物不添加任何内容。

<a id="dispatch-gates-ports-and-senders"></a>
### 调度口、端口和发件人

条目为 16 个字节：持有者，种类位于 +8 (`w2`)，标志位于 +9 (`w3`，1 仅适用于 10000+偏移量)：

    id == holder->slot7()
    entry[8] == the drain's kind
    entry[9] ? header[2] == [manager+0x480f0] : no check
 类型是网状端口：0 表示内容持有者（20030、10050、ping），1 表示 40000 系列 (`0x006daf40(manager, &holder, 1, 0)`)。发送者是一个传输指针（`[sp+0x28]` in
`0x006db9c0`) 传递到 `0x010d5e40` 并由 `0x006b5850` 解析 (`mesh->GetStationIndex`,
0xfd 失败）；环回通过 `[[0x2616a30]]+0xf0`。 `Data.ownerId` 在 10050 上不起作用。

<a id="the-data-envelope"></a>
## `Data` 信封

`gflnet.p2p.sync.pb`, `data.proto`:

    1  uint32  syncId        the content offset       30 / 40 / 50
    2  uint32  elementId     the base                 10000 / 20000
    3  uint64  ownerId       the sender
    4  uint64  clock
    5  bytes   body          four bytes in a pair; a 344-byte PK8 in a 40050
 40000持有者监听者为`element+0x18`；其插槽 0，`0x006d59f0`，路由：

    [Data+0x14] == [listener+0x10]        syncId, the element's offset
    walk [listener+0x28] .. [+0x30]       sub-elements, 0x90 bytes each
      [Data+0x18] == [sub+0x62]           elementId, u16
      [Data+0x20] == [sub+0x68]           ownerId, u64
    sub->vtable at 0x48 (sub, body, len, [Data+0x28])     body and clock
    otherwise: ret                        dropped silently

<a id="sub-element-kinds"></a>
### 子元素种类

|善良|构造函数|虚拟表| `+0x88` 出生 |插槽9，接收：尺寸检查，存储到`+0x88` |
|---|---|---|---|---|
| 32 位 | `0x006d5c00` | `0x2512bc8` | 0 (`0x006d5ce0`) | `0x006d5f20`：4、`ldr w8` / `str w8` |
|对（相位）| `0x006d6160` | `0x2512c90` | `0xfc18fc18` (`0x006d6230`) | `0x006d6490`：4、`ldr w8` / `str w8` |
| 16 位 | `0x006d66d0` | `0x2512d58` | 0 (`0x006d67b0`) | `0x006d69f0`：2、`ldrh w8` / `strh w8` |

然后接收设置 `[sub+0x78] = clock` 和 `strh 0x0100 -> [sub+0x60]`（就绪字节 `+0x61`）；槽 7（哈希值）返回时钟。一个子元素为0x90字节；其构造函数采用元素 `x0` (`+0x80`)、elementId `w1` (`+0x62`)、ownerId `x2` (`+0x68`)、标志 `w3` （`+0x70`），通过`x8`返回。

同步元素 (`0x006d3f80`) 针对每个同步内容构建一次：`0x008b5c60`、`0x008cecb0`、
`0x00c05690`、`0x01075610`、`0x010a1230`、`0x010ce604` (30)、`0x010d6904` (50)、`0x010dc264` (40)、
`0x012a7530`、`0x012bdef0`。来自 `0x2512b28` 的 Vtable：

    element+0x00  0x2512b38   primary, 6 slots; 2, 3, 4 are the three constructors with w3 = 1
    element+0x08  0x2512b78   interface A: the 32-bit kind (thunk 0x006d5ab0)
    element+0x10  0x2512b90   interface B: the pair (0x006d5ac0), the 16-bit kind (0x006d5ad0)
    element+0x18  0x2512bb0   the router listener, slot 0 = 0x006d59f0
 造币厂 `0x006d44e0` 建立了四个频道，添加了 `[element+0x70..+0x78]` 中的每个电台：

|领域 |建造者 |尺寸|持有|
|---|---|---|---|
| `+0xb0` | `0x006cd890` | 0x130 | |
| `+0xd0` | `0x006d9ca0`，A | 0x38 |每站一个32位子元素，elementId 10000（`0x006d9d90`）：仲裁哈希|
| `+0xf0` | `0x006d29b0`，B | 0x40 |在 `+0x38` 处有一个 16 位子元素，elementId 20000，所有者 0：[共享值](swsh_trade.md#the-phase-is-the-elements-field)；每个站一对，elementId 20000 (`0x006d2aa0`)，16 字节 `{stationId, sub}` 条目 |
| `+0x110` | `0x006d7980` | 0x30 |仲裁哈希遍历列表 |

<a id="the-quorum-hash"></a>
### 仲裁哈希值

elementId 10000 上的四个字节，由 `0x006d7b40` 在 `element+0xa8` 构建：

    h = 0
    for sub in subs:
        if (!sub[+0x61]) { h = 0; break }        any station not ready -> zero
        h = crc32(le32(h + sub->slot7()))        slot 7 is the clock
 非零表示每个站都已准备好。 `0x0065de30`是`zlib.crc32`（在unicorn下检查）；
`0x0065df04`（聚`0x8005`）是CRC-16。行走列表 `element+0x110` 是 `0x006d48b0` 的 `+0x40` 的副本，其中 `+0x68` 的条目保持为零；它在交换中的长度是未读的。

该链覆盖发送者的 elementId 0 和 1（无所有者），然后是其自己的 elementId 20000。托管 剑 发送的每个非零哈希都匹配，例如内容 50：

    elementId 0, no owner      clock 2304   the host's own Pokemon (344 bytes)
    elementId 1, no owner      clock 2313   the partner's Pokemon, sent back
    elementId 20000, host      clock 2278   then 2338 after its pair moved
    crc32 chain                8ffa0f2e     then b3615e90
 时钟可以在发送消息之前更改。与主机的哈希相呼应的方加入完成了与托管剑的交换。

<a id="the-party-payload-on-protocol-0x84"></a>
## 协议 0x84 上的队伍恐惧

`ReliableBroadcastProtocol` 在三个片段中携带 3456 字节的交换快照，直到被确认；第三个是zlib（Pia标志0x10）：1404 + 1404 + 157 raw，最后膨胀到648。
`trade_payload.py` 拒绝任何其他总计。布局（如`kwsch/PokePiaSWSH`，
`lincoln-lm/swsh-lan-client`）：

    0x000  six PK8 records, party form, 0x158 each          -> 0x810
    0x810  u32   party count
    0x814  MyStatus, 272 bytes      TID/SID at 0xA0, trainer name at 0xB0
    0x924  TrainerCard, 456 bytes   trainer name at 0x00, save start date at 0x170
    0xAEC  the player profile, 266 bytes                     -> 0xBF6
    0xBF6  392 bytes, the Battle Stadium block; zero for Link Trade
    0xD7E  2 bytes of padding                                -> 0xD80 = 3456
 MyStatus 和 TrainerCard 是 PKHeX 保存块 (`Saves/Substructures/Gen8/SWSH/`)。

构建器 `0x0110c180`：`0x00784f90`（队伍）、`0x01424f10`（MyStatus）、0x1C8 memcpy（训练家卡）、`0x01124fa0`（个人资料）、可选块的 0x188 memcpy 或一个内存集。 `0x010fcff0`的呼叫者中，链接交换（`0x010967f0`）和密码匹配（`0x00bd80f4`，
`ChikaMatchingStateSession`) 通行无阻；对战体育场（`0x00b2d7d0`、`StateBtlSpot*Battle`、休闲、排名、竞技）通过一项。接收器 `0x0110cff0` 复制每个电台的两个区域。

<a id="the-battle-stadium-block"></a>
### 战斗体育场街区

0x180字节数据，u64长度。生产者`0x00b2eb60`填写可选（标志`+0`，数据
`+8`);快照从其持有者的`+0x60`（`0x0110c378`）复制0x188；阅读器 `0x00b2d9fc` 需要长度 0x118。来自 0xBF6：

    0x000  u32    CRC-16 (0x8005) of the 0x22fc-byte regulation core   0x008ff9e0:
                  0x0065dd70([reg+0x180]+0x60, 0x22fc); regulation_preset_core_%d.bin (0x008feb34)
    0x004  0x100  the team's signature: +0x36 of the 0x136-byte team descriptor at match+0x98
                  (0x00b2ef24)
    0x104  4      zero
    0x108  u64    the manager's optional (value +0x1ab8, flag +0x1ab0, 0x00adc8d0), zero unless
                  match type 3                                         0x00b2f100
    0x110  u8     the manager's byte +0x191c (0x00adbbe0) when 0x00adb920 yields an object and
                  0x00b1ce10(0) == 2                                   0x00b2efc4
    0x111  u32, u16, u8   team descriptor +0, +4, +6
    0x118  0x68   zero
    0x180  u64    length, 0x118
 接收方`0x00b2e590`将伙伴的CRC与自己的CRC（`0x00b2e760`）进行比较；对于 `0x008fc470`，当两者都成立时，结果为 9，否则为 10 (`cinc` `0x00b2e778`)。 `0x010719f0`, `0x01071a98`,
`0x01071c00` 将其与 `+0x188` (`0x008ffa10`) 处的 0x640 字节上的 CRC 进行比较。描述符在 18 个站点上被整体复制，其中四个位于 `StateDownloadTeamMenu`（`0x013e660c` 到 `0x013e7c58`）。

match+0x70 是可选值（标志 `+0x70`，值从 `+0x78` 开始：u64 键、指针、u64、指针，随后是 `+0x98` 的描述符）。唯一写入方为 `0x00ad9cf0`（`0x00adeaf0` 中的 memcpy）：对战竞技场匹配更新 `0x00ad5750` 在 `0x00ad6a2c` 从 `[state+0xb8]+0x20` 填充，`0x00ad6a68` 和 `0x00b1ea88` 清除。请求对象由队伍下载任务（`0x014f7fd0`..`0x014f809c`，完成标志 `+0x18`）从 `[job+0x88]` 的结果容器填充：描述符 `+0x00..+0x2f` 为 `+0x38` 的六个 u64，`+0x30..+0x35` 为 `+0x68` 的六字节，`+0x36..+0x135` 来自 `+0x6e`，随后由 `v1/validate` 签名覆盖（`0x014f8094`）。容器取队伍列表中键匹配所选键的完整 0x158 字节条目（`0x01503f10`，在 `0x014fa804` 复制）。列表 `0x0150320c` 包含两类条目：

| 键 | 条目 |
|---|---|
| (1, team) | 存档对战队伍：每只成员一个 u64 `box \| slot << 32`，共六个，来自 `save+0x525 + team*12 + i*2`（`0x0140a5c0`、`0x0140a5f0`）；名称位于 `save+0x4a0 + team*0x16` |
| (2, i) | 已存储记录：`0x01430670` 读取的 0x87f 字节记录中，字节 0x26..0x15b |

签名为RSA-2048、PKCS#1 v1.5、SHA-256，由`0x011aedf0(team, v, sig)`检查（调用者
`0x00b2f19c`、`0x00b2f1e0`、`0x00b2f2e0`、`0x0109eb68`），唯一调用者
`nn::crypto::detail::BigNum::ModExp`（PLT `0x018fff50`，得到`0x0260fb38`）：

    0x011aee90  count 0x148-byte stored PK8s        bl 0x7664c0, add w26,#0x148
    0x011aeeac  v as BE u16, then 00 01             rev w8,w22; lsr #16; strh 0x100
    0x011aef98  Sha256Impl::Initialize
    0x011aefa8  BigNum::Set(modulus, .., 0x100), Set(exponent, ..)
    0x011aeffc  Sha256Impl::Update(message)
    0x011af01c  BigNum::ModExp(out, sig, exponent, 0x100, ..)
    0x011af06c  cmp x8,#0xca: the 00 01 FF..FF 00 padding
    0x011af090  memcmp(.., Sha256Generator::Asn1ObjectIdentifier, 0x13)
    0x011af128  Sha256Impl::GetHash, memcmp(.., 0x20)
 游戏机仅持有公钥；图像承载着
`https://v3-lp1.vp.n.srv.nintendo.net/v1/public_key` (`0x01bd7d41`) 和 `.../v1/validate` (`0x01c11a93`)，因此任天堂服务器可能会签名。链接交换永远不会到达支票。

`v1/validate` (`0x011a2a70`) 发送一个以 NUL 结尾的字符串（`v1/public_key` 的所有主体），密钥版本为 BE u16（密钥持有者 `+0x68`，从 `0x0144fb90` 的 `v1/public_key` 回复中设置），游戏机的版本`0x007d4270() = 0x2D`（屏蔽）为BE u16，`00 01`，BE计数和0x148字节记录（`0x007664c0`）。签名消息持有相同的记录、版本和`00 01`；其中 `v` 是合作伙伴的 MyStatus 字节 `0xA4`（`obj+0x104`、`0x01424bf0`，默认 `0x2D` 位于 `0x014245f0`、PKHeX
`MyStatus8.Game`）。回复解析器 `0x011a2870`：字节 0 状态（2：过时密钥，再次获取；
`R+0x70` = 状态 == 1)，字节 5 至 6 为大端计数 n，上限为 6，n BE u32 进入 `R+0x74`，状态为 0
0x100 字节转换为 `R+0x8c` (`0x011a29e4`)。五个呼叫者中，只有 `0x014f8c00` 保留他们（以
`obj+0x183`); `0x014f808c` 将它们写入描述符形状的 0x136 字节运行的 `+0x36` 处。

比赛类型为 vtables `0x2538238`、`0x2538358`、`0x2538478` 的插槽 8 (`+0x40`)：1 休闲 (`0x00adda60`)、2 排名 (`0x00adde60`)、3 在线比赛（`0x00ade340`）。 `0x00adcfb0(obj,
mode)` 构建它们，仅通过 `0x00b1cdd0` 从 `StateBtlSpotTop` (`0x00b23080`) 的六个站点到达，该站点移动到 `StateBtlSpotCasualMatchEntrance`、`StateBtlSpotRankMatchEntrance` 或
`StateBtlSpotCompTop`。 `+0x108`是由`0x00adc8b0`（`str x1,[x0,#0x1ab8]`，标志`+0x1ab0 =
1`）从`0x00b41b7c`写入`StateBtlSpotCompTop`，u64位于保存块的0x33C0 `0x88F6D6AE`（0x33D0字节，密钥在`0x02072fac`，由`0x01444ac0`读取；前面的密钥`0xEEE5A3F8`是PKHeX的
`KOfficialCompetition`）。

<a id="the-player-profile"></a>
### 玩家简介

0xAEC 处的 266 字节，也是 0x1F 处的信标记录（[会话](swsh_session.md#taking-a-seat)）。
`0x01111970` 从单例 `[0x2610958]` 复制它（+0x310 到 +0x564，互斥体 +0x580）；
`0x01125080` 打包所有组或不打包，因此布局是固定的；位封装组首先是 LSB。
`trade_payload.read_tail` 对其进行解码。

    0x00  16  nn::oe::GetPseudoDeviceId
    0x10  16  nn::account::GetUserId, the account Uid
    0x20   8  nn::account::GetNetworkServiceAccountId, or zero
    0x28  24  trainer name, UTF-16, from MyStatus+0xB0; stale bytes after the terminator
    0x40  25  appearance, bit-packed:
                bit 0      MyStatus+0xA5 (gender) != 0
                bit 1      set by 0x0111cfec; 0 in every capture
                bits 2-5   MyStatus+0xA7, the language (3, French)
                bits 6-7   zero
                8 bits     MyStatus+0xCC
                17 x 10    the model 0x0111dd60 unpacks from the MyStatus bitfield at +0x00
                2, 2, 10   the last three of that unpacking
    0x59  55  position samples, bit-packed:
                2, 2 bits  `a` (sample object +0x47) and `b` (+0x1c9), below
                8 bits     generation: random at ring reset (0x00eb98a8), +1 per re-seed
                8 bits     player object byte +0x136 (7 in every capture)
                3 x 17     at 0x5C, 0x6D, 0x7E, newest first: 5-bit counter (0x01123be0, +1 per
                           push); 3-bit state (+0x1c8, below); x, y, z floats; yaw in radians
                           (Euler component 1, 0x006101c0). 0x00ebf590 pushes at most once a second
                           from the field object's +0x60 (position) and +0x50 (rotation);
                           0x00b4f140 and 0x00b54450 re-push the current sample three times.
                8 bits     at 0x8F: player object byte +0x140 (1 in every capture)
    0x90  37  activity, bit-packed: an 8-bit kind (below; 13 in trade), an optional 28-byte part,
              a 24-byte field, a u16 at 0xB2, a bool; only kind and u16 non-zero. The u16 is the
              location, the line of `script/place_name.dat` (0x00f27d70), PKHeX's met-location
              id (170 Challenge Beach); setter 0x0111bc60, readers 0x0111b8c8, 0x0111b8f4.
    0xB5  37  two more groups (56 and 16 source bytes), zero in every capture
    0xDA  32  sixteen u16 records, `0x010f5060`: Record8 indexes 6, 32, 0, 33, 17, 27, 34, 24,
              12, 3, 10, 35, 38, 7, 36, 37, each clamped to 0xFFFF (PKHeX `RecordList_8`:
              total_capture, evolution, egg_hatching, net_battle, trade, license_trade, cooking,
              campin, pretty, capture_raid, rotomu_circuit, poke_job_return, bike_dash, dress_up,
              get_rare_item, whistle)
    0xFA   8  an optional u64, zero in every capture
    0x102  8  zero
 接收器 (0x00dd5e24) 将位置存储在 +0xB0 处，并将偏航角作为四元数存储在 +0xA0 (0x00992cd0) 处； 0x011a68a4 仅在状态 1、2、3、6 下采样。

样本状态为`[[0x261bd18]]`的`+0x1c8`，仅由`0x00ebf570`设置，通过复位归零
`0x00eb97b0`（唯一调用者`0x00dd2e00`、`0x00eb986c`）；当push为0时立即返回（`0x00ebf5a8`）：

| 状态 | 设置该状态的代码 |
|---|---|
| 0 | `0x00dfd1d4`，vtable `0x2561ec8` 插槽 9 |
| 1 |现场玩家插槽 13 (`0x00d98f28`)、30 (`0x00d9d2a8`)、76 (`0x00da0188`)； `0x00d97730` 运动 0 |
| 2 | `0x00d97730` 运动 1 或 2；插槽7（`0x00d97644`，运动1，当`[+0x5b8]`在运动2中变为1或2时）；插槽 75 (`0x00d9fcc4`) |
| 3 | vtable `0x253e358` 插槽 15（`0x00b4f028`，`StateCreateSession` 类）；设置 `[[obj+0x98]+0x58]` 时，vtable `0x25614c0` 插槽 8 (`0x00dedf80`) |
| 4 | vtable `0x253e8d0` 插槽 16（`0x00b54338`，`StateConnect` 类）；清除时的`0x25614c0`插槽|
| 5 |什么都没有|
| 6 | `0x00da09a0`（`0x00da0a04`）来自`0x00cebe00`，`0x00cebea4`，`0x01466d90`在本机`CallRaidBattleMatchingEvent_`（`0x01466d30`，表`0x25aac68`）|

`0x00d97730(player, motion)` 通过 `player->vtable[0x190]`，以 `[0x261e8a0]` 为键保存动作；原生 `IsPlayerRideBicycleType`（`0x0148b960` -> `0x00da0210`）也读取该值。`0x00e57940` 的 Lua 枚举将动作命名为 `NORMAL`、`BICYCLE_GROUND`、`BICYCLE_WATER`（`0x00e5793c` 的 `1 | 2<<32`）。`0x25614c0` 槽还启动种类 11 的活动记录（`0x0111b660`），交给 `[0x26108d8]`（`0x00fa13c0`）并提交样本。`0x25614c0` 对象对应宝可梦露营访问：原生 `PokeCampToVisit`（请求 `0x0100`，状态 3）和 `NpcPokeCampToVisit`（`0x0000`，状态 4）均构建它；网络侧请求 `0x0101`（状态 3）和 `0x0001`（状态 4）也相同，映像包含多人露营的 `contents.pokecamp.pb.KwSyncData`。状态 6 是极巨团体战匹配。

`a` 和 `b` 打包到位 0-1 和 2-3 中（`0x01123710`；`0x01123760` 将 `b` 3 读取为 0）。重置
模式 0 中的 `0x00eb97b0` 从区域键 `[[[0x2617c48]]+0x180]` (`0x00eb97d0..0x00eb9848`) 设置 `a`：

|关键|地区 | `a` |
|---|---|---|
| `0x5742865396e549d0` | `wr0101` | 1 |
| `0x5ea5c3539ab81c81` | `wr0201`，装甲岛（在位置 170 捕获）| 2 |
| `0x674edc539f9f74a6` | `wr0301` | 3 |
|其他| | 0 |

密钥是 `a_wr0101` 的 FNV-1a 64（基础 `0xcbf29ce484222645`、`0x01369700..0x01369724`），
`a_wr0201`、`a_wr0301`（最后两个字符倒转，全部达到`0xb8123d750dc24af8`）。它们也是数组 `0x02061f98`（在 `0x00ecd418` 处循环），映射到位于
`0x01c25bbb`、`0x01be5bad`、`0x01c2d3a5` (`0x00ec51b4..0x00ec5218`) 和 `0x00de19c0` 副本
`a_wr0101`（`0x01c0ae67`）放在第一位； romfs 有 `a_wr0201.bnk` 和 `a_wr0301.bnk` 音库。
`b` 由 `0x00ebf580` 从 vtable `0x259add8` 插槽 8（`0x0110e850(...) < 4`、`0x012dfaec`）和插槽 11（2、`0x012dfca8`）设置，每个插槽后跟一个推送。

活动记录位于0x90是`0x49`字节，设置为`0x0111b660(rec, kind)`（类于`+0`, 零点为`+4`, `+0x24..+0x3e`, `+0x40`, `+0x48`）。按呼叫站点分类：9`0x0102437c`; 11
`0x00dedf3c`, `0x0126e37c`; 12 `0x01272120`; 18 `0x01027d38`; 19, 21, 23, 25 `0x01027d2c` (`0x13 + 2n`); 27 `0x00de7a0c`; 28 `0x00de727c`; 29 `0x01026290`; 30 `0x0109659c`; 31 `0x015d595c`; 255 `0x01027fac`, `0x010962b8`, `0x01097990`, `0x01097bc4`;和`0x010961b0`按通讯方式`[obj+0x70]`通过表在`0x2066c40`:

    mode   0    1  2   3   4   5   6
    kind   255  1  13  14  15  16  30

`SetMode` (`0x01096d10`, `str w1,[x0,#0x70]`) 由 Link 交换 ([session](swsh_session.md#how-a-searching-sword-finds-a-partner)) 用 2 调用，用 0, 1, 6 调用。

训练家员姓名出现四次（我的状态、训练家员卡、队伍记录、个人资料）；
`pokeldn/swsh/trade_payload.rewrite` 移动所有四个，并交换屏幕名称该训练家。空的队伍槽位为零； 0x810 处的计数一致。

<a id="the-pk8"></a>
## PK8

与 `pokeldn/gen8.py` 中的 BDSP 共享（PKHeX `PK8` 和 `PB8` 均为 `G8PKM`）。剑送来
0x158 队伍表格（`pokeldn/swsh/pokemon.py`），BDSP 0x148 存储表格。

    0x00  u32  encryption constant, in the clear. Seeds the cipher and the block order
    0x06  u16  checksum, in the clear, over the decrypted body only
    0x08       four 80-byte blocks, LCG-encrypted and permuted by (EC >> 13) & 31
    0x148      the party stats, LCG-encrypted with the stream restarted, never permuted
 两个无声误读：

- 队伍统计重启LCG（`PokeCrypto.Decrypt8`种子`CryptArray`两次来自EC）；连续的流给出了看似合理的垃圾，例如 110 级。
- `BLOCK_ORDER[sv]` 命名成为块 *i* 的块：应用它，永远不要反转它。 32 个 `sv` 值中的 16 个是自逆的，并且校验和忽略顺序，因此错误的方向通常读起来很好。   PKHeX 的 `BlockPosition` 条目 24-31 重复 0-7。

检查解码的队伍：昵称与种类匹配；等级（未洗牌尾部）比赛经验；极限训练 0x126 匹配 IV 词 0x8C； MyStatus 的训练家 ID 与每个 PK8 匹配。

<a id="the-trade-message"></a>
## 交换消息

`net_contents.trade.common.pokemon_trade.protocol_buffers`:

    Pokemon                  { 1 bytes   serializePokemonParam }
    PokemonTradeDataHolder   { 1 Pokemon pokemon }
 提议在 10050 上携带 344 字节 PK8 (`trade.py` `pokemon_offer`)。解析`0x010d81d0`构建0x28字节消息（`0x010d9c90`），调用`ParseFromArray`（`0x0070c180`）并传递`[msg+0x18]`；
`MergePartialFromCodedStream` (`0x010d9ee0`) 仅接受标签 0x0a。听者读
`[Pokemon+0x18]`作为libc++ `std::string`（字节0位0选择+0x10处的堆指针），复制
0x158。

<a id="the-receive-handlers-two-silent-drops"></a>
### 接收处理程序的两个静默丢弃

`0x010d5e40`:

    w0 = 0x006b5850(senderPointer)                            0xfd on failure
    if (w0 == 0xfd) { [content+0x1a4] = 1; return; }          silent
    memcpy(stack, body, 0x158)
    subscriber = [content + 0x30 + index*8]
    if (subscriber == null || its refcount is 0) return       silent
    ... invoke it, then content 50's send 0x010d6000
 Content 50的init仅填充`+0x30`和`+0x38`，因此返回大于1的站索引；内容 40 年代
`0x010dbc90` 的门与 `+0x38`/`+0x40` 相同。游戏机立即用自己的答案回答 10050；没有 10050 返回意味着提议从未到达 `0x010d5e40`。内容 30 的插槽 (`0x010ce080`) 仅拒绝其自己的 id (`[[0x2616a30]]+0xf0`)：无主提议通过盒子阶段并失败内容 50。

<a id="content-40s-message"></a>
### 内容 40 条留言

`net_contents.trade.common.sync_save.protocol_buffers`:

    SyncSaveDataHolder { 1 SyncCommand syncCommand }
    SyncCommand        { 1 int32       data       }
 解析 `0x010ddb20`（`0x010d81d0` 的双胞胎）； `0x010df6d0` 仅接受标签 0x0a，子消息解析器 `0x010debc0` 仅接受标签 0x08。 `trade.sync_command` 构建它。
