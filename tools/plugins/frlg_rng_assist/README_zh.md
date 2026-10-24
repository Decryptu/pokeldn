# FRLG RNG Assist 0.2.0

这是一个给零售 FireRed / LeafGreen 使用的 PokeLDN 插件。现在已经有一条可测试的闭环：

1. 用主机的只读 `rng-trace` 采集游戏当前的 `gRngValue`。
2. 用插件的离线 LCG/Method 1/2/4 模型搜索目标 PID、性格和 IV。
3. 用实机的 PID/IV 样本做 offset 校准。
4. 在易失 RAM 安装 resident observer，持续记录 seed、RNG advance、触发点和状态。
5. 需要时把 trigger index、offset、PID 和性格写入 resident 参数，并显式选择是否启用一次性 A。
6. 再读一次状态确认 `fired` / `hit_locked` / `missed`，然后在游戏里手动检查结果。

安装 observer 和配置参数会改写掌机的易失 RAM、VBlank 链和一次性回调；软复位后消失。插件不写存档、不写 `gRngValue`，也不持续模拟手柄。Auto-A 默认关闭，只有勾选“Enable one-shot A”才会启用一次尝试；运行时还会要求触发前的 `gMain.intrCheck` 表示主循环空闲，避免在 lag 帧接管输入。

## 使用步骤

先在 Board 页面连接 ESP32，确认 PokeLDN 主机使用当前版本的 FRLG runtime，并选择正确的游戏构建：

- `BPRE` / `BPRF`：FireRed 英文 / 法文。
- `BPGE` / `BPGF`：LeafGreen 英文 / 法文。

主机要求的游戏路径一直是 **Mystery Gift → Wonder Cards → Friend**。每个 live 工具都会提示这一点。

### 1. 采集 seed

运行 **RNG Assist: trace seed**，默认采样 60 帧。默认模式只读 `gRngValue`，并保存 `.trace.bin` 和 `.trace.bin.json` 到 `Documents\pokeldn\FRLG RNG Assist`（也可以在 Capture/report path 中指定路径）。报告里的 `samples` 每项是 `before -> after`。高级的 `Trace ROM call` 保持为 `0`；填入 `Random` 等地址会执行 ROM 并可能推进 `gRngValue`，用于验证 LCG 连续性时必须把这次推进计入校准。

### 2. 搜索离线目标

从 trace 报告复制一个测量到的 seed，填入 **RNG Assist: offline search**，并填写游戏实际的 TID/SID。TID/SID 不是 PokeLDN 的联机身份。搜索结果的 index 单位是 LCG advance，不是 VBlank 帧；没有经过实机 offset 校准时，不要把它当作按键倒计时。

### 3. 做实机校准

用游戏里实际生成的宝可梦填写 **RNG Assist: calibration** 的 HIT seed、PID 和六项 IV（顺序 HP / Atk / Def / SpA / SpD / Spe）。可以保存多条记录；单条记录不会自动把遭遇 profile 标为已验证。

### 4. 安装 observer

运行 **RNG Assist: install observer**，保持 **Enable one-shot A** 关闭。安装完成后马上运行 **RNG Assist: read state**，确认 `initialized`、`current_seed` 和 `current_index` 在变化。状态地址默认 `0x0203FF80`，这是易失 EWRAM；如果你手动改过安装地址，读取时必须填写同一个地址。

### 5. 配置一次性 A

用离线搜索结果和已经校准的 offset 填写 **RNG Assist: configure one-shot A**：

- `Trigger index`：observer 当前 RNG epoch 中的触发 advance。
- `Trigger offset`：从触发 RNG 到目标生成的已校准 advance，范围 `0..255`。
- `Target PID` / `Target nature`：写入状态供记录和核对；resident 本身不会在掌机上搜索目标。

先不勾选 Enable one-shot A 可以只更新参数；确认所有值来自同一会话后再勾选并运行一次。运行结束后读状态：`fired` + `hit_locked` 表示 shim 已经执行；`missed` 表示场景、回调或时序不再匹配，插件不会在晚到的帧补按 A。

一次性回调只在正常 overworld callback pair 仍然存在、且请求只等待一个主循环窗口时执行。切换地图、重置或游戏重新播种都会使旧请求失效。实际命中仍须在游戏中检查，并把新的 PID/IV 记录回来做校准。

## 安全边界和固件

插件不会自动按键，也不会写存档；`install observer` 和 `configure one-shot A` 的 RAM 写入由主机的 `--write-unsafe` 保护，但它们只覆盖本次运行的易失地址。Wireless 1.8.0 与本插件 API 1.8 的工具调用兼容；关键是 PokeLDN 主机源码也要包含 `rng-assist` resident runtime 和生成的 `resident_stubs.py`。如果插件能安装但主机报 “no rng-assist resident runtime”，更新 PokeLDN 主程序后再试。

FireRed / LeafGreen 的 ROM 构建、语言和地址必须匹配。插件不把 Mewtwo、三鸟或 Snorlax 标签当作已经验证的 timing profile；它们只是报告分类。

## 开发、测试和打包

从 PokeLDN 源码根目录运行：

```powershell
python -m pytest tools/plugins/frlg_rng_assist/tests --confcutdir=tools/plugins/frlg_rng_assist/tests -q
$env:Path = 'D:\Codex\ch32\EasyMCU_CH32\.tools\bin;' + $env:Path
python scripts/gen_resident_stubs.py --check
python scripts/pack_plugin.py tools/plugins/frlg_rng_assist -o "$env:USERPROFILE\Downloads\frlg-rng-assist-0.2.0.pokeplugin"
```

插件包不带 `.s` 源码；runtime 由 PokeLDN 主程序提供。开发包未签名，安装页显示“Not signed”是预期的，安装前应确认包来自自己的构建目录。

离线工具可以在没有掌机时测试。live 工具在没有 radio/console 时会停在 host session，不会伪造 seed 或报告成功。
