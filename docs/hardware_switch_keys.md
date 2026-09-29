---
title: Switch keys on the Pi
parent: Hardware and setup
nav_order: 2
---

# Installing Switch keys on the Raspberry Pi

`prod.keys` is a credential for your own Switch, required by the live LDN host. Never commit it,
paste it into configuration, include it in a capture, or copy a desktop virtual environment to the
Pi; deployment never transfers it. It goes in `/home/PI_USER/.switch/prod.keys`, and the Pi's
ignored `config/host.local.toml` names that absolute path, since the host runs under `sudo` and `~`
would not resolve to the login account:

```toml
[ldn]
keys_path = "/home/PI_USER/.switch/prod.keys"
```

## Install locally on the Pi

Run the installer as the Pi login user (under `sudo` it restarts as `$SUDO_USER`). It creates
`~/.switch` with mode `0700`, installs the file with mode `0600`, never displays it, and on a re-run
keeps an identical file and repairs its permissions. The source must be a regular file at an
absolute path, readable by the login user:

```bash
cd ~/pokeldn
./scripts/install_switch_keys.sh --source /absolute/path/to/prod.keys
```

`--stdin` streams the key over SSH with no staging copy:

```bash
# On the desktop; pi-ldn is your SSH alias.
ssh pi-ldn 'cd ~/pokeldn && ./scripts/install_switch_keys.sh --stdin' < "$HOME/.switch/prod.keys"
```

## SCP through an SSH alias

Stage in a private directory, never a shared one such as `/tmp`, and remove the copy afterwards
(`scp -p` keeps the local mode):

```bash
# On the desktop.
ssh pi-ldn 'install -d -m 700 "$HOME/.frlg-ldn-provision"'
scp -p "$HOME/.switch/prod.keys" pi-ldn:.frlg-ldn-provision/prod.keys
ssh pi-ldn 'cd ~/pokeldn && \
  ./scripts/install_switch_keys.sh --source "$HOME/.frlg-ldn-provision/prod.keys" && \
  rm -f "$HOME/.frlg-ldn-provision/prod.keys" && \
  rmdir "$HOME/.frlg-ldn-provision"'
```

Verify either method:

```bash
ssh pi-ldn 'stat -c "%a %U %n" "$HOME/.switch" "$HOME/.switch/prod.keys"'
# Expected: 700 PI_USER /home/PI_USER/.switch
#           600 PI_USER /home/PI_USER/.switch/prod.keys
```
