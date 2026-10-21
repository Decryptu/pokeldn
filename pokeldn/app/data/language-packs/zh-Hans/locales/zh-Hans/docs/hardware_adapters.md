<a id="wi-fi-adapters"></a>
# Wi-Fi 适配器

Linux 主机可以作为 root 直接驱动支持 AP 的 Wi-Fi 卡，代替 [ESP32 无线收发设备](hardware_esp32.md)。这条道路是遗留的，没有进一步发展。

|症状 |原因 |
|---|---|
| 启动 AP 时出现类似虚拟机管理程序造成的 USB 断连 | USB 模式开关（见下文） |
|沉默的主机| `accept_decrypted_ccmp` 未设置 |
| `failed to get tx report from firmware` 在 `dmesg` |主机自行拆解|
<a id="windows-usb-wi-fi-through-ldnrs"></a>
## 通过 ldnrs 使用 Windows USB Wi-Fi

Windows 可通过 [ldnrs 0.0.3](https://github.com/unlimitedcoder2/ldnrs/releases/tag/0.0.3) 使用外置 USB Wi-Fi 适配器。请另行安装 ldnrs，完成适配器向导并保持其守护进程运行。在 pokeldn 的“插件”页面，从“无线后端”中选择“USB Wi-Fi（Windows，ldnrs）”。Switch 密钥仍使用 pokeldn 设置中的文件。

ldnrs 向导会将选定适配器绑定到 WinUSB，并下载所需的 Linux 驱动固件。WinUSB 接管期间，该适配器无法再提供普通 Windows Wi-Fi，请使用其他连接访问互联网。要恢复普通联网，请在设备管理器中恢复原驱动。兼容性取决于 ldnrs 中的驱动及固件；下方的 Linux 网卡测量不能证明 Windows 兼容性。

在 PowerShell 中，先选择后端，再运行对应游戏的常规启动器：

```powershell
$env:POKELDN_RADIO = 'ldnrs:'
python bin/swsh_gift_host.py --keys C:\Switch\prod.keys --species 25 --level 25
```

空参数选择本地管道 `\\.\pipe\ldnd`，冒号后也可指定其他本地管道。守护进程通过该本地管道接收选定的密钥，负责无线设备、LDN 关联与加密；pokeldn 通过既有的用户态 IPv4 协议栈传输以太网帧。扫描、加入、主持及广播更新使用[守护进程协议 7](https://github.com/unlimitedcoder2/ldnrs/blob/0.0.3/docs/daemon-protocol.md)。守护进程缺失、适配器未就绪或协议版本不符时会报错。

守护进程允许关联过程耗时 70 秒，启动器至少允许 90 秒。上游的 [RTL8822BU 测量](https://github.com/unlimitedcoder2/ldnrs/blob/0.0.3/clients/python/ldnd/compat.py)显示，两次驱动重新配置各需约 14.5 秒。游戏握手在关联完成后开始。一个守护进程同时只能处理一场会话；会话结束时，pokeldn 关闭自身原始通道及网络，外部守护进程继续运行。数据包捕获仍保留游戏 UDP 流量，但 ESP32 计数器及随包库的 Wi-Fi 管理钩子不适用于此后端。

离线检查会将扫描、加入与主持请求对照 ldnrs 0.0.3 Python 客户端生成的向量，并与脚本化守护进程通过原始以太网通道交换 UDP。目前尚未使用 Windows 适配器及零售版游戏机实测此后端。

<a id="tested-cards"></a>
## 测试卡

|型号|类型 |司机 |测试主机上的结果 |
|---|---|---|---|
| TP-Link Archer T3U (`2357:012d`) |外接USB | `rtw88_8822bu` |可靠的;参考适配器|
|阿尔法 AWUS036ACHM |外接USB | `mt76x0u` |可靠 |
|瑞昱 RTL8821CE |内部 PCIe | `rtw88_8821ce` |可靠 |
| AMD RZ616 | AMD RZ616内部 M.2 | `mt7921e` |大约一半的速度，有时退出前会出现僵局|
| MT7601U |外接USB | `mt7601u` |原厂驱动没有AP模式；需要固定的 `mt7601u-ap` DKMS 模块 ([Raspberry Pi 主机](hardware_raspberry_pi.md)) |
|英特尔 AX200 |内部 M.2 | `iwlwifi` |失败：无法分配 IP |
|创锐讯 AR9271 |外接USB | `ath9k_htc` |失败：通常无法分配IP |
<a id="host-modes"></a>
## 主机模式

`--skip-encryption` 跳过 LDN 的 Python CCMP 步骤，因此 mac80211 或硬件应用 CCMP 一次；无线流量保持加密状态。 Archer T3U（`config/host.toml` 中的 `skip_encryption = true`）和 ALFA AWUS036ACHM 需要它。

`--accept-decrypted-ccmp` 用于监视器驱动程序，将 CCMP 标头和 MIC 保留在硬件解密的明文周围，就像 Archer T3U 的 `rtw88_8822bu` 所做的那样；它在将明文转发到 `ldn-tap` 之前剥离 MIC。对于提供标准框架的 ALFA，请将其关闭。

|适配器| 主机配置 |
|---|---|
| TP-Link弓箭手T3U |跟踪的 `config/host.toml` 轮廓；没有 Wi-Fi 标志 |
|阿尔法 AWUS036ACHM | `--phy phyN --skip-encryption --no-accept-decrypted-ccmp` |

`phy = "auto"` 仅解析单个 `rtw88_8822bu` USB `2357:012d` 设备，并且在一个或多个上失败。显式的 `--phy phyN` 总是获胜；保留它用于一次性调试，因为每次重新枚举时数字都会发生变化。启动会打印检测到的配置文件、传输和接收模式，如果标志与经过验证的配置文件不同，则会发出警告。
<a id="the-tp-link-archer-t3u"></a>
## TP-Link Archer T3U

`rtw88_8822bu` 自内核 6.11 起成为主线，并列出了此 USB id。确认内核绑定它：

```bash
modinfo rtw88_8822bu | grep -i 2357
lsusb | grep -i 2357
iw dev
```

<a id="keep-networkmanager-off-the-adapter-itself"></a>
### 让 NetworkManager 远离适配器本身

NetworkManager 声明适配器的热插拔接口 (`wlx...`) 并启动后台扫描；界面出现后不久，频道更改就会导致无线收发设备关闭（测量 11 秒）：

```text
rtw88_8822bu 3-1:1.0: write register 0x81c failed with -71
usb 3-1: USB disconnect, device number 2
```
 排除适配器和 LDN 接口：

```text
# /etc/NetworkManager/conf.d/zz-ldn-unmanaged.conf
[keyfile]
unmanaged-devices=interface-name:ldnclient;interface-name:ldn;interface-name:ldn-mon;interface-name:ldn-tap;interface-name:wlx*;interface-name:wlan*
```
 文件必须最后排序 (`zz-`)：某些发行版提供较晚的文件设置
`unmanaged-devices=none`。重新加载网络管理器； `nmcli device status` 必须显示适配器
`unmanaged` 和 `NetworkManager --print-config | grep unmanaged` 列表。如果其中没有 `ldnclient`，NetworkManager 会抓取连接创建的接口，将 wpa_supplicant 指向它，并且连接会失败并显示 `[Errno 114] Match already configured`。
<a id="disable-the-drivers-usb-3-mode-switch"></a>
### 禁用驱动程序的 USB 3 模式开关

`rtw88_usb` 默认为 `switch_usb_mode=Y`，它在驱动程序加载后将适配器重新枚举为 USB 3 模式。使设备通过的虚拟机管理程序发现断开连接，LDN 接口消失，主机在托管过程中早期终止（测量大约 1 秒），且没有先前的驱动程序错误：

```text
RuntimeError: 802.11 beacon injector stopped: [Errno 100] Network is down
```
 该参数本身的描述指出，USB 3 模式可能会干扰 LDN 的 2.4 GHz 频段。

```text
# /etc/modprobe.d/rtw88-ldn.conf
options rtw88_usb switch_usb_mode=N
options rtw88_core disable_lps_deep=Y
```
 之后重新插入适配器：它会保持在 USB 3 模式，直到断电。然后它以高速连接一次（打开开关后，它会枚举两次，先是高速，然后是超高速）：

```bash
cat /sys/bus/usb/devices/*/speed     # 480, not 5000
cat /sys/bus/usb/devices/*/version   # 2.10, not 3.00
```

<a id="bring-the-adapter-interface-down-before-a-run"></a>
### 在运行前关闭适配器接口

向上管理的接口保存无线收发设备的信道。 `transport.free_radio()`降低；一个裸露的
`tools/ldn/ldn_scan.py` 不：

```text
OSError: [Errno 16] Device or resource busy
```

```bash
sudo ip link set wlxXXXXXXXXXXXX down
```
 恢复基本接口的终止脚本会导致下次启动失败并出现该错误。任何为内核 `iw scan` 提高它的东西都必须在移交之前再次降低它。
<a id="verify"></a>
### 核实

`./scripts/preflight_pi.sh` 在任何 Linux 主机上运行。
