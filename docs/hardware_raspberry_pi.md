---
title: Raspberry Pi host
parent: Hardware and setup
nav_order: 4
---

# Raspberry Pi 4 Mystery Gift host

A 64-bit Raspberry Pi 4 with the TP-Link Archer T3U / AC1300 (`2357:012d`, `rtw88_8822bu`) hosts
Mystery Gift. The patched LDN implementation is `vendor/LDN`; never install the unpatched PyPI
package on the Pi. The adapter's kernel setup is in [Adapters](hardware_adapters.md).

Deployment pushes committed Git objects through an SSH alias to a bare repository on the Pi, with
no GitHub, no `rsync` and no ignored files (reference repositories, `.venv`, captures, Pokemon files,
Switch keys).

## First deployment

On the desktop, with the SSH alias and the Pi login user:

```bash
git add -A
git commit -m "Prepare Raspberry Pi deployment"
./scripts/deploy_pi.sh --host pi-ldn --user PI_USER
```

`deploy_pi.sh` refuses a dirty desktop checkout, runs the configuration and documentation tests,
creates `/home/PI_USER/repos/pokeldn.git` if needed, pushes the current commit to its `deploy`
branch, and creates or fast-forwards `/home/PI_USER/pokeldn`. It never force-resets and rejects a Pi
checkout with uncommitted files. If the SSH alias already names the remote user, give the paths:

```bash
./scripts/deploy_pi.sh --host pi-ldn \
  --path /home/PI_USER/pokeldn \
  --repo /home/PI_USER/repos/pokeldn.git
```

Then bootstrap the Pi:

```bash
ssh pi-ldn
cd ~/pokeldn
./scripts/setup_pi.sh
```

`setup_pi.sh` needs 64-bit Raspberry Pi OS (`aarch64`) and Python 3.11 or newer (Bookworm 3.11,
Trixie 3.13). It builds the virtual environment from `requirements.txt`, installs the system tools
(`--no-apt` skips them) and excludes `ldnclient`, `ldn`, `ldn-mon` and `ldn-tap` from NetworkManager
(`--no-networkmanager` skips it). Keep SSH on Ethernet or the built-in Wi-Fi: hosting takes the
TP-Link adapter exclusively.

## Configuration and Switch keys

The tracked `config/host.toml` is the TP-Link live profile:

```toml
[host]
live = true
skip_encryption = true
accept_decrypted_ccmp = true

[ldn]
phy = "auto"
```

The ignored `config/host.local.toml` holds the absolute key path (the host runs under `sudo`); how to
install `prod.keys` is in [Switch keys on the Pi](hardware_switch_keys.md).

## Verify and run

With the TP-Link adapter plugged in:

```bash
cd ~/pokeldn
./scripts/preflight_pi.sh
./scripts/run_mystery_gift.sh
```

Preflight is read-only. It checks Python and the vendored LDN package, loads `config/host.toml` and
the optional `config/host.local.toml`, checks the TP-Link USB id and `rtw88_8822bu`, AP and monitor
support, the NetworkManager exclusion and that the key file is mode `0600`. It rejects a TP-Link
invocation that disables `skip_encryption` or `accept_decrypted_ccmp`, arguments passed through
`run_mystery_gift.sh` included. It adds Debian's `sbin` paths itself, so it behaves the same in a
shell and through a one-line SSH command.

`run_mystery_gift.sh` runs preflight once, then supervises short-lived root host processes, each with
a random TID/SID, restarted after a delivery, a failed attempt, or five minutes with no Switch join or
Pia/RFU traffic. Ctrl-C once stops it. It always passes `--end-on-success` (end after the
post-delivery close) and `--idle-timeout 300` (end after that many seconds without Switch traffic)
and owns `--id`, so a saved `--id` cannot reuse an old identity. Every other `bin/frlg_mg_host.py`
option is forwarded; `--help` and `--print-effective-config` need neither preflight nor root.

Each joined attempt is appended to the ignored daily ledger `logs/mystery-gift-attempts-YYYY-MM-DD.csv`
with columns `attempt`, `received_result` (`true` only when a Wonder Card or Stamp was sent), `time`,
`trainer_name`, `trainer_ot` (the name and five-digit trainer ID from the Switch's LinkPlayer block,
blank if the attempt failed before it). `bin/frlg_mg_host.py --attempt-log-dir logs` writes the same
ledger.

Event controls: `--gift`, `--flag-id`, `--verbose`, `--capture`, `--ot`, `--version`, `--id`.
`--client-ready-idle-frames N` is a timing diagnostic for hardware tests; leave it unset otherwise.
`--make-artifact` writes a deterministic `.ram.lst` listing under `artifacts/` (`--artifact-dir DIR`
redirects it): the compiled RAM script bytes, decoded instructions, checksums, branch and message
destinations, and the delivery-stage summary; `--no-make-artifact` disables it in a saved command.

```bash
./scripts/run_mystery_gift.sh --gift solrock-stamp --client-ready-idle-frames 45 \
  --capture solrock-45.jsonl
./scripts/run_mystery_gift.sh --gift worlds-xp --make-artifact
```

Leave `--phy`, `--adapter`, `--skip-encryption` and `--accept-decrypted-ccmp` at the TP-Link defaults
unless diagnosing other hardware. For the ALFA `mt76x0u`, pass its current PHY (`iw dev`; it changes
after a replug) and `--no-accept-decrypted-ccmp`; preflight then checks that PHY's AP and monitor
modes and the `mt76x0u` CCMP profile.

### MT7601U adapter with the custom AP driver

The stock `mt7601u` driver has no AP mode. Hosting needs the pinned `mt7601u-ap` DKMS module
(`vendor/mt7601u-ap-1.0`) built on the Pi for its ARM64 kernel; never copy a desktop-built `.ko`.
From the desktop:

```bash
./scripts/deploy_pi.sh --host pi-ldn --user PI_USER --install-mt7601u-ap
```

or on the Pi:

```bash
cd ~/pokeldn
./scripts/setup_pi.sh --install-mt7601u-ap --no-networkmanager
```

This installs `dkms` and `linux-headers-rpi-v8` and registers the module for every installed kernel
with matching headers (APT can install a newer kernel before the reboot); it stops if the running
kernel has none. Replug the adapter (or reboot), read its PHY from `iw dev`, and run with `--phy phyN
--no-accept-decrypted-ccmp`. Preflight confirms the loaded `mt7601u` comes from `updates/dkms` and
has AP and monitor mode.

## Deploying changes

Commit on the desktop and run `./scripts/deploy_pi.sh --host pi-ldn --user PI_USER` again. It
fast-forwards code only; the Pi refreshes its virtual environment when dependency files or
`vendor/LDN` change. `./scripts/update_pi.sh` on the Pi updates after a push by hand. Never edit
tracked files on the Pi; keep `config/host.local.toml`, keys and captures Pi-local and ignored.
