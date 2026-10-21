<a id="the-cartridge-its-keys-and-taking-a-seat"></a>
# 卡带、钥匙以及就座

`main` 静态链接所有 Pia（252 个 `nn::pia` 类、2036 个虚拟方法）和导入
`nn::ldn`。在 Pia 之上，游戏使用协议缓冲区：`main` 为 78 个 P2P 消息集（`gflnet.p2p.framework.pb`、`.block.pb`、`.sync.pb`，每个内容一个包：交换、战斗、营地、突袭）中的每一个携带一个 `FileDescriptorProto`。
<a id="the-ldn-passphrase"></a>
## LDN 密码

    W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL
 64字节，原始（两份，`0x203ff04`和`0x203ff45`）；等于 NintendoClients wiki 的朱／紫行，距离传奇：阿尔宙斯（这里是 `HGhG`，那里是 `HGHG`）有一个字符。

    0x006c3eb4  adrp x1, #0x203f000 ; add x1, x1, #0xf04    the literal
    0x006c3ec0  add  x0, sp, #0x10                          the LdnCreateSessionSetting
    0x006c3ec4  mov  w2, #0x40                              64, not a NUL-terminated length
    0x006c3ec8  bl   #0x1790450                             its passphrase setter

`nn::pia::local::LdnCreateNetworkJob` 的密码短语位于 +0xC4，其长度为 +0x104，
`NetworkConfig`意图+0xB8（本地通信ID）和+0xC0；它将密码复制到
`SecurityConfig+4` (`0x01797280..0x01797284`) 就在 `nn::ldn::CreateNetwork` (`0x017972bc`) 之前。
`LdnBackgroundProcessJob` 要求长度为 16..64。
<a id="the-pia-game-key"></a>
## Pia 游戏密钥

    p1frXqxmeCZWFv0X
 `0x01c3dc87` 处的 16 个 ASCII 字节，由三个调用站点（维基的剑／盾行）未更改地使用：

    0x006ca914  mov  w8, #1 ; str w8, [sp, #0x18]     crypto enabled
    0x006ca91c  adrp x8, #0x1c3d000 ; add x8, x8, #0xc87
    0x006ca924  ldp  x9, x8, [x8]                     the 16 bytes
    0x006ca938  stur x9, [sp, #0x1c]                  -> the setting's key field
    0x006ca93c  bl   #0x183fd10                       create/join

<a id="reading-the-cartridge"></a>
## 读取卡带

    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --keys prod.keys --type Program
    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --nca 87e41bc8 --exefs 0 --extract main
    ./.venv/bin/python tools/switch/nso_read.py main
    ./.venv/bin/python tools/switch/rtti_names.py main.bin 0x1900fc0 --rodata 0x1901000:0x24da168

`xci_read.py`就地读取XCI； `main` 是文本 0..0x1900fc0，rodata 为 0x24da168，数据为
0x2635f38。方法：[对Switch标题进行逆向工程](switch_re.md)。

`/bin/message/<Language>/common/*.dat` 使用 Gen 6/7/8 消息容器：第 *n* 行的密钥开始于
`0x7C89 + n * 0x2983` 并每个字符向左旋转 3（每行以 `0x0000` 结尾）。 `.tbl` 是 `AHTB` 索引，条目 *i* 是行 *i*。
<a id="pia-4"></a>
## 皮亚 4

Pia 标头携带版本 4，其形状与 [Pia 层](pia.md) 上的两个频段不同；其下方是 5.27 的 LDN 系列（相同密钥、IV、帧加一个字段）。 `pokeldn/ldn/pia4.py` 实现了它。
`pokeldn.swsh.session_keys`是BDSP的推导，没有版本替换：

    session key   = ldn_session_key(GAME_KEY, application_data[12:16] little-endian)
    IV            = crc32(application_data[0:4] || the sender's MAC)[0:3] || source id || nonce
    tag           = sixteen bytes, checked in full
 484 个零售数据包中的 484 个已通过身份验证，每个数据包的源 ID 为 0。每个会话的会话参数和网络 ID 都会更改。第二条路径 `0x0179bff0` -> `0x01774f40` 在会话的两个 64 位值上播种 AES-GCM；本地交换只需要广告。
<a id="taking-a-seat"></a>
## 入座

    POKELDN_RADIO=esp32:auto ./.venv/bin/python bin/swsh_join.py --keys PROD_KEYS --scan-only
扫描主机屏幕并将每个广告写入`scratchpad/swsh_net_facts.json`；
默认为 `--pw-mode raw`。

|屏幕|本地通讯 ID |版本 |场景|应用程序版本 |
|---|---|---|---|---|
|链接交换 | `0x0100ABF008968000`（剑的）| 4 | 60001 | 7 |
| 神秘礼物本地无线通信 | 相同 | 4 | 65535 |  |

盾 使用 剑 的 id：它将 `0x0100ABF008968000` 与 `0x011083e0..0x011083f0` 处的 `mov`/`movk` 构建为 `sp+0x88`（`0x01108404`；其通往 LDN 意图的路径未追踪），并且其`control.nacp` 列出了 `LocalCommunicationId[0] = 0x0100ABF008968000`、`[1..7] = 0x01008DB008C2C000`。

384字节的应用数据：

    0x00  4  network id, random per session
    0x04  4  CRC32 of the Link Code's ASCII digits, LE; 0 with no code (12345678 -> 0x9AE0DAAF)
    0x08  1  system communication version, 5
    0x09  1  header size, 0x18
    0x0A  2  padding
    0x0C  4  session param, random per session
    0x10  8  zero
    0x18  2  CRC16 over 0x1A..0x180 (`0x0065dcb0`, `pokeldn.swsh.beacon.crc16`)
    0x1A  2  network version word, 12 bits, 0x0D70 (`0x006c17c0` from `0x02068848`)
    0x1C  1  bit 0 from `0x006b5c10`; set is refused
    0x1D  1  payload type, 0 for station info
    0x1E  1  page byte, 1 and 2 in turn every third publish (`0x0111aac0`)
    0x1F 266 the player profile, as in the trade snapshot at 0xAEC but sampled at another moment
             ([the protocol page](swsh_protocol.md#the-player-profile)); zero to the end

`Connect failed with status code 1` 是拒绝关联；下一次尝试相同的搜索可以关联。搜索 剑 在一个 Comm id 下通告两个网络：其 Y-Comm 信标位于场景 65535，并且在第二条消息之后，其匹配网络位于场景 60001。信标上的站点在 16 个连接中的 0 个到达交换盒（网状连接因原因 1 被拒绝，或者其下的广告已更改）； `bin/swsh_connect.py` 仅加入场景 60001 并重新扫描直至其出现。关联后，游戏机向 `169.254.x.255:12345` 广播 Pia（每秒大约十个数据包）；屏幕什么也没显示。加入的电台离开后结束游戏机广告的内容是未读的。
<a id="how-a-searching-sword-finds-a-partner"></a>
## 搜索之剑如何寻找伙伴

在 Y-Comm 屏幕上，每个游戏机在场景 65535 处托管一个信标网络，并大约每秒浏览一次（`0x006c3630`：托管 `0x006c3840`，使用 `0x006c4550` 中的标准浏览 `0x006c3770`，
`0x0183fac0`，仅针对通讯 ID 和网络类型）。通过 CRC 和版本门 (`0x006c1be0`) 的记录到达附近的玩家注册表 (`0x0110f270`)，该注册表会删除自己的记录（广告 0x1F 处的设备 id 和 0x2F、`0x0111b160` 处的帐户 uid）以及任何没有网络 id 和场景对的记录（`0x0110f2d4`）。这里没有任何东西加入。

Link 交换，然后是普通交换，显示两条消息，每条消息都等待 A。在第二条消息（“您可以取消搜索...”）之后，`0x00fba940` 调用 `SetMode(comm, 2)` (`0x01096d10`)； `0x01095f10`在一秒内行走状态0、5、3、4、6，状态6调用场景60001（`0x01096730`）的`StartRandomMatching`（`0x010fcff0`）。主世界显示“Recherche...”。第一条消息中留下的游戏机永远不会调用 `SetMode(comm, 2)` 并且永远不会匹配。

匹配层通过以下方式连接网络（`0x006c9e70`、`0x006cb8e0`、连接 `0x006ca1c0`）：

    scene 60001, equal to its own
    node count 1, below its maximum of 2; network type 2; node count maximum 8 or less
    advertise 0x04 zero: a search without a link code refuses a password
    advertise 0x00, a u32, greater than the searcher's own
    advertise 0x00 not among ids whose join failed this search (0x80 entries)
 A 连接密码仅更改 0x04。 `bin/swsh_connect.py`（无代码）加入编码游戏机并进行交易；
`bin/swsh_host.py --code 12345678` 是通过编码搜索加入的，绝不会没有代码。 id 主机较大，因此两个搜索控制台仅以一种方式配对； a 主机 在附近发布一个 id
0xFFFFFFFF。
<a id="what-the-console-says-first"></a>
## 游戏机首先说的话

Pia本地协议0x24，如BDSP（`pokeldn.ldn.local_protocol`）：版本1，类型0x11，0x30固定字节，八个九字节席位，主机迁移字节。 `allow_participating` 为真，因此游戏机在说出 Pia 之前先列出加入方。

    a9fe0e01 3039 ... 00      169.254.14.1:12345   station 0, the console, ranking 0
    a9fe0e02 3039 ... 01      169.254.14.2:12345   station 1, the seat, ranking 1
 主机重复更新会话，直到每个站确认它 (0x21)。携带其序列 ID 的 ack 会停止重播（13 毫秒内）；具有另一个序列 ID 的 ack 则不会 (`bin/swsh_connect.py --seq-delta`)。头字节 0x05 和 IV 的源 id 为 0，如游戏机自己的（`--station-sweep` 走其他）。
<a id="the-pia-session-object"></a>
## Pia 会话对象

`[[0x02616a30]]`（也为`[0x02630f40]`），交换代码读取站id，是Pia的会话对象：0x270字节，无vtable，由`0x0183ddb0`（`0x0183dfd4`）从`0x006a8644`分配一次。后端来自网络工厂（`[x20+0x60]`、`0x006a8600`）：`+0x178` 插槽 `0x240/8`，
`+0x188` 插槽 `0x290/8`、`+0x168` 插槽 `0x248/8`（`0x0183e074`）、`+0x170` 插槽 `0x248/8` 时插槽
`0x1b8/8` 为真；字节 `+0x162` 选择。在LDN上，工厂是`LdnNetworkFactory`，其插槽73（`0x01791080`）构建了一个0x7220字节`LdnMatchmakeSession`（来自GOT `0x0262fbd0`的vtable）。

|领域 |写者 |价值|
|---|---|---|
| `+0xf0` | `0x018418a0` (`0x01841918`) |该游戏机自己的站id |
| `+0xf8` | `0x018418a0` (`0x01841990`) | 网状网络主机索引处的站点 ID，即字节 `[[0x0262f7b0]]+0xab`（`0x017bbfe0`）；当 `[obj+0xd4] == 4` 时跳过 |

`0x018418a0` 在创建 (`0x018394d8`) 和加入 (`0x0183d9b0`) 上的 `0x018410e0` 之后运行。网格主机索引`+0xab`（自己的索引`+0xac`）由创建写入（`0x017b092c`，等于`+0xac`），加入响应（`0x017b4e4c`），重置为`0xfe` (`0x017bb820`) 和 `0xfd` 以及 `+0xac` (`0x017b99a0`)，以及主机迁移：`0x017ca454`（来自 `LanProcessHostMigrationJob`，
`LocalProcessHostMigrationJobNew`，下）和 `0x017caf48`。

`MeshEventListener`插槽2，`0x01843580`（打开`[x1]`，表`0x02083fe8`），还写入`+0xf8`：

|活动 |商店 |
|---|---|
| 1 |后端的插槽30（`0x01844bc4`），然后`0x018412a0(obj, 2, id)`就改变了|
| 2 | id `0x017d6080` 返回（`0x01844a74`）；后端槽位30（`0x01844edc`）； `0x01844f60` |
| 3 | 当 `[obj+0xd4] != 3` 时，与 `+0x100` 一起清零（`0x0184415c`、`stp xzr,xzr`） |

`0x01837000..0x01850000` 中的商店为 `+0xd4`：

|价值|网站 |
|---|---|
| 0 | `0x018399c8` |
| 1 | `0x01837c1c`、`0x018396ac`、`0x0183dbbc` |
| 2 | `0x01837a8c`、`0x01839474`、`0x0183cda8`、`0x0183d94c` |
| 3 | `0x01839f7c`，在`0x01839cc0`，其呼叫者为`0x0177d8a0`、`0x0180afe0`和`0x0180bd0c` |
| 4，否则2 | `0x0183a2cc`，在`0x0183a040`：4时`w8 - 6 < 3`(`0x0183a2b8..0x0183a2c8`)；呼叫者 `0x0177e8a8` 和 `0x01818b68` |

`0x01839cc0`的调用者属于`LanMatchJointSessionJob`（`0x0177d8a0`）并且
`NexMatchJointSessionJob`（`0x0180afe0`、`0x0180bd0c`）。 `0x0183a040`的调用者属于相同的两个作业（`0x0177e8a8`、`0x01818b68`）。普通LDN创建并加入设置模式`+0xd4`为2。

仅当 `0x01841350` 和 `0x01769ec0([obj+0x38])` 为 false 并且无符号值 `[obj+0xd8] - 2` 至少为 6 (`0x01843980..0x018439a4`) 时，事件 2 才到达主机 ID 存储。方式2从`0x017d6080`中选择新站的常量id；模式 4 选择包含 slot-30 存储的联合会话分支。因此，event-2 slot-30 存储需要联合会话模式 4。

事件1的slot-30商店要求出发站的id与`+0xf8`匹配并且与`+0x100`不同，
`0x01840b90(obj)` 为真，请注明 `+0xd8 == 1` 和 `[mesh+0x64] == 0`（`0x01844614..0x01844638`、`0x01844654..0x01844664`）。 `0x0184a4b0` 必须找到一个输出字非零且与 `obj+0x180+4*[obj+0x162]` 处的字不同的映射。如果设置了网格控制器的字节 `+0x84`，则还必须设置其字节 `+0xc0` (`0x01844b54..0x01844b9c`)。新的 slot-30 值在存储之前必须与 `+0xf8` 不同。在 LDN 上，`0x01840b90` 测试本地网格控制器的
`+0x281` 和 `+0x234` 通过虚拟插槽 `+0xb0` 和 `+0xa8`。成功的本地控制器构造将两个字节设置为 1（`0x017a06ac`、`0x0183c228`）；其余的 event-1 门仍然适用。单独的后端类型并不排除此分支。

当`[this+0x18]`为空时，`LdnMatchmakeSession`的槽30（`0x017a23d0`）返回`0xff`，否则
`0x017672d0`的16字节地址为`[[this+0x18]+0x18]+0x2c0+8`：0时全为零，其前四个字节后十二位为零时，否则错误`0x10c07`。插槽 28 (`0x017a23b0`) 是 `0x018407f0` 进行的虚拟调用。

当 `+0xf0` 非零时，`0x018407f0` 为 true，等于 `+0xf8`，并且后端的插槽 28 与托管 Pia 网格的游戏机上的创建和连接值一致。主持交换的游戏机根据命令爬上确认阶梯；加入 pokeldn 主机的主机遵循共享价值观（[泵](swsh_trade.md#the-pump)）。
<a id="reaching-the-game-layer"></a>
## 到达游戏层

游戏下面的每一层都是双向的（[Pia层](pia.md)）：本地协议0x24，站握手0x14，网状连接0x18，RTT 0x58，可靠的Windows 0x7C和0x80。

加入端的 0x14 连接响应必须使用《剑》发送的 840 字节形式（`host4.build_host_response`：0x11 的账户 ID、0x88 的玩家名称、0xB1 的尾部、0xBC 的令牌）。模拟运行的《盾》1.3.2 主机接受了 56 字节响应（`[0x37]` 为 1，其后为零），将站点加入网状网络，却不发送游戏消息；使用 840 字节形式后，在加入响应后 0.03 秒发送首个 ping，以加入端名称打开交换盒子并完成交换。实机《剑》使用 17 字节响应也完成交换，其 0x11 之后的字段来自残留缓冲区字节（[Pia 层](pia.md#what-a-connection-response-must-satisfy-to-be-read)）。`bin/swsh_connect.py --respond` 发送 840 字节形式。

单独放置时，游戏机会重复 `61 00 00 00 0a 00`，一个 ping（大约每秒 4 次）； 0x80 每秒请求一次 ack id 1，0x7C 保持沉默。 `bin/swsh_connect.py --send-data HEX
--send-protocol 0x7c` 发送应用程序数据（`reliable4.build_data_message`，与游戏机自己的字节精确；五个静默接收检查：[版本 4](pia.md#version-4)）。通过信号：0x80 ack id 移1； 0x7C 完全确认。
<a id="the-ping-handshake"></a>
## ping 握手

一个 PBS 是一个四字节小端消息 id 和一个 protobuf 主体。一次握手包含这五个，而不包含其他（右列在一次捕获中对每个进行计数）：

    0x7C  61000000 0a00      97 SyncPingDataHolder, field 1 ping {}           x20
    0x7C  61000000 1200      97, field 2 pingReply {}                          x2
    0x7C  61000000 1a00      97, field 3 pingSynced {}                         x3
    0x7C  60ea0000 0a00      60000 BlockDataHolder, field 1 result {}          x2
                             (Result { bool isBlocking })
    0x80  60ea0000 12020801  60000, field 2 imReady { isReady: true }          x2
（`gflnet.p2p.sync.ping.pb`，`gflnet.p2p.block.pb`。）回答将分五个步骤进行游戏：

    1  answer the ping continuously   --send-data 610000000a00 --send-mirror --send-count N
    2  ack every reliable window      0x7C, 0x18 port 1, 0x80; one unacked window kills the mesh
    3  answer `result{}` on 0x7C      the mirror is per protocol
    4  answer imReady on 0x80         --send2-data 60ea000012020801
    5  the console sends its party on 0x84
- 必须连续应答 ping：一个答案就可以得到一个`pingReply`然后游戏恢复 ping 状态。
- A`pingReply`在游戏机要求停止其心跳之前发送。
-`imReady`已发送0x7C回答`result{}`画不0x84: 答案继续0x80。
- 延迟确认的消息被重新发送，并且可以在其后继消息之后到达（`pingReply`在序列 9 之后`pingSynced`10）。只有高于最新消息的序列才会替换当前消息；应答重新发送循环`pingReply`和`imReady`永远不会来。

`bin/swsh_connect.py --sync-answers` 在有规则的情况下回答 `trade.SYNC_ANSWERS`，在其他地方回显每个协议，并打印每个未规则的 VOC（在它引起的答案之后；读取所有者 ID）。
<a id="leaving"></a>
## 离开

离开交换会话的 剑 发送框命令 3，并在大约 0.77 秒后开始 Pia 离开其角色。每个步骤都会等待答复，如果没有答复，则会因超时而失败。

加入的 剑 留下主机：

|步骤|剑发送|主机欠 |未答复 |
|---|---|---|---|
|网状假| LEAVE_REQUEST `04 <own index>`，0x18 端口 1，可靠，一次 | LEAVE_RESPONSE `08 <host index>` | 5.0 秒 |
|车站断线| `03` on 0x14，每 0.5 秒 | `04` | 8 个请求，3.6 秒 |
| LDN |离开网络| | |

如果双方均未得到答复，剑（零售或模拟 盾）将在 LEAVE_REQUEST 后 9.0 至 9.1 秒离开 LDN 网络。当 `08 00` 发送两次且 `04` 应答时，零售剑在 LEAVE_REQUEST 0.04 秒后发送一个 `03` 并在其后 0.14 秒离开。

- 版本 4 主机处理程序 `0x017c19a0`（网格类型 4，表 `0x02081564`）通过 `0x017c2450` 发送 `08` 及其自己的索引，两个不可靠副本（`0x01851200` 的无捆绑标志为 0，然后为 1），并从网格。只有当 [1] 是网格主机的索引时，离开者的处理程序 `0x017c0d44` 才会接受它。
- 0x14处理程序`0x017c6110`（类型3，表`0x02081804`）向发送方应答一字节`04`并将其标记为消失；类型 4 处理程序 `0x017c5fcc` 清除离开者的等待。

`pokeldn/ldn/host4.py` 都回答了。

托管 剑 离开其客户端（它是 LDN 接入点）：

|步骤|剑发送|客户欠|未答复 |
|---|---|---|---|
|网格迁移| MIGRATION_START `44 00 01` ([主机迁移](swsh_trade.md#host-migration)) | MIGRATION_FINISH 和 UPDATE_MESH 命名为 主机，来自指定站 | 5.0 秒 |
|本地会话 |其更新会话（0x24 类型 0x11）具有主机迁移字节 1 和新的序列 id，大约每 0.11 秒 |该序列 ID 的 0x21 确认 | 10.0 秒 |
|破坏网络| START_HOST_MIGRATION `01 13 00..`（16 字节），每 0.33 秒 |离开LDN网络| 10.0 秒 |

在零售 剑 上测量，从 MIGRATION_START 到最后一个数据包：

|客户回答|网格步骤结束|最后一个数据包 |
|---|---|---|
|什么都没有（5 次捕获）| 5.0 秒 | 25.0 秒 |
| MIGRATION_FINISH 和 UPDATE_MESH 作为主机，重复 | 0.1 秒 | 20.1 秒 |
| MIGRATION_FINISH（确认），确认，离开 | 5.0 秒 | 5.07 秒 |
| MIGRATION_FINISH, UPDATE_MESH 作为主机，确认，离开 | 0.07 秒 | 0.17 秒 |

仅确认完成后，游戏机确认客户端数据 4.8 秒；与
UPDATE_MESH 启动后0.07秒安静。

- `LocalDestroyNetworkJob::WaitUntilAllClientsDisconnection` (`0x017acd70`) 计算网络连接的节点（`0x017a9b20`，八个插槽），并在仅保留主机时或 `0x2710` 毫秒后销毁它，每 `0x12d` 毫秒重新发送 START_HOST_MIGRATION （`0x017acbd0`、`0x017a8bb0`）。
-更新会话由`LocalResendMessageJob`重新发送；仅当其序列 ID 等于消息的 (`0x017aed10`) 时，确认（处理程序 `0x017a9250`，本地类型 0x21）才会清除发送方的位。二进制文件中 10.0 秒本地会话步骤的界限是未读的。
- START_HOST_MIGRATION 不携带任何序列（其串行器 `0x017abc60` 在 0xC 处写入 0）并且没有重新发送作业：没有任何内容对其进行确认。

`bin/swsh_connect.py --answer-migration --update-mesh --leave-with-host`（在 `--preset trade` 中）发送完成和 UPDATE_MESH 作为主机，确认主机迁移更新会话并在 START_HOST_MIGRATION 上离开网络。
<a id="operational-notes"></a>
## 操作注意事项

- 切勿现场通过`--verbose`；使用 `--capture FILE`。
- 游戏机的频道在会话之间发生变化（看到 1 和 6）；扫描保持最繁忙的状态（[通道](ldn.md#channels)）。
- `0x2D0`（分配在`0x006a970c`，`0x006a9740`）是会话单例的大小（`0x006b4410`，全局`main+0x02616758`），而不是720字节的神奇配置。
