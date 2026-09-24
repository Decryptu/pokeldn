---
title: Hardware and setup
nav_order: 9
has_children: true
---

# Hardware and setup

The radio is an ESP32 board on USB serial running `firmware/esp32`; LDN, Pia and the games run in
Python on the host, which needs no root and no Wi-Fi driver. Every title has completed a trade
through it. A Linux host can instead drive an AP-capable Wi-Fi card directly; that path is no
longer developed.

## Pages

- [ESP32 radio](hardware_esp32.md): the board, its firmware, serial protocol and measurements.
- [Switch keys](hardware_switch_keys.md): installing `prod.keys` safely.
- [Adapters](hardware_adapters.md): the Linux Wi-Fi cards, their configuration and failure modes.
- [Raspberry Pi host](hardware_raspberry_pi.md): the Linux deployment and the supervised Mystery Gift
  runner.
