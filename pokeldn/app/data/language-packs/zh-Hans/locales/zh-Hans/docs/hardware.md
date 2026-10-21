<a id="hardware-and-setup"></a>
# 硬件和设置

该无线收发设备是 USB 串行上的 ESP32 板，运行 `firmware/esp32`； LDN、Pia 和游戏在主机上以 Python 运行，无需 root 也无需 Wi-Fi 驱动程序。每个头衔都通过它进行交易。 Linux 主机可以直接驱动支持 AP 的 Wi-Fi 卡；这条道路是遗产。
<a id="pages"></a>
## 相关页面

- [ESP32 无线收发设备](hardware_esp32.md)：开发板、固件、串口协议和测量。
- [Switch 密钥](hardware_switch_keys.md)：安全安装 `prod.keys`。
- [适配器](hardware_adapters.md)：Linux Wi-Fi 网卡、配置和故障模式。
- [手柄开发板](hardware_pad.md)：通过蓝牙 LE 控制的 ESP32-S3 有线手柄，或通过 USB 串口控制、与 Switch 配对为 Pro 手柄的经典 ESP32。
- [Raspberry Pi 主机](hardware_raspberry_pi.md)：Linux 部署和受监督的神秘礼物运行程序。