# FRLG RNG Assist：最新版复核与独立插件方案

复核日期：2026-10-22。目标始终是 **零售 Switch + PokeLDN**；PC 模拟器进程读写不在本方案范围内。

## 1. 版本基线：不要混用 main 和已发布版本

本次实际执行了 `git ls-remote`、`git fetch origin main`，并查询 GitHub Releases：

| 对象 | 核实结果 |
| --- | --- |
| 上游 | `Decryptu/pokeldn` |
| 最新 main | `af33b4cd257cf960954391e45b65a4eebd5f89cd`，提交标题 `Release 0.34.0` |
| main 提交时间 | 2026-10-22 16:22:25，Asia/Shanghai |
| 查询时最新已发布 Release | `v0.33.2`，发布于 2026-10-20 17:57:12，Asia/Shanghai |
| v0.33.2 提交 | `c1f2b953800834c3387fa5b2fe44cccf1e86cea0` |
| 用户本地工作分支 | `codex/frlg-remote-trade-p0`；本次开始时 HEAD 为 `ce9af7d` |
| 最新插件 API | 1.9；本插件只要求公共 API 1.8 |

因此，`main` 已标记 0.34.0 **不等于**查询时已存在 0.34.0 的正式 Release。
本次在临时导出的源码快照中检查最新版本，没有把上游整体合并进用户的远程交易开发分支。

源码依据均以以上提交为准，可在 GitHub 对应提交下检查：

- `docs/plugins.md`、`pokeldn/plugins.py`、`pokeldn/app/plugin_store.py`、`scripts/pack_plugin.py`。
- `docs/frlg_rng.md`、`pokeldn/frlg/rom/lcg.py`、`rng_countdown.py`、`native_script.py`。
- `asm/install-resident.s`、`asm/resident/{shiny,turbo,ivs}.s`、`overlay.inc`。
- `pokeldn/frlg/rom/buffer_script.py`、`builds.py`、`pokeldn/frlg/gift/builder.py`。
- FRLG 反编译参考：`pret/pokefirered/src/main.c` 的 `ReadKeys`、`CallCallbacks`、`VBlankIntr`、`WaitForVBlank`；零售构建地址仍由 PokeLDN 的 Build 表提供。

## 2. 结论与必须修正的认识

独立插件方向成立。插件负责 PC 上的预测、记录、展示和以后对部署流程的编排；常驻 Hook 负责客体侧采样和最终输入时序。
插件机制本身不赋予实时读取零售 Switch RAM 的能力，也不会让一次运行时安装跨越软复位或完全退出游戏。

**现有 RNG 工具不是统一的“只读自然推进”工具集。**

| 现有能力 | 真实行为 | 本插件处理 |
| --- | --- | --- |
| `lcg.step/advance/distance/draws/recover_wild_state` | PC 上的数学计算 | 通过单一兼容层复用 |
| `rng_countdown._mon_from` | 给定状态的 Method 1 预测 | 复用；隔离其私有 API 依赖 |
| `rng_countdown.scan` | 按固定 `2 advances/frame` 扫描 | 不直接用作通用调度器；按单个 advance 搜索 |
| `rng-seed-reader` | NPC/RAM script 读取并显示一次 Seed | 可参考读取方法；不是持续 PC 遥测，而且该交付方式会占用 RAM script/礼物内容 |
| `rng-rate-probe` | 指定实验流程内测量推进速率 | 只作场景校准证据，不能推广为全游戏恒定速率 |
| `rng-shiny-hunt` / `rng-mon-hunt` / `far` / `both` | 搜索命中后写回 `gRngValue`，再由脚本生成遭遇 | 不调用、不直接部署、不照搬其写回尾部 |
| `rng-mon-hunt-log` | 除搜索写 Seed 外，还将日志写进 SaveBlock1 的备用区域，存档后可持久化 | 禁止用于本插件的运行日志 |
| resident `shiny.s` | 持续跟踪、预测与显示；还包含慢速等待逻辑 | 参考跟踪/预测；不能把慢速时序当作自然等待的校准结果 |

优先复用的应是 **数学函数、PID/IV 顺序、现有测试与传输协议**，不是不加区分地调用所有名字包含 `rng` 的功能。
指定 PID 是查找自然序列中的候选条件，不是强制写入 PID。

## 3. 最新版相对旧方案的实质变化

### 3.1 容量没有扩大，存档路径却更容易走通

从当前生成文件读取的真实大小：

- `install-resident`：148 B。
- `shiny`：868 B；单次安装合计 1016 / 1024 B。
- `turbo`：696 B；`turbo-lite`：356 B。
- Resident 默认区域仍为 `0x0203FC00..0x02040000`。

独立 `rng-assist.s` 仍正确。V1 目标约 700～800 B 是预算目标，**不是已经证明搜索、shim、显示全部能装下**。
每次产出必须检查 `148 + code_size <= 1024`，以及代码、状态、保留的原 Handler 指针互不覆盖。

最新版持久化格式已经变为 `PKR2`：16 B 头 + Hook + 4 B checksum，通过 `install-kept` 安装。
`save-head.s` 不再是该路径；`build_resident_save_session()` 可拆成多次写入。当前 `shiny` 的 save blob 为 888 B。
所以“原来的 shiny 太大，写存档自然失败”已经不成立。

此外 `gift.builder.Boosts.built()` 对超出单次 receive buffer 的组合会自动令 `keep=True`。
**RNG Assist 不能复用这种自动存档回退。超限就构建失败，不得悄悄改走 save-write。**

### 3.2 增加了 Hook 链，RNG Assist V1 必须独占

最新版支持 `turbo+noencounter` 等 Hook 链，集中在 `chain_names()`、`_chain_blob()`、`CHAIN_DATA` 和 `_check_resident_layout()`。
RNG Assist V1 不加入 `CHAIN_ORDER`。与 turbo、慢速等待、follower、noclip 等组合的输入/RNG/显示影响未校准，应明确拒绝。
连接链时 `p_original` 不一定直接是原版 VBlank，不能据此声称“只运行了一次原版流程”。

### 3.3 Build 表不再只有四个版本

最新版包含英、法、德、意、西、日的火红/叶绿，共 12 个 game code；日版还有不同的 EWRAM 地址。
`Build.hook_literals()` **已经包含** `cb1_overworld`，无需再重复添加。
后续硬件适配应复用 `builds.resolve()` 和 `build.ewram`，特别是 `overlay_pal`、队伍、帮助系统等字段。
本插件 0.1.0 的四种选择只用于离线记录：BPRE/BPGE/BPRF/BPGF，不表示四种 ROM 的新 Hook 均已实机验证。

### 3.4 “双行”不等于两行八位

现有 `overlay.inc` 的第一行是 8 位 HEX；`OVERLAY_TWO_ROWS` 的第二行循环只有 **6 位，取 word 的高 24 位**。
直接把 `display_bottom=0x00000127` 接到它，只会显示 `000001`，不能显示预期的 `00000127`。

需为新 Hook 编译一个第二行 8 位的变体，使用 OAM 112..119；现有 IV Hook 保持 6 位布局。
不要通过修改共享 include 的默认值而悄悄改变已有 Hook。

## 4. Auto-A：保留 shim，但必须补足时序约束

保留用户提出的核心顺序：

```text
WaitForVBlank
  → Resident：读取进入中断前的 intrCheck
  → 原始 VBlankIntr 正常执行一次
  → 采样 gRngValue，确认 trigger
  → 记录 HIT、预约 callback1 shim
下一轮 ReadKeys
  → callback1 shim：OR A，恢复 callback1，tail-call 原 CB1
  → 正常主循环决定并执行 CB2
```

要补充以下规则：

1. **只在中断进入前 `intrCheck & 1 == 0` 的空闲帧预约。** 否则中断可能插在主循环 callback 中间，预约不再保证对应下一轮输入。
2. **原 VBlank 前后不能混用 Seed 边界。** VBlankIntr 自身调用 `Random()`；固定 HIT 为原 Handler 返回后的采样。后续校准记录必须标明同一边界。
3. **PENDING_A 只允许下一次预定的正常回调消费。** 主循环可能因 Help、保存失败界面或 link 状态而跳过 callback。若下一 VBlank 已到，或回调/场景已改变，应取消预约，记 `MISSED/CANCELLED`；不得几帧后补按。
4. **Shim 再检查 callback2、Pending 状态和预约期限。** 只在仍拥有 callback1 时恢复该指针；不要覆盖后来由游戏设置的新 callback。
5. **V1 限定 callback1=CB1_Overworld、callback2=CB2_Overworld。** 不支持任意回调，故可从 Build 常量恢复，不把保存指针塞入 `mode` 或 Seed 字段。
6. **使用 `newKeys |= A` 和 `newAndRepeatedKeys |= A`。** 不清除玩家真实输入；默认不改 heldKeys。是否允许并存方向/菜单键，要由场景 gate 确定。
7. **真正 tail-call 原 CB1。** ARM7TDMI/ARMv4T 不支持草稿中的 Thumb `blx r3`；应在恢复寄存器/LR 后 `bx` 到原回调，不能重复跑 CB2。
8. **一次预约和一次生效分开记。** HIT 是触发观测，不是“实际 CreateMon 入口采样”，`FIRED` 只在 shim 确实注入后设置。
9. **失同步不自动重新 ARM，不清除已锁定 HIT。** 从战斗回到地图时的失同步不能造成第二次意外 A。重置、取消和重新 ARM 必须是明确操作。
10. **计算量也会影响时序。** 即使不写 Seed，搜索拖长中断仍可能造成额外 VBlank/lag；必须测量执行预算。不能把“无额外 callback”写成“绝对不扰动时序”。

禁止链中加速；遇到已越过 trigger 的目标，标记错过并寻找后续目标。不能因为某场景测到每帧 2 advances 就认为所有候选状态都能成为可触发的帧边界。
静止地图的相位/奇偶、Help、脚本等待、Quest Log、fade、TV 与战斗转换都属于现场验证范围。

## 5. 内存布局与输入定义

保留已经定下的 **64 B 对外状态结构**：

| Offset | 字段 | Offset | 字段 |
| --- | --- | --- | --- |
| 00 | current_seed | 04 | current_index |
| 08 | predicted_generation_seed | 0C | predicted_generation_index |
| 10 | trigger_seed | 14 | trigger_index |
| 18 | hit_seed | 1C | hit_index |
| 20 | hit_frame | 24 | frame_counter |
| 28 | target_pid | 2C | target_nature |
| 30 | candidates_tested | 34 | flags |
| 38 | mode | 3C | display_bottom |

默认 state=`0x0203FF80`，占用 `[0x0203FF80, 0x0203FFC0)`。
推荐使用独立符号 `p_rng_state:64`，不要沿用会被通用校验器按 36 B 计费的 `p_state`。

该结构没有持久搜索游标。进入搜索阶段时需明确另分配 `search_seed/search_index` 的 8 B，不能每帧从 current_seed 重扫。
如果还要求 HIT 后顶行冻结而 current_seed 继续实时更新，再加 `display_top` 4 B。
一种可检查的布局是把 12 B scratch 放在 `0x0203FFC0..0x0203FFCC`，保持原 64 B ABI 不变；完整实际占用是 **76 B**，不是还声称只有 64 B。

纯观测阶段可以直接 `p_overlay=state+0x00`；需要冻结显示时改为独立显示缓存，不冻结实时追踪字段。
初始化必须完整清零运行态，区分重装与失同步，确认首次读取不依赖该区域碰巧全零。

Offset 的唯一单位是 RNG advances：

```text
predicted_generation_seed = advance(trigger_seed, calibrated_offset)
predicted_generation_index - trigger_index = calibrated_offset
```

Generation 边界定义为“该预测模型第一笔 PID draw 之前”。草丛的 nature/slot/rejection、御三家或钓鱼不能未经建模套用它。
LCG 在 32 位空间是全周期，任意两状态都有 distance；只有合理范围、正确 PID/IV 模型和一致场景下的距离才有校准意义。

## 6. 插件架构与复用边界

代码放在 `tools/plugins/frlg_rng_assist/`；可以独立打包，不修改主程序 catalog、registry 或全局 STUBS。

```text
plugin.toml / plugin.py             公共 API 注册两个 FRLG 工具
search.py                          离线目标搜索入口；build_parser 无副作用
calibrate.py                       单次 HIT/PID/IV 校准记录入口
frlg_rng_assist_core/compat.py      唯一依赖 PokeLDN 内部 RNG 模块的边界
frlg_rng_assist_core/model.py       候选、筛选、校准；单位只有 advances
frlg_rng_assist_core/reporting.py   公共 progress/panel/library API
tests/                             数学、IV顺序、兼容、真实加载/打包/子进程测试
```

公共插件 API 可承诺兼容；`pokeldn.frlg.rom.*` 并不是文档列出的稳定 API。
0.1.0 采用单一兼容层 + 确定性向量自检 + 对正式 Release/固定 main 提交的集成测试，遇到接口变化停止计算并报告。
不在插件内重新实现一套 LCG，也不声称运行自检能代替所有未来版本回归测试。

数据持久化仅指 **电脑的插件资料库 JSON**。该记录与游戏 SaveBlock/存档完全不同。
TID/SID 必须来自本次游戏，不自动代入 PokeLDN 的交易训练家设置；Seed/PID 用 HEX，计数与 IDs 用十进制。
界面六项 IV 使用 `HP/Atk/Def/SpA/SpD/Spe`，适配层显式转换上游存储顺序 `HP/Atk/Def/Spe/SpA/SpD`。

### 实时同步的实际边界

当前工具没有“零售 Switch 任意 RAM 连续读取”的公共 PC API。`rng-seed-reader` 的游戏内显示、一次 Console Code 执行、插件的进度条是三种不同能力，不能拼接成一个不存在的 `read_seed_live()`。

最小可行实机路线是 **客体闭环**：PC 配置条件和校准参数 → 运行时安装 Hook → Hook 读取实际 Seed、搜索、跟踪并在游戏内显示 → 经验证后由同一 Hook 完成一次 A。PC 不参与逐帧按键定时，手工抄回/导入的读数仍标记为离线样本。

如果以后要让 PC 也实时显示，必须另行证明从正在运行的游戏向 PC 返回带 session/sequence 的样本通路，并定义样本过期与断线处理。没有这条通路时，PC 可以展示离线预测和历史记录，不能显示“实时剩余 127 advances”。Teachy TV 后也必须由客体重新读取实际状态；PC 收不到新样本就保持未同步。

## 7. 分阶段交付与验收

### 阶段 A：本次 0.1.0 插件骨架

- 可安装的插件布局，FRLG 下提供离线搜索和校准两个工具。
- 手动 Seed/TID/SID，Method 1/2/4；闪光、性格、指定 PID、六项 IV 下限组合筛选。
- 每个 advance 都可搜索，不把 2 advances/frame 固化为调度规则。
- 可选手填已测 offset，仅给出 predicted trigger；没有 offset 则不产生触发时机。
- 按 PID/IV 反查候选 pre-PID 状态，限制 offset 范围，保留无匹配/歧义，不自动挑一个。
- 进度条、结果卡片、JSON 记录；卡片始终显示离线，`profile_verified=false`、`auto_a_available=false`。
- 超梦、三鸟、卡比兽只是记录标签；不意味着每个真实遭遇已经有可靠决定点。

### 阶段 B：运行时观测与静态遭遇校准

1. 重做并审计 `rng-assist.s` 基础，先只有 Seed/index/双行 Overlay。
2. 插件携带经 ARMv4T 构建、带 hash 和 Build 清单的预编译资源；终端用户无需 assembler。
3. 调查最新公共 `frlg.gift.builder` 的 Console Code/预构建 binary 路径与 CLI，构造 **仅 RAM** 的独立安装交付，不加入 Game boosts，不做存档回退。
4. 仅允许已验证 ROM/语言；校验安装 image、状态区、原 Handler、入口 Thumb bit 与数据初始化。
5. Mystery Gift/link 菜单下的采样视为一次 session 数据；回到标题可能 reseed，旧 live session 必须失效。
6. PC 无连续样本时显示离线/失同步；Teachy TV 的 313/314 不作为固定推进常数。后续由客体读取实际 Seed，同步后再计算剩余距离。
7. 分遭遇、最终对话状态、采样边界、ROM、输入方式收集至少 20 组一致校准；19/20 不能直接宣布稳定。

插件禁用或退出不会自动抹掉已安装的客体 Hook；在可靠的运行时卸载路径完成前，应明确通过软复位停止它。
严格的“不留存档”承诺需做安装前后内容差分。不能把所有 Mystery Gift 交付都一概视为无存档改动。

### 阶段 C：客体搜索与一次性 Auto-A

- 先实现一个经过校准的静态/对话场景；预算控制、游标、目标过期和可触发边界均在客体侧处理。
- 保留 `RESET → TRACKING → TARGET_FOUND → ARMED → TRIGGER_REACHED → PENDING_A → FIRED → HIT_LOCKED`，增加 `MISSED/CANCELLED/DESYNC` 退出分支。
- 只允许有效预约在正常 `ReadKeys` 后生效一次；不运行额外回调，不写 Seed、TID/SID、PID、IV。
- 顶行可显示锁定 HIT，底行显示 hit_frame；实际 generation 必须由结果恢复验证。
- 减速、TV、大范围搜索和个体筛选是后续能力，各自重新校准，不自动继承旧 offset。

### 必须补齐的 Hook 行为测试

- ARMv4T 编译、generated stub 一致、容量与全部数据区碰撞检查。
- 模拟原 VBlank 的 Random 消费后再采样；0/1/63/64/65 advances 的跟踪边界。
- ReadKeys 覆盖后 shim OR A；CB1 一次、CB2 由主循环执行、原输入保留。
- lag 帧、Help/link 吞 callback、回调切换、超期预约、取消/重装、soft reset。
- 已 FIRED 后 reseed/战斗大跳仍保持 HIT，不能再次自动按 A。
- 内存写监视禁止触碰 gRngValue、TID/SID、队伍与 save 区域。
- 所有入口拒绝存档持久化及与其他 Hook 组成链；超限绝不回退 save-write。
- 实机检查 Overlay 帧延迟、音乐/画面稳定性、callback 期限和生成结果；Unicorn 不代替零售实机验证。

## 8. 上次遗留汇编草稿审查

本地未跟踪的 `asm/resident/rng-assist.s` 是上次中断前的草稿，不在最新版上游，也未注册进本地 builder。
本次保留原文件用于定位问题，不将它包含进插件包或作为可运行 Hook 发布。

主要问题：

1. 使用 `blx r3`，不符合构建器规定的 ARMv4T；实际写法也不是用户要求的 tail-call。
2. `ldr r5, p_offset` 后又 `ldr r5, [r5]`，错误地把数值 offset 当地址解引用。
3. 未设置 `OVERLAY_TWO_ROWS`，有 `p_overlay2` 也不会绘制第二行；即便开启仍有上述六位限制。
4. 没有进入前 intrCheck 门控、pending 期限或 shim 的完整复核。
5. 失同步时清空 FIRED/HIT，可能导致后续重复触发；也没有完整初始化与重装策略。
6. 64 次跟踪循环在执行第 64 步之后未再比较，实际只能匹配 0..63 步。
7. 名为 `p_state` 的 64 B 布局仍会被旧/通用元数据当成 36 B；注册表、生成文件和专门测试均未接入。
8. 顶行依然显示 current_seed、底行显示 current_index，不是承诺的冻结 HIT/Remaining；也没有闪光搜索器。

这些是待修复的实现缺口，不能用“框架已验证”描述。当前能够交付和验证的是离线插件，不是自动闪光实机成品。

## 9. 本次验证记录

测试在独立导出的上游源码环境中运行：

| 验证 | 结果 |
| --- | --- |
| 插件对 main `af33b4c`：数学、注册、打包、CLI 启动 | 33 passed |
| 插件对正式版 `v0.33.2` / `c1f2b95` | 33 passed |
| main 原有 LCG、countdown、resident chain/save 回归 | 85 passed, 1 skipped |

跳过项需要本地 `bs15_dump.bin`。执行方法见插件目录的 `README_zh.md`。
安装包由 main 的官方 `scripts/pack_plugin.py` 生成，包含同上游一致的 AGPL v3 许可证；未包含汇编草稿。
未改动用户其他远程交易文件，未连接或修改任何游戏。数学与加载测试通过，不代表零售实机决定点已经验证。
