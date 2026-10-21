
<a id="controller-board"></a>
# 手柄开发板

手柄开发板可以是通过 USB-C 被 Switch 识别为有线手柄的 ESP32-S3，也可以是通过经典蓝牙作为 Pro 手柄配对的经典 ESP32。电脑控制主机按键，并加载由开发板按自身时钟执行的宏。固件位于 `firmware/pad`，电脑端位于 `pokeldn.pad`，应用页面见[手柄控制](gui.md#the-controller)，命令行工具为 `tools/switch/pad.py`。

<a id="which-boards"></a>
## 支持的开发板

| 芯片 | 手柄方式 | 原因 |
|---|---|---|
| ESP32-S3 | USB 有线手柄 | USB-OTG 模块可以实现任意 USB 设备 |
| 经典 ESP32 | 经典蓝牙无线 Pro 手柄；电脑通过 USB 串口连接 | 没有原生 USB 设备功能，但支持 Pro 手柄使用的经典蓝牙 |
| ESP32-C3、ESP32-C6 | 不支持 | USB Serial/JTAG 为固定功能，且蓝牙仅支持 LE |

<a id="the-usb-side"></a>
## USB 端

开发板枚举为 HORI 宝拳手柄，ID 为 `0f0d:0092`，只有一个 HID 接口，带中断 IN 和 OUT 端点。Switch 将此 ID 作为普通 HID 手柄接收，无需 Pro 手柄握手。固件 23.0.1 的零售版 Switch Lite 在 HOME 菜单中成功枚举，并根据开发板报告移动光标，无需修改设置。

输入报告长 8 字节，只要 USB 主机准备好接收，就每毫秒发送一次：

| 偏移 | 大小 | 字段 |
|---|---|---|
| 0 | 2 | 按键，小端序 |
| 2 | 1 | 方向：0 为上，顺时针递增到 7（左上）；8 为居中 |
| 3 | 4 | LX、LY、RX、RY；128 为居中，0 为左或上 |
| 7 | 1 | 厂商字节，固件在此写入蓝牙状态 |

| 位 | 按键 | 位 | 按键 |
|---|---|---|---|
| 0x0001 | Y | 0x0100 | Minus |
| 0x0002 | B | 0x0200 | Plus |
| 0x0004 | A | 0x0400 | 左摇杆按下 |
| 0x0008 | X | 0x0800 | 右摇杆按下 |
| 0x0010 | L | 0x1000 | HOME |
| 0x0020 | R | 0x2000 | 截图 |
| 0x0040 | ZL | | |
| 0x0080 | ZR | | |

厂商字节：1 已同步，2 正在广播，3 已连接；步骤失败时为 `0x80 | step`。

<a id="cabling"></a>
## 接线

使用 USB-C 转 USB-C 数据线连接开发板和主机。主机同时提供电源并作为 USB 主机，开发板从其取电。USB 主机配置设备后，XIAO ESP32S3 的 LED（GPIO21）亮起。

Switch Lite 通过 C-to-C 线缆连接到 Mac 时由 Switch 供电，且不枚举设备。通过 Mac 的 USB-A 接口连接，并打开“通过 USB 连接复制到电脑”后，会枚举为 `057e:201d`，带一个 MTP 接口、只读“Album”存储及十个只读操作（`0x1001` 至 `0x100a`）。

<a id="the-bluetooth-side"></a>
## 蓝牙端

开发板以 `POKELDN-PAD` 广播，提供一个服务 `7a1e0001-5d2c-4c3e-9f4b-504f4b454c44`：

| 特征 | 访问方式 | 内容 |
|---|---|---|
| `...0002` | 写入、无响应写入 | 原样发送的 8 字节输入报告；宏运行时忽略 |
| `...0003` | 读取 | 下述状态 |
| `...0004` | 写入 | 下述命令 |

状态使用小端序：已配置标志 u8、报告写入次数 u32、运行标志 u8、已完成循环数 u32、条目索引 u16、条目数 u16、固件版本文本、NUL、重置原因 u8（`esp_reset_reason`）、上次启动到达的阶段 u8，以及上电以来的启动次数 u16。1.0.0 之前的固件只发送前五个字节。

| 命令 | 内容 | 效果 |
|---|---|---|
| `0x10` load | 条目数 u16、循环起点 u16、循环次数 u32 | 停止宏并设置程序大小；循环次数 0 表示直到手动停止 |
| `0x11` data | 首个条目 u16，随后为条目 | 每个条目包含报告和以毫秒为单位的按住时长 u16，共 10 字节 |
| `0x12` play | | 开始执行程序 |
| `0x13` stop | | 停止并释放全部按键 |
| `0xB0` download | | 重启芯片进入 ROM 下载模式 |

程序最多容纳 8192 个条目。循环起点之前只运行一次，其余部分重复执行。执行器使用 1 kHz 时钟节拍下的 `vTaskDelayUntil` 等待，累计时长不会漂移：在 Mac 的 USB 端测得，重复 10 次的宏每轮均为准确的 500 毫秒。

macOS 上使用 bleak 无响应写入时，CoreBluetooth 队列已满会丢弃写入，而 bleak 不读取 `canSendWriteWithoutResponse`：连续发送 300 个中立报告，开发板只计数 67 次；间隔至少 20 毫秒时，40 次全部到达。`pokeldn.pad.link` 在每次写报告前等待该标志；若没有此标志或持续一秒为假，则使用有响应写入。

| 报告写入方式 | 连续发送时的单次耗时 | 到达开发板的报告 |
|---|---|---|
| 无响应，无节流 | 0.1 毫秒 | 300 个中到达 67 个 |
| 有响应 | 60 毫秒，连接后的前 25 秒内保持稳定 | 300 个全部到达 |
| 无响应，按标志节流 | 2.4 毫秒 | 200 个全部到达 |

固件 1.2.0 在连接时请求 15 至 30 毫秒的连接间隔；有响应写入仍需 63 毫秒，尚不清楚 macOS 是否接受该请求。

连接断开会将报告恢复到中立状态，因此电脑消失后不会留下按住的按键；正在运行的宏继续执行。

<a id="the-serial-side"></a>
## 串口端

经典 ESP32 保持连接到电脑的 USB 接口，UART0 以 921600 波特率双向传输帧（`firmware/pad/main/uart_link.c`、`pokeldn/pad/serial_link.py`），关闭控制台输出。关闭控制台后，没有代码把 UART0 路由到 GPIO1 和 GPIO3，因此固件自行设置引脚；否则开发板不会回应。

    A5 5A | length u16 (type and payload) | type u8 | payload | sum of type and payload mod 256

| 类型 | 方向 | 载荷 |
|---|---|---|
| `0x01` | 发往开发板 | 8 字节报告；回复 `0x81` |
| `0x02` | 发往开发板 | 无；以 `0x82` 回复状态记录 |
| `0x03` | 发往开发板 | 与控制特征相同的命令；回复 `0x81` |
| `0x81` | 发往电脑 | 结果 i8：0 成功，-1 长度错误，-2 拒绝 |
| `0x82` | 发往电脑 | 状态记录；mounted 表示 Switch 已设置玩家指示灯 |

电脑打开端口时将 DTR 和 RTS 置低。但在 macOS 上，DevKit 的 CP2102 仍会在打开端口时重启开发板，启动期间的请求会丢失，因此电脑会在最多 3 秒内重复发送状态请求。服务先尝试除 S3 原生 USB 之外的 USB 串口，再扫描蓝牙 LE。应由一个进程持续持有端口：每次重新打开都会重启开发板并断开蓝牙连接。

<a id="the-bluetooth-classic-side"></a>
## 经典蓝牙端

`firmware/pad/main/bt_esp32.c` 注册 Bluedroid HID 设备：170 字节 Pro 手柄报告描述符、服务“Wireless Gamepad”、提供者“Nintendo”、子类 0x08、设备类别 0x002508、名称“Pro Controller”，采用无输入无输出的 SSP，关闭调制解调器睡眠。它按 ID 回复 0x01 子命令：0x02 设备信息（固件 4.00、类型 0x03、蓝牙地址）、0x10 SPI 读取、0x03 报告模式、0x04 触发器时间、0x21 MCU 配置，其余回复普通 ACK；0x30（玩家指示灯）表示手柄已被接收。回复优先于任何 0x30 报告发送。

蓝牙连接建立后，按键或摇杆变化时立即发送 0x30 报告，否则每 100 毫秒发送一次；不发送报告时，Switch Lite 虽已连接却不会启动握手。连接建立后等待 1 秒，转入 sniff 模式后等待 250 毫秒，发送因拥塞（原因 8）被拒绝后等待 45 毫秒。这些值来自 friendmaker 的 Switch Lite 配置（`classic_bt_controller_transport.cpp`、`SWITCH_LITE`）。

| 0x30 发送节奏 | 实机 Switch Lite |
|---|---|
| 0x03 模式切换后每 15 毫秒发送 | 握手完成至玩家指示灯，随后 Bluedroid 切换 sniff 模式，发送因拥塞失败；指示灯亮后 2 到 20 秒 Switch 断开（HCI 0x13），没有按键到达画面 |
| 变化时发送，否则每 100 毫秒，使用上述等待 | 连接保持稳定，501 次发送中 0 次失败；按键可移动“更改握法／顺序”和“手柄”菜单的光标 |

Switch 的握手顺序：0x02、0x08、0x6000 和 0x6050 处的 0x10、0x03（0x30）、0x04、0x6080、0x6098、0x8010、0x603D、0x6020 处的 0x10、0x40、0x30（0）、0x48、0x21、0x30（玩家 1）。

已配对开发板启动时会重新连接 Switch。刷写合并镜像会覆盖 NVS 分区及配对记录，因此需从“更改握法／顺序”重新配对。

`pro_report.c` 将共用报告映射到 Pro 手柄的字节布局（dekuNukem 的 `bluetooth_hid_notes.md`）：摇杆居中为 0x800，两个方向的幅度均为 0x700，与 0x603D 返回的出厂校准一致；序列号和用户校准返回空白闪存值（0xFF）。`tests/test_pad_pro.py` 在电脑端编译并检查全部按键位和校准。

<a id="macros"></a>
## 宏

宏是扩展名为 `.pokemacro` 的 JSON 文件（`pokeldn.pad.macro`）：

```json
{
  "format": "pokeldn-macro", "version": 1,
  "name": "Soft reset", "description": "", "author": "", "game": "",
  "press_ms": 100, "gap_ms": 150,
  "setup": [{"press": "HOME"}, {"wait": 1000}],
  "loop": [
    {"press": ["A", "B"], "ms": 500, "after": 2000, "note": "skip the intro"},
    {"repeat": 3, "steps": [{"press": "A"}]},
    {"press": [], "left": [0, 1], "ms": 300},
    {"wait": 5000}
  ],
  "loops": 0
}
```

| 字段 | 含义 |
|---|---|
| `press_ms`, `gap_ms` | 步骤未指定时的按住时长及操作后间隔 |
| `setup` | 只运行一次的步骤 |
| `loop` | 重复 `loops` 次的步骤；0 表示直到手动停止 |
| 按键步骤 | `press`：按键名称或同时按下的名称列表（`A B X Y L R ZL ZR PLUS MINUS LSTICK RSTICK HOME CAPTURE UP DOWN LEFT RIGHT UPLEFT UPRIGHT DOWNLEFT DOWNRIGHT`）；`left` 和 `right`：摇杆 `[x, y]`，取值 -1 到 1，向上为正；`ms` 按住时长；`after` 间隔；`note` 备注 |
| 等待步骤 | `wait`：释放全部按键后等待的毫秒数 |
| 重复步骤 | `repeat`：对 `steps` 重复 1 到 10000 次，最多嵌套 8 层 |

编译器展开重复，合并相邻的相同报告，并拆分超过 65535 毫秒的按住操作。展开后超过 8192 个条目的宏会被拒绝。两个相同按键之间使用 `after: 0` 会连续保持按下。文件的 `version` 高于读取器版本时会被拒绝。

<a id="the-host-side"></a>
## 电脑端

`pokeldn.pad.service` 持有蓝牙连接，在 `127.0.0.1:47800` 每行接收一个 JSON 请求：`status`、`connect`、`send`、`tap`、`play`、`stop`、`download`、`scan`、`disconnect`。应用将其作为子进程启动；若没有正在运行的服务，`tools/switch/pad.py` 在自身进程中启动服务。

macOS 上开发板在保持连接时断电（从 Switch 拔下），CoreBluetooth 可能让读取或写入一直等待且不报错。服务会限时回复每个请求（`status` 为 5 秒，`play` 为 120 秒，`scan` 为 20 秒，其余含连接为 40 秒）。超时后服务关闭连接，使开发板重新广播，并返回错误。应用客户端在 150 秒后停止等待。

    ./.venv/bin/python tools/switch/pad.py A
    ./.venv/bin/python tools/switch/pad.py HOME wait:1 'RIGHT*3' A
    ./.venv/bin/python tools/switch/pad.py hold:B:2 stick:L:-1:0:0.5
    ./.venv/bin/python tools/switch/pad.py --play soft_reset.pokemacro
    ./.venv/bin/python tools/switch/pad.py --stop --status

若负责进程的应用未声明 `NSBluetoothAlwaysUsageDescription`，macOS 会终止尝试使用蓝牙的进程，嵌入其他应用的终端会出现此问题。`pad.py --make-app PATH` 创建运行服务的小应用；使用 `open` 打开一次并允许蓝牙后，后续 `pad.py` 调用及源码运行的应用均可使用它。

<a id="flashing-again"></a>
## 再次刷写

手柄占用 USB 接口，esptool 无法将其重置进下载模式。download 命令、开发板页的安装操作及 `pad.py --download` 均通过蓝牙完成；按住 BOOT 连接开发板则无需现有固件。

- `RTC_CNTL_USB_CONF` 在重置后保留。若停留在 USB-OTG，下载器枚举为 OTG CDC 设备 `303a:0009`，esptool 只有约一半概率连接成功。固件先停止 NimBLE 和 TinyUSB，将 PHY 交还 USB Serial/JTAG，并在重置前设置 `RTC_CNTL_FORCE_DOWNLOAD_BOOT`；下载器此后始终为 `303a:1001`。
- 蓝牙和 USB 均运行时调用 `esp_restart()` 曾出现卡住：已枚举、LED 亮起，但没有报告。
- macOS 首次打开新出现的下载端口时读不到数据，esptool 还会在整个进程期间锁住端口。`gui/board.py` 刷写手柄固件前等待 8 秒再不重置地连接；仍运行无线固件时回退到重置方式。
- 强制下载模式刷写后，USB 重置会停留在下载器；看门狗重置才能启动镜像（`--after watchdog-reset`）。

通过 `python -m gui.board --kind pad|radio` 已验证无线固件与手柄固件的双向切换。`--from-loader` 用于 download 命令已置入下载模式的开发板：先等待，不重置地连接，再通过看门狗启动镜像，与手柄固件的流程相同。

注意：FreeRTOS 默认 100 Hz 时，USB 循环延迟换算为零个节拍，导致 NimBLE 得不到运行时间；此固件使用 1000 Hz 构建。

<a id="build"></a>
## 构建

    . scratchpad/esp/env.sh
    cd firmware/pad && idf.py -B BUILD_DIR -D SDKCONFIG=SDKCONFIG_PATH build

TinyUSB 来自组件管理器（`espressif/esp_tinyusb` 2.4.0）。发布构建在无线镜像旁生成 `pokeldn-pad-s3.bin`。

<a id="unresolved"></a>
## 尚未验证

- Switch 2 是否与经典 ESP32 固件配对；目前只测量了 Switch Lite。
- Switch 2 是否同样接受 HORI ID；目前只在 Switch Lite 上测量。
