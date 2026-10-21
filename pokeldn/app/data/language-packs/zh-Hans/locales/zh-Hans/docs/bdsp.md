
<a id="brilliant-diamond-and-shining-pearl"></a>
# 晶灿钻石和明亮珍珠

晶灿钻石和明亮珍珠由 ILCA 使用 Unity 开发，IL2CPP 游戏代码直接使用 Pia。

测量使用法语版明亮珍珠 1.3.0，在联合房间（宝可梦中心二楼左侧接待员，选择普通的“是”）和地下大洞窟中进行。

<a id="status"></a>
## 状态

已在实机验证：

- 仅凭 `prod.keys` 和 LDN 口令即可加入游戏机会话；所有数据包均可解密，发送路径与游戏机自身密文逐字节一致。
- Local、Mesh Station 和 Mesh Protocol 的握手、RTT 定时器及双向可靠传输。
- 角色能在真实联合房间中行走、显示交换表情，并与玩家进行游戏原有的问候对话。
- 完整交换：接收游戏机提议、接受构建的宝可梦并写入存档；同一次关联中可连续交换（[交换](bdsp_trade.md#the-completed-trade)）。
- 担任主机：进入联合房间的游戏机加入 pokeldn 创建的房间，显示本机角色并完成交换（[担任主机](bdsp_session.md#hosting)）。
- 在联合房间交换制作的球壳；游戏机会使用玩家现有的贴纸，将球壳保存到收藏中（[游戏协议](bdsp_protocol.md)）。
- 混合记录和对战大厅，目前可接收到游戏机记录及其选择的六只宝可梦。
- 角色可在地下大洞窟中行走，并能读取游戏机的秘密基地。

<a id="pages"></a>
## 相关页面

|页 |内容 |
|---|---|
| [连接与Pia层](bdsp_session.md) |广告、密码、席位、数据包格式、密钥层次结构、网状握手和托管 |
| [游戏协议](bdsp_protocol.md) | BDSP 说话、联合房间和控制角色的 65 条消息 |
| [交易](bdsp_trade.md) |交换流程、PB8、保存和断开惩罚 |

<a id="unresolved"></a>
## 未解决

- 游戏机屏幕上是否会显示替换后的问候名称（[问候中的名称](bdsp_protocol.md#the-name-in-the-greeting)）。
- 未发起对战的实机收到 0x08 后会显示什么：代码会写入地址 0x18，既没有空指针检查，游戏模块也没有用户异常处理程序。此前发送的 0x08 使用了可靠传输窗口已接收过的序列号，因此尚未到达该路径（[对战流程](bdsp_protocol.md#the-battle-ladder)）。
- 非地下大洞窟会话主机的实机是否接受 pokeldn 发来的 0x61；已测量的地下会话均由游戏机担任主机，pokeldn 尚未主持此类会话。公共分发逻辑和 `UgNetworkManager` 处理程序都不筛选发送方（[协议页面](bdsp_protocol.md#the-grand-underground)）。
