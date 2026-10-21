
<a id="bdsps-own-protocol-and-controlling-a-character"></a>
# BDSP自己的协议，并控制一个字符

在 Pia 有效负载内部，BDSP 运行类型化协议。 `Dpr.NetworkUtils.NetDataParser` 中
`TeamLumi/opendpr` 是该游戏的反编译 C# 娱乐版本，列出了每条消息：一个 `ANetData<T>`，其中一个单字节 `DataID` 围绕着一个普通结构体 `T`。

<a id="framing"></a>
## 框架

    0x0  1  data id
    0x1  2  payload length, big-endian
    0x3  .  the struct, little-endian, packed

`JoinData` (`byte, byte, byte, short, Vector3`) 在线上为 17 个字节，在 C# 的默认对齐方式下为 20 个字节。

`NetDataParser` 注册65条消息； `pokeldn/bdsp/netdata.py` 包含所有这些，由
`opendpr` 由 `scripts/gen_bdsp_netdata.py` 结账。来源决定了 53 种布局。其他 12 个包含 C# 字符串、数组或列表 (`netdata.OPAQUE`)，由二进制决定它们。

负载是封送后的结构体（`ANetData<T>.ConvertStructToBytes` [main.bin 0x27bb0e0]：`Marshal.SizeOf`、`AllocHGlobal`、`StructureToPtr`），字符串和数组使用固定长度字段。结构体长度来自 `Il2CppTypeDefinitionSizes` 的 `native_size`；字符串长度来自 `global-metadata.dat` 的 `fieldMarshaledSizes`；数组数量由其他字段留下的空间决定。`CodeRegistration.interopData` 中的 `marshalToNative` 写入精确字节 [1.3.0 main 0x4acd0c8，0x255 项，每项 56 字节]。捕获的四种不透明负载逐字节匹配（`room.NATIVE_SIZES`、`room.MEASURED`）。标为 1.3.0 main 的地址属于明亮珍珠，晶灿钻石 1.3.0 的相同方法位于其他地址。

|编号 | 厦门 |字节|布局|
|---|---|---|---|
| 0x02 | `PosListData` | 72 | 72 12 x `PosData`（ushort posX，ushort posZ，短 rotY）|
| 0x13 | `TradePokeData` | 328 | 328一个存储大小的加密 PB8 |
| 0x14 | `NetRecodeData` | 694 | 694 `RECORD` 120、`RANDOM_SEED` 132、`TvRecodeData` 204、4 x `TV_STR_DATA` 36、`RECORD_HEAD` 48、10 个整数、6 个字节 |
| 0x15 | `BallDecoData` | 143 | 143 affixSealCount、Is3DEditMode、IsAppliedTemplate，然后 `AttachSealData` 140 (20 x `SealParam{short x, y, z; byte id}`) |
| 0x18，0x54 | `UgSecretBase` | 616 | 616短zoneID、posX、posY；字节方向、扩展状态； int 好计数； 30×`UgStoneStatue` 20；布尔 isEnable (4) |
| 0x22 | `StanbyListData` | 20 | 5 个 `StandbyData`（isAddPlayer、hostIndex、myIndex、langId）|
| 0x24 | `TradeTranerData` | 32 | 32 13 UTF-16 字符、uint tranerId、字节 cassetVersion、字节 langId |
| 0x29，0x61 | `UgStationID_to_DigFossilIDList` | 8 | `byte DigFossilIDs[8]`，0..7 的排列 |
| 0x38 | `BattleMatchingPokeData` | 481 | 481 328 字节 PB8，20 x `SealParam` 7，uint AttachPokemonId，uint AttachPersonalRnd，字节索引，num，is3DEditMode，isAppliedTemplate，affixSealCount |
| 0x42 | `NetPlayerName` | 28 | 28 13 UTF-16 字符、字节性别 ID、字节语言 ID |

`BattleMatchingPokeData`的两个阵列将468分割为328 + 20密封，唯一分割匹配
`TradePokeData` 和 `AttachSealData`。

`SendStandbyPlayerData` [1.3.0主0x01e52fa0]填充了0x22的五个插槽
`UnionStateController.unionMatchWaitDataList` (`isAddPlayer = 1`, `hostIndex` 0);空列表是二十零字节。一个站用`NetDataStandbyWaitData`（0x59，相同的四个字节）添加自己：在`59 0004 01 00 01 03`（站1，法语）之后，被`ReciveMatchWaitData` [0x01e539b0]接受，下一个0x22是`22 0014 01 00 01 03` 和十六个零。 `isAddPlayer = 0` 将其删除。屏幕没有变化。

编组器不会清除其缓冲区：固定字段携带超过其值的堆残留（[交换页](bdsp_trade.md)）。 id 按半字节分组；无低半字节达到 0xA。

<a id="what-has-been-on-the-air"></a>
## 正在播出的内容

房间里的一台游戏机发送了 65 条中的 4 条（接收器丢弃环回广播）：

|编号 |类 |可靠 |不可靠|尺寸|
|---|---|---|---|---|
| 0x01 | `NetJoinData` | 2070 | 0 | 17 |
| 0x02 | `NetPosData` | 0 | 60 | 72 |
| 0x12 | `NetRequestData` | 4333 | 55 | 1 |
| 0x23 | `NetDataIsMatchWaitData` | 1734 | 0 | 1 |

根据请求，它还发送 0x09（一个字节，0 表示没有战斗设置）和 0x22；在一项活动中，0x14 和
0x15。交换消息位于[交换页面](bdsp_trade.md)。

0x23 可以位于存在字节 0x00（计数的 1505 个副本）后面，并且只能由将 0x00 作为消息的步行读取（[消息帧](pia.md#message-framing)）。每个 TCP（超过 8000 个）都是一个格式良好的消息，其长度恰好等于其字节数。

<a id="the-messages-the-console-repeats"></a>
## 游戏机重复的消息

`NetJoinData`是玩家的到来，`JoinData`的整体：

|偏移|尺寸|领域 |
|---|---|---|
| 0x00 | 1 | `avatarId`（8个女孩，0个男孩；[型号](#the-model)) |
| 0x01 | 1 | `colorId`, 0 |
| 0x02 | 1 | `cassetVersion`，0x31 |
| 0x03 | 2 | `InitRotY`，面向度数（测量的 45 的倍数），小尾数，未对齐 |
| 0x05 | 12 | 12 `InitPos`，三个小端浮点数：x、y、z |

`NetRequestData` 是一个字节，即想要的消息的 id。 `NetDataIsMatchWaitData`
`{isMatchWait = 0}` 是回答自己请求的游戏机。游戏机要求两件事：

|要求|次 |
|---|---|
| `NetDataIsMatchWaitData` (0x23) | 4333 |
| `NetCharacterStateData` (0x04) | 55 |

游戏在创建角色时询问每个角色的站状态，因此 0x04 请求表示角色存在（55 个请求，在 265 个未绘制角色的连接中没有一个请求）； `bin/bdsp_connect.py` 将其打印为判决。游戏机重复其 0x23 请求，直到客户端确认其可靠窗口； 75 秒内收到了 487 个未确认的请求。

`UnionRoomManager$$SetNetData` [1.3.0 main 0x01e50700] 为六个 id 回答 `NetRequestData` 并忽略其他所有：

|请求|游戏机发送|通过|
|---|---|---|
| 0x01 `NetJoinData` |其加入记录 | `UnionRoomManager$$SendJoinData` |
| 0x04 `NetCharacterStateData` |其性格状态 | `UnionRoomManager$$SendOpcStateData` |
| 0x09 `NetDataBattleTypeData` |它的战斗规则| `UnionRoomManager$$SendBattleRuleData` |
| 0x13 `NetTradePokeData` |它所提供的宝可梦| `UnionRoomManager$$SendPokeData` |
| 0x22 `NetDataStandbyWaitListData` |其候补名单| `UnionRoomManager$$SendStandbyPlayerData` |
| 0x23 `NetDataIsMatchWaitData` |是否等待匹配 | `UnionRoomManager$$SendIsMatchWait` |

在请求后 30 到 130 毫秒内测量，房间内有一个角色的工作站有 5 个在可靠流上得到应答；当没有选择宝可梦时，则不是0x13（返回`SendPokeData`）。基础游戏的处理程序 [base main 0x01fd4600] 回答相同的六个，然后命名为 0x22
`NetDataTradeStandbyData`。请求到达其答案所使用的流：可靠流上的 0x23 全部为 4333，不可靠流上的 0x04 全部为 55。

<a id="compression"></a>
### 压缩

可靠标头的标志 0x10 标记 zlib 流。发送者根据大小决定：
`ReliableSlidingWindow`的推送[1.3.0主`0x15a10d0`]测试了窗口的压缩开关（+0x7ac，`0x15a1364`），当它在`0x159a500`上时，压缩了整个游戏消息，其3字节头包括：

    0x1685384   deflateInit2: level 5, window bits 12, memLevel 5, strategy 0, 4000-byte output
    0x16854e0   deflate(Z_SYNC_FLUSH)
    0x1685608   deflate(Z_FINISH)
    0x159a5b0   compressed size >= raw size  ->  error 0x2c7d, the message goes raw
    0x15a1398   otherwise: header |= 0x10, send the compressed bytes
 所有 55 个标记的游戏机消息与 Python 的字节相同
`zlib.compressobj(5, zlib.DEFLATED, 12, 5)` 具有同步刷新，然后完成，并且 10955 个未标记的没有一个在其下收缩。连接和单记录 0x22 列表是原始的；全零 0x22 列表（原始读取看起来像 `NetBonusStart`）、记录（0x14）和球囊（0x15）收缩。接收器永远不需要压缩； `bin/bdsp_connect.py` 在旗帜上充气。

<a id="senders-of-the-other-opaque-messages"></a>
### 其他不透明消息的发送者

来自1.3.0中每个`ANetData<T>.SendReliableData`的调用者：

|编号 |类 |发送者 |
|---|---|---|
| 0x14 | `NetDataRecodeData` | `RecodeMatching$$SendRecodeData`，`UnionStateController$$SendRecodeData` |
| 0x15 | `NetDataAttachSealNetData` | `BallDecoMatching$$SendBallDecoData` |
| 0x18 | `NetSecretBaseData` | `UgNetworkManager$$SendMySecretBaseData`;根据要求（`OnReceiveRequestData`）|
| 0x61 | `NetDigTableData` |根据要求（`OnReceiveRequestData`）|
| 0x38 | `NetDataBattleMatchingSelectPokemon` | `BattleMatchingManager$$SendSelectPokemonData` |
| 0x42 | `NetPlayerNameData` | `UgNetworkManager$$SendOnJoinNewPlayer`，`SendPlayerNameData` |
| 0x54 | `NetSecretBaseUpdate` |没有可靠的发件人； `netdata.py` 命名 |

<a id="the-unreliable-stream"></a>
### 不可靠的流

它承载着三个信息：

|字节|次 |留言 |
|---|---|---|
| `04 0002 00 00` | 853 | 853 `NetCharacterStateData{state: NONE, isRecruiment: 0}`，每两秒测量一次 |
| `12 0001 04` | 55 | 55 `NetRequestData`：“将你的`NetCharacterStateData`发送给我” |
| `02 0048 <72 B>` | 60| `NetPosData`，十二点，而游戏机的头像行走|

`room.build_state()` 构建第一个 `room.build_match_wait(False)` 游戏机自己的 0x23 答案。

游戏机重新传输可靠的消息，直到确认信号覆盖该消息（每秒测量五次）；超出其最后序列的 2 个 ack 将被忽略。一旦游戏机确认了客户端自己的数据，`bin/bdsp_connect.py` 将在最后一个序列处进行确认加一。

<a id="sending-messages-the-game-acts-on"></a>
## 发送游戏所作用的消息

可靠的序列ID与游戏机自己的发送共享，并且在其确认名称的ID下方的消息被默默地丢弃。每次发送前立即读取 id。

按确认序列发送的加入将起作用：在间隔 0.4 秒发送的 15 个加入中，游戏机请求 0x04 12 到 15，即第一次加入后的前 0.10 到 0.57 秒。
`--room-pattern fixed` 在第一个请求时停止，为每个连接提供 `--join-wait` 秒（默认 1.0）。

`UnionOpcManager` 在每个连接上调用 `CreateCharacter(joinData)`：四十个连接相当于四十个到达。在一台实机上，创建的角色后面没有会话，会跟随玩家穿过地图，直到游戏重新启动，并且当其站离开网格时，已移动的角色会被移除。不跟踪出发时的移除路径（`OpcManager$$RemoveCharacter` [0x02279ee4] 采用车站索引）。

<a id="the-character-record"></a>
## 人物记录

`OpcManager.CharaData` 是
`{int stationIndex, string assetName, int colorId, int avatarId, int sexId, int cassetVersion}`，由站键入 (`RemoveCharacter(int stationIndex)`)。

<a id="the-model"></a>
### 模型

`OpcManager.CreateCharaData(ANetData<JoinData>)` 从连接构建记录，`avatarId` 选择出现的人：

    NetJoinData.avatarId  ->  CreateCharaData  ->  CharaData.avatarId
                          ->  UnionCharacterTable.SheetSheet1{ID, AssetName}
                          ->  OpLoadCharacter("persons/field/" + assetName)

`CreateCharaData` [1.3.0 main 0x022796b0] 仅按外观设置 `sexId`，条件为 `avatarId > 7 &&
avatarId != 16`（`0x02279770`）：8 至 15 为女孩，0 至 7 和 16 为男孩。`GetOpcSexId` [0x02279840] 返回此值，`GetNpcColorId` 读取相同外观：8 是女孩，0 是蓝帽男孩（`--join-avatar N`）。

游戏机加入时携带变量 360（`SendJoinData` [0x01e4f630] 经 `GetAvaterId` [0x01e54030]）。新存档初值为 0，创建存档不选择联合房间外观；原生代码仅通过这两个方法读取，两个脚本写入。可选外观柜台（`ev_union_character_select_*`）按存档性别（`_GET_MY_SEX`）提供八种训练家职业：男孩存储 16 或 1 至 7，女孩存储 8 至 15。未使用柜台且变量为 0 时，`ev_connect_union_check_save` 和 `ev_connect_global_check_net` 调用 `ev_traner_other_see_random`，设为 1 加一个小于 16 的随机值（`_GET_RND`、`_ADD_WK`），可能是任一性别。仅使用柜台后，加入外观才表示存档性别，消息没有说明玩家是否使用过柜台。

`NetDataTranerCardData`（0x05，75 字节：`fashionId`、`bodyType`、`genderid`，...）
`UnionOpcManager.CreateTranerCard()`；收到的一个在联合房间的屏幕上没有绘制任何内容。

<a id="the-state-byte"></a>
### 状态字节

`StateData` 是 `{byte state, byte isRecruiment}`、`state` 和 `OpcState.OnlineState`：

|价值|名称 |价值|名称 |
|---|---|---|---|
| 0 | `NONE` | 5 | `RECRUITMENT_RECORD` |
| 1 | `DIG_FOSILL` | 6 | `RECRUITMENT_GREETINGS` |
| 2 | `SECRETBASE_ACTION` | 7 | `RECRUITMENT_BALL_DECORATION` |
| 3 | `RECRUITMENT_BATTLE` | 8 | `COMMUNICATE` |
| 4 | `RECRUITMENT_TRADE` | | |

17 到 21 是 `NOW_*` 状态，每个活动一个（[transitionType 表](#talkstate-and-the-value-that-crashes-the-game)）。
`OpcController.ShowEmoticon(OnlineState)` 和 `GetEmoticonType(state)` 读取； `RECRUITMENT_*` 值会引发气泡。用 `StateData{RECRUITMENT_TRADE, 1}` 回答游戏机的请求会在零售屏幕上放置一个交换气泡； `StateData{NONE, 0}` 没有任何改变。

收到的 0x04 变为 `UnionRoomManager$$OnReceiveData` [1.3.0 主 0x01e506c0] ->
`OpcManager$$SetNetData` [0x02279450]（当站没有字符时丢弃）->
`UnionOpcController$$SetNetData` [0x01e48c50]，其唯一的消费者：

    if state != GetOpcOnlineState():      SetOpcOnlineState(state)                 0x02277be0
                                          isRecruiment == 1 ? SetEmoticonHost()    0x022779b0
                                                            : SetEmoticonNormal()  0x02277a50
    if state != 0:                        AnimationPlayer.Play(animation 0)
 地下双胞胎是 `UgOpcController$$SetNetData` [0x01f7f820]。

`OpcState` 是 `{OnlineState _curretOnlineState +0x18; Action<OnlineState> _OnChangeState +0x20}`，由 `OnlinePlayerCharacter$$Start` [0x02276ff0] 添加，Action 绑定到 `ShowEmoticon` [0x02277094]；状态从 0 开始。`SetOpcOnlineState` [0x02277c80] 是其唯一的实时存储（`OpcState$$OnChangeOnlineState` [0x02277d10] 没有调用者）。 setter 的调用者（虚拟，类偏移 0x190）中，有 3 个触摸远程字符：具有接收状态的 `UnionOpcController$$SetNetData` [0x01e48d7c]，以及 `OpcManager$$RemoveCharacter` [0x02279ee4] 和 `UgOpcManager$$RemoveAllCharacter` [0x01f80cac] 为 0。因此，远程角色的状态仅在来自其自己站的 0x04 上发生变化。其余设置游戏机自己的：`UnionSystemController$$ChangeOpcState` [0x01c2d3f8]（其参数，然后是
0x04 广播 [0x01c2d4d0]), `RusultGreetJoinYesNoWindow` [0x01c2e8ac] 6,
`<CreateContextBattleTypeMenu>b__0` [0x01f8b790] 3, `UnionTradeManager$$InitPlayerState` [0x01c33a58],
`UnionStateController$$InitPlayerState` [0x01e4e83c] 和 `SwitchCancelEnd` [0x01e4fd70] 0,
`UnionStateTransitionController$$StartFadeOut` [0x01e5a00c] 其型号为+0x2c，
`UgNetworkManager$$OnReceiveJoinDigPermission` [0x01f7ca94] 和 `SendOnPlayDigFossil` [0x01f79f78] 14，以及 `UgNetworkManager$$SetMyEmoticon` [0x01f79148]。

在 `Start` 运行之前，getter 返回 0 [0x02277dcc]，setter 会删除值 [0x02277c50]。角色的 0x04 请求在 `SetActive(true)` 之后立即发出
`CreateCharacter` 加载回调 [0x01e49854]，因此在 `Start` 之前到达的答案会丢失；每两秒重复一次该状态，就像游戏机一样。

`OnlinePlayerCharacter$$IsCanTalkState` [0x02277af0]：玩家可以与状态1、3到8以及17到21对话，而不能与状态0、2或9到16对话。

<a id="walking"></a>
### 步行

游戏机自己的 `NetPosData` 每 0.410 秒出现一次，跨越 0.935 个单位（`room.POS_PERIOD`，
`room.POS_STRIDE`； `--room-walk-period`、`--room-walk-stride`)；每 0.35 秒行走 0.1 单位会显示为口吃。

`PosData` 是 `{ushort posX, ushort posZ, short rotY}`、`pos = (-posX * 0.05, posZ * 0.05)`：一个单位的二十分之一，x 取反。远程角色与墙壁碰撞（玩家不会与其碰撞）并按字面意思保留 `rot_y`。在房间内散步：游戏机的六十条消息穿过房间并穿过远处的墙壁，`--room-walk-steps 8` 留在里面。

交易无需步行：实机与客户角色完成了两次交易，而客户角色没有发送任何信息
`NetPosData`（`--room-walk-steps 0`，交换路径上的默认值）。

<a id="being-talked-to"></a>
## 正在与人交谈

具有表情的玩家会留在原地，直到有人互动，并且当玩家的状态非零时，玩家自己的 A 按下不会执行任何操作（[游戏机接近](#the-console-approaching)）。游戏机广播表情：

    NetCharacterStateData{state: 4, isRecruiment: 1}     the trade emote, up
    NetCharacterStateData{state: 0, isRecruiment: 0}     and down again
 `isRecruiment` 上的门：状态 18 是已经在交换中的游戏机，并且拒绝接近它。实机在其交换表情后 0.0 秒（40 毫秒后）应答了发送的接近，因为它在 3.0 秒后应答了发送的接近：`IsCanTalk 0, IsRecruitment 1, emoticonStateType 4`（`bin/bdsp_host.py
--approach-delay`，默认 0）。

方法是 `NetDataTalkReserveData` (0x63)、`63 00 01 00`，如游戏机发送的那样 (`bin/bdsp_connect.py --initiate-talk`)。游戏机的玩家接近客户的角色，按顺序：

    cli ->  64 0003 00 01 04      NetDataTalkReserveResultData{IsCanTalk, IsRecruitment, emoticonStateType}
    con ->  06 0005 00 01000000   NetDataTalkData{talkOpcSexId: 0, talkState: GREETING}
    con ->  10 0002 01 04         NetDataTalkCancelEndData{IsRecruitment: 1, emoticonStateType: 4}
 谈话等待0x64；如果没有得到答复，玩家的角色就会保持冻结状态。

| `IsCanTalk` |然后发送 |屏幕|
|---|---|---|
| 0 |什么都没有|问候语运行并停在“一秒钟！” |
| 1 |什么都没有，`NetDataSelectData{0}` 或 `{1}` | “抱歉，我有其他计划”，聊天结束 |

放下电台会发出驻留问候语； B 没有可靠地留下一个。

<a id="the-console-approaching"></a>
### 游戏机即将来临

`UnionRoomManager$$MyUpdate`[1.3.0主0x01e49fb0]仅当玩家自身状态为0时处理A按[0x01e4a644]，`UnionWork.isTalking`（静态+0x85）为0，没有菜单或消息窗口打开并且玩家在每个外部`EnterCollision` 圈。它会在 10.0 单位内行走角色，并且玩家的 `talkDistance` (+0x38) 的状态通过 `IsCanTalkState`：

|角色的状态 | A 做什么 |
|---|---|
| 0、2、9 至 16 |什么都没有|
| 8、17 至 21 |步行后，`UnionRoomManager$$StartTalk(opc, 0, 0, 0)`[0x01e4c2d0]就最近；没有消息 |
| 4 | `UnionSystemController$$CheckErrorMessageTrade` [0x01c2e8d0];没有错误，如最后一行 |
| 7 | `UnionSystemController$$CheckBallDeco` [0x01c2ec20];当它通过时，作为最后一行 |
| 1、3、5、6 | `NetDataTalkReserveData`（0x63）到角色的站[0x01e4ac94]，状态存储在`nowTalkReserveState`（+0x188）中，`isTalking`设置，`UnionStateController$$CreateSelectStateModel(state, 1)` [0x01e4b620] |

对于状态 1 和 3 到 7，步行立即作用于比之前的字符更接近的第一个合格字符。

游戏机回答 0x63，在 `UnionRoomManager$$SetNetData` [0x01e50c3c] 中：

    r.IsCanTalk = UnionWork.isTalking
    if stateController._currentModel (+0x88) is null:
        r.IsCanTalk = 1; SendOpcStateData(requester)
    r.IsRecruitment = 1
    r.emoticonStateType = the console player's own state
    send r (0x64) to the requester                           0x01e5110c
    if isTalking was 0 and r.IsCanTalk is 0: isTalking = 1
 游戏机在自己的 0x63 [0x01e50dec] 之后读取 0x64：

    canTalk = IsCanTalk == 0 and not isCancelStock (+0x183, cleared here)
    if emoticonStateType != nowTalkReserveState:
        send NetDataTalkCancelEndData{0, 0}                  0x01e50f24
    else:
        nowTalkReserveState = 0                              0x01e50ea0
        canTalk ? StartTalk(opc, IsRecruitment == 0, 1, 0)
                : the refusal path 0x01e512f0 (the character's state against 3 to 7)
人物广告`{4, 1}`画`63 0001 00`在 A 上，并且`64 0003 00 01 04`开始谈话。任何其他`emoticonStateType`画`NetDataTalkCancelEndData{0, 0}`，第二个也是如此0x64为了同样的0x63，第一个已清除`nowTalkReserveState` [0x01e50e94]。逐一回答0x63一次，而不是每次重传的副本。

游戏机作为说话者，客户的角色是招聘人员。招聘人员对交换提议（`UnionTradeContextMenu.<>c__DisplayClass10_0.<ShowTradeYesNoWindow>b__0` [0x01c32f70]）表示“是”；“否”是 `TradeRecruitmentStateModel$$Cancel` 0x01c24150）打开消息 8 和尾部呼叫
`UnionContextMenu$$SendTransitionData(station, 0)` [0x01f86480]，发送
`NetDataTransitionData{menu+0x50, 0}` 可靠； `SetTransitionType` [0x01c32ef0] 将 +0x50 设置为 18。 是的是 `07 0002 12 00`，当客户接近招募游戏机时发送的消息（[交换页面](bdsp_trade.md#the-message-sequence)）。在 0x64 开始在会说话的游戏机上进行交换而玩家没有同意后，类型 18 的 0x07 （`SwitchTransitionMessage` [0x01e53bf0] -> `TransitionTradePoke` [0x01e5c1c0]，如下）：游戏机发送其 `NetDataTradeTranerData` (0x24) 并打开交换框。接近客户端状态 4 字符的实机接收 0x64 应答后发送的 `07
0002 12 00` 并完成交换。

在会说话的游戏机上，状态 4 角色上的 A 在以下位置构建了 `TradeJoinStateModel`
`UnionStateController+0x50`（`CreateSelectStateModel(4, 1)`，存储0x01e4b814，唯一一个，从未清除）。 0x64 运行 `SwitchTalkStateMine` [0x01e4c41c]：18 进
`UnionSystemController.onlinePlayerSelectState` (+0x28) 和 `SetTargetStationIndex(station,
cassetVersion, 1)` [0x01e54ae8]。 0x07 无需状态测试 [0x01e52610]，即可
`SwitchTransitionMessage` [0x01e53bf0]，读取类型的模型（字节表0x03db869b），不进行空测试；对于交换 `TradeJoinStateModel$$OpenSwitchFadeMsg` [0x01c22f50] 以发送者的性别打开消息 9 或 10，发音为 `OPPONENT` (`SpeakerID` 1)，关闭为 `StartFadeOut`。褪色后
`SwitchTransition` [0x01e5ba70] 发送 18 到 `TransitionTradePoke` [0x01e5c1c0]，它获取并清除目标站，检查 `IsGamerActive` 并发送游戏机的 0x24 [`SendTranerData`
0x01e5c2b0]：加入方方向交换的开始。一个 0x07 到达一个游戏机，该游戏机自 `UnionStateController` 构建以来从未在交换招聘人员上按过 A，读取 null (0x01e53c4c)；其他过渡类型在其自己的模型上具有相同的形状。

<a id="the-name-in-the-greeting"></a>
### 问候语中的名字

问候语、其扬声器标签和战斗阶梯的“正在选择”行通过其电台的 Pia 玩家名称来命名角色：`UnionBaseMsgWindow$$SetTargetDataMessage` [1.3.0 主 0x01f86810] 和
`GetSpeakerName` [0x01f87050] 读取 `NetworkManager$$GetGamerData(station)` [0x02250e50] (`IlcaNetGamer.gamerName` +0x30、`nameStringLanguage` +0x38)。 `NetGamerNameGet` [0x0273a9a0]，在 Pia join 事件上，将 `INLpiaSessionGetPlayerInfo` [0x01e15cd0] 中 80 字节缓冲区的 `length - 1` 字节解码为 UTF-8（长度为 2 下为空），并复制原始语言字节。

`Utils$$CheckNGTrainerName` [0x01cbdc30] 将名称替换为
`Utils$$GetReplacedNGName(UnionWork.nowTargetCassetVersion)` [0x01cbde20] 当为空时，当
`CheckNgWords` [0x01c99220] 对其进行标记，或者当它的 UTF-16 单位多于
`SoftwareKeyboard$$LanguageMaxLength(6, lang)` [0x01c995b0]：

| `lang` |限制|
|---|---|
| 1、8、9、10 | 6 |
| 其他任意正值 | 12 |
| 0 或以下 | UI 的当前语言决定 |

语言为PlayerInfo字节0x7A。 Mesh Station 协议的解析器 [0x0154f044..0x0154f5e0] 每次迭代读取一个 195 字节的 PlayerInfo (`add w23, w23, #0xc3` 0x0154f588)；无论编码如何，偏移量都是固定的：

|偏移|领域 |阅读 |
|---|---|---|
| 0x00 |名称编码| 2：20个UTF-16单元（0x0154f078..0x0154f15c）；其他：80 字节 |
| 0x01..0x50 |名称 |进入站记录+0x120 +索引*0x80 |
| 0x51 |第二个字符串的编码 | 0x0154f220 |
| 0x52..0x79 |第二个字符串，40 字节 |编码 2：10 个 UTF-16 单元，为 +0x320 + 索引*0x58 |
| 0x7A |语言 | `strb w8, [x20+x25, #0x480]` 0x0154f5a0 |
| 0x7B..0xBA | 64 字节 | 0x0154f5b8 |
| 0xBB..0xC2 | u64 | 64至 +0x490 + 索引*8 |

`INLpiaSessionGetPlayerInfo`到达`0x01391a90`，默认该字节为0xFF[0x01391b44]，并将站记录的+0x480原封不动地复制到`NetGamerNameGet`的`nameStringLanguage`中[0x01391bb0]。该字节是 `MsgLangId`：

    JPN 1, USA 2, FRA 3, ITA 4, DEU 5, ESP 7, KOR 8, SCH 9, TCH 10
 游戏机通过 `IlcaNetBase$$PlatformInitialize2` [0x01e13ce0] 发送自己的 `MessageManager$$get_UserLanguageID` 及其 `CheckNGTrainerName` 检查名称（`SessionConnector$$ResetParam` [0x0202f050]） `PiaPlugin$$RegisterStartupSessionSetting` [0x0227d5a0]，并且站协议的 PlayerInfo writer 将 +0x480 放在字节 0x7A [0x01550e98] 处。法语版游戏机的连接响应（站协议类型2）携带编码1、其名称、字节0x79 0和字节0x7A 3。

语言字段取自发送方游戏的文本语言，即存档中的 `CONFIG.msg_lang_id`（PlayerWork +0xac，`get_msgLangID` [0x0237e100]）。只有保存的值不在 1..10 范围内时，`GameManager.<OnetimeInitializeOperation>` [0x01e0eb44] 才会根据系统语言（`GetCurrentIetfCode`）填入该值。本机站点记录的 +0x480 通过四次复制得到 PlayerInfo 的语言字节：

| 步骤 | 代码 | 来源 | 目标 |
|---|---|---|---|
| `RegisterStartupSessionSetting` | `0x0156f918`（设置构建器，`0x0156fa08`），`0x0168d4c8` | 插件的玩家数组（步长 0x28） | 框架保存的设置 +0x3220：PlayerInfo +0x18、语言 +0x98、步长 0x98 |
| `ChangeStateJob::StartupSession` | `0x01690d6c` -> `0x0168c5b8` -> `0x0157d36c` -> 控制器虚函数 2（`LocalMatchMeshLayerController` `0x016c3e70`） | 设置中的首个 PlayerInfo（`0x016c3f48`） | 控制器的玩家列表 +8、语言 +0x88、数量 1 位于 +0x268 |
| `CreateSessionJob::MeshStartup` `0x015873b0`，`JoinSessionJob::MeshStartup` `0x015884bc` | 控制器虚函数 4（`MeshLayerController` `0x0171a068`）-> `0x01546fa4` | 控制器的列表 | 网状网络对象（`[0x04c4db60]`）+0x128 + n*0x98、语言 +0x80（`0x015472e4`）、数量 +0x388 |
| `CreateMeshJob::SetupLocalPlayerInfo` `0x0155a764`，`JoinMeshJob::SetupLocalPlayerInfo` `0x0155b988` | `0x015494f0` | 网状网络对象的列表 | 本机站点记录 +0x480 + n（`strb w8, [x23, x22]` `0x0154956c`） |

`ChangeStateJob::StartupSessionBegin`（`0x01690c70`）会直接进入 StartupSession；若框架 +0x7c 为 0，则先经过 `StartupSessionJob`（`0x0168ec7c`，设置位于任务 +0x70）和 `WaitStartupSessionLdnInitialize`（`0x01690e30`）。`StartupSessionJob` 只有一个实际执行的步骤 InitializeLdn（`0x0168ed74`），不会复制 PlayerInfo。法语游戏机发送的 30 个 PlayerInfo（17 个连接响应、13 个连接请求）中，字节 0x7A 均为 3，字节 0x51 均为 0。

`bin/bdsp_connect.py` 和 `bin/bdsp_host.py` 都使用 `pokeldn/bdsp/host.py` 构建 PlayerInfo
`player_info`（编码1，UTF-8名称，字节0x51 0）并发送`--language`，默认3；桌面应用程序通过其培训语言。 3岁以下，11个字符的名字显示完整。

替换取决于对话角色的 `CharaData.cassetVersion`，其字节 2
`NetJoinData`，这两个呼叫者的问候语（`SwitchSpokenStateMine` 0x01e53b58，
`MessageEndSpokenData` 0x01e57ab8）存储在`UnionWork.nowTargetCassetVersion`（静态+0x8C）中。
`GetReplacedNGName` 采用 `dp_characters` 的标签 247 表示 0x31，否则采用标签 206 (0x01cbdecc) 并附加句号。来自 1.3.0 RomFS `Message/<language>` 捆绑包的文本：

|捆绑| 0x31 (明亮珍珠), `DP_CHARACTERS_247` |还有什么，`DP_CHARACTERS_206` |
|---|---|---|
|英语 | `Pearl.` | `Diamond.` |
|法语 | `Perlo.` | `Diamant.` |
|德语 | `Perl.` | `Diamant.` |
|意大利语 | `Perl.` | `Diaman.` |
|西班牙语 | `Perla.` | `Diamant.` |
|日本，jpn_kanji | `パール.` | `ダイヤ.` |
|韩语 | `펄.` | `다이아몬드.` |
| 简体中文（simp_chinese） | `帕尔.` | `戴亚.` |
| 繁体中文（trad_chinese） | `帕爾.` | `戴亞.` |

<a id="talkstate-and-the-value-that-crashes-the-game"></a>
### talkState，以及导致游戏崩溃的值

`TalkState` 为 `{CHECK = 0, GREETING = 1, NONE = 2}`；停放的游戏机在 `GREETING` 中等待。
`UnionStateController$$SwitchSpokenStateMine` 发送除 CHECK 之外的任何内容
`StartOpenGreetingMsgWindow`（`b 0x1fd85e0` 位于 0x1fd5e80）； CHECK 加载 `systemController->msgWindow` (0x1fd5e84) 并在没有空保护的情况下取消引用它 (0x1fd5ec0)。玩家站着并发出表情时没有消息窗口，因此 CHECK 会使游戏崩溃； `pokeldn/bdsp/room.py` 拒绝发送。在读取接收方的处理程序之前，切勿发送从发送方读取的状态值。

`NetDataTransitionData{transitionType, isRecruitment}` (0x07) 将驻留问候语推进到活动中。游戏将其作为尾调用发送，因此仅 BL 调用者扫描会将其报告为从未发送（[查找调用者](switch_re.md#finding-callers)）。 `transitionType` 是 `OnlineState`；
`UnionStateTransitionController$$SwitchTransition` [1.3.0 main 0x01e5ba70] 通过一个 19 条目的表对其进行调度，并且 `SwitchTransitionMessage` 读取 `UnionStateController` 处的模型 + 下面的偏移量：

|过渡类型 |活动 |通过 | 输入型号|
|---|---|---|---|
| 3, 17 |战斗| `TransitionBattle` | +0x38 或 +0x40 由 `isRecruitment` (`tbz w4`) |
| 4, 18 | 交换 | `TransitionTradePoke` | +0x50, `tradeJoinStateModel` |
| 5, 19 |混合记录| `RecodeMatching$$Open` | +0x60 |
| 6、20 |训练家卡| `TransitionShowTrainerCard` | +0x70 |
| 7、21 |球胶囊| `BallDecoMatching$$Open` | +0x80 |
| 8 至 16 |无 | |没有任何;返回 |

`RecodeMatching$$Open`和`BallDecoMatching$$Open`立即发送游戏机自己的记录（0x14，
0x15) 并等待；只有合作伙伴的（`StartRecodeTradeFlow`、`StartBallDecoTradeFlow`）写入保存。

<a id="record-mixing"></a>
### 录制混音

游戏机通过 Y 菜单（状态字节 5）中的“Échanger des données”进行招募。当客户端走上来并且玩家说“是”时，它会发送 `NetDataTransitionData{5, 0}`，然后是 694 字节
`NetDataRecodeData`（205 字节 zlib 流；测量后 1.5 秒），并在状态 19 处等待 (`NOW_RECORD`)。没有得到答复，它显示“un des attendees n'est plus disponible”并返回房间；测量的等待时间为 44 秒，并且未找到计时器。 `room.parse` 返回记录的头部为 `recode`：

    RECORD.record[30]        thirty uint counters indexed by RECORD_ID (CLEAR_TIME, DENDOU_CNT,
                             CAPTURE_POKE, ..., CONTEST_RATE_SINGLE)
    RANDOM_SEED              group_name (16 chars), name (32 chars), int sex, int region_code,
                             ulong seed, ulong random, long time_stmp (a Windows FILETIME),
                             int user_id (the trainer id)
    TvRecodeData             five TV records (personality, ball decoration, fossil digging,
                             statue, fashion), each `bool isEmpty` (4 bytes), ints, a TV_STR_DATA
    4 x TV_STR_DATA          {16-char value, byte language, genderId, two reserved}
    RECORD_HEAD              13-char username, int language, byte sex, int body_type,
                             uint uniqueID (the trainer id again)
    ten ints, six bytes      the per-TV branch values, myVersion (0x31), five *IsNotEmpty flags
 未写入字段保存 64 位堆指针。 `RECORD_HEAD.sex` 和 `RANDOM_SEED.sex` 在一条记录中可能不一致（捕获的记录中为 0 和 1）。 `RECORD`、`RANDOM_SEED` 和 `RECORD_HEAD`（命名空间
`DPData`) 元帅位于包 4，`TvRecode*` 结构位于包 8；在这些字段大小下没有填充结果。

<a id="the-battle-ladder"></a>
### 战斗天梯

对战（“Combattre”，招募时状态字节为 3）按以下交互流程进行；招募方主机在每一步都等待加入方（此处为客户端）：

| 加入方发送 | 主机的行为 |
|---|---|
| `NetDataTalkData{GREETING}` | 显示“Un combat ? OK ! Donne-moi juste une minute !”（要对战？好！稍等我一下！）并等待 |
| `NetDataSelectData{0}` (0x08) | 显示“POKELDN est en train de choisir quoi faire...”（POKELDN 正在选择要做的事情……）并等待 |
| `NetDataBattleTypeData{0}` (0x09, `BattleModeID.Single`) | 询问玩家“voulez-vous faire un combat selon ces règles ?”（是否按这些规则对战？）；选择是后发送 `NetDataTransitionData{17, 0}`，状态字节为 17，并打开显示“connexion en cours”（正在连接）的单打大厅 |
| `NetDataBattleMatchingJoin` (0x30) `{uint id, byte stationIndex, index, language, colorId, avatarId, sexId, cassetVersion}` | 以本站的加入消息回复（`id` 为训练家 ID，station 为 0，index 为 0），并转发加入方的消息；加入方角色出现在大厅的第二个位置 |
| `NetDataBattleMatchingReady`（0x32，内容为空） | `BattleMatchingManager$$ReceiveReadyData`：全员准备完毕后发送 `NetDataBattleMatchingState{0, 6}`（0x33），进入 `MatchingState.SelectBattleTeam`（单打跳过 4 和 5），玩家获得队伍选择按钮 |
| 不发送消息 | 玩家选择队伍后，发送六条 `NetDataBattleMatchingSelectPokemon`（0x38，481 字节），随后显示“en attente d'autres personnes”（等待其他玩家） |

每条 0x38 包含一个校验和有效的加密 PB8（按选中队伍的顺序）、二十个具有相同堆残留数据的 `SealParam` 槽位；其中 `affixSealCount` 为 0，`attachPokemonId` 和 `attachPersonalRnd` 为 0，`index` 为 0 至 5，`num` 为 6。一台主机接受了 `id` 为 0x0badc0de 的 0x30；尚未找到对该字段的检查。`BattleMatchingManager.MatchingState` 的枚举值为：None 0、Initialize 1、Load 2、RecruitmentMember 3、SelectTeamMember 4、SelectRule 5、SelectBattleTeam 6、SelectPokemon 7、GoBattle 8、Result 9、Resume 10、Closing 11、LeavedOtherMembers 12。

`NetDataSelectData`（0x08）对应 `{byte index}`。唯一的接收器 [`UnionRoomManager$$SetNetData`，0x01e52a30] 读取发送方的站点，而不读取 index：

    m = stateController.battleRecruitmentModel                  UnionStateController +0x38
    m.ChangeBattleRecruitmentState(BATTLE_RULE_SELECT_WAIT 4)   0x01d2aab0
    m.currentCancelModel = {SelectCancel 0, station}
    m.CloseWindow()
    if m.unionMsgBattleWindow != null:
        SetTargetDataMessage(window, station, 1, 1); OpenMsgWindow(window, 3, 2)   0x01f86fa0

无论当前打开哪种对话，0x08 都会驱动对战招募模型。两个发送器都写入 0（`UnionBattleContextMenu$$SendRuleSelectState` [0x01f87c60] 为尾调用，以及 `<ShowBattleJoinYesNoWindow>b__0` [0x01f8800c]）。

接收方从不检查模型是否为空：它加载 +0x38 [0x01e52a78]，分支 4 通过该指针在 `NetStateModel$$SetState` [0x023e2604] 中执行写入。唯一写入 +0x38 的位置是 `CreateSelectStateModel` [0x01e4bb08]：玩家发起对战时，为状态 3 或 17 构建 `BattleRecruitmentStateModel`（`stateModelType` 为 0；按 A 则传入 1 并构建 `BattleJoinStateModel`）。每个 `UnionRoomManager` 只构建一次 `UnionStateController`（`UnionRoomManager$$SetUp`，`.ctor` 0x01e4d01c），连接对战会保留两者（`EvDataManager$$UpdateStart` -> `UnionRoomManager$$ReturnBattle` [0x01b02a78]，不调用构造函数）。每次进入都会构建新的 `UnionRoomManager`：`EvDataManager$$EvCmdUnionProc` [0x01b35f70] 在传送进房间前将其添加到 `new GameObject("UnionRoomManager")` [0x01b36090]，没有设置 `DontDestroyOnLoad`。`UnionRoomManager$$Init` [0x01e49e40] 将区域 {484, 491, 492, 493}（`UNION`、`UNION01` 到 `UNION03`）传给 `NetUseManager.SetEnableZone` [0x026cfca0]，后者订阅 `FieldManager` 的区域变化事件；首次进入列表以外的区域时，`NetUseManager.OnZoneChange` [0x026cfef0] 调用 `Object.Destroy(gameObject)` [0x026d00f0]。离开房间（`LeaveUnion` [0x01e4e300]，其协程在 [0x01e560e0] 设置过渡区域）会触发这种变化，因此会执行 `UnionRoomManager$$OnDestroy` [0x01e4c540] 并调用 `Clear`。所以每次进入时，对战招募模型都从空值开始。如果玩家在此次进入后尚未发起对战，收到的 0x08 就会通过空指针写入：接收方没有空值检查，直接将空模型传入 `BattleRecruitmentStateModel$$ChangeBattleRecruitmentState` [0x01d2aab0]；其分支 4 以该模型尾调用 `NetStateModel$$SetState` [0x023e25f0]，而 `str x2, [x20, #0x18]!` [0x023e2604] 会写入地址 0x18。该构建在此路径上没有生成 IL2CPP 空指针检查，映像也未导入 `nn::os::SetUserExceptionHandler`。

流程表中的 0x08 是在已经招募对战的主机上测得的。客户端已使用过的序列号会被可靠窗口丢弃（[Pia 页](pia.md#what-the-receiver-discards-in-silence)）；向尚未招募对战、正在对话的主机发送的 22 条消息，使用了客户端此前某条 0x64 回复的序列号，因此没有一条进入空指针路径。

只有主机自身的 0x04 表明状态为 3 且 `isRecruiment` 为 1 时，才可发送 0x08。

<a id="the-grand-underground"></a>
### 地下大洞窟

地铁在场景 ID 12608 下发布相同的 `local_communication_id` 广告；同一会话线路关联，没有加入记录（`--room-walk 0`）。电台到达时 `UgNetworkManager` 发送：

|编号 |类 |字节|内容 |
|---|---|---|---|
| 0x17 | `NetZoneData` | 16 | 16 `Vector3 pos`、`int zoneID`（519中捕获）|
| 0x42 | `NetPlayerNameData` | 28 | 28 13 UTF-16 字符，字节性别 ID，字节语言 ID（3，法语）|
| 0x50 | `NetKousekiCount` | 4 | `int Value` |
| 0x41 | `NetSecretBaseInfo` | 16 | 16而不是秘密基地（633区）内的0x17：`Vector3 pos`，`int zoneID`，入口在楼上（519）|

命名玩家区域的 `NetUgJoinData`（0x16，18 字节：`byte avatarId, colorId; short zoneID, InitRotY; Vector3 InitPos`）会在玩家旁边放置一个角色：`OnReceiveJoinData` [1.3.0 main
0x01f7bd80]请求其`NetCharacterStateData`和`NetNaminoriData`（0x55，4字节布尔值），游戏机每0.41秒发送一次`NetPosData`。位置使用房间的编码 (`--ug-join --room-walk-steps N`)。

`UgNetworkManager$$OnReceiveRequestData` [1.3.0主0x01f7c050]回答0x01、0x04的请求，
0x18、0x19 `NetDigData`、0x54、0x55 和 0x61：

|请求|字节|内容 |
|---|---|---|
| 0x18 `NetSecretBaseData` | 616 | 616玩家自己的`UgSecretBase`；当 `zoneID` 为 0 时什么也没有 |
| 0x54 `NetSecretBaseUpdate` | 616 | 616相同的 616 字节 |
| 0x61 `NetDigTableData` | 8 |八个挖掘化石 ID，`01 06 04 02 05 03 00 07` |

在游戏机的窗口传送任何内容之前，在序列 1 发送的请求没有得到答复。对任何其他 id 的请求不会产生任何结果（尝试了 0x29 和 0x42 ）。

0x61 是 `UgFieldManager.ugDigGroupList`，`Guid.NewGuid()` 的顺序为 0..7 (`UgStationID_to_DigFossilIDList$$Init` [0x02031830])；编组器 [0x002498c0] 复制元素 0 到 7，没有长度前缀，并抛出更少的元素。游戏机回答了
0x61 仅在其自己的表准备好后才请求（`UgNetworkManager.IsDigTableReady`，+0xA8，测试于
0x01f7c440）。

`UgNetworkManager$$OnSessionEvent` [0x01f77510]开启`SessionEventType`（字节表
0x03db8970）：

|活动 |目标|效果|
|---|---|---|
| 1 `JoinIn_Mine` | 0x01f77588 | 主机: 标志集 [0x01f7763c], `DeleteAllDigPoints`, `CreateDigPoints(MyStationIndex)`; not 主机: `NetRequestData{0x61}` to all [0x01f77738], flag left 0 |
| 2 `JoinIn_OtherPlayer` | 0x01f776bc | `SendOnJoinNewPlayer` |
| 3 `ChangeHost_Mine` | 0x01f776d4 | 0 时设置标志 [0x01f77740]，没有新表 |
| 4, 5 | 0x01f776dc |什么都没有|
| 6 `Leave_OtherPlayer` | 0x01f776ec | `OnLeaveOtherPlayer` |
| 7、8、9 | 0x01f77574 | `OnCrash` |

`UgNetworkManager$$OnReceiveDigTableData` [0x01f7dad0]采用标志为0时到达的第一个0x61，来自任何站，在其自己的`JoinIn_Mine`之前或之后：它仅测试标志[0x01f7db0c]和类别，将数组存储为`ugDigGroupList` [0x01f7db94] 取消选中，重建挖掘点 [0x01cfd6d0，0x01cfdab0] 并设置标志。所有三个存储都向 +0xA8 写入 1，因此后面的每个 0x61 都会被忽略。普通调度（`SessionManager$$OnReceivePacket` `0x1df8ac0`）从不参考`INetData.FromStationIndex`。

`CreateDigPoints` 读取元素 `[MyStationIndex]` [0x01cfdc7c] （8 次或更多抛出），找到
`UgDigFossilePosGroup` 与 `ID` (`List.Find` 0x01cfdcd8) 并读取其 `Grids`
`CreateDigPointModel` [0x01cfe470] 没有空测试。在 1.3.0 `ugdata` 捆绑包中，35 个区域（508 至 542）中的每一个都有 8 个组（ID 0 至 7），每组有 6 至 26 个单元。仅发送 0..7 的排列：较大的字节会导致游戏机出错。

每个 `UgFieldManager` 在 `StartSession` [0x01cfebb0] 中新建一个 `UgNetworkManager`（唯一的 `AddComponent<UgNetworkManager>`，0x01cfed54），并在 `OnDestroy` [0x01cff530] 中销毁它，因此每次都会重新接纳表。没有场景预先放置这两个管理器：1.3.0 RomFS 的 14052 个资源包及根目录文件包含 53861 个 MonoBehaviour，其中没有任何脚本为 `UnionRoomManager` 或 `UgNetworkManager`。两者仅存在于 `globalgamemanagers.assets` 的脚本表，且没有资源包引用该文件。

0x29 `NetDigGroupIdData` 共享 0x61 的结构体和方法。只有 `NetDataParser` 的构造函数 [0x0224a420] 引用它：没有任何内容发送它，并且 `UgNetworkManager$$OnReceiveData` [0x01f7a880] （22 个 id）没有它的分支。

`bin/bdsp_connect.py --inject-file PATH` 可靠地发送文件的每个新 `ID:HEX` 行。

<a id="ball-capsules"></a>
### 球形胶囊

游戏机通过“Déco Capsule”（状态字节 7）进行招募。它发送 `NetDataTransitionData{7, 0}`，进入状态 21 (`NOW_BALL_DECORATION`)，并将其 143 字节 `NetDataAttachSealNetData` 作为 116 字节 zlib 流发送（测量为 1.8 秒后）。没有得到答复，它显示“quelqu'un a miss fin à la communications”并返回房间；测量的等待时间为 45 秒，并且未找到计时器。使用客户端自己的 143 字节（`bin/bdsp_connect.py --answer-with 0x15:FILE`）进行应答，它应用它们（`BallDecoMatching$$ReceiveBallDecoData`，如下）并返回到房间，状态字节 0；据测量，返回时间不到五秒。从它自己的任务发送答案：从接收器内部，它等待的确认永远不会被读取。

在 1.3.0 映像中，一旦游戏机发送了自己的设计（其第一个带有密封件的插槽），`BallDecoMatching$$ReceiveBallDecoData` (`0x021ca5e0`) 就会运行。它写了 99 个没有密封件的胶囊槽中的第一个 (`0x021ca674`)，或者当所有胶囊槽都有密封件时什么也不写。 `BallDecoWork$$CopyTradeCapsuleData`（`0x01f23eb0`，在基础游戏中不存在）清除插槽，包含附加的宝可梦，将`Is3DEditMode`和`IsAppliedTemplate`存储为`byte == 1`，并行走`affixSealCount`印章：

    if SaveSealData[id].Count >= 1:  place it at (x, y, z) / 100, then SubSealCount(id, 1)
    else:                            drop it
 玩家胶囊上的密封件在起飞前缺货 (`CapsuleInfo$$RemoveAffixSeal`
`0x01e940d0` 称为 `BallDecoWork$$ReturnSealCount`）。没有库存，什么也没有写；该槽可存放已放置的密封件并压实。当至少放置了一个且没有掉落时，结果为 true，并选择结束消息 (`0x021c9f80`)：如果为 true，则为 `DLP_net_union_room_090`，否则为 `_114`（“Seuls les sceaux que vous possédez ont été colllés”）。计数超过 20 或密封 ID 超过 200 个或更多索引超过数组（`0x01f24254`、`0x0238b7b0`）并抛出异常。

位置是胶囊半径的百分之一，两种模式下表面的大小都是 100 等。 “有密封件”是`AffixSealCount != 0` (`0x01e93630`)。 3D 模式将每个印章绘制在其所在位置。 2D 模式（`Capsule2DViewController$$UpdateGridCells`、`0x01e90de0`）仅在网格单元处绘制密封
`BallDecoWork$$Convert2DPosition` (`0x01f24da0`)：半径 1，行和列在正面 (+z) 上相距 28 度，在背面相距 25 度，每个分量四舍五入到 0.01。

`Capsule2DViewController$$Initialize` (`0x01e909b0`) 以网格根的 `Capsule2DGridCell` 子代、中间的子代为中心 (+0x78) 和根 `GridLayoutGroup` 的单元格大小加上间距作为步长，并给出每个单元格 `GridPosition` = 其偏移量从中心越过台阶，呈圆形（`0x01e90c48`）； `Capsule2DGridCell$$Setup` (`0x01e905e0`) 将 `Convert2DPosition(GridPosition,
isFront)` 存储在 +0x30 处。 1.3.0 捆绑包 `/Data/StreamingAssets/AssetAssistant/UIs/ui/uiresidentwindow` 包含三个 `Capsule2DViewController`，每个根 `Grid` 一个 `GridLayoutGroup` {单元 72x72，间距 3x3，7 个固定列}超过 37 个单元和 12 个角垫片。正面和背面的网格是 7 x 7 的正方形减去 `(|x|, |y|)` 中的 `{(3, 2), (2, 3), (3, 3)}`：

    row  3   columns -1..1
    row  2   columns -2..2
    row  1   columns -3..3
    row  0   columns -3..3
    row -1   columns -3..3
    row -2   columns -2..2
    row -3   columns -1..1
 游戏机自己的 2D 胶囊在前部单元上有密封。脱离网格的 2D 设计填充了标记为“装饰”的槽位，并且不绘制任何内容；有货时，正面电池上的密封件会拉紧。

网格位置保持在零售规模。 `Initialize` 将世界空间偏移（`Transform$$get_position`、`0x01e90bd0`）除以局部步长，两个轴上均为 75（`fdiv` `0x01e90c10`）。直到根 `Seal` 或 `SealTemplate` 的每个祖先都有局部尺度 1；根 `Canvas` 是一个屏幕空间覆盖，其 `CanvasScaler` 的宽度从 1280 x 720 缩放，并且 `Window` 动画师仅绑定翻译。因子 `Screen.width / 1280` 为 1：+0x1c 处的 1.3.0 `/Data/rawsettings` u32 为 0，这将默认分辨率开关 `0x006062e8` 保持在 1280 x 720 对接和手持（1 遵循操作模式，2 遵循性能模式，3 两者），并且无托管代码调用
`SetResolution` 或 `Screen` 设置器。

`Screen.width` 是唯一原生屏幕对象（`0x04efe760`）+0x68 处的整数，通过虚表槽 0xa8（`0x002c2c24`）读取。它有三处写入：构造函数 `0x002c257c`（1280 x 720）、启动时唯一的 `SetMode(0)` `0x002c2858`（使用 `0x006062e8` 的值），以及 `SetResolution` `0x002c2888`。后者仅由运行模式和性能模式处理程序 `0x002c2a1c`、`0x002c2af0` 调用，且要求 rawsettings +0x1c 非零。此路径不读取 `globalgamemanagers` 中的玩家设置；托管层的 `Screen.SetResolution` 仅把参数存到 `[obj+8]`，不改变任何状态。
