---
title: FRLG 远程联机方案：先局域网交换，再扩展公网
parent: FireRed and LeafGreen
nav_order: 10
---

# FRLG 远程联机方案：先局域网交换，再扩展公网

日期：2026-10-01。代码基线：当前工作区；最终可复现提交号以测试包 `BUILD_INFO.txt` 为准。

本文延续前述聊天中的双端桥接思路，第一目标是让两名玩家在各自的 Switch 上选择并交换真实队伍中的宝可梦。第一版限定 FireRed/LeafGreen 的 Direct Corner Trade Center，先在局域网验证，后续再接公网中继。

**当前状态分为两个边界：** P0 数据探针的核心双实机流程已经跑通；正式交换仍未实现，也没有通过正式交换的双实机验收。最近一轮 P0 已完成 `link_player → trainer_card → party_0 → party_1 → party_2 → mail → ribbons` 七阶段，双端快照摘要互相匹配，`probe_only=true`、`commits=0`，并拒绝了 `READY_TO_TRADE`；剩余的证据问题是正常退出时一端先关闭 TCP 造成的 `LAN peer disconnected` 记录，修复后需要重新跑 `check-evidence.ps1`。下文凡未标为“现有”的正式交换模块、协议、命令和指标仍是拟议内容。本方案与 [内存 RNG 方案](frlg_memory_rng_plan_zh.md) 独立，不以 CFW、内存读写、自动乱数或 FRLGSwitchSeedFarmer 为前置条件。

P0 的运行入口和禁止交易边界见 [FRLG 局域网数据探针（P0）](frlg_remote_trade_p0_zh.md)。本文的正式交换章节描述 P1/P2 的实现目标，不能作为“已经可以交换”的使用说明。

## 1. 结论与范围

推荐采用“两个本地 RFU 主机 + 一个跨 PC 的交换协调器”路线：每台 PC 负责自己身边的 Switch，通过 LAN 交换完整的业务数据块和双方意图。

这条路线有可复用的基础，但不能把现有文件交换程序接上 TCP 就视为完成。现有主机引擎会使用预载队伍、自动选择和确认；真人联机必须支持真实对端数据、双方同意、拒绝与取消，以及不确定结果的处理。

第一版交付边界：

- 两台零售 Switch，各一套当前已能完成本地交换的 PC + ESP32 环境。
- 两台 PC 能经普通局域网 IP 互通；先指定 IP，不做自动发现、端口映射或 NAT 穿透。
- 双方在游戏内选择宝可梦并确认。PC 不能替另一名玩家自动确认。
- 首个可验收版本每个房间只完成一笔交换，然后正常退场；连续交换作为下一阶段。
- 首轮实机测试用普通、非蛋、无信件、不会交换进化的宝可梦。其他情况另列兼容性验收，不能默默当作已支持。
- 第一个支持组合选用已经完成本地基线测试的 FR/LG 和语言组合，报告精确游戏版本、语言、ESP32 固件和 PokeLDN 提交号。

第一版不包括对战、多人 Union Room、游戏内聊天、观战、文件赠送、跨世代交换或其他游戏。这里的“远程联机”先指这一项具体交换功能，不是所有 LDN 游戏的透明远程联网。

## 2. 已有基础与实际缺口

| 现有实现 | 可以复用 | 远程模式必须补齐 |
|---|---|---|
| `HostTransport`、ESP32 radio | 本地 LDN AP、收发与设备生命周期 | 两端独立启动、识别本地 Switch、防止选错房间 |
| `HostPeerProtocol` | Pia Net/Session/RTT、加密和发送调度 | 不把其 nonce、ACK 或会话 ID 搬到另一端 |
| `HostSession(engine=...)` | Reliable + RFULeader，已有引擎注入入口 | 注入远程交换策略，保持现有无线背压行为 |
| `HostTradeEngine` | 入室、入座、分块、屏障和退场状态机 | 动态对端数据、双端选择与确认、完整拒绝路径 |
| `TradePlan` | 文件提供方的配置校验 | 另建远程配置；不能要求真人对端预先提供 `.pk3` |
| `HostApplication` | OS 资源、事件循环、清理和部分活动钩子 | 构建组件仍绑定文件队伍；需要有限的工厂和事件钩子 |
| 现有离线脚本子机与故障无线链路 | RFU/Reliable 回归测试骨架 | 两套本地链路 + 可控 LAN + 独立人类输入脚本 |

依据：[主机架构](frlg_host.md)、[HostSession](../pokeldn/frlg/link/host_session.py)、[HostTradeEngine](../pokeldn/frlg/link/host_trade.py)、[HostApplication](../pokeldn/frlg/link/host_app.py)、[配置](../pokeldn/frlg/config.py)、[端到端测试](../tests/test_host_end_to_end.py)。

源码中需要特别注意的行为：

1. `_on_child_linkcmd()` 收到本机 `READY_TO_TRADE` 就发预设槽位，收到本机 `INIT_BLOCK` 就开始动画；没有等待另一名真人的逻辑。
2. `_request_and_send()` 同时请求本机数据和发送预载数据。远程模式必须拆开“请求本机”和“提供对端”，保留阶段推进条件。
3. 当前 Direct Corner 主机发送空 mail/ribbon 数据，接收端也没有保留这些数据块；远程模式必须保留真实内容。
4. `_commit()` 增加 `commits`、保存接收对象后才进入 `H_SAVE`。这个计数不是“两台 Switch 已持久化存档”的证明。
5. `HostApplication._log_activity_progress()` 目前根据 `commits` 报完成并导出文件；远程模式必须使用新的结果判据。
6. `HostSession` 有重传与 outstanding 上限，背压可能暂停 `activity.tick()`。LAN 超时和退出判定不能只依赖活动帧计数。

仓库还存在 [ldn_mitm_host.py](../pokeldn/ldn/ldn_mitm_host.py)，它让模拟器通过 LAN 接入一个 LDN 主机，可参考传输注入方式；它不是两台零售 Switch 间已完成的远程交换桥，也不能代替本方案的事务协调。

## 3. 拓扑与职责

```text
Switch A                     Switch B
   | 本地 LDN/RFU               | 本地 LDN/RFU
ESP32 A                      ESP32 B
   | USB                        | USB
PC A                         PC B
  HostTransport                HostTransport
  HostPeerProtocol             HostPeerProtocol
  HostSession                  HostSession
  本地交换引擎                 本地交换引擎
  RemoteTradePolicy            RemoteTradePolicy
         |                         |
         +------ LAN TCP ----------+
           房间协调器位于 PC A
```

三个“主机”概念必须分开：

- **LAN 房主**：PC A 监听 TCP、建立房间并决定一笔交换何时可以进入下一阶段。
- **本地 RFU 主机**：PC A 和 PC B 都是，分别负责自己的无线时序。
- **游戏内玩家**：两台真实 Switch 在各自链路上都是 child / player 1；对端真人被本地 PC 表现为 parent / player 0。

每端映射如下：

| 真实数据 | Switch A 所在链路 | Switch B 所在链路 |
|---|---|---|
| A 的资料、队伍与选择 | 本机 child 数据 | 对端 parent 数据 |
| B 的资料、队伍与选择 | 对端 parent 数据 | 本机 child 数据 |
| child echo | 只回显 A 自己的行 | 只回显 B 自己的行 |
| Reliable 序号、RFU 屏障计数 | A 本地维护 | B 本地维护 |

不跨 LAN 转发原始 802.11、Pia 包、每帧 RFU 行、ACK、held-key 序列或原始屏障计数。LAN 上传完整业务块及经过解释的事件，由接收端按自己的本地角色重新封装。发送方为 child 的块不能直接原样作为 child 行注入另一端。

### 路线比较

| 路线 | 评价 |
|---|---|
| 双本地主机 + 业务块/决策桥接 | 推荐；无线回显和重传留在本地，但需证明角色映射和阶段门控 |
| 一端本地主机、一端本地 joiner | 保留真实 leader/follower 分工；需要跨两套状态机协调请求与响应，作为备用研究路线 |
| 整条 RFU/Pia 流透传 | 远端延迟直接进入本地时序、回显和重传，不作为首版 |
| 只把待交换 `.pk3` 发给对方 PC | 不能证明两台游戏都交出了原宝可梦，不符合本任务 |

若推荐路线在关键门槛失败，先记录失败阶段与抓包，再评估备用路线；不能通过填入临时宝可梦、自动假确认或放宽所有超时“绕过”失败。

## 4. 第一优先级：证明能正确交换对端数据

### 4.1 身份启动不能依赖尚未收到的队伍

现有构造函数预先生成 LinkPlayer、Trainer Card 和 host party。远程模式启动时没有对端的真实数据，必须改成延迟提供。

拟定流程：

1. 两台 PC 先配对，检查协议版本和两侧硬件准备状态。
2. 使用明确的本地桥接名称发布 discovery，供玩家区分两套设备。discovery/Pia 身份与游戏内真实 LinkPlayer 身份分别保存。
3. 两端各请求本机 Switch 的 LinkPlayer，正常完成本地回显；收到后立即经 LAN 发送。
4. 拿到远端 LinkPlayer 后，按本地 parent 角色生成发送块，再开始后续 Trainer Card 阶段。
5. 游戏内 OT、TID/SID、语言、进度标志和卡片来自真人数据，不用本地默认 `PkCamp` 资料冒充。

保留 LinkPlayer 原始块作为权威数据。解析用于校验和展示；只修改经确认与本地角色有关的字段，例如 `player_id`，并记录修改范围。禁止先解码名字再完整重建记录，以免丢失未知字节或字符。

**待实测门槛 G0-A**：discovery/Pia 身份与游戏内 LinkPlayer 的这种分离是否被目标版本接受；角色字段到底需要改哪些；先进入的一侧能等待多久。

LinkPlayer 阶段已有较紧时序，不能假设两人可相差几十秒进入而仍然成功。需要测试可否在 LDN/Pia/RFU 的合适启动边界等待两侧就绪；若等待窗口不足，必须设计可重试的入室流程。不能把“双方恰好同时按键成功一次”作为通过。

### 4.2 队伍必须逐块交叉传递

`BufferTradeParties` 每次只准备两只宝可梦，收到本轮双方块后才准备下一对。若 PC 要先读齐本机 600 字节再开始回传远端数据，会形成循环等待。可从 [上游 trade.c 的 BufferTradeParties](https://github.com/pret/pokefirered/blob/master/src/trade.c) 核对该门控；实现时应固定上游提交，不能依赖变化中的行号。

正确的流水顺序：

```text
本地 A 请求 party[0]       本地 B 请求 party[0]
收 A[0] 并回显 A          收 B[0] 并回显 B
           A[0] <---- LAN ----> B[0]
把 B[0] 发给 Switch A     把 A[0] 发给 Switch B
各自完成本轮发送及本地 link-task 门控
再进入 party[1]，随后 party[2]、mail、ribbons
```

每个块的状态至少区分：`REQUESTED`、`LOCAL_RECEIVED`、`REMOTE_RECEIVED`、`PARENT_SENT`、`LOCAL_PHASE_SETTLED`。不把“PC 已收到”“TCP 已送出”“RFU 块已发完”“Switch 已消费”视为同一事件。

`_link_waiting_idle` 不能因为 LAN 等待期间出现 idle 就提前推进；必须先满足该阶段的数据和本地发送条件。保留现有本地 block sender、回显、quiet-window 门控，经测试后补充跨端条件。

Trainer Card 同样按阶段请求和交换。每个请求都必须带明确阶段标识，不能仅凭长度判断：LinkPlayer 和 party 都走 200 字节请求。

**待实测门槛 G0-B**：两个真实 child 在上述逐块交换方式下，均能显示对端真实身份和六槽队伍，再取消退场；此阶段禁止发 `START_TRADE`。

### 4.3 数据清单与快照

| 数据 | 本地逻辑长度 | LAN 处理 |
|---|---|---|
| LinkPlayer | 60 字节有效记录，200 字节请求缓冲 | 保留原始请求缓冲，验证 magic，受控角色转换 |
| Trainer Card | 100 字节 | 原始内容传递，包含尾部卡片字段 |
| Party | 3 x 200 字节，总计 600 字节 | 按块发送，保持六个槽位，含每只 100 字节 party 数据 |
| Mail | 220 字节 | 原始缓冲传递，不替换为空信件 |
| Gift ribbons | 40 字节 | 原始缓冲传递，不假设是无用装饰 |
| Selection / confirmation | 结构化事件 | 指定快照、选择版本、槽位和操作，不用本机预设槽位 |

RFU 分片重组结果可能带填充：按请求类型提取逻辑长度，不把分片容量误当有效数据长度。快照摘要使用逻辑数据，原始抓包另存。

每轮建立 `snapshot_id`，全部块收齐后计算 `snapshot_digest`。两个客户端都报告“本地快照 X 已被对端完整呈现”后，才开放选择协调。SHA-256 摘要用于绑定内容与检测差异，不证明对端 PC 的诚实性。

远程字节不得走文件导入的 PKHeX 重建、修复、换 PID、改 OT 或合法化流程。传输层保持原始数据，游戏自行执行正常交换规则。

## 5. 双人选择、确认与交换状态机

### 5.1 状态归属

本地引擎管理 RFU 与游戏阶段；房间协调器管理双方意图及跨端决策。两者通过事件连接，不共享可变引擎对象。

```text
PAIRING -> LOCAL_LINKS -> DATA_EXCHANGE -> SELECTING
  -> CONFIRMING -> PREPARED -> START_AUTHORIZED -> ANIMATING
  -> BOTH_FINISHED -> FINISH_AUTHORIZED -> SAVING
  -> POST_TRADE_SYNC -> COMPLETED -> CLOSING -> CLOSED

开始前取消 -> CANCELLED / 返回 SELECTING
结果无法判断 -> IN_DOUBT
```

`CLOSED` 只表示资源和本地链路已经结束，不能覆盖 `CANCELLED` 或 `IN_DOUBT`。退场失败也不能抹掉已核实的交换结果。

### 5.2 事件与游戏命令映射

| 输入 | 跨端处理 | 本地动作 |
|---|---|---|
| A/B `READY_TO_TRADE(slot)` | 记录对应快照的选择；等待双方 | 双方都选好后，各发一次 `SET_MONS_TO_TRADE(对端槽位)` |
| A/B `INIT_BLOCK` | 记录游戏内最终 Yes；绑定当前选择版本 | 双方 Yes 且准备条件通过后才允许开始 |
| A/B `READY_CANCEL_TRADE` | 撤销本轮确认，处理拒绝或游戏规则拒绝 | 按本地 parent/child 视角发正确取消命令，返回菜单 |
| A/B `REQUEST_CANCEL` | 区分退出意图与仍想选择的一方 | 单方取消处理和双方退出分别走原生路径 |
| A/B `READY_FINISH_TRADE` | 等待双方真实完成事件 | 双方完成授权前不发 `CONFIRM_FINISH_TRADE` |
| 本地连续 save barriers 完成 | 记录本地保存进度，不代替对端 | 继续本地握手，进入真实队伍刷新 |
| 两侧交换后快照已核验 | 建立双端完成结果 | 允许正常退场；连续交换版才允许开启下一轮 |

槽位严格校验为 `0..5` 且对应有效、被呈现的队伍槽位。当前代码的 `cursor % 6` 不适合作为网络输入容错规则，越界必须拒绝。

取消必须覆盖：未选择、双方选择不一致、确认页 No、游戏判定不可交换、一方想退出而另一方仍在选择。两个本地主机面对的真实角色不同，不能向两侧机械发送同一个 `PLAYER_CANCEL_TRADE` / `PARTNER_CANCEL_TRADE`。角色关系需有表驱动测试。

原有“本机连续两次 CANCEL 就让机器人退出”策略不能充当另一名真人的退出意图。首版一笔完成后，房间可以统一进入“等待双方退出”状态，但仍完成两侧游戏内所需的 Cancel/Yes 和退场屏障。

### 5.3 快照、选择与版本约束

- 一笔交换使用唯一 `trade_id`，不复用上笔 ID。
- 一对选择使用 `selection_epoch`，绑定双方 `snapshot_id`、槽位与被选中原始数据摘要。
- 重新选择、取消、游戏拒绝或队伍刷新都会使旧确认失效。
- `INIT_BLOCK` 在线上没有 LAN epoch，本地适配层只可将当前游戏阶段产生的事件绑定到当前 epoch；不能给晚到的旧命令随意贴上新 epoch。
- 取消后先排空该阶段本地发送/接收状态并观察菜单重入条件，再开放新选择。无法区分旧事件时结束会话，不能冒险继续。
- 开始前再核对双方所确认的选择摘要一致。PC 上显示的摘要只是辅助，最终 Yes 来自游戏。

### 5.4 开始与完成的持久化门控

协调器在双方确认后生成包含双方快照和槽位摘要的准备记录；两侧分别写入本地日志，完成落盘后返回 `PREPARED`。

协调器随后持久化 `START_DECISION` 并发送给双方；双方落盘回复 `DECISION_STORED`。收到双方回复后发 `START_RELEASE`，各自记录发放意图，再向自己的 Switch 排入一次 `START_TRADE`。

两侧收到真实 `READY_FINISH_TRADE` 后，完成授权使用同样的“决策落盘 -> 双侧确认 -> 释放”步骤，然后各发 `CONFIRM_FINISH_TRADE`。原来的 `anim_delay=1935` 不能充当对端完成证明；必要的本地动画时序仍保留并单独测量。

这套门控减少错误开始并提供审计线索，**不是能回滚 Switch 的数据库事务，也不保证两端原子提交**。释放指令可能只有一端收到，落盘记录也不能证明命令已经被游戏消费。

尤其要注意：上游 `CB2_UpdateLinkTrade` 在发送 `READY_FINISH_TRADE` 前已经调用 `TradeMons` 修改内存队伍；收到完成事件不能解释为“还没交换，只等提交”。[上游 trade_scene.c](https://github.com/pret/pokefirered/blob/master/src/trade_scene.c)

因此，从任一端可能收到 `START_TRADE` 起就进入不可盲目重试区间；不能把 `CONFIRM_FINISH_TRADE` 当作唯一风险边界。

### 5.5 正式交换的 P1/P2 落地顺序

正式交换必须与 P0 共用数据块和角色映射代码，但使用独立的能力开关。默认配置仍为 `probe_only=true`；只有明确选择正式模式、双方协商出相同的协议能力、完成两端本地日志初始化并通过版本/游戏身份检查时，才允许进入下列流程。任何能力不一致、日志不可持久化、快照摘要不一致或本地无线状态异常都必须 fail closed，回到取消或 `IN_DOUBT`，不能降级成“先发命令再看结果”。这些开关是拟议接口，当前 CLI 尚未提供正式交换能力。

#### 5.5.1 单笔交易的事件顺序

每一笔交易都使用新的 `trade_id`；每次重新选择都递增 `selection_epoch`。协调器只接受当前 `trade_id`、当前 epoch 和当前 snapshot 的事件，旧事件只记录为 `stale_event`，不能驱动状态转移。

| 顺序 | LAN 事件 | 必要条件 | 本地游戏动作 | 必须落盘的内容 |
|---:|---|---|---|---|
| 0 | `SNAPSHOT_READY` | 七个数据阶段已收齐，逻辑长度和摘要通过 | 保持交易菜单，不发交易命令 | snapshot ID、digest、阶段摘要 |
| 1 | `SELECT` / `SELECT_ACK` | 槽位为 `0..5`，槽位属于当前快照且未被取消 | 记录真实 Switch 发来的 `READY_TO_TRADE(slot)` | 双方槽位、选择摘要、epoch |
| 2 | `PREPARE` / `PREPARED` | 双方选择和快照摘要相互匹配，没有拒绝或退出 | 等待本地 `INIT_BLOCK`，不发送 `START_TRADE` | 交易摘要、两端准备记录 |
| 3 | `DECISION(kind=start)` / `DECISION_STORED` | 两端 `PREPARED` 均已 durable | 不改变游戏状态 | start decision hash、发送序号 |
| 4 | `RELEASE(kind=start)` | 两端都确认 start decision 已落盘 | 每端只排入一次 `START_TRADE` | start release 意图、时间和本地命令计数 |
| 5 | `ANIMATION_FINISHED` | 本地真实收到 `READY_FINISH_TRADE`，且 trade/epoch 匹配 | 先保持本地保存路径，不等待 LAN 才继续本地屏障 | 本地完成事件和引擎状态 |
| 6 | `DECISION(kind=finish)` / `DECISION_STORED` | 两端都报告真实完成事件 | 暂不发送 `CONFIRM_FINISH_TRADE` | finish decision hash、双方完成摘要 |
| 7 | `RELEASE(kind=finish)` | 两端 finish decision 均 durable | 每端只调用一次 `_commit()`；由引擎在该调用内发送一次 `CONFIRM_FINISH_TRADE`，随后进入保存路径 | release 意图和命令审计 |
| 8 | `SAVE_PROGRESS` | 本地保存屏障按预期顺序完成 | 继续本地保存和队伍刷新 | 保存阶段、屏障计数、异常 |
| 9 | `POST_TRADE_SNAPSHOT` | 从 Switch 重新取得真实队伍及相关块 | 不用 PC 内存中的临时 swap 代替读取 | 交换后 snapshot、允许变化说明 |
| 10 | `RESULT` / `RESULT_ACK` | 两侧交换后快照都核验通过 | 进入正常退场 | 结果摘要、核验规则版本 |
| 11 | `CLOSE_REQUEST` / `CLOSE_RESULT` | 结果已确定或明确取消 | 按原生菜单、退场和 close grace 收尾 | 关闭状态、最终分类 |

`SELECT_ACK`、`PREPARED`、`DECISION_STORED` 和 `RESULT_ACK` 是业务确认，不是 TCP `ack_seq`。相同事件键和相同内容必须幂等应答；相同键内容不同、epoch 倒退、槽位越界或阶段不允许的事件都属于协议错误。开始或完成释放只允许协调器生成，任何一端收到重复释放都不得再次向 Switch 发命令。

#### 5.5.2 两道不可越过的提交门

**开始门（Start gate）**必须同时满足：

1. 两端各自的七阶段数据都与其所发布的 `snapshot_digest` 自洽，双方都确认了对端的 `snapshot_id`；A 与 B 的 digest 不要求相等，因为两边的真实队伍本来不同。选择槽位及个体摘要必须分别绑定到这两个 snapshot。
2. 两端都收到真实的本地选择/确认事件，且当前 epoch 没有取消、拒绝或游戏规则错误。
3. 两端各自完成 `PREPARED` 落盘，并对同一个 `START_DECISION` 返回 `DECISION_STORED`。
4. 协调器只发一个 `START_RELEASE`；本地适配器在 release 之前绝不调用发送 `START_TRADE` 的路径。

**完成门（Finish gate）**必须同时满足：

1. 两端都观察到本地真实 `READY_FINISH_TRADE`，并确认事件属于当前交易。
2. 两端各自完成 `FINISH_DECISION` 落盘，并对同一个 decision hash 返回 `DECISION_STORED`。
3. 协调器发出一个 `FINISH_RELEASE` 后，本地适配器才允许调用 `_commit()`；`HostTradeEngine._commit()` 是发送一次 `CONFIRM_FINISH_TRADE` 的唯一入口。
4. 每端进入保存后都继续自己的 RFU/save 屏障；不能为了等待对端 ACK 而中断已经获授权的本地保存。

这两道门是“命令释放门”，不是可回滚的数据库事务。`START_TRADE` 可能已经让游戏进入动画，且上游在发出 `READY_FINISH_TRADE` 前就可能修改内存队伍；从任一端进入 start release 后，断线都必须按 `IN_DOUBT` 或已知的单端结果处理，禁止自动重试、恢复旧存档或重新发送个体。

#### 5.5.3 取消、拒绝和重选

- `SELECTING` 或 `PREPARE` 阶段任一方取消：协调器广播 `CANCEL(trade_id, selection_epoch)`，两端排空当前块/命令队列，确认重新回到菜单后才可以建立新的 epoch；旧 `SELECT` 和 `PREPARE` 永久失效。
- 一方选了空槽、摘要不在当前 snapshot、游戏发送 `READY_CANCEL_TRADE` 或另一方明确拒绝：发送带原因码的 `REJECT`，不产生 start decision；两端回到 `SELECTING` 或共同取消。
- 一方在另一方选择时退出：等待原生取消窗口并记录双方意图；不能把本地连续两次 CANCEL 当作远端同意。
- `START_RELEASE` 之后收到取消：取消只作为诊断事件，不能撤回开始命令；按 `IN_DOUBT` 处理，等待两端能取得的 post-trade 证据。
- 旧 TCP 连接、旧 run 或旧 `trade_id` 的消息不得接管新会话。重新连接必须创建新的 `run_id`，不能重放 `START_TRADE` / `CONFIRM_FINISH_TRADE`。

#### 5.5.4 实现拆分与验收产物

P1 先实现无 socket 的 `coordinator`：把上述事件转换成纯状态转移，保存事件 journal，并对重复、乱序、旧 epoch、单边确认和崩溃窗口做模型测试。P1 的通过条件是任何测试序列都不能在两个 `PREPARED` 或两个 start `DECISION_STORED` 之前产生 `START_RELEASE`，也不能在两端 finish event 和 finish `DECISION_STORED` 之前产生 `FINISH_RELEASE`。

P2 再实现本地适配层：将当前 `HostTradeEngine` 的 `READY_TO_TRADE`、`INIT_BLOCK`、`READY_FINISH_TRADE` 和保存屏障转换为类型化事件；把 `SET_MONS_TO_TRADE`、`START_TRADE` 和 `_commit()` 的调用集中到 gate release 回调，并让 `_commit()` 保持 `CONFIRM_FINISH_TRADE` 的唯一出站路径。两套 `HostSession` 加脚本子机先跑一笔 happy path，再跑 No、拒绝、重选、单边断线和每个持久化边界的崩溃用例。

每个实现 PR 必须同时交付：协议 schema 和测试向量、状态转移表、双端关联 journal、命令审计字段、故障注入结果和现有交易/runtime 回归结果。没有这些证据时，代码即使能显示交易动画，也只能标为实验分支，不能称为正式交换。

## 6. 保存、结果核验与连续交换

### 6.1 完成判据

远程模式不用原有 `commits` 判定成功。至少分开记录：

1. `ANIMATION_FINISHED`：观察到本机 `READY_FINISH_TRADE`。
2. `SAVE_PROGRESS_OBSERVED`：观察到本地正确顺序的保存屏障与阶段转移。
3. `POST_TRADE_SNAPSHOT`：从本机重新请求、实际收到交换后的队伍和相关数据。
4. `COMPLETED`：两侧都满足前述条件，交换结果通过核验，双方完成记录已确认。

超时、TCP ACK、RFU ACK、导出了 `.pk3`、原有 `commits += 1` 或仅一侧回到菜单，均不能替代此判据。

运行时最多据协议观察报告完成。宣称持久化行为可靠，需要实机验收时双方正常退出后关闭/重新打开游戏，确认从存档加载后的结果。没有直接读盘证据时，不显示“已验证物理存储写入”。

### 6.2 如何核对宝可梦

开始前以实际收到的字节绑定选择。开始后以两台 Switch 新发回的真实快照为准，不在 PC 内做一次列表 swap 就当作新队伍。

校验双方被选槽位确实接收了对端个体，未选槽位没有非预期变化；比较 PID、OT ID、物种/进化关系等，并允许经过明确建模的游戏正常变化。不能要求交换前后完整 100 字节完全相同，也不能只凭 PID 就宣称同一对象。

游戏交换会处理亲密度、信件绑定，后续还可能发生进化；核验规则必须列出允许变化，未支持情形在开始前拒绝或明确标为未验证。[上游 TradeMons 与交换场景实现](https://github.com/pret/pokefirered/blob/master/src/trade_scene.c)

首版限制非进化、无信件个体是缩小验证范围，不是删除 mail/ribbon 数据通路。扩展版本再加入交换进化、持有物消耗、蛋、信件和跨语言用例。

### 6.3 连续交换

单笔稳定后才能开放。一笔完成后双方必须重新逐块交换实际队伍，更新快照，再允许下一轮选择。新一轮可合法选择刚收到的宝可梦，不能继承现有文件模式“offered slots 不重复”的限制。

每轮独立 `trade_id` 和确认记录；一轮状态不明确即停止后续轮次。最后退场复用现有房间等待、close-link 确认与宽限，不因 TCP 关闭直接切断本地无线。

## 7. LAN 协议与运行时

### 7.1 传输选择

首版使用一条有序 TCP 连接，采用标准库 socket，保持现有 Python 依赖；不引入 UDP 自制可靠层、WebRTC 或 QUIC。业务块很小，首要问题是阶段正确性与等待预算，不是吞吐量。

PC A 监听用户选定的 LAN 地址和端口；PC B 主动连接。端口建议 `24873`，作为可配置默认值，必须检查占用，不假定系统已放行。

第一版只接受可信局域网，不自动修改防火墙、不监听全部接口、不扫描整个子网。两台 PC 优先使用有线网络；ESP32 只承担各自的 Switch 无线链路，不同时充当 LAN 路由器。

### 7.2 帧与字段

拟定帧为 `4 字节大端长度 + UTF-8 JSON 消息 + 认证标签`。固定小二进制字段用 Base64，暂不压缩。协议解析器需处理半包、粘包、EOF、非法 JSON 和解码异常，不允许 pickle 或任意对象反序列化。

| 字段 | 作用 |
|---|---|
| `protocol_version`、`capabilities` | 显式兼容性校验，不依赖双方恰好运行同一个脚本 |
| `room_id`、`run_id` | 房间和本次无线会话身份；重建无线会话必换 `run_id` |
| `sender_id`、`seq`、`ack_seq` | 发送方、方向内序号与应用接收位置 |
| `trade_id`、`selection_epoch` | 业务轮次；准备阶段允许 `trade_id` 为空 |
| `type`、`phase`、`payload` | 受 schema 约束的事件类型、阶段、内容 |
| `snapshot_id`、`digest` | 绑定呈现给玩家的数据，防止旧队伍/旧选择混用 |

长度上限建议 16 KiB/帧；更大的诊断抓包不走控制通道。收到长度后先检查上限，再分配缓冲。块类型有单独长度检查；合法 JSON 不代表合法游戏数据。

核心消息：

| 消息 | 用途 |
|---|---|
| `HELLO`、`AUTH`、`ROOM_READY` | 协商、配对与硬件准备 |
| `LOCAL_LINK_STATE` | 本地发现、连接、掉线与阶段摘要 |
| `PHASE_READY`、`PEER_BLOCK`、`SNAPSHOT_READY` | 分块交叉交换与完整性门控 |
| `SELECT`、`CONFIRM`、`REJECT`、`CANCEL` | 玩家意图；全部绑定适用快照/epoch |
| `PREPARE`、`PREPARED` | 开始前的双端准备记录 |
| `DECISION`、`DECISION_STORED`、`RELEASE` | `start` / `finish` 两类持久化授权 |
| `ANIMATION_FINISHED`、`SAVE_PROGRESS`、`POST_TRADE_SNAPSHOT` | 来自真实本地链路的进度与结果 |
| `RESULT`、`RESULT_ACK`、`CLOSE_REQUEST`、`CLOSE_RESULT` | 双端结果收敛及退场 |
| `PING`、`PONG`、`ERROR` | 连通性、延迟与分类故障 |

`ack_seq` 表示消息被协议端接收，不能代替 `PREPARED`、`DECISION_STORED` 或游戏阶段完成。相同序号/事件键且内容相同可幂等回应；相同键但内容不同属于协议错误。

业务消息只能在允许的阶段生效。对过期消息记录并忽略，对越阶段的开始/完成授权拒绝并停止本轮。TCP 的有序性不能代替这种检查，也不能带来跨进程“恰好一次”保证。

### 7.3 配对与访问边界

房主生成随机、一次性、至少 128 bit 的房间密钥，通过用户现有可信渠道传给另一人。不要用六位数字作为唯一认证，也不要把密钥放进普通日志、抓包摘要或进程命令行。

LAN alpha 使用标准库 HMAC 做随机挑战应答及逐帧认证：认证绑定版本、房间、双端 nonce、方向和序号；长度与原始消息字节共同验签。具体编码在 P1 固定并配测试向量，不能两端分别凭字符串拼接实现。会话派生值采用明确的域分离，不自行设计加密算法。

这一模式的业务内容仍是明文，不能抵御获准参与的恶意 PC，也不能提供保密性。只用于可信 LAN；公网版本必须使用经过验证的 TLS 通道和明确的对端身份校验。

两侧各自使用本地所需 `prod.keys`。Nintendo 密钥、整个存档和不相关文件都不发给房间对端或未来中继。默认只传完成此交换所需资料。

### 7.4 不阻塞本地无线循环

LAN socket 的收发和认证放到单独 I/O worker；主线程独占 `HostSession` 和交换引擎。双方通过有界消息队列交流，worker 不直接改引擎状态。日志落盘也经有界 worker 返回明确的 `durable` 结果，不能在 RFU tick 内做 `fsync`。

主循环每轮有上限地消费事件，然后继续 `peer.tick()`、无线收发及当前活动。通过新增小型控制事件钩子接入 `HostApplication`，保留原来的关闭处理。

等待远端时仍按既有协议维持本地 Pia、Reliable 和 RFU echo，只暂停尚未获准的业务推进。不能统一 `sleep`、停止所有 RFU tick 或伪造下一轮 standby。

保留默认 `59.727 Hz` 和现有 outstanding/backpressure 约束，不靠降低 tick 掩盖等待。队列满时停止接收新业务并报错；不能丢弃已接受的关键块或开始/完成指令。控制消息保留容量，诊断输出可限流。

LAN 心跳建议每秒一次，连续 3 秒无有效消息进入连接异常，5 秒进入断线判定；这些是控制面初值，不代表游戏能等这么久。各游戏阶段的更短等待预算以 P0 实测为准。人类选择等待与网络故障分开计时。

## 8. 断线、崩溃与不确定结果

首版不做活跃交换的自动断线续传，也不从日志重放 `START_TRADE`。新的 TCP 连接不能直接接管旧无线会话。

| 故障时机 | 处理 | 是否自动重试交换 |
|---|---|---|
| 配对前或尚未建立本地链路 | 关闭未完成房间，允许重新配对 | 可重新建房，不算重试交易 |
| 资料交换/选择阶段，确定未释放开始授权 | 尝试原生取消或有界关闭，确认本地状态后新建会话 | 不在旧会话盲重放 |
| 决策已落盘，但无法证明两端均未收到开始命令 | 标为 `IN_DOUBT`，保留证据 | 不可 |
| 任一侧可能已开始动画，或仅一侧报告完成 | 保持能维持的本地链路，不猜测缺失的对端事件；超时后提示人工核验 | 不可 |
| 完成释放已获有效授权，正在本地保存 | 尽可能继续已授权的本地保存屏障，禁止为等 LAN 而中断本地保存 | 不可 |
| 一侧有交换后快照、另一侧未知 | 结果为 `IN_DOUBT`，不显示全局成功 | 不可 |
| 双方已核验完成，最终结果 ACK 丢失 | 已知侧保留自己的证据，未确认侧显示等待核验；只对账，不重新交易 | 不可 |
| 两侧完成后退场通信失败 | 单独报告退场故障，保留已核实结果 | 不可重复原交易 |

本地无线掉线、ESP32 拔出、用户强制停止、worker 崩溃和 LAN 掉线分别记录。不能把“没收到对方完成”推导成“对方没有交换”。

恢复入口只展示双方最后状态、授权、快照摘要及结果证据，帮助核对游戏实际状态。禁止自动恢复旧存档、回写宝可梦或再次发送原始个体作为“补偿”，以免复制或丢失。

日志建议放在 `pokeldn.app.paths.DATA / remote / <run_id>`，继续尊重 `POKELDN_DATA`。每笔交易保留阶段事件、摘要和关键持久化决策；损坏或不完整尾记录按不确定处理。

默认日志不打印完整宝可梦、SID、密钥或完整抓包。原始队伍快照只作为显式启用的本地诊断文件，不能称为完整存档备份；分享诊断包前应给出脱敏摘要。

## 9. 代码组织与改动边界

### 9.1 计划新增

| 路径 | 责任 |
|---|---|
| `pokeldn/frlg/remote/config.py` | RemoteTradeConfig、地址、配对、实验限制与校验 |
| `pokeldn/frlg/remote/protocol.py` | 消息 schema、编码、验签、长度/序号/阶段字段验证 |
| `pokeldn/frlg/remote/transport.py` | TCP worker、队列、心跳与断线事件 |
| `pokeldn/frlg/remote/coordinator.py` | 无 socket 的双端交易状态机和决策 |
| `pokeldn/frlg/remote/policy.py` | 本地游戏事件、对端数据提供、角色映射及门控 |
| `pokeldn/frlg/remote/journal.py` | 追加日志、durable ACK、崩溃记录检查 |
| `pokeldn/frlg/remote/app.py` | 组装现有无线 runtime、远程策略与协调器 |
| `bin/frlg_remote_trade.py` | 薄 CLI：建房/加入、参数校验、启动 |
| `tests/test_frlg_remote_*.py` | 编码、角色映射、协调器、双链路与崩溃测试 |

先放在 FRLG 归属内；不因未来可能支持其他游戏就提前抽一个全项目远程框架。

### 9.2 现有代码的必要调整

`HostTradeEngine` 增加可选的业务策略入口，明确允许“远程策略提供数据”的构造方式；文件模式仍保留当前 party 参数及校验。需要拆出的边界限于请求/提供块、选槽、开始、完成授权、取消和结果观察，不整体重写 RFU 或 battle/chat 分支。

远程策略只接受已校验的原始记录与类型化事件，通过显式方法交给引擎。不要在 CLI 中写循环修改 `_expected`、`_words`、`self.party` 等私有字段；也不要用大量覆写私有方法的子类复制半个主机引擎。

通过现有 `HostSession(engine=...)` 注入；`HostApplication` 仅增加构建活动/消费控制事件/报告远程结果所需的钩子。现有文件交换的行为、输出和默认时序保持不变，以回归测试约束。

`TradePlan` 不扩充远程可选字段；新增 RemoteTradeConfig 分离 LAN 角色、discovery 身份和实时游戏身份。远程模式没有 `--party`、`--slot`、`--fresh-pid` 或 PKHeX 输入流程。

### 9.3 CLI 形态

以下为拟议接口，当前不能运行；本阶段只编写方案，不创建这些命令。

```powershell
# PC A：明确选择本机 LAN 地址，房间密钥交互显示/输入
$env:POKELDN_RADIO = "esp32:COM5"
python bin/frlg_remote_trade.py host --listen 192.168.1.10 --port 24873 --channel 1

# PC B：选择自己的 ESP32；密钥从交互提示或本地 secret 文件读取
$env:POKELDN_RADIO = "esp32:COM7"
python bin/frlg_remote_trade.py join --connect 192.168.1.10 --port 24873 --channel 6
```

`POKELDN_RADIO` 是现有机制；COM 端口和 IP 仅为示例。Linux/macOS 使用本机设备路径，不改变现有 radio 配置约定。

两台 Switch 均选择 Join Group，分别连接身边 PC 发布的房间。两组设备近距离测试时使用不同的 discovery 名称和合适的 2.4 GHz 信道，显示本地参与者标识，第二个参与者不得进入本轮活动。信道配置不能代替身份确认，也不能宣称完全消除无线干扰。

### 9.4 GUI 放在 CLI 实测之后

在 [tool catalog](../pokeldn/app/catalog.py) 增加独立 FRLG Remote Trade 入口，继续使用现有参数、设备选择和运行记录体系。

界面仅需建房/加入模式、地址/端口、配对、两端状态、当前交换摘要和结果记录。选择与 Yes 来自 Switch。停止按钮在开始前请求取消，在动画/保存中先提示当前风险并请求有序收尾；强制停止是单独的明确动作。

不再把该功能呈现为“从文件提供宝可梦”。房间密钥不写入普通设置或运行日志；进度使用类型化事件，不通过匹配英文日志猜状态。

## 10. 分阶段实施与验收

以下是工作量范围，不是交付日期；实机时序问题可能改变估算。各阶段可拆为独立 PR，P0 不通过就不进入实际交换发布。

| 阶段 | 工作内容 | 验收/停止条件 | 估算 |
|---|---|---|---|
| P0 可行性探针 | 固定双端本地基线；验证身份门控、逐块交叉交换、角色映射 | 核心实机路径已跑通；修复正常退出证据竞态后重跑核验器；全程禁止 START | 已完成核心路径，证据复跑待完成 |
| P1 协议与协调器 | 编解码、配对、队列、journal、纯事件状态机、start/finish 双门 | 无硬件测试覆盖单边确认、拒绝、重复、旧 epoch、崩溃窗口；双端不错误推进 | 3-5 工程日 |
| P2 双链路集成 | 将正式策略接入引擎，搭建两套 HostSession + 脚本子机 | 正确穿过完整选择/确认/保存/刷新/退出，现有单机用例不退化 | 3-5 工程日 |
| P3 双实机单笔 | 同一 LAN，一房一笔，普通宝可梦 | 20 笔符合范围的交换全部核实正确，双方重新加载存档后抽检；每次异常都有明确状态 | 2-4 工程日 |
| P4 故障与兼容性 | 时延、断线、崩溃、正常拒绝、连续交换和特殊个体 | 没有假成功、旧确认复用或自动重放；支持矩阵按实测填写 | 3-6 工程日 |
| P5 GUI 与发布 | catalog、结构化运行状态、恢复查看、文档 | Windows 主路径与第二系统冒烟通过，用户可完成配对到退场 | 2-3 工程日 |
| P6 公网 | TLS 中继、房间服务、跨网压测 | LAN 标准仍满足，增加公网故障测试；单独评估工期 | 不提前估算 |

P0 可使用最小回环/临时 LAN 传输做探针，但只能传结构受限的实验消息，不开放实际开始交换能力。探针不需要先实现 GUI、互联网账号或完整配对服务。

每阶段的产物包括代码、测试、双端关联日志和一页实测结论。实测说明应区分：离线模型通过、单机本地通过、双端 LAN 通过、公网通过。

涉及共享引擎时，先通过相关检查；达到可发布的大改时按项目约定提交、推送并走现有 PR/Actions 流程。本文档本身不代表已完成发布。

## 11. 验证矩阵

### 11.1 自动化验证

- 协议：半包、粘包、超长、错误 Base64、长度不符、未知类型/版本、错误认证、序号重用、旧房间消息。
- 角色映射：两侧 LinkPlayer、parent block owner、选择槽位、单方和双方取消；未知记录字节保留。
- 分块：LinkPlayer/party 同长度不可混淆；对端慢一块、本地 idle 提前到、mail/ribbons 非零、阶段错序。
- 选择：双方先后选择、单侧 Yes、No、游戏拒绝、取消后旧确认、选择空槽、队伍刷新后的旧摘要。
- 授权：两个 `PREPARED` 前不能开始；两个真实完成事件前不能完成授权；重复消息只形成一次有效动作。
- 结果：`commits` 增长或导出文件不能触发远程成功；保存中断和缺一侧后快照必须保留不确定结果。
- 崩溃：每次落盘前后、发送前后、仅一侧收到 RELEASE、ACK 丢失；恢复程序不重放交换命令。
- 资源：队列溢出、worker 停止、无线 hole guard、设备消失、退出超时，不形成无限等待或忙循环。
- 回归：现有文件交换、Mystery Gift runtime、Union Room/battle 活动的注入和清理不受影响。

复用 [脚本子机与 ImpairedRadio](../tests/test_host_end_to_end.py)、[引擎测试](../tests/test_host_trade_engine.py)、[runtime 测试](../tests/test_host_app_runtime.py)。扩展脚本子机以模拟真实拒绝、等待消费、mail 和较慢保存，不能仅让两个复制了同一错误假设的模型互相通过。

建议增加 `test_frlg_remote_protocol.py`、`test_frlg_remote_policy.py`、`test_frlg_remote_coordinator.py`、`test_frlg_remote_journal.py`、`test_frlg_remote_end_to_end.py`。实现阶段按模块运行，再执行相关 FRLG/shared-runtime 回归；本次文档修改不等于这些测试已经存在或运行。

### 11.2 时延与故障注入

| 条件 | 期望 |
|---|---|
| RTT 0/10/30/50 ms，额外抖动 0/10/20 ms | LAN 目标范围，测试内正确完成，不丢选择和确认 |
| RTT 100/200/500 ms | 探索各阶段边界，未测通过前不写入支持承诺 |
| 一侧入室晚 5/15/30 秒，确认晚 5/30/120 秒 | 入室能受控重试，选择等待不触发假确认；测出每阶段真实上限 |
| LAN 短停 100/500/2000 ms | 根据阶段继续等待或受控失败，不能用超时补齐对端事件 |
| 网络层 1%/3% 丢包、重传和抖动 | TCP 负责字节重传，应用检验背压与时延；不假装 TCP 会交付乱序字节 |
| 协调器层重复/晚到/过期事件 | 使用假 transport 注入，验证业务幂等与 epoch 防护 |
| 每个关键阶段断 LAN、拔板、杀进程 | 结果分类正确，无自动复制、补偿或重放 |

无线损伤与 LAN 损伤分开注入。先测试单一变量，再组合测试，报告实际 RTT、tick 延迟、队列峰值、Reliable outstanding、阶段持续时间和错误阶段。

现有文档中的低空口帧率成功记录不能当作“支持 200 ms 网络延迟”的证据；LAN 等待出现在不同层次，必须另外测量。[现有 RFU 时序记录](frlg_link.md)

### 11.3 实机顺序

1. 每套 PC + ESP32 单独通过当前本地交换基线，排除设备问题。
2. 两台 PC 配对，两台 Switch 仅交换身份和队伍，然后取消。
3. 首次实际交换使用容易辨认、无特殊机制的普通个体，双方记录交换前后槽位和摘要。
4. 双方完成、正常退场、重新打开游戏核验存档；首笔不使用珍贵或唯一个体。
5. 累积单笔成功样本后验证拒绝/取消；危险阶段故障测试使用可承受损失的专用测试存档。
6. 再测试交换进化、信件、蛋、跨语言、连续交换，更新支持矩阵，不把未验证组合自动标绿。

## 12. 从 LAN 扩展到公网

LAN 稳定后，优先公网中继，不先做 P2P 打洞。两台 PC 都主动连中继，普通家庭网络无需手工开放入站端口；业务层仍使用相同的双端状态和快照协议。

中继负责房间匹配、鉴权、限流和消息转发，不生成宝可梦、不替玩家确认，也不接管本地 RFU。交易协调权仍固定在一个端点，不能出现房主与中继各自作决定的双主状态。

公网新增 TLS、证书验证、房间有效期、资源配额和中继故障测试。TLS 到中继不等于端到端加密；若要防中继看到玩家数据，需要另行设计和评审端到端加密，不能默认已有。

优先使用单个就近中继，先验证更高 RTT 下 LinkPlayer、分块、确认和保存预算。公网掉线仍按 `IN_DOUBT` 处理，不能因为有服务器就宣称可以回滚或无缝恢复交换。

后续对战应单独写设计：指令流、随机状态、动作同步和双方角色约束与交易不同。不能把本方案的“块与决策桥接”直接宣传成通用远程对战支持。

## 13. 建议下一步

P0 的核心数据路径已达到这一目标；修复 shutdown race 后先重新生成双端证据，再进入正式交换的 P1。正式交换实施顺序是：先交付无 socket 的状态机和 journal，再接入两套本地主机，最后才允许 start/finish 两道 release gate 调用真实游戏命令。

P0 报告至少回答四个问题：

1. 两个本地主机的角色映射是否正确，需修改哪些字段？
2. 逐块交叉转发是否无死锁，发送完成与游戏消费如何区分？
3. 双方不同步入室时，最先超时的是哪一层，可否受控重试？
4. 哪些阶段能等待对端，最大已测等待时间是多少？

正式交换仍需回答四项 P0 之外的问题：双方确认是否能稳定对应当前 snapshot、两道 release gate 是否在重复/延迟事件下保持单次、保存后快照是否真实反映双方队伍、每个危险窗口能否明确归类为 `CANCELLED` 或 `IN_DOUBT`。在这些问题有自动化和实机证据前，不能把 P0 的“数据可达”升级成“交易可用”。
