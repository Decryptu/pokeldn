<a id="raspberry-pi-4-mystery-gift-host"></a>
# Raspberry Pi 4 神秘礼物主机

配备 TP-Link Archer T3U / AC1300（`2357:012d`、`rtw88_8822bu`）的 64 位 Raspberry Pi 4 承载神秘礼物。修补后的LDN实现是`vendor/LDN`；切勿在 Pi 上安装未打补丁的 PyPI 包。适配器的内核设置位于[Adapters](hardware_adapters.md)中。

部署通过 SSH 别名将提交的 Git 对象推送到 Pi 上的裸存储库，没有 GitHub，没有 `rsync`，也没有被忽略的文件（参考存储库、`.venv`、捕获、宝可梦文件、切换密钥）。
<a id="first-deployment"></a>
## 第一次部署

在桌面上，使用 SSH 别名和 Pi 登录用户：

```bash
git add -A
git commit -m "Prepare Raspberry Pi deployment"
./scripts/deploy_pi.sh --host pi-ldn --user PI_USER
```

`deploy_pi.sh` 拒绝脏桌面签出，运行配置和文档测试，根据需要创建 `/home/PI_USER/repos/pokeldn.git`，将当前提交推送到其 `deploy` 分支，并创建或快进 `/home/PI_USER/pokeldn`。它永远不会强制重置并拒绝未提交文件的 Pi 签出。如果 SSH 别名已命名远程用户，请提供路径：

```bash
./scripts/deploy_pi.sh --host pi-ldn \
  --path /home/PI_USER/pokeldn \
  --repo /home/PI_USER/repos/pokeldn.git
```
 然后引导 Pi：

```bash
ssh pi-ldn
cd ~/pokeldn
./scripts/setup_pi.sh
```

`setup_pi.sh` 需要 64 位 Raspberry Pi 操作系统 (`aarch64`) 和 Python 3.11 或更高版本（Bookworm 3.11、Trixie 3.13）。它从 `requirements.txt` 构建虚拟环境，安装系统工具（`--no-apt` 跳过它们）并从 NetworkManager 中排除 `ldnclient`、`ldn`、`ldn-mon` 和 `ldn-tap` （`--no-networkmanager` 跳过它）。将 SSH 保留在以太网或内置 Wi-Fi 上：托管仅使用 TP-Link 适配器。
<a id="configuration-and-switch-keys"></a>
## 配置和切换键

跟踪的 `config/host.toml` 是 TP-Link 实时配置文件：

```toml
[host]
live = true
skip_encryption = true
accept_decrypted_ccmp = true

[ldn]
phy = "auto"
```
 被忽略的`config/host.local.toml`持有绝对关键路径（主机运行在`sudo`下）；如何安装`prod.keys`在[树莓派上的开关按键](hardware_switch_keys.md)中。
<a id="verify-and-run"></a>
## 验证并运行

插入 TP-Link 适配器后：

```bash
cd ~/pokeldn
./scripts/preflight_pi.sh
./scripts/run_mystery_gift.sh
```
 预检是只读的。它检查Python和供应商的LDN包，加载`config/host.toml`和可选的`config/host.local.toml`，检查TP-Link USB id和`rtw88_8822bu`、AP和显示器支持、NetworkManager排除以及密钥文件是否为模式`0600`。它拒绝禁用 `skip_encryption` 或 `accept_decrypted_ccmp` 的 TP-Link 调用，参数通过
包括 `run_mystery_gift.sh`。它本身添加了 Debian 的 `sbin` 路径，因此它在 shell 中和通过一行 SSH 命令的行为相同。

`run_mystery_gift.sh` 运行预检一次，然后监督短期根主机进程，每个进程都有一个随机 TID/SID，在交付、尝试失败或五分钟没有交换机加入或 Pia/RFU 流量后重新启动。 Ctrl-C 一旦停止它。它始终通过 `--end-on-success`（在交付后关闭后结束）和 `--idle-timeout 300`（在没有 Switch 流量的几秒后结束）并拥有 `--id`，因此保存的 `--id` 无法重复使用旧身份。转发所有其他 `bin/frlg_mg_host.py` 选项； `--help` 和 `--print-effective-config` 不需要预检，也不需要 root。

每个加入的尝试都会附加到被忽略的每日分类账 `logs/mystery-gift-attempts-YYYY-MM-DD.csv` 中，其中包含 `attempt`、`received_result`（仅当发送了神奇或图章时才使用 `true`）、`time`、
`trainer_name`、`trainer_ot`（来自 Switch LinkPlayer 块的名称和五位训练家 ID，如果之前尝试失败则为空）。 `bin/frlg_mg_host.py --attempt-log-dir logs` 写入相同的账本。

事件控件：`--gift`、`--flag-id`、`--verbose`、`--capture`、`--ot`、`--version`、`--id`。
`--client-ready-idle-frames N`是硬件测试的时序诊断；否则请保持未设置状态。
`--make-artifact` 在 `artifacts/` 下写入确定性 `.ram.lst` 列表（`--artifact-dir DIR` 重定向它）：编译的 RAM 脚本字节、解码的指令、校验和、分支和消息目的地以及传递阶段摘要； `--no-make-artifact` 在保存的命令中禁用它。

```bash
./scripts/run_mystery_gift.sh --gift solrock-stamp --client-ready-idle-frames 45 \
  --capture solrock-45.jsonl
./scripts/run_mystery_gift.sh --gift worlds-xp --make-artifact
```
 将 `--phy`、`--adapter`、`--skip-encryption` 和 `--accept-decrypted-ccmp` 保留为 TP-Link 默认值，除非诊断其他硬件。对于 ALFA `mt76x0u`，传递其当前 PHY（`iw dev`；重新插入后会更改）和 `--no-accept-decrypted-ccmp`；然后 preflight 检查 PHY 的 AP 和监控模式以及 `mt76x0u` CCMP 配置文件。
<a id="mt7601u-adapter-with-the-custom-ap-driver"></a>
### 带有自定义 AP 驱动程序的 MT7601U 适配器

库存 `mt7601u` 驱动程序没有 AP 模式。托管需要在 Pi 上为其 ARM64 内核构建固定的 `mt7601u-ap` DKMS 模块 (`vendor/mt7601u-ap-1.0`)；切勿复制桌面构建的 `.ko`。从桌面：

```bash
./scripts/deploy_pi.sh --host pi-ldn --user PI_USER --install-mt7601u-ap
```
 或在 Pi 上：

```bash
cd ~/pokeldn
./scripts/setup_pi.sh --install-mt7601u-ap --no-networkmanager
```
 这将安装 `dkms` 和 `linux-headers-rpi-v8` 并为每个已安装的内核注册具有匹配标头的模块（APT 可以在重新启动之前安装更新的内核）；如果正在运行的内核没有，它就会停止。重新插入适配器（或重新启动），从 `iw dev` 读取其 PHY，并使用 `--phy phyN
--no-accept-decrypted-ccmp` 运行。 Preflight确认加载的`mt7601u`来自`updates/dkms`并且具有AP和监控模式。
<a id="deploying-changes"></a>
## 部署变更

在桌面上提交并再次运行`./scripts/deploy_pi.sh --host pi-ldn --user PI_USER`。它仅快进代码；当依赖文件或
`vendor/LDN` 更改。手动推送后，Pi 上的 `./scripts/update_pi.sh` 会更新。切勿在 Pi 上编辑跟踪文件；保留 `config/host.local.toml`、密钥和捕获 Pi 本地并被忽略。
