
<a id="joining-a-bdsp-session-and-what-is-under-the-encryption"></a>
# 加入BDSP会话，以及加密的内容

<a id="the-advertisement"></a>
## 广告

    local_communication_id  0100000011d90000
    scene_id                4352 (0x1100) Union Room; 5120 (0x1400) Union Room entered with a
                            password; 12608 (0x3140) Grand Underground
    version                 4
    channel                 a 2.4 GHz channel, band 2, chosen per session (6 in the capture)
    accept_policy           ALL
    participants            1/8
    application_data        17 bytes
 通讯 ID 为晶灿钻石的标题 ID，由明亮珍珠 (`010018e011d92000`) 共享。该广告仅用`prod.keys`（`tools/ldn/ldn_scan.py`）进行解密。 17字节的应用数据是Pia的LDN广告头（[无线层](ldn.md)），16字节，然后是1字节的应用数据；在没有密码打开的房间中，CRC32字段为0。

使用密码进入的房间带有密码 ASCII 数字的 CRC32、little-endian（00000000 -> `0xC0088D03`）和场景 id 5120。`bin/bdsp_connect.py` 不变地加入这样的房间；
`bin/bdsp_host.py --password 00000000` 对两者进行广告，并且使用该密码进入的游戏机加入并进行交易。游戏机分三个阶段进行检查（1.3.0 `main`）：

|舞台|代码|检查 |
|---|---|---|
|扫描| `NetworkHelper.CreateUnionGameMode` `0x224e630`; `nn::ldn::Scan` `0x16be184` |场景ID是游戏模式（0x1100普通，0x1200组，0x1400密码）和扫描过滤器（标志0x25：通讯ID，网络类型，场景ID）；另一个场景永远不会到达游戏|
|浏览 | `LdnMatchmakeSession` `0x16c1abc`; `GameState_BrowseSessionAfter_LocalRandom2` `0x273f804` |当 +0x04 处的 u32 非零时，房间受密码保护；有密码的游戏机会跳过未受保护的房间，而没有密码的游戏机会跳过受保护的房间 |
|连接 | `LocalMatchJoinSessionJob` `0x16c36c8`；支票 `0x16b8890` |方加入计算其输入的密码 (`0x1719204`) 的 `crc32`； +0x08 必须为 8，+0x04 处广告的 u32 之外的 CRC 失败，并在 `nn::ldn::Connect` 之前出现 0x6c51 |

主机将该标头写入 `LdnProtocol` `0x16b6a14`：网络 ID、密码的 CRC32、字节 8、会话参数。没有消息将加入方的 CRC 传送到主机：输入错误密码的游戏机不会向主机发送任何内容，并打开自己的房间。超过 8 个字符的密码为 Pia 保留 8 个字符，并将其余的移动到 `INL1` (`IlcaNetSession.SettingSet` `0x2735f14`) 后面的应用程序数据中。

<a id="the-passphrase"></a>
## 密码

    WirelessStrongCryptoKey2021
 使用原始：27 字节，既不填充也不散列（LDN 接受具有明确长度的 16 到 64 字节）。游戏将其交给`nn::ldn::SecurityConfig`中的`nn::ldn::CreateNetwork`；它永远不会到达 Pia 的加密货币。

<a id="taking-a-seat"></a>
## 入座

`bin/bdsp_join.py`扫描、关联并报告参与者表：

    participant 0: ip=169.254.54.1  mac=48f1eb209b22                 <- the console
    participant 1: ip=169.254.54.2  mac=58d8122149a2  name=b'POKELDN' <- the client
 游戏机分配IP。联合房间的八个座位是LDN `max_participants`。 LDN 席位位于游戏下方：屏幕上没有显示任何内容，并且它不是 Pia 会话中的席位。

`Connect failed with status code 1` 表示关联失败；ESP32 开发板大约有一半尝试会失败，因此应先重试，再排查原因。重新进入房间会打开新的网络（信道、SSID 和会话参数都会变化），密钥派生会实时处理这些变化。

游戏机可能在房间画面没有变化时停止广播：随机匹配逻辑会关闭它自己的会话，再次匹配。联合房间通过 `NetworkManager$$StartSessionRandomJoin` [1.3.0 main 0x0224f600] 启动会话（`SessionManager$$StartSession` 0x01df89e0，由 `UnionRoomManager$$SetUp` 和 `$$SessionStart` 调用）；所用 `NetworkParam` 的 `Reset` [0x0202ec30] 会将 `matchingMode` 设为 1（随机匹配），并选择本地网络。随机匹配创建或加入会话后（`GameState_JoinProcessAll` -> `ToGameFrontBeforeLocalRandom` [0x02743940]，这是进入游戏状态 20 的唯一路径），每次会话更新都会运行 `INL1.IlcaNetSession$$GameState_GameFrontBefore_LocalRandom` [0x02740640]：

| 站点数量 | 行为 |
|---|---|
| 2 或更多 | `GameFrontRnoInit` 清空两个计数器，进入游戏前台阶段 |
| 1 | 计数器 0 和计数器 1（`gameFront_cnt`）各加一 |
| 1，计数器 0 超过 `localRandomMatchmakeHostWaitTime + (localRandomMatchmakeHostWaitTimeMask & r)`，计数器 1 不超过 `localRandomMatchmakeTimeUp` | `CleanupRecoveryToLoggedIn` [0x0273a7f0]，游戏状态 9（`GS_LoggedInReturnWaitWorker`）：关闭会话并重新匹配 |
| 1，计数器 0 超过等待阈值，计数器 1 超过超时阈值 | `GameFrontRnoInit`；游戏机继续担任其会话的主机 |

每次进入状态 20 都会重新抽取随机值 `r`，同时清空计数器 0，保留计数器 1 继续计数。`IlcaNetSessionSetting` 构造函数 [0x01f46fc0] 将等待阈值设为 25、掩码设为 0x7F、超时阈值设为 270，`SessionConnector$$StartSession` [0x0202f2c0] 不会更改这些值。因此，独自在新会话中的游戏机会在 25 到 152 次更新后关闭会话，并反复执行这一过程；累计独处 270 次更新后，才保留最后建立的网络。LDN 接口上的接收方必须过滤自身的源 IP，因为广播会回送给自己。

会话每个渲染帧更新一次，即每秒 30 次，因此等待时间为 0.83 到 5.07 秒，超时阈值为 9.0 秒；掉帧会延长两者。在 1.3.0 main 中，调用链如下：

| 步骤 | 位置 |
|---|---|
| `NetworkManager.<IE_Start>d__28$$MoveNext` 订阅 `NetworkManager$$OnUpdate` | `Sequencer$$SubscribeUpdate` 调用 [0x0202da38] |
| `SubscribeUpdate` 将回调插入 `Sequencer._orderableList`（静态字段 +0x8） | [0x01a8fed0] |
| `Sequencer$$Update` 是 Unity 的 `Update`，在检查 `isSuspendUpdate`（静态字段 +0xC8）前，以 `Time.deltaTime` 调用列表中的每个回调一次 | [0x01a906d8]..[0x01a9071c] |
| 设置了 `[[this+0x30]+0x60]` 时，`NetworkManager$$OnUpdate` 调用 `SessionConnector$$OnUpdate` | [0x02253190] |
| `SessionConnector$$OnUpdate` 调用 `INL1.IlcaNetSession$$Update` 一次 | [0x02030a38] |

`Sequencer$$Awake` 将 `Application.targetFrameRate` 设为 30 [0x01a8ed68]。1.3.0 的 `globalgamemanagers` 中唯一的画质等级（`Ultra`，Unity 2019.4.27f1）将 `vSyncCount` 设为 2；在 60 Hz 输出下同样得到每秒 30 帧，并使 Unity 忽略 `targetFrameRate`。没有托管代码设置 `vSyncCount` 或画质等级。`TimeManager` 保存的固定时间步长为 1/30 秒。`NetworkManager$$OnUpdate` 唯一的其他调用方是 `SoftwareKeyboard$$Open` [0x01c980c8]。

未经身份验证的 Pia 会默默地被丢弃，不会出现错误，也不会丢失席位。

<a id="what-is-on-the-wire"></a>
## 电线上有什么

在电台确认之前，主机游戏机向其广播其更新会话
`169.254.x.255:12345` 每 100 ms，发送至 `dst_var = 0`；捕获的每个数据报为 176 字节：

    32ab9864 89 00000000 11bac90d 0000 00 f5a83bd383ce712d 59baa5cbc320cb56 <144 bytes>
    magic    v  dst=0    src      pid  f  nonce (a counter) tag              ciphertext
 版本字节 `0x89` 已加密，版本 9：Pia 5.27-5.45；可靠协议的版本 3 将其范围缩小到 5.31-5.43。标头、消息帧和传输协议位于[Pia 层](pia.md)。 `pokeldn/ldn/pia5.py` 往返 674 个字节相同的捕获数据包。

<a id="the-key-hierarchy"></a>
## 关键层次结构

    cryptoKeyDataSeed  9918bd0fdcfa65779918bd0fdcfa6577    from global-metadata.dat
    game key           9900bd0cdcfa65639918bd0fc7fa6577    = seed derived with version 199
    session param      0x36dee059                          advertisement +0x0c, little-endian
    session key        7b182cb087eeabd228a2efd91a8be147    = AES-ECB(game key) over 16 SEAD bytes
    network id         b4c85cf8                            advertisement +0x00, little-endian
    source MAC         48:f1:eb:20:9b:22
    crc32(netid||MAC)  0xda291352
    IV (first packet)  da29130df5a83bd383ce712d
 参考捕获的所有 674 个数据包均经过验证，并且对每个明文重新加密可逐字节再现游戏机的密文和标签。

<a id="where-the-seed-lives"></a>
### 种子生活的地方

`INL1.IlcaNetSessionSetting` 的构造函数设置默认值：

    IlcaNetSessionSetting..ctor
      byte[16] cryptoKeyDataSeed  <- RuntimeHelpers.InitializeArray(array, fieldHandle)
      string   wirelessCryptoKey  <- the "WirelessStrongCryptoKey2021" literal
      ulong    localCommunicationId = 0x0100000011d90000
 字段句柄解析为 `<PrivateImplementationDetails>.33F804682DF9E210AABDC4D939CBCD380EC7517F`，即 16 个字节的 SHA-1。该 blob 位于 `global-metadata.dat` 的字段默认值部分，既不在可执行文件中，也不在 RomFS 中；方法见[逆向工程Switch标题](switch_re.md)。

<a id="the-published-key-is-the-seed-derived"></a>
### 发布的密钥是种子，派生的

    seed (metadata)   9918bd0f dcfa6577 9918bd0f dcfa6577
    published key     9900bd0c dcfa6563 9918bd0f c7fa6577
                        ^^   ^^         ^^         ^^        bytes 1, 3, 7, 12
 游戏覆盖本地通讯版本的第1、3、7、12字节，1.3.0为199（广告中的`app_version`）； `ldn_game_key(seed, 199)` 复制已发布的密钥。

<a id="the-session-key"></a>
### 会话密钥

来自 `nn::pia::local::LocalProtocol`：

    seed  = a u32 session value held at LocalProtocol+0x5b0
    state = for i in 1..4:  prev = ((prev ^ (prev >> 30)) * 0x6C078965 + i)
    rnd   = four consecutive xorshift128 draws (shifts 11, 8, 19) -> 16 bytes, little-endian
    key   = AES-128-ECB(game key at LocalProtocol+0x5bc).encrypt(rnd)
 生成器是SEAD的RNG； `pokeldn/ldn/sead.py` 实现了它。

<a id="the-gcm-nonce"></a>
### GCM 随机数

IV 由流对象构建，每个网络系列一个：

    nn::pia::local::LdnOutputStream::vfunc3     0x16b39c4      the LDN sender
    nn::pia::local::LocalOutputStream::vfunc3   0x16bca80
    nn::pia::lan::LanOutputStream::vfunc3       0x16a0f80
    nn::pia::nex::NexOutputStream::vfunc3       0x16eca0c
 各取`(this, buf, buflen, packet)`；发送方在 `PacketWriter+0x948` 处调用它，接收方在 `PacketReader+0xc8` 处调用它。

    IV[0..3]  = u32be( crc32(ten bytes) )
    IV[3]     = overwritten with (packet.source_variable_id & 0xFF)
    IV[4..11] = the eight-byte header nonce, copied from packet+0x1b
 `0x1719204` 处的 CRC 是基于网络 id（小端，来自广告 +0x00，通过网络对象的 +0x450）和来自站记录的源 MAC 的普通 CRC32 (`0xEDB88320`)。无法从正在解密的数据包中恢复源MAC。

<a id="the-local-protocol-decoded"></a>
## 本地协议，已解码

参考捕获的每个数据包都携带相同的消息：

    presence 0x7f  flags 0x11  size 121  protocol 36  port 0  destination 0
 这是本地协议的 `0x11` 更新会话，每 100 毫秒重新广播一次，直到每个站都确认为止：

    local message header  version 1, type 0x11, size 73
    sequence id           4
    network id            8b4a3b22        random, not the advertisement's network id
    host variable id      11bac90d        the same value as the packet header's source variable id
    host constant id      0000 48f1 2022 9beb
    allow participating   1
    node 0                169.254.54.1:12345          the console
    node 1                169.254.54.2:12345   01     the client
    nodes 2-7             empty, marked 0xff
    host migration state  0
 八个九字节节点槽位，房间的八个席位，则一个字节。主机常量id，读取little-endian，通过LDN规则（`mac[2] << 56 | mac[4] << 48 | mac[5] << 40 | mac[3] << 32 |
mac[1] << 24 | mac[0] << 16`）解包到扫描到的MAC `48:f1:eb:20:9b:22`。 Pia 消息头是大端字节序，本地协议字段是小端字节序，其中的本地地址又是大端字节序。存在字节 0x7F 设置三个位，未命名 Pia 5.27-6.30 中的字段。

<a id="the-ack"></a>
### 确认

20 字节的 ack 位于 [Pia 层](pia.md#the-local-protocol-0x24)。有效的帧是主机自己的：带有数据包 `dst_var` 0 和消息目的地 0 的广播；单播帧未经测试。第一个 ack 停止更新：在捕获中，42 个更新间隔 100 毫秒，而 ack 比最后一个更新晚 34 毫秒。然后游戏机没有发送任何内容，而电台也没有再发送任何内容。

<a id="joining-the-mesh"></a>
## 加入网格

三次握手和ack规则位于[Pia层](pia.md#joining-a-mesh)。 BDSP的地址：

|什么|哪里 |
|---|---|
|站协议接收调度程序| `0x0154e848`，表`0x3e6b38f` |
|连接请求解串器| `0x0154ebd0` |
|内部错误的结果映射 | `0x0154f5e8` |
|通过 id 查找协议版本 | `0x0159b850`，未注册的 id 返回 0 |
|读取网格消息的 ack id | `0x01542db8`（`size - 4`，大端）|
|发送ack（8字节，在0x14上）| `0x01550324`，`mov w3, #8` |
|加入请求处理程序，主机端 | `0x0154b790`，`0x0154b868` |
|加入响应处理程序 | `0x0154b984`，`0x0154b9a4` |

`0x01550324` 属于 `session + 0xa0` 处的 MeshStationProtocol。加入响应处理程序是发送加入请求后存储在 `MeshProtocol + 0x128` (`0x0154e5c4`) 的指针 `JoinMeshJob`。

游戏机注册了九个协议（[测量](#measurement-methods)）：

    0x14 Station v2   0x18 Mesh v3      0x1c SyncClock v0
    0x24 Local v0     0x58 RTT v3       0x68 Unreliable v1
    0x7c Reliable v3  0x94 Session v1   0xa4 MonitoringData v0
 版本 0 的四个版本无法通过版本探测来区分是否未注册。

两站网格的连接响应：

    stations 2, host index 0, joiner index 1, max_active 8, update counter 0
    station 0   the console
    station 1   the client: its own station location and ids, read back
 游戏机在一秒钟内发送 RTT (0x58) 和可靠 (0x7c) 流量。结果 7 表示变量 id 已经是其站之一。

<a id="the-session-protocol-0x94"></a>
### 会话协议 (0x94)

`nn::pia::session::SessionProtocol`（1.3.0 `main`，vtable `0x4b5da50`）具有联合会话功能，并且在LDN上是惰性的。 Pia 的会话启动会构建它[`0x157c66c`]，除非设置了设置字节（GOT `0x4c4b850` 后面的+0x38），将其存储在会话+0xC8 中并给它一个
`transport::ReliableSlidingWindow` 每个其他站 [`0x1581938`]。当联合会话作业 (session+0x70) 为 null 时，其调度程序 [`0x15820b8`，跳转表 `0x3e6b986`] 的每个处理程序都会返回 null，并且在 LDN 上它始终是：`LdnNetworkFactory` 的槽 61 [`0x16b30ac`] 返回 null，唯一的其他存储是空值（`0x157c618`、`0x157d0e8`）。 Lan和Nex工厂建造`LanMatchJointSessionJob`和
`NexMatchJointSessionJob`。

它的窗口是游戏流的 `ReliableSlidingWindow` [构造函数 `0x159dab4`]，具有两个插槽环，协议 0x94，端口 1 (`0x159de54(window, 2, 2, 0x94000001)`)；接收位置为插槽 10 [`0x1581c98`]。在窗口读取 session+0x70 之前没有任何内容，因此有效的可靠 0x94 消息（第一个标记为 `is initialized`，序列低于基数加 2）被确认，然后由其处理程序丢弃。尚未捕获或发送 0x94。

<a id="hosting"></a>
## 托管

进入联合房间的游戏机在打开自己的房间之前会加入任何有空闲座位的房间（`matchingMode` `IlcaNetSessionInitMode.Random`，`localRandomMatchmakeHostWaitTime` 25，
`localRandomMatchmakeTimeUp` 270）。 `bin/bdsp_host.py` 主机一台，进入联合房间的游戏机加入其中； `pokeldn/bdsp/host.py` 握住主机侧。某零售店的广告：

    LDN protocol         1 (AES-CTR advertisement)
    frame version        4
    security mode        1
    scene_id             4352 (0x1100)
    app_version          199
    accept policy        ALL, 1/8
    application_data     17 bytes, the Pia header with a fresh network id and session
                         parameter, then one zero byte
 主机发送的内容，每个字节都从零售主机 (`tests/test_bdsp_host.py`) 重建：

|步骤|留言 |框架|
|---|---|---|
|一站联营公司|本地协议更新会话，每 100 毫秒一次，直到确认为止，加入方作为节点 1，排名为 1 |广播，`dst_var` 0 |
|它的连接请求|一个接受的连接响应，949字节：类型2的请求布局，主机的九个协议，它的站点位置，广告的网络ID，一个PlayerInfo，零填充，最后一个ack id | `dst_var` 0，标志 0x01 |
|它的网格连接请求|请求的 ack id 的站 ack，然后是加入响应（两个站，`max_active` 8，加入方在其条目中自己的位置字节）| `dst_var` 0 |
|加入响应已确认 |可靠窗口上的 `NetJoinData`，序列 1，标志 0x0F | `dst_var` 加入方 |
|从此|每秒更新网格（556 字节），RTT 请求，`NetCharacterStateData{0, 0}` 上的 0x68 | `dst_var` 1，目的地 0xFFFFFFFF |

主机所在站位置无公网地址且NAT字段为零，36字节；加入方都有 40。主机的站条目具有索引和加入顺序 0，加入方为 1。

方加入根据已确认的加入响应大约每秒发送一次同步时钟 (0x1C) 请求；主机以请求的滴答声和网格时钟（以毫秒为单位）进行应答。当屏幕显示“communication en cours”时，同步时钟请求未得到答复的方会反复取消身份验证并重新关联。在第一次请求后大约十秒就出发了；超时未读。应答后，它发送 `NetJoinData` 并请求 0x04 和 0x23，就像零售主机所做的那样，从那里房间是对称的：接近、问候和[交换](bdsp_trade.md) 与游戏机作为加入方一样运行。

<a id="leaving"></a>
## 离开

离开房间的游戏机运行 Pia 的网状离开作为加入方，并将其主机迁移离开作为主机。两者都在网状协议的可靠窗口（0x18 端口 1）上打开，在序列为 1 的可靠标头下，并且都等待在端口 0 上不可靠发送的答案。零售 Pia 将每个答案发送两次，第二次在其自己的数据包中。网格调度程序是 `0x0154ac94`（跳转表
`0x3e6b25a`，在 `0x3e6b35c` 后面键入 0x40 到 0x4A）。

|游戏机|发送 |是欠|结束等待的处理程序 |
|---|---|---|---|
| 加入方, `LeaveMeshJob` | `04 <own index>`，请假请求| `08 <host index>` 主机 | `0x0154baf8`，清除作业+0x7c |
| 加入方，然后 |站断开请求，0x14 上的 `03` | `04` | |
| 主机, `LeaveWithHostMigrationJob` | `44 <host index> <new host index>`，每站一张 |各站`48 <station index>` | `0x0154b068`，清除作业+0x6e[索引] |

主机的离开请求处理程序`0x0154b9e0`拒绝除2以外的大小、索引0xFD和自己的索引，通过`0x0154c860`（`08`和主机自己的站索引）应答并丢弃站。
`LeaveMeshJob::WaitLeaveResponse` 当响应清除其标志或截止期限已过时，`0x0155fd2c` 继续前进。 `LeaveWithHostMigrationJob::WaitMigrationResponse` `0x015607bc` 在任何当前站的标志被设置时等待；离开的电台会清除自己的电台。

没有回答的情况下测量：

|游戏机|第一条消息 |那么|走了|
|---|---|---|---|
| 加入方离开托管房间（4 次捕获）|每 0.125 秒发出一次请求，持续 4.9 至 5.0 秒 |从 3.6 秒开始，每 0.5 秒发出一次断开连接请求（一次捕获运行到最后）|在第一个请求后 9.0 秒取消身份验证，在该捕获中 |
| 主机离开房间并加入一站（4 次捕获）|每 0.125 秒迁移一次，持续 4.9 秒 |更新会话，序列+1，迁移状态1，每0.11s更新一次，持续10s；然后本地协议 0x13（开始主机迁移）每 0.3 秒一次，持续 10 秒 |首次迁移开始后 25.3 秒其网络关闭 |

已答复（`08 00` 两次和 `04`），零售加入方离开在其离开请求后 0.06 秒发送了一个断开连接请求，并在其后 0.15 秒取消身份验证。已应答（`48 01`，更新会话确认，0x13 上的离开），发送了离开房间的零售主机
0x13 迁移开始（2 次运行）后 0.11 和 0.45 秒并关闭它。

0x13 阶段由 `LocalDestroyNetworkJob::WaitUntilAllClientsDisconnection` `0x016b95b8` 实现。距上次发送（`job+0x68`）超过 301 毫秒时重新发送 0x13，并在以下任一条件先满足时结束：请求的取消字节置位，转到 `WaitForCancel` `0x016b9330`；`0x016b014c` 返回的在场站点数量为 1（`0x016b9614`）；距前一状态 `WaitUntilAllClientsReceiveUpdateSessionMessage` `0x016b936c` 超过 10000 毫秒，其时间存于 `job+0x70`（`0x016b9644`）。后两者进入 `StartDestroyNetwork` `0x016b950c` 并关闭网络。站点离开会使此阶段在下次更新时结束；站点留在网络中则等待完整的 10 秒。前一状态在 `[[protocol+0x4f0]+0x5c]` 置位（`0x016b0888`）或经过 10001 毫秒后结束。

`pokeldn.bdsp.session.answer_departure` 构建了两个答案； `bin/bdsp_host.py` 应答离开加入方及其断开连接请求，`bin/bdsp_connect.py` 应答迁移开始、确认每个后续更新会话并在 0x13 上离开网络（`--no-leave-on-host-migration` 保持）。

离开交换框不会发送离开消息：框的关闭回调 `TradeSelectPokeModel$$CheckComplete` [1.3.0 main 0x1c26810] 发送 `NetDataCurrentFlowCancelData{0}` (0x25, `SendCancel` 0x1c26bf0) 和
`UnionTradeManager$$Cancel` [0x1c33780] 发送 `NetCharacterStateData{0}`，两者都在一个数据包中，无需等待合作伙伴。

<a id="measurement-methods"></a>
## 测量方法

- 仅当协议计数与其自身匹配时，游戏机才应答连接请求；扫描计数得到 9。未注册的协议需要版本 0，因此版本 1 会失败，二分法会读取任何协议的版本。
- 信号必须是回复；沉默往往就像一个丢失的数据包。可靠的窗口会确认它接受的数据，因此只发送数据并扫描序列 ID。
