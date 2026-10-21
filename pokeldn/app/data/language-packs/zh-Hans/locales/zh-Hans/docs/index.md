
<a id="pokeldn"></a>
# pokeldn

pokeldn 实现 Nintendo Switch 本地无线通信（LDN），通过 ESP32 无线开发板与实机上的宝可梦游戏通信：电脑和 Android 手机使用 USB 串口，iPhone 使用蓝牙。本系列文档说明相关协议，包含反编译引用、反汇编地址和硬件测量结果。

先阅读[应用设置](gui.md)或[命令行用法](usage.md)。[代码组织](architecture.md)介绍共享模块和测试。

<a id="targets"></a>
## 支持的游戏与功能

七款游戏均在真实硬件上运行，共用相同的 LDN 和 Pia 通信层：

| 功能 | FRLG | LGPE | SwSh | BDSP | PLA | SV | PLZA |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 交换 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 神秘礼物 | ✓ | ∅ | ✓ | ∅ | ∅ | ∅ | ∅ |
| 活动宝可梦 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 连接对战 | ✓ | ✗ | ✗ | ✗ | ∅ | ✗ | ✗ |
| 在游戏机运行代码、读取和写入存档 | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |

✓ 已在实机验证 · ✗ 尚未实现 · ∅ 游戏未通过本地无线通信提供此功能

FRLG：火红／叶绿 · LGPE：Let's Go! 皮卡丘／伊布 · SwSh：剑／盾 · BDSP：晶灿钻石／明亮珍珠 · PLA：传说 阿尔宙斯 · SV：朱／紫 · PLZA：传说 Z-A

火红和叶绿在 Switch 的模拟器中运行原始 GBA ROM，因此 ROM 自身的 GBA 连接协议叠加在游戏机的 LDN 和 Pia 上。其余六款游戏的代码直接使用 Pia：晶灿钻石和明亮珍珠使用 Unity／IL2CPP；剑／盾和 Let's Go! 使用 C++，在 `gflnet3` 上传输 Protocol Buffers；传说 阿尔宙斯、朱／紫和传说 Z-A 使用静态链接 Pia 的 C++ 代码。

<a id="sections"></a>
## 文档章节

| 章节 | 内容 |
|---|---|
| [无线通信层](ldn.md) | LDN 和 Pia：广播、关联、各版本的数据包格式及会话密钥派生，与具体游戏无关。 |
| [Switch 游戏逆向分析](switch_re.md) | 读取真实游戏的代码：原地提取 NCA／RomFS、IL2CPP 元数据和 C++ RTTI，以及通用分析方法。 |
| [火红和叶绿](frlg.md) | GBA 连接、神秘礼物、在游戏机执行代码、随机数生成器，以及两种卡带的差异。 |
| [晶灿钻石和明亮珍珠](bdsp.md) | Pia 5.27–5.45、联合房间和交换流程。 |
| [剑和盾](swsh.md) | Pia 4、同步框架、交换，以及神秘礼物的本地通信分支。 |
| [Let's Go! 皮卡丘和伊布](lgpe.md) | Pia 3、连接密码和交换流程。 |
| [传说 阿尔宙斯](pla.md) | Pia 头部版本 11、交换流程，以及主机构建的记录。 |
| [朱和紫](sv.md) | Pia 头部版本 11、可靠数据流、主机执行的交换流程，以及主持和加入太晶团体战。 |
| [传说 Z-A](za.md) | Pia 头部版本 16、游戏的二十种交换消息，以及主机和加入方的交换流程。 |
| [模拟神秘礼物](gift_simulated.md) | 为不支持本地神秘礼物的五组游戏，通过交换提供按接收存档生成的官方礼物宝可梦。 |
| [命令行用法](usage.md) | 源码设置及各游戏命令。 |
| [桌面应用](gui.md) | 设置、银行、手柄、更新与构建。 |
| [代码组织](architecture.md) | 共享模块、宝可梦准备和验证。 |
| [硬件与设置](hardware.md) | ESP32 无线收发设备、Switch 密钥，以及旧版 Linux Wi-Fi 适配器方案。 |

<a id="credits"></a>
## 致谢

本项目基于 [kinnay 的 LDN 库](https://github.com/kinnay/LDN)和 [NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki)，并参考了火红／叶绿的反编译项目 [pret/pokefirered](https://github.com/pret/pokefirered)。
