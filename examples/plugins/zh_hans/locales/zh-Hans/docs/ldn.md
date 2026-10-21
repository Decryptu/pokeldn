<a id="the-wireless-layer"></a>
# 无线层

Switch 通过 **LDN**（任天堂的本地无线网络）与附近的游戏机进行通信，并通过任天堂的点对点会话中间件 [Pia](pia.md) 与附近的游戏机进行通信。两者都是系统库；标题因 Pia 版本和有效负载而异。
<a id="the-two-secrets"></a>
## 两个秘密

LDN 密码验证 802.11 关联：16-64 字节（由
`nn::pia::local::LdnBackgroundProcessJob`)，逐字使用； 晶灿钻石直接将 ASCII 字符串传递给 `nn::ldn::CreateNetwork`。 16 字节 Pia 游戏密钥派生出加密每个数据报的会话密钥。

|标题 | LDN 密码 | Pia游戏键|
|---|---|---|
| 晶灿钻石／明亮珍珠 | `WirelessStrongCryptoKey2021`（27 字节，原始）|源自 `cryptoKeyDataSeed`；参见[BDSP](bdsp_session.md) |
| 剑／盾 | `W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL`（64 字节，原始）| `p1frXqxmeCZWFv0X` |

朱／紫和传说阿尔宙斯使用剑／盾的密码和游戏密钥([朱和紫](sv.md), [传说阿尔宙斯](pla.md)); NintendoClients wiki 中阿尔宙斯的 `HGHG` 拼写是错误的。
<a id="discovery"></a>
## 发现

阅读广告只需要`prod.keys`：`tools/ldn/ldn_scan.py`显示任何会话的
`local_communication_id`、`scene_id`、版本、通道、接受策略、参与者数量和应用数据。标题只能看到其自己的 LDN 协议的广告（1：AES-CTR
`master_key_00`; 3：`master_key_12` 下的 AES-GCM），因此主机复制标题的（`HostTransport(protocol=...)`）。

|标题 |协议|广告格式|
|---|---|---|
| GBA 应用程序（火红、叶绿），通讯 ID `0x01006fa0233f8000` | 3 | 3、AES-GCM|
|剑神秘礼物屏幕，通讯 ID `0x0100abf008968000` | 1 | 2、AES-CTR|
| 传说阿尔宙斯本地交换，通讯 ID `0x01001f5010dfa000` | 1 | 4 |

主机游戏机以 11 Mbit/s DSSS 发送信标，并以 HT MCS 3、20 MHz (OFDM) 发送广告操作帧，朱的链路交换搜索和 剑 的神秘礼物屏幕类似；仅 DSSS 接收器会错过动作帧。
<a id="the-advertisements-application-data"></a>
## 广告的应用数据

Pia 5布局，来自明亮珍珠：

    +0x00  4  network id                     random per session
    +0x04  4  CRC32 of the user password     0 when the room has no password
    +0x08  1  system communication version
    +0x09  1  header size                    16
    +0x0a  2  padding
    +0x0c  4  session parameter              random per session; seeds the Pia session key
    +0x10     application data
 捕获仅使用其自己会话的广告进行解密；另一个默默地失败了。

Pia 6.16 到 6.41 使用系统属性块并从 SSID 派生会话密钥和网络 ID：

    +0x00  2  system property data size      0x5C
    +0x02  1  system communication version   21 for 6.16-6.30, 22 for 6.39-6.41
    +0x03  2  application communication version
    +0x05  16 user password
    +0x15  1  is player limit enabled
    +0x16  1  number of players
    +0x17  4  player name size
    +0x1b  1  player name encoding           1 = UTF-8, 2 = UTF-16
    +0x1c  64 player name
    +0x5c     application data
 启用传输加密后，用户密码将使用 0xFE 填充到 16 个字节并就地加密，游戏密钥下的 AES-128-GCM，标签被丢弃，IV `key[1] key[8] key[7] key[2]`，然后由区块生成器复制（阿尔宙斯 1.1.1 `0x6fac70`；[the设置器](pla.md#the-link-code-in-the-advertisement))。一个 GCM 块是一个 XOR，其密钥流由密钥固定：游戏密钥单独读取密码。
<a id="hosting-for-an-emulator"></a>
## 模拟器托管

ldn_mitm 模式下的模拟器通过端口 11452 关联，然后通过 LAN 运行 Pia：无无线收发设备，无
`prod.keys`，无root。 `pokeldn/ldn/ldn_mitm.py` 加入； `ldn_mitm_host.py` 主机通过
`IpHostTransport`，其中`NEEDS_RADIO = False`选择`NullBeaconInjector`。

    UDP  console -> host:11452   Scan          header only, unicast and broadcast
    UDP  host    -> console      ScanResp      NetworkInfo, 0x480
    TCP  console -> host:11452   Connect       NodeInfo, 0x40
    TCP  host    -> console      SyncNetwork   NetworkInfo with the console seated, held open

`nn::ldn::NetworkInfo`、0x480 字节：

    +0x000  NetworkId          IntentId 0x10 (u64 localCommunicationId, u16, u16 sceneId, u32) then SessionId 0x10
    +0x020  CommonNetworkInfo  MAC 6, Ssid 0x22 (length byte then 0x21), s16 channel, u8 linkLevel, u8 networkType, u32
    +0x050  LdnNetworkInfo     SecurityParameter 0x10, u16 securityMode, u8 acceptPolicy, ...
    +0x066                     u8 nodeCountMax, u8 nodeCount
    +0x068                     NodeInfo[8], 0x40 each: u32 IPv4 little-endian, MAC 6, u8 nodeId,
                               u8 isConnected, 0x20 name at 0x0C, u16 localCommunicationVersion at 0x2E
    +0x26A                     u16 advertiseDataSize, then 0x180 bytes of advertise data
    +0x478                     u64 authenticationId
 节点携带真实的 LAN 地址（Pia 未隧道化）；节点 0 必须可达，绝不是链路本地：游戏机发送 Pia 并在那里打开 TCP 连接。仿真器从节点的地址（172.16.86.1 为 `02:00:ac:10:56:01`）得出节点的 MAC。游戏自己的节点在+0x2E处保存88（在0x2C处的字节之后对齐），其`ConnectImpl`传递的值，并且游戏保持NetworkInfo与发送的完全相同。 火红的扫描过滤器仅比较 `localCommunicationId` 和 `networkType` (`sceneId`
0xFFFF、`ssidLength` 0)。

16 字节会话 id 是三个位置中的一个值：`NetworkId.SessionId`、十六进制的 `Ssid` 文本以及 Pia 会话密钥的明文 `AES(game_key).encrypt(ssid)`、网络 id
`crc32(ssid[1:16])` [`pokeldn/ldn/crypto.py`:114]，正如 LDN 库所做的那样 [vendor/LDN/ldn/__init__.py:1921, :1910]。广告一个并与另一个同事加密，然后游戏机会丢弃所有数据报告并超时，没有错误。
<a id="a-stations-broadcasts"></a>
## 某电台的广播

加入的游戏机直接向 BSS 发送广播和多播（无 DS 位；地址组、游戏机、BSSID；CCMP 组密钥、密钥 id 1）和单播至 DS（成对密钥、密钥 id 0）。 火红的第一个广播是主机的 ARP 和 IPv6 多播。标准接入点会丢弃没有 DS 位的帧，并且不应答 ARP 的主机会因原因 3 被取消验证。 [ESP32](hardware_esp32.md) 会整个转发这些帧 (`vendor/LDN/ldn/__init__.py`)
`_process_data_frame` 为旧版 Linux 路径解密它们）。
<a id="channels"></a>
## 频道

LDN 还允许 5 GHz 通道 36/40/44/48，这是 ESP32 无法达到的； 火红／叶绿仅扫描 2.4 GHz。重新托管的游戏机可能会改变频道；开发板的扫描打印它：

    POKELDN_RADIO=esp32:auto ./.venv/bin/python tools/ldn/ldn_scan.py --keys PROD_KEYS --dwell 2.5
 广告泄漏到相邻频道：主板也会在自己旁边的频道上听到主机的广告，但数量要少得多，且 RSSI 相同。加入邻居关联，并且主机自己的通道上的下一个广告会因为不兼容的网络而丢弃该链接；因此，扫描会报告最繁忙的频道。
