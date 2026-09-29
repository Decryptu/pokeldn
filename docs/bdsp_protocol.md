---
title: The game protocol
parent: Brilliant Diamond and Shining Pearl
nav_order: 2
---

# BDSP's own protocol, and controlling a character

Inside the Pia payloads BDSP runs a typed protocol. `Dpr.NetworkUtils.NetDataParser` in
`TeamLumi/opendpr`, a decompiled C# recreation of the game, lists every message: an `ANetData<T>`
with a one-byte `DataID` around a plain struct `T`.

## Framing

    0x0  1  data id
    0x1  2  payload length, big-endian
    0x3  .  the struct, little-endian, packed

`JoinData` (`byte, byte, byte, short, Vector3`) is 17 bytes on the wire, 20 under C#'s default
alignment.

`NetDataParser` registers 65 messages; `pokeldn/bdsp/netdata.py` holds all of them, generated from an
`opendpr` checkout by `scripts/gen_bdsp_netdata.py`. The source decides 53 layouts. The other twelve
carry a C# string, array or list (`netdata.OPAQUE`) and the binary decides them.

A payload is the marshalled struct (`ANetData<T>.ConvertStructToBytes` [main.bin 0x27bb0e0]:
`Marshal.SizeOf`, `AllocHGlobal`, `StructureToPtr`), strings and arrays as fixed-size fields. A
struct's size is its `native_size` in `Il2CppTypeDefinitionSizes`; a string's length is in
`global-metadata.dat`'s `fieldMarshaledSizes`; an array's count is what the other fields leave. The
exact bytes are written by `marshalToNative` in `CodeRegistration.interopData` [1.3.0 main 0x4acd0c8,
0x255 entries of 56 bytes]. The four captured opaque payloads match byte for byte (`room.NATIVE_SIZES`,
`room.MEASURED`).

| id | payload | bytes | layout |
|---|---|---|---|
| 0x02 | `PosListData` | 72 | 12 x `PosData` (ushort posX, ushort posZ, short rotY) |
| 0x13 | `TradePokeData` | 328 | one encrypted PB8 at stored size |
| 0x14 | `NetRecodeData` | 694 | `RECORD` 120, `RANDOM_SEED` 132, `TvRecodeData` 204, 4 x `TV_STR_DATA` 36, `RECORD_HEAD` 48, ten ints, six bytes |
| 0x15 | `BallDecoData` | 143 | affixSealCount, Is3DEditMode, IsAppliedTemplate, then `AttachSealData` 140 (20 x `SealParam{short x, y, z; byte id}`) |
| 0x18, 0x54 | `UgSecretBase` | 616 | short zoneID, posX, posY; byte direction, expansionStatus; int goodCount; 30 x `UgStoneStatue` 20; bool isEnable (4) |
| 0x22 | `StanbyListData` | 20 | 5 x `StandbyData` (isAddPlayer, hostIndex, myIndex, langId) |
| 0x24 | `TradeTranerData` | 32 | 13 UTF-16 chars, uint tranerId, byte cassetVersion, byte langId |
| 0x29, 0x61 | `UgStationID_to_DigFossilIDList` | 8 | `byte DigFossilIDs[8]`, a permutation of 0..7 |
| 0x38 | `BattleMatchingPokeData` | 481 | a 328-byte PB8, 20 x `SealParam` 7, uint attachPokemonId, uint attachPersonalRnd, byte index, num, is3DEditMode, isAppliedTemplate, affixSealCount |
| 0x42 | `NetPlayerName` | 28 | 13 UTF-16 chars, byte genderid, byte languageId |

`BattleMatchingPokeData`'s two arrays split 468 as 328 + 20 seals, the only split matching
`TradePokeData` and `AttachSealData`.

`SendStandbyPlayerData` [1.3.0 main 0x01e52fa0] fills the five slots of 0x22 from
`UnionStateController.unionMatchWaitDataList` (`isAddPlayer = 1`, `hostIndex` 0); an empty list is
twenty zero bytes. A station adds itself with `NetDataStandbyWaitData` (0x59, the same four bytes):
after `59 0004 01 00 01 03` (station 1, French), accepted by `ReciveMatchWaitData` [0x01e539b0], the
next 0x22 is `22 0014 01 00 01 03` and sixteen zeros. `isAddPlayer = 0` removes it. The screen does not
change.

The marshaller does not clear its buffer: a fixed field carries heap residue past its value
([the trading page](bdsp_trade.md)). The ids are nibble-grouped; no low nibble reaches 0xA.

## What has been on the air

A console left alone in the room sends four of the 65 (the receiver drops looped-back broadcasts):

| id | class | reliable | unreliable | size | runs |
|---|---|---|---|---|---|
| 0x01 | `NetJoinData` | 2070 | 0 | 17 | 19 |
| 0x02 | `NetPosData` | 0 | 60 | 72 | 5 |
| 0x12 | `NetRequestData` | 4333 | 55 | 1 | 19 |
| 0x23 | `NetDataIsMatchWaitData` | 1734 | 0 | 1 | 13 |

On request it also sends 0x09 (one byte, 0 with no battle set up) and 0x22; on an activity, 0x14 and
0x15. The trade messages are on [the trading page](bdsp_trade.md).

1505 of the 0x23 copies, in two captures, sit behind a presence byte 0x00 and are read only by a
walk that takes 0x00 as a message ([Message framing](pia.md#message-framing)). Every payload (over
eight thousand) is a well-formed message whose length accounts exactly for its bytes.

## The messages the console repeats

`NetJoinData` is a player's arrival, the whole of `JoinData`:

| offset | size | field |
|---|---|---|
| 0x00 | 1 | `avatarId`, 8 in every capture |
| 0x01 | 1 | `colorId`, 0 |
| 0x02 | 1 | `cassetVersion`, 0x31 |
| 0x03 | 2 | `InitRotY`, the facing in degrees (multiples of 45 measured), little-endian, unaligned |
| 0x05 | 12 | `InitPos`, three little-endian floats: x, y, z |

`NetRequestData` is one byte, the id of the message wanted. `NetDataIsMatchWaitData`
`{isMatchWait = 0}` is the console answering its own request. The console asks for two things:

| asked for | times | in which runs |
|---|---|---|
| `NetDataIsMatchWaitData` (0x23) | 4333 | all nineteen |
| `NetCharacterStateData` (0x04) | 55 | four runs |

The four are the runs where an avatar appeared (none across 265 sends that drew nothing). The game
asks each character's station for its state when it creates the character, so a 0x04 request signals
that a character exists; `bin/bdsp_connect.py` prints it as the verdict. The 0x23 request stops at t = 9.4 s once the
client acknowledges the reliable window; unacknowledged, it came 487 times in 75 seconds.

`UnionRoomManager$$SetNetData` [1.3.0 main 0x01e50700] answers a `NetRequestData` for six ids and
ignores every other:

| requested | the console sends | by |
|---|---|---|
| 0x01 `NetJoinData` | its join record | `UnionRoomManager$$SendJoinData` |
| 0x04 `NetCharacterStateData` | its character state | `UnionRoomManager$$SendOpcStateData` |
| 0x09 `NetDataBattleTypeData` | its battle rule | `UnionRoomManager$$SendBattleRuleData` |
| 0x13 `NetTradePokeData` | the Pokemon it is offering | `UnionRoomManager$$SendPokeData` |
| 0x22 `NetDataStandbyWaitListData` | its standby list | `UnionRoomManager$$SendStandbyPlayerData` |
| 0x23 `NetDataIsMatchWaitData` | whether it is waiting to be matched | `UnionRoomManager$$SendIsMatchWait` |

From a station with a character in the room, five are answered on the reliable stream 30-130 ms
after the request; 0x13 is not when no Pokemon is selected (`SendPokeData` returns). The base game's
handler [base main 0x01fd4600] answers the same six, 0x22 then named `NetDataTradeStandbyData`. A
request arrives on the stream its answer uses: all 4333 for 0x23 on the reliable one, all 55 for 0x04
on the unreliable one.

### Compression

The reliable header's flag 0x10 marks a zlib stream. The sender decides it by size:
`ReliableSlidingWindow`'s push [1.3.0 main `0x15a10d0`] tests the window's compression switch
(+0x7ac, `0x15a1364`), and when it is on `0x159a500` deflates the whole game message, its 3-byte
header included:

    0x1685384   deflateInit2: level 5, window bits 12, memLevel 5, strategy 0, 4000-byte output
    0x16854e0   deflate(Z_SYNC_FLUSH)
    0x1685608   deflate(Z_FINISH)
    0x159a5b0   compressed size >= raw size  ->  error 0x2c7d, the message goes raw
    0x15a1398   otherwise: header |= 0x10, send the compressed bytes

All 55 flagged console messages are byte-identical to Python's
`zlib.compressobj(5, zlib.DEFLATED, 12, 5)` with a sync flush then a finish, and none of 10955
unflagged ones shrinks under it. A join and a one-record 0x22 list go raw; the all-zero 0x22 list
(read raw it looks like a `NetBonusStart`), a record (0x14) and a ball capsule (0x15) shrink. A
receiver never has to compress; `bin/bdsp_connect.py` inflates on the flag.

### Senders of the other opaque messages

From the callers of each `ANetData<T>.SendReliableData` in 1.3.0:

| id | class | sent by |
|---|---|---|
| 0x14 | `NetDataRecodeData` | `RecodeMatching$$SendRecodeData`, `UnionStateController$$SendRecodeData` |
| 0x15 | `NetDataAttachSealNetData` | `BallDecoMatching$$SendBallDecoData` |
| 0x18 | `NetSecretBaseData` | `UgNetworkManager$$SendMySecretBaseData`; on request (`OnReceiveRequestData`) |
| 0x61 | `NetDigTableData` | on request (`OnReceiveRequestData`) |
| 0x38 | `NetDataBattleMatchingSelectPokemon` | `BattleMatchingManager$$SendSelectPokemonData` |
| 0x42 | `NetPlayerNameData` | `UgNetworkManager$$SendOnJoinNewPlayer`, `SendPlayerNameData` |
| 0x54 | `NetSecretBaseUpdate` | no reliable sender; `netdata.py` names it |

### The unreliable stream

It carries three messages:

| bytes | times | message |
|---|---|---|
| `04 0002 00 00` | 853 | `NetCharacterStateData{state: NONE, isRecruiment: 0}`, every two seconds |
| `12 0001 04` | 55 | `NetRequestData`: "send me your `NetCharacterStateData`" |
| `02 0048 <72 B>` | 60 | `NetPosData`, twelve points, while the console's avatar walks |

`room.build_state()` builds the first and `room.build_match_wait(False)` the console's own 0x23 answer.

The console retransmits a reliable message five times a second until an ack covers it; an ack two
beyond its last sequence is ignored. `bin/bdsp_connect.py` acks at the last sequence plus one once the
console has acknowledged the client's own data.

## Sending messages the game acts on

The reliable sequence id is shared with the console's own sends, and a message below the id its
acknowledgement names is dropped in silence: with the ack at 13, of twenty joins numbered 1 to 20
exactly the eight from 13 up became avatars. Read the id immediately before each send.

Sent at the acknowledged sequence, nearly every join is acted on: of fifteen joins 0.4 s apart the
console requested 0x04 for 12 to 15 (seven runs), the first 0.10 to 0.57 s after the first join.
`--room-pattern fixed` stops at the first request, giving each join `--join-wait` seconds (default
1.0).

`UnionOpcManager` calls `CreateCharacter(joinData)` on each join: forty joins are forty arrivals. A
character created without a session behind it follows the player across maps until the game
restarts; one that has been moved is cleaned up when its station leaves the mesh.

## The character record

`OpcManager.CharaData` is
`{int stationIndex, string assetName, int colorId, int avatarId, int sexId, int cassetVersion}`, keyed
by station (`RemoveCharacter(int stationIndex)`).

### The model

`OpcManager.CreateCharaData(ANetData<JoinData>)` builds the record from the join, and `avatarId`
picks who appears:

    NetJoinData.avatarId  ->  CreateCharaData  ->  CharaData.avatarId
                          ->  UnionCharacterTable.SheetSheet1{ID, AssetName}
                          ->  OpLoadCharacter("persons/field/" + assetName)

`GetSexId` and `GetNpcColorId` read the same value: 8 is a girl, 0 a boy in a blue cap
(`--join-avatar N`).

`NetDataTranerCardData` (0x05, 75 bytes: `fashionId`, `bodyType`, `genderid`, ...) feeds
`UnionOpcManager.CreateTranerCard()`; sending one changes nothing on screen.

### The state byte

`StateData` is `{byte state, byte isRecruiment}`, `state` an `OpcState.OnlineState`:

| value | name | value | name |
|---|---|---|---|
| 0 | `NONE` | 5 | `RECRUITMENT_RECORD` |
| 1 | `DIG_FOSILL` | 6 | `RECRUITMENT_GREETINGS` |
| 2 | `SECRETBASE_ACTION` | 7 | `RECRUITMENT_BALL_DECORATION` |
| 3 | `RECRUITMENT_BATTLE` | 8 | `COMMUNICATE` |
| 4 | `RECRUITMENT_TRADE` | | |

17 to 21 are the `NOW_*` states, one per activity ([the transitionType table](#talkstate-and-the-value-that-crashes-the-game)).
`OpcController.ShowEmoticon(OnlineState)` and `GetEmoticonType(state)` read it; a `RECRUITMENT_*`
value raises the speech bubble. Answering the console's request with `StateData{RECRUITMENT_TRADE, 1}`
puts a trade bubble on a retail screen; `StateData{NONE, 0}` changes nothing.

A received 0x04 goes `UnionRoomManager$$OnReceiveData` [1.3.0 main 0x01e506c0] ->
`OpcManager$$SetNetData` [0x02279450] (dropped when the station has no character) ->
`UnionOpcController$$SetNetData` [0x01e48c50], its only consumer:

    if state != GetOpcOnlineState():      SetOpcOnlineState(state)                 0x02277be0
                                          isRecruiment == 1 ? SetEmoticonHost()    0x022779b0
                                                            : SetEmoticonNormal()  0x02277a50
    if state != 0:                        AnimationPlayer.Play(animation 0)

The Underground twin is `UgOpcController$$SetNetData` [0x01f7f820].

`OpcState` is `{OnlineState _curretOnlineState +0x18; Action<OnlineState> _OnChangeState +0x20}`,
added by `OnlinePlayerCharacter$$Start` [0x02276ff0] with the Action bound to `ShowEmoticon`
[0x02277094]; the state starts at 0. `SetOpcOnlineState` [0x02277c80] is its only live store
(`OpcState$$OnChangeOnlineState` [0x02277d10] has no caller). Of the setter's callers (virtual, class
offset 0x190), three touch a remote character: `UnionOpcController$$SetNetData` [0x01e48d7c] with the
received state, and `OpcManager$$RemoveCharacter` [0x02279ee4] and `UgOpcManager$$RemoveAllCharacter`
[0x01f80cac] with 0. So a remote character's state changes only on a 0x04 from its own station. The
rest set the console's own: `UnionSystemController$$ChangeOpcState` [0x01c2d3f8] (its argument, then a
0x04 broadcast [0x01c2d4d0]), `RusultGreetJoinYesNoWindow` [0x01c2e8ac] 6,
`<CreateContextBattleTypeMenu>b__0` [0x01f8b790] 3, `UnionTradeManager$$InitPlayerState` [0x01c33a58],
`UnionStateController$$InitPlayerState` [0x01e4e83c] and `SwitchCancelEnd` [0x01e4fd70] 0,
`UnionStateTransitionController$$StartFadeOut` [0x01e5a00c] its model's +0x2c,
`UgNetworkManager$$OnReceiveJoinDigPermission` [0x01f7ca94] and `SendOnPlayDigFossil` [0x01f79f78] 14,
and `UgNetworkManager$$SetMyEmoticon` [0x01f79148].

Until `Start` has run, the getter returns 0 [0x02277dcc] and the setter drops the value
[0x02277c50]. The character's 0x04 request goes out right after `SetActive(true)` in the
`CreateCharacter` load callback [0x01e49854], so an answer that lands before `Start` is lost; repeat
the state every two seconds, as the console does.

`OnlinePlayerCharacter$$IsCanTalkState` [0x02277af0]: the player can talk to states 1, 3 to 8 and 17
to 21, never to 0, 2 or 9 to 16.

### Walking

The console's own `NetPosData` comes every 0.410 s spanning 0.935 units (`room.POS_PERIOD`,
`room.POS_STRIDE`; `--room-walk-period`, `--room-walk-stride`); 0.1 units every 0.35 s stutters.

`PosData` is `{ushort posX, ushort posZ, short rotY}`, `pos = (-posX * 0.05, posZ * 0.05)`: a
twentieth of a unit, x negated. A remote character collides with walls (the player does not collide
with it) and keeps `rot_y` literally; sixty messages at the console's speed cross the room and leave
through the far wall, `--room-walk-steps 8` stays inside.

## Being talked to

An emote locks a player in place until someone interacts. The console broadcasts it:

    NetCharacterStateData{state: 4, isRecruiment: 1}     the trade emote, up
    NetCharacterStateData{state: 0, isRecruiment: 0}     and down again

Gate on `isRecruiment`: state 18 is a console already inside a trade, and approaching it is refused.

The approach is `NetDataTalkReserveData` (0x63), `63 00 01 00`, as the console sends it
(`bin/bdsp_connect.py --initiate-talk`; answered in 40 ms). The console's player approaching the
client's character:

    t=37.47  cli ->  64 0003 00 01 04   NetDataTalkReserveResultData{IsCanTalk, IsRecruitment, emoticonStateType}
    t=37.67  con ->  06 0005 00 01000000  NetDataTalkData{talkOpcSexId: 0, talkState: GREETING}
    t=80.68  con ->  10 0002 01 04      NetDataTalkCancelEndData{IsRecruitment: 1, emoticonStateType: 4}

The talk blocks on the 0x64: unanswered, the player's character freezes until a reboot.

| `IsCanTalk` | then sent | the screen |
|---|---|---|
| 0 | nothing | the greeting runs and parks on "one second!" |
| 1 | nothing, `NetDataSelectData{0}` or `{1}` | "sorry, I have other plans", the chat closes |

B does not reliably leave a parked greeting; dropping the station does, a reboot otherwise.

### The console approaching

`UnionRoomManager$$MyUpdate` [1.3.0 main 0x01e49fb0] handles the A press [0x01e4a644] only when the
player's own state is 0, `UnionWork.isTalking` (static +0x85) is 0, no menu or message window is open
and the player is outside every `EnterCollision` circle. It walks the characters within 10.0 units
and the player's `talkDistance` (+0x38) whose state passes `IsCanTalkState`:

| the character's state | what A does |
|---|---|
| 0, 2, 9 to 16 | nothing |
| 8, 17 to 21 | after the walk, `UnionRoomManager$$StartTalk(opc, 0, 0, 0)` [0x01e4c2d0] on the nearest; no message |
| 4 | `UnionSystemController$$CheckErrorMessageTrade` [0x01c2e8d0]; with no error, as the last row |
| 7 | `UnionSystemController$$CheckBallDeco` [0x01c2ec20]; when it passes, as the last row |
| 1, 3, 5, 6 | `NetDataTalkReserveData` (0x63) to the character's station [0x01e4ac94], the state stored in `nowTalkReserveState` (+0x188), `isTalking` set, `UnionStateController$$CreateSelectStateModel(state, 1)` [0x01e4b620] |

For states 1 and 3 to 7 the walk acts at once on the first qualifying character nearer than the
earlier ones.

The console answering a 0x63, in `UnionRoomManager$$SetNetData` [0x01e50c3c]:

    r.IsCanTalk = UnionWork.isTalking
    if stateController._currentModel (+0x88) is null:
        r.IsCanTalk = 1; SendOpcStateData(requester)
    r.IsRecruitment = 1
    r.emoticonStateType = the console player's own state
    send r (0x64) to the requester                           0x01e5110c
    if isTalking was 0 and r.IsCanTalk is 0: isTalking = 1

The console reading a 0x64 after its own 0x63 [0x01e50dec]:

    canTalk = IsCanTalk == 0 and not isCancelStock (+0x183, cleared here)
    if emoticonStateType != nowTalkReserveState:
        send NetDataTalkCancelEndData{0, 0}                  0x01e50f24
    else:
        nowTalkReserveState = 0                              0x01e50ea0
        canTalk ? StartTalk(opc, IsRecruitment == 0, 1, 0)
                : the refusal path 0x01e512f0 (the character's state against 3 to 7)

A character advertising `{4, 1}` draws `63 0001 00` on A, and `64 0003 00 01 04` opens the talk. Any
other `emoticonStateType` draws `NetDataTalkCancelEndData{0, 0}`, and so does a second 0x64 for the
same 0x63, the first having cleared `nowTalkReserveState` [0x01e50e94]. Answer each 0x63 once, not
each retransmitted copy.

With the console as the talker, the client's character is the recruiter. A recruiter's yes to the
trade offer (`UnionTradeContextMenu.<>c__DisplayClass10_0.<ShowTradeYesNoWindow>b__0` [0x01c32f70];
no is `TradeRecruitmentStateModel$$Cancel` 0x01c24150) opens message 8 and tail-calls
`UnionContextMenu$$SendTransitionData(station, 0)` [0x01f86480], which sends
`NetDataTransitionData{menu+0x50, 0}` reliably; `SetTransitionType` [0x01c32ef0] sets +0x50 to 18. The
yes is `07 0002 12 00`, the message a recruiting console sends when the client approaches it
([the trading page](bdsp_trade.md#the-message-sequence)). A client that answered the 0x63 and sent
`07 0002 12 00` drew a retail console's `NetDataTradeTranerData` (0x24), the trade box and a completed
trade, with no yes from the console.

On the talking console, A on a state-4 character builds a `TradeJoinStateModel` at
`UnionStateController+0x50` (`CreateSelectStateModel(4, 1)`, store 0x01e4b814, the only one, never
cleared). The 0x64 runs `SwitchTalkStateMine` [0x01e4c41c]: 18 into
`UnionSystemController.onlinePlayerSelectState` (+0x28) and `SetTargetStationIndex(station,
cassetVersion, 1)` [0x01e54ae8]. A 0x07 goes, with no state test [0x01e52610], to
`SwitchTransitionMessage` [0x01e53bf0], which reads the type's model (byte table 0x03db869b) with no
null test; for a trade `TradeJoinStateModel$$OpenSwitchFadeMsg` [0x01c22f50] opens message 9 or 10 by
the sender's sex, spoken as `OPPONENT` (`SpeakerID` 1), closing into `StartFadeOut`. After the fade
`SwitchTransition` [0x01e5ba70] sends 18 to `TransitionTradePoke` [0x01e5c1c0], which takes and clears
the target station, checks `IsGamerActive` and sends the console's 0x24 [`SendTranerData`
0x01e5c2b0]: the start of the trade in the joiner direction. No 0x07 has been sent to a talker. A 0x07
reaching a console that has not pressed A on a trade recruiter since its `UnionStateController` was
built reads through null (0x01e53c4c); the other transition types have the same shape on their own
models.

### The name in the greeting

The greeting, its speaker label and the battle ladder's "is choosing" line name a character by its
station's Pia player name: `UnionBaseMsgWindow$$SetTargetDataMessage` [1.3.0 main 0x01f86810] and
`GetSpeakerName` [0x01f87050] read `NetworkManager$$GetGamerData(station)` [0x02250e50]
(`IlcaNetGamer.gamerName` +0x30, `nameStringLanguage` +0x38). `NetGamerNameGet` [0x0273a9a0], on the
Pia join event, decodes `length - 1` bytes of an 80-byte buffer from `INLpiaSessionGetPlayerInfo`
[0x01e15cd0] as UTF-8 (empty under length 2) and copies the language byte raw.

`Utils$$CheckNGTrainerName` [0x01cbdc30] replaces the name with
`Utils$$GetReplacedNGName(UnionWork.nowTargetCassetVersion)` [0x01cbde20] when it is empty, when
`CheckNgWords` [0x01c99220] flags it, or when it has more UTF-16 units than
`SoftwareKeyboard$$LanguageMaxLength(6, lang)` [0x01c995b0]:

| `lang` | limit |
|---|---|
| 1, 8, 9, 10 | 6 |
| any other positive value | 12 |
| 0 or below | the UI's current language decides |

The language is PlayerInfo byte 0x7A. The Mesh Station Protocol's parser [0x0154f044..0x0154f5e0]
reads one 195-byte PlayerInfo per iteration (`add w23, w23, #0xc3` 0x0154f588); the offsets are fixed
whatever the encodings:

| offset | field | read |
|---|---|---|
| 0x00 | name encoding | 2: 20 UTF-16 units (0x0154f078..0x0154f15c); anything else: 80 bytes |
| 0x01..0x50 | name | into the station record at +0x120 + index*0x80 |
| 0x51 | second string's encoding | 0x0154f220 |
| 0x52..0x79 | second string, 40 bytes | encoding 2: 10 UTF-16 units, to +0x320 + index*0x58 |
| 0x7A | language | `strb w8, [x20+x25, #0x480]` 0x0154f5a0 |
| 0x7B..0xBA | 64 bytes | 0x0154f5b8 |
| 0xBB..0xC2 | u64 | to +0x490 + index*8 |

`INLpiaSessionGetPlayerInfo` reaches `0x01391a90`, which defaults the byte to 0xFF [0x01391b44] and
copies the station record's +0x480 unchanged into `NetGamerNameGet`'s `nameStringLanguage`
[0x01391bb0]. The byte is a `MsgLangId`:

    JPN 1, USA 2, FRA 3, ITA 4, DEU 5, ESP 7, KOR 8, SCH 9, TCH 10

A console sends its own `MessageManager$$get_UserLanguageID` and its `CheckNGTrainerName`-checked name
(`SessionConnector$$ResetParam` [0x0202f050]), through `IlcaNetBase$$PlatformInitialize2`
[0x01e13ce0] and `PiaPlugin$$RegisterStartupSessionSetting` [0x0227d5a0], and the station protocol's
PlayerInfo writer puts +0x480 at byte 0x7A [0x01550e98]. A French console's connection response
(station protocol kind 2) carries encoding 1, its name, byte 0x79 0 and byte 0x7A 3.

`station_protocol.player_info` writes the UTF-8 name at offset 1 and the language at 122.
`bin/bdsp_connect.py --name` (default `PkCamp`) sends `--language`, default 1 (`JPN`: a 6-unit limit,
Japanese font); `pokeldn/bdsp/host.py` sends 3, under which an 11-character name shows whole.

The substitute depends on the talked-to character's `CharaData.cassetVersion`, byte 2 of its
`NetJoinData`, which both callers of the greeting (`SwitchSpokenStateMine` 0x01e53b58,
`MessageEndSpokenData` 0x01e57ab8) store in `UnionWork.nowTargetCassetVersion` (static +0x8C).
`GetReplacedNGName` takes label 247 of `dp_characters` for 0x31 and label 206 otherwise (0x01cbdecc)
and appends a full stop. The texts, from the 1.3.0 RomFS `Message/<language>` bundles:

| bundle | 0x31 (Shining Pearl), `DP_CHARACTERS_247` | anything else, `DP_CHARACTERS_206` |
|---|---|---|
| english | `Pearl.` | `Diamond.` |
| french | `Perlo.` | `Diamant.` |
| german | `Perl.` | `Diamant.` |
| italian | `Perl.` | `Diaman.` |
| spanish | `Perla.` | `Diamant.` |
| jpn, jpn_kanji | `パール.` | `ダイヤ.` |
| korean | `펄.` | `다이아몬드.` |
| simp_chinese | `帕尔.` | `戴亚.` |
| trad_chinese | `帕爾.` | `戴亞.` |

### talkState, and the value that crashes the game

`TalkState` is `{CHECK = 0, GREETING = 1, NONE = 2}`; the parked console waits in `GREETING`.
`UnionStateController$$SwitchSpokenStateMine` sends anything but CHECK to
`StartOpenGreetingMsgWindow` (`b 0x1fd85e0` at 0x1fd5e80); CHECK loads `systemController->msgWindow`
(0x1fd5e84) and dereferences it with no null guard (0x1fd5ec0). A player standing with an emote up has
no message window, so CHECK crashes the game; `pokeldn/bdsp/room.py` refuses to send it. Never send a
state value read from a sender before reading the receiver's handler.

`NetDataTransitionData{transitionType, isRecruitment}` (0x07) advances a parked greeting into an
activity. The game sends it as a tail call, so a BL-only caller scan reports it as never sent
([finding callers](switch_re.md#finding-callers)). `transitionType` is an `OnlineState`;
`UnionStateTransitionController$$SwitchTransition` [1.3.0 main 0x01e5ba70] dispatches on it through a
19-entry table, and `SwitchTransitionMessage` reads the model at `UnionStateController` + the offset
below:

| transitionType | activity | entered through | model |
|---|---|---|---|
| 3, 17 | battle | `TransitionBattle` | +0x38 or +0x40 by `isRecruitment` (`tbz w4`) |
| 4, 18 | trade | `TransitionTradePoke` | +0x50, `tradeJoinStateModel` |
| 5, 19 | record mixing | `RecodeMatching$$Open` | +0x60 |
| 6, 20 | trainer card | `TransitionShowTrainerCard` | +0x70 |
| 7, 21 | ball capsules | `BallDecoMatching$$Open` | +0x80 |
| 8 to 16 | none | | none; returns |

`RecodeMatching$$Open` and `BallDecoMatching$$Open` send the console's own record at once (0x14,
0x15) and wait; only the partner's (`StartRecodeTradeFlow`, `StartBallDecoTradeFlow`) writes the
save.

### Record mixing

The console recruits with "Échanger des données" in the Y menu (state byte 5). When the client walks
up and the player says yes, it sends `NetDataTransitionData{5, 0}`, then 1.5 s later its 694-byte
`NetDataRecodeData` (a 205-byte zlib stream), and waits at state 19 (`NOW_RECORD`); after 44 s without
an answer it shows "un des participants n'est plus disponible" and returns to the room. `room.parse`
returns the record's head as `recode`:

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

Unwritten fields hold 64-bit heap pointers. `RECORD_HEAD.sex` read 0 and `RANDOM_SEED.sex` 1 in the
same record. `RECORD`, `RANDOM_SEED` and `RECORD_HEAD` (namespace `DPData`) marshal at pack 4, the
`TvRecode*` structs at pack 8; no padding results at these field sizes.

### The battle ladder

A battle ("Combattre", state byte 3 while recruiting) runs a ladder; the recruiting console waits on
the joiner (here the client) at every rung:

| the joiner sends | the console does |
|---|---|
| `NetDataTalkData{GREETING}` | shows "Un combat ? OK ! Donne-moi juste une minute !" and waits |
| `NetDataSelectData{0}` (0x08) | shows "PkCamp est en train de choisir quoi faire..." and waits |
| `NetDataBattleTypeData{0}` (0x09, `BattleModeID.Single`) | asks its player "voulez-vous faire un combat selon ces règles ?"; on yes sends `NetDataTransitionData{17, 0}`, state byte 17, and opens the solo lobby at "connexion en cours" |
| `NetDataBattleMatchingJoin` (0x30) `{uint id, byte stationIndex, index, language, colorId, avatarId, sexId, cassetVersion}` | answers with its own join (`id` its trainer id, station 0, index 0) and relays the joiner's back; the joiner's character appears in the lobby's second slot |
| `NetDataBattleMatchingReady` (0x32, empty) | `BattleMatchingManager$$ReceiveReadyData`: when every member is ready, `NetDataBattleMatchingState{0, 6}` (0x33), `MatchingState.SelectBattleTeam` (4 and 5 skipped for a solo battle), and its player gets the team-selection button |
| nothing | on the player's team choice, six `NetDataBattleMatchingSelectPokemon` (0x38, 481 bytes), then "en attente d'autres personnes" |

Each 0x38 holds an encrypted PB8 whose checksum verifies (the picked team, in order), twenty
`SealParam` slots of identical heap residue with `affixSealCount` 0, `attachPokemonId` and
`attachPersonalRnd` 0, `index` 0 to 5 and `num` 6. The joiner's `id` in 0x30 is not checked
(0x0badc0de was accepted). `BattleMatchingManager.MatchingState`: None 0, Initialize 1, Load 2,
RecruitmentMember 3, SelectTeamMember 4, SelectRule 5, SelectBattleTeam 6, SelectPokemon 7, GoBattle
8, Result 9, Resume 10, Closing 11, LeavedOtherMembers 12.

`NetDataSelectData` (0x08) is `{byte index}`. Its one receiver [`UnionRoomManager$$SetNetData`,
0x01e52a30] reads the sender's station and never the index:

    m = stateController.battleRecruitmentModel                  UnionStateController +0x38
    m.ChangeBattleRecruitmentState(BATTLE_RULE_SELECT_WAIT 4)   0x01d2aab0
    m.currentCancelModel = {SelectCancel 0, station}
    m.CloseWindow()
    if m.unionMsgBattleWindow != null:
        SetTargetDataMessage(window, station, 1, 1); OpenMsgWindow(window, 3, 2)   0x01f86fa0

A 0x08 drives the battle recruitment model whatever conversation is open. Both senders write 0
(`UnionBattleContextMenu$$SendRuleSelectState` [0x01f87c60], a tail call, and
`<ShowBattleJoinYesNoWindow>b__0` [0x01f8800c]).

The receiver never tests the model for null: it loads +0x38 [0x01e52a78] and case 4 writes
through it in `NetStateModel$$SetState` [0x023e2604]. The only store to +0x38 is
`CreateSelectStateModel` [0x01e4bb08], building a `BattleRecruitmentStateModel` for state 3 or 17
when the player recruits a battle (`stateModelType` 0; the A press passes 1 and builds a
`BattleJoinStateModel`). `UnionStateController` is built once per `UnionRoomManager`
(`UnionRoomManager$$SetUp`, `.ctor` 0x01e4d01c), and a link battle keeps both
(`EvDataManager$$UpdateStart` -> `UnionRoomManager$$ReturnBattle` [0x01b02a78], no constructor). A
0x08 reaching a console whose player has not recruited a battle in that visit writes through null.

No 0x08 has reached `SetNetData` on a console: the 22 sent after a talk went out under a sequence id
one of the client's own 0x64 answers already held, and the reliable window keeps the first message
for an id ([the Pia page](pia.md#what-the-receiver-discards-in-silence)).

Never send 0x08 unless the console's own 0x04 says state 3 with `isRecruiment` 1.

### The Grand Underground

The Underground advertises the same `local_communication_id` under scene id 12608; the same session
line associates, with no join record (`--room-walk 0`). On a station's arrival `UgNetworkManager`
sends:

| id | class | bytes | content |
|---|---|---|---|
| 0x17 | `NetZoneData` | 16 | `Vector3 pos`, `int zoneID` (519 measured) |
| 0x42 | `NetPlayerNameData` | 28 | 13 UTF-16 chars, byte genderid, byte languageId (3, French) |
| 0x50 | `NetKousekiCount` | 4 | `int Value` |
| 0x41 | `NetSecretBaseInfo` | 16 | instead of 0x17 inside a secret base (zone 633): `Vector3 pos`, `int zoneID`, the entrance on the floor above (519) |

A `NetUgJoinData` (0x16, 18 bytes: `byte avatarId, colorId; short zoneID, InitRotY; Vector3 InitPos`)
naming the player's zone puts a character next to the player: `OnReceiveJoinData` [1.3.0 main
0x01f7bd80] requests its `NetCharacterStateData` and `NetNaminoriData` (0x55, a 4-byte bool), and the
console sends it `NetPosData` every 0.41 s. Positions use the room's encoding
(`--ug-join --room-walk-steps N`).

`UgNetworkManager$$OnReceiveRequestData` [1.3.0 main 0x01f7c050] answers requests for 0x01, 0x04,
0x18, 0x19 `NetDigData`, 0x54, 0x55 and 0x61:

| requested | bytes | content |
|---|---|---|
| 0x18 `NetSecretBaseData` | 616 | the player's own `UgSecretBase`; nothing when its `zoneID` is 0 |
| 0x54 `NetSecretBaseUpdate` | 616 | the same 616 bytes |
| 0x61 `NetDigTableData` | 8 | eight dig-fossil ids, `01 06 04 02 05 03 00 07` |

A request at sequence 1, before the console's window has
carried anything, goes unanswered.
A request for 0x29 or 0x42 draws nothing.

0x61 is `UgFieldManager.ugDigGroupList`, a `Guid.NewGuid()` ordering of 0..7
(`UgStationID_to_DigFossilIDList$$Init` [0x02031830]); the marshaller [0x002498c0] copies elements 0
to 7, no length prefix, and throws on fewer. The console answers a
0x61 request only once its own table is ready (`UgNetworkManager.IsDigTableReady`, +0xA8, tested at
0x01f7c440).

`UgNetworkManager$$OnSessionEvent` [0x01f77510] switches on `SessionEventType` (byte table
0x03db8970):

| event | target | effect |
|---|---|---|
| 1 `JoinIn_Mine` | 0x01f77588 | host: flag set [0x01f7763c], `DeleteAllDigPoints`, `CreateDigPoints(MyStationIndex)`; not host: `NetRequestData{0x61}` to all [0x01f77738], flag left 0 |
| 2 `JoinIn_OtherPlayer` | 0x01f776bc | `SendOnJoinNewPlayer` |
| 3 `ChangeHost_Mine` | 0x01f776d4 | flag set when 0 [0x01f77740], no new table |
| 4, 5 | 0x01f776dc | nothing |
| 6 `Leave_OtherPlayer` | 0x01f776ec | `OnLeaveOtherPlayer` |
| 7, 8, 9 | 0x01f77574 | `OnCrash` |

`UgNetworkManager$$OnReceiveDigTableData` [0x01f7dad0] adopts the first 0x61 that arrives while the
flag is 0, from any station, before or after its own `JoinIn_Mine`: it tests only the flag
[0x01f7db0c] and the class, stores the array as `ugDigGroupList` [0x01f7db94] unchecked, rebuilds the
dig points [0x01cfd6d0, 0x01cfdab0] and sets the flag. All three stores to +0xA8 write 1, so every
later 0x61 is ignored. The common dispatch (`SessionManager$$OnReceivePacket` `0x1df8ac0`) never
consults `INetData.FromStationIndex`. A retail non-host console has not been tested.

`CreateDigPoints` reads element `[MyStationIndex]` [0x01cfdc7c] (8 or more throws), finds the
`UgDigFossilePosGroup` with that `ID` (`List.Find` 0x01cfdcd8) and reads its `Grids` in
`CreateDigPointModel` [0x01cfe470] with no null test. In the 1.3.0 `ugdata` bundle each of the 35
zones (508 to 542) has eight groups, IDs 0 to 7, of 6 to 26 cells. Send only permutations of 0..7: a
larger byte faults the console.

Each `UgFieldManager` builds a new `UgNetworkManager` in `StartSession` [0x01cfebb0] (the only
`AddComponent<UgNetworkManager>`, 0x01cfed54) and destroys it in `OnDestroy` [0x01cff530], so each
adopts a table afresh.

0x29 `NetDigGroupIdData` shares 0x61's struct and methods. Only `NetDataParser`'s constructor
[0x0224a420] references it: nothing sends it, and `UgNetworkManager$$OnReceiveData` [0x01f7a880]
(22 ids) has no branch for it.

`bin/bdsp_connect.py --inject-file PATH` sends each new `ID:HEX` line of the file reliably.

### Ball capsules

The console recruits with "Déco Capsule" (state byte 7). It sends `NetDataTransitionData{7, 0}`, goes
to state 21 (`NOW_BALL_DECORATION`), and 1.8 s later sends its 143-byte `NetDataAttachSealNetData` as
a 116-byte zlib stream. After 45 s without an answer it shows "quelqu'un a mis fin à la communication" and returns
to the room. Answered with the client's own 143 bytes (`bin/bdsp_connect.py --answer-with 0x15:FILE`),
it applies them and returns to the room within five seconds, state byte 0. Send the answer from a
task of its own: from inside the receiver, the ack it waits for is never read.

In the 1.3.0 image, `BallDecoMatching$$ReceiveBallDecoData` (`0x021ca5e0`) runs once the console has
sent its own design (its first slot with seals). It writes the first of the 99 capsule slots with no
seals (`0x021ca674`), or nothing when all have seals. `BallDecoWork$$CopyTradeCapsuleData` (`0x01f23eb0`, absent from the
base game) clears the slot, attached Pokemon included, stores `Is3DEditMode` and `IsAppliedTemplate`
as `byte == 1`, and walks `affixSealCount` seals:

    if SaveSealData[id].Count >= 1:  place it at (x, y, z) / 100, then SubSealCount(id, 1)
    else:                            drop it

Seals on the player's capsules are out of stock until taken off (`CapsuleInfo$$RemoveAffixSeal`
`0x01e940d0` calls `BallDecoWork$$ReturnSealCount`). With none in stock nothing is written; the slot
stores the placed seals, compacted. The result is true when at least one was placed and none dropped, and picks the
closing message (`0x021c9f80`): `DLP_net_union_room_090` when true, `_114` ("Seuls les sceaux que
vous possédez ont été collés") otherwise. A count above 20 or a seal id of 200 or more indexes past
an array (`0x01f24254`, `0x0238b7b0`) and throws.

Positions are hundredths of the capsule radius, the surface at magnitude 100 in both modes. "Has
seals" is `AffixSealCount != 0` (`0x01e93630`). 3D mode draws every seal where it is. 2D mode
(`Capsule2DViewController$$UpdateGridCells`, `0x01e90de0`) draws a seal only at a grid cell's
`BallDecoWork$$Convert2DPosition` (`0x01f24da0`): radius 1, rows and columns 28 degrees apart on the
front (+z) and 25 on the back, each component rounded to 0.01.

`Capsule2DViewController$$Initialize` (`0x01e909b0`) takes the grid root's `Capsule2DGridCell`
children, the middle one as the centre (+0x78) and the root `GridLayoutGroup`'s cell size plus spacing
as the step, and gives each cell `GridPosition` = its offset from the centre over the step, rounded
(`0x01e90c48`); `Capsule2DGridCell$$Setup` (`0x01e905e0`) stores `Convert2DPosition(GridPosition,
isFront)` at +0x30. The 1.3.0 bundle `/Data/StreamingAssets/AssetAssistant/UIs/ui/uiresidentwindow`
holds three `Capsule2DViewController`s, each root `Grid` a `GridLayoutGroup` {cell 72x72, spacing 3x3,
7 fixed columns} over 37 cells and 12 corner spacers. The grid, front and back, is the 7 by 7 square
minus `(|x|, |y|)` in `{(3, 2), (2, 3), (3, 3)}`:

    row  3   columns -1..1
    row  2   columns -2..2
    row  1   columns -3..3
    row  0   columns -3..3
    row -1   columns -3..3
    row -2   columns -2..2
    row -3   columns -1..1

A console's own 2D capsule has its seals on front cells. A 2D design off the grid (a ring at z = 44)
fills a slot marked decorated and showing nothing; one on front cells shows the seals in stock.

The grid positions hold at the retail scale. `Initialize` divides world-space offsets
(`Transform$$get_position`, `0x01e90bd0`) by the local step, 75 on both axes (`fdiv` `0x01e90c10`).
Every ancestor up to the root `Seal` or `SealTemplate` has local scale 1; the root `Canvas` is a
screen-space overlay whose `CanvasScaler` scales from 1280 x 720 on the width, and the `Window`
animators bind only translations. The factor `Screen.width / 1280` is 1: the 1.3.0 `/Data/rawsettings`
u32 at +0x1c is 0, which keeps the default-resolution switch `0x006062e8` at 1280 x 720 docked and
handheld (1 follows the operation mode, 2 the performance mode, 3 both), and no managed code calls
`SetResolution` or a `Screen` setter.
