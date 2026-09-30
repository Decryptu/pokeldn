---
title: FRLG 局域网数据探针（P0）
parent: FireRed and LeafGreen
nav_order: 8
---

# FRLG 局域网数据探针（P0）

`bin/frlg_remote_trade.py` 是双端远程交换方案的 P0 实验入口。它只转发真实 Switch 提供的 LinkPlayer、Trainer Card、三组队伍块、mail 和 ribbons；到达交易菜单后拒绝交易命令。此版本不会发送 `START_TRADE`，不会启动交换动画、保存或提交。

P0 的自动化协议和引擎检查已覆盖；**尚未完成两台零售 Switch 的实测**。游戏角色映射和不同入室时差仍是待验证门槛，不能据此宣称远程交换已可用。

## 运行准备

- 两套独立、已通过本地 FR/LG Direct Corner 基线的 PC + ESP32 + Switch。
- 两台 PC 位于可信的普通局域网，知道 PC A 的明确私有 IP。两边不自动扫描、改防火墙或做 NAT 穿透。
- 每台 PC 各自保留本机 `prod.keys`。房间口令和 Nintendo 密钥不发送给对端。
- 首次探针选已解锁 Direct Corner 的目标游戏/语言组合。仅观察数据和取消；不要选择要交换的宝可梦。

先分别启动两台 PC。PC A 会显示一次 256 位房间密钥；用可信的私下渠道交给 PC B。PC B 在隐藏输入提示中填入 64 位十六进制密钥。两台 PC 都显示配对完成后，再让两台 Switch 各自选择 Join Group。

```powershell
# PC A：把地址换成 PC A 的私有 LAN IPv4；COM 口与信道按本机设备设置。
$env:POKELDN_RADIO = "esp32:COM5"
python bin/frlg_remote_trade.py host --listen 192.168.1.10 --port 24873 --channel 1

# PC B：启动后在隐藏输入提示中粘贴收到的 64 位密钥。
$env:POKELDN_RADIO = "esp32:COM7"
python bin/frlg_remote_trade.py join --connect 192.168.1.10 --port 24873 --channel 6
```

两边进入 Direct Corner 后，确认真实对端身份和队伍都已显示，然后在各自 Switch 上选择取消并正常退场。探针拒绝 `READY_TO_TRADE` / `INIT_BLOCK`，在引擎层也对 `START_TRADE` 和 `_commit()` 加了不可绕过的保护。不要把本地游戏提示误读成已完成交易。

端口默认为 `24873`，可以显式改成相同的其他端口。`--listen` 和 `--connect` 接受私有、链路本地或回环 IP；绑定指定接口，不监听通配地址。回环仅便于同机协议检查，不能代替双机 LAN 实测。当前 HMAC 提供认证和完整性，不加密业务数据，因此只在可信局域网运行。

## 探针边界与数据

- TCP worker 只发有长度上限、HMAC 认证的 JSON 业务消息；不会转发无线帧、Pia 包、RFU 行、ACK 或按键序列。
- 每个数据块按明确阶段校验长度。LinkPlayer 保留原始 200 字节传输缓冲；发到本地 Switch 前仅把记录中的 `player_id` 改为 parent `0`，其他字节原样保留。这是 G0-A 的待测假设。
- 队伍按 200 字节块逐块交叉发送，随后发送真实 mail（220 字节）和 ribbons（40 字节）。没有 `.pk3` 输入、预载队伍、空 mail 或零 ribbons 替代。
- 双端报告各自本地快照 ID / SHA-256。摘要只绑定字节并帮助诊断，不证明对端 PC 可信或 Switch 已保存。
- 默认事件日志在 `%APPDATA%\pokeldn\remote\<run_id>\events.jsonl`（或 `POKELDN_DATA` 指向目录）。日志只含阶段、长度、错误分类和摘要，不含数据块、房间密钥或 Pokémon 原始记录。
- 配对完成后若 LAN 断开，LAN worker 报告故障，主线程继续维持本地 RFU/Pia 循环；不要自动重启旧无线交易会话。若本地游戏仍卡在数据阶段，保留现场和日志，记录失败阶段。

## 自动化覆盖与实机待办

自动化检查覆盖帧边界/半包粘包、HMAC、JSON 重复字段、配对挑战与方向序号、阶段长度与顺序、快照门控、LinkPlayer 字节保留，以及 P0 禁止开始交易。现有本地主机回归需要另行运行。

实机 P0 必须记录准确游戏版本、语言、固件、提交号和关联 run ID，并回答方案中的 G0-A / G0-B 问题：角色字段是否正确、逐块数据是否无死锁、晚入室等待上限、是否可以正常取消退场。当前支持矩阵仍为“未验证”；这份探针实现不代表已通过任何双实机测试。
