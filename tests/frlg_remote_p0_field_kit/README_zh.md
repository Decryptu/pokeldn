# FR/LG P0 实机测试包

本目录随 `source/` 中的同版本 PokeLDN 源码和经典 ESP32 合并固件一起分发。包内固件取自官方 PokeLDN `v0.2.2` 发布资产；它与 P0 主机程序分开版本，协议版本兼容性由 ESP32 串口握手和本机测试确认。检查 `BUILD_INFO.txt` 与 `MANIFEST.sha256` 记录的源码提交和文件摘要。

P0 仅把两台真实 Switch 提供的 LinkPlayer、Trainer Card、三组队伍块、mail 和 ribbons 经 LAN 转发到对端，随后停在交易菜单。不得选宝可梦或确认交换。运行结束后，检查两台 Switch 录像、双端日志和命令审计；本包不启用交易、动画或保存功能。

## 硬件与主机

- 两套本地基线已经通过的 PC、经典 ESP32 无线板和零售 Switch。第一轮固定 PC A 为 LAN host、PC B 为 join；两台游戏机都在各自身边选择 Join Group。
- 无线板必须是经典 ESP32。当前 PokeLDN 不支持 ESP32-C3、ESP32-S3 或 ESP32-C6；不要给这些芯片刷本包固件。优先用已完成 FR/LG 本地基线的板型，如 ESP32-D0WD / WROOM-32E。
- PC 使用 Windows x64 和 Python 3.13。双机接入同一可信普通 LAN；TCP 使用 PC A 的明确私有 IP。不要将 24873 端口映射到公网。
- 两台 PC 各自保留本地 `prod.keys`。密钥只用于各自本地 FR/LG 网络发现；LAN 房间密钥仅在同伴之间私下传递。
- 使用专用测试存档，准备身份和队伍明显不同的样本。P0 不选择任何宝可梦。

## 安装与刷写

每台 PC 各解压一份本包，在包目录运行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
```

先核对固件摘要，再按串口刷写经典 ESP32 固件。刷写会覆盖该板现有应用：

```powershell
.\verify-firmware.ps1
.\flash-classic-esp32.ps1 -RadioPort COM5
```

把 `COM5` 改为对应电脑上板子的端口。刷写后重新插拔板子，检查 LED / 串口握手，再分别按测试方案执行两侧的本地 Direct Corner 基线。若设备不是经典 ESP32，停止刷写并记录 `BLOCKED`。

## LAN 启动

PC A 终端：

```powershell
.\start-probe.ps1 -Role host -RadioPort COM5 -LanAddress 192.168.1.10 -Channel 1
```

PC B 终端：

```powershell
.\start-probe.ps1 -Role join -RadioPort COM7 -LanAddress 192.168.1.10 -Channel 6
```

替换串口和地址。host 在前台输出一次 64 位十六进制房间密钥；用可信的私下渠道交给 join。join 启动时以隐藏输入读取。不要用 transcript、录屏或重定向保存包含房间密钥的 host 启动输出。两台 PC 都显示 `LAN pair ready` 后，才启动两台 Switch 的 Join Group。每个重复样本都重启两个进程并使用新的 run ID 和房间密钥。

日志默认在各自 PC 的 `%APPDATA%\pokeldn\remote\<run_id>\events.jsonl`。正常结束后，将两边日志复制到**包目录之外**的测试证据文件夹，避免把真实身份与队伍诊断数据误提交到 Git。

## 阶段延迟测试

`--p0-test-hold-phase` 是显式的本机测试闸门，只阻止指定 peer block 交给本地 Switch；LAN 心跳和 RFU 主循环仍继续。它不模拟断网，不应冒充队列满或取消行为。要使用闸门，启动时同时指定阶段和一个尚不存在的本机释放文件：

```powershell
$release = Join-Path $env:TEMP "frlg-p0-party-1.release"
.\start-probe.ps1 -Role host -RadioPort COM5 -LanAddress 192.168.1.10 -Channel 1 -HoldPhase party_1 -ReleaseFile $release
```

看到本机日志 `P0 test gate holding peer party_1` 后记录两台 Switch 当前画面与时间。结束等待时，在**同一台 PC** 运行：

```powershell
.\release-phase-gate.ps1 -Path $release
```

释放文件必须每次使用一个从未存在的新路径。阶段闸门可能令游戏停在数据等待；设定延迟预算、记录状态并及时释放。不要在等待中选择宝可梦；到达交易菜单仍按两次取消和原生退场流程结束。

## 双端日志核验

把正常取消并关闭后的两个 `events.jsonl` 路径传给核验器：

```powershell
.\check-evidence.ps1 -JournalA "D:\evidence\A\events.jsonl" -JournalB "D:\evidence\B\events.jsonl"
```

它检查 run ID、七阶段顺序和逻辑长度、两向摘要、双快照、正常关闭字段、P0 命令审计，以及日志中没有原始数据块或密钥字段。成功只说明 JSONL 里的可机检条件一致；**仍须人工核对**两台 Switch 的真实身份、六槽队伍、正常取消录像、游戏版本/语言和设备固件。PC 收到数据、LAN ACK、RFU ACK 或菜单提示都不能单独证明 Switch 已消费数据。

离线故障用例运行方式：

```powershell
Set-Location .\source
.\.venv\Scripts\python.exe -m pytest tests/test_frlg_remote_probe.py tests/test_frlg_remote_policy.py tests/test_frlg_remote_field_kit.py -q
```

自动化中队列和 journal 故障以可控夹具注入。实机 LAN 断线只断开 PC 间的 LAN 链路；不要拔 ESP32 USB 来模拟 LAN。不要在真实 Switch 会话上强制填满程序队列或磁盘，也不要把合成日志当成实机结果。

完整步骤、重复次数和结果标准见 [P0 测试执行方案](source/docs/frlg_remote_trade_p0_zh.md)。
