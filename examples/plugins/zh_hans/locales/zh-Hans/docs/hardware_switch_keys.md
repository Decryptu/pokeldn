<a id="installing-switch-keys-on-the-raspberry-pi"></a>
# 在 Raspberry Pi 上安装 Switch 键

`prod.keys` 是您自己的交换机的凭据，实时 LDN 主机需要。切勿提交它、将其粘贴到配置中、将其包含在捕获中或将桌面虚拟环境复制到 Pi；部署永远不会传输它。它位于 `/home/PI_USER/.switch/prod.keys` 中，并且 Pi 忽略了 `config/host.local.toml` 命名该绝对路径，因为主机在 `sudo` 下运行，并且 `~` 不会解析为登录帐户：

```toml
[ldn]
keys_path = "/home/PI_USER/.switch/prod.keys"
```

<a id="install-locally-on-the-pi"></a>
## 在 Pi 上本地安装

以 Pi 登录用户身份运行安装程序（在 `sudo` 下，它会以 `$SUDO_USER` 身份重新启动）。它创造了
`~/.switch` 模式为 `0700`，安装模式为 `0600` 的文件，从不显示它，并在重新运行时保留相同的文件并修复其权限。源必须是绝对路径下的常规文件，可由登录用户读取：

```bash
cd ~/pokeldn
./scripts/install_switch_keys.sh --source /absolute/path/to/prod.keys
```

`--stdin` 通过 SSH 流式传输密钥，无需暂存副本：

```bash
# On the desktop; pi-ldn is your SSH alias.
ssh pi-ldn 'cd ~/pokeldn && ./scripts/install_switch_keys.sh --stdin' < "$HOME/.switch/prod.keys"
```

<a id="scp-through-an-ssh-alias"></a>
## 通过 SSH 别名进行 SCP

暂存于私有目录中，切勿使用共享目录，例如 `/tmp`，然后删除副本（`scp -p` 保留本地模式）：

```bash
# On the desktop.
ssh pi-ldn 'install -d -m 700 "$HOME/.frlg-ldn-provision"'
scp -p "$HOME/.switch/prod.keys" pi-ldn:.frlg-ldn-provision/prod.keys
ssh pi-ldn 'cd ~/pokeldn && \
  ./scripts/install_switch_keys.sh --source "$HOME/.frlg-ldn-provision/prod.keys" && \
  rm -f "$HOME/.frlg-ldn-provision/prod.keys" && \
  rmdir "$HOME/.frlg-ldn-provision"'
```
 验证任一方法：

```bash
ssh pi-ldn 'stat -c "%a %U %n" "$HOME/.switch" "$HOME/.switch/prod.keys"'
# Expected: 700 PI_USER /home/PI_USER/.switch
#           600 PI_USER /home/PI_USER/.switch/prod.keys
```
