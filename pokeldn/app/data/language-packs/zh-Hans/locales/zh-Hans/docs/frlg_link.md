
<a id="the-gba-link-and-what-runs-on-it"></a>
# GBA 链接及其上运行的内容

在实机硬件上测量或从 [pret/pokefirered](https://github.com/pret/pokefirered) 中读取。
<a id="the-rfu-link-layer"></a>
# RFU链路层
<a id="one-child-slot-per-parent-poll"></a>
## 每个父节点轮询一个子节点槽

`RfuMain2_Parent` 每次轮询在 `gRfu.childRecvBuffer[i]` 中保留一个子节点槽并检查其滚动情况
`childSendCmdId`标签是最后保留的`+1 mod 8` [link_rfu_2.c:876-892]。坏标签会增加
`numChildRecvErrors[i]`; `> 4` 调用 `RfuSetErrorParams` 并杀死链接；一个好的标签会重置它，所以死亡需要连续五次错误的民意调查。一次民意调查中的第二个位置是已删除的标签。根据走进交换室的零售火红测量，按排放率计算：

| 子节点排放 |游戏机停止投票|
|---|---|
|自由运行（~57/s 对比它的~55/s）|步行开始后 0.10 秒 |
|每次投票 2 个席位 |步行开始后 0.28 秒 |
|每次投票 1 个位置 |步行开始后 5.8 秒 |

在每次轮询的一个槽中，每个标签都是有序的，并且 `numChildRecvErrors` 永远不会递增；以该速度步行到达座位，因此 5.8 秒的停止并非来自标签检查。

没有什么是可以豁免的，包括座位行走。
<a id="row-one-of-the-parents-table-is-the-consoles-own-command-mirrored-back"></a>
## 父节点的表第一行是游戏机自己的命令，镜像回来

该规则适用于游戏机在任何活动中发送时的每个停顿。

`MGL_Send` 块大小为 252 字节，并在每个块之前和末尾等待 `MGL_HasReceived(link->sendPlayerId)` [mystery_gift_link.c:176,205]。 `sendPlayerId`是游戏机自己的id 1
[mystery_gift_client.c:33]，所以它会等到自己的块通过父节点`gRecvCmds`的第一行完整返回，复制主机镜像。 `RfuHandleReceiveCommand`为每个玩家重新组装块，包括子节点本身[link_rfu_2.c:1125]，并且`RfuMain1_Child`从父节点的表中填充`gRecvCmds`，其自己的行包括[:970]。

RFU块发送方等待同一个镜像：`HandleBlockSend`持有INIT直到它看到它被镜像，`SendLastBlock`重复最后一个片段直到镜像，然后重新排队镜像位掩码[HandleSendFailure, link_rfu_2.c:1366-1416]中丢失的每个片段。游戏机无法命名丢失的片段；它会重新发送所有内容。

`rfu_leader.ChildEcho` 遵循两条规则：

- 切勿删除不同的命令；掉落的碎片是盲修轮。有界回显队列会从突发中丢弃命令（21 片段块溢出两个条目界限）；然后游戏机重复整个块，第二次丢失以链路丢失结束。
- 合并仍在等待的重复（`SendLastBlock` 重新发送每一帧）；一项就足够了。镜子熄灭后的重复是一个新问题并得到了解答。

子节点每收到一个父节点帧就发送一个命令（`childSendCount` 仅在
`recv.newDataFlag` [link_rfu_2.c:600]），因此镜像队列无法自行增长。
<a id="a-tile-step-is-exactly-16-link-updates"></a>
## 一个图块步骤正好是 16 次链接更新

`FacingHandler_DpadMovement` 套 `objEvent->directionSequenceIndex = 16`；
`MovementStatusHandler_TryAdvanceScript` 每次链接更新时递减一次，同时忽略密钥 (`MOVEMENT_MODE_FROZEN`) [overworld.c:3432-3470]。连续运行 N 个方向键会留下 `N mod 16` 的最后一步，因此脚本化行走的间隙只需要更新 `16 - (N mod 16)` ；超调每次更新都会花费一个槽位，仅此而已。
<a id="the-players-inputs-are-not-always-transmitted"></a>
## 玩家的输入并不总是被传输

`UpdateHeldKeyCode` 每当时将 EMPTY、四个 DPAD 代码、START 和 A 重写为 `LINK_KEY_CODE_NULL`
`GetLinkSendQueueLength() > 1` [overworld.c:2786-2810] 和 `SendKeysToRfu` 不发送任何内容：在队列压力下行走的玩家看起来像是停着的。 `LINK_KEY_CODE_READY` (0x16) 是豁免的，因此 0x16 上的门永远不会缺少 DPAD 代码。
<a id="the-seat-is-a-mutual-barrier"></a>
## 座位是相互的屏障

`Task_EnterCableClubSeat` 显示“请稍候”，调用 `SetInCableClubSeat()`（下一个保持键发射变为 `LINK_KEY_CODE_READY`），然后在 `GetCableClubPartnersReady()` 上旋转
[cable_club.c:827-869]，仅当 `AreAllPlayersInLinkState(PLAYER_LINK_STATE_READY)` 时才成功
[overworld.c:2988-2999]。然后 `Task_StartWirelessTrade` 运行 `SetLinkStandbyCallback()`
[cable_club.c:910-943]，后座备用轮的来源。仅当两名玩家都准备好后才驾驶；在仍然处于 `CABLE_SEAT_WAITING` 状态的游戏机上驾驶它们会导致其座椅状态机出现故障。
<a id="what-a-real-child-sends-end-to-end"></a>
## 真正的子节点发送的是什么，端到端

零售法语版《火红》作为子节点对抗主机。顺序是由协议固定的； IDLE 计数来自一次交换：

```
IDLE x8
SEND_BLOCK_INIT w1=0x0011 x4   + 17 fragments      (LinkPlayer, 0x11 = 17)
IDLE x31
SEND_BLOCK_INIT w1=0x0009 x4   + 9 fragments       (trainer card)
IDLE x262   READY_EXIT_STANDBY w1=0x0000 x1
IDLE x72    READY_EXIT_STANDBY w1=0x0001 x1
IDLE x45    <room: SEND_HELD_KEYS 0x1b x24, EMPTY, 0x1a once, the walk, READY, then EMPTY x13>
IDLE x22    READY_EXIT_STANDBY w1=0x0002 x1
IDLE x28    READY_EXIT_STANDBY w1=0x0003 x1
IDLE x75    -> the host pulls the party
```

- 每个待机轮都是一帧，由 Pia Reliable 重新传输，直到落地。重复计数显示主机已经完成一轮。
- 在两轮之间，子节点完全空闲（全零 `gSendCmd`）。在队列交换之前，领导者的安静帧计数器仅在完全空闲的时隙上前进，因此 EMPTY keepalive 会使其陷入僵局。
- 房间负载前缀（`0x1b` = HANDLE_RECV_QUEUE ×24，则 `0x1a` = IDLE）是队列管理。   `LINK_KEY_CODE_IDLE` 在对等体 [overworld.c:2755] 上设置 `sPlayerLinkStates[player] = IDLE`，并且 `HandleLinkPlayerKeyInput` 仅为处于 IDLE 状态的玩家运行图块脚本。
<a id="both-sides-advance-only-when-they-have-heard-from-the-peer"></a>
## 双方只有在听到对方的消息后才能前进

`CB1_UpdateLinkState` 仅在 `!IsRfuRecvQueueEmpty()` 时运行 `UpdateAllLinkPlayers`，如果任何 `gRecvCmds` 条目非零 [link_rfu_2.c:787-800]，则返回 FALSE。 `MoveSendCmdToRecv`将父节点自己的`gSendCmd`复制到`gRecvCmds[0]`中，这样父节点就可以自我维持；实际上，循环会变成每次往返一次交换。

主机的 `SEND_HELD_KEYS` 的高字节是 `heldKeyCount`，每个准备好的命令一个，因此最后一个值计算链路更新其幸存的交换室。
<a id="post-seat-standby-gate-and-walk-out"></a>
## 座位后备用门和走出去

双方坐下后，游戏机在反映主机后在 mpId 0 处广播自己的 `READY_EXIT_STANDBY` count=2（在录制的交换中 130 毫秒后）。仅当子节点计数等于其自身时，它才接受子节点计数（`Rfu_LinkStandby` recv 门，link_rfu_2.c:1577-1591），因此在主机的 count=2 反射上发送的 count=3 被忽略；反射只能证明父节点看到了槽。主机自己的 mp0 计数=2 上的门计数=3 并继续重新布防，间隔超过主机之前的安静窗口
`BufferTradeParties`（`HostTradeTiming.entry_final_standby_quiet_frames`，75个槽，比子节点60帧重发的`READY_EXIT_STANDBY` [link_rfu_2.c:1529]长）。

退出：主机发出 `LINK_KEY_CODE_EXIT_ROOM` (0x17) 并阻止
`KeyInterCB_WaitForPlayersToExit` 直至 `AreAllPlayersInLinkState(EXITING_ROOM)`
[overworld.c:2962-2981]。子节点必须在持有密钥流上用自己的 0x17 进行应答；全零的槽不是键。
<a id="leaving-the-room"></a>
## 离开房间

游戏机玩家在入座前或对战后离开交换中心时，会发送按键 `0x17`（EXITING_ROOM），并停在“请稍候”，直到所有玩家均发送该值 [KeyInterCB_WaitForPlayersToExit, overworld.c:2977]。主机会在 `H_ENTRY_SEAT`、`H_RETURN_FIELD` 及对战状态中回复自己的 `0x17`（`host_trade._child_send_held_keys`）。实机火红在主机仍走向座位时离开，会一直等待，直到 `H_ENTRY_SEAT` 也作出回应。

<a id="quiet-gate"></a>
### 静默门限

游戏机连续 `QUIET_GATE_SECONDS`（0.25 秒）未发送数据时，主机会抑制自身重传，但每 `QUIET_RETRANSMIT_SECONDS`（1 秒）仍发送一次，确保正在等待被主机空洞保护（`HOST_OUTSTANDING_MAX`）阻挡的帧的游戏机仍能收到该帧（`tests/test_host_quiet_gate.py`）。

<a id="cancel-after-a-trade"></a>
## 交换后取消

`BufferTradeParties` 在礼品奖章交换后清除收到的块标志
[trade.c:1549]，在`Leader_ReadLinkBuffer`读取菜单命令之前[1593-1633]。在设置合作伙伴的选择之前，可以清除在该交换期间完成的取消请求。领导者自己的 `REQUEST_CANCEL` (`0xEEAA`) 证明它正在处理 Cancel 输入 [2049]。 `bin/frlg_trade_join.py`，一旦其配置的交易完成并选择取消，当领导者到达时再次发送其 `REQUEST_CANCEL` (`pokeldn/frlg/link/trade.py`，
`_on_linkcmd`）。
`BOTH_CANCEL_TRADE` 在退出待机轮次之前清除任何挂起的请求。

跟随者在 YES 后从其实时菜单发送 `REQUEST_CANCEL`，打印“等待朋友”并空闲直到 `BOTH_CANCEL_TRADE` [trade.c:2049, 1643]；领导者的玩家在读到它时选择取消答案[1715-1722]。主机立即在最终菜单中回答游戏机的`REQUEST_CANCEL`。
<a id="one-sided-cancel-returns-both-sides-to-the-menu"></a>
## 单侧取消将两侧返回菜单

`PLAYER_CANCEL_TRADE` / `PARTNER_CANCEL_TRADE` 遍历 `CB_HandleTradeCanceled` → `CB_MAIN_MENU`
[trade.c:2094-2113];只有`BOTH_CANCEL_TRADE`结束会话[1715-1722]。方加入重新进入
S4_PARTY并在60帧后再次选择。用 `PARTNER_CANCEL_TRADE` 回答 `REQUEST_CANCEL` 会循环游戏机“votre ami veut échanger des 宝可梦”； `bin/frlg_trade_host.py` 用 `BOTH_CANCEL_TRADE`（退出路径）回答第一个。领导者自己的选择不发送任何内容（`SetReadyToTrade`
[trade.c:1811-1828]);每位玩家的取消信息为 `REQUEST_CANCEL` [trade.c:2049]。首先发送 `READY_TO_TRADE` 的方加入会在领导者第一次取消时绘制 `PLAYER_CANCEL_TRADE`；
`bin/frlg_trade_join.py` 然后在菜单中取消，因此领导者的第二次取消会结束会话。
<a id="version-and-language-on-the-link"></a>
## 连接中的版本与语言

`IsTryingToTradeAcrossVersionTooSoon` [union_room.c:1499] 仅对既不是《火红》也不是《叶绿》的伙伴触发，并显示消息而不断开连接；《火红》与《叶绿》之间的交换已在实机上验证。`ConvertInternationalString` 对日语名称作特殊处理；法语版《火红》可以接收英语神奇卡片。联合房间的 `Task_SearchForChildOrParent` 会跳过日语候选者 [union_room.c:3726]。神秘礼物使用 `Task_ListenForCompatiblePartners`，其玩家兼容性检查依据序列号和广播名称标志，不采用该语言过滤器。日语版卡带为神奇卡片和神奇新闻接受的活动编号与其他语言版本不同（见[日语版布局](frlg_rom_map.md#japanese-layout)）。

玩家在神秘礼物的“朋友”列表中选择 pokeldn 后，主机会在 GameData 中发送 ROM 游戏代码。主持端在传送前选择对应卡带的地址和卡片布局。GUI 在基础页面的版本旁显示自动检测到的语言。

<a id="the-emulator-can-close-the-link-on-its-own"></a>
## 模拟器可以自行关闭链接

`HandleLinkConnection` 仅在 Switch 版本 [link.c:1654] 上运行 `svc_51`：

    #if REVISION >= 0xA
        if (svc_51())
        {
            ...
            CloseLink();
        }
    #endif

`svc_51` (`swi 0x51`) 由模拟器 [sloopsvc.c:120] 应答。非零表示 `CloseLink()`，然后 `Task_MysteryGift` 下的 `RfuSoftReset()`，否则 `RfuReloadSave()` [link.c:1674]：切换错误 2318-0006。在 RFU 级别上主机干净的死亡指向 LDN/Pia。

| SVC |致电 |它是做什么的 |
|---|---|---|
| `swi 0x45` | librfu_rfu.c:667,749 |手中的模拟器`gRfuLinkStatus` |
| `swi 0x49` | AgbRfu_LinkManager.c:657 | 非零时，在 SEARCH_CHILD 期间保持 `connect_period` 开启 |
| `swi 0x4a` | AgbRfu_LinkManager.c:720 | 同上，作用于 SEARCH_PARENT 期间 |
| `swi 0x4b` | link_rfu_2.c:2114、union_room_player_avatar.c:518 | `SVC4B_EXIT_EARLY` 退出 SpawnGroupLeader； `SVC4B_RESEED_RNG` 从主机训练家 ID 重新播种 |
| `swi 0x51` |链接.c:1654 |现在关闭链接（在神秘礼物下软重置） |
| `swi 0x53` | wireless_communication_status_screen.c:328 |模拟器驱动退出状态屏幕|
<a id="the-wireless-layer-as-this-game-exercises-it"></a>
# 无线层，正如这个游戏所练习的那样
<a id="the-advertised-rate-set"></a>
## 广告费率设置

没有 6、9 和 12 Mbit/s 的关联响应使得游戏机在关联后 2.9 至 3.9 秒、Pia 会话完成后、在任何链路阶段离开 LDN 网络：76 个这样的第一个关联中有 42 个留下，而具有这些速率的 284 个关联中有 0 个留下。缺少 Pia 类型 2 Join Response 同时给出休假（[游戏机作为 Pia 子节点](#the-console-as-a-pia-child)）。从托管的火红和叶绿会话的 360 个空中捕获中，每次运行的第一个关联与游戏机是否在 6 秒内离开：

|协会回应|灯塔| 游戏机的关联请求 |还剩 3 秒 |留下来 |
|---|---|---|---|---|
| 启用 6、9、12 | 启用 | 启用 | 0 | 139 |
| 启用 6、9、12 | 启用 | 未启用 | 0 | 84 |
| 启用 6、9、12 | 未启用 | 启用 | 0 | 26 |
| 启用 6、9、12 | 未启用 | 未启用 | 0 | 35 |
| 未启用 | 未启用 | 未启用 | 42 | 34 |

仅交替设置响应的速率：20 个中的 0 个保留速率，8 个中的 4 个不保留速率。失败集是`1B 2B 5.5B 11B 18 24 36 54`（编号为6、9、12、48）；游戏机需要四个中的哪一个尚不清楚。 ESP32 softAP 的关联响应携带所有 12 个速率（[hardware_esp32.md](hardware_esp32.md)，接入点的帧）。

主机通告交换机速率集（1B 2B 5.5B 11B 6 9 12 18，扩展24 36 48 54）。不需要 Switch 的其他元素（DTIM 2、ERP、功能 0x411、Nintendo 供应商元素、HT/HE、WMM）。游戏机根据信标构建其关联请求的速率，因此信标头携带元素 0 (SSID)、1 (支持的速率) 和 3 (DS 参数)，这是一个 41 字节的子集。携带 WMM 的信标使游戏机发送 QoS 数据帧（子类型 8），主机必须对其进行解码；供应商的 LDN 解码器将 TID 放入 CCMP 随机数和 AAD 中。 `host_pia` 单播类型 5 更新会话。在保密能力下没有RSN的探测响应使得游戏机的关联请求得不到答复。
<a id="the-console-as-a-pia-child"></a>
## 游戏机作为 Pia 子节点

- 游戏机子节点需要类型 2 的加入响应：仅在类型 5 上，它每 0.5 秒重新发送其加入请求，忽略单播类型 5 副本，并在加入后约 3 秒（测量为 3.05-3.20 秒）离开网络，与短速率集相同的症状。
- 托管神秘礼物的游戏机在其网络 0x11 的 50-66 毫秒内回答类型 5 的游戏机子节点。   它回答 `bin/frlg_mg_client.py`，没有类型 2，2.0 秒后回答类型 5；加入请求的哪个字段导致差异未知。托管交换的游戏机在 34 毫秒内发送类型 5 和类型 2，RTT 仅在最终确定后发送。

从托管神秘礼物的游戏机到接收客户端的序列，来自其网络 0x11：

    0.000  Net 0x11 (once)
    0.006  client: Net 0x12 + Session join
    0.252  RTT request, then every 316ms (6 probes, nothing else)
    2.038  Session type 5, no type 2 ever
    2.040  client: type 6 (finalize); 2.159 reliable open
    2.318  host 'A' frame
    4.63   host's own NI (join status = the player's YES on the console)
    6.82   SEND_PLAYER_IDS, 6.87 BLOCK_REQ (2.2s after the YES)
    8.15   Net 0x50 property update every ~0.5s, acked 0x51

<a id="leaving-the-pia-session"></a>
## 离开 Pia 会话

游戏机子节点在其 RFU `D` 帧之后分三步离开：暂停、Session type-3 离开请求、然后其 LDN 解除认证（原因 3）。测量了超过 33 个托管交换和神秘礼物捕获，没有 4 类答案：

|间隔|测量|
|---|---|
| `D` 第3型 | 1.97-2.02 秒 |
|类型 3 到类型 3，四次发送 | 0.48-0.54 秒 |
|首先键入 3 向 LDN 离开 | 2.03-2.08 秒 |
| `D` 向LDN 离开| 4.02-4.08 秒 |

    type 3, 22 bytes:  03 | random u32 | constant id (8) | variable id (2) | kind 0 | IPv4 | port
    type 4, 15 bytes:  04 | random u32 | the request's constant id and variable id
 偏移量位于 GBA 应用程序的 `main` 中，从图像开始。 `LeaveMeshJob` 发送请求于
`0xcacf4` 的截止时间为 500 毫秒，`WaitLeaveResponse` (`0xcaf38`) 在作业的响应标志 `+0x99` 处结束，或者在每个截止时间重新发送，而其计数为 2 或更少 (`0xcb06c`..
`0xcb08c`)：四次发送，然后作业完成，站点离开网络。会话调度程序的类型 4 情况（`0xba028`，表 `0x180fc9`）为 15 字节消息设置该标志，该消息的常量 id 为 5，变量 id 为 13 是该站自己的。主机的类型 3 处理程序 (`0xbf2d4`) 占用 22 或 34 个字节（类型 1 携带 18 个地址字节，`0xbf3ac`）并应答 15 个字节：类型 4，一个新的随机字，请求的字节 5 到 14 (`0xbf454`..`0xbf4e4`)。主机以该形式 (`pokeldn.ldn.host_pia.HostPeerProtocol`)、单播、标头回答每种类型 3
`(console variable, 0x00C6)`，在发往该游戏机的其他单播数据包的计数器上编号。零售火红在来自同一站的编号为 6203 的单播数据包之后忽略了编号为 560 至 573 的四个类型 4（所有四个类型 3 均已发送，在第一个之后留下 2.05 秒）。在单播计数器上编号，第一个类型 4 被采用（一个类型 3，LDN 在其后留下 0.07 秒）。游戏机自己的数据包针对每个目的地携带一个计数器（到主机变量和变量 1）。

第一种类型 3 之前的暂停是 GBA 应用程序网络管理器中固定的 120 滴答倒计时，与主机无关。管理器每秒计数 60 个滴答（其超时与滴答计数器相比）
`+0x2774` 反对秒乘以 60，`0x4ff64`）。子节点的`TryDisconnectRfu`在其`rfu_REQ_disconnect`发送`D` [link_rfu_2.c:1446-1455, 983-985]之前发布`swi 0x44`； `LinkRfu_Shutdown` 也发出[link_rfu_2.c:625]。其处理程序 `0x58b0c` 通过管理器的槽 `0x68`（`0x53d98` -> `0x4f0ec`，字段 `+0x730`）发布断开连接请求 1。每提议更新 `0x4ee34` 将请求 1 转换为倒计时 `+0x734 = 0x78` (`0x4ef00`)，每个提议递减一次，并在零时调用管理器的槽 `0x78` (`0x4ef60`；子类 `0x53328`将状态设置为 1 通过
`0x4f0b4`）。下一个更新（`0x5392c` -> `0x536f0`）调用`Session::LeaveAsync`（`0xb1060`，位于
`0x537e0`），离开作业的第一步发送类型 3（[pia.md](pia.md)，离开会话）。

从网络收到的任何信息都不会缩短倒计时。仅在断开请求 2 或 3（`swi 0x42` 或带有零 PID 的 `swi 0x43`）或 Pia 错误或超时设置断开原因 `+0x277c`（首先在 `0x4ee64` 中检查；通过 `0x4f020` 设置）时提前结束`0x5110c`，
`0x52470` 和 `0x53440`）。倒计时代码没有角色检查。
<a id="behaviour"></a>
## 802.11 行为

- 控制台作为站：不省电（PM 位始终为 0），每个数据帧之前进行 RTS。当它离开时，它会发送一个取消身份验证，前面没有探测或空帧。
- 交换机主机在 11M 处发出信标并在 48-54M 处发送数据。
<a id="the-pia-header-nonce-is-a-counter-the-console-enforces"></a>
## Pia 标头随机数是游戏机强制执行的计数器

游戏机保留每个通道最后接受的 8 字节标头随机数（大端）并丢弃任何不严格位于其之上的数据报，因此随机随机数大约有一半的时间通过：

    random nonce:   ~1.1 duplicate outgoing reliable deliveries per unique frame, ~0.3 inbound
    counter nonce:  0.34 outgoing, 0.00 inbound

`Sim._next_nonce` 和主机都算。
<a id="carry-forward"></a>
## 结转

每个可靠帧都会在接下来的 4 个数据报中重复，并在原始帧后约 17 毫秒进行确认。空气损耗为 1-2%，并且是突发性的（游戏机自身的重传率为每帧 0.01-0.02），Pia 按顺序传送，并且一个孔保留每个后面的时隙，直到其重传，然后将它们一起传送并溢出游戏机的 8 深 RFU 接收队列。进位0时，一个丢失的父节点时隙及其68毫秒重传一次将十个时隙放入游戏机，并在300毫秒后断开连接。主机按顺序去重。
<a id="the-consoles-acknowledgement-lag-is-a-512-ms-metronome"></a>
## 游戏机的确认延迟是 512 毫秒节拍器

游戏机的累积确认位于 CTRL 帧中（`parse_bulk_ack`）；可靠标头的 `ack` 字段是发送者自己的最低待处理序列。

游戏机一次停顿 50-70 毫秒：相对于 15 毫秒基线，入站停止 35-70 毫秒，它重新传输自己的最后帧，然后其累积确认会跳过几帧：

    26.553 in   D1849 D1850 ACK next=919
    26.587 OUT  D919 D920 ACK next=1851
    26.617 in   D1849* D1850*        (retransmits, no ack)
    26.653 in   ACK next=924         (catches up five frames at once)
 两个卡带和三个活动上有超过 42 个间隔，每个周期是 16 毫秒（一帧）内的 512 毫秒时隙的整数个。观察到的计数为 16 和 17 个槽位，其中一个 18 个槽位和一个 33 个槽位跳过了一个刻度。网格锁相至 LDN 连接：103 秒内有 12 个停顿，相位跨度为 18 毫秒。在空闲聊天链接上，未完成计数达到 5，无害；在神秘礼物或交换负载下，摊位会出现在完整的发送窗口上。 ROM没有512ms的tick，所以定时器属于模拟器或者Pia/LDN层；它是什么仍然未知。
<a id="the-ident-25-stall-a-hole-plus-an-unbounded-backlog"></a>
## ident-25 停滞：一个漏洞加上无限的积压

游戏机可以在最后一个传送脚本块（ident 25，`MG_LINKID_RAM_SCRIPT`）之后进入空闲状态，从不发送ident 20（READY_END），然后离开。父节点块永远不会被反射，因此丢失的片段在捕获中是不可见的。

当无界积压后面的漏洞关闭时，游戏机立即将每个保留的帧交给游戏，其 8 深的 RFU 队列会丢弃 ident-25 片段，并保持连接状态“传输...”。在一次测量的停顿中，连续两帧丢失，累计确认停顿 1.75 秒，而主机在每个数据报（大约 100 份）中重新发送它们，并在每个数据报中添加 5 个新帧，在一个数据报中有 97 帧到达游戏，游戏机保持“传输...”状态 150 秒。 99% 的 ack 时，正常的 ack 延迟为 0-1 帧。

`HostSession` 持有新帧，而 `HOST_OUTSTANDING_MAX` (6) 帧未被确认，不断重传间隙，并在 ack 赶上时恢复，因此封闭的孔最多释放 6 个。
`--ram-script-block-repeat 3` 发送 ident-25 块 3 次：已发送 5 个会话中的 5 个。与
`--block-repeat 1`，测量的一个叶绿会话在 ident 25 处停止。是否是空气损耗或游戏机的 RFU 到游戏切换导致碎片掉落尚不清楚。
<a id="transmission-phase-deaths-after-the-card"></a>
## 传送阶段死亡卡后

传输停滞 250 毫秒到 3 秒，然后没有确认，然后每个未确认的帧都会重新发送卡后的每个蜱虫杀死会话：主机 UDP 输出峰值为每 0.25 秒 52-519 个数据报，而完成的会话中为 23-36 个数据报。主机的守卫，默认全部开启：

- `HOST_RTX_LIMIT` 限制每个 VBlank 的可靠重传。
- `FRLG_ECHO_MAX` 限制子节点块槽的 FIFO 回显。
- 传输套接字是非阻塞的，并且 `FRLG_QUIET_GATE_MS` 在游戏机静音时保持重传和结转（接受卡后约 0.5 秒，其闪存保存；那里的阻塞发送冻结了主机 6-11 秒）。
<a id="datagrams-held-between-the-socket-and-the-air"></a>
## 套接字和空气之间保存的数据报

播出前 0.1-1.1 秒保存的主机数据报（在一场实测战斗中，以 200 毫秒内 71 帧的突发形式发布）足够长，足以让游戏采取链路丢失路径并显示“erreur de connexion，rapprochez-vous”[link_rfu_2.c:2312 → CB2_PrintErrorMessage, link.c:1521]。在 ESP32 板上，在板的传输队列（[ESP32 radio](hardware_esp32.md)、TX_DONE）中，四个火红交易的最长套接字到确认等待时间为 265 毫秒。
<a id="the-union-room"></a>
# 联合房间
<a id="getting-listed-the-advertised-activity-byte"></a>
## 列出：广告活动字节

仅当其广告活动位于其搜索的链接组的接受列表中时，搜索游戏机才会保留候选者[`IsPartnerActivityAcceptable`，union_room.c:1590； `sAcceptedActivityIds`，src/data/union_room.h:398-456];大多数列表都拥有一个 id。联合房间里的游戏机打广告
`ACTIVITY_SEARCH` (12) 并搜索 `LINK_GROUP_UNION_ROOM_INIT`，列出 `{ACTIVITY_SEARCH, 0xFF}` [src/data/union_room.h:419]，所以交换主机 (`ACTIVITY_TRADE`, 4) 或神秘礼物主机(`ACTIVITY_WONDER_CARD`, 21) 被该字节单独过滤掉。房间内的搜索是
`LINK_GROUP_UNION_ROOM_RESUME` [union_room.c:2664]：`IN_UNION_ROOM | activity`、`IN_UNION_ROOM = 1 << 6` [包括/常量/union_room.h:49]。

记录字节 16 是活动：21 列出 Wonder Cards 屏幕上的主机，22 列出神奇新闻屏幕上的主机，其中游戏机加入并完成会话。
<a id="the-connect-inunionroom-exactly-and-alone"></a>
## 连接：IN_UNION_ROOM，完全独立

`IsPartnerActivityIncompatible` [src/link_rfu_2.c:2925] 测试

    else if (partner->activity != IN_UNION_ROOM)   // [link_rfu_2.c:2933]
        return TRUE;
 完全相等。 `IN_UNION_ROOM | ACTIVITY_TRADE` (0x44) 生成头像，但与其交谈会打印“Communication avec POKELDN”，然后打印“le DRESSEUR est ocupé”，空中没有数据包：`Task_TryConnectToUnionRoomParent` [link_rfu_2.c:2963] 内部的连接被拒绝。交换意图存在于
`sPlayerCurrActivity`，链路up后协商。裸机 `IN_UNION_ROOM` (0x40) 连接。化身实时跟踪信标：当主机重新启动时，它会走出并返回。
<a id="no-parent-ni-and-the-five-frame-rule"></a>
## 无父节点NI，以及五框规则

联合房间子节点期望没有父节点 join-status NI: 一旦它的名字 NI 成功
[AgbRfu_LinkManager.c:1203]、`LinkManagerCB_UnionRoom` [link_rfu_2.c:2526] 设置 TYPE_UNI 接收缓冲区，从不 TYPE_NI，并且 `Task_UnionRoomListen` [link_rfu_2.c:533] 启动 `Task_PlayerExchange`
MODE_CHILD。只有交换中心回调[link_rfu_2.c:2364]添加了TYPE_NI缓冲区。

NI 的身体是致命的。 `rfu_STC_NI_receive` 采用 LCOM_NI_START 没有游戏缓冲区
[librfu_rfu.c:2202]，但身体需要一个：`rfu_STC_NI_initSlot_asRecvDataEntity` 失败并显示
ERR_RECV_BUFF_OVER [librfu_rfu.c:2300] → `recvErrorFlag` → REQ 错误 → `LMAN_MSG_REQ_API_ERROR` →
`RfuSetErrorParams` →“连接错误，请恢复正常”[link_rfu_2.c:2585]。
`RFULeader(skip_parent_ni=True)`，由`--union-room`启用，跳过它。

游戏机在未应答的第五个父节点帧上断开连接（三个捕获一致）：

    child NULL 28.361  host NI ts=8..12, K only   D 28.496   (NI_STARTs ts=6,7 were mirrored)
    child NULL 34.069  host NI ts=8..12, K only   D 34.199
    child NULL 36.527  host UNI ts=6..10, K only  D 36.628
 来自子节点的NULL：135/130/101 ms，其缺少的两个镜像的前三两帧，匹配`maxMFrame = 4` [link_rfu_2.c:128]。 完成的交换中心捕获最多显示两个。

`--union-room-keepalive N`（120作品）代表了UNI之前N个VBlanks的第一个父节点NI_START，因此游戏机总是有一个确认要发送。然后等待大约八秒：
`Task_UnionRoomListen` 每帧重试 `rfu_UNI_setSendData`，并在 NI_START 挂起时失败并显示 ERR_SUBFRAME_SIZE：接收控制占用子节点 16 个 LL 帧字节 [librfu_rfu.c:2262] 中的 2 个字节，并且 UNI 子帧需要 16 个字节[librfu_rfu.c:1449]。挂起的接收仅由 `NI_failCounter_limit` 释放，在最后一个 NI_START 后 480 帧
[link_rfu_2.c:139, AgbRfu_LinkManager.c:1328]（测量：主机最后一个帧之后的第一个 UNI 帧 482 帧）。没有什么可以提前释放它。
<a id="what-the-console-does-once-connected"></a>
## 连接后游戏机会做什么

[src/union_room.c:2858-2879]

    if (gReceivedRemoteLinkPlayers) {
        CreateTrainerCardInBuffer(gBlockSendBuffer, TRUE);
        CreateTask(Task_ExchangeCards, 5);
        uroom->state = UR_STATE_COMMUNICATING_WAIT_FOR_DATA;
    }
    ... then, if sPlayerCurrActivity == (ACTIVITY_TRADE | IN_UNION_ROOM),
        UR_STATE_SEND_TRADE_REQUST
 提示符为“POKELDN: oh bonjour \<name>, vous désirez quelque select ?”与致敬/战斗/聊天/返回。每个选择发送一个 `SEND_PACKET` 并等待
[UR_STATE_HANDLE_ACTIVITY_REQUEST, union_room.c:3151]：

|游戏机发送|活动 |主机答案 |
|---|---|---|
| 0x48 |卡（敬礼）| 0x51 接受 |
| 0x44 |交换（交换板）| 0x51 接受 |
| 0x41 |战斗（战斗）| 0x51 接受 |
| 0x45 |聊天（聊天）| 0x51 接受 |
| 0x40 |退出（返回）|视为游戏机的关闭|

每次活动结束后，双方 `SetLinkStandbyCallback` [union_room.c:2995, :3012] 和游戏机返回其提示。 Switch 版本还对接受方进行了门控
`svc_CommsAllowedByParentalControls()` [union_room.c:3159, :3037, REVISION >= 0xA]，因此游戏机自己的家长控制可以将其请求转变为拒绝。敬礼展示主机的训练家卡并重复； Retour 发送 0x40，然后发送 READY_CLOSE_LINK，一旦应答，游戏机就会正常断开连接并留在房间内，没有错误。
<a id="the-trading-board"></a>
## 交换板

开发板列出广告带有`tradeSpecies`、`tradeType`和`tradeLevel`的合作伙伴
[union_room.c:3400]：记录字节18（`type << 2`）、19（`gameClear | level << 1`，按包装层的打包方式，见[广播记录](frlg_rom.md#the-advertisement-record)）和22:24（小端字节序）
`tradeSpecies:10` 的 `RfuGameData` [include/link_rfu.h:107]）。种类 277（木守宫；低字节单独 21，烈雀）列为“POKELDN / NORMAL / ARCKO / 26”，测量字节 23。

交换板交换是每个链路一次交换。 `Task_StartUnionRoomTrade`将`gMain.savedCallback =
CB2_ReturnToField`设置在`CB2_LinkTrade` [union_room.c:1744]之前，并且仅当保存的回调是交换中心的`CB2_StartCreateTradeMenu`时，`CB2_SaveAndEndTrade`才保持链接
[trade_scene.c:2722-2725];任何其他以 `SetCloseLinkCallback` 结尾。序列：游戏机的宝可梦块（计数 9）、主机、其邮件块（计数 19）、主机、动画、其
READY_FINISH，主机的CONFIRM_FINISH，保存障碍，READY_CLOSE_LINK双向，其正常断开回房间。另一个板交换是一个新的连接。交换中心返回其交换菜单，而不是 [trade.c:2094-2113]。没有队伍交换、菜单或房间路线。
<a id="chat"></a>
## 聊天

聊天乘坐 `SendBlock` 并绕过 `Rfu_SendPacket`：每个成员主动调用 `SendBlock(0, sendMessageBuffer,
0x28)`，没有 `BLOCK_REQ` [`ChatEntryRoutine_Join`，union_room_chat.c:429；
`ChatEntryRoutine_SendMessage`，：823]。 0x28 字节块是 `count` 4。

    [0]      command: 0 NULL, 1 CHAT, 2 JOIN, 3 LEAVE, 4 DROP, 5 DISBAND
    [1..8]   player name, PLAYER_NAME_LENGTH + 1 bytes, EOS-terminated
    [9]      multiplayer id            (JOIN / LEAVE / DROP / DISBAND)
    [9..39]  message text, EOS-terminated (CHAT)

[`PrepareSendBuffer_*`, union_room_chat.c:1256-1281; `ProcessReceivedChatMessage`, :1283]。在接受 0x45 时，游戏机进入 `Task_StartActivity` 的聊天分支 [union_room.c:1938]，该分支仅停止新连接 (`rfu_LMAN_stopManager(FALSE)`) 并保留链接。双方成员在进入时发送 JOIN，无需等待；主机对游戏机的加入做出反应。

一行有 15 个条目（`MESSAGE_BUFFER_NCHAR` [union_room_chat.c:21]；31 字节缓冲区允许
0xF9 与 [string_util.c:560] 配对）。接收器将到达的所有内容复制到 [:1308] 到一个未剪辑的行中，因此第 16 项之后的条目会超出屏幕；主机在启动时拒绝过长的 `--chat-message` 或 `--chat-file` 线路（`uroom_chat.entry_count`）。

领导者必须在离开时关闭：离开者等待父节点删除链接
[`ChatEntryRoutine_AskQuitChatting` cases 2/4/5, union_room_chat.c:596-660]，否则它会显示“退出聊天？”。主机在 LEAVE 后 0.1 秒发送 DROP 并运行关闭链路握手。写入后约 1.7 秒，附加到 `--chat-file` 的行到达游戏机。
<a id="the-link-battle-urbattle-0x41"></a>
## 链接战 (UR_BATTLE 0x41)

`HasAtLeastTwoMonsOfLevel30OrLower` [union_room.c:4565] 需要 2 个 30 级或以下的非蛋队伍，在游戏机提供 [union_room.c:2923] 并接受 [union_room.c:3176，发送拒绝]时检查；双方仅测试自己的 `gPlayerParty`，并且拒绝是屏幕上的一条消息。

双方都选择两个mon后，各自发送一个0x20字节块，其第一个字节为`ACTIVITY_ACCEPT | 0x40` = 0x51（如果取消则为0x52），其余为零[union_room_battle.c，`CB2_UnionRoomBattle`]；其他任何内容都会以“拒绝”关闭链接。然后，交换机路径有两个链接任务等待，其间有一个备用等待（`#if REVISION >= 0xA` 情况 50/51/52）。

`SetUpPartiesAndStartBattle` 保留两个选定的 mon，将其他四个清零，然后调用
`StartUnionRoomBattle(BATTLE_TYPE_LINK | BATTLE_TYPE_TRAINER)` [union_room.c:1811]，设置
`gLinkPlayers[0].linkType = LINKTYPE_BATTLE` (0x2211) [link.h:92]，`TryReceiveLinkBattleData` 完全测试 [battle_controllers.c:520]。然后[`CB2_HandleStartBattle`, battle_main.c:934]：

    state 1  SendBlock struct LinkBattlerHeader {versionSignatureLo, versionSignatureHi,
             vsScreenHealthFlagsLo, vsScreenHealthFlagsHi, struct BattleEnigmaBerry}
    state 3  SendBlock gPlayerParty[0..1]   200 bytes      state 4  recv -> gEnemyParty
    state 7  SendBlock gPlayerParty[2..3]   200 bytes      state 8  recv
    state 11 SendBlock gPlayerParty[4..5]   200 bytes      state 12 recv
    state 15 InitBattleControllers
 队列交换是交易的 3 × 200 字节传输（`mon.party_blocks`；`Rfu_InitBlockSend` 最多允许 252 个）。
<a id="master-election"></a>
### 大师选举

在单场比赛中，只有`BATTLE_TYPE_IS_MASTER`方设置`gBattleMainFunc =
BeginBattleIntro`；另一个保留`BeginBattleIntroDummy` [`InitLinkBtlControllers`，
battle_controllers.c:141; `SetUpBattleVars`，：45]。非主机不运行回合分辨率、伤害或 RNG：它接收 BUFFER_A 控制器命令，显示它们并回答，因此作为非主机的主机是战斗控制器。

`LinkBattleComputeBattleTypeFlags` [battle_main.c:886]，来自多人游戏 id 1 的游戏机：如果
`gBlockRecvBuffer[0][0] == 0x100`或者双方签名相等，玩家0为主；否则最低索引具有最高版本。 0x100 以外的低于 0x201 的签名为游戏机主机；主机发送 0x200。
<a id="the-link-buffer-protocol"></a>
### 链接缓冲区协议

每个控制器命令都是一个具有 8 字节标头 [battle_controllers.c:401-435] 的 SendBlock：
`LINK_BUFF_BUFFER_ID, ACTIVE_BATTLER, ATTACKER, TARGET, SIZE_LO, SIZE_HI, ABSENT_BATTLER_FLAGS,
EFFECT_BATTLER`，然后是税务，存储为`alignedSize = size - size % 4 + 4`（4字节税务占8个）。 `bufferId` 0 = BUFFER_A（命令），1 = BUFFER_B（回复），2 = exec-flag 清除，其一个字节是发送者的多人游戏 ID [Task_HandleCopyReceivedLinkBuffersData:566-594]。战斗者0是主人的怪物，战斗者1是主机的怪物。

同步规则 [battle_util.c:185-201]：`MarkBattlerForControllerExec` 设置位 `28+battler`；当命令块返回时，`MarkBattlerReceivedLinkData` 为每个玩家 i 设置 `gBitTable[battler] << (i*4)` 并清除位 28+battler；每个玩家都用 bufferId 2 清除其半字节。主站仅在 `gBattleControllerExecFlags == 0` 上前进，因此每个命令都必须得到两个战斗者的确认。

在 56 个玩家缓冲区命令 [battle_controller_player.c:110] 中，这些命令需要的不仅仅是 ack：

    CONTROLLER_GETMONDATA    -> EmitDataTransfer(BUFFER_B, size, data)   [player.c:1515]
    CONTROLLER_CHOOSEACTION  -> EmitTwoReturnValues(1, B_ACTION_*, 0)    [player.c:232-241]
    CONTROLLER_CHOOSEMOVE    -> EmitTwoReturnValues(1, 10, move | target << 8) [player.c:342]
    CONTROLLER_CHOOSEPOKEMON -> EmitChosenMonReturnValue(1, partyId, order)    [player.c:1316]
    CONTROLLER_OPENBAG       -> EmitOneReturnValue(1, itemId)            [player.c:1340]
    CONTROLLER_EXPUPDATE     -> EmitTwoReturnValues(1, RET_VALUE_LEVELED_UP, exp) [player.c:1051]
    CONTROLLER_ENDLINKBATTLE -> gBattleOutcome = payload[1], then ack     [player.c:2876]

`B_ACTION_USE_MOVE` 0、`USE_ITEM` 1、`SWITCH` 2、`RUN` 3 [battle.h:34]。

第一个命令是 `GETMONDATA` `REQUEST_ALL_BATTLE` [battle_main.c:2519]，用 0x58 字节应答
`struct BattlePokemon` [pokemon.h:170] 作为 `CopyPlayerMonData` 构建它 [player.c:1519]；
`statStages`、`ability`、`type1`、`type2`、`status2` 和 `unknown` 被重新计算，因此使用零。可以跳过对战士 0 的 BUFFER_B 回复：游戏机从 `gEnemyParty` [link_opponent.c:444] 应答其自己的 GETMONDATA。

链接战斗者可能会以最高回合顺序运行 [battle_main.c:3239] [:3548-3560]，因此回答第一个
`CHOOSEACTION`与`B_ACTION_RUN`演练全程并结束战斗。
<a id="two-rules-not-visible-in-the-decomp"></a>
### 两条规则在 decomp 中不可见

块的大小并不决定其路径。每个 ack 和短命令（包括第一个 `GETMONDATA`）都是一个 16 字节、两个片段的记录，因此在战斗中状态会路由一个块，而不是它的大小。

ack 绝不能超过它所确认的块的回显。仅当游戏机自己的块返回 [`MarkBattlerReceivedLinkData`, battle_util.c:193] 并且主机的 ack 清除它 [battle_controllers.c:585] 时，游戏机才会设置 exec-flag 位；两个片段的 ack 可以传递一个七片段的 echo：

    104.268 console bufferA battler 0 PRINTSTRING (72 B)
    104.366 host    ack battler 0                     <-- host's ack first
    104.383 echo    bufferA battler 0 PRINTSTRING
 回声然后设置位，游戏机永远等待 `gBattleControllerExecFlags == 0`，它门控 `Cmd_waitmessage` [battle_script_commands.c:2041]，冻结在链接活动的战斗结束消息上。 `HostTradeEngine._echo_owed` 持有一个新区块，而任何子节点命令都在等待其镜像。

ack 还等待回声的每个片段。 `rfu_leader.echo_blocks` 保持每一个回响
`SEND_BLOCK_INIT` 发出了一组片段索引，并且 ack 等待 0..count-1。空的 echo 队列速度慢 24 倍；计算回声，或仅观察最后一个片段，可以让重新发送的片段的回声与 ack 共享一个帧。稍后的消息无法释放正在等待的游戏机
`gBattleControllerExecFlags`;结束主机通过错误屏幕将其返回到房间。
<a id="the-pace-is-the-rfu-vblank-budget"></a>
### 节奏是 RFU VBlank 预算

与主机的链接战斗步骤在两个方向上大约需要一秒钟。数据报周转时间的中位数为 5.8 毫秒（8204 个回复的 p99 为 16.6 毫秒；游戏机的中位数为 8.1 毫秒）。连续的 `bufferA` 命令的中间间隔为 800 毫秒；游戏机块在 19 毫秒内回显，主机的应答块在 355 毫秒后跟随。 `HostSession.tick` 每次调用时发出一个 RFU 时隙，`HOST_VBLANK_SECONDS =
1/59.727` = 16.74 ms（测量值 17 ms × 5035、16 ms × 413）；一个命令块跨越大约 20 帧，约 340 毫秒，一个步骤是加上返回腿。每个 VBlank 多个插槽并不是硬件链路的作用。
<a id="what-two-real-consoles-put-on-the-air"></a>
## 两个真正的游戏机播出了什么

被动捕获两个真实主机之间的交换（火红通过第三个 NPC 主持，叶绿加入）。监视器帧数是一个下限； 802.11 序列计数器给出监视器错过的帧。序列校正帧率，同火红游戏机：

|车站|与主机交谈|与真正的游戏机交谈|
|---|---|---|
|火红游戏机| 161.8/秒 | 25.5/秒 |
|它的同行| 58.9/s，每个 VBlank 一个插槽上的主机 | 6.1/s，叶绿|

25.5/s 的数字基于最柔和的捕获。

通过 Direct Corner 托管的火红游戏机在偏移处以纯 ASCII 形式携带 Switch 配置文件名称
`application_data` 的 0x11；广告中没有游戏内训练家的名字。
<a id="host-tick-rate-and-the-consoles-output-rate"></a>
## 主机节拍率和游戏机的输出率

`--tick-hz` 设置主机每秒的 RFU 插槽（每个 VBlank 默认一个）。使用相同的游戏机以每种速率进行一次交换：

| | 59.727 Hz（默认）| 20赫兹|
|---|---|---|
| 主机数据报出| 79.3/秒 | 39.3/秒 |
| | 游戏机数据报61.8/秒 | 51.8/秒 |
| 交换持续时间| 92 年代 | 197 秒 |
| 游戏机数据报，整个会话| 5663 | 10218 |

在 20 Hz 时，游戏机的速率下降了六分之一，交换时间为 197 秒，而游戏机发送的数据报数量增加了 80%。默认值是每个 VBlank 一个插槽。
<a id="the-cable-club-colosseum"></a>
# 连接俱乐部斗兽场

`frlg_trade_host.py --colosseum` 宝可梦中心2楼→第三个NPC（无菲尔俱乐部）→斗兽场→单挑→加入。仅 `CB2_ReturnFromCableClubBattle` 增加神奇配合的 `battlesWon`
[src/cable_club.c:792];联合房间战斗通过`CB2_ReturnToField`回归。

`Task_StartActivity` 将 `ACTIVITY_BATTLE_SINGLE` 视为 `ACTIVITY_TRADE` [union_room.c:1903]，除了地图（`MAP_BATTLE_COLOSSEUM_2P` 位于 (6, 8)，而不是 `MAP_TRADE_CENTER` 位于 (5, 8)）和
`HealPlayerParty()`，因此训练家卡交换和`--card-flag-id`的工作方式不变。有四件事发生了变化：

1. 活动字节：`LINK_GROUP_SINGLE_BATTLE` 接受 `{ACTIVITY_BATTLE_SINGLE, 0xFF}` [src/data/union_room.h:398]； `build_colosseum_app_data` 仅更改该字节。
2. `BattleColosseum_2P_EventScript_PlayerSpot0/1`没有队伍检查[data/scripts/cable_club.inc:576]（4P `ChooseHalfPartyForBattle`有选择步骤）。座位握手方式不变。
3. `Task_StartWirelessCableClubBattle` 情况 2 发送 `SendBlock(0, &gLocalLinkPlayer,
   sizeof(gLocalLinkPlayer))` [cable_club.c:701]：裸露的 28 字节 `struct LinkPlayer`，没有入口块的 GameFreak 魔法，双方均无提示；游戏机停在情况 3 中，直到每条记录都落地。然后20帧，`IsLinkTaskFinished`，`SetLinkStandbyCallback`，另一个等待（情况4-6，`REVISION >= 0xA`），`CB2_InitBattle`。
4.全队伍战斗：`party_blocks` 就地取队伍[union_room_battle.c:47]。

从`CB2_InitBattle`开始就是联合房间之战，包含签名0x200，不含0x20字节
0x51 选择块（仅限 `CB2_UnionRoomBattle`）。

座椅仅需要 READY 键：没有任何动作，游戏机将继续进行
`Task_StartWirelessCableClubBattle`（`GetCableClubPartnersReady` 仅读取链接状态
[overworld.c:2989]）。没有座位后的候补轮次； a 主机等待他们僵局，而停在情况 3 中的游戏机发送 `SEND_BLOCK_INIT` 计数 3 和
`04 40 00 80 65 df | bb c8 ff 00 11 00 | 01 00 03 00 00 00`（版本0x4004火红，`lp_field_2`
0x8000，其训练家ID）。该块的到达完成了条目。

主机在战斗后也欠退出键：门等待着每个玩家
`PLAYER_LINK_STATE_EXITING_ROOM` [overworld.c:2977]，否则游戏机将处于*“conduire a la sortie de lapiece，veuillez耐心者”*直到链接错误。
<a id="what-decides-whether-a-colosseum-run-counts"></a>
## 是什么决定了罗马斗兽场跑步是否算数

弃权即为游戏机的胜利：`HandleAction_Run` 将 `B_OUTCOME_WON` 设置为未运行的一方，与 `B_OUTCOME_LINK_BATTLE_RAN` (1 << 7) [battle_main.c:4300] 进行或运算，其中
`HandleEndTurn_BattleWon` 在 `CB2_ReturnFromCableClubBattle` 开启之前清除 [battle_main.c:3734]。记录的id是`gLinkPlayers[GetMultiplayerId() ^ 1].trainerId` [cable_club.c:794]，来自28字节记录，每个统计一次（每个统计记录5个）[mystery_gift.c:630]。对三个不同的 `--id` 值的三次弃权将 `battlesWon` 提高到 3，战斗计数卡将以其 POTION 奖励。一后：

    save 0x3434:  0100 0000 0000 2300    battlesWon 1, lost 0, trades 0, icon 35 CARD_TYPE_LINK_STAT
    game data:    "1 battles won"

<a id="two-host-side-constraints"></a>
# 两个主机端约束

关闭路径取决于孔防护装置：`done` 来自断开路径，门控打开
`disconnect_requested`，由 `_tick_close_link` 设置在 `activity.tick()` 内，`HostSession.tick` 在孔防护装置保持时跳过。停止确认的游戏机会锁定防护装置，因此关闭计时器会停止；一旦游戏机在确认退出后离开 LDN，运行时间就会停止。

全零 `easyChatProfile` 打印“??? ???”在训练家卡上：字 0 是 `EC_GROUP_POKEMON_2` 索引 0 (`SPECIES_NONE`)，`IsECWordInvalid` 拒绝并用 `CopyEasyChatWord` 替换
`gText_ThreeQuestionMarks` [easy_chat.c:166-171]。一个字是`(group & 0x7F) << 9 | (index & 0x1FF)` [easy_chat.h:1089]，每张卡四个[trainer_card.h:28]；用 `EC_WORD_UNDEFINED` (0xFFFF) 填充一个短语，它什么也不打印。
