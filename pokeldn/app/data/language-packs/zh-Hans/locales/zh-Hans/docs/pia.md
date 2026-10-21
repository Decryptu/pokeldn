<a id="the-pia-layer"></a>
# Pia层

Pia 是任天堂的点对点会话中间件，在所检查的每个游戏中都使用 UDP 端口 12345。每个数据报告都以神奇的 `32 AB 98 64` 开头。 Pia 版本决定标题布局：

| | 火红／叶绿（GBA应用程序）| 晶灿钻石／明亮珍珠 | 剑／盾 |
|---|---|---|---|
| Pia版本字节| 15/16 (6.32+) | 9（5.27-5.45）| 4 |
|标题大小 | 0x1D | 0x20 | 0x20 |
|变量 ID |每个 2 个字节 |每个 4 个字节 | 1 个字节 + 一个半字 |
|电线上的 GCM 标签 | | 8，从 16 截断 |全部 16 |
|模块| `pokeldn/ldn/pia_connect.py` | `pokeldn/ldn/pia5.py`（往返捕获字节到字节）| `pokeldn/ldn/pia4.py` |

除非某个部分指定了另一个版本，否则 `0x01...` 地址是 盾 1.3.2 的解压缩 `main`（如 `tools/switch/nso_read.py` 所示），而 `main.bin 0x01...` 地址是 BDSP 1.3.0。
<a id="packet-headers"></a>
## 数据包头
<a id="version-9-pia-527-545"></a>
### 版本 9（Pia 5.27-5.45）

来自`nn::pia::common::Packet::Header`；解析器将三个字段与 `rev` 进行字节交换。

    0x00  4  magic 0x32AB9864, big-endian
    0x04  1  0x80 (encrypted) | version (0x7F)
    0x05  4  destination variable id, big-endian   (0 = broadcast to the mesh)
    0x09  4  source variable id, big-endian
    0x0d  2  packet id, big-endian
    0x0f  1  footer size
    0x10  8  AES-GCM nonce, a monotonic counter
    0x18  8  AES-GCM tag, truncated from 16
    0x20     ciphertext: the plaintext padded to a multiple of 16

<a id="version-4"></a>
### 版本 4

来自解串器 `0x01774730`，它需要超过 0x1f 字节 (`cmp w2, #0x1f; b.hi`)：

    0x00  4  magic 0x32AB9864, big-endian
    0x04  1  0x80 (encrypted) | version (0x7F) = 4
    0x05  1  connection id
    0x06  2  packet id, big-endian
    0x08  8  AES-GCM nonce, a monotonic counter
    0x10  16 AES-GCM tag, not truncated
    0x20     ciphertext
 这两个小字段针对每个目标站，在发送到任何站的数据包上均为 0：零售剑发送的 484 个数据包中的每一个（`0x017beb14`、`0x017beb20`）。发送到一个站（`0x017beb74`、`0x017beb78`、来自调用者的字节、来自会话对象的半字）：

- 连接id：发送者在站的字节+0x78，在连接到`2 + (tick mod 254)`（`0x017c6a00`）时设置；对等方到达连接设置并保持在+0x79。接收方（`0x017bdbd0`）丢弃与其持有的 2 个或更多的 id 不同的 id； 0和1通过。
- 数据包 ID：每站计数器在每次发送前按 `0x0185dd00` 递增，1 到 0xFFFF。接收器（`0x0185dd20`）传递0作为未排序；不高于该站最后一个的非零 ID 会被删除，并且在 +0x18 处的站丢失数据包计数中添加一个间隙。

两者都发送 0，就像游戏机一样，通过每条路径。初始化器 `0x017748bc` 存储
`0x00000004_32AB9864` 作为一个 64 位字，并将随机数和标签归零；验证器 `0x017749f0`，
`0x01774b60`、`0x01774d00` 检查`(byte & 0x7f) == 4`（BDSP：与9相同）。在标头下方，版本 4 共享版本 9 的会话密钥和 IV，及其帧加一个字段。
<a id="version-11-what-a-receiver-drops-scarlet-400"></a>
### 版本 11：接收方丢弃的内容（朱 4.0.0）

`0x6e9744` 在各协议读取前接受或丢弃整个数据包；一旦丢弃，所有协议都收不到。令 `st` 为源地址的站点，`V` 为接收方变量 ID，`D` 为头部目标，`S` 为头部来源：

| 检查 | 丢弃条件 |
|---|---|
| 发送方 | `st` 已标记（`+0x78`）或处于状态 3 |
| 目标 | `D >= 2` 且 `D != V` |
| 来源 ID | `S != 0` 未对应任何站点，且 `D == V`，或 `D` 为 0、1 并带尾部 |
| 数据包 ID，`D == 1` | 不新于 `st` 的目标 1 计数器中上次值（`st+0x60`、`0x6e9854`） |
| 数据包 ID，其他 `D` | 不新于 `st` 的另一计数器中上次值（`st+0x48`、`0x6e98b4`） |

计数器检查 `0x6f3ff4` 对数据包 ID 0 直接通过，不保存值；其他 ID 必须满足 `(int16)(id - last) >= 1`，因此同一 ID 的重发会被丢弃。加入过程中，若源地址还没有站点，则不检查包 ID。任何检查都不读取尾部 ID。实机发送方（`0x6b6b38`）用一个计数器（`0x696d04`）编号目标 1 的包；发往单个变量 ID 的包则使用按接收方独立的计数器（`0x696ce4`），两者都跳过 0。

<a id="message-framing"></a>
## 消息框架

一个 Pia 端点携带一条或多条消息，每条消息都以一个存在字节开头，说明后面跟着哪些报头字段。它省略的字段继承自数据包中的前一条消息（`0x01853050`，逐位）：标志位于+9，大小位于+0xA，协议|端口位于+0xC，目的地位于+0x10，源位于+0x18。继承的大小根据 0x589 进行边界检查。步行停在 `0xFF`，没有其他地方：
`0x00` 是合法的单字节标头，是继承每个字段的消息。

每个带的读取器向前复制前一个标头，然后读取已设置位的字段：

|标题版本 |标题已读 |读者|停止测试|下一条消息开始 |
|---|---|---|---|---|
| 4 |剑| `0x01852da0` | `0xFF` |四的倍数 |
| 9（5.27-5.45）| 明亮珍珠1.3.0 | `0x159b980`，复制 `0x159b9ec`..`0x159ba10`，字段 `0x159bb60` | `cmp w8, #0xff` 在 `0x159b9d4` |四的倍数（`0x15abf68`..`0x15abf70`，所有七个调用者）|
| 11 (6.16-6.30) | 传说阿尔宙斯 1.1.1 | `0x7484cc`，复制 `0x748538`..`0x74855c`，字段 `0x7486a8` | `0x748520` |栏结束的位置 (`0x743f14`..`0x743f18`) |
| 11 | 11 朱4.0.0 | `0x6ed2d0`，复制 `0x6ed348`..`0x6ed360`，字段 `0x6ed4b4` | `0x6ed324` |栏结束的位置 (`0x6e9054`..`0x6e905c`) |
| 16（6.39-7.2）| 传说 Z-A | `0x256e088`，复制 `0x256dac4`，字段 `0x256de5c` |无：数据包标头说明其填充 |终点在哪里 |

站将相同大小的消息捆绑在存在 0x00 后面：朱是其零填充的记录块，明亮珍珠是在相同大小的一个之后的可靠消息，阿尔宙斯是其第二个 24 字节记录。将 0x00 视为一条消息，每次行走都恰好在 `0xFF` 填充（5,866 明亮珍珠、11,501 阿尔宙斯、38,350 朱包）上结束；停止在 0x00 处，其中 3,444 个字节中有未读字节，并丢弃之后的所有内容。 `tests/test_pia_bundled.py` 每个标题固定一个数据包。

版本 3（Let's Go 1.0.2）没有存在字节：固定的 0x16 字节标头，其第二个字节必须为 1 (`0x5ae7d0`)，步行停止在 `0xFF` (`0x5ae790`)。

版本 4 在 18 个站点处内联计算标头大小，始终以 1 为基数，将 5 个条件相加：

    tst w9, #1    -> +1       message flags
    tst w9, #2    -> +2       payload size, big-endian
    tst w9, #4    -> +4       protocol id and a 3-byte port
    tst w9, #8    -> +8       destination
    tst w9, #0x10 -> +8       the sender's station constant id
 存在 0x7F 给出了 24 字节的标头；位 0x20/0x40 不添加任何内容，如版本 9 所示，其标头为 16 字节。发送方 MAC 上的八字节常量 id 为 `station_protocol.ldn_constant_id`，本地协议为 `host_constant_id`：此处为大端，本地协议主体中为小端。

版本 16 (Z-A) 缩小了字段范围：标头大小 `0x256dfc8` 是一个字节加一个标志，两个字节加大小，0x04（协议）、0x08（端口）和 0x10 位各一个。位 0x10 字节位于协议和端口之间（`0x256df54`，设置器 `0x256a8e8`）；新的标头包含协议 0xFF、0xFD 和端口 0 (`0x256a8c0`)。读取器忽略 0x20 至 0x80 位，并拒绝 0x590 或更大 (`0x256df04`) 的大小。位 0x10 尚未在广播中看到。 `pokeldn.ldn.reliable.parse_messages` 读取它。

在版本 4 和 9 中，每条消息都被填充为四的倍数（明亮珍珠用 0x00 填充），跳过未读；数据包尾部为`0xFF`。 `pia4.parse_packet()` 解析继承，
`pia4.parse_messages()` 返回发送时的每个标头。当消耗的字节加上时，步行是正确的
`0xFF` 填充占每个数据包的整个明文。
<a id="compression"></a>
### 压缩

栏可能是一个 zlib 流，在消息标志中对每个消息进行标记：5.27-5.45 中的 0x20，版本 4 中的 0x10。版本 5 可靠标头有自己的 zlib 标志 0x10； BDSP 在一些游戏消息上设置它（23 字节的消息作为具有 4 KB 窗口的 20 字节流）（[BDSP 协议](bdsp_protocol.md)）。

BDSP 在会话中切换压缩。读取原始数据，压缩的 31 字节消息会解析为标有 0x6260 的税标的标头。在 2835 条版本 4 消息中，`flags & 0x10` 准确预测了解压缩性（256 条设置，全部有效；2579 条清除，无）。 zlib 流的前两个字节作为大端半字读取，是 31 的倍数。
<a id="the-footer"></a>
### 页脚

发送到多个游戏机的数据包带有一个页脚：每个接收者一个大端半字，其变量 ID 的低半部分，头字节中的长度为 0x0f。 GCM 标签未涵盖它：密文为 `data[0x20 : len(data) - footer_size]` (`pokeldn/ldn/pia5.ciphertext()`)，并且留下的页脚未通过身份验证，没有其他症状。当只有部分数据包进行身份验证时，首先按页脚大小对失败进行分组。
<a id="session-keys"></a>
## 会话密钥

每种网络类型一个会话密钥实现，在不同的类中：

|网络类型 |类 |推导|
|---|---|---|
| LDN（本地无线，联合房间）| `nn::pia::local::LocalProtocol` |游戏密钥下的 AES-128-ECB，从会话值的 xorshift128 中提取超过 16 个字节 |
|局域网 | `nn::pia::lan::LanProtocol` | HMAC-SHA256 的前 16 个字节（游戏密钥，最后一个字节递增的 32 字节参数）|
| NEX（互联网）| `nn::pia::nex::*` |来自匹配服务器的会话密钥 |

在已发表的文章中，“用会话参数播种的 SSID 或随机值”列出了两种实现方式；类名表明捕获使用了哪一个。
<a id="the-game-key"></a>
### 游戏钥匙

    key = cryptoKeyDataSeed                     the game's own 16-byte constant
    key[1]  = (version >> 8) & 0xFF
    key[3]  = (version >> 4) & 0xFF             version = the local communication version,
    key[7]  = (version >> 1) & 0xFF                       which the advertisement carries
    key[12] = (version >> 0) & 0xFF
 已发布的每游戏密钥是一个游戏版本的该值，与种子的字节 1、3、7 和 12 (`ldn_game_key()`) 完全不同。 剑／盾的密钥是一个 16 字节 ASCII 文字，加载了一个 `ldp` 并按原样使用，没有种子，也没有版本替换。
<a id="the-ldn-session-key"></a>
### LDN 会话密钥

对于 Pia 5.9-5.45：

    rnd = four SEAD draws, seeded with the session parameter from the advertisement (+0x0c),
          packed little-endian into 16 bytes
    session key = AES-128-ECB(game key).encrypt(rnd)
 SEAD，任天堂的标准库 RNG，通过 `s[i] = (prev ^ (prev >> 30)) *
0x6C078965 + i` 为其状态播种，并运行具有班次 11、8 和 19 的 xorshift128（`pokeldn/ldn/sead.py`；
`pia5.ldn_session_key()`）。对于 Pia 6.16+（火红），会话密钥是游戏密钥下 SSID 的 AES（[无线层](ldn.md#hosting-for-an-emulator)）。
<a id="the-aes-gcm-iv"></a>
### AES-GCM IV

对于 Pia 5.27-5.45 和版本 4（`ldn_nonce_crc()`、`gcm_iv()`）：

    IV[0..2]  = first three bytes of crc32( network id (little-endian) || source MAC address )
    IV[3]     = source variable id & 0xFF        from the packet header
    IV[4..11] = the packet's 8-byte header nonce
 源MAC不在数据包中；其余的来自捕获或广告。明文用 `0xFF` 填充为 16 的倍数，即测试一个 AES 块中候选密钥的已知明文。
<a id="the-protocols"></a>
## 协议

从 `GetProtocolId`（每个 `nn::pia` 协议对象上的 vfunc4，两个字主体）读取 RTTI vtable。

|编号 |类 |笔记|
|---|---|---|
| 0x14 | MeshStation 协议 |连接握手；还带有每个网格确认|
| 0x18 |网状协议|加入、更新网格、主机迁移 |
| 0x1c |同步时钟协议| |
| 0x24 |本地协议 |主机重播更新会话 |
| 0x54 |带宽检查协议 | |
| 0x58 | Rtt 协议 |往返时间 |
| 0x68 |不可靠协议 | |
| 0x77 |时钟协议| |
| 0x7c |可靠协议 |可靠的推拉窗|
| 0x80 |广播可靠协议 | |
| 0x84 |可靠广播协议|与 0x80 不同的类别 |
| 0x94 |会话协议 | |
| 0xa4 |监控数据协议 | |

BDSP 寄存器九个：0x14 v2、0x18 v3、0x1c v0、0x24 v0、0x58 v3、0x68 v1、0x7c v3、0x94 v1、0xa4 v0。 Mesh 版本 3 将库固定到 Pia 5.30-5.45，可靠版本 3 固定到 5.31-5.43。
<a id="joining-a-mesh"></a>
### 加入网格

站点依次通过更新会话（0x24）、连接请求（0x14）和加入请求（0x18）加入；每个每 500 毫秒重传一次，直到得到确认。

Mesh 协议没有 ack 类型（5.31-5.43 没有构建器）：确认 Mesh 消息的四个站点称为 `MeshStationProtocol`，因此 ack 是 0x14、`05 00 00 00` 上的 8 字节类型 5 确认，确认 ID 使用大端字节序。 ack id 是消息的最后四个字节，无论其长度如何（`size - 4` 带借位检查；四个字节以下为 0）。 `pokeldn/ldn/mesh_protocol.ack_for()`。主机在发送加入响应之前确认加入请求；接收方确认每个副本。
<a id="leaving-a-session-pia-6"></a>
### 离开会话 (Pia 6)

`Session::LeaveAsync` 开始 `LeaveSessionJob`，其第一步 LeaveSessionJob::LeaveMesh 开始
`LeaveMeshJob` 位于非主机站上（`LeaveMeshWithHostMigrationJob` 在主机上）。
`LeaveMeshJob` 的第一步 SendLeaveRequest，发送 Session type-3 离开请求，并等待 500 ms 主机的 type-4 响应，最多发送 4 次。在调用和第一个类型 3 之间，Pia 内部没有运行计时器；属于游戏之前的延迟。

| | 传说阿尔宙斯 1.1.1 | GBA 应用程序 (Pia 6.39) |
|---|---|---|
| `Session::LeaveAsync` | `0x72a6dc` | `0xb1060` |
| `LeaveSessionJob` 启动，第一步LeaveMesh | `0x72c5a4` -> `0x72c640` | `0xb460c` -> `0xb46f0` |
|非主机分支到`LeaveMeshJob`启动| `0x734f04` -> `0x734dd0` -> `0x73b820` | |
|发送休假请求 | `0x73b898` | `0xcacf4` |

这些步骤由作业存储在每个步骤指针旁边的字符串命名（阿尔宙斯中的 `LeaveSessionJob::LeaveMesh` 为 `0x37a2eb9`，GBA 应用程序中为 `0x174e53`）。其他步骤是 WaitLeaveMesh、WaitLeaveMeshWithHostMigration、WaitHostMigerated、MeshCleanup 和 DisconnectNetwork，在 6.39 中还有 WaitDisconnectNetwork、SendMonitoringData 和 CompleteProcess。
<a id="the-local-protocol-0x24"></a>
## 本地协议（0x24）

主机大约每 100 毫秒广播一次更新会话（类型 0x11），直到每个站都确认它：

    local message header  version 1, type 0x11, size 73
    sequence id
    network id            random, not the advertisement's network id
    host variable id      the same value as the packet header's source variable id
    host constant id
    allow participating
    node 0..7             address:port and a ranking byte each
    host migration state
 八个九字节节点槽和一个字节。 Pia消息头是big-endian，这些字段是little-endian，其中的本地地址是big-endian。 `pokeldn/ldn/local_protocol.py` 解析它和版本 4。
<a id="the-ack"></a>
### 确认

ack（类型0x21）是20字节，来自`LocalAckMessage::Serialize`（`main.bin 0x016bc0f4`）：`1`为0，类型为1，布局大小半字为2，六个零字节为4，序列ID为0x0C，四个零字节位于 0x10。构造函数（`0x016bc0c8`、`mov w8, #0x14; str w8, [x0, #0x14]`）将 20 写入 +0x14 处的半字，并将 +0x16 处的 PBS 大小清零。

`LocalProtocol` 对于所有四种类型都有一个发送路径 (`0x016af22c`)，因此 ack 的结构类似于更新会话：存在 `0x7F`、标志 `0x11`（“目标是位图”加上“可能不会捆绑”）、协议 36、端口 0、目标 0。位图(`0x0159a15c`) 为 `1 << station index`，或 0 表示广播。客户端向网络广播地址广播其ack，数据包`dst_var` 0，消息目的地0；重播停止是通过信号。

确认由发送方的地址决定：`0x016af96c` 调用 `0x016aec94`，它在 `this+0x188` 处遍历 9 个节点槽（跨步 0x40），比较 +8 处的 16 字节地址和 +0x18 处的端口。客户端的变量 id 提供 IV（源变量 id 的低字节），因此它必须在运行中稳定且非零。
<a id="the-mesh-station-protocol-0x14"></a>
## Mesh Station 协议 (0x14)

调度程序用字节 0 减 1 索引一个七条目表（版本 4：`0x017c5f50`，表
`0x02081804`; BDSP：`0x0154e848`，表`0x3e6b38f`）：连接请求和响应、断开请求和响应、ack、中继连接请求和响应。
<a id="the-version-9-connection-request"></a>
### 版本 9 连接请求

按顺序检查：

|偏移|领域 |失败给出|
|---|---|---|
| |尺寸 15..949 |下降|
| 0x0 |消息类型、连接结果、平台id |下降|
| 0x3 |目标常量id，big-endian u64，与游戏机自己的比较|沉默|
| 0xB |目标变量id，big-endian u32，与游戏机自己的比较|沉默|
| 0xF |协议数量与游戏机本身的数量相比|沉默（错误0x11c26）|
| 0x10 |那么多（id，版本）对 |版本低→结果2，高→结果3，均回复|
| |站位置大小，big-endian u16，0x20..0x40 |下降|
| |车站位置|下降|

`0x0159b850` 对于未注册的 id 返回版本 0，因此 `(0xFF, 1)` 总是绘制“太高”：绘制拒绝的 `(0xFF, 1)` 对中的 N 是游戏机的协议计数。

`0x0154f5e8` 处内部错误的结果字节映射：

|错误 |结果 |意义|
|---|---|---|
| 0x646f | 2 |请求者的版本太低|
| 0x6470 | 3 |太高了|
| 0xc24 | 4 | |
| 0xc25 | 1 | |
| 0x11c0f | 7 |解析后，每个版本都匹配，第二阶段拒绝它；还有“这个变量 id 已经是我的车站之一”（当车站离开、玩家重新进入房间或通过新的 id 时清除）|
| 0x11c26 | *（无）* |协议计数不匹配：沉默 |

id 永远不会被检查：九个 `(0xFF, 0)` 条目通过协商。

站位置的地址大小字节对端口进行计数：InetAddress 解析器针对 `0x00040044` 测试 `1 << size`，因此只有 2、6 和 18 通过。请求解析器会丢弃位置的错误，因此格式错误的位置会读取为变量 id 为 0 的请求，并且每个变量 id 都会遭到相同的拒绝。

二进制文件的大小：ack 8 个字节 (`0x0154fa2c`)、拒绝 15 个字节 (`0x015501ec`)、断开响应 1 个字节 (`0x0154ea60`)。
<a id="the-version-4-connection-request"></a>
### 版本 4 连接请求

处理程序 `0x017c62a0` 在同一协议上读取不同的消息：

    [0]     message type            1
    [1]     a byte compared against the station's own byte at +0x79
    [2]     platform id             must be 9   (5.27-5.45 checks 4)
    [3]     0 or 1; anything higher is rejected. 1 means the request also names a target variable id
    [4]     target constant id      big-endian u64, compared against the console's own
    [0xC]   target variable id      big-endian u32, checked only when [3] is 1
    [0x10]  protocol count          compared against the console's own count at +0x78
    [0x11]  the sender's station location
 从偏移 3 开始，版本 9 的字段位于前面一个字节。没有协议列表：从 0x11 开始是站位置（一个串行器调用上限为 0x40 字节），与版本 9 相同（解串器 `0x0185ee20`，相同的偏移量，地址大小 2、6 或 18），这使得 [1] 和 [0x10] 成为其 nat 标志，自然位置。

当 [3] = 1 时，游戏机不应答（96 个请求）。当 [3] = 0 时，游戏机用它自己的请求进行应答：它的位置、常量 id、更新会话给出加入方的变量 id、服务变量 id、nat 四元组、然后是 ack id、每条消息计数器 `0x017d5750` 在消息大小减 4 时读取。

首先运行平台检查（`0x017c62e8`）并回答不匹配：响应发送者
`0x017c6c30`分配17个字节，`[0] = 2`、`[1] = result`、`[2] = 9`、`[3] = 0`。后续检查是静默的，因此错误的平台会告诉“从未到达处理程序”和“后续检查失败”。平台 4 取自零售 剑 `02 02 09 00 00 00 00 00 00 00 00 00 00 00 00 00 00`：结果 2。

握手，[3] 清除：

    ->   the console's connection request
    <-   the joiner's connection response, result 0, carrying the console's constant and variable ids
    ->   `05 00 00 00 <ack id>`, a type-5 ack, eight bytes
    ->   its own connection response, result 0, ~600 bytes, carrying the joiner's constant id,
         variable id and the player's name in plain ASCII, repeated until acknowledged
确认中的 u32 是被确认消息的末尾计数器。发送游戏机请求的类型 5 确认可停止重传（桥接驱动程序的 `--ack-request` 会发送）。响应处理程序不读取确认状态：类型 5 处理程序（`0x017c6034`）只从待确认表清除 ID（`0x017d5770`）；游戏机的连接任务（`0x017afa70`）在收到确认或站点达到状态 5 时结束。实机《剑》读取了全部 12 个未附确认的响应。

<a id="what-a-connection-response-must-satisfy-to-be-read"></a>
### 连接响应必须满足什么条件才能被读取

类型 2 和 7 到达处理程序 `0x017c6e70`（入口 `0x017c5fb4` 和 `0x017c60c0`，表 `0x02081804`；类型 7 入口传入 w2 = 1）。结果不为 2 的响应逐字段检查，每次失败均静默丢弃：

|处理程序读取 |它需要|失败给出|
|---|---|---|
| `[1]` 结果字节 | 2 采用单独的路径 | |
| `[5]` 大端 u64 |接收者自己的常量 id |下降，`0x017c6f48` |
| `[0xD]` 大端 u32 |接收者自己的变量 id |下降，`0x017c6f68` |
|发件人的电台位置|解析到一个它知道的电台 |下降，`0x017c6f04` |
| `[0x37]` 一个字节，仅结果为 0 时 | 小于 5 | 丢弃，`0x017c6ff0` |
| 站点 +0x48 的状态 | 4，在发送确认后检查（`0x017c71a4`） | 返回；接受后为 5（`0x017c7990`） |

游戏机在 `0x017c7134` 确认响应，即在 `[0x37]` 检查后、状态检查前；从未获确认的响应在 ID、站点位置或 `[0x37]` 检查中失败。非零结果或 `[0x37]` 大于等于 5 时，将结果（该检查为 2）保存到站点 +0xa0 对象的 +0x79 字节。

该对象是站点的网状连接任务 ConnectStationJob。其步骤 `0x017afa70` 在截止时间内、站点尚未达状态 5 时读取此字节（`0x017afc34`）：0 继续等待，1 为错误 `0xc25`，2 按 `+0x7c`（`response[2] - 9`）符号选择 `0x646f`、`0x6470` 或 `0x11c26`，其他值为 `0xc24`。它把错误交给等待上下文（`0x01769720`），释放待确认 ID（`0x017d5770`），并把站点从状态 4 移至 6（`0x017afafc`）。
状态 4 通过指向站点 +0x48 的指针写入（`str w9, [x8]`）：类型 1 请求使用 `ProcessConnectionRequestJob::ConnectToRequesterStation`（`0x017c8e90`，写入 `0x017c8fd8`），类型 6 使用 `::WaitInverseConnection`（`0x017c9760`，写入 `0x017c98a8`），两者在请求处理程序 `0x017c62a0`（`0x017c6aac`、`0x017c6aa4`）保存对端 ID 到 +0x79、状态 3 和自身 ID 到 +0x78 后调用。在状态 3 且 `request[3]` 不为 1 时，启动面向对端的 ConnectStationJob（`0x017af520` 或 `0x017b0120`），写入状态 4、设置截止时间、安装步骤 `0x017c9080`；上下文有错误时步骤结束（`0x017c90d4`）。`request[3]` 为 1 时返回 0，不写入。

17 字节响应（`RESPONSE_SIZE`，`0x017c6c30` 处的短格式分配 `mov w3, #0x11`）使 `[0x37]` 位于消息末尾之外 38 字节的残留缓冲区，因此是否读取取决于发送方无法控制的内存：ldn_mitm 下模拟运行的《盾》1.3.2，无论是否附请求确认，52 次中接受 3 次；实机《剑》12 次全部接受。模拟《盾》接受了全部 23 个补齐到 56 字节、`[0x37]` 为 1 的响应，而该处为 5 的 4 个全部拒绝。未附请求确认时，补齐形式首次发送就获接受（`bin/swsh_connect.py --ip-join`）。游戏机自身的接受响应为 840 字节，`[0x37]` 为 1；`station4.build_connection_response(..., min_size=ACCEPTED_RESPONSE_SIZE)` 补齐到 0x38 并写入 1。
本层接受不表示上层游戏开始：《剑／盾》还等待 0x37 之后的字段（[到达游戏层](swsh_session.md#reaching-the-game-layer)）。

响应后，游戏机的连接响应表示接受；其请求每 500 毫秒以相同末尾计数器重传表示拒绝（携带加入方自身 ID 的响应引发 20 次重传，随后静默）；单纯静默既不表示接受也不表示拒绝。使用游戏机 ID 回应、且从未得到确认的请求在 44 秒内没有重传。

游戏机请求的 [1] 处的 nat-flags 字节在连接之间有所不同，并且不跟随加入方控制的字节（在 26 个连接上尝试的每个读数）。其内容不得而知；它的记录由电台位置解析器 `0x0185ee20` 填充。
<a id="the-mesh-protocol-0x18"></a>
## 网格协议 (0x18)

`MeshProtocol::vfunc9`（接收时隙）通过表（版本 4：调度程序 `0x017c0c80`，表 `0x02081564`）采用字节 [0] 减一，以 0x80 为界。 129 个条目中有 19 个已上线；版本 4 是 BDSP 减去 0x22 DUMMY_MESSAGE 和 0x23 DUMMY_ACK。

加入请求有六个字节：类型 1、站索引 253（“尚未在网格中”）、ack id。版本 4 处理程序 (`0x017c1700`) 根据 0xFD 检查 [1]，使用 `0x017d5750` 获取 ack id，并对 0x14 (`0x017c6dd0`) 进行确认。 Pia 重新传输大约十秒钟。

两个频段中的加入响应标头均为 16 个字节。版本 4 解析器 `0x017b4830` 首先读取拒绝形状（`[1] == 0`、`[2] == 0xFF`、`[3] == 0xFF`，原因在 [4]），然后将 [1] 处的站计数与其最大值，[8] [9] [0xA] 作为一个大端序24位值，更新计数器大端在0xC。

站条目：5.31-5.45使用68字节（64字节站位置、站索引、大端半字连接顺序）；版本 4 使用 64，索引为 0x3E，并且没有连接顺序（光标从
`0x10 + 0x3E`，`ldrb w8, [x20], #0x40`；针对 `0x017bfa34` 的 32 个站，拒绝通过 `0x810 = 0x10 + 32 * 0x40` 的响应）。两个长度证实了这一点：

    join response   148 B  =  0x10 + 2 * 0x40 + 4        68-byte entries would give 156
    update mesh     524 B  =  12   + 8 * 0x40            BDSP's eight 68-byte seats give 556
 版本 4 从每个路径的不同字段获取条目计数：未分段（`fragments == 1`，
`0x017b48f4`) 从基数 0 开始遍历 `stations` 条目，并且从不读取 [6] 或 [7]； fragmented（`0x017b4b6c`，最多三个片段）将 [6] 个条目放入槽 [7] 中，并根据第一个片段检查 [1]-[4]。 5.31-5.45 两者都采用 [6]，因此 [6] 为零的单片段响应读取为空网格。 `parse_join_response(version4=True)` 遵循两条路径。

UPDATE_MESH (0x20)，大约每秒一次，是网格中的主机列表；在 BDSP 中，始终将未使用的席位清零的完整 556 字节，因此走 `entries` 字节 (`mesh_protocol.parse_update_mesh()`)。 5.31-5.45 连接顺序对网格创建后的连接进行计数：在一台计算机连续三个连接后，它读取 0 表示主机，3 表示索引 1 处的客户端。
<a id="host-migration"></a>
### 主机迁移

名为 next 主机 的电台必须应答。 0x18 端口 1 上的网格消息在可靠标头下到达。

MIGRATION_START（0x44）是三个字节。处理程序 `0x017c1f00` 拒绝该消息，除非

    size == 3                                     0x017c1f54
    [1] == the mesh's HOST index, byte 0xAB       0x017c1f64, getter 0x017bbfe0
    [2] <= 0x1F                                   0x017c1f78, the 32-station bound
    [2] != that host index                        0x017c1f8c
 和发送方 `0x017c31b8` 完全构建为 `[0x44, host index, new host index]`。

答案是 `[0x48, own station index]`：MIGRATION_RESPONSE 处理程序 `0x017c10ac` 需要
`size == 2`，构建器 `0x017c3310` 使用 `0x017bc430` 中的 w22 写入 `[0x48, w22]`。 getter 相距一字节：`0x017bbfe0` `ldrb w0, [x0, #0xAB]`（主机索引）、`0x017bc430` `ldrb w0, [x0,
#0xAC]`（自己的索引），在托管网格的站上相等。

MIGRATION_FINISH（0x41）关闭它：`[0x41, host index, flag & 1]`（`0x017c2ef0`），处理程序
`0x017c0fb0` 根据主机索引检查 `size == 3` 和 [1]。

响应转到新主机（`0x017c3250`，由 `0x017ca1a0` 调用）。那个电台播出
`MIGRATION_FINISH`；向离开的主机发送响应并不能完成切换。

`pokeldn/ldn/mesh_protocol.py`：`parse_migration_start`，`build_migration_response`，
`build_migration_finish`、`parse_migration_finish`。已发布的四个剑／盾客户端均不处理迁移；在两个控制台之间，指定的站应答它。
<a id="the-rtt-protocol-0x58"></a>
## RTT协议（0x58）

主机从每个站点进入网格开始计算时间（没有维基页面涵盖这一点）。版本 9 的消息有 13 个字节：

    u8   kind        0 = request, 1 = response; anything else is dropped
    u64  timestamp   big-endian, the sender's own clock
    u32  target      big-endian, whose reply this is; zero is accepted by everyone
 版本 4 保留 id 0x58 (vfunc4 `0x0185d590`)；它的解析器 (`0x0185d2a0`) 读取 16 个字节并忽略 13 个字节的答案。在观察到的每个请求中，字节 1..7 为零，表示未知；
`rtt_protocol.response_for_v4()` 呼应它们并仅设置类型。

站点回答类型 1，并回显时间戳。主机将`(now - echoed) / ticks per ms`放入每个站的9个样本环中，其中位数是满后的RTT； BDSP 时间戳的运行频率约为 31.36 MHz。在测量的 BDSP 会话中，RTT 协议没有丢失静默站；它停止采样。更新的请求周期在`0x015ace54`后面有两个分支，410 ms和500 ms：未应答，BDSP每410 ms请求一次；一旦每个环已满，每 508 毫秒一次，可靠的重传间隔遵循较小的测量 RTT（大约每秒六轮）。

BDSP 地址：id 和版本 `0x015ada10`/`0x015ada18`、大小 (`mov w0, #0xd`) `0x015adab4`、序列化/解析 `0x015ada24`/`0x015ad54c`、更新 `0x015acd90`、答案生成器`0x015ad024`，目标检查`0x015ad000`，样品环`0x015ad058`。
<a id="the-reliable-sliding-window-0x7c"></a>
## 可靠的推拉窗（0x7c）
<a id="version-9-pia-529-543"></a>
### 版本 9（Pia 5.29-5.43）

    0x0  1  flags     1 application data, 2 message start, 4 message end, 8 is initialized,
                      16 zlib, 32 reset, 64 reset ack
    0x1  1  stream id
    0x2  2  payload size, big-endian
    0x4  2  sequence id, big-endian
    0x6  2  lowest sequence id pending ack, big-endian
    0x8  1  number of destination bits (N)
    0x9  4 * ceil(N / 32)  destination bitmap words, big-endian
            payload

`GetSize` 是 `9 + (((N + 0x1f) >> 3) & 0x3c)`，所以 9 或 13 个字节。 N 个 0x20 或更多，且 危险
0x5a1以上均被拒绝。

当应用程序数据标志被清除时， PBS 是一个批量确认：

    0x0  1   a bitfield; 0 in every captured ack. Its bit 0 sets a flag on the receiver
    0x1  1   entry count, refused at 0x21 or more
    0x2  21 * n  entries: u8 stream id, u16be ack id, u16be `ack id - 1`, 16-byte ack mask
 实机对序列0和1的确认：

    00 00 0017 ffff 0003 00   00 01   00 0002 0001  00 * 16
 无标志，流 0，序列 id 0xFFFF（控制消息没有序列），则发送方仍在等待的最低 id。 `ack id` 比收到的最高序列多 1。
`pokeldn/ldn/reliable5.build_ack_message()` 逐字节再现它。序列为 0 的数据消息不会收到确认；序列 1 绘制 ack。
<a id="what-the-receiver-discards-in-silence"></a>
### 接收者默默丢弃的东西

接收路径根据端口的窗口检查一条消息，并将税务复制到槽中：朱 4.0.0 `main.bin` `0x006f0330`； 晶灿钻石 1.3.0 `0x159fb98`，从
`ReliableSlidingWindow` 接收标志位 0 的 `0x159f1e4`（位 5 复位、位 6 复位确认、窗口槽 13 的任何其他确认；`0x159f88c..0x159f8b8`）。五种情况丢弃消息，仍返回成功；两个还设置了“ack欠”字节（朱协议`+0x48`，BDSP窗口
`+0x738`），因此发送方读取应用程序从未收到的消息的确认。

|消息被丢弃时 | 朱 | BDSP |确认仍然发送|
|---|---|---|---|
|窗口未初始化且标志缺少 `is initialized`（位 3）| `0x6f037c` | `0x159fbd8..0x159fbe4` |没有|
|序列 id 低于窗口基 `+0x18` | `0x6f03cc` | `0x159fc30..0x159fc3c` |是的，`0x6f03d0` / `0x159fc3c` |
|目标计数（已解析的标头 `+0x10`）非零且位图缺少接收方位 | `0x6f0430` | `0x159fc7c..0x159fca4` |没有|
|流 ID（线路字节 1，解析头 `+9`）与窗口 `+0x1e` 初始化时锁存的流 ID 不同（BDSP `strb w26, [x24, #0x1e]` `0x159fc14`）| `0x6f0454` | `0x159fcc0..0x159fcc8` |没有|
|环槽已被占用| `0x6f0540` | `0x159fdb0..0x159fdb4` |是的，`0x6f0530` / `0x159fda4`（测试前）|

三个条件返回可读结果（朱）：超过窗口末尾的序列`0x4c0d`（`0x6f04a4`），对`0x5a1`字节`0x10407`（`0x6f05cc`）的重组，不膨胀的zlib `0x2c03` (`0x6f0580`)。

BDSP 接收环位于窗口 `+0x38`：时隙缓冲区 `+0x8`、时隙计数 `+0x10`、环头
`+0x14`，基本序列`+0x18`，流id `+0x1e`，初始化标志`+0x1f`。槽位为`0x5b8`字节；环索引通过减法进行换行。 A槽：占用字节`+0`、消息结束标志`+1`、zlib标志
`+2`，拓扑大小 `+4`，拓扑来自 `+6`，每端口句柄 `+0x5a8`，时间戳 `+0x5b0`。不存储消息开始标志；重组从基部运行到带有结束标志的第一个插槽。

流上的第一条消息将基数设置为其自己的序列 ID (`strh w25, [x24, #0x18]`
`0x159fc10`);仅在目标和流 ID 测试通过后才设置初始化标志 (`0x159fce4`)。当 `seq - base + [ring+0x1c] >= [ring+0x10]` (`0x159fc60..0x159fc78`) 时，序列被 `0x4c0d` 拒绝； `+0x1c` 是环头偏移，0 为新鲜流。

BDSP窗口更新`0x159fea8`发送欠ACK时定时器（窗口`+0x740`加上周期
`+0x778`）用完（`0x15a003c..0x15a005c`），用数据包写入器`+0x750`（`0x15a0318`，`0x15a0354..0x15a0364`）调用窗口槽11 `0x15a1c78`。如果 `+0x738` 为 0 (`0x15a1cb8`)，则时隙 11 返回，构建具有序列 0xFFFF (`0x15a1de4`) 的控制消息，可选择压缩类似数据 (`+0x7ac`、`0x15a1f70`)，通过时隙 10 发送它(`0x15a203c..0x15a2044`)，清除
`+0x738` (`0x15a1fe8`) 并重新启动定时器 (`0x15a1ff8`)。插槽 10 将 `+0x748` 处的协议和端口字写入标头（`0x15a1be8`），并将数据包交给写入器（`0x15a1c0c`，
`0x15a1c20`）。 ack 发送到窗口 `+0x638` 上的每个活动节点；如果没有，则不发送任何内容，并且字节被清除（`0x15a1eb4`、`0x15a1fd8..0x15a1ff8`）。插槽 11 也在数据路径 (`0x15a0298..0x15a02b8`) 上运行，因此 ack 与数据一起运行。

朱在`0x6f03a8`（初始化）、`0x6f0238`（每条传递的消息一步）和`0x6f1734`/`0x6f176c`中写入窗口`+0x18`的基数，在空槽上向窗口中的目标行走
`+0x20`（`0x6ef228` 为 -1，负值时不行走，在第一个占用的槽处停止）。接收函数 `0x6efc2c` 在窗口检查之前将标头反序列化为 `sp+0x18`（`0x6efdc8`，
`MessageHeader` vfunc3); `0x6eff24`/`0x6eff28`复制其`lowest pending`（标题`+0x6`，
`[sp+0x26]`) 至窗口 `+0x20`，`0x6eff2c` 处的行走将底座和环头向上推进至
`lowest pending - base` 插槽。

因此，发送者自己的 `lowest pending` 驱动对等方的接收基础。在发送者的下一个序列上方声明，它将基址移动到尚未发送的消息，然后到达其下方，并在 `0x6f03cc` 处通过确认被丢弃：模拟的朱站在基数 8 处丢弃主机的提交（序列 7），并且 BDSP 游戏机将主机的序列 5 和 6 确认为 `(7, 7)` 和
`(8, 8)` 并且从未交付。确认在标头和条目的第二个半字中携带发送者自己的最低未确认序列。
<a id="who-a-window-sends-to-pia-6"></a>
### 窗口发送给谁 (Pia 6)

`ReliableSlidingWindow` 的目的地是窗口 `+0x40` 上的站指针，按站索引，大小为 `[[0x46d0860]]+0x50` (朱 4.0.0 `main`)，由 Pia 在没有游戏代码的站事件上填充。唯一的非空存储是 `0x6ef588` 中的 `0x6ef69c` (`str x23, [x8, x25, lsl #3]`)，它在索引处注册一个站；空值存储在 `0x6ef3dc`、`0x6ef4e0`、`0x6ef9b4` 中。 `0x6ef588` 在以下情况下拒绝：

|拒绝|代码|
|---|---|
|窗户无容量，`[w+0x28]` 零 | 0x1040c |
|电台为空，是窗口自己的`[w+8]`，或者索引是窗口自己的`[w+0x10]` |没有读过|
|索引已被占用| 0x10407 |
|索引的每站记录 (window vfunc `0x40`) 已设置字节 `+0x1f` (`0x6ef650`..`0x6ef664`) | 0x10408 |
|该电台已在另一个索引中注册 | 0x10408 |

成功后，它会重置该记录（vfunc `0x10`），将索引写入 `+0x24` 并从 `w3` 写入 u16
`+0x26`，并设置`[w+0x74]`中的索引位。它的调用者是 slot-11 站事件方法：`0x6e6288`、BroadcastReliableProtocol (0x80)、
`bl` 位于 `0x6e630c`，首先由 StreamBroadcastReliableProtocol 的插槽 11 `0x6f51a8` (`0x6f51bc`) 调用；和 `0x6ee528`，ReliableProtocol (0x7C)，请致电站点 `0x6ee5d4`。 `0x6e6288` 通过事件 `+8` 的 id 查找事件的电台（`[[0x46d0860]]` -> `0x1e7c4e8` -> vfunc `+0x38`），并在协议自身电台索引为 0xfd 时返回（`0x6ec4f0`）或该站是它自己的（`0x6ec4a8`，针对`[station+0x30]`）。事件 0 在索引处寄存器 `[station+0x30]`
`[station+0x28]` 与 `[station+0x38]`；事件 1 删除索引 (`0x6ef75c`)。

只有在其加入事件之前、离开之后，当协议具有站索引 0xfd 时，或者当 `0x6ef588` 拒绝它时，站才会从列表中丢失。批量确认编译器 `0x6f2138` 读取相同的列表：它会跳过空值 (`0x6f2324`..`0x6f232c`) 并在检查其 ack 状态后设置站的标头目标位 (`0x6f22f8`..`0x6f230c`)，回退到调用者的掩码（`0x6f2360`..`0x6f2370`）。 ack 中的一个位显示窗口注册了该站，但没有显示发送给它的消息。
<a id="version-4-1"></a>
### 版本 4

一个标头类服务于 0x7C 和 0x80：`nn::pia::transport::ReliableSlidingWindow::MessageHeader`（GetSize `0x0184e480`、反序列化 `0x0184e390`、序列化 `0x0184e230`）。

    0x0  1  flags
    0x1  1  stream id
    0x2  2  payload size, big-endian    refused at 0x589 and above (0x0184e3cc)
    0x4  2  sequence id, big-endian
    0x6  2  lowest sequence id pending ack, big-endian
    0x8  1  destination count           refused at 0x20 and above (0x0184e404)
    0x9  8 * count  station constant ids, big-endian

`GetSize` 是 `9 + 8 * count`。这两个版本仅在计数 0 处一致，即双方发送的每条 0x7C 消息，因此版本 9 的解析器读取 221887 条版本 4 消息，没有一个字段不在位。

接收路径（`0x01859338`）默默地拒绝五件事：

    0x0185952c   payload size <= 0x57F - 8 * count     tighter than the deserialiser's own bound
    0x0185954c   the Pia message length equals 9 + 8 * count + size exactly
    0x0185956c   the stream id is the window's own for this station, [w + 0x18*st + 0x46]
    0x01859578   a count above 0 is a list the receiver must find itself in; count 0 is unfiltered
    0x01859ca0   the first message on a stream carries FLAG_IS_INITIALIZED
 它在 `0x01859734` 处的标志上调度：位 5 RESET、位 6 RESET_ACK、位 0 APPLICATION_DATA；其他任何内容（包括无标志）都会转到 ack 处理程序 `0x01859a70`。

当每站字节 `[window + 0x18*station + 0x47]` 为零时，流不存在；第一条数据消息必须携带FLAG_IS_INITIALIZED，并设置流id（`+0x46`）和起始序列（`+0x40`）。游戏机在其第一条消息上发送标志 0x0F，之后发送 0x07。
`reliable4.build_data_message(bytes.fromhex("610000000a00"))` 逐个字节地再现游戏机的序列：`0f0000060001000100610000000a00`。

ack 发票正好是 0x260 字节，即 wiki 的原始“Ack Data”，5.29 替换为计数列表：

    5.29-5.43   1 unknown byte, 1 count, then `count` x 21 bytes
                    u8 stream id, u16be ack id, u16be the window's field 0x50, 16-byte mask
    version 4   32 entries of 19 bytes, always
                    u8 stream id, u16be ack id, 16-byte mask
 处理程序 `0x01859a84` 打开 `ldrh w8, [x2, #0xa]; cmp w8, #0x260; b.ne` 并应答 0x2c03，但不读取正文；串行器 `0x0185bfb0` 循环 0x20 次写入流 id、大端 ack id 和十六个掩码字节作为两个大端 u64 半部分。读取的槽是从处理程序的第四个参数中获取的站索引，站点没有说明其站；插槽的流 ID 必须与窗口的 (`0x01859c1c`) 匹配。 `reliable4.build_ack_payload` 用相同的条目填充每个槽，在任一读数下均正确。

屏蔽会留下它不使用的插槽，在流 id 0 下保存陈旧字节（`22284`、`16`、
`57080`、`2517` 位于插槽 1、2、4、5，而插槽 0 保持 2)。只读已确认流的条目：所有槽的最大值是一个陈旧值，并且跟随它的发送者超出了游戏机的窗口（针对 97 处的窗口发送了 401 条消息），然后停止确认。

在固定的 `lowest_pending` 上不断增长的序列 id 意味着不断增长的积压；测量每条消息的 `lowest_pending` 并根据序列 ID 重新传输。
<a id="protocol-0x80-the-broadcast-reliable-window"></a>
## 协议0x80，广播可靠窗口

`nn::pia::transport::BroadcastReliableProtocol`（vfunc4 `0x0184d880` 返回 0x80），与 0x84 的 `ReliableBroadcastProtocol` 不同的类。它的消息被压缩（版本 4 标志 0x10）：42 字节原始，625 解压缩，目标计数为 1 的可靠标头和 0x260 ack 上的一个八字节站常量 ID（版本 9 的位图规则将给出 621）。网格可以容纳的每个站有一个 slot，按站索引：游戏机用真实的 ack id 填充 0..7，并保留 8..31 零，8 是来自加入响应的 `max_total`。
<a id="protocol-0x81-the-stream-broadcast-reliable-transfer-pia-6"></a>
## 协议0x81，流广播可靠传输（Pia 6）

`StreamBroadcastReliableProtocol` 将一个固定大小的块从一个站点移动到每个需要它的站点，以块的形式（朱 4.0.0 `main`）。插槽10是其更新`0x6f5360`，插槽11
`0x6f51a8`，插槽 17 `0x6e6818`，插槽 19 BroadcastReliableProtocol 的 `0x6e69a0`，它从 `[proto+0x70]` 加载窗口并运行 `ReliableSlidingWindow` 发送循环 `0x6f0638` （`bl` 在
`0x6e69c0`)，带字节预算 `[proto+0x64]`；循环从重传截止时间 `0x6f0d14`（`bl` 位于 `0x6f073c`）开始获取每个时隙的下一次。块通过 `0x6f1994` 入队（`0x6f5c2c`，
`x0 = [proto+0x70]`)，现在在插槽上标记 (`0x6f1bd4`)。 0x81 传输会在与 0x7C 和 0x80 相同的截止日期重新传输，并且不会没有任何目的地的 RTT 样本。

每条消息都携带一个 11 字节的 StreamData 标头，由 `0x6f60e8` 写入：

    +0  1  kind: 0 a receive posted, 1 the first chunk, 2 a later chunk, 3 to 6 control
    +1  1  transfer id
    +2  1  percent of the block delivered after this chunk
    +3  4  big-endian u32: the receive capacity in a kind 0, zero in a chunk
    +7  4  big-endian u32: the length of the data that follows
    +11    the data
 游戏的发送 API 需要一个缓冲区、一个大小和一个传输 id；它的接收 API 包括发送者、缓冲区、容量和 id，并且发布的接收发送携带容量的类型 0。对于大于 `[proto+0xa0]`、id 0xff 的大小或没有站的 `[proto+0x98]` 字节等于 id 的发送将被拒绝。当 `0x6f1ef8` 找到一个空闲槽时，块循环（`0x6f5b54`..`0x6f5c58`，在 `0x6f5560` 中）排队：
`[window+0x70] - 11` 字节，种类 `(offset != 0) + 1` (`0x6f5bb0`..`0x6f5bbc`)，来自 `+0xa4` 的 id，百分比 `(offset + chunk) * 100 / size` （`0x6f5b78`..`0x6f5b98`），也保存在`+0xba`。

接收循环 `0x6f5cdc` 在 `0x6f5560` 之后的更新中调用，使用 BroadcastReliableProtocol vfunc13（`0x6e644c`，发送者位于 `sp+0xb80`）拉取每条消息，使用 StreamData vfunc3 (`0x6f635c`) 解码标头，解析发送者的索引为`0xe42ddc`，并通过`0x3c0d5e5`处的字节表打开类型，忽略6以上的类型：

|善良|目标|接收者做什么 |
|---|---|---|
| 0, 接收发布 | `0x6f5e5c` |在其自身状态 1、2、4、5、8、9 或 10（掩码 0x736）中，将发送者标记为 `[+0xc0]`；否则 (`0x6f6094`) `[+0x98][sender] = id` 和 `[+0xa0] = min([+0xa0], capacity)` |
| 1、第一个块 | `0x6f5e90` |清除接收到的计数 `+0xac` 和 `+0xba`，状态 4 至 5，然后为种类 2 |
| 2、块| `0x6f5eb4` |仅在状态 5 中，对于来自发送者 `+0xb0` 的 ID `+0xa5`：如果适合 `+0x90`，则将数据复制到 `[+0x88] + [+0xac]`，添加其长度，将百分比保持在 `+0xba` |
| 3、发件人忙拒绝接收 | `0x6f5f2c` |仅在状态 4 中：重置传输，每个 `[+0x98]` 到 0xff，状态 7 |
| 4、发件人取消| `0x6f5f9c` |重置传输，每个 `[+0x98]` 到 0xff，状态 0xC |
| 5，接收方取消 | `0x6f6000` | `[+0x98][sender] = 0xff`，在 `[+0xc8]` 中标记发送方 |
| 6、发送方确认取消| `0x6f6024` |仅在状态 0xA 中：复位，状态 0xB |

控制类型带有 ID 0xff。更新 `0x6f5560` 将类型 3 发送到 `[+0xc0]` 中标记的站（`0x6f6268` 与 `w2 = 3`、`0x6f5750`），将类型 6 发送到 `[+0xc8]` 中标记的站(`0x6f57d8`)，在状态 9 种类 5 中发送至预期发送者 `[+0xb0]`（`0x6f5904`，通过 `0x6f1de8` 单播），然后状态 0xA，并在状态 8 种类 4 中发送至其目的地 (`0x6f5984`)。发布的最小容量限制了发送 API 接受的块。

`+0x78`（`0x6f53b0`）处的状态：当`+0xba`到达0x64（`0x6f5460`）时，接收从5变为6；当 `[+0x98]` 的条目等于 `+0xa4` 并且窗口报告序列 `+0xb8` 已确认（`0x6e7128`、`0x6f54e4`）时，从 2 发送到 3，并且向 0xC 发送没有匹配的条目。
<a id="protocol-0x84-the-reliable-broadcast-transfer"></a>
## 协议0x84，可靠的广播传输

`nn::pia::transport::ReliableBroadcastProtocol`携带剑／盾的交换快照：

|善良|意义|
|---|---|
| 0x11 / 0x12 |数据片段；计数器位于 [4]，容量位于 [10] |
| 0x19 |转移完成 |
| 0x21 |带有连续基址和提前到达的位掩码的 ack |
| 0x28 |答案0x19 |

从未应答的接收者永远不会看到最后三个，并且发送者不断重传（没有测量限制）。
`pokeldn/ldn/broadcast4.py`。游戏机在端口 0 上发送自己的传输，并在端口 1 上确认对等方的传输。
<a id="unresolved"></a>
## 未解决

- 实机《剑》在 17 字节连接响应的 `[0x37]` 读取什么，即消息末尾之外 38 字节、发送方未写入的内容：实机 12 次全通过，ldn_mitm 下模拟《盾》1.3.2 的 52 次中通过 3 次。
- 实时拒绝交给等待上下文（`0x01769720`）的具体错误码；除零值检查外，未找到后续读取方。

<a id="credits"></a>
## 学分

标头版本表、会话密钥派生和随机数布局来自 [NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki/Pia-Protocol)（其
`Pokemon-Brilliant-Diamond.md` 说明游戏密钥的推导； `Pia-Game-Keys` 仅列出派生密钥；搜索它是在 [Switch 游戏逆向分析](switch_re.md))。哪个派生属于哪个网络类型，`cryptoKeyDataSeed` 值和版本规则是从零售标题自己的代码中读出的。
