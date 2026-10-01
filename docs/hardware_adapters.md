---
title: Adapters
parent: Hardware and setup
nav_order: 3
---

# Wi-Fi adapters

A Linux host can drive an AP-capable Wi-Fi card directly, as root, in place of the
[ESP32 radio](hardware_esp32.md). This path is legacy and no longer developed.

| symptom | cause |
|---|---|
| a hypervisor-style USB disconnect at AP start | the USB mode switch (below) |
| a silent host | `accept_decrypted_ccmp` unset |
| `failed to get tx report from firmware` in `dmesg` | the host's own teardown |

## Tested cards

| model | type | driver | result on a tested host |
|---|---|---|---|
| TP-Link Archer T3U (`2357:012d`) | external USB | `rtw88_8822bu` | reliable; the reference adapter |
| ALFA AWUS036ACHM | external USB | `mt76x0u` | reliable |
| Realtek RTL8821CE | internal PCIe | `rtw88_8821ce` | reliable |
| AMD RZ616 | internal M.2 | `mt7921e` | about half the speed, sometimes deadlocks before exiting |
| MT7601U | external USB | `mt7601u` | the stock driver has no AP mode; needs the pinned `mt7601u-ap` DKMS module ([Raspberry Pi host](hardware_raspberry_pi.md)) |
| Intel AX200 | internal M.2 | `iwlwifi` | fails: cannot be assigned an IP |
| Atheros AR9271 | external USB | `ath9k_htc` | fails: usually cannot be assigned an IP |

## Host modes

`--skip-encryption` skips LDN's Python CCMP step so mac80211 or the hardware applies CCMP once;
traffic stays encrypted over the air. The Archer T3U (`skip_encryption = true` in `config/host.toml`)
and the ALFA AWUS036ACHM need it.

`--accept-decrypted-ccmp` is for monitor drivers that keep the CCMP header and MIC around
hardware-decrypted plaintext, as the Archer T3U's `rtw88_8822bu` does; it strips the MIC before
forwarding the plaintext to `ldn-tap`. Keep it off for the ALFA, which delivers standard frames.

| adapter | host configuration |
|---|---|
| TP-Link Archer T3U | the tracked `config/host.toml` profile; no Wi-Fi flags |
| ALFA AWUS036ACHM | `--phy phyN --skip-encryption --no-accept-decrypted-ccmp` |

`phy = "auto"` resolves only a single `rtw88_8822bu` USB `2357:012d` device and fails on none or
several. An explicit `--phy phyN` always wins; keep it for one-off debugging, since the number
changes on every re-enumeration. Startup prints the detected profile, the transmit and receive
modes, and a warning if the flags differ from the proven profile.

## The TP-Link Archer T3U

`rtw88_8822bu` is mainline since kernel 6.11 and lists this USB id. Confirm the kernel binds it:

```bash
modinfo rtw88_8822bu | grep -i 2357
lsusb | grep -i 2357
iw dev
```

### Keep NetworkManager off the adapter itself

NetworkManager claims the adapter's hotplugged interface (`wlx...`) and starts a background scan;
the channel change takes the radio down shortly after the interface appears (11 s measured):

```text
rtw88_8822bu 3-1:1.0: write register 0x81c failed with -71
usb 3-1: USB disconnect, device number 2
```

Exclude the adapter and the LDN interfaces:

```text
# /etc/NetworkManager/conf.d/zz-ldn-unmanaged.conf
[keyfile]
unmanaged-devices=interface-name:ldnclient;interface-name:ldn;interface-name:ldn-mon;interface-name:ldn-tap;interface-name:wlx*;interface-name:wlan*
```

The file must sort last (`zz-`): some distributions ship a later file setting
`unmanaged-devices=none`. Reload NetworkManager; `nmcli device status` must show the adapter
`unmanaged`, and `NetworkManager --print-config | grep unmanaged` the list. Without `ldnclient` in
it, NetworkManager grabs the interface a join creates, points wpa_supplicant at it, and the join
fails with `[Errno 114] Match already configured`.

### Disable the driver's USB 3 mode switch

`rtw88_usb` defaults to `switch_usb_mode=Y`, which re-enumerates the adapter into USB 3 mode after
the driver loads. A hypervisor passing the device through sees a disconnect, the LDN interfaces
vanish, and the host dies early in hosting (about 1 s measured) with no preceding driver error:

```text
RuntimeError: 802.11 beacon injector stopped: [Errno 100] Network is down
```

The parameter's own description notes that USB 3 mode can interfere with 2.4 GHz, LDN's band.

```text
# /etc/modprobe.d/rtw88-ldn.conf
options rtw88_usb switch_usb_mode=N
options rtw88_core disable_lps_deep=Y
```

Replug the adapter afterwards: it stays in USB 3 mode until it loses power. It then attaches once,
at high speed (with the switch on, it enumerates twice, high speed then SuperSpeed):

```bash
cat /sys/bus/usb/devices/*/speed     # 480, not 5000
cat /sys/bus/usb/devices/*/version   # 2.10, not 3.00
```

### Bring the adapter interface down before a run

An up managed interface holds the radio's channel. `transport.free_radio()` lowers it; a bare
`tools/ldn/ldn_scan.py` does not:

```text
OSError: [Errno 16] Device or resource busy
```

```bash
sudo ip link set wlxXXXXXXXXXXXX down
```

A kill script that brings the base interface back up makes the next launch fail with that error.
Anything that raises it for a kernel `iw scan` must lower it again before handing over.

### Verify

`./scripts/preflight_pi.sh` runs on any Linux host.
