
<a id="host-implementation"></a>
# 主机实现

`bin/frlg_trade_host.py` 是火红／叶绿直角领导者：交换机加入主机的 LDN 网络，Pia 建立对等会话，Reliable 携带模拟父节点 RFU 链路，以领导者端交换状态机结束。 `bin/frlg_mg_host.py` 重用活动下面的所有内容。

<a id="components-and-ownership"></a>
## 组件和所有权

|组件|拥有|
|---|---|
| `TradeRunConfig` |不可变的运行配置：`TrainerProfile`、`TradePlan`、`LdnConfig`、`HostOptions` 或 `JoinerOptions` |
| `HostApplication` |资源排序：验证、传输启动、信标注入、事件循环、中断、清理；活动挂钩提供消息和持久性，因此交换和神秘礼物共享循环 |
| `HostTransport` | LDN AP、虚拟接口、参与者事件、UDP：12345；没有 Pia 解析 |
| `HostPeerProtocol` |一个对等点的 Pia 状态：网络、会话接受、RTT、数据包 ID、随机数选择、加密、成帧、可靠批处理；发出 `OutboundDatagram` |
| `HostSession` |可靠+`RFULeader`+活动引擎（`engine=`挑选交换或神秘礼物）；无套接字，离线端到端测试使用的边界
| `HostTradeEngine` |领袖房间进入、队伍和卡牌交换、选择、确认、动画和保存障碍、取消、退出房间、关闭恩典； `HostTradeTiming` 命名帧数 |
| `BeaconInjector` |它的原始监视器套接字和工作线程|

数据报流开关，`HostTransport`，`HostPeerProtocol`，`HostSession`，`RFULeader`，
`HostTradeEngine`（子节点命令row in，父节点row out）然后返回。计时器截止时间来自对等协议，因此网络/会话重试、RTT 探测、重传和 ~59.727 Hz 滴答声不依赖于轮询延迟。

<a id="startup-and-session-establishment"></a>
## 启动和会话建立

1. CLI 将 `TradeRunConfig` 交给 `HostApplication`，这会启动不活动的 Direct Corner 网络和周期性信标。
2、Switch加入； `on_participant_joined()` 发送 Pia Net 连接请求，重试直至 ACK。
3. 交换机回复 Net ACK 和会话加入请求；主机发送会话更新和单播加入响应（诊断设置反转该对），并且交换机进行确认。
4. RTT 和 Reliable/RFU 流量启动，并且应用程序数据属性设置为活动。

格式错误的 Pia、错误的填充、身份验证失败、不完整的可靠平铺和不匹配的会话身份都会被记录并忽略。仅当会话请求的常量 id、Pia 变量、源 IP 和加密标头与当前 LDN 对等方一致时，会话请求才会被接受。

<a id="trade-and-room-exit-lifecycle"></a>
## 交换和退出房间的生命周期

```mermaid
stateDiagram-v2
    [*] --> PlayerExchange
    PlayerExchange --> RoomEntry: LinkPlayer and trainer card
    RoomEntry --> PartyExchange: seat route and entry barriers
    PartyExchange --> Selection: party, mail, ribbons
    Selection --> Confirmation: Switch selects; leader offers configured slot
    Confirmation --> Animation: both confirm
    Animation --> Save: trade committed
    Save --> PartyExchange: another configured trade
    Save --> MenuExit: final party refresh
    MenuExit --> RoomExit: both cancel; five-second field wait
    RoomExit --> CloseGrace: Switch confirms room exit
    CloseGrace --> Disconnect: fifteen seconds of peer traffic
    Disconnect --> [*]
```
 最后交换后主机等待Switch交换菜单；播放器选择“取消”并确认“是”，主机立即回答 `BOTH_CANCEL_TRADE`。主机完成备用屏障，在离开房间之前等待五秒，除非交换机先离开，并在交换机确认关闭（`READY_CLOSE_LINK`）后保持正常对等流量十五秒，然后将 RFU 断开排队。它用类型 4 应答游戏机的会话离开请求（[frlg_link.md](frlg_link.md)，离开 Pia 会话）。 LDN 离开事件立即停止对等输出。

<a id="shutdown-and-cleanup"></a>
## 关闭和清理

断开连接后：保存收到的宝可梦（如果存在），停止并加入信标工作器，关闭套接字和网络，清理LDN vifs。相同的清理工作在正常完成时运行，
`KeyboardInterrupt`，部分分配后启动失败，beacon-worker失败。保存收到的宝可梦与捕获日志无关。

每个主机、交换、战斗和神秘礼物都会在游戏机离开 LDN (`HostApplication.run`) 时停止：在未确认结束时立即停止，在 2 秒后结束 (`HOST_CLOSE_SETTLE_SECONDS`) 时结束。 `--end-on-success` 一旦成功发送断开连接，就停止神秘礼物主机，无需等待游戏机离开；在没有 Switch 流量的情况下，它的 `--idle-timeout` 会在几秒后停止它。

<a id="trainer-profile-propagation"></a>
## 训练家档案传播

`pokeldn.config.DEFAULT_TRAINER` 是默认身份。每个 CLI 都会派生出一个不可变的每次运行
`TrainerProfile`（`--ot`、`--version`、十进制 `--id TID[:SID]`），验证 Gen III 名称和范围，并从中派生每个视图：

|查看 |携带 |
|---|---|
| LDN 发现 |名称和公共 TID |
|皮亚会议 | UTF-8 参与者姓名 |
|链接播放器 | `SID << 16 \| TID`，版本、语言、性别和进度标志；第三代名称 |
|训练家卡|第三代名称；主机垫带有 `0xFF`，连接器保留原生 `0x00` |

<a id="failure-handling"></a>
## 失败处理

- 预检拒绝不支持 AP 的无线设备。
- Linux Wi-Fi 网卡在 LDN 身份验证后，必须为站点设置 `NL80211_STA_FLAG_AUTHORIZED`。驱动配置和标志见[适配器](hardware_adapters.md)。
- 传输或信标线程故障会中止运行，并清理已创建的资源。
- 参与者意外离开会停止输出。房间关闭已确认后，参与者从 LDN 消失会触发 2 秒稳定等待（`HOST_CLOSE_SETTLE_SECONDS`），随后结束运行；只有参与者仍在网络中时，十五秒宽限期才会完整执行。
- 宽限期（`HostTradeTiming.post_client_close_grace_frames`）仅在 RFU 主机处于 UNI 状态时计时；游戏机的 `D` 将其转为 DISCONNECTED（`pokeldn/gba/rfu_leader.py`），引擎随即停止更新。13 次实机《火红》主机交换中，游戏机在首次 `READY_CLOSE_LINK` 后 0.1 秒发送 `D`，继续回复 Pia 传输，并于 0.5 至 4.0 秒后离开 LDN，因此正常关闭不会用到宽限期。
- 仅在收到完整宝可梦数据时写入输出；输入 `.pk3`/`.ek3` 文件始终不修改。

<a id="extending-the-host"></a>
## 扩展主机

在理解它的最低层添加行为：运行配置中的设置、应用程序或传输中的操作系统和网络、`HostPeerProtocol` 中的 Pia、`RFULeader` 中的 RFU、`HostTradeEngine` 中的 Direct Corner 决策。测试其发出的数据报、有效负载、帧或命令行的每个边界。

主机服务于一台交换机。更多的peer每个需要一个`HostPeerProtocol`（自己的Pia变量，nonce，数据包id）和一个游戏级的RFU策略；提高 LDN 参与者限制还不够。

<a id="source-map"></a>
## 源图

|来源 |责任|
|---|---|
| `bin/frlg_trade_host.py` | CLI、配置、入口点 |
| `pokeldn/frlg/host_cli.py` |共享主机 CLI 选项 |
| `pokeldn/frlg/link/host_app.py` | `HostApplication` |
| `pokeldn/frlg/config.py` |训练家、交换计划、神秘礼物发票、LDN、角色和运行配置 |
| `pokeldn/frlg/link/trade_runtime.py` | CLI 日志记录、队列加载、槽解析、输出保存 |
| `pokeldn/frlg/link/host_beacon.py` |捕获交换信标，发现突变，`BeaconInjector` |
| `pokeldn/host_support.py` |面向操作系统的支持（sudo 感知键路径解析）|
| `pokeldn/ldn/transport.py` | `HostTransport` |
| `pokeldn/ldn/host_pia.py` | Pia 框架，`HostPeerProtocol` |
| `pokeldn/frlg/link/host_session.py` | `HostSession` |
| `pokeldn/ldn/reliable.py` |可靠|
| `pokeldn/gba/rfu_leader.py` | `RFULeader`: 父节点分帧、NI/UNI 握手、回显表 |
| `pokeldn/frlg/link/host_trade.py` | `HostTradeEngine`，`HostTradeTiming` |
| `pokeldn/frlg/link/linkplayer.py` | LinkPlayer 和训练卡编码器 |
| `pokeldn/ldn/ldntrace.py` |可选 JSONL 诊断 |
