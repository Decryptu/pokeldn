package org.pokeldn.usbprobe;

import java.util.Locale;

/** The guided USB setup's states and their guidance (docs/gui.md, Android setup requirements). */
public final class Setup {
    public enum State { NO_DEVICE, UNSUPPORTED_BRIDGE, NEEDS_PERMISSION, PERMISSION_DENIED, CHECKING, HANDSHAKE_FAILED, READY }

    /** Espressif's native USB Serial/JTAG (S3, C3, C6). */
    public static final int ESPRESSIF_VID = 0x303a, ESPRESSIF_PID = 0x1001;
    /** Silicon Labs CP210x, the bridge on most classic ESP32 boards (UsbStream drives it). */
    public static final int CP210X_VID = 0x10c4, CP210X_PID = 0xea60;
    /** USB-to-UART chips on classic ESP32 boards: CP210x, CH34x, FTDI; the app drives only the CP210x. */
    private static final int[] BRIDGE_VIDS = {0x10c4, 0x1a86, 0x0403};

    public static boolean isCp210x(int vid, int pid) { return vid == CP210X_VID && pid == CP210X_PID; }

    public static boolean isBoard(int vid, int pid) {
        return vid == ESPRESSIF_VID && pid == ESPRESSIF_PID || isCp210x(vid, pid);
    }

    public static boolean isBridge(int vid) {
        for (int bridge : BRIDGE_VIDS) if (bridge == vid) return true;
        return false;
    }

    /** handshake: null while untried, "" once the board answered, else the error. */
    public static State decide(boolean board, boolean bridge, boolean permission, boolean denied, String handshake) {
        if (!board) return bridge ? State.UNSUPPORTED_BRIDGE : State.NO_DEVICE;
        if (!permission) return denied ? State.PERMISSION_DENIED : State.NEEDS_PERMISSION;
        if (handshake == null) return State.CHECKING;
        return handshake.isEmpty() ? State.READY : State.HANDSHAKE_FAILED;
    }

    /** Where the phone keeps its USB host switch. Only the OnePlus toggle is measured; others give the searchable name. */
    public static String otgHint(String manufacturer) {
        String maker = manufacturer == null ? "" : manufacturer.toLowerCase(Locale.ROOT);
        if (maker.contains("oneplus"))
            return "OnePlus phones switch USB devices off after a while. Open Settings, search for \"OTG connection\" and turn it on. The board lights up without replugging.";
        if (maker.contains("oppo") || maker.contains("realme"))
            return "This phone may have an \"OTG connection\" switch. Open Settings and search for \"OTG\"; turn it on if it is there.";
        return "Some phones have a USB host or \"OTG\" switch. Open Settings and search for \"OTG\"; turn it on if it is there.";
    }

    public static String title(State state) {
        switch (state) {
            case NO_DEVICE: return "Plug in your radio board";
            case UNSUPPORTED_BRIDGE: return "This USB adapter is not supported";
            case NEEDS_PERMISSION: return "Allow USB access";
            case PERMISSION_DENIED: return "USB access was refused";
            case CHECKING: return "Talking to the board...";
            case HANDSHAKE_FAILED: return "The board did not answer";
            default: return "Board ready";
        }
    }

    public static String guidance(State state, String manufacturer, String detail) {
        switch (state) {
            case NO_DEVICE:
                return "Connect an ESP32-S3, C3 or C6 board by its native USB port, or a classic ESP32 with a CP210x "
                    + "USB chip, to the phone with a data cable (some cables only charge).\n\n" + otgHint(manufacturer);
            case UNSUPPORTED_BRIDGE:
                return "This board talks through a USB-to-serial chip the phone app does not drive (it drives the "
                    + "CP210x only). Use this board with the desktop app.";
            case NEEDS_PERMISSION:
                return "Android asks once whether PokeLDN may use the board. Tap Allow USB access, then OK on Android's prompt.";
            case PERMISSION_DENIED:
                return "Without USB access the app cannot reach the board. Tap Allow USB access and choose OK. "
                    + "Ticking \"Always open\" skips the question next time.";
            case CHECKING:
                return "Asking the board for its firmware version.";
            case HANDSHAKE_FAILED:
                return "Check the cable, then unplug and replug the board. If it keeps failing, flash the PokeLDN firmware "
                    + "from the desktop app.\n\nError: " + detail;
            default:
                return "Firmware " + detail + ".";
        }
    }

    private Setup() {}
}
