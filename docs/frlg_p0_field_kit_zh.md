---
title: FR/LG P0 实机测试包
parent: FireRed and LeafGreen
nav_order: 9
---

# FR/LG P0 实机测试包

仓库中的 `tests/frlg_remote_p0_field_kit/` 和 `tools/frlg/validate_remote_p0_evidence.py` 是实机测试包的模板和日志核验器。生成的 ZIP 包含本次提交的完整源码、Windows 安装/启动脚本、测试记录表、经典 ESP32 合并固件，以及源码与固件的 SHA-256 清单。

用当前工作区 Python 构建包：

```powershell
.\.venv\Scripts\python.exe scripts/package_frlg_remote_p0_field_kit.py `
  --firmware-dir dist/frlg-p0-field-kit/firmware
```

默认输出为 `dist/frlg-p0-field-kit-<commit>.zip`。固件必须来自官方 PokeLDN `v0.2.2` 发布资产，目录里需要有 `pokeldn-radio.bin` 和原始 `SHA256SUMS`。构建器会比对官方摘要并把包绑定到当前已提交的 Git tree；提交中的未提交文件不会悄悄混入源码包。`dist/` 为生成物目录，不纳入 Git。

## 包内执行

每台 PC 单独解压，在包根目录运行 `setup.ps1`。它按 `source/requirements.txt` 安装 Python 3.13 依赖，并安装固定版本的 pytest 与 esptool。无线板须为经典 ESP32；PokeLDN 不支持 ESP32-C3、ESP32-S3 或 ESP32-C6，刷写前先核对板型并执行 `verify-firmware.ps1`。

每侧可先运行 `flash-classic-esp32.ps1 -RadioPort COM5`，再按原有 FR/LG 本地基线确认板子和 Switch。PC A 运行 `start-probe.ps1 -Role host -RadioPort COM5 -LanAddress <PC-A私有IP>`；PC B 用 `-Role join` 和 PC A 地址。Host 输出的一次性房间密钥只通过双方选择的私下渠道传递；Join 的隐藏输入不会把密钥写入 PowerShell 命令历史。

如需命中指定数据阶段，在单侧命令上附加 `-HoldPhase party_1 -ReleaseFile <该机的新文件路径>`。看到闸门命中日志后，用包内 `release-phase-gate.ps1 -Path <同一路径>` 释放。闸门只停止所选 peer block 的本地交付；LAN 心跳和 RFU 运行保持活动。它不能注入网络丢包或模拟用户菜单取消。队列耗尽和 journal 写入故障通过离线 pytest 夹具覆盖。

完成双端取消、RFU 关闭和日志落盘后，可运行 `check-evidence.ps1 -JournalA <A的events.jsonl> -JournalB <B的events.jsonl>`。核验器检查 run ID、阶段长度与顺序、跨端摘要、双快照、正常关闭字段和 P0 命令计数，并拒绝包含原始数据块或密钥字段的日志。它无法核对视频、画面上的游戏身份或玩家操作；这些仍须人工对照 [P0 测试执行方案](frlg_remote_trade_p0_zh.md) 的记录表。

包内 `record-template.md` 是每次运行的基础记录表。日志、截图、录像与存档状态说明放在仓库以外，并在设备及版本矩阵中标明每个 run ID。
