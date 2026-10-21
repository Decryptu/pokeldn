
<a id="legends-arceus"></a>
# 传说 阿尔宙斯

宝可梦传奇：阿尔宙斯（2022，游戏 ID `01001f5010dfa000`）是一款原生 Switch 游戏，Pia 静态链接到 `main`。

地址是更新 1.1.1 的解压缩 `main` 中的偏移量，如 `tools/switch/nso_read.py` 所示（文本 `0x0..0x32a5690`，来自 `0x32a6000` 的rodata，来自 `0x401a000` 的数据）。

<a id="the-wireless-layer"></a>
## 无线层

| |价值|
|---|---|
| Pia 头版本 | 11、wiki 的 Pia 6.16 至 6.23 频段（剑 4、BDSP 9、GBA app 15/16）|
|标题大小 | 0x1C |
|电线上的 GCM 标签 | 8 个字节，从 16 个字节截断 |
| LDN 密码 | 剑／盾的，`HGhG` 拼写（wiki 的 `HGHG` 行是错误的）|
| Pia游戏键| `p1frXqxmeCZWFv0X`，为剑／盾和朱／紫 |
| LDN 本地通信 ID | `0x01001f5010dfa000`，标题id |

游戏密钥和密码位于 `0x3985308` 和 `0x3985319` 的 RODATA 中，以 NUL 结尾。 `0x2c1e684` 处的 LDN 设置采用 `x3` 中的本地通信 ID（`mov`/`movk` 在 `0x264082c` 上运行）并在 `0x2c1e880` 处安装游戏密钥。

`0x6f0744` 处的标头初始值设定项将魔术 `0x32AB9864` 存储在对象 `+8` 处，并将 `0x0b` 存储在
`+0xc`; `0x6f07d0` 的验证器检查魔法，`(byte & 0x7f) == 11` 和数据包长度减去
0x1C低于0x5a5。数据包缓冲区为`+0x30`（容量为0x5c0），长度为`+0x5f8`； `0x6f0878` 处的副本分配固定了每个字段的大小：

    wire  object  size  field
    0x00  +0x08   4     magic 0x32AB9864, big-endian
    0x04  +0x0c   1     0x80 (encrypted) | version (0x7F) = 11
    0x05  +0x0e   2     destination variable id
    0x07  +0x10   2     source variable id
    0x09  +0x12   2     packet id
    0x0b  +0x14   1     footer size
    0x0c  +0x15   8     AES-GCM nonce
    0x14  +0x1d   8     AES-GCM tag, truncated from the 16 the object holds
    0x1c                ciphertext, then the footer
 页脚在加密之外。加密路径 `0x6f09f4` 减去页脚大小，
0xFF填充到块大小，从缓冲区`+0x4c`加密，通过AES-GCM条目`0x6e68d0`将标签写入`+0x1d`，标签长度为8（`mov w4, #8`位于`0x6f0b24`），然后OR `0x80` 进入版本。

<a id="the-receive-path-for-a-breakpoint"></a>
## 断点的接收路径

    0x6ff6d8   nn::pia::local::LocalInputStream::vfunc4, the socket read
    0x6f07d0   the header validator (five callers; 0x6ff6fc is the input stream's)
    0x6f0b84   the packet decrypt, through the GCM entry at 0x6e6aac; failing here is key, IV or tag
    0x6f09f4   the packet encrypt
    0x7015b4   LdnBackgroundProcessJob::WaitConnected, the step body a stalled joiner sits in
    0x70c304   LdnProtocol vfunc18, which that step requires to return 0

<a id="the-gate-a-joiner-stops-at"></a>
## a 加入方停止的门

谓词 `0x6f63fc` 读取 LdnProtocol 对象上的两个端点槽，`+0x98` 和 `+0xb8`（每个 0x20 字节：`+8` 处的 16 字节地址，`+0x18` 处的本机 u16 端口）：

    0x6f0ee4(a)     -> set: port non-zero and address not the sixteen zero bytes at 0x3972091
    0x6f0f48(a, b)  -> equal: same port, same sixteen address bytes
    0x6f63fc(obj)   -> 0 unless both are set, then 0x6f0f48's answer
 连接加入方同时保存游戏机自身地址和Pia端口，返回1；仅在拆卸和下一次连接之间，槽位为零。该门不会阻止加入方。

<a id="what-a-message-is-routed-by"></a>
## 消息的路由方式

调度键是数据包的源变量 id：来自注册表中缺失的站的消息在查阅其协议之前会被跳过，并且变量 ids 会在每个会话中重新滚动。消息标志`0x01`表示“跳过源变量id检查”，对于在对等方知道发送者之前发送的消息； `bin/pla_host.py` 将其设置在两个探头上。

<a id="the-net-protocol-measured"></a>
## 网络协议，测量

托管其自己网络的游戏机打开与 `NetUpdateNetworkConnectionStatusMessage` 的交换（协议 0x2C，类型 0x11）。它与 wiki 的 6.16 至 6.39 布局相匹配，其网络 ID 是从广告的 SSID 派生的：

    01 11 002a          header version 1, type 0x11, payload size 0x2a
    00000002            sequence id
    eb6f                host variable id, a fresh value every session
    ac56011000020000    host constant id, ldn_constant_id of 02:00:ac:10:56:01
    000000004f264487    network id, the low four bytes being crc32(ssid[1:16])
    01                  is network open
    0002                number of stations
    00                  is migrating host
    ...                 two NetStation entries
 NetStation 在此频段有 21 个字节，其中 6.39 有 22 个：

    +0x00  1   host migration state
    +0x01  1   host migration ranking
    +0x02  1   one byte where 6.39 has two, disconnection candidate and kicking
    +0x03  18  station address: 16 bytes of address, then a big-endian u16 port
 两个条目都携带端口 12345，游戏机排名为 0，加入方排名为 1。

托管交换的游戏机不回答发送到其变量 id 的会话 (0x98) 加入请求（下面的读卡器门将其丢弃）。它要求加入的站点担任主机角色：

| 方加入行为| 游戏机 |
|---|---|
|使用 0x12 ack 回答 0x11 | 0x11 再次使用新的序列 ID 和 `is migrating host` 1，然后是 `01 40 00 00`（裸 `NetStartHostMigrationMessage`）大约每秒两次 |
|发送加入请求，从不回复 0x11 |每0.5秒相同的0x11，然后设置`is migrating host`，然后设置`01 40 00 00`，然后网络下降（关联后8.6到10.1，13.5到14.1和16.8到17.5秒）|
|答案为 `NetUpdateNetworkHostMessage` |不断重复0x40 |

在游戏机的第一个 0x11 收到指定其后继者的会话类型 7 后 4.5 秒，方加入将其加入请求加入到目的地 0，并在电台列表后 0.02 秒（模拟游戏机上的 4 个席位中的 4 个席位；ESP32 板上的一个零售席位）保持 4.5 秒。新主机通过在相同代码上创建网络来完成迁移：游戏机在请求后 3 到 6 秒内断开自己的网络，加入新网络并以加入方的身份进行交易。 `bin/pla_join.py` 在第一个 0x40 上离开座位并运行
`bin/pla_host.py` 在相同的代码和通道上，或通过 IP 与 `--ip-join`（`--take-host`，默认情况下打开）。针对模拟游戏机的序列：类型 7、类型 8，加入方的主机在最后一个数据包后 5.2 秒上升，游戏机在 0.02 秒后加入（[加入游戏机网络](#joining-a-consoles-network)）。

每个网络消息都有一个带有序列化器的命名标头类。 `NetUpdateNetworkHostMessageHeader` (`0x6fe03c`)：u64 位于线 +4，u64 位于 +0xc，u16 位于 +0x14，大小 0x16，大端。 0x11 标头 (`0x6fd9dc`) 映射对象 +0x0c、+0x10、+0x18、+0x20、+0x28、 +0x2a 接线 +4、+8、+0xa、+0x12、+0x1a、+0x1b。 `nn::pia::session::ClusterPacketWriter`（0x732264 到 0x7336e8）内联写入会话消息。

主持搜索的游戏机通过离开来移交主机角色。`Session::LeaveAsync` 启动 `LeaveSessionJob`，其 DisconnectNetwork 步骤（`0x72c9dc`）调用网络接口槽 15；网络主机上，只要 `NetProtocol+0x248` 置位，就启动带主机迁移的 `NetDestroyNetworkJob`（`0x7069d0`）。构造函数 `0x6f48fc` 将其设为 1（`0x6f4a14`），这是唯一写入处。任务以新序列号发送 Net 0x11，并把 `is migrating host` 设为 1（`0x6f6af0`）；等待各 0x12 最多 4000 毫秒（`0x706b34`），然后每 300 毫秒发送 `NetStartHostMigrationMessage`（`0x6f7674`），直到只剩本站或超时：0x11 完整确认后 4000 毫秒，未确认超时后 2000 毫秒（`0x706df0`、`0x706e98`）。随后销毁 LDN 网络，仍在网络中的站点继承主机角色。14 次 `bin/pla_join.py` 入座中，游戏机丢弃 Session 加入请求，没有回复；首次迁移 0x11 在入座后 8.3 至 10.3 秒到达，持续重发 4.0 秒，再发送 0x40 持续 2.0 秒。

站点关联后不发送 Session 加入请求，也会按此方式结束席位。模拟器游戏机主持搜索时，使用 `bin/pla_join.py --join-delay 20`，WaitMember 定时器到期（`0x2bdb7a0`）发生于入座后 0.99 秒，2 毫秒后匹配序列的错误处理程序构建离开请求（`0x2c27fb8`；捕获的错误类型名不匹配 `0x2c4ee3c` 时，由 `0x2c4ee60` 调用）。`Session::LeaveAsync`（`0x72a6dc`）约在 1.4 秒时执行。`LeaveSessionJob` 随后运行 `LeaveMeshWithHostMigrationJob`（`0x72c640 -> 0x734c8c -> 0x73eee4`），轮询下一主机直到 8000 毫秒后的截止时间（`0x73efb4`）；没有 Session 路由的站点（路由字节 +0x90、+0x91 为 0xfd）始终不符合条件，所以断开及迁移 0x11 在等待 8 秒后发生：不设置断点时为入座后 10.48 秒。

游戏机将网格创建为全网格主机（`CreateSessionJob`，无需等待）。加入的游戏机从其自己的变量 id 向标头目的地 0 发送其会话加入请求。主机的
`ClusterPacketReader`门`0x744644`（通过vfunc `0x98`，`0x731edc`调用，在`0x743ec0`）在其站之间查找单播数据包的源变量id（`0x744718`，manager vfunc）
`0x48`）并在没有匹配时丢弃数据包（`0x7447a8`）；发送到目标 0 或 1（不带页脚）或来自源变量 id 0 的数据包将跳过查找。因此，从尚未注册的加入方发送到主机变量 id 的加入请求在解密后会在会话调度程序之前被丢弃。发送到目的地0，它绘制加入响应和类型5站列表。托管搜索的模拟游戏机在加入方以这种方式就位后约 10 秒离开迁移，不发送数据交换记录，并返回到其搜索且不显示任何错误。

<a id="the-packet-crypto"></a>
## 数据包加密

| | |
|---|---|
|会话密钥 | `AES-128-ECB(game key)` 超过一区块的网络SSID |
|网络 ID |删除第一个字节的 SSID 的 CRC-32，`ssid[1:16]` |
| GCM IV | `u32be(network id XOR source IP)` 然后是标头的八个随机数字节 |
|标头随机数 |每个数据包计数器，大端 |
|标签| GCM 标记的前 8 个字节，位于标头 |

`0x70d61c` 派生会话密钥：它重复一个短于 16 个字节的种子（`0x10 / len` 在
`0x70d66c`）并在 `LdnProtocol+0x238` 的游戏密钥下加密一个 ECB 块。加密模式 0 位于
`LdnProtocol+0x234` 将密钥保留为全零。

`nn::pia::local::LocalOutputStream::vfunc3` (`0x711710`) 构建 IV：`0x6ed380` 在 `IV[0]` 写入大端 XOR，然后标头的 8 个随机数字节转到 `IV[4]`。发送方递增每个数据包的随机数并通过 `0x6ed360` 写入。 GCM 加密设置为 `{mode +0, IV
pointer +8, IV length +0x10, key pointer +0x18, key length +0x20}`：模式 1、IV 12、密钥 16。

`pokeldn/ldn/crypto.py` 对整个 6.16 至 6.42 频段进行相同的推导。

<a id="the-protocols-above-the-packet"></a>
## 数据包上面的协议

Pia 6.16 至 6.30 将 5.29 至 5.45 id 保留在会话层以下，并用一种会话协议取代了站协议和网状协议。 id 在 6.32 再次更改：

|协议| 5.29-5.45 | 6.16-6.30 | 6.32-6.40 |
|---|---|---|---|
|网|缺席| 0x2C | 1 |
|实时传输时间 | 0x58 | 0x58 | 3 |
|不可靠 | 0x68 | 0x68 | 5 |
|克隆，从原子到时钟| 0x74-0x77 | 0x74-0x77 | 6-9 |
| 可靠传输 | 0x7C | 0x7C | 10 |
| 可靠广播 | 0x80 | 0x80 | 11 |
|会议| 0x94 | 0x98 | 13 |
| 监测数据 | 0xA4 | 0xA4 | 15 |
|站、网状网络、同步时钟、本地 | 0x14、0x18、0x1C、0x24 |缺席|缺席|

`pia_connect.py`（网络、会话、RTT 为 6.32）适合此频段，其 ID 已重新编号；
`station_protocol.py` 和 `mesh_protocol.py` 实现此处缺少的协议。

游戏机的加入请求列出了其协议版本：

    Net 0x2c v0   RTT 0x58 v3   Unreliable 0x68 v1   Clone 0x74 v0   Clock 0x77 v0
    Reliable 0x7c v2   BroadcastReliable 0x80 v3   0x81 v3   Session 0x98 v0   Monitoring 0xa4 v0

<a id="the-session-join-request"></a>
### 会话加入请求

来自 `ClusterPacketWriter` 的 115 字节会话类型 0 消息：类型字节、协议计数、上面的 10 个 `(id, version)` 对，然后：

    +22  4   random, fresh on every repeat; Scarlet seeds it from the system tick
             (`docs/sv.md`, The Session join request)
    +26  8   source constant id, ldn_constant_id of the console
    +34  2   zero
    +36  2   source variable id, the joiner's own, fresh per session
    +38  1   NAT mapping
    +39  1   private-IPv6 flag
    +40  32  identification token, all zero on a codeless join
    +72  1   address kind, 0 for IPv4
    +73  4   source station address, IPv4
    +77  2   source station port, 12345
    +79  8   destination constant id, the host's
    +87  2   zero
    +89  2   destination variable id, the host's, `00c6`
    +91  1   player count, 1
    +92  1   a flag, 1
    +93  22  one player record: id `00..01 00..00` (two big-endian u64, 1 and 0), a big-endian u32
             name length of 1, a kind byte of 1, the name, a single space
 线路上的位置 id 为 12 个字节：big-endian u64 常量 id，两个零字节，big-endian u16 变量 id。每次重复时消息标志为 `0x01`。 `pokeldn.ldn.pia6.build_session_join` 再现 115 字节 (`tests/test_pla_session_v11.py`)。

<a id="the-session-join-reply"></a>
### 会话加入回复

连接方解析 `0x737534` 处的确认和 `0x7379c0` 处的连接响应，通过 `main+0x3973f19` 处的类型表从接收循环 `0x7353a0` 调度。每个都比较四个 ID，并在不匹配时默默地丢弃消息：主机将请求的目标 ID 回显为自己的，并将其源 ID 回显为游戏机的。

ack 是会话类型 1，25 个字节：类型字节、主机位置 id、游戏机位置 id。设置`JoinMeshJob+0x69`，并将加入截止时间`job+0x80`延长8000毫秒；它什么也完成不了。

加入响应是会话类型2，43字节：

    +0x00  1   02
    +0x01  1   protocol id 0x98, read only when status is 3
    +0x02  1   Session version, read only when status is 3
    +0x03  1   status, 1 is the accept path
    +0x04  8   unread on the accept path
    +0x0c  12  host location id, four-field compare
    +0x18  12  console location id, four-field compare
    +0x24  1   route byte A, stored to the self station +0x90
    +0x25  1   route byte B, stored to +0x91
    +0x26  1   station index, sets bitmap bit [+0x788][index]
    +0x27  2   join order, big-endian u16, stored to +0xf8
    +0x29  2   sequence id, big-endian u16, stored to +0xde
 分配字段存储时未经验证（游戏机的作者 `0x736cec` 将路线 `00 01`、索引 1、第一个加入方的加入顺序 1）。状态 1 设置 `JoinMeshJob+0x68` 并停止请求重复（大约一个窗口十六次）。一旦应用了序列达到 `+0x29` 的更新，则完成标志 `JoinMeshJob+0x7c` 由类型 5 更新 `0x738740` 设置；方加入以 13 字节会话类型 6 进行响应：类型字节、游戏机常量 id、两个零字节、序列。

<a id="the-type-5-station-list-update"></a>
### 5 类电台列表更新

`0x7404a8` 在 `0x73897c` 读取更新之前重新组装更新；一个片段承载了一切。七字节片段头是字节类型、big-endian u16 序列、片段计数、片段索引和 big-endian u16 偏移量。缓冲区以类型和序列为种子，因此 VOC 从主机常量 id 开始，偏移量为 3。重新组装的主体：

    +0x00  1   05, the reassembly byte
    +0x01  2   sequence id, big-endian u16
    +0x03  8   host constant id, big-endian u64
    +0x0b  4   host variable id, a [0000, u16] big-endian u32
    +0x0f  1   station count, at most 0x18
    +0x10  n   IPv6 bitmap, (count + 31) / 32 * 4 bytes, little-endian u32 words, bit i set for an
               IPv6 station
       ...     station entries
 由 `0x739050` 读取的每个站条目，采用 IPv4 形式：

    +0x00  8   constant id, big-endian u64
    +0x08  4   variable id, a [0000, u16] big-endian u32, the low half passed to the admit
    +0x0c  4   IPv4 address
    +0x10  2   port, big-endian u16
    +0x12  1   route byte A
    +0x13  1   route byte B
    +0x14  1   station index
    +0x15  2   join order, big-endian u16
    +0x17  1   NAT mapping
    +0x18  1   private-IPv6 flag
    +0x19  32  identification token
    +0x39  1   player count
    +0x3a  1   participant count
    +0x3b  ..  player records, each a 16-byte id, a big-endian u32 name length, an encoding byte, and
               the name
 IPv6 站携带 18 字节地址来代替 6 字节地址。主机为路由 `00 00`，索引 0，加入顺序 0；第一个加入方 `00 01`, 1, 1。玩家记录是加入请求的。
`0x738bc0` 通过常量 id 更新或创建每个站，然后设置 `JoinMeshJob+0x7c` 并发送类型 6。然后加入的游戏机运行 RTT、克隆时钟和流广播可靠流。

<a id="sustaining-the-mesh"></a>
## 维持网格

除非先完成 0x81 数据交换，否则加入的主机会在游戏的 DataExchangeStart 步骤超时后离开，实测为加入请求后 10.2 秒（[游戏读取器与处理函数注册前的阶段](#the-games-reader-and-the-pre-handler-phase)）。RTT（0x58）共 11 字节：类型、八字节时间戳、两字节目标；目标为 0 的类型 1 回显会被接受。

Stream Broadcast Reliable（0x81，可靠流广播）承载 `pokeldn/ldn/reliable5.py` 滑动窗口：先是 9 或 13 字节头部，再接应用数据；应用数据标志未置位时，则接 `2 + 21 * count` 字节的批量确认。确认消息开头的类型字节只读取第 0 位；每个 21 字节条目由站点字节、大端 u16 确认 ID、大端 u16 字段和 16 字节掩码组成。消费方（`BroadcastReliableSlidingWindow` vf13 `0x742730`）读取自身站点索引对应的条目，并要求其中的站点字节等于发送方索引：主机确认索引 1 的加入方时，至少发送两个条目，所有站点字节都为 0。ID 和掩码遵循[确认机制](#acknowledgement)。

消费方将每项的第二个半字存入 `[window + 0x528 + 2 * station]`（`0x742828..0x742830`），根据类型第 0 位设置 `[window+0x4b8]`，并通过 0x7c 窗口的 `0x74f0ec`（`0x742880`）应用 ID。发送路径 vf11 `0x742304` 从目标位图中移除半字为 `0xffff`、不低于窗口基值或槽位为空的所有站点（`0x74238c..0x74242c`），再将位图交给确认发送函数 `0x74ea00`：`[window+0x4b8]` 未置位时不执行；位图为空时清除它并写入时间戳 `[window+0x4c0]`；否则发送 AckMessage，序号 `0xffff`、长度 `2 + 21 * count`（`0x74eb64..0x74eb94`），每个占用站点一项（`0x74eba0..0x74ec2c`，由 `0x74ec80`、`0x743160` 序列化）。该半字仅门控确认，不影响重传。捕获的全部 30 次加入中，主机 0x81 应用消息的序号均为 1，因此主机端的确认使用 `ack_id 2`；主机仍确认到最高已收序号加一。

主机用 INITIALIZED 数据消息（标志 `0x0f`，序号 1）及第二条消息打开流；大约每秒发送一次确认，其中的主机端流 ID 会在主机端不发送数据时持续增长。主机端数据的目标位图若包含游戏主机站点索引对应的位（第 1 位，数量 2），就会被应用；位不正确时会在发送站点检查处丢弃。

<a id="the-silent-station-check"></a>
### 静默站检查

会话启动 `0x729d3c` 将启动设置的 `+0x28c` 复制到 `SessionProtocol+0xd8` (`0x72a098`)，没有下限（Z-A 的下限为 4000 毫秒），并将 `+0x290` 传递到发送静默限制（`0x746fe4`：负数失败，0x10407，0 变为 1000 ms）。每次更新 `0x73564c` 都会列出处于状态 2 的每个站，其最后一个数据包 (`ClusterStation+0x88`) 早于 `[SessionProtocol+0xd8]` 毫秒，在主机和加入方上都是如此。一旦第一个条目已存在 3000 毫秒 (`0x735364`)，`0x7359ac` 就会在列表上起作用：主机将每个电台交给 `KickoutManageJob` (`0x73cad4`)；列表中命名为主机的方加入将主机视为已消失 (`0x735b28`)。设置的 `+0x28c` 读取 10000 毫秒（托管搜索的模拟游戏机上的 `0x72a09c` 处的 `w9 = 0x2710`），如 Z-A 中所示。盒子屏幕上的无声主机在大约 13 秒内绘制伙伴留下的消息：10000 毫秒和 3000 毫秒宽限期。

<a id="the-games-reader-and-the-pre-handler-phase"></a>
## 游戏的读取器和预处理程序阶段

游戏在 `main+0x2ca4f30`（`0x741494`）轮询读取器（一个实测时间窗口中调用了 365 次）：0x7C 和 0x80 两个循环共用同一处理函数表。0x81 上的主机端数据不会到达此表。消息前八字节是由两个 u32 组成的处理键；匹配的处理函数接收剩余内容，不匹配的键则被丢弃。

在交换搜索界面，处理函数表为空（读取后的 `ldr x8, [x19+0xd0]; cbz x8`），因此所有消息都会被取出而不处理。`0x2ca5264` 在流程步骤 0x1e 注册处理函数，超时的会话从未到达这一步；离开菜单时处理函数数组指针被清空。实测空闲时读取循环每秒约执行 2.5 次。游戏的九个 Pia 调用点仅涉及 0x68、0x7C、0x80（三条读取循环、四条发送路径）；0x77 时钟流量来自 Pia 自身。

十秒后离开属于游戏匹配流程的失败分支，位于 Pia 网状网络加入流程之上；成功分支进入交换场景。交换流程为 `0x13d5bfc`，步骤位于 `[flow+0xa4]`，跳转表 `0x397c118` 对应步骤 0x15 至 0x22。步骤 0x17 调用 `0x26bdcac`，在 `[manager+0x70]` 构造序列；步骤 0x18 通过虚函数表槽位 9（`0x12b3290`）轮询它，未完成子任务计数器 `[request+0x70]` 为零时返回真。该流程不读取任何网络、会话或网状网络字段。步骤 0x1e 注册处理函数（`0x13d5f94 -> 0x26d8c2c -> 0x2bcb8c8 -> 0x2ca5264`）。以下按 `0x26bdcac` 与函数对象配对的名称字符串列出序列步骤：

    LoginRelayServer     looked up before the sequence is built; a missing one returns false
    Matching             the matchmaking, from the TradeMatchmakingConfig record
    DataExchangeStart    the two-round data exchange and its 10.0 s deadline
    OnCancelDataExchange
    OnSuccess            the trade scene
    OnFailure            event 8, flow step 0x23 (table `0x397c134`), the leave
    OnCancel
    Cleanup

步骤 0x18 的第二个门控条件为 `0x13de870`，位于持久网络菜单对象的 `[obj+0x7c] == 1`。当当前页面（`[obj+0x88]`；ViewTop `[obj+0x90]` `0x13de950`、ViewAlert `[obj+0x98]` `0x13de9d8`、ViewInMatching `[obj+0xa0]` `0x13dea28`，由 `0x13de3cc` 根据 `netm` 布局构造）在其 `+0x5bc` 中返回结果 1 时，分支 0 的更新函数 `0x13de888` 会设置它。只有玩家输入会写入它：InputDecide 和 InputBack 写入 1（`0x13dc7b4`、`0x13dc7ec`、`0x13dd3ec`，在 `0x13dc0a4`、`0x13dc1a0`、`0x13dc9a0` 安装）；`button_00`、`button_01` 对应 2、3（`0x13ddcb4`），并设置 `[obj+0x7c] = 2`、`[obj+0x84]`。第一个门控条件，即子任务计数器，在 `0x13d6130` 读到 0。

DataExchangeStart 步骤的启动函数 `0x26c5288`（由 `0x26be3f0` 构建，步骤名之后在 `0x26bde74` 调用；Matching 为 `0x26be354`）将数据交换对象保存到 `[step+0x118]`，并在 `[step+0x120]` 启动基于系统 tick 的秒表（`0x26c539c`）。更新函数 `0x26c6988` 在收到至少两个站点的记录，且每个已占用槽均有记录时完成（`0x26c6b70`、`0x26c6c04`）；否则将经过秒数与常数 10.0 比较（`0x26c6a94` 的 `fmov d1, #10.0`，测得加入请求后 10.2 秒），并以 `net_contents::p2p::ErrorLeaveAnyone` 使请求失败（虚表 `0x416c628`，由 `0x26c6d30` 构建）。失败经 `0x13d654c -> 0x13d6384 -> 0x2c43d78 -> 0x2ca0a10 -> Session::LeaveAsync (0x72a6dc)`，随后弹出错误 7。进入 `0x2c43d78` 的调用是间接的：没有指令直接引用它，在入口回溯帧得到返回地址 `0x12b37fc`、`0x12b23d0`、`0x2c227c0`、`0x26be9b0`、`0x13d63d0`。模拟器游戏机主持搜索、加入端不发送数据交换记录时，`0x26c6d30`、`0x13d6384`、`0x2c43d78` 在入座后 11.2 秒依次执行（流在 1.17 秒打开），0.07 秒后加入端收到类型 7。`0x26d4ae8` 位于结果回调 `0x26d4aa0` 内，依次检查错误是否为 `gflnet::request::Error::Timeout`、`ErrorLeaveAnyone`（`0x26d4e04`）及 `gflnet::npln::NplnResult`，所有错误均经过这里。该步骤仅在会话已建立后启动：若 `[exchange+0x80]` 的站点对象未报告已建立状态，或本站索引为 0xfd，`0x26c564c` 返回 false。唯一的 `Error::Timeout` 来源是观察器 `0x2bdb754`；匹配流程两处 WaitMember 步骤由 `0x2bda8cc` 启用它：25000 毫秒（`0x2bda24c`，请求 `0x2bcd394`，目标 2），以及 `3000 + rand % 1000` 毫秒（`0x2c491b8`、`0x2c4874c`，目标取自匹配记录）。WaitMember 在会话成员数（虚函数 `+0xd8`）达到目标字节 `+0x88`（`0x2c1a8f0..0x2c1a920`）时完成，没有逻辑延长定时器。第二个步骤的目标为记录的 `+0x22` 半字（`0x2c48a28` 的 `ldrh w28`，在 `0x2c48cf4` 存到等待器 `+0x88`）；模拟器游戏机以密码 00000000 主持搜索时读到 2。三个会话驱动虚表（`0x4197120`、`0x4197310`、`0x4197cf0`）中的虚函数均为 `0x2bcbdb4`，返回 `[Session+0xe0]`，即 `Session+0xd0` 处 Pia Session 成员列表的大小（`0x72ab78`）。列表包含会话启动时加入的本站（`0x72ad4c`），以及每次 Session 加入事件的条目：主机接受加入请求（`0x737608`，事件 `0x7378bc`），加入端则从类型 5 更新添加各站点（`0x738bc0`、`0x738f08`）。仅在 LDN 关联或发送 Net 0x11 的站点不计入；离开事件（`0x735cb8`）移除条目。

没有站点的搜索会在该定时器到期后重新创建网络。模拟器游戏机使用密码 00000000 主持搜索时，各网络都按同样方式结束：WaitMember 到期（`0x2bdb7a0`），0.3 秒后在 `0x2c4ee60` 发起离开请求，再过 0.3 秒执行 `Session::LeaveAsync`（`0x72a6dc`），随后销毁 LDN 网络，使用新会话 ID 及字节完全一致的广播数据创建新网络。没有启用断点的 32 个网络中，每隔 2.43 至 4.33 秒创建一个网络（中位数 3.23 秒），两个网络之间扫描不到网络的时间为 0.25 至 0.5 秒（21 个会话 ID 均不同）。加入站点因此只有当前网络 `3000 + rand % 1000` 毫秒窗口的剩余时间可成为成员。

模拟器游戏机主持搜索、`bin/pla_join.py` 通过 IP 加入时，主机 WaitMember 在入座前 1.4 秒比较成员数 1 和目标 2（`0x2c1a904`，w0 1、w8 2）；入座后 0.09 秒，加入端变量 ID 随加入回复进入成员列表（`0x7292f4`）；1.19 秒后启动 10.0 秒秒表（`0x26c539c`）。之后两轮数据交换完成，在保持席位的 29 秒内没有迁移 0x11。已入座的主机席位因此由 10.0 秒期限结束：秒表在匹配返回后启动，失败会带主机迁移离开会话。完成回调为 `[request+0x90] -> 0x26d69e8 -> 0x26d6a88`。

加入网状网络后，DataExchangeStart 在 Stream Broadcast Reliable（0x81）的端口 0、1 等待两轮数据交换：每个站点用类型 0x0f 消息打开流，在标志 0xa0 下用 44 字节 `0000002c ffff` 消息确认（[加入游戏主机的网络](#joining-a-consoles-network)），并发送一条 74 字节的类型 0x1f 内容记录，其中携带以 `484b6264` 开头的 64 字节载荷。收到对方第二轮记录后步骤完成（实测间隔 17 毫秒），并将 `OnSuccess` 入队（`0x26d5f64`）；主机端若只确认流就会超时。加入的游戏主机会主动打开流，在主机端记录之后发送自己的内容记录（实测晚 86 毫秒）；主持会话的游戏主机则在加入方打开流时先发自己的记录。交换盒子数据（399 字节类型 7 记录）稍后通过 0x7c 传输。

消息在载荷末尾结束；此版本范围不将消息对齐到四字节（5.27 至 5.45 会对齐），只有数据包补齐（[读写数据包](#reading-and-writing-a-packet)）。主机端回应游戏主机打开流时，在一个数据包中合并两条消息：先是端口 0 的记录，再是端口 1 上自身的流打开消息；后者使用标明大小、协议、端口的头部，并继承消息标志。`bin/pla_host.py` 每次加入只发送该组合包一次；无线传输丢失时，游戏主机会在 10.2 秒超时后显示错误 7。

| 协议 | 头部目标 | 尾部 |
|---|---|---|
| Session（会话）、Clone Clock（克隆时钟）、Reliable（可靠传输） | 对方的可变 ID | 无 |
| RTT（往返时延）、Stream Broadcast Reliable（可靠流广播） | 网状网络目标 0x0001 | 接收方的可变 ID，明文 |

头部目标为伙伴变量 ID 的 0x81 消息不会到达游戏。同一存档双方的 64 字节内容负载除发送方站点索引外完全相同。它是 139 字节记录的 zlib 压缩（4 KB 窗口，级别 5；`pokeldn.pla.data_exchange`）：Pia StreamData 头部下的一个数据块（[协议 0x81](pia.md#protocol-0x81-the-stream-broadcast-reliable-transfer-pia-6)），包含存档的 0x80 字节 MyStatus 块（PKHeX `MyStatus8a`）：

    +0x00  1   StreamData kind, 1: the first chunk
    +0x01  1   transfer id, 0
    +0x02  1   percent of the block delivered, 0x64
    +0x03  4   zero
    +0x07  4   big-endian u32 0x80, the bytes that follow
    +0x0b  128 the MyStatus block: trainer id pair +0x1b, version +0x1f (47), gender +0x20,
               language +0x22, UTF-16LE name +0x2b

Pia 写入头部（序列化器 `0x7533e8`，分块循环 `0x7529f8`）。`0x26c564c` 从步骤自身副本整体复制后，游戏在 `0x26bfd28` 调用 `0x753554(stream, exchange + 0xa0, 0x80, 0)` 仅传入数据块（`0x1024038` 为数据块序列化器，块位于对象 `+0x68`）。按接收玩家生成的礼物读取此训练家（`data_exchange.read_trainer`、[按接收玩家生成](gift_simulated.md#made-for-the-receiving-player)）。

参考记录中，另外两个非零字段为 32 位。实机存档记录还在记录 +0x60 包含 22 字符账户标识，在 +0x7d 包含值 1：

- +0x3c（记录 +0x47）是开场 4×2 `grid_player` 中选择的外观，值为列号加 4 倍行号（`0x1348df8`，设置器 `0x1023f94`）。同一次选择设置性别，列 2、3 为女（`column > 1`、`0x134d728`），同时设置肤色。八个值为 `p1skin001`（0）、`p1skin004`（1）、`p2skin001`（2）、`p2skin004`（3）、`p1skin002`（4）、`p1skin003`（5）、`p2skin002`（6）、`p2skin003`（7）；`p1` 为男，`p2` 为女。游戏通过 `0x1023f9c` 读取，用于玩家照片 `photo_player_0N` 和结束字幕 `credit_end_0N`。参考值 5 为第三种肤色的男玩家；外观列与 +0x15（记录 +0x20）性别冲突时，不是游戏存档会生成的组合。`bin/pla_host.py` 和 `bin/pla_join.py` 按 `--gender`（应用取自设置）发送对应性别、相同肤色的外观：男为 5，女为 7（`data_exchange.build_record`）。
- +0x50（记录 +0x5b，PKHeX 的 `Unk_0x50`）为 1，由初始化器 `0x1023144` 在 `0x10230e4` 内写入，后者也写入版本 47。该类没有此字段的访问器。

Game Freak 从偏移基值 `0xcbf29ce484222645` 使用 FNV-1a 64 哈希这些名称。肤色对应 `0x1348cbc` 判断的八个哈希，`grid_player` 对应 `0x13497fc` 打开的布局。

<a id="the-games-reliable-channel"></a>
## 游戏可靠渠道

数据交换后，交换流到达 `0x13d5cac`，在游戏的网络对象上测试 `[net+0xb8] > 1`。对象根据游戏在 0x7c 上读取的内容前进：状态 0 到 1
`0x26d9170`，`[net+0x78]` 上的 1 到 2，由选择器 1 上的接收处理程序 `0x26da310` 设置（跳转表索引 1，`0x26da3a4`）。

调度程序 `0x2ca4a88` 将消息的八字节密钥与每个通道的 `+0x6c` 进行匹配，并移交正文。存在两个通道，均通过 `0x2bcb8c8` 注册：交换盒 (`0x26d8c2c`) 的密钥 `00 00 00 00 00 00
00 00`，阶段协议 (`0x26d7aa0`) 的 `01 00 00 00 00 00 00 00`。

端口 0 和端口 1 是两个 Reliable 实例，在 `0x2bba180` 的协议序列中注册为
`0x7c000000`和`0x7c000001`（流广播：`0x80000000`、`0x80000001`）。句柄位于按端口索引的 `0x4308a80` 的表中（`0x4308a84` 是 0x7c 端口 1）。 `0x2ca4a88`读取0x68、0x7c和0x80的端口0； 0x7c的端口1是通过下表的通道表来读取的。

两个端口均以 `reliable5` 流打开（无目标位图、对等方的变量 id、序列 1、消息开始、消息结束和初始化标志）；每个站通过一个条目确认其对等方的消息，并在同一端口上发送回相同的消息：

    port 0    key eight zero bytes      body 0100        the host opens it
    port 1    b9 01 01 b9 02 b9 02 00 00 01              the joiner announces the zero key open

<a id="acknowledgement"></a>
### 致谢

`ReliableSlidingWindow`（虚函数表`0xc5b4d98`) 在 vf12 中构建其确认`0x74ee1c`: 接收窗口的`+0x50`作为 id，每个条目在 16 字节掩码中保留一位（`0x74ef18..0x74efb8`），掩码为空，同时`[window+0x54]`已设置。 vf13`0x74efbc`应用一：它解析 AckMessage (`0x742da0`），删除它，除非发票是`2 + 21 * count`字节并且条目的流字节等于窗口的`+0x36`，并调用`0x74f0ec(window, station, ack_id, mask)`在`0x74f09c`。发送条目是0x5d0字节，序列位于`+0x24`，每站待定位图位于`+0x2c`:

|进入顺序|确认站的待处理位|
|---|---|
|以下 `ack_id` |已清除 (`0x74f274`) |
|等于 `ack_id` |保留 |
|以上 `ack_id` |当掩码位 `seq - ack_id - 1` 置位时清零，偏移量高达 0x7f (`0x74f280..0x74f2a8`) |

| `ack_id` |效果|
|---|---|
| 0 |什么都没有(`0x74f0fc`) |
|窗座下方|设置 `[window+0x4b8]`，返回 (`0x74f17c`，`0x74f2d0`) |
| `base + count`（计数`[window+0x32]`），已过去最后发送|释放一切|
|超越`base + count` |传递给 `[vt+0x30]` 和 `0x20000000` (`0x74f18c..0x74f1c0`)、vf6 `0x74f2e8`、两个窗口类中的裸 `ret`：忽略 |
| `0xffff` |适用于整个窗口(`0x74f104..0x74f11c`) |

比较是两个 16 位 id 的 32 位差异：在一个流上的 65536 个消息之后，超过窗口的 id 如下所示。

id 是累积的：确认 n+2 会释放 n，无论它是否到达。游戏机确认过去的连续运行，并在掩码中保存条目：四个小端字（`0x742f00` 处的 memcpy，由 `0x74f2a0` 读取每个字），位 `seq - ack_id - 1` 是 128 位小端整数（`pokeldn.ldn.reliable5.build_mask`）的位 n。实机在数十毫秒内确认主机 0x7c 数据（测量为 17 至 67 毫秒）。

接收器在读取标志之前，根据每条消息的最低挂起字段（包括确认）移动其窗口基数（`0x74c250`将其存储在`[x0+0x20]`；基数`+0x18`将空槽移动到第一个占用的槽，`0x74c2f0..0x74c2f8`；标志调度`0x74c3ac`）；较低的值不会移动 (`0x74c25c`)。通过未确认的消息声明的最低待处理消息使其重新发送低于基准并被丢弃。实机的确认声明小于其 id（ack 8，最低待处理 6）。

`bin/pla_host.py` 和 `pokeldn.pla.joiner` 使用 `pokeldn.ldn.reliable5` (`SendWindow`,
`ReceiveWindow`): 保留每条 0x7c 消息直到被确认，0.4 秒后在相同的序列 ID 和新的随机数下重新发送，最多将其自己的最低未确认序列声明为最低待处理序列（主机游戏机的端口 0 编号在捕获中比加入方的编号领先一位，并声明更多的基数越过加入方的未发送序列）阶段 6)，用掩码确认已通过连续运行，并按顺序交付一次。方加入的 0x81 消息每 1 秒重新发送一次。游戏机在端口上的第一个 0x7c 消息携带序列 1（66 个记录端口中的 66 个）。

游戏机通过 `0x74c9c8` 重新发送 0x7c 和 0x81 数据（刻度：0x81 `0x7419ec`、0x7c）
`0x74a27c`/`0x74a2f8`)：超过基址的每个条目最多 127 个，具有非零挂起位图 `+0x2c` 和已通过的截止日期（`0x74cd10..0x74cd80`；0x81 通过 `0x742194`，仅到挂起站），则截止日期 =现在 + 33 ms + 1.4 x 最大往返（`0x74d06c`，浮点数 `0x3fb33333`；33 ms at
`0x74a784`)，对计数 `+0x14` 没有重试限制。待处理位仅在窗口内确认 (`0x74f1f4..0x74f204`) 或站离开（事件 1、`0x7411cc` 至 `0x74b528`）时清除；每个截止日期加入零的电台（`0x74b358`）。游戏机永远重新发送给仅通过窗口后的 ID 进行应答的对等点。

<a id="the-channel-table-on-port-1"></a>
## 端口1上的通道表

0x7c 的端口 1 携带通道表：每个站宣布其打开了哪些处理程序密钥，并且只有在其对等方宣布该密钥打开后，站才发送密钥。

调度程序的初始化`0x2ca36f0`构建一个0x298字节对象（vtable `0x41997d8`），端口字节`+0x70` = 1，保存在调度程序`+0x20148`中。轮询 `0x2ca82d0` 的每一帧从 0x7c 端口 1 接收到 `0x2ca9800` 并运行发送方 `0x2ca83dc`。两个 0x18 字节条目表，每个表都有一个位于 `+0x00` 的八字节密钥和位于 `+0x08` 的站位掩码：

|表|持有|
|---|---|
| `+0xa0` |站自己的频道，在频道存在时设置条目 `+0x10` 处的字节以及已告知的站命名位掩码 |
| `+0xd8` |已宣布的对等方频道，位掩码命名宣布密钥开放的电台 |

发送方在每次轮询中首先运行（`0x2ca8310`），同时设置脏标志`[obj+0x90]`（`0x2ca83fc`），每个站位遍历自己的表：宣布已清除位的现有通道打开并设置位；已销毁且已设置位 (`0x2ca86c4`) 的已被宣布关闭且该位被清除。通道的析构函数使用其密钥（`0x2ca3168..0x2ca3178`；表槽 13 `0x2caa0d4` 是同一主体）调用接口槽 1 `0x2caa12c`，清除 `+0x10` 并设置脏标志。

接收方 `0x2ca9800` 从 `0x2ca83a8` 处的轮询中运行一次，每个待处理的端口 1 消息 (`0x2ca8398..0x2ca83d4`)，通过会话的 `[vt+0x38]` (`0x2ca9854`) 解析发送方的站索引，丢弃 0xfd 并在 2 个或更多 (`0x2ca9df0`) 上中止。每个键：

|同行表|打开|关闭 |
|---|---|---|
| 持有该键 | 将站点对应位按位或入掩码（`0x2ca9a6c`）；重复打开不会改变任何内容 | 通过按位与清除该位（`0x2ca9ae4`）；若两个站点的位均已清除，则下移尾部并执行 `[obj+0xe0] -= 0x18`（`0x2ca9b14`），删除该条目 |
|缺少钥匙 |附有电台位的条目 |附加零掩码的条目 |

没有手臂调用游戏或在对等表之外写入。收藏家`0x2ca8f58`（每次投票，
`0x2ca8318`）擦除零掩码条目（`0x2ca9060..0x2ca90c8`）并在`[obj+0x98]`中没有设置位时清空表；出站路径`0x2ca90e0`（来自`0x2ca4a48`）清除`[obj+0x98]`和每个掩码中的站位。没有其他任何东西可以清除对等条目。

创建频道（`0x2bcb8c8` -> `0x2ca5264`-> 构造函数`0x2ca3024`，每个下一个的唯一调用者）存储表的接口（`[dispatcher+0x20148]` + 0x68,虚函数表`0x41998c8`）在频道的`+0xb8` (`0x2ca30d0`，建于`0x2ca5acc`) 位于弱引用后面`+0xa8`（使用计数`+0xc`每次调用前测试），然后调用接口槽0`0x2caa0cc` (`sub x0,x0,#0x68; b
0x2ca9dfc`，表槽 12) 及其钥匙：`+0x10`已设置清除（`0x2ca9e78`), 设置返回 (`0x2ca9e74`)，缺失的内容附加为`{key, 0, 1}` (`0x2ca9e90..0x2ca9ec0`）；第一个和第三个设置脏标志（`0x2caa034`). (`stp xzr,xzr,[x23,#0xb8]`在`0x2ca3c6c`将表自己的归零`+0xb8`.) 对等表查询：

|功能|槽 |答案 |
|---|---|---|
| `0x2ca9218` |接口2 |自己的表持有密钥 K |
| `0x2ca92e0` |接口3 |插槽10的测试，由句柄给出的站并通过`[vt+0x38]`解决|
| `0x2ca93d4` |接口4 |插槽 10 的测试，按站索引 |
| `0x2ca958c` |接口5| `0x2ca9448` 关于表对象|
| `0x2ca9360` |表 vtable `0x41997d8` 插槽 10 |对等表保存 K 和站位 i |
| `0x2ca9448` |桌子插槽 11 |宣布 K 的电台除了这一个以外的所有电台 |

每个通道发送方通过调用接口槽 3`+0xb8`其钥匙位于`+0x6c`并且仅在 yes 上发送：阶段发送者通过`0x2ca34e0` (`0x26d7e00`在`0x26d7d8c`, `0x26d7ef8`在`0x26d7e84`），交换框发送者内嵌在`0x26d9200`, `0x26d92f0`, `0x26d950c`, `0x26d9688`, `0x26d980c`（选择器 5）和`0x26d9a1c`。对等表也控制端口 0 发送，每个端口都有自己的密钥；这是交换屏幕显示的等待时间，而主机在端口 1 上处于静音状态。接口插槽 2、4 和 5 没有呼叫站点通过`+0xb8`.

表指针位于 `[dispatcher+0x20148]`（最后一个字段；分配 `0x20150`，
`0x2bcac00`），仅在调度程序中使用：init `0x2ca3d24`，析构函数`0x2ca3f88`（在`0x2ca3f48`中），station join `0x2ca4774`（`0x2ca4574`来自`0x2bcb2b8`：位） ORed 为 `[+0x98]`，脏集），站离开 `0x2ca4a38`（`0x2ca90e0`），帧的轮询 `0x2ca5020`，通道创建 `0x2ca5284`（表槽 8 `0x2ca91cc`）。另一个副本是每个通道的 `+0xb8`（接口插槽 0、1、3）。未找到其他对等表读取器：vtable `0x41997d8` 仅由 `0x2ca3c18` 和 `0x2ca7f2c` 引用，
`0x41998c8` 没什么； `0x2ca3000..0x2cab000` 中通过 `+0x48/+0x50/+0x58` 的调用仅
`0x2ca92c0`、`0x2ca9340`（插槽 10）、`0x2ca9490`（会话）；外线呼叫 `0x2ca6000..0x2cab000` 只能到达 `0x2caa960..0x2caafec`；插槽 9 `0x2ca9264` 无呼叫者。

消息是游戏的标记序列：0x80 以下的无符号整数是其自己的字节；标签
0x80、0x81、0x82、0x83 前缀为小端 1、2、4、8 字节值（`0x2661ec4`、`0x26619cc`、
`0x2661f78` 写入 u32、u64、u16)。尺寸表 `0x397dfcc` 给 0x84 到 0x87 相同的宽度，
0x88 四个字节，0x89 八个字节，0xb5 到 0xbf 一个。 0xb9 打开一个元组，后面是字段计数。

    b9 01              a tuple of one field, the list
    NN                 the number of entries
    per entry:
      b9 02            a tuple of two fields, the key and its state
      b9 02 LO HI      the key as two u32, low word first
      01 | 00          1 open, 0 closed
 游戏机在交换期间发送三个：

|留言 |意义|当 |
|---|---|---|
| `b9 01 01 b9 02 b9 02 00 00 01` |交换箱钥匙打开|端口 1 打开，到达交换步骤 |
| `b9 01 01 b9 02 b9 02 01 00 01` |相位钥匙打开|确认后，`0x26d7aa0`创建相位通道时|
| `b9 01 01 b9 02 b9 02 01 00 00` |相位键已关闭|一旦交换被写下|

`pokeldn.ldn.channel_table` 构建并解析这些。主机用自己的每个键应答一次打开，并留下一个未应答的关闭：发回的关闭会删除游戏机的阶段密钥的对等条目（在交换中无害，因为没有任何东西轮询对等表），并且常设条目服务于下一个交换（[一个会话中的第二个交换](#a-second-trade-in-one-session)）。

<a id="the-trade-box"></a>
## 交换盒

当两个通道都打开时，游戏的消息会在零键后面的端口 0 上交叉。接收处理程序
`0x26da310` 读取选择器和计数器，切换 `0x397e388` 处的字节表，并丢弃任何高于 7 的值。

    1   ready                0x26da3a4   sets [net+0x78], what step 0x20 waits on
    2   showing a Pokemon    0x26da3f0   stored at [net+0x98] by 0x26da1d8, nothing else
    3   showing no record    0x26da430   -> 0x26d93c8
    4   offering a Pokemon   0x26da3b0   stored at [net+0xb0] by 0x26da23c, phase 0xbc := 3
    5   confirmed            0x26da43c   counter check, -> 0x26da2c0
    6   withdrawn            0x26da458   state 4|5 := 3, phase 0xbc := 2, counters moved
    7                        0x26da49c   counter check, phase 0xbc := 5
 处理程序将中止，除非其第四个参数等于合作伙伴 `[net+0x88]`。 port-0开放体
`01 00` 是就绪的（选择器 1，计数器 0），每个会话欠一次。

`0x26d9458`（`0x10fb198`中仅调用者`0x10fb200`，其本身仅在`0x110a010`调用）当其记录为空（`0x26d94a0`）或其种类为0（`0x2b5d3a4` ->
`0x2b6849c` 在 `[pk+0x98]` 上，块 `0x3984e57` 的第一个半字放在前面），否则选择器 2 具有来自 `0x2b65514` (`0x26d9554..0x26d9570`) 的 0x178 字节体。记录是
`0x11207f8(ui, box, slot)` (`0x1109fa0..0x1109fac`)，复制到 `[ui+0x1660]` 的插槽
`0x111da04`（`0x11208e4..0x1120910`、`0x111fc18..0x111fc4c`）：空槽上的光标发送
`03 00`。接收 3，`0x26d93c8` 将 `[net+0x98]` 替换为新的 0xb8 字节 `0x151dc70` 对象，刻度 `0x26d9094` 永远不会读取该对象。

选择器 6 收回要约（状态 3：自己的选择器 4 已发送，`0x26d95d4` 需要 2，`0x26d9718` 写入 3）或确认（状态 4：自己的选择器 5，`0x26d9788` 需要 3，`0x26d9838` 写入 4）。其发送者`0x26d9898`在状态2和5中拒绝（`0x26d98ac`：`cmp w8,#2; ccmp w8,#5,#4,ne`），发送计数器`[net+0xf8] + 1`（`0x26d9918`），然后清除`[net+0xc0]`，设置状态2 (`0x26d9a54`)，加薪
`[net+0xf8]` 和 `[net+0xfa]` 并将相位 4 或 5 返回到 3。接收臂 `0x26da458` 将计数器存储到 `[net+0xfa]`，升高 `[net+0xf8]`，清除 `[net+0xc0]`，设置相位 2，将状态设置为4 或 5 返回 3，并且不发送任何内容：回显的 6 取消确认游戏机。

选择器 2 和 4 带有相同的主体：当电台进入盒子时为 2，当玩家提供时为 4。只有 4 个移动阶段。主机通过显示回答要约，使游戏机留下一个空的伙伴六边形，并且没有错误； `pokeldn/pla/trade_box.py` 镜像选择器。

主体由`0x26dac6c`（选择器）、`0x26662fc`（计数器）和`0x26dacbc`（记录）读取； 0xbc介绍`0x26da3b0`手工测试的记录。

    0x00  1   the selector
    0x01  1   the counter, 0 on both record-carrying selectors
    0x02  1   0xbc
    0x03  1   0x81
    0x04  2   the record's length, 0x178
    0x06  376 the record
 9 字节标头下的 390 字节的适配器，无目标位图，标志 0x07（应用程序数据、消息开始、消息结束；无初始化位、无 zlib 位），位于序列 2 处。

该消息仅取决于保存（在主机和会话密钥之间相同）：捕获重播。

该记录是 Gen-8 实体（`pokeldn.gen8` 标头、LCG、块排列和 16 位校验和），具有 0x58 字节块：0x168 存储，0x178 在队列中。 `gen8.BLOCK_ORDER[(ec >> 13) & 31]` 在解密时按原样应用，在加密时反转。校验和无法区分两者；名字可以：直接读，昵称在0x60（第二块），训练家名字在
0x110（第四）。倒读，两者都提前一个街区落地。 0x0c的训练家ID和训练家姓名是数据交换携带的玩家id和姓名。

<a id="confirming-the-trade"></a>
## 确认交易

交换它在零键上发送选择器 5 和计数器 `[net+0xf8]`。发送方 `0x26d9770` 需要 `[net+0xb8] == 3`（自己发送的提议）并将其设置为 4。消费者 `0x26da2c0` 设置相位
`[net+0xbc]` 为 4，当 `[net+0xb8]` 已经为 4 时，清除 `[net+0xc8]` 并分配到其中：第二个确认站继续。选择器 5 和 7 将计数器降到 `[net+0xfa]` 以下（`0x26da440`，
`0x26da4a0`）。

确认后，游戏机宣布阶段密钥在端口 1 上打开（无初始化标志），并且在主机也宣布它之前不发送任何内容；否则交换屏幕将在第 5 阶段等待。

<a id="the-trade-objects-own-state-machine"></a>
## 交换对象自己的状态机

`[net+0xb8]`为状态步骤0x20测试；勾号 `0x26d9094` 移动它：

    0     if [net+0x90] is set, 0x26d9170 -> state 1
    1     once [net+0x78] is set, one 64-bit store of 0x200000002 puts the state at 2 and the
          phase [net+0xbc] at 2 in the same instruction
    3, 4  while [net+0xc0] is set: read the stopwatch at [net+0xc8], and once [net+0xd0] is past
          1.5 seconds and the phase is 4 or 5, 0x26d9254 sends selector 7 and the state becomes 5
    5     no case. The object is finished
 状态 5（已提供，均已确认）使保存保持不变；下面的工作进行交换。

<a id="the-job-that-carries-the-trade-out"></a>
## 执行交换的工作

该场景在 6..10 中轮询 `0x26d9ea0`：`[net+0xd8]` 非空，并且该作业的状态为 `+0x10`。
`0x26d9a90` 从 `[net+0xa0]`、`[net+0xa2]`、`[net+0xa4]` 建立子状态 7 臂中的工作，
`[net+0xa8]`和提供的记录`[net+0xb0]`：0x140字节，在`0x26dc08c`构造，vtable
`0x416c8f8`，从 `0x26dc564` 开始，有八个回调，由 `0x26dc2c8` 状态从 0 到 1。它的更新
`0x26dc71c`通过`0x397e390`接通`state - 1`（基础`0x26dc758`；0xf及以上返回）。执行器`[job+0x130]`由`0x26db724` -> `0x26dd39c`（vtable `0x416c918`，id `[+0x70] = 3`）构建。

|状态|手臂|确实 |
|---|---|---|
| 1 | `0x26dc774` |执行者 vf `+0x40` `0x26dd488`（针对八个 ID `0x1e3..0x1ed` 的两个记录的种类），其结果为 `[job+0x1d]`，然后是 `0x26d7d8c(obj, 3)` (`0x26dc97c`)；仅当发送返回 true 时才处于状态 2 |
| 2 | `0x26dc798` | `0x26d7e5c(obj, 3)`: 主机的 `02 03` |
| 3 | `0x26dc7b4` |执行器 vf `+0x50` `0x26dd910` 直到返回 false：交换限制设置并保存 ([交换限制](#the-trade-restriction)) |
| 4 | `0x26dc7e4` |发送阶段 6 |
| 5 | `0x26dc800` |等待`02 06` |
| 6 | `0x26dc81c` | `0x26db9f8`：执行者阶段 `[+0x68] = 1`，然后 vf `+0x58`：应用交换，清除限制 |
| 7 | `0x26dc82c` |等待执行器阶段 3 (`0x26dba0c`)，然后发送 `0x0b`（状态 8），或状态 9 并清除 `[job+0x1d]` |
| 9 | `0x26dc85c` |向下计数 `[job+0x20]`，然后发送 `0x0b` |
| 8, 10 | `0x26dc758` |等待`02 0b` |
| 11, 12 | `0x26dc888`, `0x26dc898` | 执行器阶段4，然后等待阶段5并发送`0x0e`；第 4 阶段运行 `0x1048690` -> `0x298f2f4`，调用 `nn::fs::Commit` (`0x298f318`) |
| 13 | `0x26dc8c0` |等待`02 0e` |
| 14 | `0x26dc8e0` | 成功函子 `[job+0x30]`，或用 `[job+0x18]` 设置失败函子 `[job+0xb0]`；状态 0xf |

状态 9 的计数在作业初始化 `0x26dc2c8` 中设置一次：xoroshiro128+ 绘制 0 到 300（`0x26dc400`，全局状态 `[[0x4279680]+0xd8]`）加上 2（`0x26dc340`），2 到 302 帧。成功调用者`0x26db864`写入交换对象`[+0xb8] = 6`；失败调用者 `0x26db8ec` 写入 7。

状态2调用`0x26d7e5c([job+0x28], 3)`，它要求`[obj+0x70]`非空并且`[obj+0x90]`设置，并返回`[obj+0x92] ==
n`。发送方 `0x26d7e84` 仅在成功发送后才写入两者：它测试 `0x2ca34e0([obj+0x70],
[obj+0x88])`，通过 `[obj+0x70]` 的 vtable +0x40 发送到 `[obj+0x88]`，在 `+0x92` 记录相位并设置`+0x90`。

失败的门在下一次更新时重试（`bl 0x26d7d8c; tbz w0,#0,0x26dc908`；`0x26dc908` 返回，`[job+0x10]` 不变）：通道表拒绝的发送将作业保持在发送状态（在状态 1 处拒绝 `01 03`，在状态 2 处丢失 `02 03`）。处于状态 1 或 2 的作业本身没有超时：唯一的倒计时是状态 9 的 `[job+0x20]` (`0x26dc85c`)；下没有读取时钟
`0x26d7d8c`、`0x26d7e5c`、`0x26d7f4c`、`0x26dd488` 或 `0x26dc6b0`；执行器tick `0x26dba38`在阶段0不执行任何操作（`0x26dba68..0x26dba80`）；唯一读取的刻度 `0x265d420`（`nn::os::GetSystemTick` 位于 `0x265d440`）来自状态 3。

另一个出口是取消请求 `0x26dc640` (`[job+0x14]`, `[job+0x18]` := 1)，仅通过场景监视器 (`0x1109ef4`) 中的 `0x26d9e90` 到达并离开模式 9 (`0x110b7ac`，秒表在`[scene+0x278]`、`0x110b794..0x110b79c`）。场景位于作业生命周期的模式 5、步骤 9（从 `0x110ad34` 开始，步骤 9 设置为 `0x110ad3c`）；步骤9臂`0x110abb8`等待
`0x26d9354`（`[+0xb8]`到`0x397e380`，6到5，7到0）读取5.预切换调用
`0x26bc6c4`、`0x10fb234`（`0x26d93b4`）和`0x1126408`没有交给场景，无法结束等待。监视器 `0x1109d00` 在模式切换 (`0x1109a98`) 之前运行每次更新，仅模式 5，通过 `0x3979c68`（基础 `0x1109d20`）分步：

|步骤|手臂|
|---|---|
| 0 到 5, 8 | `0x1109d4c`：错误或伙伴消失了|
| 6, 7 | `0x1109e48` |
| 9 | `0x1109e84` |
| 10 至 12 |什么都没有|
| 13 | `0x1109ec0` |

在第 9 步，监视器读取 `0x26d9ea0` (`0x26dc65c`)。在 6 到 10 的作业中，错误来自
`0x110977c(1)`给出模式8；否则，错误（`0x1109ee4`）会取消作业（`0x1109ef4`）并给出模式7（`0x1109ba8`），一条消息然后离开。 `0x110977c` 报错没有会话或者没有
`0x110ccf0`（`0x11097a4`、`0x1109810`）、非零 `0x2bbb590`，或（参数位 0）根据 `0x110994c` 消失的伙伴（会话 `[vt+0xb0]` 假或站计数） `+0x28` 2以下，
`0x11099fc..0x1109a04`）。挂起的作业会等待，直到会话失败或主机离开 ([Leaving](#leaving))。

游戏机在等待时没有任何需要重新发送的内容：主机必须重新发送在空中丢失的 11 个答案中的任何一个（端口 0 打开、两个通道打开、显示、提议、选择器 5 和 7、四个阶段）。

在 `0x26dc9a4` 允许的状态下进行取消，`0x3ff7 >> state & 1`：0 到 2 和 4 到 13。取消处理器 `0x26dc6b0`（来自 `0x26dc670` 的每一帧）通过设置 `[executor+0x6c] = 1`
`0x26dbe98` 和状态 0xf 的作业，请求 2。然后，执行器在 `[+0x68]` 低于 2 的阶段，调用 vf `+0x48` `0x26dd5f8` 并设置 `[+0x6c] = 3` （`0x26dbcf8`）；在第 2 至 4 阶段，它首先完成保存 (`0x26dbd44..0x26dbd90`)。作业进入状态 0xe，请求 3，失败回调。室颤
`+0x48` 仅在设置 `[executor+0xb0]` 时写入（`0x26dd610`、`0x26dd614 cbz`），仅在以下位置存储 1
vf `+0x58` 中的 `0x26ddc6c`，状态 6。在状态 1 或 2 取消的作业不写入任何内容，也不保存任何内容（执行器 init `0x26dd43c`：阶段 0，`+0xb0` 0，保存请求 `+0xb8` 0）；在此类取消之后，模拟保存是字节相同的。

<a id="the-trade-restriction"></a>
## 交换限制

交换限制是保存块中的 u64 分钟数`0x96993D83`， 场地`+0x70`的物体在`[game manager+0x2b8]`（经理通过`[0x4279560]`, 访问器`0x1048f94`;虚拟表`0x40f2048`, 构造函数`0x102500c`）。其方法：

    0x102518c  clear
    0x1025194  set
    0x102519c  decrement, stopping at 0
    0x10251b0  read
    0x10251b8  non-zero
 注册`0x1024d5c`（槽位`0x40f2098`）绑定三个字段来保存块，通过
`0xff0ee8` 通过 u32 键对 0x30 字节条目进行二分搜索（`0xff0f3c..0xff0f70`）：

|领域 |块|类型 |
|---|---|---|
| `+0x68` | `0xAFA034A5`（密钥位于 `0x3978f78`）|布尔值 (`0xfddf30`) |
| `+0x70` | `0x96993D83`（密钥位于 `0x3978f7c`）| u64 (`0xff0ee8`) |
| `+0x78` | `0x24E0D195`（构建于 `0x1024f30`）、0x2F2 字节 | `0x1024ee4` |

PKHeX 的 `BlankBlocks8a.cs` 与这些大小一致。存档中 `0x96993D83` 为类型 11、值 0，`0xAFA034A5` 为 false 布尔值，`0x24E0D195` 为零标志字节及最近交换收到的记录。

`+0x78` 字节标记已收到但尚未放置的记录。`0x10251c8` 设置它（`0x102520c`），将记录复制到 `+0x79`；若提供交换后形态，则写到 `+0x1f1`（标志 `+0x369`）。唯一调用方是任务状态 6 的执行器 vf `+0x58`（`0x26ddc64`）；`0x2b5be48` 对两者返回相同种类时不传入交换后形态。`0x26dcc74` 读取该字节（`0x26dccfc` 处的 `0x102527c`）；已设置时放置记录（`0x10325a0`）、登记图鉴（`0x10342b0`）、清除字节（`0x26dcdc8` 处的 `0x1025268`），并以请求类型 3 保存。取消仅在 `[executor+0xb0]` 已设置时清除它（`0x26dd70c`）。`0x26dcc74` 在模式 5 步骤 10（`0x110accc`）、模式 9 步骤 0（`0x110bc88`）及盒子代码（`0xc17ce0`、`0xc17e8c`）运行，没有其他位置写此字节。
计数的全部写入方（全文调用索引；没有指针槽保存方法）：

|网站 |来电者 |价值|当 |
|---|---|---|---|
| `0x26dd9a0` |执行器 vf `+0x50` `0x26dd910`，作业状态 3 | 10 | 10在伙伴的 `02 03` 之后，在任一记录移动之前 |
| `0x26ddaf0` |执行器 vf `+0x58` `0x26ddaa0`，作业状态 6 | 0 |交换被应用|
| `0x26dd704` |执行人vf `+0x48` `0x26dd5f8`，取消| 10 | 10仅当 `[executor+0xb0]` 设置时，`0x26ddc6c` 在状态 6 时执行此操作 |
| `0x26bd5d0` |股票代码 `0x26bd434` |负 1 |每 60 秒 |

设置10后，vf `+0x50`收到来自`0x12aff48`的保存请求，武装它
`0x265d420(request, [executor+8], 3)` (`0x26dd9e8`)，并保持状态3直到`0x265d460`报告完成；运行保存数据状态机 `0x10457e4`（`0x265d668`；步骤 `0x1048354`，
`0x1048558`、`0x10485c0`、`0x1048628`、`0x1048690`、`0x10486f8`，其中一个通过 `nn::fs::Commit` 到达
`0x298f2f4`）。这些是交换代码中唯一的保存请求。在作业状态 3 之前停止的交换不受限制；在状态 6 在保存中留下 10 后，一个在状态 3 和保存之间停止。

倒计时由 `0x277c530` 在 `0x42eced0` 的系统列表中注册（调用 `0x277cc0c`，
`0x277fbb0`； `0x2789df4` 构建它，构造函数 `0x26bd300`，vtable `0x416c2f0`，更新 `0x26bd430` -> `0x26bd434`）。其状态为 `+0x58`：

    0  count non-zero -> 2                                          0x26bd4bc
    2  count zero -> 0; else snapshot the count to +0x70 and start a stopwatch at +0x60
       (nn::os::GetSystemTick, ConvertToTimeSpan, 0x26bd534..0x26bd544) -> 1
    1  count changed -> 2; elapsed / 1e9 >= 60.0 (0x26bd5b4) -> decrement (0x26bd5d0) -> 2
 10 是游戏运行的十分钟，在操作系统上勾选：时钟设置不起作用，游戏关闭的时间不计算在内。行情在球场上运行：限制设置后，比赛时间为 10 分钟（在球场上留下的实机上测量为 667 秒）。

`0x13d67b0` 是非零方法的唯一调用者 (`0x13d67e8..0x13d67f0`)。在Link交换的合作伙伴选择菜单中，`0x13d55fc`和`0x13d56ac`（在`0x13d55dc`内部，由`0x13d53c0`调用，断言
`[x0+0xa4] == 3`;和 `0x13d5648`（由 `0x13d53dc`、`0x13d5808` 调用）在计数非零时返回 `0x500000001`，否则返回 `0x300000001`，当 `0x13d65c0` 为假时返回 `0x400000001`。菜单更新
`0x13d5344` 开启`[obj+0xa0]`（字节表`0x397c105`）；结果 `(n << 32) | 1` 将其移动到状态 n (`0x13d5404`)。决定回调 `0x13ddcb4` 为窗格 `button_00` 写入 2，为窗格写入 3
`button_01`（名称的FNV-1a-64，基础`0xcbf29ce484222645`），由状态0路由到`0x13d55dc`和`0x13d5648`（`0x13d5590..0x13d55a0`）；根据窗格名称，`button_00` 可能是“附近有人”。每个州的 `common/net` 标签（表 `0x397c158`）通过 `0x13dbe68` 继续到 `pane_T_info_00`：

|结果 |状态|标签|文字|
|---|---|---|---|
| `0x500000001` | 5（`0x13d59a4`），然后回到0 | `matching_win_03` |现在无法链接交换，上次连接已中断；稍等一下（法语：“Votre connexion a été interrompue lors de votre dernier échange...”）|
| `0x300000001` | 3、然后在6中牵线搭桥| `matching_win_06` |中断的交换会暂时阻碍交换的警告 |
| `0x400000001` | 4 | `matching_win_02` |至少需要两个可交易的宝可梦 |

<a id="the-phase-protocol-and-the-message-only-a-host-sends"></a>
## 阶段协议，只有主机发送的消息

该作业在创建作业时注册的密钥 `01 00 00 00 00 00 00 00` 上宣布阶段。通告对象保留三对，每对一个标志和一个半字：

    [obj+0x94] / [obj+0x96]   the phase this station has announced, written by 0x26d7d8c
    [obj+0x98] / [obj+0x9a]   the phase the peer has announced, on receiving selector 1
    [obj+0x90] / [obj+0x92]   written by 0x26d7e84, and on receiving selector 2
 两个发送者仅在他们写入的选择器上有所不同；接收处理程序 `0x26d7f90` 镜像它们：选择器 1 填充对等点对，选择器 2 填充第三个，选择器 0 中止。该消息是选择器和阶段，各一个字节，而阶段位于 0x80 下。 State-2 臂的
`0x26d7e5c(obj, 3)` 等待第三对保持 3。

选择器 2 是要发送的主机。 `0x26d7e84` 仅在 `[obj+0x78]` 之后到达，`0x26d7aa0` 在创建作业时通过将该站与会话的主机站进行比较的谓词写入一次。方加入从不发送选择器 2，因此它的工作仅在主机上留下状态 2。仅镜像选择器 1 的主机使交换屏幕等待，同时显示宝可梦，并且线路上没有任何突出的内容。该设置有五个退出，使 `[obj+0x78]` 为零：空参数、空转换、
`[vtable+0xd8]()` 未返回 2，`+0x28` 处的站计数不是 2，即空站槽。

站点在端口上发出的每条消息（包括镜像）都采用其自身序列的下一个 id。一旦计数出现分歧，重用对等方 ID 的镜像就会发生冲突，并被确认但被丢弃。

<a id="the-completed-trade"></a>
## 已完成的交换

游戏机依次公布3、6、0xb、0xe；主机用选择器 2 和相同的相位回答每个问题，这将继续工作：

一旦第一个 `02 03` 到达（实测为 240 毫秒后）：

    <-  0x7c p0  01 03      ->  01 03   the mirror     ->  02 03   the host's
    <-  0x7c p0  01 06      ->  02 06
    <-  0x7c p0  01 0b      ->  02 0b
    <-  0x7c p0  01 0e      ->  02 0e
 第三对读取 1 和 3。动画结束后，框将主机的玩家命名为原始伙伴。八个保存文件发生变化：两个插槽中的 `main`、`main2`、`backup`，都是 ExtraData 文件。

然后游戏机发送一个新的选择器 2（无论光标在什么位置），主机以显示应答，阶段键关闭 `b9 01 01 b9 02 b9 02 01 00 00`，主机不应答。

<a id="a-second-trade-in-one-session"></a>
## 一次会话中的第二次交换

会话承载任意数量的交易：完成交换后，场景将重置交换对象并返回到会话启动的框。

完成交换后，场景在 `0x110aa04` 处调用 `0x26d8fd0(net)`（仅当 `[net+0xb8]` 为 6 时），并将步骤 `[scene+0xb4]` 设置为 0xc。重置：

    0x26d8fec  [net+0xa0], [net+0xa2] cleared           job inputs
    0x26d8ff4  [net+0xa8], [net+0xb0] released          shown and offered records
    0x26d903c  0x200000002 to [net+0xb8]                state 2, phase 2
    0x26d9044  [net+0xc0] cleared                       stopwatch flag
    0x26d9050  [net+0xd8] released through 0x26dade4    the job
    0x26d9064  32-bit zero to [net+0xf8]                both counters

`[net+0x78]`（同伴已准备好）并且`[net+0x88]`（伙伴）被保留：下一轮从状态 2 开始，没有新的选择器 1。场景的更新`0x1109a68`（指针指向`0x3406990`,
`0x40fc090`) 运行监视器，然后打开模式`[scene+0xb0]`通过`0x3979c5e`（根据`0x1109b60`):

|模式 |处理程序 |它是什么 |
|---|---|---|
| 0 | `0x1109f00` |框：光标，显示，选择交换|
| 1, 2 | `0x1109b6c` |什么都没有|
| 3, 4 | `0x110a65c`，`0x110a694` | |
| 5 | `0x110a7f8` |交换，逐步（半字表 `0x3979c7c`，基 `0x110a858`，步骤 0 到 13）|
| 6 | `0x110b330` |伙伴走了，没有错误：一条消息，然后模式 1 (`0x110b408`) |
| 7 | `0x110b468` |会话错误，作业在步骤 9 取消：一条消息，然后模式 9 (`0x110b508`) |
| 8 | `0x110b54c` |第 9 步出现会话错误，第 6 至 10 步中的作业：一条消息，然后 `0x115e420(..., 1)` (`0x110b60c`) |
| 9 | `0x110b72c` |离开：取消作业（`0x110b7ac`），在操作系统滴答声上等待至少 3 秒，完成 |

完成交换后，在模式 5 中：

    step 11  0x110a928  UI waits (0xc4cc88, 0x1127ab8, 0x110d8b0, 0xc6a788, 0x26bc6a4), 0x26d9eb0,
                        0x10fb2c4, 0x10fb414, 0x10fb164(..., 1) ([+0x161] = 1), 0x10fb178 (0x110a9e8),
                        0x1126408, 0x1126400, 0x26d8fd0 (0x110aa04), step 12
    step 12  0x110aae0  returns while 0x10fb170 ([+0x161]) is set, UI calls, step 13 (0x110abac)
    step 13  0x110ac80  waits for 0xc4cc88 and 0xc6a610, then 0x110acc4 b 0x110b9f0
    0x110b9f0           UI (0x1120ce0, 0x111fb5c or 0x11152b8, 0xc42438, 0xc4ba88, 0xc428b0), then
                        0x110ba44 str xzr,[x19,#0xb0]: mode 0, step 0
 步骤 11 至 13 中没有被叫方到达会话、频道表或发送：场景返回到会话已启动的框。步骤5的手臂`0x110ac9c`将尾部共享到`0x110b9f0`。 `0x10fb178` 清除盒子控制器的有效标志 `+0x164`、`+0x16c`、`+0x174` 和尾部调用 `0x26d93c4`，这用新的 `0x151dc70` 对象替换 `[net+0x98]` 并不发送任何内容。

模式0每帧读取光标（`0xc5294c`盒子、`0xc4bf2c`槽、`0x11207f8`记录）并调用
`0x10fb198` 位于 `0x110a010`，仅当光标元组与`+0x168/+0x170/+0x178`中缓存的元组不同或有效标志被清除（`0x10fb1a8..0x10fb1f0`）时才通过`0x26d9458`发送显示，发送后缓存元组（`0x10fb208..0x10fb220`）；交换后，清除的标志会导致新的选择器 2。光标移动只能通过`0x10fb198`到达网络。提供（菜单结果 0x19、`0x110a098`）通过 `0x26d95ac`（`0x110a24c`）运行 `0x10fb25c`、选择器 4，成功后 `0x110a260 mov w8,#5; b 0x110a148` 在步骤 0 进入模式 5。

每个模式均在步骤 0 处进入（`str x8,[x19,#0xb0]` 位于 `0x1109abc`、`0x1109ac8`、`0x1109bac`、
`0x110a148`、`0x110a314`、`0x110ae14`、`0x110b408`、`0x110b508`、`0x110b9dc`、`0x110ba44`、
`0x110bd98`，`0x110c9f0`； `stp w8,wzr`，`0x11094dc` 处为 7），`0x11094a8` 除外，当设置了盒子控制器的 `+0x160` 时（`0x10fb15c` 位于 `0x110948c`），模式 5 步骤 1。

柜台`[net+0xf8]`仅在那里归零`0x26d8c04`，仅由选择器 6 发送（`0x26d9a60`）或收到（`0x26da468`），并通过序列化`0x26d81fc`每个发件人 (`0x26d91c8`选择器1，`0x26d92b8` 7, `0x26d94d4`2和3，`0x26d9640` 4, `0x26d97d4` 5).

下一个作业由 `0x26d9a90` 从场景步骤 7（`0x110ad34`，当 `0x26d9354` 返回 4 时）构建，并再次使用密钥 1 创建其相位通道（`bl 0x26d7aa0` 在 `0x26dc398`）。它的相位在`0x26dc71c`中是立即数：3在`0x26dc978`，6在`0x26dc7ec`，0xb在`0x26dc848`和`0x26dc874`，
0xe 位于 `0x26dc8ac`。第二次不撤回的交换重复 `05 00`、`07 00`、相位和端口 1 相位密钥逐字节打开；只有序列 ID 不同，因此回答每个不同主体的对等体一旦回答了其中任何一个。

如果主机应答了游戏机关闭阶段键，则第二个`01 03`在门内等待，直到主机再次宣布键打开：作业处于状态1，场景处于步骤9，无超时，无限制。

处于状态 1 或 2 的作业显示 `common/box` `msg_ui_box_p2ptrd_09`，“正在通信。请待命...”（“Communication en cours...Veuillez Patienter。”），由“交换它”回调发出
`0x110c3d8` 通过消息助手（`[scene+0xc0]`，`bl 0x26bcc14` 位于 `0x110c424`，标签哈希在
`0x110c408..0x110c418`)，设置步骤6；助手的关闭 `0x26bcfc0` 仅在以下位置调用
`0x110a84c`、`0x110ac5c`、`0x110ace4`。 `0x1128184(ui, 1)` 打开取消提示（`InputCancel`，
`0x11281bc`），只读步骤 2 和 7（`0x110ac00`、`0x110ad4c`）。

<a id="what-a-trade-rewrites"></a>
## 交换重写

当光标到达时，交易的记录将作为显示返回。接收到的记录与发送的记录在这些字段中不同（对于使用 70 级队伍尾部发送的 50 级记录，需要 23 个字节）：

    0x006  2   the checksum
    0x092  1   the current HP, 235 sent, 192 stored
    0x0b8  26  the handling trainer's name, filled in with the receiver's own
    0x0d3  1   the handling trainer's language
    0x0d4  1   the current handler, set to 1
    0x0d8  1   the handling trainer's friendship
    0x16a  12  the six party stats, recomputed
 其他所有内容均按到达时存储；保持高于该水平的满足水平。所写的亲密度是个人条目中该种类的基础亲密度（耿鬼和烈咬陆鲨为50）。

每个块的开头是 `pokeldn.gen8` 加上每个前一个块的八个字节：昵称 0x60（第 8 代）
0x58），最近持有人名称0xb8（0xa8），训练家名称0x110（0xf8），训练家名称0x168（0x148）。在块内，偏移量跟随块：第一个是 Gen 8，除了移动（0x54 和 PP 0x5c，其中 Gen 8 在第二个块中有 0x72 和 0x7a），第二个 Gen 8 加 8，第三个加 0x10，第四个加 0x18，球移至见面日期之后。

`pokeldn/pla/trade_box.py` 和 `pokemon.py` 再现游戏机的字节。

<a id="choosing-what-to-offer"></a>
## 选择提供什么

主机提供的记录是其自己创作的。游戏读取 PKHeX 的 PA8，并且每个测量的偏移量都与其一致：

|偏移|领域 |偏移|领域 |
|---|---|---|---|
| 0x08 |种类 | 0x92 |当前HP |
| 0x0a |持有物 | 0x94 |包装个人价值|
| 0x0c | 训练家ID，32位（面板显示模1000000）| 0xa4 |成长价值|
| 0x10 |经验| 0xac，0xb0 |绝对身高、体重（浮动）|
| 0x14 |特性| 0xb8 |最近持有人|
| 0x16 |阿尔法位| 0xee |版本 |
| 0x1c |人格价值| 0xf2 |语言 |
| 0x20 |性格（第三世代表：9 为乐天）| 0x110 |训练家姓名|
| 0x24 |表格| 0x134 |见面日期|
| 0x26 |努力值| 0x137 |球 |
| 0x3e |阿尔法移动| 0x138，0x13a |蛋和遇见地点|
| 0x50、0x51、0x52 |身高标量、体重标量、比例| 0x13d |达到水平和训练家性别|
| 0x54，0x5c |移动，PP | 0x159 |购买搬家记录|
| 0x60 |昵称| 0x15d |掌握位图动作|
| 0x8a |重新学习动作| 0x168，0x16a |等级，六项统计数据 |

`pokeldn/pla/pokemon.py` 将地图保存为四个表。在 47 个捕获的记录中，alpha 位和 alpha move 设置在相同的三个记录上，其中 0x50、0x51 和 0x52 中携带 0xff；比例等于所有 47 中的高度标量； 0x94 有蛋和昵称位清晰；每条记录都带有版本 47、语言 2、健全性 0 和附加功能区 0xff。

`pokemon.build` 从 376 个零字节组装一条记录，将给定字段写入每个捕获记录都同意的默认值，并写入校验和；未映射的字段保持为零。与游戏机自己的68级耿鬼相比，它的不同之处仅在于选择的领域。组合记录（第 6 代异色值为 0 的异色、alpha、昵称、保存从未保存过的种类、游戏表格中的每个值）交换并显示为已发送。存储后，它们与仅在字段[交换重写内容](#what-a-trade-rewrites)列表中发送的内容不同；携带游戏计算统计数据的尾部留下 14 个字节的变化（校验和和处理程序字段）。

存储已保存的已接收的记录（其加密常量和PID）（盒块 `0x47E1CEAB`）。

`bin/pla_host.py` 按顺序处理每个 `(port, sequence id)` 一次，并重新发送未确认的答案。每次光标移动都会显示一次，取消的提议将重新提议为 `04 01`。第二个交换会重复消息正文，因此按正文进行重复数据删除会丢失其答案。

<a id="mastered-moves"></a>
### 掌握动作

0x15d 处的 8 个字节是游戏掌握列表中 61 个动作的位图（按顺序排列）；一个种类只能掌握其个人进入许可证（u64 at 0xa8）。在牧场变化招式屏幕上，当招式的掌握等级（`mastery_la`，按种类和形式，学习集格式）等于或低于当前等级或设置其位时，招式就会绘制卷轴：在13级小火焰猴上，高速星星（20，索引10）仅在其位设置时绘制它。

<a id="the-stats-the-game-computes"></a>
### 游戏计算的统计数据

`pokeldn/pla/stats.py` 重现了交换写入尾部的统计数据。每个统计数据都是一个增长项，四舍五入为 `(sqrt(base) * multiplier + level) / 2.5`，加上一个基本项：`((level / 100 + 1) * base)` 截断加上 HP 水平，`((level / 50 + 1) * base / 1.5)` 截断，其余部分的性格为 110% 或 90%。乘数是通过增长值加上个人价值偏差（3 为 31 及以上、2 为 26、1 为 20）从表格中读取的，总和固定在
10.经过68级14级游戏机计算的12个数字验证，耿鬼的基本属性：完美个人价值和成长10的273/210/199/322/345/220，捐赠者的239/136/121/322/304/133（个人价值22和成长9也钳位到10，所以它的速度不变）。

0xac和0xb0的绝对身高和体重是种类平均时间
`(scalar / 255) * 0.40000004 + 0.8` 每个标量，高度单独为高度，两者相乘为重量，采用 32 位浮点数。标量 111 和 221 相对于平均值 150 和 405 给出 146.11766052246094 和 452.38031005859375，这是游戏机耿鬼携带的浮点数。

种族值、性别比例、特性、经验曲线、平均大小、升级学习集和 PP 来自 PKHeX 的游戏表副本：`personal_la`（0xB0 字节一个条目；0x21 位 6 标记游戏中的一个种类，其中 264 个），`lvlmove_la.pkl`（一个16 位 BinLinker 存档，先移动半字，然后再移动级别字节），`MoveInfo8a`、`Experience`。

<a id="the-clone-clock-and-atomic-protocols"></a>
## 克隆时钟和原子协议

该频段将 Clone 系列分成独立的协议，与 6.32 克隆协议无关：Clone Clock 0x77 和 Clone Atomic 0x74。

克隆时钟消息为 18 个字节：种类、序列、大端 u64 原始时钟、大端 u64 响应者时钟（以毫秒为单位）。 Kind 0 是一个请求（除非接收者是主设备，否则被忽略）； kind 1 是回复，它检查序列，计算 NTP 样式的偏移量并推进 ClockProtocol `+0x5c` 的状态（0 重置，1 请求，2 同步，3 主控，4 停放）。加入的游戏机停在状态 4，发送一些请求并等待。主机 kind-1 回复回显序列并发出与主机毫秒时钟同步的滴答声，并停止发送。

克隆原子消息有 14 个字节：种类（0 宣布、1 提交、2 确认）、生成、大端 u32 元素索引（低于 33）、大端 u64 值。元素表是 0x18 字节的 33 个槽：生成、状态（0 个空、1 个挂起、2 个等待提交）、u64 值，以及在 `+0x10` 处，仅由来自已知参与者的匹配生成类型 2 写入的确认站位图（协议 `+0x78` 上的参与者表；站 0 的主机读取一次 1）加入）。仅交换场景创建元素（本地公布`0x6e1e48`）；种类 1 和 2 需要一个挂起，并且主机 kind-0 通告会绘制一个不填充任何槽位的 kind-2 回声。

<a id="reading-and-writing-a-packet"></a>
## 读写数据包

`pokeldn/ldn/pia6.py` 讲版本 11；消息帧是 5.27 到 6.30 的，读取不变
`pia5.parse_messages`（标志 `0x01` 标记了 5.27 处的目标位图）。

每级填充字节为0xFF。消息行走读取 0x00 的存在字节作为单字节标头，继承前一条消息的每个字段：零填充使游戏解析第二条消息，失败并丢弃整个数据包（在 `0x74419c` 处被拒绝）。游戏机在 `0x6f0af8` 处用 0xFF 预填充其加密缓冲区； `0x6e6cb0` 将块大小设置为 16。

`pokeldn/pla/`保存密码（阅读广告所需）、游戏密钥、本地通信ID和`session_keys(ssid)`。 `tests/test_pia6.py` 引脚布局、针对 `crypto.PiaCrypto` 的推导、捕获的广告以及 `main` 的每个常量读数。

<a id="hosting"></a>
## 托管

`bin/pla_host.py` 广告标题、密码、场景 ID 和链接代码；
`pokeldn.pla.build_advertise_data(code)` 逐字节重建零售广告（`app_version` 0、`security_mode` 1）。主机使用来自其自己的 SSID 的会话密钥验证每个入站数据包，并按协议 ID 打印每个 Pia 消息。

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/pla_host.py --keys PROD_KEYS \
        --code 00000000 --seconds 240
 搜索屏幕上的游戏机交替扫描为站点（它与找到的主机关联；其取消验证，原因 3，结束扫描）和在新 SSID 下托管，大约五秒的周期：一次扫描，二到四次托管。关联的加入方保持沉默，直到主机发送 Net 0x2C 连接请求（`host_pia.build_net_probe` 在 6.32 处的消息），每 500 ms 一次，直到得到答复； `--no-net-probe` 阻止了它。

<a id="joining-a-consoles-network"></a>
## 加入游戏机网络

一个方加入者欠主机游戏机这些消息，以零售加入方的顺序（来自模拟主机的Net 0x50）； `pokeldn.pla.joiner` 发送它们。

|主机发送 |方加入答案 |
|---|---|
|净0x11 | Net 0x12 回显序列 id，消息标志 `0x11`，标头目的地 0；第一次，会话加入请求（类型 0），标志 `0x01`，标头目的地 0 |
|净0x50 | Net 0x51 回显序列 id，标头目标 0 |
|会话类型 7 命名加入方 |类型 8：位置 id，类型 7 名称作为目标，然后是主机自己的 |
|会话类型 5 |类型6：它自己的常量id，两个零字节，更新的序列|
|第一种类型 5 | 0x81 流在端口 0 上打开，`0f00000b 0001 0001 01 00000001 0000000000008000000000` |
|端口 0 上的 0x81 记录 |确认，它自己在端口 1 上的记录（标志 `0x1f`，序列 1，位图 `0x01`），然后在 0x7c 端口 1 上打开密钥零，初始化标志 |
| 0x7c 端口 0 打开，`0000000000000000 0100` |同样的背面，它自己的 port-0 序列 1 |
|展示或提议|它自己的、相同的选择器和计数器 |
|选择器 5 和 7 |相同的两个字节； 7之后，相位键在端口1上打开|
|相位钥匙打开|阶段 3、6、11、14（选择器 1），每次主机应答后，然后阶段键关闭 |
| RTT 类型 0 | kind 1，时间戳回显，最后两个字节为请求者的变量id |

零售加入方将其 Net 0x12 发送到标头目的地 0（108 of 108）。读卡器门丢弃一个寻址到主机的变量 id：然后，模拟的游戏机每 0.5 秒重新发送其迁移的 0x11，持续 4 秒，并在其类型 7 后 4.1 秒发送其第一个 0x40。寻址到 0，0x11 发送一次，第一个0x40 在 7 型（4 座中的 4 座）后 0.10 秒后跟随；根本没有类型 8，9.1 秒。

当游戏机的 WaitMember (3000 + rand%1000 ms, `0x2c491b8`) 在接受加入请求之前结束时，类型 7 来自 `LeaveMeshWithHostMigrationJob`，如朱 ([docs/sv.md](sv.md#what-decides-a-seat))； `bin/pla_join.py --join-delay 4.5` 绘制它。游戏机每秒重新发送一次，直到类型 8 到达。它的类型 8 处理程序 `0x739b08` 仅采用 25 字节消息，其第二个位置 id 是游戏机自己的； `0x73f0a8` 然后设置作业的完成标志
`+0xb0` 当第一个等于作业在 `+0x68` 处持有的目标时：

    08 | joiner location id (12) | host location id (12)
 一旦主机应答，加入方会在零点几秒后发送其下一阶段，交换动画除外（几秒）。

实机主机在加入方到达之前用选择器 1 宣布每个阶段，然后在 0.02 到 0.04 秒后用选择器 2 应答加入方。只有选择器 2 响应一个阶段。在 `02 0e` 之前关闭游戏机自己的 `01 0e` 上的相位密钥的方加入永远不会收到
`02 0e`：交换未完成，游戏机在离开时显示错误2-AW7KA-0007并保留十分钟限制（[交换限制](#the-trade-restriction)）。
`bin/pla_join.py` 关闭 `02 0e` 上的钥匙，并在交换后保留座位，直到游戏机的玩家退出，或 `--hold` 结束； `--hold-after-trade N` 在最后一次排队交换后 N 秒离开。稍后在同一个座位上的交换会逐字节重复每个步骤，因此加入方会在交换完成后忘记它回答的步骤，并显示下一个 `--offer`。它大约每秒在端口 0 和 1 上重复一次 0x81 确认：

    0000002c ffff 0002 01 00000001       header: size 0x2c, lowest pending 2, bitmap 1
    00 02                                type 0 on the first, 1 on every later one; two entries
    00 0002 0001 00*16                   the host's stream: one past its sequence, then its sequence
    00 0001 0001 00*16                   its own stream
 后来的确认也将第一个条目的第二个字段中的序列放入过去。
`tests/test_pla_joiner.py` 对加入方演奏脚本化的主机； `tests/test_esp32.py` 在两个模拟板上运行它。

<a id="reaching-local-trade-on-the-console"></a>
## 在游戏机上进行本地交易

    title screen, A -> Jubilife Village, the trading post -> talk to Simona (Trado in French), A
    -> "echanger des pokemon !" -> local rather than online
    -> the warning that an error temporarily restricts trading
    -> an eight-digit code
    -> "Echange en reseau ! Recherche d'un partenaire en cours..."
 两个控制台在搜索开始之前输入相同的八位代码，如 Let's Go 中所示。

`0x397e1b8` (`30 30 60 60 120 120 180 180 240 240 360 360 480 480 960 960
1440 1440 2160 2160`) 处的分钟表是丢失的挎包的：`0x2686a0c` 在网络时钟上返回 `max(0, table[count % 20] -
elapsed)` (`0x265d180` -> `nn::time::StandardNetworkSystemClock::GetCurrentTime`)，仅由丢失包数据存储字符串旁边的 `0x266c740` 和 `0x266d580`（`CreateLBData`，
`ScanOtherData`、`ReturnLB`、`0x266d8dc..0x266dec8`）。 `0x129751c`，另一个网络时钟调用程序，将经过的秒数与 21600 进行比较。

<a id="the-advertisement"></a>
## 广告

从搜索屏幕上的游戏机扫描：

| | |
|---|---|
|本地通讯 ID | `0x01001f5010dfa000` |
| LDN协议| 1：AES-CTR广告，如剑|
|场景 ID | 1 |
|广告框版| 4（GBA 应用程序 3、剑 2）|
|接受政策 |全部 |
| 参与者 | 2 个中的 1 个 |
| SSID | 16字节，会话密钥的输入|
|应用数据| 112 字节 |

应用程序数据是0x5C系统属性块（`docs/ldn.md`，6.16至6.41：系统通信版本21，应用程序通信版本0，十六字节用户密码，玩家限制启用，一名玩家，名称大小1，编码1，名称单个空格），然后20个字节携带明文代码：

    +0x00  16  the code as ASCII, NUL-padded
    +0x10  4   its length, little-endian
 代码 `0000 0000` 给出 `3030303030303030`，八个 NUL，长度为 8。

<a id="the-link-code-in-the-advertisement"></a>
### 广告中的链接代码

用户密码是相同的代码，由Pia的密码设置器`0x6fc454`加密。在模式 1 (`+0x234`) 下启用传输加密 (会话 `+0x230`) 时，它会使用 0xFE 填充 16 字节缓冲区，将 NUL 填充代码复制到其上，并使用 `0x6e68d0` 对其进行就地加密：会话密钥下的 AES-128-GCM `+0x238`（游戏密钥`p1frXqxmeCZWFv0X`，通过`0x6fc8a4`设置），没有额外的数据，标签被丢弃，从密钥中取出一个四字节IV，`key[1] key[8] key[7] key[2]`（`0x6fc4e4`到`0x6fc4fc`），这里`1emf`。一个 GCM 块是具有固定密钥流的 XOR：

    password = KEYSTREAM XOR (the code's ASCII, NUL-padded to 16)
    KEYSTREAM = AES-128-GCM(key = p1frXqxmeCZWFv0X, iv = 1emf).encrypt(sixteen zero bytes)
              = e5ab19ed742b6d40885998bf968aa166
 密钥流不随 SSID、频道、代码或游戏重启而改变。 `pokeldn.pla` 有
`link_code_keystream`、`user_password`、`link_code` 和 `parse_advertise_data`（根据解码的密码检查所述代码）。设置器是 Pia 的，因此乐队的每个标题都以这种方式加密（[无线层](ldn.md)）。

<a id="retail-notes"></a>
## 零售笔记

实机在两种角色中都运行与仿真机相同的链，无论有或没有链接代码。法语保存写入处理程序语言 3，而英语保存写入 2。`--fresh-pid` 重新发送保存已在新 PID 和加密常量下保存的记录。主机在提议之间重新读取其提议文件；标志更改需要重新启动。主机在其下重新启动的游戏机在下次搜索时显示错误 2318-0006；离开交换菜单并再次搜索会将其清除。

<a id="leaving"></a>
## 离开

退出交换机的游戏机运行`nn::pia::session::LeaveMeshJob`：发送Session type-3离开请求，等待主机的type-4离开响应500ms，然后再次发送，最多发送4次，然后让网络应答或不应答。步骤是SendLeaveRequest `0x73b898`（作者
`0x737ee8`，在 `0x737f40` 处键入字节 3，在 `0x73b990` 处调用，截止时间 `0x73b9a8` 处 0x1f4 毫秒），WaitLeaveResponse `0x73bab8`（重试计数器 `[job+0x6c]`，放弃过去 3 个（`0x73bbf0`）和 CompleteProcess `0x73ba54`。

    03 | u32 random | location id (12) | address kind | IPv4 (4) | port big-endian (2)
    04 | u32 random | location id (12)                          the response, 17 bytes
 位置 ID 是 `pia_connect._location_id` 的（站常量、零半字、大端变量 ID）和站自己的地址。每次发送的随机字都不同，包括重传。在每个捕获的离开中，`+0x11` 处的地址类型为 0；处理程序在 1 和 6 之后读取 18 字节的地址和端口（`0x7380f0`），并接受 24 或 36 字节的请求（`0x738024`）。

类型 3 处理程序 `0x738000`（调度表 `0x3973f19`，基础 `0x735434`）仅当 `+0x50` (`0x7473ec`) 处的会话常量 id 等于 `+0x40` 处的站自身的会话常量 id 时才起作用（`0x747388`）。它通过其位置 ID 找到离开者，将 `04`、一个新的随机字和请求的字节 5 到 16 应答到请求的地址（`0x7381c0..0x738248`，通过 `0x735fb0` 发送），然后删除该站（`0x735b90`）。类型 4 处理程序 `0x738280` 仅在常量 id 和变量 id 为离开者自己的 17 字节消息上设置作业的完成标志 `[job+0x69]`，并且仅在作业运行时设置 (`0x6e5f0c`)；一个主机回答不离开保留所有退出游戏机完整的四个发送。

| 主机 |首先离开身份验证|
|---|---|
| `bin/pla_host.py` 4 类响应之前（8 个零售出发）| 2.02 至 2.07 秒，四个请求间隔 0.49 至 0.55 秒 |
| `bin/pla_host.py` 用类型 4 回答（两个零售出发）| 0.046 和 0.066 秒，一个请求 |

对于类型 4 答案，第一个类型 3 在玩家确认退出后 0.15 秒内出现（带有引导标记，两次离开），并且该字段在确认后 3.70 秒返回屏幕上。

退出后，交换场景至少保持“Communicating. Please stand by...”提示（`msg_ui_box_p2ptrd_09`）3.0 秒。玩家退出（`0x110bd50`，来自 `0x110b970` 的是／否选择）、伙伴离开（`0x110c9bc`）及会话错误（`0x110b504`）都进入模式 9（`0x110b72c`，步骤 `[scene+0xb4]`，表 `0x3979c98`）。步骤 0 运行 `0x26dcc74`，仅当 `[[[0x4279560]+0x2b8]+0x78]` 中待放置记录标志已设置时保存（`0x10457e4`，请求类型 3；见[交换限制](#the-trade-restriction)）。步骤 1 在 `[scene+0x278]` 启动基于 `nn::os::GetSystemTick` 的计时器、开始离开（`0x26be890`），并取消交换任务（`0x26d9e90`）。步骤 2 等待 3.0 秒（`0x110b7d8` 的 `fmov d1,#3.0`）、离开序列完成（`0x26bdc94`）且任务消失（`0x26d9cf0`），再关闭提示；步骤 3 在提示关闭后返回 true。立即获回应的离开（0.05 秒）和无主机回应的离开（2.0 秒）都在 3.0 秒内完成，因此主机回应不影响回到地图的时间。一次有类型 4 回应的实机离开，从类型 3 到地图出现为 3.77 秒。
模拟运行的《阿尔宙斯》1.1.1 主持搜索、一个站点入座时退出，到达步骤 1（`0x110b78c`），4.33 秒后通过步骤 2（`0x110b81c`），比最后数据包晚 0.43 秒：交给站点的主机迁移（类型 7）超过了 3.0 秒下限。步骤 3（`0x110b80c`）再晚 0.03 秒，场景析构（`0x110bec0`）在步骤 2 后 0.33 秒。
模拟运行的《阿尔宙斯》1.1.1 作为 `bin/pla_host.py` 的站点从盒子退出时，到达步骤 1 后在 0.07 秒内发送类型 3（立即获回应），步骤 1 后 3.03 秒通过步骤 2，再过 0.03 秒到步骤 3，步骤 2 后 0.33 秒析构：离开在下限内完成，因此步骤 2 只等待满 3.0 秒。

Pia 内部没有计时器先于第一个类型 3（[pia.md](pia.md)，离开会话）。 `Session::LeaveAsync`的唯一调用者是游戏的离开请求，更新`0x2ca0a10`（vtable `0x4198ef8`，状态`[req+0x88]`，跳转表`0x3985448`）：其第一次更新调用`LeaveAsync` (`0x2ca0ac0`) 除非会话作业已在运行 (`0x72a280`)，并且其下一个更新等待作业的结果 (`0x72a294`)。

从游戏机在 0x7C 上的最后一个游戏消息到其第一个类型 3 的时间为 1.91 至 83.4 秒，经过九个主机出发，包括玩家的输入。在该窗口中，游戏机仅发送 RTT、网络应答、其定期 0x81 记录和主机交换盒的确认。在线路离开之前没有固定的延迟，并且没有人需要回复。

`bin/pla_host.py` 使用类型 4 响应来应答每个类型 3 请求。脚本化的游戏机
`tests/test_pla_host_loss.py` 运行作业的计时，主机的答案在 unicorn 下通过 `0x738280`。

收到的休假不会改变游戏机屏幕上的任何内容；游戏机作用于网络消失或其伙伴沉默。游戏机出现在盒子屏幕上，但没有提供任何内容：

| 主机 | 游戏机 |
|---|---|
|网络中断，无论是否请假|一秒钟内出现“错误代码 2318-0006” |
|网络启动且无声，无论是否离开（`--leave-sends 0`）| “你的交换伙伴选择不继续交换”（“L'autre joueur a choisi d'annuler l'échange”），然后是通信，然后是 `DisconnectedByUser`，没有错误代码（消息大约 13 秒，A 之后大约 3 秒的通信）|

`--leave-after SECONDS`使`bin/pla_host.py`将带有自己id的请假发送到每个加入的站点并结束运行； `--stay-after-leave` 保持网络正常运行、安静，并在游戏机在交换后离开后继续运行。叶子的形状固定在捕获的四片游戏机叶子上。

<a id="unresolved"></a>
## 未解决

- 析构（模拟站点中为步骤 1 后 3.36 秒）到地图出现（实机类型 3 后 3.77 秒）之间的 0.4 秒做什么；模拟器不提供地图标记。
- 盒子代码的哪些流程调用 `0x26dcc74`（`0xc17ce0`、`0xc17e8c`）。
