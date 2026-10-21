
<a id="the-bdsp-trade"></a>
# BDSP 交换

零售明亮珍珠与发明的角色进行交易，将宝可梦组装并写入其保存。方法及问候语见[游戏协议](bdsp_protocol.md)。

<a id="the-message-sequence"></a>
## 消息序列

    NetDataTransitionData{transitionType: 18}     entering the trade
    NetDataTradeTranerData        32 B            who they are
    NetTradePokeData             328 B            the Pokemon
    NetDataTradePokeCheckOkData    1 B, value 1   "yours is fine"
    NetDataTradeReadyOkData        2 B            the last message before the exchange
 每一个都用客户自己的一个来回答。

游戏机唯一的实时检查成功发送者是 `TradeSelectPokeModel.<OpenTradeBoxWindow>b__54_2` [1.3.0 主 0x1c28520]，即 `BoxWindow$$Open(otherName, msgLangId, onSelected,
onDecide, onConfirm, onComplete, onCancelSelect, ...)` 的 `onDecide`（lambdas `b__54_1` 到 `b__54_5`）。它将自己的检查状态（+0x80）设置为6，发送`{isCheckOk: 1}`到
`tradeTargetIndex` (+0x48)，并设置 `isWaitingOK` (+0x7b) 1 和 `isWaitingSelect` (+0x7c) 0 [0x1c285a4]。 `isCheckOk`始终为1：游戏机从不通过此消息拒绝宝可梦（`SendTradePokeCheckOk` [0x1c27cb0]没有呼叫者）。 `BoxWindow$$OnTradeContextMenu` 调用
`onDecide` [0x212e99c]，然后将盒子的交换阶段推进一个 [0x212e9dc]。

`TradeSelectPokeModel$$PokeSelectWait` [0x1c26070] 一旦盒子阶段超过 2，并且接收（+0x78）和自选（+0x79）标志都被设置，则显示对等方的宝可梦；没有什么可以检查它。当两个检查状态（+0x80 自己，+0x84 对等）均为 6 时，`TradePokeCheckOkWait` [0x1c25f50](pia.md#what-the-receiver-discards-in-silence) 继续前进。层])。

在本地无线中，仅检查玩家自己的选择是否存在保存的非法标记（`CoreParam$$GetDprIllegalFlag`）； `NetworkManager$$RequestValidateTrade` 仅在以下情况下运行
`UnionFrontDeskStateController.isGlobal` 已设置。

`RequestValidateTrade` [0x02251cb0] 在客户端不做任何检查。它将各宝可梦的 `CoreParam` 复制到 0x148 字节的请求中，发送给任天堂验证服务器（`IlcaNetServerValidate.CheckRequestAutoAsync` [0x027318c0]）。回复为 `ValidateResultID`（None、InvalidData、SignatureError、ProcessError），签名或处理错误会弹出错误对话框。玩家自己的宝可梦被标记时选择消息 `SS_box_182`，其含义为“由于你的宝可梦存在问题，无法交换宝可梦。”；原英文为“You can't trade Pokémon because there is a problem with your Pokémon.”，法文为“Un problème avec votre Pokémon rend tout échange impossible.”。`SS_box_181` 则说明对方的宝可梦存在同样问题。

<a id="the-trade-state-machine"></a>
## 交换状态机

`UnionTradeManager.currentState`（+0x88；+0x80 在 1.3.0 中）是
`TradeFlowState {NONE 0, SELECT_WINDOW 1, SECURIY_TRADE 2, PLAY_DEMO 3, END 4}`：

    UnionTradeManager$$RecivePokeData          0x1dd2800   currentState == SELECT_WINDOW only
    UnionTradeManager$$SetTargetTranerParam    0x1dd2130   TargetTranerParam{uint id, string name}
    UnionTradeManager$$ReciveTradeReadyOkData  0x1dd2a70   routed on the same field
 宝可梦仅在 SELECT_WINDOW 中被取入 `tradeSelectModel.targetPokemonParam` 中
`isRecivePokeParam` 套装。 `NetDataTradeReadyOkData` (0x21) 进入 SELECT_WINDOW
`TradeSelectPokeModel$$ReciveReadyOk`（[Box Phases](#box-phases-and-the-messages-that-reset-a-round)），在 SECURIY_TRADE 到 `TradeSecurityController$$ReciveState` 中（在 1.3.0 [0x1c34290] 中，仅当控制器的 `GetCurrentState` 非零时；在 0 时调用`SettingSecurityControllerParam` [0x1c343f4] 并丢弃该消息），并被丢弃到其他地方。

`ReciveReadyOk` [1.3.0 0x1c27d40] 将消息的第二个字节 `tradeState` 复制到
`targetTradeState`（+0x78；1.3.0 中的+0x84，其中收到的 check-ok 也写入 6）； `isTradeOk` 从未被读取。 `UnionTradeManager.<WaitBoxWindowComplete>d__24` 等待直到`myTradeState`（+0x74，由玩家的`MyReadyOk`设置）和`targetTradeState`都为2（`WAIT`），然后将`currentState`设置为
SECURIY_TRADE，清除选择模型并发送自己的0x21，其中`tradeState` 0。仅对等方的
0x21 将游戏机移出 SELECT_WINDOW。

<a id="box-phases-and-the-messages-that-reset-a-round"></a>
### 盒子阶段，以及重置回合的消息

`BoxWindow.NetTradePhase`:

    None 0, WaitSave 1, PlayerSelecting 2, WaitSend 3, OtherPokeConfirm 4, WaitOtherDecide 5,
    LastConfirm 6, WaitTrading 7, Complete 8, WaitClose 9, CancelOther 10, Error 11

`WaitSave` 不写入任何内容：`BoxWindow.<WaitTradeSave>d__203` 计数 `FieldCommonParam[0xEB]` * 比 `Time.deltaTime` 减少 0.001 秒。

复位为`TradeSelectPokeModel$$ReciveReturnSelectPoke`[1.3.0主0x1c27f00]。对于
`isReturnSelect` 1 它回答 `NetDataReturnSelectData{0}` [0x1c27f48]，因此游戏机回答每个
`{1}` 与 `{0}`。在每种情况下都会清除 `isWaitingOK`/`isWaitingSelect` [0x1c27fb0]，
`isRecivePokeParam`/`isSendPokeParam` [0x1c2803c] 和两个交换状态 [0x1c28040]，并设置
`UnionWork`静态+0x50（`boxState`）到6，`CANCEL_SELECT` [0x1c28030]。在盒子阶段 3 或更高版本，或者没有盒子时，它会调用 `CloseOverUIWindows` [0x1c28168]。

`BoxWindow$$UpdateNetworkTrade` [0x2121628] 获取并清除 `CANCEL_SELECT` [0x2121c64]：在第 2 阶段，它会丢弃未经确认的突出显示；在任何其他 [0x21225b0] 处，它都会关闭窗口，设置第 2 阶段并显示 `SS_box_588`（“L'autre joueur a choisi d'annuler l'échange。”）。

|来自同行的消息|盒相|游戏机的作用是什么？
|---|---|---|
|检查-确定（0x46）|无框或低于 6 |对等检查状态 (+0x84) = 6 (`ReciveTradePokeCheckOk` 0x1c34630) |
|检查-确定（0x46）| 6 `LastConfirm` 或更高版本 |重置为 `{1}` [0x1c34718]，则 `securityController?.ResetTradeState()` |
|准备好（0x21），SELECT_WINDOW |闩锁+0x71 设置|掉落[0x1c342e4] |
|准备好（0x21），SELECT_WINDOW |盒子存在，第 5 阶段或以下 |重置为 `{1}` [0x1c3440c]，则 `ResetTradeState()` |
|准备好（0x21），SELECT_WINDOW |第 6 阶段或更高版本，或无盒子 | `ReciveReadyOk`，锁存器+0x71 = 1 [0x1c3435c] |
| return-select (0x45)，任一值 | 2 `PlayerSelecting` |重置；盒子掉落未经证实的亮点|
| return-select (0x45)，任一值 | 3 或更高 |重置；该框返回到第 2 阶段并显示 `SS_box_588` |
|返回选择 (0x45) |任意，PLAY_DEMO |无需重置； [0x1c345c0] 清除 `targetDemoPokemonParam` |

锁存器（+0x71，`<isLoadingBox>k__BackingField`）由`Init`，`WaitBoxWindowComplete`清除，
`Cancel`、`RecivePokeData` 和 `ReciveCancelData`；它的设置者 [0x1c33040] 没有调用者。最后一次确认后，当其盒子关闭时，游戏机发送自己的就绪状态（`b__54_4` -> `BoxCloseComplete` ->
`MyReadyOk` 0x1c26d90 -> `SendReadyOk` 0x1c26f14）。

游戏机自己的退出，`onCancelSelect` (`b__54_5` 0x1c28620)，将框设置为阶段 2 (`ToNextPhase(box, 2)`；非零参数存储在 `[[box+0x390]+0x50]`，0 加一)，发送
`NetDataReturnSelectData{1}` [0x1c286a4]并清除等待标志、宝可梦标志和双方交换状态，而不设置`CANCEL_SELECT`。然后等待新的`NetTradePokeData`（`isRecivePokeParam`的唯一设置者是`UnionTradeManager$$RecivePokeData`，在SELECT_WINDOW中，任何阶段[0x1c33e9c]）；合作伙伴的`{0}`没有发布。

- 对每个游戏机检查一次回答“OK”。在第一个答案将方框移动到 `LastConfirm` 后回答的副本会重置回合。可靠窗口保留 id 的第一条消息（[Pia 页面](pia.md#what-the-receiver-discards-in-silence)）；在捕获的 12858 个游戏机可靠消息中，322 个重复的 id 是字节相同的副本。接收方丢弃已发送的 ID； `pokeldn.ldn.reliable5.Reassembler` 这样做，`bin/bdsp_connect.py` 使用它。
- 用 `45 0001 00` 回答游戏机的 `45 0001 01`； `{1}` 退回是客户自己的退回。   切勿在替换宝可梦消失或游戏机重新选择后发送 0x45：它会擦除回合。
- 在选择窗口中，游戏机最后确认之前的 0x21 表示取消，之后仅计算第一个确认。在游戏机返回其选择窗口之前停止安全状态中继器。

<a id="the-security-phase"></a>
## 安全阶段

然后 `TradeSecurityController` -> `CreateTradeStateModel` -> `TradeStateModel`，它拥有保存：

    TradeStateModel.TradeState
    NONE 0, INIT 1, WAIT 2, SEND_POKE 3, WAIT_POKE 4,
    SEND_READYOK 5, WAIT_READYOK 6, START_WRITE_SAVE 7, WRITEING_SAVE 8

`TradeStateModel$$InitState` 首先调用`PlayerSave`。 `WriteSaveData` 尾调用 `ReplacePoke`；两者都只能以注册代表的身份接触。 `FirstSave` 在写入之前设置断开连接惩罚。

在安全阶段，宝可梦消息仅触发下一步。 `UnionRoomManager$$RecivePokeData` 中
SECURIY_TRADE 丢弃解码后的宝可梦并调用 `SetSecurityTradeParam()`，后者将
`manager.targetPokemonParam`（+0x48，当玩家在全屏视图上确认时设置）到安全控制器。直到玩家确认它为空并且WAIT_POKE永远不会结束。

<a id="who-leads-the-rarer-pokemon"></a>
### 谁领先：稀有的宝可梦

`CreateTradeStateModel` [1.3.0 main.bin 0x1c24620] 为两个角色构建一个 `TradeParentStateModel`（`TradeChildStateModel` 的覆盖是裸 `ret`）。角色是`tradeParent`（+0x94），
`TradeParent {NONE 0, PARENT 1, CHILD 2}`，由`TradeSecurityController$$CheckPokeRarity` [0x1c25060]编写，当同行的宝可梦到达（`UnionTradeManager$$SetSecurityTradeParam` [0x1c34750]）时，来自`Dpr.SubContents.Utils$$GetPokeRarityNum` [0x1cbe560]的两个种类：

    POKE_RARITY_VERY_RARE 3, POKE_RARITY_LEGEND_RARE 2, POKE_RARITY_SUB_LEGEND_RARE 1, anything else 0
    mine > theirs   PARENT
    mine < theirs   CHILD
    equal           PARENT if isRecruiment (+0x38), else CHILD
    species -1      no role set (to 0x1c25120)

`GetPokeRarityNum` 按顺序遍历三个静态 `MonsNo[]` 列表（0x1cbe614、0x1cbe698、0x1cbe71c；无 0x1cbe730），由 `Utils$$.cctor` 填充[0x1cbe9a0] 从 1.3.0 开始：`global-metadata.dat`：

|静态场|稀有度|元数据 |种类 |
|---|---|---|---|
| `very_rare_monsno` +0x78 | 3 | `0x666aa6` | 151、251、385、386、489、490、491、492、493（神话）|
| `legend_rare_monsno` +0x80 | 2 | `0x666b06` | 150、249、250、382、383、384、483、484、487（盒子传奇）|
| `sub_legend_rare_monsno` +0x88 | 1 | `0x667c39` | 144、145、146、243、244、245、377-381、480、481、482、485、486、488 |

帝牙卢卡提出对抗游戏机的梦幻而离开游戏机父母。

`TradeParentStateModel$$StateProc` [0x1c23350]，表位于 0x3d80f2f：

    2 WAIT            targetState == WAIT                    -> 3
    3 SEND_POKE       waitRndTime runs out; SendPokeData     -> 4
    4 WAIT_POKE       targetPokeData non-null                -> 5
    5 SEND_READYOK    PARENT only: send own state            -> 6
    6 WAIT_READYOK    targetIsTradeReadyOk; PARENT sends     -> 7
    7 START_WRITE_SAVE  WriteSaveData                        -> 8
    8 WRITEING_SAVE     CheckReplacePokeData                 -> 10

`TradeSecurityController$$ReciveState` [0x1c24f10] 开启游戏机自身状态，表位于
0x3d80f39：

    1 INIT            -> WAIT, send own state
    3 SEND_POKE       send own state
    5 SEND_READYOK    CHILD only: peer 5 -> send, go to 6; peer 6 -> send, go to 6, set targetIsTradeReadyOk
    6 WAIT_READYOK    set targetIsTradeReadyOk
    every case        targetState = the peer's byte

`TradeStateModel$$SetTragetPokeData` [0x1c24d70] 以发送游戏机的状态结束，WAIT_POKE。然后儿童游戏机移动到SEND_READYOK并默默等待对等状态 5 或 6，因此回显的客户端WAIT_POKE使其陷入僵局。`room.mirror_trade_state`答案WAIT_POKE和SEND_READYOK， 哪个`ReciveState`扮演任一角色：一个处于其状态的孩子SEND_READYOK（案例 5），一位家长WAIT_READYOK（案例6）。`tests/test_bdsp_trade_states.py`在随机延迟下根据客户端策略运行这两个函数作为模型。

每个可靠序列 ID 发送一条消息：`their_ack_id` 仅当游戏机确认时才移动，因此同一 ID 下的后续消息看起来像是重传并被丢弃。 `bdsp_connect`拥有自己的计数器。

<a id="the-completed-trade"></a>
## 已完成的交换

安全性按顺序声明游戏机作为招募者和家长（游戏机的状态，然后是客户的答案）：

    their READY-OK {isTradeOk 0, tradeState 2}  ->  the client's READY-OK
    INIT          ->  WAIT
    WAIT          ->  WAIT
    SEND_POKE     ->  SEND_POKE, and its Pokemon
    WAIT_POKE     ->  WAIT_POKE
    SEND_READYOK  ->  SEND_READYOK
    WAIT_READYOK  ->  SEND_READYOK
 WAIT_READYOK之后，游戏机写入保存，播放动画并运行`ReplacePoke`，仅发送`NetCharacterStateData`。离开 WAIT_READYOK 需要对方再发送一条消息。游戏机在以任一角色进入 WAIT_READYOK 时都会报告 SEND_READYOK（来自 `StateProc` 案例 5 的家长，来自 `ReciveState` 案例 5 的孩子），因此客户端对该报告的答复到达其中。在 25 个零售交易中的 25 个中，无论是哪种角色，游戏机的下一条可靠消息都在 SEND_READYOK 之后 0.16 至 0.24 秒，然后再重复；家长的 WAIT_READYOK 报告紧随其后 0.02 至 0.06 秒（19 中的 19）。客户端仅在游戏机的 SEND_READYOK (`room.repeats_trade_state`) 之前每秒重复一次其状态：在它之前，CHILD 的 SEND_READYOK 仅在消息到达其中时结束。站不得在此窗口中离开：将游戏机降落在 `FirstSave` 和 `SecondSave` 之间。相同的序列以游戏机作为房间的加入方和 pokeldn 作为主机运行。

来自游戏机 `tradeState` 6 的时间线，零售 BDSP 加入 `bin/bdsp_host.py`：动画在约 2.7 秒开始，接收到的宝可梦在约 18.6 秒出现，玩家在约 29 秒控制（手按标记，最多晚 2 秒）。

一次完整的交换以没有任何消息的方式结束。客户端在回答游戏机的问题时进行计数
SEND_READYOK;下一轮从游戏机的下一个 `NetTradePokeData` 开始。

`NetDataReturnSelectData` (0x45)、`45 00 01 00` (`{isReturnSelect: 0}`) 是游戏机对重置的响应（[盒子阶段](#box-phases-and-the-messages-that-reset-a-round)）：`{1}`，或0x21 在框阶段 5 或以下的选择窗口中着陆，通过相同路径 [0x1c3440c] 重置并显示 `SS_box_588`。它不要求任何答案（`{1}` 答案会绘制 `{0}` 并重置已经清除的回合）。在 26 笔捕获交易中的 26 笔中，客户端通过动画每秒重复其状态一次，`{0}` 跟随客户端的 0x21 之一 25 到 300 毫秒，玩家看到
`SS_box_588`;在游戏机的 SEND_READYOK 之后没有 0x21，在两种角色的 5 个零售交易中的 5 个中（每个角色中有两个在一个协会中排队），游戏机没有发送 0x45 并且没有显示取消。 `TradeSelectPokeModel$$SendReturnSelectPoke` [0x01c27c20] 构建它（`isReturnSelect` = 不是它的参数，为 `tradeTargetIndex` +0x48）；它没有直接的 `bl` 调用者。

交易链在一个关联中，每个交易都从选择窗口循环，没有第二次方法或训练家记录：三笔交易与 `bin/bdsp_connect.py` 连续完成（框屏幕在每笔交易后返回），两笔交易与 `bin/bdsp_host.py` 托管。 `TradeStateModel$$ReturnTradePokeSelectWindow` [0x01c29590]运行`PlayerSave`，然后模型在+0x80处回调；其调用者未被追踪。第二次交换会读回游戏机存储的内容。当玩家选择（框第 5 阶段或以下）时，SEND_READYOK (5) 0x21 着陆会重置该回合，因此游戏机的 SEND_READYOK 之后不会重复。

<a id="the-pokemon"></a>
## 宝可梦

`NetTradePokeData`携带328字节，Gen 8 `SIZE_STORED`：加密的PB8，[剑／盾页面](swsh_protocol.md#the-pk8)上的格式(`pokeldn/gen8.py`; `pokeldn/bdsp/pokemon.py` PB8视图)。 0x06 处的校验和对解密的主体求和，因此解码构建的宝可梦可以验证它，但错误的块顺序除外，16 位字的总和无法看到。

`NetDataTradeTranerData` 是编组结构 `string tranerName; uint tranerId; byte
cassetVersion; byte langId` ([Framing](bdsp_protocol.md#framing))：

    0x00  26  tranerName, UTF-16LE, NUL-terminated
    0x1a   4  tranerId, the full 32-bit id, secret id in its high half
    0x1e   1  cassetVersion, the save's version (49)
    0x1f   1  langId, the save's language (3)

游戏机在交换开始、尚未提供宝可梦时发送此记录，表示存档训练家；按接收玩家生成的礼物读取它（`room.traner_trainer`、[按接收玩家生成](gift_simulated.md#made-for-the-receiving-player)）。此消息没有性别，会话其他消息也没有。加入外观仅在使用联合房间可选外观柜台后对应存档性别；此前首次连接会随机分配任一性别的外观（[角色模型](bdsp_protocol.md#the-model)）。提供的宝可梦可以补充性别：存档为初训家时读取 OT，否则读取当前训练家（[游戏机对接收宝可梦的处理](#what-the-console-does-to-a-received-pokemon)）。

 交换屏幕从该记录中命名伙伴；问候语使用 Pia 玩家名称（[协议页面](bdsp_protocol.md#the-name-in-the-greeting)）：0x24 分支
`UnionRoomManager$$SetNetData` [1.3.0 main.bin 0x1e51940] 从消息中获取所有四个字段，仅从 `GetGamerData(...).nameStringLanguage` 中获取字体语言，将名称包装在
`MessageHelper$$SurroundFontTag` 并将其交给 `UnionTradeManager$$SetTargetTranerParam` [0x1c33330]。

名称终止符和 id 之间的十个字节是堆残留（`AllocHGlobal` 不清除；0x14 处的字有所不同）。 `room.build_trade_traner` 逐个字节地携带游戏机自身的剩余部分。

提议是一个真正的宝可梦，但命名字段已更改（`pokemon.build_from`）；游戏机本身的数据、功能区、处理程序记录和语言都是非零的。

<a id="what-the-console-does-to-a-received-pokemon"></a>
## 游戏机对收到的宝可梦做了什么

由其初训家接收回来，两个字节发生变化：`IsNicknamed`（0x08F第7位，IV32第31位）当名称与游戏语言中的种类名称不同时设置，校验和如下。名称字符串保持不变；种类名称仍然是种类名称。

由另一位训练家接收，十一个字节发生变化，`ot_name` 未被触及：

    0x0A8..0x0B2   HandlingTrainerName, UTF-16LE
    0x0C3          HandlingTrainerLanguage (3, French)
    0x0C4          CurrentHandler, 0 -> 1
    0x0C8          HandlingTrainerFriendship, 50
    0x006..0x007   the checksum

0xC6（PKHeX 的 `HandlingTrainerID`，“未使用？”）保持为零。 PKHeX 的 `IsUntraded` (`Data[0xA8] == 0`) 变为 false。

`TradeStateModel$$ReplacePoke` [1.3.0 main 0x1c29120] 执行修改。它从存档 `DPData.MYSTATUS`（`PlayerWork$$get_playerStatus`，构造器 [0x24a1b30]）创建 `OwnerInfo`：`{trainerId, sex, langID, name}`，包含 ID、`sex ^ 1`、`region_code` 和姓名。状态字段 `sex` 在男孩时为真，与 `_GET_MY_SEX` 的读取方式一致。它将 `OwnerInfo` 传给 `CoreParam$$UpdateOwnerInfo` [0x2495920]，比较宝可梦 OT 性别、32 位 ID 和姓名：

- 三者均相同：清除当前训练家标志，不改写其他字段。
- 否则：设置标志，将存档姓名、性别（0xC2）和语言写入当前训练家字段，清零回忆，亲密度设为种类基础值。

其他训练家接收时每次写入 0xC2；上述测量中它原本已经是接收方性别。不记录当前训练家 ID 或版本。GTS（`GMSSceneDataModel$$OnReceivePokeData`）、游戏内交换（`LocalKoukan$$CreateTradePokeParam`）、神秘礼物（`MysteryGiftWork$$CreatePokemonParam`）及 `RenkeiData$$Get_1`/`Get_2` 从存档构建相同 `OwnerInfo`。`UpdateOwnerInfo` 是游戏唯一写入当前训练家性别的方法。游戏不含 Pokémon HOME 代码，从 HOME 到来的宝可梦由 HOME 写入。

<a id="duplicate-detection"></a>
### 重复检测

`PokeDupeChecker`（1.3.0中添加）在重复的宝可梦上设置非法标志。标志为解密后的PB8字节0x52的位0（块A+0x4A，`CoreDataBlockA.set_dpr_illegal_flag` `0x027bb040`）； PKHeX 将其读取为 `PB8.IsDprIllegal`。被标记的宝可梦无法进行交易（“Un Probleme avec votre 宝可梦 rend tout echange不可能。”）。

`UpdateIllegalFlagAll` [`0x01de5860`] 按顺序在腰部、1 至 40 号盒子和日托处运行 `CheckDuplicate` [`0x01de59d0`]。宝可梦参与时，其原始游戏是晶灿钻石或明亮珍珠（`version & ~1 == 0x30`），它不是蛋，其标志是清晰的，并且不是游戏内交换宝可梦（`IsLocalKoukanPokemonParam` [`0x01de66d0`]：遇到位置30001，训练家ID，加密常量和性格与`LocalKoukanData` 条目）。每一个都与之前的每一个进行比较；第一个副本保持干净，并且后面的每个副本都被标记。

`IsDuplicatedPokemonParam` [`0x01de62f0`] 匹配所有：

|领域 |配件| PB8偏移|
|---|---|---|
|加密常量| `GetPersonalRnd` | 0x00 |
| PID| `GetColorRnd` | 0x1C |
| 训练家 ID (TID16, SID16) | `GetID` | 0x0C |
|性格 | `GetSeikaku` | 0x20 |
|六个 IV | `GetTalentHp` .. | 0x8C |

铁面忍者（291）和脱壳忍者（292）对永远不会重复。不比较种类、形态、昵称和OT名称。

`UpdateIllegalSpecialTraining` [`0x01de6830`] 标记 99 级或以下且具有任何极限训练位设置的晶灿钻石或明亮珍珠宝可梦。

该检查在保存加载（`PlayerWork.OnPostLoad_NeedMD`）、交换框（`TradeSelectPokeModel` [`0x01c28310`]）中的每次选择时以及Wonder交换保存（`Dpr.GMS`）之前运行；收到交换后，什么都不运行。本地交换中的标记选择将 `UnionWork.boxState` 设置为
`INVALID_DATA` 并且盒子拒绝；在线交换将选择发送至
改为 `NetworkManager.RequestValidateTrade`。 `ClearIllegalFlagAll` 没有调用者，因此标志永远不会被清除。

切勿提供加密常量、PID、训练家 ID、性格和 IV 均与接收保存中的宝可梦匹配的晶灿钻石或明亮珍珠记录。 `bin/bdsp_host.py --fresh-pid`提取新的加密常量和PID，保持异色状态；以这种方式交易到保存原始记录的记录中没有任何标志。

<a id="the-disconnect-penalty"></a>
## 断开连接惩罚

在 `FirstSave` 和 `SecondSave` 之间退出的电台会留下惩罚，并且游戏机拒绝新的本地交换“vous ne pouvez pas faire d'echange en reseau pour le moment”，直到清除：

    TradeStateModel$$FirstSave    0x1cd4fc0   SetPenartyCounter(30); SetPenartyTime(now)
    TradeStateModel$$SecondSave   0x1cd5030   SetPenartyCounter(0)
    UnionFrontDeskStateController$$CheckPenarty  0x1fcc400   counter >= 1 AND not CheckDateTime()
 完成的交换将其清除；处罚意味着 `FirstSave` 跑动并且游戏机写道。
`UnionWork$$CheckDateTime` [0x1dd3e30] 和 `SetPenartyTime` [0x1dd32d0] 使用未加权和：

    w8 = Year + Month + Day + Hour + Minute + Second
    cset w0, mi            ... on  (stored + 30.0) < w8
 当分钟或小时结束时，总和每秒增加 1，减少 58（18:45:20 为 2125，19:20:00 为 2081）；只有日得以延续。 `Hour+Minute+Second` 跨度为 0..141，因此在一个小时内准备就绪后，等待会持续到第二天或更长时间。代码中没有持续时间。

切勿更改游戏机的时钟或系统设置来清除它：BDSP 会检测到更改并锁定一天的基于时间的功能。将时钟向后拨可以恢复惩罚；只有 `SecondSave` 将计数器清零。
