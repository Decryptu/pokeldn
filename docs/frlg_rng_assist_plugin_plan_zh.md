# FRLG RNG Assist：插件与运行时方案

复核日期：2026-10-24。目标是零售 FireRed / LeafGreen + PokeLDN，不读取模拟器进程，也不把游戏存档当作插件数据库。

## 当前结论

FRLG RNG Assist 0.2.0 已经是可安装、可离线测试、可按顺序进行实机验证的插件。它把 PC 端的候选搜索/校准和掌机端的只读跟踪/一次性输入分开：

- `search.py`、`calibrate.py` 在 PC 上做 LCG、Method 1/2/4、PID/性格/IV 筛选和校准记录。
- `trace.py` 调用 PokeLDN 已有的 `rng-trace` buffer script，默认只读采集当前构建的 `gRngValue`；只有显式填写 ROM call 才会执行被调函数。
- `install.py` 调用 `install-resident`，把 `rng-assist.s` 安装到易失 EWRAM；它不写存档，也不写 `gRngValue`。
- `state.py` 调用 `memory-dump` 读取 64 B 状态区。
- `arm.py` 调用 `call-chain` 更新 resident 参数；只有显式勾选时才打开一次性 A。

主程序需要同时包含 `asm/resident/rng-assist.s`、生成的 `resident_stubs.py` 和 `buffer_script.py` 的 `rng-assist` 注册。插件包不携带汇编源码，避免和主程序的 Build 地址表脱节；如果 host 报没有 `rng-assist` runtime，应先更新 PokeLDN 主程序。

## 地址与构建

当前只开放已经有完整地址表的构建：

- `BPRE` / `BPRF`：FireRed 英文 / 法文。
- `BPGE` / `BPGF`：LeafGreen 英文 / 法文。

live 工具把构建映射到主机的 `--console-build`、`--expect-console` 和 `--version`。构建必须和实际 ROM 的版本/语言一致。Wireless 1.8.0 不改变插件 API 1.8 的调用方式；关键是主程序的 runtime 版本要和插件要求一致。

## 客体运行时

`rng-assist.s` 是一个独占 VBlank resident hook，不加入旧的 `turbo`/`shiny`/`ivs` 链。每帧先调用原 VBlank，再读取 `gRngValue`，用 LCG 追踪当前 seed 和 advance。状态区默认从 `0x0203FF80` 开始，64 B 布局如下：

| 偏移 | 字段 | 偏移 | 字段 |
| --- | --- | --- | --- |
| 00 | current_seed | 04 | current_index |
| 08 | predicted_generation_seed | 0C | predicted_generation_index |
| 10 | trigger_seed | 14 | trigger_index |
| 18 | hit_seed | 1C | hit_index |
| 20 | hit_frame | 24 | frame_counter |
| 28 | target_pid | 2C | target_nature |
| 30 | candidates_tested | 34 | flags |
| 38 | mode | 3C | display_bottom |

flags 为 `initialized=1`、`pending_a=2`、`fired=4`、`hit_locked=8`、`armed=16`、`target_found=32`、`missed=64`。当前 runtime 不在掌机上重做目标搜索；PID/性格是 host 侧搜索结果写入的记录字段。

当 `auto_a` 非零、跟踪 index 到达 `trigger_index`、offset 不超过 255、进入 VBlank 前 `gMain.intrCheck` 表示主循环空闲，且 `gMain` 仍是普通 overworld callback pair 时，resident 记录 HIT 并暂时接管 callback1。下一次 `ReadKeys` 后，shim 将 A OR 到 `newKeys` 和 `newAndRepeatedKeys`，恢复原 callback1 并只调用一次。若 callback 被游戏替换、下一次 VBlank 已过去，或场景已变化，则清除 pending 并标记 `missed`，不会在迟到的帧补按。软复位会清除整个 resident。

主机和汇编都限制 offset 为 `0..255`，保证 VBlank 预测循环有界。安装和 arm 使用主机的 `--write-unsafe` 开关，但写入范围是本次会话的易失 RAM，不是 SaveBlock 或 Flash。

## 实机闭环

1. 在 Board 页面连接 ESP32，选择正确 build。
2. 运行 `RNG Assist: trace seed`，在掌机选择 **Mystery Gift → Wonder Cards → Friend**；默认只读采样 60 帧，保存 raw dump 和 JSON。
3. 从报告复制测量 seed，运行离线搜索，填写游戏实际 TID/SID。所有 index 都是 LCG advances，不是固定帧数。
4. 用游戏生成的 PID/IV 运行 calibration。单条记录不会把场景标为已验证。
5. 运行 `RNG Assist: install observer`，保持 Auto-A 关闭；再运行 `RNG Assist: read state`，确认 `initialized`、seed 和 index 在变化。
6. 用同一 live session 的 trigger index 和已校准 offset 运行 `configure one-shot A`。先不勾选开关可只更新参数；确认目标和时序后才显式启用。
7. 再读状态，检查 `fired`/`hit_locked` 或 `missed`。在游戏里手动确认实际生成结果，并将新的 PID/IV 写回 calibration。

每个 live 工具都会通过既有 host 传输；没有 radio/console 时会失败或等待，不会伪造 seed、状态或成功结果。trace 的高级 ROM call 默认是 0；只有确认被调函数安全时才使用。

## 已完成和仍需实机验证

已完成：

- 插件 API 注册、打包、library JSON 记录和离线候选搜索。
- ARMv4T resident 生成、入口/原 Handler 链接、64 B 数据区计费、代码/数据碰撞检查。
- 双行 overlay、callback1 shim 期限检查、场景 callback gate、失同步和 offset 上限。
- host 参数解析、trace/state/arm 的 dump 解码和缺少 runtime 时的明确错误。

仍需实机确认：

- 四个构建的 VBlank/overworld callback 地址和 overlay 在真实卡带上的表现。
- 正常地图、Help/link、地图切换、战斗转换时的 pending 取消行为。
- 注入一次 A 后实际 encounter 的 PID/IV 与校准模型是否一致。
- 安装前后 save 内容差分，以及长时间运行对画面、声音和输入的影响。

因此报告继续保留 `profile_verified=false`；`fired` 只表示 shim 确实执行，不自动等价于目标已命中。

## 测试与打包

```powershell
python -m pytest tools/plugins/frlg_rng_assist/tests tests/test_rng_assist_runtime.py --confcutdir=tools/plugins/frlg_rng_assist/tests -q
$env:Path = 'D:\Codex\ch32\EasyMCU_CH32\.tools\bin;' + $env:Path
python scripts/gen_resident_stubs.py --check
python scripts/gen_buffer_scripts.py --check
python scripts/pack_plugin.py tools/plugins/frlg_rng_assist -o "$env:USERPROFILE\Downloads\frlg-rng-assist-0.2.0.pokeplugin"
```

开发包未签名，安装页显示 `Not signed` 是预期的；安装前确认包来自自己的构建目录。插件使用 AGPL v3 许可证，运行记录保存在 `Documents\pokeldn\FRLG RNG Assist`，和游戏存档完全分离。
