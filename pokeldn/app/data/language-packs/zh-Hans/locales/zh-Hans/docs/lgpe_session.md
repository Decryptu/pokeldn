
<a id="the-cartridge-its-keys-and-the-session"></a>
# 卡带、其密钥和会话

地址是 Let's Go 皮卡丘 1.0.2 的解压缩 `main` 中的偏移量，如 `tools/switch/nso_read.py` 所示：文本 `0..0xd32ba8`、来自 `0xd33000` 的rodata、来自 `0x1527000` 的数据。

<a id="what-the-title-is-built-from"></a>
## 标题是根据什么构建的

更新NSP携带程序NCA `2b7730a9e56498bbafac2002d4908c6b`（标题`010003f003a34000`，权利ID `010003f003a348000000000000000007`，密钥生成6）。其执行者持有`main`（13.0 MB压缩）、`rtld`、`sdk`、`subsdk0`和`subsdk1`；每个 `nn::pia` 和 `gflnet3` 参考都在
`main`。

    ./.venv/bin/python tools/switch/xci_read.py "<the .nsp>" --keys prod.keys \
        --nca 2b7730a9e56498bbafac2002d4908c6b --exefs 0 --extract main
    ./.venv/bin/python tools/switch/nso_read.py main main.bin
    ./.venv/bin/python tools/switch/rtti_names.py main.bin 0xd32ba8
 Pia 是静态链接的：269 个 `nn::pia` 类，2112 个命名虚拟方法。 `nn::pia::local` 包含 `Ldn*` 和 `Local*` 系列（`LdnCreateNetworkJob`、`LdnCreateSessionSetting`、
`LdnJoinSessionSetting`、`LocalProtocol`）。 `nn::ldn`是从nnSdk导入的（`CreateNetwork`，
`Connect`、`Scan`、`SetAdvertiseData`、`GetSecurityParameter`、`*Private` 变体）、GOT 插槽
`0x15fa1e0..0x15fa2a8`。在 Pia 之上，`gflnet3` 捆绑了协议缓冲区 (`lib/gflnet3/external/include/google/protobuf/`)。

<a id="the-ldn-passphrase"></a>
## LDN 密码

    W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL
 64字节，`0xf73a50`，原始使用，与剑和盾相同。两个调用站点以文字长度 `0x40` 传递它：

    0x004db6b4  adrp x1, #0xf73000 ; add x1, x1, #0xa50
    0x004db6c4  mov  w2, #0x40
    0x004db6c8  bl   #0x5c0fb0              LdnCreateSessionSetting passphrase setter

    0x004dbba4  adrp x1, #0xf73000 ; add x1, x1, #0xa50
    0x004dbbb0  mov  w2, #0x40
    0x004dbbbc  bl   #0x5c1280              LdnJoinSessionSetting passphrase setter

`LdnCreateNetworkJob`（构造函数`0x5ce640`，剑的偏移量）将密码短语保留在+0xC4，其长度保留在+0x104，并从它们之前构建`nn::ldn::SecurityConfig`
`nn::ldn::CreateNetwork`（`0x5ce988`，PLT 存根 `0xd31c78`）。

<a id="the-pia-game-key"></a>
## Pia 游戏密钥

    p1frXqxmeCZWFv0X
 `0xefd659` 处有 16 个 ASCII 字节，维基百科列出的剑／盾、传奇：阿尔宙斯和朱／紫的文字键。一个调用站点将其存储到加密设置中，以模式字段为条件：

    0x0011a364  ldr  w9, [x19, #0x98]
    0x0011a368  orr  w9, w9, #2 ; cmp w9, #2 ; b.ne   (mode 0 or 2 takes the key)
    0x0011a374  adrp x9, #0xefd000 ; add x9, x9, #0x659
    0x0011a380  ldp  x10, x9, [x9]
    0x0011a384  stp  x10, x9, [x8]          x8 = setting + 0x24c

<a id="the-pia-header"></a>
## Pia 头

版本 3（维基百科的 Pia 5.11-5.17）。初始化器 `0xd122d4` 将 magic 和 version 写入一个 64 位存储，`0x00000003_32AB9864`；验证器 `0xd12400` 检查魔法并
`(byte & 0x7f) == 3`。

    0x00  4  magic 0x32AB9864, big-endian
    0x04  1  0x80 (encrypted) | version (0x7F) = 3
    0x05  1  connection id
    0x06  2  packet id
    0x08  8  AES-GCM nonce
    0x10  16 AES-GCM tag, not truncated
    0x20     ciphertext
 wiki的5.11-5.21布局，剑的版本4但针对版本字节； `pokeldn/ldn/pia4.py`。

<a id="the-message-framing"></a>
## 消息框架

固定的 22 字节消息头（Pia 5.11-5.12；5.18 及更高版本带有存在标记）。
`ProtocolMessageAccessor::Header`的解串器`0x5ae870`拒绝少于`0x16`字节；写入器 `0x5aeb00` 在字节 1 处存储文字 1。

    0x00  1  message flags: 1 = destination is a bitmap, 2 = relay needed, 4 = relayed, 8 = unbundled
    0x01  1  version, always 1
    0x02  2  payload size, big-endian
    0x04  1  protocol type
    0x05  1  protocol port
    0x06  8  destination, big-endian: a constant id, or a station bitmap when flag 1 is set
    0x0E  8  source constant id, big-endian
    0x16     payload, then padding to a multiple of 4

`pokeldn/ldn/pia3.py` 通过 pia4 的标头实现它。

<a id="the-session-key"></a>
## 会话密钥

`LocalProtocol` 的派生 `0x5cd560` 是 BDSP 和 剑 的：从一个 32 位值（`0x57cfc0`，围绕 `0x6C078965` 循环）播种 SEAD xorshift128，四次抽取到 16 个字节，游戏密钥下的 AES-128-ECB `LocalProtocol+0x49c`（启用标志+0x498）。
`pokeldn.ldn.pia5.ldn_session_key`。

广告的应用程序数据（Pia 5.9-5.18）以 24 字节标头打开：

    0x00  4  network id, random per session
    0x04  4  CRC32 of the user password
    0x08  1  system communication version, 4 for 5.11-5.17
    0x09  1  header size, 0x18
    0x0A  2  padding
    0x0C  4  session param
    0x10  8  zero
    0x18     the game's application data
 种子是 +0x0C 处的会话参数。来自 Let's Go 皮卡丘主机的 392 个数据报中的 392 个在 `ldn_session_key(game key, session param)` 下使用 pia4 IV 进行身份验证（三个字节
`crc32(network id little-endian || host MAC)`，源 ID 字节 0，八字节标头随机数）。

<a id="the-link-code"></a>
## 链接代码

链接代码为NetworkInfo场景id；应用程序数据 +4 处的密码 CRC32 保持为 0，SSID 保持为 `01000000000000000000000000000000`。场景id为`1000a + 100b + 10c + 1`，在选择器中分别选择其索引（皮卡丘0、伊布1、妙蛙种子2、小火龙3、杰尼龟4、波波5、绿毛虫6、小拉达7、胖丁8、地鼠9）。

它是在运行时构建的：`0x891580` 将选择折叠到 `100a + 10b + c`，`0x978080` 计算
`10 * number + mode`，交换模式 1（模式 2 和 3 来自 `0x9765f4` 的交换机，其功能未读）。该值将 `0x349010` 和 `0x4da710` 传递给会话构造函数 `0x4db1e0`（`u16` 位于 `+0x302`）； `0x4db6ac`放入`LdnCreateSessionSetting+0x60`中，Pia将其复制到
`NetworkConfig.intentId.sceneId` 之前的 `nn::ldn::CreateNetwork` (`0x5ce988`)。

相同的构造函数选择搜索游戏机所在的频道：`{1, 6, 11}[scene % 3]`，表
`0xf73a44`，索引为`0x4db248..0x4db254`； `pokeldn.lgpe.search_channel(code)`。

|编写一个搜索到的游戏机 |广告场景 ID |频道 |
|---|---|---|
| 皮卡丘，皮卡丘，皮卡丘 | 1 | 6 |
| 妙蛙种子, 小火龙, 杰尼龟 | 2341 | 6 |
| 妙蛙种子、小火龙、妙蛙种子 | 2321 | 11 |
| 伊布、皮卡丘、地鼠 | 1091 | 11 |
| 皮卡丘, 皮卡丘, 妙蛙种子 | 21 | 1 |

仅当搜索游戏机在其自己的频道上通告该游戏机的场景ID时，该搜索游戏机才加入另一个网络。 `bin/lgpe_host.py --code NAMES` 托管在代码的通道上（`--channel auto` 扫描游戏机的网络）； Let's Go 皮卡丘和 Let's Go 伊布加入其中。 `bin/lgpe_join.py` 不发送代码，游戏主机与其进行交易。

<a id="the-local-protocol-measured"></a>
## 本地协议，测量

会话状态在 Pia 协议 0x24、端口 0 上发出，就像在 BDSP 和 剑 上一样：wiki 的 5.7-5.45 更新会话消息 (`pokeldn.ldn.local_protocol.parse_update_session`)。 12字节本地头（版本1，类型0x11），序列id，本地网络id，主机变量id，服务变量id和常量id，允许参与字节，八个节点（IPv4地址，端口，迁移排名）：主机`169.254.105.1`排名0，加入方`169.254.105.2`排名1、其余255。

主体携带主机常量 id 小端 (`000048f120229beb`,
`station_protocol.ldn_constant_id` 通过 MAC `48:f1:eb:20:9b:22`)； Pia 消息头将其大端字节序作为源 (`eb9b2220f1480000`)，与 剑 上一样。

<a id="the-station-protocol-for-a-mesh-join"></a>
## 站协议，用于网状连接

协议 0x14 上的连接请求，然后 0x18 上的网状连接。连接请求处理程序
`0x5b8800`读取wiki的5.10-5.18布局，station-protocol版本9：

    [0]     message type            1
    [1]     connection id
    [2]     version number          must be 9 (`cmp w8, #9` at 0x5b8848; 5.27-5.45 checks a platform)
    [3]     is inverse connection request; rejected above 1
    [4]     target constant id      big-endian u64, compared against the console's own at 0x5b6830
    [0xC]   target variable id      big-endian u32, checked only when [3] is 1 (0x5b6840)
    [0x10]  inverse connection id   compared against the station's own record at +0xA0
    [0x11]  station location        the 5.11-5.45 layout, unchanged from Sword
    [...]   ack id                  u32, the message size minus four
 剑 的版本 4 请求（平台字节位于 [2]，移位标志位于 [3]）和 5.29-5.45 布局（协议列表位于 [1]）将每个字段放置在错误的位置。目标常量 id 是游戏机自己的，来自其 MAC；方加入的位置携带其常量ID、变量ID和服务变量ID。

零售 Let's Go 皮卡丘运行完整的版本 9 序列，其中反向连接请求已在 5.27 中删除：

    ->  connection request (type 1, is_inverse 0, target the host constant id, own location)
    <-  type-5 ack; inverse connection request (type 1, is_inverse 1) to the joiner's constant and
        variable ids, with the host's location and a trailing ack id
    ->  type-5 ack; connection response (type 2, result 0, host constant id at [5], variable id at
        [0xD], gate byte 1 at [0x37], padded to 0x38)
    <-  connection response (type 2, result 0, 840 bytes, platform 4, the joiner's ids, a network
        id, one player info), repeated until acknowledged
    ->  type-5 ack
 连接响应解析器 `0x5b9270` 读取 `[1]` 结果，`[5]` 是一个大端 u64 和
`[0xD]` 是针对其自己的 ID 的大端 u32，而 `[0x37]` 是门字节，当 5 或更多时，结果 0 路径会下降。

<a id="the-connection-response-a-station-sends"></a>
### 站发送的连接响应

0x348 字节（解析器接受 0x3C）：

    0x00  1  message type 2
    0x01  1  result
    0x02  1  version 9
    0x03  1  platform 4
    0x05  8  the receiver's constant id, big-endian
    0x0D  4  the receiver's variable id, big-endian
    0x31  4  the network id, big-endian: the advertise data's first u32, read little-endian
    0x35  2  01 01
    0x37  0xC3  a PlayerInfo: the station name "username", then the Switch profile's nickname,
             then the language. Its first byte is the gate the parser drops when 5 or more
    0x344 4  the ack id
 PlayerInfo是`station_protocol.player_info`构建的195字节结构；实机用其配置文件名称填充它。 `station9.build_connection_response(..., network_id=N,
player_name=B)`; `bin/lgpe_join.py --player-name NAME`（`--short-response` 发送 0x3C 字节）。

连接请求中的方加入站位置为 36 个字节：一个空公共地址（零端口）和零 NAT 标志和位置，`station_location(..., public=False, nat_flags=0,
nat_location=0)`。

<a id="joining-the-mesh"></a>
## 加入网格

0x18（`mesh_protocol.build_join_request`，类型 1，本地站索引 253，尾随 ack id）上的网格加入请求绘制加入响应：类型 2，148 字节，两个站，主机索引 0，加入索引 1，一个片段，两个位置的两个站信息，最大活动 2，最大总数 8。然后主机广播更新网格（类型0x20，524字节，更新计数器1)。加入响应由 0x14 (`mesh_protocol.ack_for`) 上的 type-5 ack 确认；方加入是站索引 1。

然后，主机传输本地协议更新会话 (0x24，用 0x21 确认)、RTT (0x58)、同步时钟 (0x1C) 和克隆 (0x73)。方加入会应答每个请求，并从就座那一刻起发送自己的 RTT 和同步时钟请求。

<a id="the-rtt-protocol-0x58-version-3"></a>
## RTT 协议 (0x58)，版本 3

16 个字节：[0] 处的大端 u32（剑 上的一个字节），发送者的 19.2 MHz 系统在 [8] 处标记为 u64。响应复制类型 1 的刻度。每个站大约每秒请求一次。

    00000000 00000000 0000000049845557     request
    00000001 00000000 0000000049845557     the answer to it

`rtt_protocol.build_v3` 和 `response_for_v3`； `bin/lgpe_join.py --connect` 双向运行（`--no-rtt` 将其关闭）。

<a id="the-sync-clock-protocol-0x1c"></a>
## 同步时钟协议（0x1C）

主机控制的单调网状时钟（维基同步时钟协议）。站点每两秒请求一次，并将往返行程的一半添加到主机回复的值中。

    request, 16 bytes   [0] u64 the sender's system tick (19.2 MHz), [8] u64 zero
    reply,   16 bytes   [0] u64 the tick copied back, [8] u64 the mesh clock in milliseconds
 加入方在网格加入响应之后立即发送其第一个请求。克隆协议时钟就是这个时钟；一个主机在加入方自己的正常运行时间内给出克隆消息，释放克隆并离开。 `pokeldn.ldn.sync_clock`; `bin/lgpe_join.py --connect` 运行它（`--no-sync-clock` 停止）。

Keep-alive是协议0x08，无正文，以实物形式回答。

<a id="the-reliable-protocol-0x7c-where-the-games-data-is"></a>
## 可靠协议（0x7C），其中游戏数据为

Pia 5.11的头部为24字节（5.29-5.43中为9或13）；两个站上的 32 位序列 ID 均从 0xFFFFF82F 开始。

    0x00  1  flags
    0x01  1  stream id, 3 for the game's stream and 0 on an acknowledgement
    0x02  2  payload size, big-endian
    0x04  4  zero
    0x08  4  sequence id, big-endian
    0x0C  4  the next sequence id expected from the peer, big-endian
    0x10  8  zero
    0x18     the payload
 确认是单独的标头、流和大小为零。 `pokeldn.ldn.reliable3`。轮椅是游戏的框架（下面的“可靠协议上的游戏消息”）。

<a id="the-clone-protocol-0x73"></a>
## 克隆协议 (0x73)

`nn::pia::clone::CloneProtocol`（GetProtocolId `0x158aab8`；SDK 字符串 `PiaCommon-5_11_4`）携带合作伙伴同步。类型字节`0xAB`：高半字节结构，低半字节的一种变体。每条消息都以版本 3、类型和发送者的帧计数器作为大端 u16 开头（从发送者的 Pia 会话开始每秒大约 60 个）。在 Ryujinx 下通过 ldn_mitm 的两个 Let's Go 皮卡丘 1.0.2 端点之间进行测量；双方运行相同的状态机。

<a id="clock-sync-the-first-two-seconds"></a>
### 时钟同步，前两秒

双方每秒大约发送 5 次时钟请求（类型 0x11，18 字节，串行器 `0x51f9b0`），并通过回复回答对方的请求（类型 0x21，22 字节，`0x51fab0`）。

    clock request                              clock reply
    [0]   1  version 3                         [0]   1  version 3
    [1]   1  type 0x11                         [1]   1  type 0x21
    [2]   2  sender frame counter              [2]   2  sender frame counter
    [4]   4  sender message count              [4]   4  sender message count
    [8]   2  destination station bitmap       [8]   2  destination station bitmap
    [0xA] 8  sender system tick                [0xA] 4  sender clone clock, ms
                                               [0xE] 8  the request's system tick, echoed

- 消息计数是每个发送者在其时钟请求、回复和参与中的一个计数器，从 1 开始。
- 位图是目的地，`1 << station index`：主机（0）发送0x0002，加入方（1）0x0001。回复将发送给请求者。
- 刻度为发送者的`os::GetSystemTick`，19.2 MHz；回复只会回应请求的勾选，除此之外没有任何其他内容。
- 克隆时钟是自发送者的克隆协议启动（元素 +0x14）以来的毫秒数，大约在第一个请求之前 60 毫秒。时钟为零的回复留下实机请求。

<a id="participate"></a>
### 参加

在十个应答请求后，加入方发送一个参与（类型 0x31，10 字节，序列化器
`0x51fbd0`)：标头、消息计数、位图 0x0003。主机用 0x33、位图 0x0002 进行应答，然后发送自己的参与，加入方用 0x33、0x0001 进行确认。从第一次参与开始，时钟回复的类型为 0x22。

<a id="clone-elements"></a>
### 克隆元素

克隆由克隆类型（1 到 4）、所属站（如果没有则为 0xFD）和 32 位克隆 ID 来键入。两个电台都发布自己的副本。在第一个交换中，随着交换屏幕的推进，主机创建 ids 1、2、3；每一次后来的交换都会宣布更多。双方都参与后，克隆类型 3 id 0 就存在。

    every command message   [0] version 3, [1] type, [2] u16 the sender's frame counter,
                            [4] u8 clone type, [5] u8 owning station, [6] u16 0,
                            [8] u32 clone id
    types 0x81 to 0xc4      [0xC] u32 the sender's message count, [0x10] u16 destination bitmap,
                            then the structure's own fields
    types 0xd1 to 0xf4      [0xC] the data, with no message count and no bitmap
 低半字节是命令标记加一：1 宣告（`SendClone::AnnounceCommandToken`，
`0x522480`)、2个请求(`ReceiveClone::RequestCommandToken`、`0x520df0`)、3个结束(`SendClone::EndCommandToken`、`0x522490`)、4个锁定(`AtomicSharingClone::LockCommandToken`、
`0x517820`）。高半字节是结构体； `0x51c110` 通过表 `0xf769c4` 进行调度：

|类型 |补充 |消息，长度 |接收案例 |
|---|---|---|---|
| 0x8N | 0x8N什么都没有| 0x12 | `0x51c614` |
| 0x9N | 0x9N [0x12] 处的 u32 时钟（以毫秒为单位）|时钟克隆命令消息，0x16 | `0x51c62c` |
| 0xaN |时钟，[0x16] 处的 u8 计数，一个 u8 和一个 u16 |时钟和计数，0x1a | `0x51c64c` |
| 0xbN | 0xbN时钟，u32 参与者位图，位于 [0x16] |时钟和参与者，0x1a | `0x51c66c` (`0x51c680`) |
| 0xcN |时钟、计数、位图 [0x1A] |时钟和计数和参与者，0x1e | `0x51c68c` |
| 0xeN | 位于 [0xD] 的 zlib 数据流 | 克隆方的状态，进行确认 |  |
| 0xfN | 0xfN [0xD] 处的一个字节，[0xE] 处的 zlib 流 |克隆的状态及其数据 | |

zlib 流膨胀为一条记录：标签 0x20、其长度、u16 克隆 ID，副本为空时为 1，满后为 3：

    0x20 0x06 u16 clone id  0x01  0x00
                                          a copy with nothing in it yet
    0x20 len  u16 clone id  0x03  u8 the station the data belongs to  u16 0
              u16 participant bitmap  u32 clock  then the clone's data
    0x20 0x0A u16 clone id  0x05  u8 the station being acknowledged   u32 clock
 A站先发布六字节表格，后填写填充表格；六字节形式是正在重试的发布，并且已确定的会话不会构建任何记录。 deflate 是一次压缩、一次同步刷新和 2 至 5 级的最终空块； `clone.pack_record` 再现每个捕获的流。 [0xC]处的0xfN头字节携带记录的参与者位图，0xeN头是它所确认的站。

|交流|留言 |
|---|---|
|业主宣布| 0xa1和0xb1与参与者位图；数据之前的其他答案 0xa2 和 0xc1 |
|接管|另一个答案是 0xa1 与 0x91 |
|数据|所有者的0xf3；另一个具有相同时钟的0xe3 |
|发布 | 0x83; 0x84 承认 |
|离开克隆会话 | 0x32; 0x41（14字节，应答者位图位于[0xA]）；无人应答的 0x32 会重复，直到游戏放弃 |

0xa2 携带网格时钟和计数，克隆类型 4 为 1，克隆类型 2 为 0。

`ClockAndCountCloneCommandMessage`（虚表`0x158ac58`，序列化器`0x51f4c0`）写入，大端，
`+0x1c`（时钟）位于[0x12]，`+0x20`（计数）位于[0x16]，`+0x21`位于[0x17]，`+0x22`（u16）位于[0x18]。计数是克隆的 vfunc 16：对于 SendClone (`0x519290`) 为 0，对于 ReceiveClone (`0x520de0`) 为 `+0x112`，对于 AtomicSharingClone (`0x517800`) 为 `+0x188`。字节 `0x17..0x19` 是堆栈残留，没有接收器读取：构建器（`0x51b3b0`、`0x51cb64`、`0x51ccf0`、`0x51cd8c`）不存储超过计数的任何内容，并且清除器 `0x51b380` 重用其 0xbN 路径的缓冲区在那里留下一个参与者词（`0x51b7a0`），因此 `01 2808ab`。 `0x51c110` 就地解析；每个陷阱都从接收循环 `0x51ad90` 或环回（`0x51e330`、`0x51e4c4`）到达它。

`0x51c110` 读取公共头（`0x51c2c0`：`[8]`、`[4]`、`[5]`），对于 0x80..0xc0 字节组
0x10-0x11（`0x51ce80`，表`0xf76e08` -> `0x51ced0`），那么上面表中的字段就不再赘述了。克隆类型表 `0xf769e4`（索引 `[4] - 1`）将 0xa1 和 0xa2 路由到采用克隆、站和时钟的处理程序，而不是缓冲区：

|克隆类型| 0xa1 | 0xa2 |
|---|---|---|
| 1 | `0x51c714` -> `0x51cb38`, `0x522350(clone, station, clock)`;未知克隆画出 0x91 |被忽略 |
| 2 |忽略（`0x51c3b8`）| `0x51cafc`、`[5]` 必须是本地站、`0x520ce0(clone, clock)` |
| 3 | `0x51c934` -> `0x51cc00`, `0x522a60` | `0x51c838`，`0x522b20(clone, station, clock)` |
| 4 | `0x51c8c0` -> `0x51cbc4`, `0x522a60` | `0x51c838` |

携带缓冲区的前向调用（`0x51c268`、`0x51c2fc`、`0x51c32c`、`0x51c784`、`mov x3,x22;
b 0x51d450`）服务于其他消息类型。

`0x522a60`，克隆类型 3 和 4 的 0xa1 处理程序，当元素状态时返回 1
当 `[[x0+0x30]+0xc0]` 中设置了发送者位时，`[x0+0x38]` 不是 1、2，否则记录电台并返回 0。主叫方使用 `0xfd04` 类型的 0xa2 应答 0（克隆类型 3 上为 `0xfd03`，
`0x51cd00`)，1 个带有 0x91 (`0x51cbe4`)，2 个什么都没有。未知克隆的 0xa1 绘制
直接0x91（`0x51c494`）。 `0x51c110` 在目的地检查 `0x51ce80` 处静默丢弃，每个发送者计数过滤器（`0x51c1e0`：`proto+0x714+4*station` 处的计数至少是消息的
`[0xC]`），以及长度和类型范围检查。

掩码 `+0xc0` 属于克隆协议对象，除了其站掩码 `+0x38` 和状态字 `+0x40` 之外：

|活动 |对`+0xc0`的影响|地址 |
|---|---|---|
|状态变为`0x22`（当`[[proto+0x48]+0x24]`为2至4时）|设置为 `+0x38` | `0x51b060..0x51b06c` |
|状态变为`0x42` |设置为 `+0x38` | `0x51b140..0x51b150` |
| 站点在状态 `0x22` 或 `0x31` 下加入 | 设置其对应位 | `0x51bc64..0x51bc88` |
|状态为 `0x31` 或 `0x22` 的 10 字节 0x33 |发送者位已清除| `0x51c354..0x51c3b4` |
| 14 字节 0x41，其中 `[0xa..0xd]` 等于 `[proto+0x3c]`，状态为 `0x42` |发送者位已清除| `0x51c380..0x51c3b4` |
|车站开出|其位已清除 | `0x51bce0..0x51bce8` |
|车站离开状态为 `0x42` |设置为 `+0x38` | `0x51bd04..0x51bd18` |
|其他路径 |归零| `0x519a1c`、`0x519ccc`、`0x51a2d4`、`0x51a7d0`、`0x51a9c0` |

在状态 `0x22` 中，协议等待掩码为空，然后再移至 `0x31` (`0x51b074..0x51b084`)。

<a id="the-clone-0-pair"></a>
### 克隆0对

克隆类型 3 上克隆 0 的所有者用 0xa1 和 0xb1 来宣布它；对方站回答0xa2和0xc1，然后所有者才发布。没有应答的实机主机（`bin/lgpe_join.py` 上的 `--withhold-clone0-answer`，仅测试）在第一个 0xa1 后 114 毫秒再次发送 0xb1 和 0xa1，并在此后 108 毫秒单独发送 0xb1，并且重复得到答案。发送该对一次并丢失答案的主机将游戏机留在“vous allez bientôt être connecté”上，没有任何过去的时钟流量。 `bin/lgpe_host.py` 每 110 ms 重复一次该对，最多 20 次，直到游戏机的 0xa2、0xc1 或 0x91 到达。已回答第一对的实机（启动器上的 `--ignore-clone0-answer` 忽略它，仅测试）回答重复
0xa2。

<a id="the-games-messages-on-the-reliable-protocol"></a>
### 可靠协议上的游戏消息

`0x7c` 上的每条消息都由 16 字节头部和消息体组成：

```
+0x00  4  kind: the channel id, 1 to 4 in one trade
+0x04  4  body length: 0x168 for kind 1, 0xe8 for kinds 2 and 4, 4 for kind 3
+0x08  4  step, counting every message a station sends from 1
+0x0c  1  tag, 0 on every trade message
+0x0d  1  destination station index, 0xff for every station
+0x0e  2  zero
+0x10     the body
```

`0x116f30(mgr, kind, buf, len, tag, dest)` 在 `mgr+0x288` 构造头部，步数为 `mgr+0x274` 加一。交换发送方经过 `0x4d94e0`（标签 0，目标 0xff）：`0x34945c`（类型 1）、`0x34a24c`（交换提议）、`0x838300` 和 `0x83838c`（提交）。`0x4d9520` 的两个参数均由调用方提供；其调用方是 `0x9dce94..0x9dede8` 中对战场景的发送函数，其中一个使用标签 3。

接收函数 `0x1171d0` 从队列中取出第一条步数等于对应站点下一步的消息，不限来源站点（`mgr+0x278[station] + 1`、`0x117334..0x117354`），并对取出或丢弃的每条消息计数。如果目标既不是 0xff，也不是本地站点索引 `mgr+0x1288`（会话开始前为 0xfd），或类型没有注册通道（16 项表 `mgr+0x110`、`0x117398..0x1173f8`），就会丢弃消息（`0x11722c`）。其他已注册类型或标签的消息会留在队列中，阻塞其后所有站点的消息。交换接收函数（`0x4d9570`）请求标签 0（`0x11746c..0x117478`）。

类型就是通道 ID，由 `0x116e80` 从每个会话的计数器 `mgr+0x270` 分配，从 1 开始（仅在会话启动时与步数计数器一起清零，`0x116a10`），并由 `0x4d9450` 存入 `chan+0x60`；已注册 16 个通道时（`mgr+0x118 > 0xf`），返回 ID 0。`0x117920` 会移除存活计数 `+0x54` 为零的通道并压紧表。`0x4d9450` 有五个调用方：交换会话对象（`0x3492f8`）、队伍提议对象（`0x349d88`）、同步保存的状态 2（`0x8382a8`）、`0x347e10` 类（`0x3481fc`）以及对战场景（`0x9dce1c`）。交换用前三者注册 1、2、3，再由交换后保存流程重建的队伍提议对象注册 4。每次注册还会通告一个克隆集合（`0x4d94b8`，跳板 `0x11b4c0` 进入 `0x11aec0`），因此克隆 ID 与通道 ID 不同。

这两个上限都不会限制同一连接中的交换次数。计数器是未经检查递增的 u32（`0x116ea4..0x116eac`），线上类型字段也是 u32，因此只有注册 2^32 - 1 次后 ID 才会回绕。16 项限制统计的是存活项：每项持有弱引用句柄（`[chan+0x58]`，由 `0x4d98a0` 创建）；活动会话中，管理器更新 `0x1175d0`（`0x11761c`）每帧调用 `0x117920`，删除通道强引用计数 `handle+0x54` 为零的项。提交通道随同步保存对象（`0x838c40`）销毁，该对象又随保存进程（`0x835000`）在调度器离开状态 3（`0x886670`）之前销毁；提议通道随队伍提议对象（`0x349dfc`）销毁，该对象在提交后释放（`0x886c70`），并由交换后保存流程替换（`0x3445e0`）。一个连接约有四个存活通道。

类型 1，消息体 0x168，为身份记录：存档 MyStatus 块复制到 `obj+0x450`（`0x3493f4`），两个站点均从状态 6 发送，早于接收任何内容。训练家结构为 PKHeX 的 `MyStatus7b`，姓名编码为 UTF-16LE：

```
+0x00  4  trainer id, then secret id
+0x04  1  version: 42 Pikachu, 43 Eevee
+0x05  1  gender
+0x35  1  language
+0x38 26  trainer name, up to the Pokemon name; --trainer-name on both launchers
+0x52 16  Pokemon name
```

按接收玩家生成的礼物从这里读取游戏机训练家（`pb7.first_trainer`、[按接收玩家生成](gift_simulated.md#made-for-the-receiving-player)）。

`pokeldn.lgpe.reference` 附带一份身份数据，来自训练家为 `POKELDN` 的模拟存档。`bin/lgpe_join.py` 默认发送这份数据，并用 `--our-trainer` 替换训练家 ID 对。

类型 2，消息体 0xe8，表示交换提议。站点发布的状态字达到 2 时立即发送；之后每次玩家更换待交换的宝可梦（在盒子中浏览选择），都用下一个步数再次发送。新步数会得到回应；重复步数视为重传，不再回应。

发送方是队伍提议对象（构造函数 `0x349bf0`，大小 0x278 字节，位于 `mgr+0x68`）。其更新函数 `0x34a210` 在 `+0x270` 已置位且 `+0x272` 未置位时发送 `+0xa0` 处的结构，然后清除 `+0x270`。交换界面在选择变化时调用 `0x34a3d0`（`0x8f0c04`、`0x8f0c38`、`0x8f8fb0`、`0x90b87c`、`0x90b8c0`），将宝可梦打包到 `+0xa0`（`0x7294e0`），并在状态允许时设置 `+0x270`：A 0 要求本地状态不是 1 或 2；A 1 要求本地状态为 3 或大于 4；A 2 始终不允许；A 3 表示对方离开（`0x3490c0`）。`0x344620` 在提交后（`0x886c70`）及连接结束时（`0x8869f0`）销毁对象；交换后的常规保存会用新通道 ID 重建对象（`0x8375a4`）。

类型 3，消息体 4，表示提交：由同步保存流程发送的 u32（见下文“提交与交换锁”）。每个站点先发送 1，其中一方收到对方的 1 后发送 2。发送 2 的站点在取出对方的 1 时发送（状态 5，`0x838310`）；状态 6 收到 2 时提交，其他消息体都忽略（`0x83839c`），因此加入方再用 2 回应 2 也能被接受。提交后，站点显示旋转等待图标，没有按键提示。交换未完成时，交换锁会保持设置状态。

类型 4，消息体 0xe8，使用常规保存流程重建的队伍提议对象通道，在交换演出结束、其 `SaveThread`（`0x8377ec`、`0x8375a4`）经过 3000 毫秒后发送，携带下一次交换的选择：先发送站点第一个栏位（与步数 2 的提议逐字节相同），随后每次选择变化发送一条。类型 4 发出前已经保存本次交换；类型 4 开启下一次交换。

从 0 计数的第 r 次交换使用类型 2 + 2r 发送提议、3 + 2r 提交、4 + 2r 结束；最后一个也是第 r + 1 次交换的提议通道（`0x116e80` 用会话计数器分配 ID；调度器每次交换都重新注册两个通道）。实测的两次连续交换中，第 r 次的队伍克隆对为 2 + 3r 和 3 + 3r，提交克隆为 4 + 3r；保存后通告的克隆对属于下一次交换。作为主机时，`bin/lgpe_host.py
--next-offer` 用下一条记录回应主机在后续每次交换中的选择。作为加入方时，游戏主机发送的第一条类型 4 是其第一个栏位：`bin/lgpe_join.py` 用下一份 `--offer` 回应该消息和之后每次选择，用类型 5 回应提交，并将类型 6 视为本次交换结束；最后一条记录结束后不再回应。

两个启动器均在发送或接收到值为 2 的提交消息时写入本次交换的接收记录，因为此时游戏机已提交交换；仅展示后撤回的宝可梦不会写入。

游戏主机执行后续交换的方式与首次相同：首次类型 4 前通告下一对队伍克隆；每次选择对应一个类型 4 步数；确认时通告提交克隆；用类型 5 提交；类型 6 前通告随后一对克隆。`bin/lgpe_host.py --lead` 为 `bin/lgpe_join.py` 模拟游戏主机，主动发送提议并投票；`tests/test_esp32.py` 在两者之间双向各交换两条记录。

一次完整交换的流程，两个站点分别计算自己的步数：

```
step 1  kind 1   identity
step 2  kind 2   the offer, again under a fresh step per selection
step 5  kind 3   commit, body 1
step 6  kind 3   commit, body 2
step 7  kind 4   the first slot, again under a fresh step per selection
```

类型 2 和 4 的消息体是 232 字节的盒子结构：第七世代布局，使用第六世代加密方式。加密常量位于 +0x00，值为零的完整性标记位于 +0x04，校验和位于 +0x06；从 +0x08 开始的四个 56 字节数据块按 `((ec >> 13) & 0x1F) % 24` 重排，再与以加密常量为种子的 16 位 LCRNG 流异或。`pokeldn.lgpe.pb7` 能对捕获的提议完成逐字节一致的往返转换。

状态字位于 `f3` 状态数据的第 12 字节，在站点拥有的每个克隆上依次经过 0、1、2。站点发布 2 并发送类型 2 后，等待对方的类型 2。

<a id="what-gates-the-games-own-first-message"></a>
### 是什么控制了游戏自己的第一条消息

链路交换对象的每帧状态机是 `0x349200`（+0x68 上的跳转表 `0xf4e994`）。状态 6 在没有网络输入的情况下发送第一条游戏消息：两个站在收到任何消息之前间隔 18 毫秒发送该消息。唯一的门是状态 4，`0x11b080`，询问 Pia 通道是否准备好：

- 对象 +0x90 处的 SendClone 报告就绪 (`0x5221b0`)：其元素的参与站 `element+0x3C` 必须全部位于克隆的确认集 `clone+0xA8` 中；
- +0x1258 上的共享克隆以同样的方式报告已准备就绪 (`0x522610`)；
- +0x250 处的每个站条目，每个 0x118 字节一个，其第一个字为 1，+0xD8 处有一个非零字节；
- +0x1430 处的字节（站索引）不是 0xFD（“无”；每个此类路径都返回 0）。

SendClone 的检查是`(element+0x3C & ~clone+0xA8) == 0`，共享克隆的`((clone+0x114 | ~clone+0xA8) & element+0x3C) == 0`;两者共享一个元素。在工作会话中，确认集已填充，`+0x114`排水沟和每个`+0xD8`变为1，而参与集从一开始就已满。站位到达`clone+0xA8`仅通过一个0xa2在来自该站的克隆类型 2 上（`0x51c52c`的跳转表`0xf76c38`进入`0x522350`).

状态 7 将每个到达的第一条消息存储在 `this + node * 0x1C8 + 0xC0` 处，并将它们计数为
`this+0x470`;它自己会循环回来，因此沉默的伙伴将计数保留为一。

<a id="hosting-a-retail-console-to-its-trade-screen"></a>
### 在其交换屏幕上托管实机

加入托管会话的游戏机在加入方层之上需要什么：

- 本地协议主体携带主机的常量 ID 小端。游戏通过站表（`0x1171b0` -> `0x5bbe70` -> `0x5b6130`）解析发送者，而 `0x117334` 处的接收跳过未解析的发送者（节点 0xFD）：使用 id big-endian 游戏机在状态 7 等待，它的屏幕显示它将很快连接。
- 当会话发生变化时，更新会话就会消失，并再次在其后面，而不是在计时器上。   它的节点列表保留一个节点，直到对等方加入网格为止。
- 电台在参与时停止其克隆时钟请求。
- 主机在发布克隆 0 的帧中发布克隆 1；游戏机在数十毫秒后宣布自己的消息（实测为 31 毫秒），等待的主机会输掉比赛并进行角色交换。
- 应答对等方拥有主机的克隆的公告的 `0xa2` 携带来自 `0x81` 后面的 `0xa1` 的时钟，因此它是在解析整个数据报之后构建的。它承载着主机的时钟，让游戏机每半秒重新宣布一次，并且从不发布其副本。
- 两个电台都会用自己的副本回复每个克隆类型 2 发布的内容，整个会话大约每秒 10 次。
- 提议在其执行的步骤下得到答复；在新的步骤下回答会开启新一轮，各站相互回答，永无止境。

<a id="the-two-clone-records-a-trade-walks"></a>
### 两个克隆人记录一次交换行走

交换对象在自己的克隆上发布其状态并读取对等体的状态。克隆类型 2 副本的 20 字节数据为 5 个字，由 `0x11bc00` 及其同级写入：

```
+0x00  4  the state: 1 a vote (0x11bc00), 2 a vote withdrawn (0x11b4e0), 4 a forced leave (0x11bcf0)
+0x04  4  that call's argument, 1 on selection and 2 on confirmation
+0x08  4  a counter, incremented on each call
+0x0c  4  the station's own step, the number of game messages it has sent
+0x10  4  the trailing word
```
 克隆类型4副本的32字节数据是会话主机（权限）视图：

```
+0x00  4  A, the agreed argument
+0x04  4  B
+0x08 16  one counter per station index (host 0, joiner 1): the counter of the vote it last saw withdrawn
+0x18  4  the station's step
+0x1c  4  the trailing word
```
 权限 `0x11b6c0` 在会话主机上运行每个刻度。仅当每个站都在当前尾随字上发布带有参数 X 的状态 1 时，才会将 A 移动到 X，同时发布 A 和尾随字加一；状态4立即移动A。对于状态 2 中的站，其参数与 A 不同，它将该站的计数器写入其槽中，将尾随字移动 1，保留 A 和 B，并在新的尾随字下重新发布其自己的类型 2。

交换屏的状态来自A及其自身记录的状态通过`0x34a300`（跳转表
A) 上的 `0xf4e9b0`； `+0x271` 设置为 `+0x272` 清除首先给出 1。

|一个 |本地状态 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| 0（表`0xf4e9d0`）| 0 | 1 | 1 | 0 | 0 |
| 1（表`0xf4e9f0`）| 2 | 3 | 3 | 0 | 2 |

无论当地状态如何，A 2 都会给出 4，而 A 3 会给出 5，合作伙伴会离开 (`0x3490c0`)。

类似的状态函数`0x3488b0`（表`0xf4e920..0xf4e980`，循环`0x9c3300`）属于类`0x347e10`（0x718字节位于`mgr+0x70`，由`0x344690`创建）， `0x886530` 在模式 1 和 2 下创建。

交换 UI 的更新（`0x756a20`，子状态 `[ui+0xa8]`）适用于队伍要约对象（`0x7568ec`）。确认票 2 (`0x756e34` -> `0x34a4e0` -> `0x11bc00`)，子状态 2 (`0x757058`)。状态4在`[[x21+0x78]+0x60]`写入5，调用`0x74a590(ui, 2)`并继续（`0x756c0c..0x756c38`）；状态2返回选择（`0x756cb4`）；状态 1 或 3 下的菜单结果 3 撤回投票（`0x756d94` -> `0x34a500` -> `0x11b4e0`，状态 2）。在子状态0、状态1用`[x22+0x258]`零调用`0x34a4a0`(`0x756b94`)，对方退出。

`0x11b688` 在 `+0x1638` 上演到达的克隆类型 4 记录； `0x11ba20` 与 `+0x1638` 进行比较
`obj+0x04`、`+0x163c` 和 `obj+0x10`，以及 `+0x1640` 和 `obj+0x0c` 中每个节点一个字。在那里发布 32 个零的主机使游戏机处于“communication en coours”状态，除了 Retour 之外的每个按钮都变成灰色。

所提供的队伍克隆先走 `1 1 1`，尾随字 1，然后走 `x 2 2`，尾随字 2。提交克隆（队伍克隆上方的一个 id）取前两个，然后取零。主机的框架，零售和模拟都一样，将类型 2 数据克隆为五个单词：

```
+0 ms     type 4 data, 32 zeros, with the announcement
          the peer publishes 1 1 1 step 0 once its player has confirmed
          1 1 1 step 0                 the host's own confirmation
+30 ms    1 1 1 step 1                 type 4 data 1, zeros, step, 1
+8 ms     the peer answers 0 1 1 step 1
+27 ms    0 1 1 step+1 1               the offered clone goes 0 2 2 step+1 2 in the same frame,
                                       and the kind 3 carrying 1 goes under that step
+3 ms     the peer's kind 3 carrying 1, its copies under its own next step
+63 ms    kind 3 carrying 2 under the next step, every copy republished under it
after the trade demo and the normal save (3000 ms past SaveThread, 0x8377ec):
          two more clones announced, 32 zeros on type 4; the peer publishes 0 0 0 on each
then      kind 4 under the next step, every copy republished under it
```
 仅当类型 4 副本的第一个字为 1 时，对端才应答尾随字 1；在对等方的 `1 1 1` 落地之前构建，它携带 0，游戏机等待。将提交克隆移至 `1 2 2` 会绘制 `0 1 1`、尾随单词 2、无种类 3，并且游戏机位于其确认屏幕上。

游戏机主机首先宣布每个克隆：克隆 1，其第一个插槽之前的队伍对 2 和 3，其 A 2 之后的提交克隆 4（状态 1 的随机延迟，`0x8380d8`），以及保存后的下一对 5 和 6，然后是其第一种 4。它也首先投票：克隆 3 上的 `1 1 1`，带有尾随字的 A 1 1、`1 2 2`，A 2，尾随字2；在提交克隆 `0 0 0`、`1 1 1` 上，A 1 带有尾随字 1，然后 `0 1 1` 带有类型 3 携带 1，在宣布后 152 毫秒。加入方接管每个克隆并在其自己的状态字下重新发布主机的前三个字和尾随字，从而完成交换。

确认过程中按钮变灰时再次按 A，会撤回确认：在 `1 2 2` 后发送 `2 2 3`（状态 2、参数 2、计数器 3）。回应 A 2 会得到状态 4：游戏机开始同步保存，在提交交换前设置交换锁（600）。实机收到这种回应后重新发布 `0 2 3`，5.0 秒后宣布提交克隆，随后不再回应；交换未完成，锁保持设置，连接菜单拒绝下一次交换（`0x976634`）。模拟运行的游戏机在相同回应下完成了交换（[未解决的问题](lgpe.md#unresolved)）。正确回应是类型 4 的 `1 0 0 3 0 0 step T+1`，它会通过 `0x11ba20` 将该记录转为状态 0；状态 0 下的 A 1 得到状态 2（`0xf4e9f0[0]`），回到选择界面。撤回选择 `2 1 4` 在 A 0 下应回应 `0 0 0 4 0 0 step T+1`。`bin/lgpe_host.py` 采用这种回应，并在一次发布中同意下一次确认；`tests/test_lgpe_host_withdraw.py` 会通过游戏代码验证这两条路径。

两个零售控制台之间的交换在任一方向上都不携带有关克隆类型 4 和 1 的克隆数据；如果主机没有发布，则其搜索屏幕上会留下一个缺少门 `0x11b080` 的加入游戏机。

<a id="the-trade-animation"></a>
### 交换动画

游戏机在执行 `0e` 步后播放交换动画，并且在此期间不发送交换发票。以零售Let's Go托管`bin/lgpe_join.py`为例，从该步骤开始：动画在约1.7秒开始，接收到的宝可梦在约15.3秒出现（手按，最多晚2秒），游戏机的4型消防（248字节）在27.0秒到达，玩家在约28.8秒获得控制。

<a id="the-commit-and-the-trade-lock"></a>
### 提交和交换锁

交换锁是存档 MyStatus 数据块中的 u32 秒倒计时。交换保存时先将其设为 600，并在提交交互之前写入存档；交互完成后，再将其改回 0 并提交保存。

MyStatus 数据块对象为 `[[[0x15fad08]]+0x98]+0x58` → `+0x78`，数据位于 `obj+0x58`，大小 0x168 字节（`0x1c9ff0`、`0x1ca000`，虚函数表 `0x153e0b0` 的槽位 5、6），也就是类型 1 的消息体。计数器为 `obj+0xe8`，位于 MyStatus 的 `+0x90`（设置函数 `0x1c9d40`，读取函数 `0x1c9d50`）。在 `savedata.bin` 中，数据块为 `0x1000..0x1168`（训练家名称位于 `0x1038`），计数器位于 `0x1090`：交换中断后保留的存档在此处为 `58 02 00 00`，数据块其余部分没有变化。捕获的每条类型 1 消息在 `+0x90` 都为 0。

设置函数的调用方包括：同步保存设置 600（`0x837f90`、`0x837fb0`），应用收到的宝可梦时设置 0（`0x838bec`、`0x838c0c`），以及倒计时（`0x1ca54c`、`0x1ca56c`）；载入存档时写入整个数据块。连接菜单检查 `0x9765f4` 根据连接模式分支：模式 1（交换）读取计数器（`0x976634`），非零时以拒绝消息 `0x0248810f825b1fee` 返回 -1（`0x97663c`）；为零时继续检查数量（消息 `0x0248800f825b1e3b`）。模式 3 在 `[x22+0x62] <= 1` 时拒绝（消息 `0x02487f0f825b1c88`）。

锁定随游戏时间倒计时。`0x1ca450(playtime, seconds)` 在 `seconds > 1`（`0x1ca46c`）或 `playtime+0x100` 清零（`0x1ca474`）时立即返回；否则从计数器减去 `seconds`，最低为 0（`0x1ca500`），并增加游戏时间（`+0x54` 为 u16 小时，`+0x56` 为分钟，`+0x57` 为秒，上限 999:59:59，`0x1ca5a0`）。`0x1ca7e0` 将 `playtime+0x100` 写为 `nn::oe::GetCurrentFocusState() != 3`（后台）。调用方 `0x1462a0` 在启用字节 `+0x54` 置位且没有存档线程（`0x1ce8f0`）时，每 20 次调用运行一次（计数器 `+0x70`）：将 `GetSystemTick` 减去基准 tick（`+0x68`）转换为整秒，把相对已计秒数（`+0x60`）的增量传给 `0x1ca450`（`0x146314..0x14637c`）；只有 tick 倒退时才更新基准（`0x146384..0x1463c0`）。两秒及以上的跳变被丢弃，因此每次通过条件的调用最多增加一秒。锁定 600 持续十分钟计入的游戏时间：焦点状态 1 和 2 计时，后台或关闭游戏时不计时（启动重新读取基准，`0x14628c`）。秒数对应实际时间：`0x1462a0` 将转换为纳秒的 tick 差除以 10^9（`0x14632c..0x146354`）。每帧调用一次、初始帧间隔 33.3 毫秒时，条件主体每 0.667 秒执行，增量为 0 或 1，所以保持前台时锁定 600 持续实际 600 秒；间隔超过 1 秒时则丢失跳变中的秒数。模拟器运行《Let's Go》1.0.2、地图上每秒 30 帧时，调用计数器 `+0x70` 每 0.125 秒增加 4：每帧一次，条件主体每 0.67 秒执行。

`0x13c944` 位于 `0x13c850` 中（该函数还执行 `0x145560`、`0x13f0d0`、`0x142cd0`、`0x1427a0`），只能由 `0x13c5a0` 到达，属于大小 0x210 字节任务的槽位 `+0x40`（虚函数表 `0x15379d8`；在初始化 `0x13b650` 中由 `0x13c440` 根据 `0x13bfa0` 构造，存于 `G+0x50`，完成字节为 `+0x204`）。工作循环 `0x20f30` 中的执行器 `0x231a0` 在 `+0x204` 未置位时执行它（`0x23264..0x23288`）。`0x13bfa0` 通过 `0x1ca00` 将任务接入依赖图（`0x13c02c..0x13c120`）；每帧由谁提交依赖图、游戏时间计时因此多久执行一次，尚不清楚。帧周期表 `0xf7eeb8` 有五档，从 16666667 到 83333334 纳秒，由 `0x39600` 索引；帧循环以 33333334 纳秒启动（`0x38ba0..0x38bb8`，虚函数表 `0x1529968`），每隔 `clamp(period / 16666666, 1, 5)` 次垂直同步呈现一帧（`0x29e80..0x29eb4`）。

`0x347190` 构造三种保存流程之一：0“常规保存”（`0x3474d0`）、1“同步保存”（`0x347670` → `0x347ae0`，0xc8 字节）、2“致命错误”（`0x347810`）。交换采用同步保存。初始化函数 `0x837c70` 在 `seq+0xb8` 创建提交通道对象（`0x4d9030`），将计数器设为 600（`0x837f88`），然后启动 `SaveThread`（`0x1cdc80`）；后者在调用线程中序列化，并在写入完成后提交（`0x1cedd4..0x1cede0`、`nn::fs::CommitSaveData`）。更新函数 `0x838070` 根据 `seq+0xa8`，经跳转表 `0xf867c4` 执行：

| 状态 | 地址 | 行为 |
|---|---|---|
| 0 | `0x8380ac` | 存在已记录的网络错误（`0x4d8a70`）时写入结果 2 并退出；否则等待 `SaveThread`（`0x1cdf40`），在 `seq+0xc0` 保存本站点是否发送 2（`0x838660`），应用收到的宝可梦并在内存中清零计数器（`0x838800`），设置 `netmgr+0x121`（`0x4d8b10`），启动 `FirstSaveThread`（`0x1ce050`） |
| 1 | `0x8380d8` | 等待 `FirstSaveThread` 写入（`0x1ce310`），然后从以 `GetSystemTick` 为种子的 MT19937-64 中抽取 `2000 + r % 6000` 毫秒延迟 |
| 2 | `0x838234` | 延迟结束后注册提交通道（`0x8382a8`） |
| 3 | `0x8382b4` | 在提交克隆上投票 1 一次（`0x4d9690`：`chan+0x64 = 1`、`0x11bc00`），然后等待通道门控（`0x4d94d0`）以及克隆空闲且 `[chan+0x74]` 为 1 |
| 4 | `0x8382ec` | 发送消息体为 1 的类型 3 |
| 5 | `0x838310` | 取出另一站点的类型 3（跳过自身回环）；消息体不是 1 时进入错误路径（`0x83836c`）；若 `seq+0xc0` 已置位，则发送消息体为 2 的类型 3（发送失败时留在状态 5，但对方的 1 已被消费） |
| 6 | `0x83839c` | 取出任意站点的类型 3：值为 2 时清除 `netmgr+0x121`（`0x4d8b20`）并发出提交信号（`0x1ce3f0`）；其他消息体忽略 |
| 7 | `0x8383e8` | 等待 `FirstSaveThread` 提交（`0x1ce410`），结果为 0 |

`FirstSaveThread` 在启动时序列化（`0x1ce154`），此时计数器已清零；写入后发出 `mgr+0x78` 信号，等待 `mgr+0x84`，仅在中止字节 `mgr+0x100090` 未置位时提交（`0x1cedf4..0x1cee18`）。错误路径（状态 2、3、5、6 对应 `0x8383b0`，错误消息体对应 `0x838520`，状态 0 对应 `0x8380c8`）在父对象中写入结果 2（`[x0+0x88]+4`）；前两条路径调用 `0x1ce520`，设置中止字节并等待线程结束。所有路径都以 `0x838540(seq, 0)` 结束。第二次保存被丢弃，磁盘存档中的计数器仍为 600。

调度器的状态 3（`0x886684`）读取该结果：结果为 2 时调用 `0x345b10`（`0x886690`），不推进状态就返回。`0x345b10` 将致命错误包装对象（虚函数表 `0x154f1f8`，0xa8 字节，`+0x88 =
0`）压入根进程栈（`0x13a6b0`）；其 `0x346140` 构造类型为 `[proc+0x88] != 0 ? 3 : 2` 的保存进程（`0x3461b8..0x3461d0`），两者都对应致命错误流程。该流程的初始化 `0x836320` 在类型 2 时显示消息 `0x191615296121e064`、类型 3 时显示 `0x977c18bf4135ff42`（`0x8365f0`，经过 `0x7ed60`），更新函数（`0x836780`）仅包含 `ret`。提交中止后会停在此界面，不会再保存，下一次启动时存档中的计数器仍为 600。

两个 ID 都是 `common/message_error.dat` 的标签（字符串位于 `0xf22dfc`），使用初始基值 `0xcbf29ce484222645` 的 FNV-1a-64；更新版本 v131072 的十种语言中均相同：

| ID | 标签 | 英语原文与中文释义 | 法语原文与中文释义 |
|---|---|---|---|
| `0x191615296121e064` | `error_fatal_save` | An error occurred. You couldn't trade Pokémon. Press the HOME Button to end the game.（发生错误，无法交换宝可梦。请按 HOME 键结束游戏。） | Une erreur s'est produite. L'échange de Pokémon n'a pas pu être effectué. Veuillez appuyer sur le bouton HOME et fermer le jeu.（发生错误，无法交换宝可梦。请按 HOME 键关闭游戏。） |
| `0x977c18bf4135ff42` | `erro_fatal_storage`（原文如此） | Save data in the Nintendo Switch couldn't be recognized. Please turn off the system, and then try again.（无法识别 Nintendo Switch 中的保存数据。请关闭主机后重试。） | L'identification des données de sauvegarde de la console Nintendo Switch a échoué. Veuillez éteindre votre console, la rallumer, puis réessayer.（无法识别 Nintendo Switch 的保存数据。请关闭主机、重新开机后重试。） |

游戏只有一个进程栈，根为 `[G+0x68]`（`G = [0x160d310]`）。执行器 `0x13a780` 仅通过 `0x13a160` 更新栈顶 `[root+0x78]`：返回 3 时同一帧执行新的栈顶；返回 1 时弹出栈顶，或换入等待中的 `[root+0x80]`。包装对象从不返回 1（`0x346140` 通过 `0x39c20` 将致命错误进程交给管理器 `[G+0x60]`），因此其下方的调度器不会再得到更新。

连接菜单的拒绝 ID `0x02487f0f825b1c88`、`0x0248800f825b1e3b`、`0x0248810f825b1fee` 两两相差 FNV 质数 `0x100000001b3`：它们是三个仅最后一个字节不同的字符串的 FNV-1a-64 哈希值（乘以该质数模 2^64 的逆元后，末尾分别为 `dd58`、`dd59`、`dd5a`）。字符串尚不明确；文本位于 romfs 消息归档中。

`netmgr+0x121` 置位期间，`0x4d8750` 将所有网络错误记录为严重级别 4（`0x4d8760..0x4d877c`），状态 2、3、5、6 会检查这个级别（`0x4d8a80`）。只有更严重的错误才会替换已有记录（`0x4d879c`），因此在 `+0x121` 置位前记录的高于 4 的错误不会通过此检查。`+0x121` 在状态 0 结束时设置（`0x8384f8` 处的 `0x4d8b10`），由状态 6 收到 2 后清除（`0x838494` 处的 `0x4d8b20`）。没有任何状态设有超时：对方不发送消息时，流程会持续等待，直到连接失败。

记录函数包括：`0x345790`（代码 0xe）、`0x3457d0`（0x11）、`0x345810`（0xf）、`0x345860`、`0x3458a0`、`0x345900`（一个 `nn::err::ErrorCode`）、`0x345940`（序列码客户端）、`0x3459f0`、`0x345a50`、`0x345aa0`。`mgr+0x60` 的监听器（虚函数表 `0x154f068`）将 `0x344c30`、`0x344c60`、`0x344c70`、`0x344c80` 路由到 `0x345790`，`0x344c40` 到 `0x345900`，`0x344c50` 到 `0x345860`，`0x344c90` 到 `0x3457d0`。交换会话对象（虚函数表 `0x154f608`）通过 `0x3496b0` 将槽位 9（`0x349650`，代码 0xe）、槽位 10（`0x3497d0`）以及槽位 11 至 14（`0x349880`、`0x3498e0`、`0x349940`、`0x3499a0`；14 对应代码 0x11）转发给监听器。

连接状态机 `0x4d9b70`（来自 `0x349520`）在状态不高于 5、没有待处理操作（`[x19+0x20]` 为空）且泵函数 `0x1175d0` 返回 0 时进入状态 6（`0x4d9b98..0x4d9bc8`）；状态 6（`0x4d9fb0`）调用槽位 9。当 `[x19+0x80]` 为空、传输层的 `+0x48` 不为 5（`0x11c560`），或会话的 u16 字段 `+0x1e6` 不大于 1（`0x1176b0..0x1176bc`）时，泵函数返回 0。只有 `0x59eab0` 写入 `+0x1e6`：它对 `s+0x178` 中各站点的状态 3 记录求和，累加每条记录的字节 `+0x415`（`0x5b5900`、`0x5a9cd0`）；该值来自连接响应的线上字节 `0x35`（`0x5b962c..0x5b9658`）。零售版《Let's Go》在此发送 1，因此结果就是站点数量。本地站点也计入：`CreateMeshJob`（`0x581f20`）及 `JoinMeshJob`（`0x583b90`）通过 `0x5a9430` 以模式 0 注册本地记录，该模式立即设置状态 3（`0x5a9558`、`0x5a9720`），并使用 `[mesh+0x12b]`（`0x58e960`；网状网络重置后为 1，`0x58bd20`）；`0x5a3be0` 先将本地 ID `[s+0xe0]` 加入 `s+0x178`（`0x5a3c48`）。双主机会话的计数为 2。

仅当 `[s+0xd8]` 不在 2 至 6、`[s+0xd4]` 为 2 或 4、且 `0x52abf0(s+0x38)` 为假时重新计数（`0x59eacc..0x59eaf8`）；交换期间三个条件都满足。`[s+0xd8]` 是会话状态：1 已连接、2 已丢失（`0x5a0490`）、3 正在启动、4 至 6 是 SessionStatusCheckJob 检测到的失败。`[s+0xd4]` 是另一会话状态字段：本地网络就绪后为 1（`0x5d70bc`），会话内为 2，联合会话期间才为 3、4；在 `CreateSessionJob::WaitCreateMesh` 结束时（`0x582a20`、`0x582a24`）以及加入方网状网络等待结束时（`0x586e74`、`0x586e98`），两字段分别变为 2、1。`[s+0x38]` 是 `LocalMatchLeaveSessionJob`（工厂槽位 `+0x1b8`，`0x5c7d20`）；任务状态 `+8` 为 1 至 7 时 `0x52abf0` 为真，这只发生在本地主机退出期间。对方离开时，网状网络的站点断开事件 1 传到会话（`0x58be90` → `0x58c040` → `0x58ea20`，分支 `0x58ebf4`）；退出处理函数 `0x59dea0`（主机迁移期间为 `0x59f1b0`）移除 ID 并重新计数（`0x59dfc4`），除非仅匹配期间设置的 `[s+0x13d]` 将其延后（`0x59df34`）。计数降至 1，泵函数返回 0，槽位 9 经监听器 `[obj+0x98]` 记录代码 0xe；管理器存储交换会话时设置该监听器（`0x343ebc`）。管理器更新 `0x344370` 每帧由 `0x13d9d0` 调用（`0x13da00`），因此同步保存期间连接状态机仍在运行：`netmgr+0x121` 置位时对方离开，会停在 `error_fatal_save`。网状网络等待多久才将沉默站点视为离线，尚未分析。

连接状态机在六个偏移处调用交换会话对象（虚函数表 `0x154f618`），均来自 `[x19+0x10]`：

| 偏移 | 函数 | 调用 | 触发条件 |
|---|---|---|---|
| `+0x30` | `0x3495e0` | `0x4da4b0` 中的 `0x4da584`（来自 `0x4d9cf0`） | 状态 4 转到 5（`0x4d9cf4`） |
| `+0x38` | `0x349600` | `0x4d9f2c` | 匹配成功，位于 `0x116890` 之前 |
| `+0x40` | `0x349620` | 位于 `0x4da5e0` 中（来自 `0x4d9e24`） | 状态 9 转到 10（`0x4d9e28`） |
| `+0x48`，槽位 9 | `0x349650` | `0x4d9fb0` 中的 `0x4da084`（来自 `0x4d9bc8`）；`0x4da0e0`（来自 `0x4d9ee0`） | 泵函数失败；或匹配失败且 `[job+0x300]` 未置位（`0x4d9e30`），结果为零或第 10 至 12 位不是 1、2（`0x4da114..0x4da128`） |
| `+0x50`，槽位 10 | `0x3497d0` | `0x4da0e0` 中的 `0x4da38c`，来自 `0x4da294`，有两个输出参数 | 匹配失败、`[job+0x300]` 未置位，且结果的第 10 至 12 位为 1 或 2 |
| `+0x70`，槽位 14 | `0x3499a0` | `0x4d9efc` | 匹配失败且 `[job+0x300]` 已置位 |

两条匹配失败路径随后都设置状态 6（`0x4d9ee4`、`0x4d9f14`）。结果为 `0xa46e`（模块 110，NIFM，描述 82）时，槽位 10 的 out1 为全局变量 `0x163ce00` 中对象的 `+0x40` 处 u32（`0x4da2a4..0x4da2c4`；全局变量为空时改调用槽位 9，`0x4da3bc`），由 `LoginJob::Logout`（`0x5de3ac..0x5de42c`）根据传输层虚函数 `+0xb0` 写入。其他结果通过 `0x5298a0` 转换成 out2 中的 `nn::err::ErrorCode`（`0xe437` 使用 `0x1601e38` 保存的代码，否则使用 `0x529940(result)` 的 N / 10000 和 N % 10000）。槽位 10 在 out1 非零时通过 `0x345860` 记录它，否则通过 `0x345900` 记录 ErrorCode；管理器在 `0x3443f4..0x34443c` 重复该检查。尚未找到槽位 11 至 13 的调用方。

`0x838660` 决定谁发送 2。令 S = {144, 145, 146, 150, 151}（掩码 `0xc7` 中的 `species - 0x90`），M = {808, 809}：提供 S 或 M 中的宝可梦、但接收的宝可梦不属于两者的站点负责发送；相反情形不发送；其他情形由 `0x4d9720` 为真的站点发送（`[mgr+0x128c] != 0`）。因此，以急冻鸟、闪电鸟、火焰鸟、超梦、梦幻、美录坦或美录梅塔交换普通宝可梦的站点，无论担任哪一角色，都会发送 2。

父数据块（`[parent+0x88]`，见下文“交换调度器”）在 `+8` 保存己方待交换宝可梦的盒子索引，在 `+0x10` 保存接收的宝可梦。状态 0 在盒子栏位仍装有己方宝可梦时调用 `0x838660`（`0x1c0d30`：`box + 0x3f800 + idx*8` 处的对象，0x3e9 表示无对象，盒子为 `[[[[0x15fad08]]+0x98]+0x58]+0xb0`），随后 `0x838800` 将 `[block+0x10]` 的副本写入该栏位（`0x838afc bl 0x1c0f30`），并应用交换的附带效果：

- 通过 `0x1cfe80`（`0x83897c`，进化后还会在 `0x838ab0` 再执行一次）在 `[[[[0x15fad08]]+0x98]+0x58]+0x88` 登记宝可梦图鉴；`0x1cff60` 跳过蛋以及种类编号为 0 或大于 809 的记录，否则在 `obj+0xdc` 设置按种类存储的位，索引为 `species - 1`。`0x1760a0(species, form)` 为真时将形态清零。
- 连接交换进化 `0x728250(pkm, partner, &species, &index)`：对于蛋，或种类不是 64（勇基拉）且持有物通过管理器虚函数 `+0x28` 检查的宝可梦，`0x723220` 保持种类不变；否则取首个满足条件的进化项 `0x723340`：方法 5 始终满足，方法 6 要求持有物等于参数，方法 7 要求小嘴蜗（616）与盖盖虫（588）交换。传入的两只宝可梦都是接收副本（`0x838a44..0x838a4c`），因此方法 7 永远不会匹配。`0x7282c0` 应用进化：通过 `0x7283c0` 修改种类，方法 `0x22` 将形态加一，方法 6、19、20 清除持有物（掩码 `0x180040`）。
- `0x115860` 为真时增加游戏记录 477，否则增加 476（`0x1ca840(id, 1)`、`0x838828..0x838840`）：记录是 `[[[[0x15fad08]]+0x98]+0x58]+0xc8` 的 `obj+0x54+4*id` 处 u32，上限由 `0xf48368[0xf4b760[id]]` 给出；`obj+0x10f8` 置位时（`0x1ca8f8`）或 ID 大于 999 时不写入。`0x115860` 返回字节 `0x1614076`，该字节由 `0x1157f0` 根据 `InternetConnectThread` 设置（`0xb2ea98`），由 `0x115830` 的退出流程以及两个 `InternetDisconnectThread` 函数体清除（`0xb2ebf8`、`0xb2f178`）：476 统计本地交换，477 统计互联网连接就绪期间的交换。

`mgr+0x128c` 表示会话开始时本地站点是否为会话主机；只有连接状态机在匹配后从状态 2 转到 4（`0x4d9f54`）时，才由 `0x116890` 写入（`0x116a48` 处的 `0x59e920(session) & 1`）。Pia 主机迁移不会再次执行它。当 `[s+0xe0]`（本地站点，在创建 `0x59f864` 和加入时设置）等于 `[s+0xe8]`（会话主机，加入时为 `0x59f920`），且站点 `[s + 0x148 + 8*[s+0x142]]` 的虚函数 `+0xe0` 返回真时，`0x59e920` 返回 1。`mgr+0x1288` 也来自 `[s+0xe0]`（`0x116a3c`）。

实现对端时需要注意：

- 确认子状态中的 A 2 会产生状态 4，从而启动同步保存并将 600 写入存档：发布 A 2 的权威端必须完成整个提交交互。
- 对方第一条类型 3 的消息体不是 1 时，会中止交换并保留交换锁。
- 在接收方状态 2 注册提交通道之前发送的类型 3 会被丢弃；状态 3 的投票会让各站点等到双方完成注册后再发送类型 3。
- 状态 1 的延迟最多会将主机的类型 3 推迟六秒（提交克隆分别在主机 A 2 之后 5.0 秒和 9.0 秒通告）。
- 状态 0 结束后至收到 2 之前记录的任何网络错误都会中止提交：存档保持 600，主机停在致命错误界面。

<a id="the-trade-dispatcher"></a>
### 交换调度员

`0x886530` 运行从菜单到退出的链接，通过表格打开 `[obj+0x68]`
`0xf87bc4`：

|状态|条目 |它是做什么的 |
|---|---|---|
| 0 | `0x886578` |设置 |
| 1 | `0x88669c` |等待它的子节点；记录的网络错误 (`0x345af0`) 变为 8； mode `+0x8c` 1或2创建`0x347e10`对象（`0x886f04`）和战斗场景（`0x886f18`），然后是6；模式3等待`0x344510`的队伍要约对象报告就绪（`0x886f30`：通道和克隆集的就绪状态，`0x4d94d0 & 0x11b4d0`）|
| 2 | `0x8866f4` |复制盒子槽位`[obj+0xf8]`为`obj+0x148`作为出局宝可梦；网络错误转到 8； `[obj+0x100]` 5，交换UI继续，开始同步保存，任何其他值都变为8 |
| 3 | `0x886670` |等待它的子节点（`[obj+0x90]` 处的弱引用，在致命包装器被推送之前被销毁）；结果 2 调用 `0x345b10`，致命错误，并保持不变；否则销毁队伍要约对象（`0x886c70`），将 `[obj+0xf0]` 放在 `obj+0x150`，启动交换演示（`0x875f40`），状态 4 |
| 4 | `0x886930` |发布 `[obj+0x150]`，状态 5 |
| 5 | `0x886950` |等待它的子节点；将 `[obj+0x158]` 写入盒槽 `[obj+0xf8]` (`0x1c0f30`)，开始正常保存，状态 7 |
| 6 | `0x886ee8` |状态 8 |
| 7 | `0x886908` |等待它的子节点；结果 1 变为 8，任何其他结果变为 1 |
| 8 | `0x8869cc` |销毁队伍要约对象（`0x8869f0`）和`mgr+0x70`对象（`0x3447a0`）并离开|

通过`0x887340`开始一次保存，构建一个保存过程（`0x346670`，0x128字节）；调度程序将 `&obj+0x178` 存储到 `+0x90`（`0x8868dc`、`0x886e48`）中。它的第一次更新
`0x8345d0` 通过 `0xef9a80 = {1, 0, 2, 2}` 将保存类型映射到 `0x347190` 的序列类型，并将指针（`0x834688`）传递为 `[parent+0x88]`：

```
obj+0x178  +0x00  save type: 0 sync save, 1 normal save, 2 or 3 fatal error
obj+0x17c  +0x04  result, written by the sequence: 0 done, 2 aborted, 1 the link ends
obj+0x180  +0x08  box index of the own offered Pokemon, [obj+0xf8]
obj+0x188  +0x10  the received Pokemon, [obj+0xf0]
```
 状态 2 填充它以进行同步保存（`0x88685c..0x88689c`）；状态 5 将类型设置为 1 (`0x886e00..0x886e04`)。正常保存的更新`0x8374b0`运行`SaveThread`（`0x8377bc`），等待3000毫秒（`0x8377ec`），然后，如果交换会话对象处于状态8（`0x349090`），则创建队列提供对象（`0x8375a4`，每帧重试）并写入结果0（`0x8375b8`）；在任何其他状态下，它单独写入 0。结果 1 仅来自 `0x837860`，在 `[x20+0x258]` 上门控且队列位于
`[x20+0x250]` (`0x83776c..0x8377a0`)。交换后，调度程序从状态 7 返回到状态 1 (`0x88691c..0x88692c`)，并在新通道上提供新的队列提供对象，因此一个座位承载着一个又一个的交换。

子引用 `[obj+0x90]` 在状态 0 保存连接菜单进程（`0x886cf4` -> `0x8871a0` -> `0x887940`，虚表 `0x15afdc0`，`0x886d44` 传入模式字 `obj+0x8c` 的地址）；状态 2 和 5 保存存档进程（`0x887340` -> `0x346670`，虚表 `0x15aa2a0`）。同步存档中止后，状态 3 读取结果 2 前，`seq+0xb8` 的提交通道已释放：各中止路径经 `0x838540` 结束序列，运行器弹出进程，其析构函数 `0x835000` 释放序列，再由序列析构函数 `0x838c40` 释放通道；状态 3 先等待子进程计数归零（`0x886670..0x886684`）。

模式 1 和 2 是连接对战。构建的进程结束时增加存档计数器（`0x95ccbc..0x95ce40`）：模式 1 为 `local_btl_single_cnt`（ID `0x1de`），模式 2 为 `local_btl_double_cnt`（`0x1df`）；`0x115860` 为真时改为 `netl_btl_single_cnt` / `net_btl_double_cnt`（`0x1e0`、`0x1e1`）。模式 2 设置双打标志 `[obj+0x810]`（`0x886f10`、`0x95c4bc`、`0x95c574`）。交换的同步存档（模式 3）依据同一标志增加 `local_trade_cnt`（`0x1dc`）或 `net_trade_cnt`（`0x1dd`）（`0x838828..0x838840`）。连接菜单的选择编号不同：选项 1 为交换，存储 3（`0x97845c`）；选项 2 存储 1，选项 3 存储 2（`0x978504..0x978514`）。

<a id="the-battle-scenes-channel"></a>
### 战斗场景频道

`0x9dce94..0x9dede8` 中的发送者是唯一的非零标签，将其状态保存在全局块中
`0x1640eb0`，其第一个字是其通道（`0x9dce10..0x9dce1c`：`ldr x0,[0x1640eb0]; b
0x4d9450`）。 `0x9dce50`将标签1下的块`+0x78f0`（一个u16站字节，一个u16 0x6e）中的四个字节发送到0xff； `0x9dd3ec`将宝可梦（`0x721ef0`）打包到`+0x348`中，`0x9dd3fc..0x9dd40c`将其在标签3下发送。每站记录为0x1788字节（`0x9dcee8`）。

注册（`0x9d2d90`）位于战斗过程的步进设置`0x9d2c30`（跳转表
`0xf92c1c`;进程引用 `Pop_BGM_battle_to_field`、`vs_wild` 和 `btl_sky.gfbmdl`），仅在模式 1 和 2 中从调度程序状态 1 到达（`0x886f18` -> `0x95c470` -> `0x95c5c0` -> `0x28cd10` -> `0x28e630` -> `0x9cbba0`）。在模式 3 中，战斗频道永远不会注册。步骤0仅当链路会话对象`[[[0x15faec8]]+0x50]`处于状态8（`0x9dc61c..0x9dc634`）时，创建通道（`0x9dc5c0`）并将其存储在`0x1640eb0`（`0x9dc6f4`）；当 `0x1640eb0` 为空时，`0x9dce10` 不记录任何内容，并且准备状态 `0x9dce30` 在没有通道的情况下返回 1，因此狂野战斗不会记录任何内容。拆卸（`0x9d3df0` -> `0x9dcce0`）会清除指针。

<a id="what-a-hosted-trade-puts-in-the-save"></a>
### 托管交换可以节省什么

所提供的框结构在发送时保存，未选中。携带这些值的记录在Let's Go皮卡丘的摘要屏幕上读回不变：种类132，经验1,000,000（等级100），隐藏槽中的特性150，针对TID 41234和SID 12345的具有异色xor 0的PID（显示为083154，`(sid << 16 | tid) % 1000000`），性格10，无性别，每个 IV 31 个，每个 AV 200 个（100 级 HP 437，游戏最高），一招，达到等级 30，遇到地点 4（路线 2），语言 2，OT `POKELDN`。偏移量是 PKHeX 的 PB7 地图。

<a id="a-joiner-leaving"></a>
### A 加入方离开

使用 Retour 退出的游戏机在所提供的克隆上发布状态 4，在新计数器下发布参数 0，然后发布参数 3。主机每隔 30 毫秒回答一次，前三个单词为零，尾部单词加 1，参数作为类型 4 副本的第一个单词。然后，游戏机在克隆类型 4 上使用 0x83 释放其克隆，站 0xFD（克隆类型 3 上的克隆 0），重复（大约每 100 毫秒，测量一次），直到 0x84 应答；主机发布自己的主机（在其站下的克隆类型 2 上以及克隆类型 4 上为 0x83）。上次发布后，一旦其克隆协议空闲（[离开前的等待](#the-wait-before-leaving)），游戏机就会在网格协议的可靠端口上发送网格离开请求，在 24 字节可靠标头下：

```
04 01        leave request, station index
```
 该端口欠可靠确认，不可靠端口 `08` 和网格主机索引 (`08 00`) 欠一个两字节离开响应。仅当离开者处理程序 `0x591bf4` 的字节 [1] 是主机 getter `0x58e5d0` (`ldrb
[x0,#0xa3]`) 名称的站的索引时，才会获取响应，然后清除离开作业的标志 `+0x78`。作业（`LeaveMeshJob`，构造函数
`0x589470`) 在发送请求时设置 5000 ms 的截止时间 (`0x5895bc`)； `WaitLeaveResponse` (`0x5896c0`) 等待标志或截止时间，重新传输请求（每 40 毫秒，测量一次），然后断开其站点并离开网络。指定离开者 (`08 01`) 的响应被丢弃：游戏机在发出离开请求后 5.00 秒取消身份验证（两个控制台上的六次离开需要 4.98 到 5.01 秒，主机的断开连接请求在每个控制台中得到应答）；回答 `08 00` 两次，它在离开请求后 0.04 秒发送自己的断开连接请求，并在约 0.06 秒后取消身份验证。返回后，主机发送一字节站断开请求，类型 3；游戏机在 50 毫秒内回答类型 4。

游戏机主机用 `08 00` 两次应答加入方的离开请求，然后重复本地协议启动主机迁移（类型 0x13，每 0.3 秒测量一次）。当离开响应到达时，方加入发送的断开连接请求将主机的播放器返回到菜单（“l'autre joueur a choisi d'annuler l'échange”）；等待的方加入会使主机重复 0x13 五秒钟。
`bin/lgpe_join.py --leave-after SECONDS` 运行出口（`pokeldn.lgpe.leave`）。

一旦两个工作站在克隆上发布带有一个参数的状态 1，游戏机主机的类型 4 副本就会在 0.27 秒内将 A 移动到该状态。权限读取每个站的存储副本（`container + 0x8d8 + i*0x260`，i低于会话的站计数）。副本仅被具有严格较新时钟的记录替换（`0x52184c`）；相同的时钟确认并保留旧数据。一个加入方在该克隆上的前一个记录的时钟下（都在一个网格时钟滴答内）发送对提交克隆的投票，使得游戏机在交换屏幕上保留旧副本及其玩家。 `pokeldn.ldn.clone.Participant.record_clock` 为克隆上的每条记录提供高于最后一条记录的时钟。
当此类投票在任何类型 3 (`pokeldn.lgpe.leave.unagreed_vote`) 之前的 `--stall-leave` 秒（默认 5）内未达成一致时，`bin/lgpe_join.py` 运行退出。退出结束等待；它不会解除交换锁，该锁是同步保存在提交克隆投票之前写入的（状态 0）
`0x838070`）。

<a id="a-host-leaving"></a>
### A 主机离开

玩家退出的游戏机主机发布状态 4，参数 3，释放其克隆（0x83，由 0x84 应答），最后一次释放后，一旦其克隆协议空闲（[离开前等待](#the-wait-before-leaving)），在可靠端口上发送网格迁移开始，`44 00 01` （主机索引，下一个主机的索引）。它的等待（`0x58aeb0`）在`job+0x6e+index`处为每个连接的站保留一个标志，并在每个标志都清除或经过5000毫秒（`0x58a8f0`）时结束；迁移响应 `48 <index>` 会清除该站的标志（处理程序 `0x591e98` -> `0x58b010`），并且该站也会离开。如果没有得到答复，游戏机每 45 毫秒重传一次起始信息，持续 5.0 秒。

然后，它广播携带主机迁移状态 1 的更新会话，其节点列表不变，并重复本地协议启动主机迁移（类型0x13) 每 301 毫秒 (`0x5d40ac`）直到除了它本身之外没有任何站点连接到 LDN 网络（`0x5cc2d0`计算它们）或已经过去 10000 毫秒（`0x5d4050`），然后破坏网络：八个 LDN 断开帧，原因 3，广播超过 200 毫秒。既不回答也不回答的方加入在迁移开始后 15.0 秒内保持游戏机主机。模拟主机用 ack 应答并`48 01`发送其更新会话和第一个0x1334 毫秒后；零售主机以发送第一个相同的方式回答0x13迁移开始后 0.06 秒。`bin/lgpe_join.py`发送两个答案并在第一个答案时离开网络0x13 (`pokeldn.lgpe.leave.host_departure`).

<a id="the-wait-before-leaving"></a>
### 出发前的等待

游戏的拆卸步骤 `0x116bc0`（链接对象更新 `0x4d9b70` 的状态 8）结束克隆会话（`0x51bee0`），然后当克隆协议状态 `& 0xf0` 为 `0x10`（空闲；由`0x5db760` 变为 `obj+0x16f4`)。否则计数为 150 次调用 (`obj+0x16fc`,
`cmp 0x95` 位于 `0x116d38`) 在通过 `[obj+0x80]` vfunc `0x68` 调用休假之前。两种角色的计数时间均为 2.49 至 2.51 秒。

协议通过状态 `0x41` 达到空闲状态，该状态在任何克隆具有未确认的数据令牌时等待（`0x51b0f0`、`0x5180cc`），然后是 `0x42`，该状态发送克隆退出（0x32）并等待每个站的0x41。在其克隆 0 发布后（克隆类型 3 上为 0x83），游戏机大约每 100 毫秒持续发布其克隆类型 2 副本。一个对等点用自己的副本回答每个人都不会确认它们：游戏机不发送 0x32 并在完整计数后离开。一个对等点在克隆类型 1 上回答每个 0xe3，站 0xFD，携带发布者的站和时钟，为每个克隆在克隆类型 2 上获得 0x83，一个 0x32，并在游戏机最后一次发布后 0.11 和 0.29 秒发出离开请求；游戏机主机在上次发布后 0.13 秒发送其迁移开始。 `pokeldn.ldn.clone.Participant` 在对等方的克隆 0 释放后进行确认。

<a id="what-a-host-does-with-a-joiner-that-holds-no-clone-data"></a>
### 主机对不包含克隆数据的加入方有何作用

给出 0x3C 字节连接响应（无网络 id，无玩家）的游戏机主机应答克隆公告并公告其自己的公告，从不发送克隆的数据（无 0xb1），并在网格加入后几秒钟离开克隆会话（0x32）。发送完整响应的方加入会在参与后获取克隆的数据（测量 1.1 秒）。

<a id="past-the-gate"></a>
### 过了门

一旦门通过，主机就会从状态 4 进入已确定的状态 8：状态 6 发送第一条消息（来自 `obj+0x450` 的 0x168 字节），状态 7 将其自己的环回和加入方计数到 `obj+0x470` 中，在恰好 2 处留下 8（`b.ne`）并且不再接收。然后主机屏幕上会显示已找到玩家。第一条消息的标题：

    01000000 68010000 01000000 00ff0000    kind 1, 0x168 bytes, step 1
    02000000 e8000000 02000000 00ff0000    kind 2, 0xe8 bytes, step 2
    02000000 e8000000 03000000 00ff0000    kind 2, 0xe8 bytes, step 3
 在工作会话中，类型 1 消息被确认，克隆 ID 2 和 3 被公布，然后类型 2 消息（相隔 70 毫秒、3.2 秒和 0.4 秒）。状态 8 是 `0x349200` 的终端：虽然模式字 `+0x8C` 保持为 0，但克隆 ID 2 和 3 永远不会被公布。

<a id="the-state-machine-above-the-gate"></a>
### 门上面的状态机

`0x349200`的状态3在`+0xB8`处分配会话子对象，通过thunk调用`0x11aec0`
`0x11b4c0`（对象`[x0+0x20]`，克隆id `[x0+0x18]`），并无条件设置状态4；状态 4 通过 `0x11b4d0` 调用门并在 true 上前进。状态 3 和 4 不从网络读取任何内容。同一后卫的三个 setter 位于连续的 vtable 槽位中，只能通过 vtable 到达：
`0x154f648` -> `0x3495e0`（状态 3，来自除 9、10、11 之外的任何状态），`0x154f650` -> `0x349600`（状态 2），`0x154f658` -> `0x349620`（状态 11，然后中止 `0x4d8b00`); `0x349650`, `0x3497d0`,
`0x349880`、`0x3498e0`、`0x349940` 跟随。

`0x11aec0`在一帧中注册并宣布一个电台的整个克隆集：第 1 类克隆`game+0x90`从`game+0x678`，4型克隆在`game+0x1258`从`game+0x13f0`，然后每个队伍成员一个（跨步0x118从`game+0x218`, 源步长0x260从`game+0x8d8`）。每个去`0x51a550`或者`0x51a510`，将播音员排入元素列表中`+0xD8`。扫地机`0x51b380`稍后将其从表中排出类型字节`0xf46acc` (0x81, 0xa1, 0x83, 0xb1）按排队对象的种类：因此`0x81`对于 2 型克隆，`0xa1`关于类型 4 和`0xa1`在一帧中的类型 1 上。

公告出现在大门前：发出该三元组的电台已通过状态 3；一个从不发出它的状态还没有达到状态 3，并且没有针对门输入的消息对其有帮助。游戏机主机仅从克隆 ID 1 的交换状态机发出三元组； ID 2 和 3 来自第二个发布者（`0x349a90`，如下）。加入时，它不发出 `0x81`，仅发出接管突发。工作站对每个克隆 ID 运行 `0x11aec0` 一次，依次为 1、2 和 3。

<a id="the-second-publisher-and-its-mode-word"></a>
### 第二个出版商及其模式词

`0x11aec0` 有两个呼叫者。交换状态机在状态 3 中为克隆 ID 1 调用它一次。ID 2 和 3 大约 3.2 秒后来自另一个每帧调度程序：`0x13a780` -> `0x13a160` ->
`0x886530` -> `0x344510` -> `0x349bf0` -> `0x349a90`，每个队伍宝可梦一个游戏对象，0x1680 分开，状态字保持 8。

`0x886530` 运行来自主世界的每一帧，并在模式字 `+0x8C` (`0x886ed0..0x886ee8`) 上分支：1 或 2 战斗场景 (`0x886ef8`)，3 发布臂 (`0x886f24`)，其他任何内容都停在 8。 `0x344510` 是一次性的：当 `[x19+0x68]` 为非空时，它会提前返回，否则分配 0x278 字节并调用 `0x349bf0`。

设置器 `0x7c4530`（模式 1）、`0x7c4580`（模式 2）和 `0x7c45d0`（模式 3；最后两个然后调用
`0x147c90` 带0）通过`[singleton+0x288]`写入字；类 vtable `0x15afa68`（插槽 9 = `0x886530`）由 `0xe13388` 周围的重定位填充。从主世界追踪到已确定的交换，当模式字从 0 移动到 3 时，三个 setter 和 `0x5a733c` 从未触发。没有类方法存储到 `+0x8C`，并且 `.text` 中的 `+0x8C` 的 16 个常量存储中没有一个写入 3：作者未知。

<a id="the-sequence-a-take-over-has-to-carry"></a>
### 接管必须执行的顺序

宣布克隆的电台会分配一个序列并将其标记在其公告上。`0x520c30`，请求方，当克隆的时候提前返回`+0x38`为零，`+0x110`已设置，或`+0xB0`和`+0xB8`两者都非空；否则它将序列分配到`+0x10C`并将播音员加入队列。`0x520ce0`，完成后，将播音员取消排队并将 1 写入`+0x110`仅当`+0xB0`和`+0xB8`是非空的并且`+0x10C`等于给定的值。`+0x110`是门的每站术语：位于的条目`+0x250`是队伍克隆，`station[i]` = `partyClone[i]+0x38`.

方加入的接管（克隆类型上的 `0x91`）与对等方公告的时钟相呼应；它自己的副本的公告带有自己的时钟：

    host   0xa1 clone type 4   00000cfe 01 2808ab      the sequence it allocated
    host   0xa1 clone type 1   00000cfe 01 2808ab
    joiner 0x91 clone type 4   00000cfe               echoed
    joiner 0x91 clone type 2   00000cfe               echoed
    joiner 0xa1 clone type 4   00000d21 01 2808ab      its own clock, the host's content
    joiner 0xa1 clone type 1   00000d21 01 2808ab

`+0xB0` 和 `+0xB8` 是嵌入在以下位置的播音员的列表链接（`sub+0x08`、`sub+0x10`）
`clone+0xA8`（`0x51e790`链接，`0x51e810`取消链接）； null 表示不在公告列表中。在工作会话中，两个克隆都已链接，并且没有分配任何内容；到达的队列克隆未链接分配，并且随后的完成被拒绝。入站 `0x82` 也会使 `0x520c30` 进行分配，因此用携带 `0x82` 的突发应答每个重新通告会为每个突发生成一个序列，大约每秒 30 个。

每个克隆携带一个通告时钟：通告者在 `0xa1` 上标记其网状时钟，对等体的确认和该克隆的下一个 `0xa1` 携带相同的编号，并且 `+0x10C` 持有它。当记录带有克隆的另一站最新`0xa1`的时钟时，记录匹配。
`0x520d30` 处理克隆类型 2 上的 `0x91`（否定确认）和 `0x520ce0`
`0xa2`，相同前提下；两者均取消与播音员的链接，并且只有 `0xa2` 向
`+0x110`。匹配的 `0x91` 取消公告，匹配的 `0xa2` 完成公告； `0xa2` 是根据 加入方自己的时钟缺失构建的。

该序列针对每个队列克隆并重新分配（在 `0x520cb8`），每次分配将 0x34 步进到 0x38。通过接管携带加入方自己的时钟，主机为两个队伍克隆分配了 `0x1114b`；克隆 0 的完成携带 `0x1114b` 并设置 `+0x110`，克隆 1 携带 `0x111b0` 并被拒绝：门 `0x11b080` 保持 false 并且状态字永不离开 4. 仅应答对等方的第一个克隆类型 2 发布并确认其余的将返回到在每次都有新鲜的顺序。

<a id="the-take-over-exchange-a-joiner-runs-once-per-clone"></a>
### 每个克隆的接管交换 a 加入方运行一次

接管是所有权转移：`0x520d30` 取消对等方的公告，加入方在自己的时钟下公告克隆。两个队伍克隆的参考交换，主机的公告为零：

```
+0 ms   host    0x81 clone 2, 0x81 clone 3, dest 0x0003
        host    0xa1 x2 per clone                        clock 0x197e, the host's
+5 ms   joiner  0x82, 0x91 x2, 0x82, 0x91 x2, 0x84 x2    echoing 0x197e
+75 ms  joiner  0x81 clone 2, 0xa1 x2                    clock 0x19c1, the joiner's own
        joiner  0x81 clone 3, 0xa1 x2                    clock 0x19c1
+102 ms host    0xa2 per clone                           clock 0x19c1, the joiner's
        host    0xa1 per clone                           clock 0x19e2, the host's own
+141 ms joiner  0xa2 per clone                           clock 0x19e2, the host's
```
 加入方在第一次宣布不拥有的克隆时，将每个克隆接管一次。之后的每一次重播都会得到一个带有该播报时钟的 `0xa2`，位于加入方站下的克隆类型 2 上，地址 `<clock> 00 00 00 02`。第二次接管会取消原本不打算易手的公告，而同行则可以无限制地重新公告。

`0xa2` 推动完成。一个电台自己的播音员在大约6ms内完成对自己的`0xa2`的环回，因此第一个队伍克隆总是完成；第二个需要加入方。工作加入方的突发不携带确认：对等方的 `0xa2` 对在 +37 毫秒时到达，加入方的单个 `0xa2` 在 +72 毫秒时到达，作为答复。从不重新声明的对等点永远不会取消链接（每个滴答构建器的取消链接，链接后大约 30 毫秒）并且不分配任何序列。

仅对等重新通告会在 20 到 60 毫秒后在克隆类型 1 上绘制对等的 `0x82`，并且
`0x82` 绘制主机的 32 个零的 4 型副本，游戏机用其 `1 1 1` 进行回答。在一次重新声明后既没有收到 `0x82` 也没有收到提交克隆的任何后续消息的零售主机将停留在其确认屏幕上，并且交换锁已保存。 `pokeldn.ldn.clone` 每 100 ms 重新发送仅对等的 `0x81`，最多 20 次，直到 `0x82` 到达。

实机在 63、26 和 62 毫秒后回答了提交克隆 4、7 和 10 的第一个仅对等公告。同行首创，仅`0x81`版主（`--withhold-announce 1` on
`bin/lgpe_host.py` 和 `bin/lgpe_join.py`，仅测试），100 毫秒后重发绘制游戏机的
`0x82` 每个角色完成三个交易。

<a id="what-the-announces-destination-field-decides"></a>
### 公告的目的地字段决定什么

命令头 `0x51f820` 将 `+0x10` 布置为站位图。首次宣布克隆的 0x81 携带整个网格（0x0003）；克隆类型 4 和 1 上其后面的两个 0xa1，以及 35 毫秒后重复的公告，单独携带对等点 (0x0001)。给定网格位图，对等方在其自己的站点下的克隆类型 4 和克隆类型 2 上用两个 0xa2 进行应答；给定对等位图，它既不回答，又继续在克隆类型 1 上发送 0xa1，并且门 `0x11b080` 永远不会看到确认集填充。

克隆类型 1 上 `0xa1` 的重传计数表明工作会话与停滞会话：工作时每个站 9 次，每 0.12 秒一次，每次重播时由对等点接管，没有结束，其游戏静默。

每个克隆消息都是通过协议对象的第九个 vtable 槽 `0x51e3d0` 构建的（第四个返回 0x73）。其调用站点的文字类型：克隆类型 2 上的 0xa2 `0x51cbb8`、0x81 `0x51e92c`、
0xa2 克隆类型 3 `0x51cdd4`、0xc1 `0x51c9e4`、0x82 `0x51c60c` 和 `0x51cd5c`、0xe3 `0x51ad2c`，
0xf3 `0x51ef18`。该游戏在一个元素上包含三个克隆对象，类型 1 为 `game+0x90`，
`game+0x1710`，`game+0x1258` 处的类型 4；消息的克隆类型不会一对一地映射到它们。

|地址 |角色 |
|---|---|
| `0x51ab20` | CloneProtocol::vfunc9，每个元素接收 |
| `0x51c100` |接收调度：表 `0xf7673c` on（类型 - 0x11）将时钟与命令消息分开，`0xf76800` on（类型 - 0x84）到达命令路径 |
| `0xf769c4`，`0xf769e4` |采用高半字节结构；克隆类型|
| `0x51b010` |回复状态机，表 `0xf76674` 上（类型 - 0x21）|
| `0x51b1d0` |时钟驱动的重传调度程序
| `0x51f9b0`、`0x51fab0`、`0x51fbd0`、`0x51f820`、`0x51f4c0` |串行器：时钟请求、时钟回复、参与、命令头、ClockAndCount |
| `0x51c1e0` |删除一条消息，其计数在 [0xC] 不超过发件人的最后 |

元素偏移：+0x34 站、+0x40 状态、+0x50 时钟、+0x7a0 发送时间、+0x32c 结果。
