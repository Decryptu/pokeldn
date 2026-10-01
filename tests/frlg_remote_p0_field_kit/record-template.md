# FR/LG P0 实机运行记录

## 运行信息

| 字段 | 记录 |
|---|---|
| `test_id` / 用例 / 重复号 | |
| UTC 开始/结束及两 PC 时钟偏差 | |
| 实际入室时差 `Δ` | |
| 源码提交 / 包内 `BUILD_INFO.txt` | |
| PC A/B 操作系统 / Python / PokeLDN 依赖 | |
| PC A/B LAN host/join、地址、端口、信道、桥接名 | |
| ESP32 A/B 芯片/板型/固件 SHA-256/串口 | |
| Switch A/B 系统版本、游戏版本、语言 | |
| 测试存档代号及开始前身份/队伍画面 | |
| 两边共享的 `run_id` | |

## 数据证据

| 检查 | A | B |
|---|---|---|
| 本地版本 / 语言 / child player ID | | |
| `link_player` 本地 / 对端摘要 | | |
| `trainer_card` 本地 / 对端摘要 | | |
| `party_0` 本地 / 对端摘要 | | |
| `party_1` 本地 / 对端摘要 | | |
| `party_2` 本地 / 对端摘要 | | |
| `mail` 本地 / 对端摘要 | | |
| `ribbons` 本地 / 对端摘要 | | |
| local snapshot ID / SHA-256 | | |
| remote snapshot ID / SHA-256 | | |
| 摘要核验器结果 | | |
| 屏幕身份和六槽队伍核对 | | |

## 退场和安全审计

| 检查 | 结果 / 证据时间点 |
|---|---|
| 两侧取消操作次数和屏幕录像 | |
| 两侧 RFU close 确认 | |
| 双端摘要的本机关闭和取消报告 | |
| `START_TRADE` 实际出站计数 / 被拒绝尝试数 | |
| commit / received mon / 动画 / 保存状态计数 | |
| LAN 故障 / journal 故障 | |
| 是否人工终止、重开游戏或改变存档 | |
| 截图、录像、日志文件的本地证据路径 | |

## 结果

状态：`PASS` / `FAIL` / `BLOCKED` / `IN_DOUBT` / `NOT_RUN`

结论范围：

未验证项、异常阶段和后续问题编号：
