# FRLG RNG Assist 0.1.0

这是 **零售 Switch + PokeLDN** 方向的第一阶段离线插件。
目前提供自然 RNG 候选搜索、单次校准分析和 PC 端 JSON 记录；不连接游戏、不安装 Hook、不按键、不修改游戏 Seed 或存档。

## 已实现

- FRLG 页面下独立的“离线搜索”和“校准”工具，PokeLDN 公共插件 API 1.8。
- 复用 PokeLDN 的 LCG/Method 1 数学模型，隔离内部接口依赖并做已知向量检查。
- Method 1/2/4 的 PID、性格和 IV 预测；闪光、指定 PID、性格、六项 IV 下限。
- 按 RNG advance 搜索，支持起始 index、上限、结果数量；不输出伪精确的帧倒计时。
- 手填 offset 后给出预测 trigger；未提供则保持为空。目标已过不做 32 位回绕补按。
- 从 HIT + 实际 PID/IV 恢复有限范围内的候选 offset，保留歧义，不自动批准场景。
- PokeLDN 进度条与状态卡；报告保存在插件资料库 `FRLG RNG Assist`，更新插件不覆盖这些记录。

**所有场景均未实机校准。** Mewtwo/三鸟/Snorlax 是记录标签，不能当作已实现的遭遇 profile。
一个 Method 1 数学候选不等于“在此刻按 A 会生成这只宝可梦”。
手填 Seed 是离线输入；不宣称实时同步。TID/SID 请填游戏实际值，不是 PokeLDN 的交易身份。

## 输入约定

- Seed/PID：十六进制，可省略 `0x`；例如 `12345678` 表示 `0x12345678`。
- TID/SID、advance、offset：十进制。
- UI/JSON 的 IV 顺序：**HP / Atk / Def / SpA / SpD / Spe**。
- `--hit-boundary post-vblank` 只用于确认来自原 VBlank handler 返回后采样的数据；默认 `unspecified`。
- `predicted_generation_seed` 位于第一笔 PID Random 调用之前；它不是从 CreateMon 实际采到的值。

## 开发运行与打包

需使用带插件 API 的 PokeLDN。用户原有旧工作分支不因此自动升级。
在 PokeLDN 源码根目录，设置插件源目录的绝对路径后：

```powershell
$env:POKELDN_PLUGINS = 'C:\path\to\frlg_rng_assist'
python -m pokeldn --plugins
python -m pokeldn frlg-rng-assist-search -- --seed 12345678 --tid 50425 --sid 50923 --advances 100000
```

正常插件运行默认保存到其资料库；`--no-save` 仅打印，`--output FILE` 创建指定 JSON 文件且拒绝覆盖旧文件。
指定 PID 筛选时若不要求闪光，添加 `--any-shininess`；默认仍要求闪光，其他条件同时成立才算目标。

```powershell
python scripts/pack_plugin.py 'C:\path\to\frlg_rng_assist' -o frlg-rng-assist-0.1.0.pokeplugin
```

在 PokeLDN 的 Plugins 页安装该包，由用户完成插件安装界面。开发包未签名，不自动安装到当前用户配置。
包不携带任何 ARM Hook 或游戏数据。包内 `LICENSE` 与 PokeLDN 根目录一致，为 GNU AGPL v3；复用的 PokeLDN 代码及模型归其原作者。

## 测试

从要验证的 **PokeLDN 主程序源码根目录** 运行（插件路径可在另一个目录）：

```powershell
python -m pytest 'C:\path\to\frlg_rng_assist\tests' --confcutdir='C:\path\to\frlg_rng_assist\tests' -q
```

测试覆盖数学向量、Method/IV 顺序、单 advance 搜索、PID/性格/IV 组合条件、offset 单位与过期、反查歧义/范围、报告防覆盖、内部 API 异常、真实插件注册/打包、真实主程序子进程启动。
使用缺乏 `pokeldn.plugins` 的旧主程序会跳过集成测试；不能把这种部分通过当作插件兼容验证。

2026-10-22 验证基线：

- 上游 main `af33b4cd257cf960954391e45b65a4eebd5f89cd`（提交标记 0.34.0）：**33 passed**。
- 正式 Release `v0.33.2` / `c1f2b953800834c3387fa5b2fe44cccf1e86cea0`：**33 passed**。
- main 现有 LCG、countdown、resident chain/save 回归：**85 passed, 1 skipped**；跳过项需要本地 `bs15_dump.bin`。

以上是数学与主程序集成验证，没有进行零售 Switch 实机命中验证。

详细设计、最新版差异和 Resident 草稿问题见仓库 `docs/frlg_rng_assist_plugin_plan_zh.md`。

## 后续阶段

运行时只读 Seed Overlay → 具体场景的 20 次 offset 校准 → 独立、限时的一次 A callback shim。
插件不会直接部署上游 `rng-*-hunt`：它们会写回 `gRngValue`；`hunt-log` 还写入游戏存档区域。
不会复用 Game boosts 的“代码太大就改走存档”回退，也不会把 TV 313/314 当作固定推进值。
