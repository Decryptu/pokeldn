
<a id="trading-with-a-retail-sword-and-shield"></a>
# 使用零售剑和盾进行交易

从快照交换到保存的剑和盾链接交换。成帧、内容注册和PK8在[同步框架](swsh_protocol.md)上。

<a id="the-sequence"></a>
## 顺序

    1  the console broadcasts its 3456-byte snapshot on protocol 0x84, port 0
    2  the client acknowledges the fragments (0x21) and the transfer (0x19 / 0x28)
    3  the client sends its own snapshot on 0x84 port 1 and reports it complete
    4  the trade screen opens
    5  the console sends the 40030 RPC pair on 0x7C port 1, several times a second
    6  the client answers the pair and sends `imReady` on 20030
    7  the console offers a Pokemon on 20030; the client offers one on 10050
    8  the player accepts (box command 4)
    9  the confirmation ladder runs on content 40
    10 the console writes its save
 主机游戏机未确认端口 0 上发送的加入方快照；方加入在端口 1 上进行。在其 0x84 得到应答之前，游戏机不会发送任何其他内容并无限期地重新传输。
`pokeldn/ldn/broadcast4.py` 实现了全部四种。

保存后的内容位于[托管交换](#hosting-a-trade)和[主机迁移](#host-migration)下。

<a id="the-trade-rpc"></a>
## 交换 RPC

ping、阻止消息和提议使用端口 0，40030 对端口 1；不会读取错误端口上的答案。

    id 40030 = 40000 + 30
      1  offset      30
      2  base        10000, and 20000 in the other member
      3  station id  the sender's, equal to the host_constant of the seat record
      4  clock       a counter advancing between messages
      5  bytes(4)    00000000 for the 10000 member, 000018fc for the 20000 one

`000018fc`是哨兵`0xfc18`（[步体](#the-step-body)）。游戏机的消息从解析的字段中逐字节重建（`pokeldn/swsh/trade.py`）。 `3e4e000012020801` 是 20030，携带 `imReady{isReady:true}`。加入的客户端发送它；游戏机作为主机，然后显示提供的宝可梦以供确认。尚未发现托管游戏机发送该消息。

- 每个答案发送一次（`--answer-once`）；在计时器上重新得出答案会重新发送提议。
- 读取器不得引发：可靠窗口上的网格消息（`44 00 01`，[主机迁移](#host-migration)）不是交换消息，并且引发的读取器结束接收任务和交换（`la communication avec l'autre joueur a été interrompue`）。 `trade.py` 中的读者返回 `None`。

<a id="host-migration"></a>
## 主机迁移

离开会话的托管 剑 请求协议 0x18 端口 1 (`nn::pia::mesh::LeaveWithHostMigrationJob`) 上的主机迁移：

    0f 00 00 03 00 01 00 01   44 00 01
    ^ version 4's reliable header, sequence 1     ^ the mesh message

`44` 为 MIGRATION_START、`[0x44, host index 0, new host index 1]`：游戏机将客户端命名为主机 (`nn::pia::mesh::LeaveWithHostMigrationJob`)。指定的客户端必须广播
`MIGRATION_FINISH` 位于网状端口 1 的可靠窗口上（[Pia 层](pia.md#host-migration)）。

使用 `--answer-migration --update-mesh`，客户端发送完成信息并在其新主机索引下发布网格更新。切换后保留会话未经验证。

托管零售 剑 在两种情况下发送 MIGRATION_START 一次：

|当 |状况 |
|---|---|
|其框命令 3 | 后 0.8 秒完成交换后 |
|玩家接受后几秒钟，游戏机以 `2-ALZAA-0016` 崩溃之前 |在梯子之前失败的交换，加入方没有发送确认命令|

`bin/swsh_host.py --migrate`通过box命令3和MIGRATION_START结束自己的托管交换；保存后，模拟的 盾 加入方会显示通信中断消息。默认情况下，主机保留会话。

<a id="hosting-a-trade"></a>
## 举办交换会

`bin/swsh_host.py` 主持，`pokeldn/swsh/host_trade.py` 作为主持 剑 领先。零售版 French 剑 1.3.2 和仿真版 盾 1.3.2 分别加入并交换。下面的详细信息是从两个模拟 Shields 1.3.2 之间的交换中读取的。

主机使用新的网络 ID、设备 ID 和帐户 UID 构建站广告。在0x84上，它确认加入方的三个快照片段，用其训练者身份和`--offer-file` PK8重写该实时快照，然后在端口0上发送结果。主机将游戏机提供的PK8写入`--received`。 `--advert FILE` 和 `--snapshot FILE` 保留已保存记录路径以供比较。

站握手，主机侧：

    joiner -> host   connection request, [1] a random byte per request
    host   -> joiner ack (05 000000 and the request's trailing id)
    host   -> joiner its own request, the joiner's [1] at [0x10]
    joiner -> host   ack, then its connection response
    host   -> joiner ack, then its response
 未确认，加入方重复其请求并且从不回答主机的请求；不匹配的 [0x10] 将被忽略。网格加入后，加入方每两秒发送一次同步时钟（0x1C）和一个克隆时钟（0x77）；主机以请求的滴答声和以毫秒为单位的网格时钟进行应答，并以 01、请求字节 1 到 9 和以毫秒为单位的克隆时钟进行应答。

应用层，在[ping握手](swsh_session.md)之后双向：

    0x84  each side's snapshot, the joiner's on port 1 and the host's on port 0; `host_trade.py`
          builds its own from the joiner's and sends it second, a retail host sends first
    110   the joiner pings first once its trade screen is up; the host answers with its own ping
          and the reply (a host ping before that screen is acked and dropped)
    30    the host opens content 30; each side offers on 20030 and sends box command 1; each
          acceptance is box command 4
    130   the joiner pings first
    50    the host publishes its Pokemon as element 0 and relays the joiner's 10050 as element 1
    120   the host pings first
    40    the ladder: host commands as element 0, the joiner's 10040 as element 1, phases 0 to 4

<a id="the-trade-animation"></a>
## 交换动画

游戏机在最后一个同步命令 40 (`3`) 之后播放交换动画，期间没有交换消息。加入 `bin/swsh_host.py` 的零售剑在同步命令后 1.2 秒开始动画，并在大约 24 秒时给予玩家控制权。它不会发送任何应用程序消息，直到玩家退出盒子（盒子命令 3）。

<a id="trades-in-a-row-on-one-session"></a>
## 一个交易日连续交易

一个会话可连续进行多次交换。交换状态 9 发送事件 7（成功）或 8（失败），在 `0x010ca360` 写入状态 0，玩家回到盒子界面。内容 30 和 ping 110 存活整个会话（由会话初始化 `0x010c9280` 构造一次）；内容 50、40 及各自的 ping 每次交换都会重建：

| 对象 | 生命周期 | 代码 |
|---|---|---|
| 内容 30、ping 110 | 整个会话 | `0x010c9280` -> `0x010cca10` |
| 内容 50、ping 130 | 一次交换 | 交换状态 1 → `0x010d5440` → 初始化 `0x010d4d90`（新内容，旧对象释放），阶段 0 的 `0x010d53fc` 创建元素；状态 3 由 `0x010d54b0` 拆除 |
| 内容 40、ping 120 | 一次交换 | 状态 6 → `0x010dabc0` → 初始化 `0x010da470`；状态 8 由 `0x010dac90` 释放 |
| 内容对象的 SyncPing | 对应元素的生命周期 | 创建函数 `0x006d44e0` 用 ID 偏移 + 0x50 构造新 SyncPing（`0x006d46d0`），并销毁旧对象（`0x006cd940`） |

已经达到同步状态的 SyncPing 不会原地重置，因此主机没有内容 50 时发送的 ping 130 不会到达任何持有者。

盒子界面的步骤状态机（`0x00aa5160`，表 `0x2059218`）读取监听器 `0x00c8d900` 设置的对方盒子命令标志。在步骤 3 收到对方标志 1（交换提议）时，同时清除标志 1、4（`0x00aa5688..0x00aa569c`）；步骤 7 等待标志 4（`0x00aa5628`），只有步骤 10 才发出动作 6、启动交换状态 1。因此，与提议同一批发送的盒子命令 4 会被清除，主机停在步骤 7，显示“En attente d'une réponse”（等待回应）。对方命令 4 必须在主机处理提议之后到达：`pokeldn.swsh.host_trade` 仅在收到加入方的 4 后发送自己的 4；加入方启动器则回应主机端的 4。

玩家按 B 也会结束步骤 7；没有计时器结束它。步骤状态机的界面是 `[this+0x80]` 处的 View_Model（`0x00aa4e78`，虚函数表 `0x25376d8`）。输入处理函数 `0x00aab0b0`（槽位 16，由 `0x00efad28` 的界面调度器调用）在 `ui+0x5d0` 已启用且本帧按下掩码包含第 49 位时设置 `ui+0x5cc = 1`；重映射表 `0x02062928` 仅由 B 键产生该位。步骤 2、6 在提议及接受后启用它（`0x00aa5434`），每次更新都会清除它（`0x00aa5608`）。步骤 7 按下时清除对方标志、发送盒子命令 5（撤回接受），并离开流程（`0x00aa57d0`）；步骤 3 则发送盒子命令 2。

在盒子命令 5 之前收到的对方提议和盒子命令 1，会随标志一起清除；游戏机的下一次提议停留在步骤 3，直到再次收到它们。`pokeldn.swsh.host_trade` 和 `bin/swsh_connect.py` 在收到盒子命令 5 后重新发送自身提议及盒子命令 1。实机《剑》作为任一角色，提出、接受、按 B 撤回后再次提出，交换均完成；不重发时停留在“En attente d'une réponse”（等待回应）。

后续每次交换都会重复自身交换流程：双方提议与盒子命令 1、按上述顺序发送的两个盒子命令 4、ping 130（加入方先发送）、阶段 0 的新内容 50、ping 120、从阶段 0 到 4 的新内容 40。交换之间不会出现 0x84 快照、ping 97 或 110、盒子命令 3、内容 30 发布。`bin/swsh_host.py` 和 `bin/swsh_connect.py` 配合重复的 `--offer-file`，分别与零售版《剑》的加入方及主机在同一会话内，每次交换一条排队记录；游戏主机离开后，主机端关闭。

`bin/swsh_connect.py` 配合重复的 `--offer-file`，将完整阶梯结束后（40040 的阶段 4）主机的提议视为下一次交换。它用下一条记录回应该提议，此时主机盒子流程已处于步骤 3 并持有自身提议，然后清除每次交换的状态：已回应的 40050、40040 克隆对及消息体、确认命令队列、选择提议锁存状态。40030 克隆对与 ping 回应会保留。`bin/swsh_host.py --accept-first --lead
SECONDS` 模拟游戏主机的玩家（先接受，交换后从盒子提供下一条排队记录）；两个启动器在模拟开发板上的同一会话中双向各交换两条记录（`tests/test_esp32.py`）。

零售版加入方玩家在盒子中按 B 时，主机发送盒子命令 2、3 及网状网络 `0401`，随后取消认证，不显示错误；再次搜索时可加入同一个主机端网络（相同网络 ID）。搜索中的主机会加入任何通过[匹配规则](swsh_session.md#how-a-searching-sword-finds-a-partner)的网络。

<a id="the-box-state-machine"></a>
## 盒子状态机

内容 30 包含从交换屏幕到提议的所有内容。 `onBoxSyncStateCommand`
`0x010ce180`，0x50 字节包装器的插槽 1，位于 `session+0x120`（虚表组 `0x2625808`）：

1. 忽略自身的echo（`sender == [[0x2616a30]]+0xf0`）；
2、`if ((msg->data - 1) > 5) return`：0、7及以上静默掉线；
3. 跳转表`0x2067bec`：连线命令*N*通知每个监听器事件*N*。

字段 1，`boxSendPokemon`，作为事件 0 进入插槽 0 `0x010ce080`。调度程序采用 0..6；发送者发出 1..5。

监听者`0x00c8d900`设置`[owner + 0x218 + code] = 1`；代码2首先清除代码1的标志（`+0x219`），代码5清除代码4的标志（`+0x21c`）。 1个提议，2个撤回提议； 4 人确认，5 人撤回
4. 玩家在确认屏幕上的主机游戏机在加入方发送命令 1 然后 2 后开始离开四秒。

发送者 `0x010cda70(content, command)` 位于包装器 `0x010cde90` .. `0x010cded0`（命令 1 到 5）后面，由场景的跳转表 `0x00a96d10` 的操作 `+0x78` 驱动：

    action 1  ->  command 3
    action 2  ->  the Pokemon (0x010ca430), then command 1
    action 3  ->  command 2
    action 4  ->  command 5
    action 5  ->  command 4
    action 6  ->  0x010ca640, which stores its Pokemon and sets the trade state to 1
 两扇静音门守护着发送：

    [content+0x48] a pending command; a different one arriving sets the error byte [content+0x4d]
                   and sends nothing
    [content+0x4c] channel ready, set by 0x010ce040 on result 0; while clear the command waits in
                   +0x48 and never goes out
 命令 3 是开场白。每帧更新 `0x010c9bb0` 在其状态切换之前运行：

    if ([session+0x418]) { if (![session+0x419]) send command 3; [session+0x418] = 0; }
 设置 `0x010c9280` 设置 `+0x418 = 1`、`+0x419 = 0x00dceea0() & 1`（来自玩家列表）：恰好一侧发送命令 3。`--box-open` 在 0x84 ack 处发送盒子命令。

<a id="the-trade-state-machine"></a>
## 交换状态机

`[session+0x140]`，范围 1..10，表 `0x2067b68`：

    1  0x010c9c78  -> 0x010ca0a0: start content 50 and send its Pokemon; true -> 2, false -> 9
    2  wait        5  wait        7  wait
    3  0x010c9f60  the Pokemon exchange (0x010d54b0 on content 50), then 4, or 9 on error
    4  0x010c9c9c  0x01109320 decides; false -> 6
    6  0x010c9f84  -> 0x010ca1ac: install four delegates and start content 40
    8  0x010c9fa8  0x010dac90(content40, session+0x170, session+0x210): unhook from
                   [content+0x20]+0x60, [content+0x28]+0x60, release 0x010daac0; -> 9
    9  0x010c9ef4  terminal: [+0x144] set means failure; listeners get event 8
    10 0x010ca838
 盒子回调 `0x010ca800` 会丢弃事件，除非状态为 0。状态 2 在委托中结束
`0x010cc380` (`session+0x2e0`)：合作伙伴的宝可梦到`session+0x70`，一条0x60字节记录(`0x010f5cc0`)，状态3。中止在状态1开始：当内容50的初始化时`0x010d4d90` (`mov w2,
#0x32`) 失败，其发送的 `0x010d5440` 不执行任何操作，并且调用者设置 `[session+0x144] = 1`，状态 9：通信中断消息。

<a id="the-confirmation-ladder"></a>
## 确认阶梯

内容 40 是一个屏障，每个命令一个梯级。

<a id="the-phase-to-state-map"></a>
### 阶段到状态图

状态为`delegate+0x5c`，仅由init(0)、机器中的四个站点`0x010dae70`和`0x010dbf40`存储。机器将`state - 1`调度到14项表`0x2067ed0`中；状态 2、4、7、9（发送离开的位置）采用默认 `0x010db38c`，尾声，并且仅通过离开
`0x010dbf40`，它忽略 4 以上的 u16，否则索引表 `0x2067f4c`：

    phase 0  -> state 1              -> send(0), announcing 1     0x010db308
    phase 1  -> state 3              -> send(1), announcing 2     0x010db0b0
    phase 2  -> state 5 -> 6 or 8    -> send(2), announcing 3     0x010db0dc / 0x010db104
    phase 3  -> state 10 or 11 -> 12 -> send(3), announcing 4     0x010db16c
    phase 4  -> state 13 -> 14       -> 0x010db970 tears down, content+0x84 = 0xfc18; no send

`[delegate+0x58]`（`0x110e620(...) & 1`）的作用是：状态7一次发送2，倒计时`[delegate+0x60]`后状态9，xorshift抽2..302。

Vtable组`0x257fe90`：主`0x257fea0`（插槽0中SyncCommand接收`0x010dbc90`，插槽3
`0x010dbf40`)，`0x257fec8`处顶部偏移−8，次要`0x257fed8`，其插槽0 `0x010dbfd0`与`+0x50`/`+0x54`上的代码相同(表`0x02067f60`，偏移量 `0x70 0x38 0x40 0x48 0x6c`)，插槽 4
`0x010dc070` 尾调用 `0x010f8e30`，其余 `ret`。 init 会同时安装：

    0x010da6bc   add x9, x19, #8       ->  [content+0x2c0] = delegate + 8     the second interface
    0x010da6d0   str x19, [x8, #0x168] ->  the 10040 holder's listener        the first

<a id="the-pump"></a>
### 泵

`0x010db3e0`，由机器之前的内容40的tick运行，是一个17状态机
`[content+0x80]` 具有共享尾部：

    w1 = [content+0x17c]                    the content's PHASE
    if (w1 != [content+0x84] && w1 != [content+0x86])                     0x010db758..0x010db778
        { 0x010de310(content, w1); B->slot7(w1); }                        slot 7 is a ret
    w1 = [content+0x17c]
    if (w1 != [content+0x84] && w1 == [content+0x86])                     0x010db794..0x010db7b4
        { 0x010de310(content, w1); B->slot0(w1); }   <- the state setter
    0x010ddf40(content)                     the queued jobs                0x010db7d4
    0x006d4b80(content+0xd0)                the element update, last       0x010db7e8

`B` 是 `[content+0x2c0]` (`delegate+8`)。状态切换先运行；状态 0 (`0x010db740`) 跳过尾部，当 `0x006d4b30` 为 false 时，状态 16 (`0x010db730`) 提前返回。既没有提交也没有宣布的阶段会静默提交（标志和作业已清除，泵状态 2）。

|领域 |意义|写者 |
|---|---|---|
| `+0x84` |承诺阶段| `0x010de310`，它还会删除挂起的正文并清空作业队列`content+0x310`（`0x010de348..0x010de3a0`）；仅从尾部（`0x010db778`、`0x010db7b4`）和状态 14（`0x010db6ac`）调用，在相位上门控！= `+0x84` |
| `+0x86` |最后一个命令宣布的阶段 |五个发送站点仅 `0x010dbab0`、`data + 1` |
| `+0x17c` |相，`element+0xac` |构造者 `0x006d3ff8`，完好 `0x006d4500`，采用 `0x006d4ccc` |

当阶段达到 `+0x86` 时，阶梯会爬升。构造函数设置`+0x84 = 0xfc18`（`0x010dc228`、`0x010dc260`）、`+0x86 = 0`（`0x010dc25c`）；注册商将 `+0x84` 设置为 0（`0x010da810`、`0x010daa78`），铸造元素为 0（`0x010daa7c`）并留下 `[content+0x80] =
1`；泵状态 1 然后调用门外的状态设置器：命令 0，宣布 1。

泵状态（表 `0x2067f08`；`[+0x1c0]` 是元件的 `+0xf0` 通道，`[+0x2a0]` [命令](#the-command) 的命令标志）：

    1   0x010db418  element ready (0x006d4e70) -> 2; delegate slot 1, then slot 0 with the phase
    2   0x010db47c  a pending body at +0x88 -> 3
    3   0x010db48c  0x006d4f10 (all ready, every pair's low half == phase): send the body
                    (0x010de080) to station [[0x2616a30]+0xf8] -> 4
    4   0x010db4dc  0x006d3690([+0x1c0], [+0x86]) publishes the high half, must return 1;
                    then 0x018407f0 ? 8 : 7                                      cinc 0x010db514
    5   0x010db51c  the same through [+0x2b8] (0x008b7300) with [+0xa8] -> 6; dead in content 40
    8   0x010db594  0x006a2840([+0x2a0]): every station has sent a command -> 9
    9   0x010db5b4  0x006d4fb0 == 0: no resend byte set -> 10
    10  0x010db5d4  0x006d4da0 && 0x006d3060([+0x1c0], [+0x86]) (every high half == announced)
                    && 0x006d4f50; then 0x006d33b0 writes shared value = announced -> 7
    11  0x010db62c  0x006a2760([+0x2a0]) clears every flag; [+0x374] ? 12 : 2
    6, 7, 12        the default, the shared tail at 0x010db758
    14  0x010db68c  the gated commit (13, 15, 16 unread)
 状态8至10仅在主站上运行（`0x018407f0`）；其他人则选择 4 到 7 并遵循共同的价值观。 `0x010d9000..0x010df000` 中没有任何内容存储 5 到 `[content+0x80]` 或非零值到 `[content+0xa8]`（仅清除，`0x010db9ec`、`0x010dc530`、`0x010de3a4`）。 `[content+0x80]`的其他作者：

|网站 |功能|状态|
|---|---|---|
| `0x010dc234` |构造函数| 0 |
| `0x010daa9c` |登记员 | 1 |
| `0x010dbc70` | `0x010dbab0`，命令发送（需要2；写入`+0x86`）| 3 |
| `0x010de3c4` | `0x010de310`，提交；清除 `0x010de344` 处的每个标志 | 2 |
| `0x010dc7a0` | `0x010dc720`（槽位 `0x257ff70`），站点离开：存在 `[+0x374]` 时通知委托对象的槽位 4，否则从元素（`0x006d50e0`）和标志（`0x006a2140`）中移除 | 11 |
| `0x010dc6f4` | `0x010dc6c0`（插槽 `0x257ff68`），需要 `[+0x374]` 和 `0x006a2a80([+0x2a0])` | 13 |
| `0x010dccec` |插槽 `0x257ff90` | 2 |
| `0x010dcee8` | `0x010dce70`，取消接受 (`x19 = content+0x68`)，除非 16 | 2 |
| `0x010db998` | `0x010db970`，拆除 | 16 |

内容40的注册器将`w2 = 1`(`0x010da6a8`)存储在`[+0x374]`(`0x010da800`)：离开的站走11、12并结束梯子。

<a id="the-phase-is-the-elements-field"></a>
### 相位是元素的字段

`0x010c0000..0x010e0000` 中没有任何内容存储到 `content+0x17c`。注册商在 `content+0xd0` (`0x010daa4c`) 处构建 40040 元素，添加子元素 (`0x006d4ff0`) 并使用
`0x006d44e0(element, w20)`，打开`str wzr,[x0,#0xa8]; strh w1,[x0,#0xac]`：相位为
`element+0xac` (`0xd0 + 0xac = 0x17c`)，从 init 的 `wzr` 开始。

仅在 `0x006d4ca0` 中前进：

    w0  = 0x006d3260([element+0xf0])        the shared value; 0xfc18 when none
    if (w0 == [element+0xac]) done
    if (0x006d3980([element+0xf0], w0)) {   publish it as its own; on success
        [element+0xac] = w0                 the phase moves
        [element+0xa0]->vtable[0]()         and the content is told
    }
 这是元素更新 `0x006d4b80` 的尾部（每个同步泵最后调用它；内容 40 位于
`0x010db7e8`)，当`0x006ce5a0([element+0xb0])`返回1时运行。在所有站准备好之前：

    if (!0x006d2e20(shared) && !0x006da180(hash channel)) {
        if (0x018407f0([[0x2616a30]]))  0x006d33b0(shared, [element+0xac])
        0x006da3d0(hash channel, element+0xa8); 0x006d3980(shared, [element+0xac])
        return
    }

`0x018407f0` 在托管 Pia 网格的游戏机上成立（[会话](swsh_session.md#the-pia-session-object)；后端调用 `+0xe0`
`[x0 + 0x168 + [x0+0x162]*8]`）。仅它为共享值 `+0xf0` 通道的 16 位子元素（[子元素种类](swsh_protocol.md#sub-element-kinds)）提供种子；各站均采用：

    0x006d3260  read            ready [sub+0x61] ? [sub+0x88] : 0xfc18
    0x006d33b0  write(v)        0x006d3570 when not ready or body != v
    0x006d3570  publish         body [sub+0x88] = v; clock from 0x01766740 (-1: error 0x2c27);
                                [sub+0x80]->vtable[0] with (sub+0x88, 2, clock, [sub+0x62], [sub+0x68])
                                when [sub+0x80]->vtable[1]() or [sub+0x70] allows, resend byte
                                [sub+0x60] = !sent; else [sub+0x60] = 1
    0x006d2e20  all ready       the shared value and every pair
    0x006d2c20  all low == v    all ready, every pair's [sub+0x88] == v
    0x006d3060  all high == v   all ready, every pair's [sub+0x8a] == v
 写入仅保留就绪字节（仅接收 `0x006d6a08` 存储 `+0x60`；写入是
`0x006d35b8 strh w8,[x20,#0x88]!`），因此读取返回 `0xfc18` 直到消息到达；在主机上，该消息是它自己的。发布到达元素的槽 0 (`0x006d5730`)，该槽将每个站的正文排队。一次完成的交换中 40040 上的 149 个客户端消息均携带四字节主体；内容的其他形状见[确认内容的其他消息形态](#shapes-the-confirmation-content-also-sends)。

<a id="the-step-body"></a>
### 步体

内容40的elementId 20000上的四字节主体，低半部分为相位，高半部分为最后公布的：

    0x006d3980(channel, v)   body = <u16 v><u16 [sub+0x8a]>    low; from the element update
    0x006d3690(channel, v)   body = <u16 [sub+0x88]><u16 v>    high; from pump state 4, [content+0x86]
 两者在通道的`{ownerId, entry}`表中找到自己的id（`[[0x2616a30]]+0xf0`），取
`[entry+0x60] - 0x50`，并调用`0x006d3860`（`0x010dbe20`往下一层）； `[content+0x1c0]` 是
`[element+0xf0]`。观察到的梯子：

    000018fc   phase 0, announced 0xfc18   the birth sentinel
    00000100   phase 0, announced 1        the cue; command 0 already sent
    01000100   phase 1, announced 1        caught up, committed
    01000200   phase 1, announced 2        state 3 sent command 1
    02000200   phase 2, announced 2        caught up
    02000300   phase 2, announced 3        committed, sent command 2
    04000400   phase 4                     the teardown rung

`trade.parse_sync_step`、`SYNC_LADDER` 和 `sync_announced_phase` 对其进行解码。

<a id="the-command"></a>
### 命令

10040 上的 `SyncSaveDataHolder{syncCommand{data:N}}`，可靠端口 0。处理程序 `0x010dbc90` 删除无法解析的发送者 `0x006b5850` (`0xfd`)，在 `[arg1+0x14]` 处获取 int32，按站选择 `+0x38` 处的订阅者index，将 int32 传递给中继 `0x010dbe20` 和订阅者的 `+0x18`，然后始终：

    0x010dbdf8  ldr  x8, [x20, #0x18]
    0x010dbdfc  ldr  x0, [x8, #0x2a0]
    0x010dbe00  mov  w2, #1          <- a constant
    0x010dbe04  mov  x1, x19         <- keyed by the sender
    0x010dbe08  bl   #0x6a24a0
 该值仅到达继电器（一个elementId-1主体`00000000`回响`syncCommand{data:0}`）；状态仅通过 `0x010dbf40` 移动，由具有自己相位的泵调用。任何命令都会前进一个梯级。 `[content+0x2a0]` 是每站标志对象（`0x006a24a0` 有 44 个调用点）：

    0x006a24a0(obj, id, flag)   map[id] = flag & 1; map at obj+0x1c0, find-or-insert
                                (0x006a24d0 hashes by udiv/msub on the bucket count at +0x10)
    0x006a2840(obj)             1 when every station listed at obj+0x100 (count +0x108) is set
    0x006a2760(obj)             clear(): frees nodes, zeroes buckets and the size at +0x270
    0x006a2480(obj)             obj+0xc0, the station list the registrar walks
 状态8等待`0x006a2840`；提交和状态 11 清除地图。该标志设置在泵外部的网络更新的排水中：`0x006a9a20` 调用 Pia 的调度 `0x006a8380` (`0x006a9a54`)，然后调用排水 `0x006db3b0` (`0x006a9a90`, [routing](swsh_protocol.md#the-routing-path))。其调用者中 `0x00ef4a9c`、`0x01109250`、
`0x01109308`，框架`0x00f1df30`运行两个，围绕游戏更新：

    0x00f1df30  bl 0x01109240     network update: 0x01109250 bl 0x006a9a20, the drain
                bl 0x00fa09a0
                bl 0x00f1cc60     the game update
                bl 0x00793ec0
                bl 0x011092f0     0x01109304 bl 0x01111db0, 0x01109308 bl 0x006a9a20, the drain again
 内容40的命令勾选`0x010dae70`在交换场景任务中运行：`0x00c8c6b0`调用
`0x010c9bb0` 位于 `0x00c8c6d8`，调用 `0x010c9c34` 处的提议。任务调度程序通过`0x00f19770`和`0x00f19080`到达它。模拟器跟踪将此标记置于之前
`0x01109250`，然后 `0x00f1cc60`，然后 `0x01109308`。在那里耗尽的命令可以被下面的场景标记所消耗。

RequestCancel 和 RequestCancelAll 还读取了地图（[下](#the-cancel-and-proceed-messages)）。

在上一次提交之后，一个梯级需要一个命令到达主设备。在梯级 0 中，任何命令都有效，包括提示 `00000100` 上的命令；之后，提示上的命令（`01000200`，
`02000300`、`03000400`）在提交之前着陆并被清除，而被捕获的主体上的那个（`01000100`、`02000200`、`03000300`）计数：

|命令，每个新身体一个 |最后的身体|
|---|---|
| 1、关于`00000100`| `01000200`：梯级 0 |
| 4、`000018fc` 至 `01000200` | `02000300`：梯级 0 和 1 |
| 9、`000018fc` 至 `04000400` | `04000400`：交换|

`--confirm-commands 0,1,2,3,0,1,2,3,0,1,2,3` 每个新机身都会弹出一个，包括 `000018fc`；队列不能枯竭。 `answer_rpc` 身体呼应，半动也不动； `--confirm-phase N` 写入低半部分。

<a id="the-cancel-and-proceed-messages"></a>
### 取消和继续消息

30040，`SequenceDataHolder`（[协议页](swsh_protocol.md#the-30000-holder)），存储在`[content+0x2b8]`（`0x010da9b8`），监听器`content+0x68`（`0x010da9b4`， `0x010da9bc`；虚表`0x02580030`，`0x010dc238`）：

|案例 |留言 |处理程序 |
|---|---|---|
| 1 |取消接受 | `0x010dce70` |
| 2 |请求取消 | `0x010dc920`，通过thunk `0x010dcf20` |
| 3 |请求取消全部 | `0x010dcaa0`，通过`0x010dcf30` |
| 4 |请求强制继续 | `0x010dc7b0`，通过`0x010dcf40` |

每个仅当 `currentSeqNo` 等于提交阶段 `(s16)[content+0x84]` 时才起作用：

- RequestCancel，当并非每个站都被标记时（`0x006a2840`、`0x010dc954`）：作业 `0x010dd0c0` 通过 `[content+0x2b8]` (`0x008b7230`) 向发送方发送 `CancelAccepted{currentSeqNo: [+0x84], isForced: 0}` 并清除其标记（`0x010dd114`）。
- RequestCancelAll，相同的防护：每个列出的站（`0x010dcaf4..0x010dcb1c`）的作业`0x010dd190`发送`CancelAccepted{[+0x84], isForced: 1}`，然后清除每个标志（`0x010dd208`）。
-取消接受：使用`isForced`，将`[content+0x370]` mod 255步进为`0x006db470`；泵状态 2 除非 16 (`0x010dcee8`)；代表插槽 6 (`ret`)。状态2到4重新运行；相位保持不变。
- RequestForcedProceed：作业 `0x010dd040` `{content, u16 targetSeqNo, sender index}` 立即运行 (`0x010dc8a8`)，在 false 时排队 (`0x010dc8bc`)。在`0x006d4da0(content+0xd0)`之后，它调用`0x006d33b0([content+0x1c0], targetSeqNo)`，状态10的写入，没有状态8和9，`0x006d3060`/`0x006d4f50`测试或主测试；发件人索引未读。

`RequestForcedProceed` 在没有 `syncCommand`（模拟屏蔽）的情况下推进共享阶段。它不会取代确认命令：随后的命令是这些请求的梯形图在保存之前停止在“通讯”处。

作业队列 `content+0x310`（条目 `+0x350`，计数 `+0x358`）从泵 (`0x010db7d4`) 在 `0x010ddf40` 中运行；返回 true 的作业将被删除。提交将其清空。

<a id="shapes-the-confirmation-content-also-sends"></a>
### 形状确认内容也发送

40040 个没有 OwnerId 且正文除四个字节之外的信封：

    elementId 20000, no owner, 2 bytes   0000   then   0100
    elementId 1,     no owner, 4 bytes   00000000        after a syncCommand{data:0}
    no elementId,    no owner, 4 bytes   00000000  then  01000000
 该对的接收`0x006d6490`丢弃两个字节的（`cmp x2,#4`）；它们是共享值（[相位是元素的字段](#the-phase-is-the-elements-field)）。

<a id="the-league-card"></a>
## 联盟卡

交换后各游戏机询问是否保留对方的联盟卡，训练家卡为
其快照的 0x924 ([协议](swsh_protocol.md#the-party-payload-on-protocol-0x84));答案没有发送任何内容。

Oui 将其原封不动地保存在保存块 `0x28e707f5` 中：来自 `album+0x230` 的 300 个 0x1d0 插槽，作为一个 `0x21fc0` 字节块（`0x013fad4c`）加载，当 `+0x1c8` 为非零时，空闲。 `0x013fbab0` 填充第一个空闲槽：0x1c4 字节，`+0x1c8`/`+0x1c9` 归零，年 `+0x1ca` (`tm_year + 0x76c`)，月 + 1
来自参数的 `+0x1cc`、日 `+0x1cd`、`+0x1ce`/`+0x1cf`（`00 00 ea 07 09 1a 02 00`：年 0x07ea、月 9、日 0x1a）。
当所有 300 个都使用时，`0x013fbc00` 返回 1。

当使用的插槽与 0x1C (`0x013fbc4c`) 处卡的 u32 匹配时，`0x013fbc40(album, card)`（调用者 `0x00aa6414`、`0x0106612c`、`0x015253f0`、`0x01543868`）会跳过该问题0x1A8 处有 8 个字节（`0x013fbc5c`，一个 64 位比较）；清空该插槽会带回问题。 0x1C 是 PKHeX
`TrainerCard8.TrainerID`、`(SID << 16 | TID) mod 10**6`（56909/48474 为 848973）； 0x1A8 是
`TimestampPrinted`，Unix时间（`9bc62a5e00000000`，2020-01-24，在零售卡中）；游戏比较所有八个字节，`pokeldn.swsh.league_card` 映射 u32。 `trade_payload.rewrite` 设置训练家ID。对抗持有主机卡的模拟盾牌：

|主机名片 |问|
|---|---|
|不变|没有|
| 训练家 ID 848973 -> 111111 |是的;归档在第一个旁边的新槽中 |
|图鉴计数 400 -> 401 |没有|
|名字，添加一个字母 |没有|
| timestamp_printed，仅字节 0x1A8 发生变化 |是的 |

零售剑在左上角绘制了收到日期、`game`（0x24，0 剑）的徽标、0x39左下角的三个ASCII字节、`dex_complete`（0x30）的洛托姆-Dex皇冠和星星。景色
`0x01592e70` 将卡复制到 `view+0x3c0`； `0x015a52f0(view, count)` 点亮七个窗格中的 `count + 1`（`view+0x618..+0x648`；验证器上限为 6）：

    count = card[0x177] + (card[0x1b6] != 0) + (card[0x1b7] != 0)      0x015930bc..0x015930dc
 它还将 `card[0x24]` 传递到 `0x015a5260` 和 `card[0x1b3] != 0` 传递到 `0x015a50d0`。建设者
`0x0158eef0`（调用者 `0x00c77830`、`0x014be578`、`0x0156167c`、`0x01561b0c`、`0x01568f4c`、
`0x015691bc`) 从保存中填充：

|字节|价值|网站 |
|---|---|---|
| 0x177 | `DesignLevel`：4 与 `FSYS_GAME_CLEAR` (`0x7d0b1ced4dbe8a87`)，其他 3, 2, 1, 0 徽章 > 6, > 3, > 0, 0 | `0x0158f084`、`0x0158f484..0x0158f4dc`、`0x0158f0c4` |
| 0x1B1 | `FSYS_SEED_CHALLENGE` (`0xbd07c2b80232e9b0`) | `0x0158f564..0x0158f5a0` |
| 0x1B3 | `FSYS_INPUT_SHIRT_NUMBER` (`0xe44b16771524b07e`) | `0x0158f0fc` |
| 0x1B6 | `FSYS_R1_GAME_CLEAR` (`0x8f1a133dff5c0ecf`)，一颗星 | `0x0158f11c` |
| 0x1B7 | `FSYS_R2_GAME_CLEAR`（`0xd450875d834cfc30`），一颗星| `0x0158f12c` |

标志键是 FNV-1a 64 个名称（[协议](swsh_protocol.md#the-player-profile)），由
`0x01410f30`；徽章计数为 `0x01438fb0`，弹出计数为 `[status+0x60]`。 `DesignLevel` 是
`capture_data.prmb` 列（哈希值 `0x3bc4598485d2a2ef`，字符串 `0x01c2a2e9`）存储在
`0x0158ead4..0x0158eb30`; `GlossIndex` 是 0x178。

`0x0158f5e0` 返回 1 拒绝一张卡，然后将其替换为默认值。在 unicorn 下，它接受 pokeldn 发送的卡（0x177 = 4，0x1B3 = 1，语言 3）和 0x1B6 或 0x1B7 设置；它拒绝 DesignLevel 5、语言 6、GlossIndex 9。 `bin/swsh_host.py --card-set FIELD=VALUE` 编辑发送的卡片（`pokeldn.swsh.league_card` 字段）；新鲜的 `trainer_id` 使游戏机再次询问。

<a id="the-offered-record"></a>
## 提供的记录

与零售剑交易的内置皮卡丘保留了每个请求的提议选项。返回的PK8具有有效的校验和并通过PKHeX合法性； PID、初训家 ID、IV 和 EV 与即将发出的提议相匹配。

|请求字段 |返回记录 |
|---|---|
|水平| 30|
|性格与能力值修正所用性格|固执，3 |
|特性|避雷针，31 |
|性别 |女, 1 |
|球 |超级球，2 |
|持有物 |光球，236 |
|选定的 IV |生命值 31，攻击力 0，速度 31 |
|努力值 | HP 252，速度 4，其他所有统计数据 0 |

`0x011e3458` 读取的加密常数与队伍索引一起进入宝可梦露营模型键 `[model+0x368]`，用于露营同步，不会进入交换或盒子代码。

20030的提议是快照的队伍槽位`--offer-slot`，已就地编辑，因此显示的队伍与提议一致；身份重写首先运行并且 `party_matches_trainer` 成立。
`pokeldn.swsh.pokemon.build_from` 重写校验和，在新的加密常量下重新洗牌，并保留每个未命名的字节（色带、内存、met 数据、处理程序记录）。

法语版《剑》 1.3.2 接受了其在四次交易中已保存的记录（相同的 PID 和 EC）并继续进行交易。 盾 1.3.2 中读取的路径不存在重复检查：PID getter（`0x0076bc20`，块 A + 0x14）仅由异色测试调用；在 12 个站点读取加密常量 getter (`0x0077ec90`)，没有一个站点能够走动；盒子代码（`obj+0x60 + box*0x2850 + slot*0x158`）仅读取种类和蛋标志；并且没有访问器触及 PK8 字节 0x52，其中晶灿钻石保留其非法标志（[BDSP 交换页面](bdsp_trade.md#duplicate-detection)）。 `bin/swsh_host.py --fresh-pid` 和
`bin/swsh_connect.py --fresh-pid` 绘制新的加密常量和PID；在剑上这是一种预防措施。

`memcmp` 桩 `0x018fe460` 的 375 次计算长度调用均不比较两只宝可梦：374 次比较字符串或库数据（sol2、protobuf、NEX、Lua、Pia、SDK 图形、名称字典、对战数据容器、FlatBuffers 虚函数表），`0x014514ac` 将 `obj+0x60` 的 0x158 字节槽与零比较。交换接收路径（`0x010d81d0` 到 `0x010f5cc0`）及盒子路径（`0x010ce180`、`0x00c8d900`）都不会通过直接调用到达这些位置；交换代码只到达 protobuf 描述符注册（`0x006e26f0`），其操作数是 rodata 中的名称。未追踪虚函数表调用。

    --offer-slot 1 --offer-nickname POKELDN --offer-ivs 31,31,31,31,31,31

|旗帜|效果|
|---|---|
| `--offer-nickname`，`--offer-ot` | 26字节UTF-16字段，最多12个字符；昵称设置昵称标志，否则绘制种类名称 |
| `--offer-species` |单独的种类词；其他一切都保留模板的 |
| `--offer-ability ID`，`--offer-moves A,B,C,D` |两个领域； PP 和重新学习动作留下 |
| `--offer-level N` | 0x148 处的等级字节 |
| `--offer-experience N` |经验词0x10 |
| `--offer-ivs` |六个 IV |
| `--offer-file FILE` |四种形状中任意一种的 `.pk8`（存储或队列、加密或 PKHeX 的解密导出，由标头校验和区分）； OT 名称和 ID 已移至快照的训练家 |
| `--offer-file-as-is` |保留文件的 OT |
| `--save-offer FILE` |在触摸收音机之前写入构建的记录|

French 剑 1.3.2 对已编辑记录的作用：

| 发送的记录 | 结果 |
|---|---|
| 模板、昵称、IV 全部为 31 | 接受；未指定的字段保持模板值 |
| 种类 93，使用耿鬼的特性 130 和招式 | 显示为鬼斯通，并在交换时进化：特性和招式不作检查 |
| 种类 25 | 根据 IV、EV、性格及极限训练字段 0x126 重新计算能力值；丢弃 0x14A 处的能力值字节 |
| 等级字节 0x148 = 50，经验值对应 100 级 | 等级为 100：由经验值（0x10）决定等级；重新生成队伍记录尾部 |
| OT 移至 12345/54321 |显示 ID 993401，`(SID << 16 \| TID) mod 1000000`|
|接收者自己的OT在国外MyStatus下|接受为玩家自己的捕获：OT id 不会与 MyStatus 进行比较 |
| PID高半部=`low ^ TID ^ SID`| 异色|
|种类 152（缺席）|存储：皮卡丘的模型、姓名字段、黑色精灵球图标、成长组 0 和零种族值；仅当前HP（0x8A）和处理程序块（0xA8, 0xC2, 0xC3, 0xC8, 0xCB-0xCC) 改变 |

未测量：其他不存在的种类绘制了什么，以及该名称是否是名称字段或查找失败。

<a id="the-command-line-of-a-completed-trade"></a>
## 已完成交换的命令行

`swsh_connect.py --preset trade` 携带交换所需的标志；覆盖预设后给出的标志。让游戏机搜索本地链路交换（Y-Comm、链路交换、本地、两条消息上的 A）并运行：

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/swsh_connect.py --keys PROD_KEYS \
        --preset trade --save-offered offered.pk8 --capture trade.jsonl
 发回的快照是游戏机自己的来自同一会话的快照（`--send-snapshot live`，预设的默认值）：三个 0x84 片段在到达时重新组合，训练家名称、TID 和 SID 被重写为 `--snapshot-name/-tid/-sid`，一旦游戏机的快照被删除，它就会消失。重新组装，因此不需要早期的捕获会话。 `--send-snapshot FILE` 发送一个已保存的 3456 字节的 TCP（`--preset capture`，然后 `tools/switch/swsh_snapshot.py`，写入 1）。

`--offer-file FILE` 将 `.pk8` 放入提供的队伍槽位，其 OT 移至快照的训练家处。如此重复，它会在会话中的每个交换中排队一个记录；最后一个服务于以后的交换，在带有 `--fresh-pid` 的新 PID 下，并且交换 N 用 `-N` 写入 `--save-offered`。游戏机提供的交换，其阶梯尚未完成，使会话持续到 `--grace` 秒 (300) 过去
`--hold`。没有队伍统计数据的存储格式交易记录；游戏机根据经验计算等级。

<a id="the-penalty-and-ending-a-run-cleanly"></a>
## 处罚，干净利落地结束比赛

链路处于活动状态的交换超时是失败的交换，并将游戏机锁定在交换之外（`msg_ui_live_comm_app_alert_00`，`/bin/message/French/common/live_comm.dat` 的第 331 行）。 `main.bin` 中的文本名称没有持续时间并且标签不存在；锁的长度未被读取。 `04000400` 后 15 秒切断链接，在保存过程中，显示通信错误 `2-ALZAA-0016`，不采取交换锁定并立即开始新的本地搜索。

一旦梯子启动，`bin/swsh_connect.py --abort-on-stall SECONDS` 就会断开链接，并且几秒钟过去了，没有新的身体。它处于第 4 阶段，无声拆卸梯级 (`stall_abort()`，
`final_phase_seen`、`LADDER_FINAL_PHASE`），因此在保存过程中链接永远不会被切断。

<a id="verifying-a-completed-trade"></a>
## 验证已完成的交换

收到的宝可梦在0xC4处带有`CurrentHandler` 1，在
`HandlingTrainerName` at 0xA8 发送者的初训家。 `--offer-echo` 交回游戏机自己的记录，因此只有不同的种类才能证明转移。
